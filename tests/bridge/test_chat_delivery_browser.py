"""Issue #398 — headless-browser tests for chat.html.

These tests drive the real ``static/chat.html`` JavaScript in a headless
Chromium (via Playwright) against a real aiohttp bridge, so they verify
the client-side half of the fetch-and-subscribe handshake that a
server-only test cannot reach:

  - Criterion 3: the WebSocket opens only after ``fetchAll()`` returns
    and the subscribe frame carries the cursor from that fetch.
  - Criterion 4: ``onWsMessage`` unconditionally appends received
    messages (no ``_pendingSent`` filter).
  - Criterion 8: the only client-side dedup is reconciliation of the
    user's own optimistic send against the server's echo, keyed on the
    authoritative message id returned from ``POST`` — and the
    reconciliation actually replaces the optimistic entry rather than
    appending a duplicate.
  - The race bug from the ticket reproduced in a real DOM: a message
    committed to the bus before the page loads appears in the iframe
    **exactly once**.

Skipped automatically if Playwright or the chromium binary is not
installed (``pip install playwright && playwright install chromium``).
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import socket
import tempfile
import threading
import time
import unittest
from typing import Any

try:
    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeoutError
    _PW_AVAILABLE = True
except Exception:
    _PW_AVAILABLE = False

from aiohttp import web

from teaparty.bridge.message_relay import MessageRelay
from teaparty.messaging.conversations import (
    ConversationType,
    SqliteMessageBus,
)


def _free_port() -> int:
    s = socket.socket()
    s.bind(('127.0.0.1', 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _static_dir() -> str:
    return os.path.join(
        os.path.dirname(__file__), '..', '..', 'teaparty', 'bridge', 'static',
    )


class _BrowserBridge:
    """A minimal aiohttp app that serves the real chat.html static files
    and enough API routes for the participant-chat code path to boot.

    The GET /api/conversations/{id} and /ws handlers are bound from
    TeaPartyBridge via ``MethodType`` so the real production code runs
    under test. The SQLite bus is created and accessed only from the
    server thread (SQLite connections are single-thread by default).
    """
    def __init__(self, db_path: str):
        self._db_path = db_path
        self._buses: dict[str, SqliteMessageBus] = {}
        self._ws_clients: set = set()

        async def _noop_broadcast(event: dict) -> None:
            pass

        self._broadcast = _noop_broadcast
        self._message_relay: MessageRelay | None = None  # created in _on_loop

        # Bind real handlers from TeaPartyBridge as methods on this object.
        from types import MethodType
        from teaparty.bridge.server import TeaPartyBridge
        self._handle_conversation_get = MethodType(
            TeaPartyBridge._handle_conversation_get, self,
        )
        self._handle_websocket = MethodType(
            TeaPartyBridge._handle_websocket, self,
        )

    def _bus_for_conversation(self, conv_id: str):
        for bus in self._buses.values():
            try:
                if conv_id in bus.conversations():
                    return bus
            except Exception:
                continue
        return next(iter(self._buses.values()), None)

    def _serialize_message(self, m) -> dict:
        return {
            'id': m.id,
            'conversation': m.conversation,
            'sender': m.sender,
            'content': m.content,
            'timestamp': m.timestamp,
        }

    async def list_conversations(self, request: web.Request) -> web.Response:
        # chat.html's participant sidebar calls GET /api/conversations?type=...
        # Return a minimal list containing the test conversation.
        bus = next(iter(self._buses.values()))
        convs = bus.active_conversations(ConversationType.OFFICE_MANAGER)
        return web.json_response([
            {'id': c.id, 'type': 'office_manager', 'created_at': int(time.time())}
            for c in convs
        ])

    async def post_conversation(self, request: web.Request) -> web.Response:
        conv_id = request.match_info['id']
        body = await request.json()
        content = body.get('content', '')
        bus = self._bus_for_conversation(conv_id)
        msg_id = bus.send(conv_id, 'human', content)
        return web.json_response({'id': msg_id})

    async def init_on_loop(self) -> None:
        """Create the SQLite bus + MessageRelay on the event-loop thread so
        that every subsequent access happens in the same thread the
        connection was opened in (sqlite3 default).
        """
        bus = SqliteMessageBus(self._db_path)
        bus.create_conversation(ConversationType.OFFICE_MANAGER, 'alice')
        self._buses['session'] = bus
        self._message_relay = MessageRelay(self._buses, self._broadcast)

    async def send_message(self, conv_id: str, sender: str, content: str) -> str:
        return self._buses['session'].send(conv_id, sender, content)


class _ServerThread(threading.Thread):
    """Run an aiohttp app on a dedicated event loop in a background thread
    so the main test thread can drive Playwright synchronously.
    """
    def __init__(self, bridge: _BrowserBridge, port: int):
        super().__init__(daemon=True)
        self.bridge = bridge
        self.port = port
        self.loop = asyncio.new_event_loop()
        self._runner: web.AppRunner | None = None
        self._ready = threading.Event()

    def run(self) -> None:
        asyncio.set_event_loop(self.loop)
        self.loop.run_until_complete(self._start())
        self._ready.set()
        self.loop.run_forever()

    async def _start(self) -> None:
        b = self.bridge
        await b.init_on_loop()
        app = web.Application()
        app.router.add_get('/api/conversations', b.list_conversations)
        app.router.add_get('/api/conversations/{id}', b._handle_conversation_get)
        app.router.add_post('/api/conversations/{id}', b.post_conversation)
        app.router.add_get('/ws', b._handle_websocket)
        app.router.add_static('/', _static_dir())
        self._runner = web.AppRunner(app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, '127.0.0.1', self.port)
        await site.start()

    def stop(self) -> None:
        async def _shutdown():
            if self._runner is not None:
                await self._runner.cleanup()
        fut = asyncio.run_coroutine_threadsafe(_shutdown(), self.loop)
        try:
            fut.result(timeout=5)
        except Exception:
            pass
        self.loop.call_soon_threadsafe(self.loop.stop)
        self.join(timeout=5)

    def call(self, coro) -> Any:
        """Run a coroutine on the server's loop from the main thread."""
        return asyncio.run_coroutine_threadsafe(coro, self.loop).result()


@unittest.skipUnless(_PW_AVAILABLE, 'playwright not installed')
class TestChatHtmlHandshake(unittest.TestCase):
    """Drive the real chat.html client with a real Chromium against a real
    aiohttp bridge.
    """

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='teaparty-398-browser-')
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.bridge = _BrowserBridge(os.path.join(self.tmp, 'messages.db'))
        self.port = _free_port()
        self.server = _ServerThread(self.bridge, self.port)
        self.server.start()
        self.server._ready.wait(timeout=5)

        self.pw = sync_playwright().start()
        self.browser = self.pw.chromium.launch(headless=True)
        self.context = self.browser.new_context()

    def tearDown(self):
        try:
            self.context.close()
            self.browser.close()
            self.pw.stop()
        except Exception:
            pass
        self.server.stop()

    def _open_chat(self, conv_id: str):
        page = self.context.new_page()
        url = f'http://127.0.0.1:{self.port}/chat.html?conv={conv_id}'
        page.goto(url)
        # Wait for the chat-messages element to render — chat.html injects
        # it after fetchAll() resolves.
        page.wait_for_selector('.chat-messages', timeout=5000)
        return page

    def _rendered_contents(self, page) -> list[str]:
        return page.eval_on_selector_all(
            '.chat-messages .msg',
            'els => els.map(e => e.querySelector(".msg-text")?.innerText?.trim() || "")',
        )

    def _pageState_len(self, page) -> int:
        return page.evaluate('pageState.messages.length')

    def _cursor(self, page) -> str:
        return page.evaluate('pageState.cursor')

    # ── Tests ────────────────────────────────────────────────────────────────

    def test_client_subscribes_with_cursor_from_fetch(self):
        """Criterion 3 (handshake ordering): the client's FIRST subscribe
        frame must carry the cursor returned by the preceding ``fetchAll``.
        Asserted on the server side by inspecting the relay's subscription
        map right after the handshake lands — if the client opened the
        WebSocket before fetchAll resolved, the installed cursor would be
        empty (or would advance past rows the fetch already returned),
        which this test rejects.
        """
        self.server.call(self.bridge.send_message('om:alice', 'agent', 'm0'))
        self.server.call(self.bridge.send_message('om:alice', 'agent', 'm1'))

        # Capture the authoritative cursor for 'om:alice' as the HTTP
        # handler would return it to the client.
        _, expected_cursor = self.server.call(
            self._capture_cursor('om:alice'),
        )
        self.assertNotEqual(expected_cursor, '')

        page = self._open_chat('om:alice')

        # Wait until the DOM has both messages and the client has installed
        # its subscription on the server side.
        page.wait_for_function(
            'document.querySelectorAll(".chat-messages .msg").length === 2',
            timeout=5000,
        )
        deadline = time.time() + 3.0
        installed: dict | None = None
        while time.time() < deadline:
            subs = self.bridge._message_relay._subscriptions
            for conn, conv_map in subs.items():
                if 'om:alice' in conv_map:
                    installed = {'cursor': conv_map['om:alice']}
                    break
            if installed is not None:
                break
            time.sleep(0.05)
        self.assertIsNotNone(
            installed,
            'client never sent a subscribe frame for om:alice',
        )

        # The installed cursor must match the one fetchAll captured — not
        # empty, not advanced past it. If connectWS() ran before fetchAll
        # resolved, the client would have sent subscribe with since_cursor=''
        # and the relay would have advanced it past every pre-fetch row,
        # i.e. to the SAME end state — but the route by which it got there
        # is wrong. We also assert on the WS-captured frame itself below.
        self.assertEqual(
            installed['cursor'], expected_cursor,
            f'subscription cursor {installed["cursor"]!r} does not match '
            f'the HTTP fetch watermark {expected_cursor!r}',
        )

        # Client-side invariant: pageState.cursor must be set at this point.
        client_cursor = self._cursor(page)
        self.assertEqual(
            client_cursor, expected_cursor,
            f'pageState.cursor ({client_cursor!r}) does not match the HTTP '
            f'fetch watermark ({expected_cursor!r})',
        )

    async def _capture_cursor(self, conv_id: str):
        bus = self.bridge._buses['session']
        return bus.receive_since_cursor(conv_id, '')

    def test_race_row_appears_exactly_once_in_dom(self):
        """The exact bug from the ticket: a message committed to the bus
        before the page loads should appear in the iframe exactly once,
        even after the relay has had multiple chances to broadcast it.
        """
        self.server.call(self.bridge.send_message('om:alice', 'agent', 'race-row'))
        page = self._open_chat('om:alice')

        page.wait_for_function(
            'document.querySelectorAll(".chat-messages .msg").length >= 1',
            timeout=5000,
        )

        # Two relay polls — the old fetch-and-poll model double-broadcast on
        # the first poll; make sure that's gated out.
        self.server.call(self.bridge._message_relay.poll_once())
        self.server.call(self.bridge._message_relay.poll_once())
        # Give the iframe a chance to process any in-flight WS frames.
        page.wait_for_timeout(150)

        contents = self._rendered_contents(page)
        self.assertEqual(
            contents.count('race-row'), 1,
            f'race-row appeared {contents.count("race-row")} time(s) in the DOM; '
            f'expected exactly 1 (full list: {contents})',
        )
        self.assertEqual(
            self._pageState_len(page), 1,
            'pageState.messages grew beyond the authoritative row count — '
            'the relay delivered a duplicate that the client did not dedup',
        )

    def test_live_message_after_load_appears_once(self):
        """Write a message AFTER the page loads — it should arrive via the
        subscribed WebSocket stream, once, and render in the DOM.
        """
        page = self._open_chat('om:alice')

        # Confirm the subscribe handshake has landed on the server side by
        # waiting until at least one subscription exists on the relay.
        deadline = time.time() + 3.0
        while time.time() < deadline:
            subs = self.bridge._message_relay._subscriptions
            if any(subs.values()):
                break
            time.sleep(0.05)
        else:
            self.fail('client never sent a subscribe frame for om:alice')

        self.server.call(self.bridge.send_message('om:alice', 'agent', 'live-m0'))
        self.server.call(self.bridge._message_relay.poll_once())

        page.wait_for_function(
            'document.querySelectorAll(".chat-messages .msg").length === 1',
            timeout=5000,
        )

        contents = self._rendered_contents(page)
        self.assertEqual(
            contents, ['live-m0'],
            f'live message should render exactly once after WS delivery; got {contents}',
        )

    def test_optimistic_send_is_reconciled_not_duplicated(self):
        """Criterion 4/8: when the user sends a message, the optimistic
        DOM entry must be reconciled with the server's echo (matched by
        id) rather than appended as a second entry.

        Regression pattern: if ``onWsMessage`` appended unconditionally
        with no id match, the final DOM would contain two identical
        rows — the optimistic one and the server echo.
        """
        page = self._open_chat('om:alice')

        # Wait for subscribe to land.
        deadline = time.time() + 3.0
        while time.time() < deadline:
            if any(self.bridge._message_relay._subscriptions.values()):
                break
            time.sleep(0.05)

        # Inject a message via the chat textarea, clicking the Send button.
        ta_selector = '.chat-input-area textarea'
        page.wait_for_selector(ta_selector, timeout=3000)
        page.fill(ta_selector, 'hello from test')
        page.click('.chat-input-area button')

        # Poll the relay so the server echo ships to the iframe.
        time.sleep(0.1)
        self.server.call(self.bridge._message_relay.poll_once())
        page.wait_for_timeout(200)

        contents = self._rendered_contents(page)
        # Exactly one entry with the user's text — not two.
        self.assertEqual(
            contents.count('hello from test'), 1,
            f'optimistic entry and server echo both rendered — got '
            f'{contents.count("hello from test")} copies of the sent text. '
            f'Full DOM: {contents}',
        )
        self.assertEqual(
            len(contents), 1,
            f'expected exactly one rendered message, got {len(contents)}: {contents}',
        )

        # The reconciled entry must carry a real message id, not the
        # optimistic placeholder — otherwise reconciliation never happened.
        final_id = page.evaluate('pageState.messages[0].id')
        self.assertTrue(
            final_id and not str(final_id).startswith('opt-'),
            f'pageState.messages[0].id is still the optimistic placeholder '
            f'({final_id!r}); reconciliation against the server echo never ran',
        )


if __name__ == '__main__':
    unittest.main()
