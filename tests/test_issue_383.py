"""Tests for Issue #383: Bus dispatch — conversation lifecycle, originator-owned open/close.

Acceptance criteria:
SC1. Originator can open a conversation with any entity it has routing permission to reach.
SC2. Conversation has explicit open/closed state (conversation_status); only originator may close.
SC3. Follow-up Send to an open conversation resumes the recipient's prior session via
     resume_fn rather than spawning a fresh session via spawn_fn.
SC4. Human interjection via chat dialog (interjection socket) triggers --resume on the
     active session for that conversation — no new routing logic required.
SC5. Multiple parallel open conversations per agent work independently (each context_id
     has its own session_id and conversation_status).
SC6. Reply closes the session turn (context status='closed') but leaves
     conversation_status='open'.
SC7. Dispatch rejects follow-ups to a closed conversation at the routing layer.
SC8. Specification-based tests cover: follow-up routing, interjection via chat dialog,
     close semantics, parallel conversations per agent.
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import tempfile
import unittest


def _run(coro):
    return asyncio.run(coro)


def _make_bus(tmpdir: str):
    from orchestrator.messaging import SqliteMessageBus
    return SqliteMessageBus(os.path.join(tmpdir, 'bus.db'))


# ── SC2: agent_contexts has conversation_status column ───────────────────────


class TestConversationStatusSchema(unittest.TestCase):
    """SC2: agent_contexts must have a conversation_status column defaulting to 'open'."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.bus = _make_bus(self.tmpdir)

    def tearDown(self):
        self.bus.close()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_new_context_has_open_conversation_status(self):
        """SC2: newly created agent context must have conversation_status='open'."""
        self.bus.create_agent_context('ctx-1', 'proj/lead', 'proj/worker')
        ctx = self.bus.get_agent_context('ctx-1')
        self.assertIsNotNone(ctx)
        self.assertEqual(
            ctx['conversation_status'],
            'open',
            'New agent context must have conversation_status=open',
        )

    def test_close_agent_conversation_sets_closed_status(self):
        """SC2: close_agent_conversation must set conversation_status='closed'."""
        self.bus.create_agent_context('ctx-2', 'proj/lead', 'proj/worker')
        self.bus.close_agent_conversation('ctx-2')
        ctx = self.bus.get_agent_context('ctx-2')
        self.assertEqual(
            ctx['conversation_status'],
            'closed',
            'close_agent_conversation must set conversation_status=closed',
        )

    def test_context_with_parent_also_starts_open(self):
        """SC2: child context created via create_agent_context_and_increment_parent
        must also have conversation_status='open'."""
        self.bus.create_agent_context('ctx-parent', 'proj/lead', 'proj/worker')
        self.bus.create_agent_context_and_increment_parent(
            'ctx-child',
            initiator_agent_id='proj/worker',
            recipient_agent_id='proj/sub',
            parent_context_id='ctx-parent',
        )
        ctx = self.bus.get_agent_context('ctx-child')
        self.assertEqual(
            ctx['conversation_status'],
            'open',
            'Child context must also start with conversation_status=open',
        )

    def test_existing_db_migration_adds_conversation_status(self):
        """SC2: existing DBs without conversation_status must be migrated."""
        import sqlite3
        db_path = os.path.join(self.tmpdir, 'old.db')
        # Create a DB with the old schema (no conversation_status column)
        conn = sqlite3.connect(db_path)
        conn.execute('''
            CREATE TABLE agent_contexts (
                context_id TEXT PRIMARY KEY,
                initiator_agent_id TEXT NOT NULL,
                recipient_agent_id TEXT NOT NULL,
                parent_context_id TEXT NOT NULL DEFAULT '',
                session_id TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'open',
                pending_count INTEGER NOT NULL DEFAULT 0,
                created_at REAL NOT NULL
            )
        ''')
        conn.execute(
            "INSERT INTO agent_contexts "
            "(context_id, initiator_agent_id, recipient_agent_id, created_at) "
            "VALUES (?, ?, ?, ?)",
            ('ctx-old', 'proj/lead', 'proj/worker', 1.0),
        )
        conn.commit()
        conn.close()

        # Opening the bus should migrate and add conversation_status
        from orchestrator.messaging import SqliteMessageBus
        bus = SqliteMessageBus(db_path)
        try:
            ctx = bus.get_agent_context('ctx-old')
            self.assertIsNotNone(ctx)
            self.assertIn(
                'conversation_status',
                ctx,
                'Migrated DB must expose conversation_status in get_agent_context',
            )
            self.assertEqual(
                ctx['conversation_status'],
                'open',
                'Migrated existing rows must default conversation_status to open',
            )
        finally:
            bus.close()


# ── SC6: Reply closes session turn but leaves conversation open ───────────────


class TestReplyClosesSessionNotConversation(unittest.TestCase):
    """SC6: Reply must close the session turn (agent_context.status='closed')
    but leave conversation_status='open'."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.bus_db = os.path.join(self.tmpdir, 'bus.db')

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _setup_parent_and_worker(self, parent_ctx, parent_session, worker_ctx):
        bus = _make_bus(self.tmpdir)
        bus.create_agent_context(parent_ctx, 'proj/lead', 'proj/worker')
        bus.set_agent_context_session_id(parent_ctx, parent_session)
        bus.create_agent_context_and_increment_parent(
            worker_ctx,
            initiator_agent_id='proj/worker',
            recipient_agent_id='proj/sub',
            parent_context_id=parent_ctx,
        )
        bus.set_agent_context_session_id(worker_ctx, 'worker-session')
        bus.close()

    def test_reply_closes_context_but_leaves_conversation_open(self):
        """SC6: after Reply, agent_context.status='closed' but
        conversation_status='open'."""
        from orchestrator.bus_event_listener import BusEventListener

        PARENT_CTX = 'agent:proj/lead:proj/worker:reply-test-1'
        WORKER_CTX = 'agent:proj/worker:proj/sub:reply-test-2'
        PARENT_SESSION = 'lead-sess-reply'

        self._setup_parent_and_worker(PARENT_CTX, PARENT_SESSION, WORKER_CTX)

        listener = BusEventListener(
            bus_db_path=self.bus_db,
            current_context_id=WORKER_CTX,
        )

        async def run():
            send_path, reply_path, close_path = await listener.start()
            try:
                reader, writer = await asyncio.open_unix_connection(reply_path)
                writer.write(
                    json.dumps({'type': 'reply', 'message': 'done'}).encode() + b'\n'
                )
                await writer.drain()
                await reader.readline()
                writer.close()
                await asyncio.sleep(0.05)
            finally:
                await listener.stop()

        _run(run())

        bus = _make_bus(self.tmpdir)
        try:
            # Worker context: session should be closed
            worker_ctx = bus.get_agent_context(WORKER_CTX)
            self.assertEqual(
                worker_ctx['status'],
                'closed',
                'Reply must close the agent context session (status=closed)',
            )
            # But conversation must remain open
            self.assertEqual(
                worker_ctx['conversation_status'],
                'open',
                'Reply must NOT close the conversation (conversation_status must stay open)',
            )
        finally:
            bus.close()


# ── SC3: Follow-up Send resumes prior session via resume_fn ──────────────────


class TestFollowUpSendResumesSession(unittest.TestCase):
    """SC3: Send with existing context_id for an open conversation must call
    resume_fn (--resume) instead of spawn_fn (fresh spawn)."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.bus_db = os.path.join(self.tmpdir, 'bus.db')
        self.spawn_calls = []
        self.resume_calls = []

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    async def _capture_spawn(self, member: str, composite: str, context_id: str) -> tuple[str, str]:
        self.spawn_calls.append({'member': member, 'context_id': context_id})
        return ('new-session-id', '')

    async def _capture_resume(self, member: str, composite: str, session_id: str, context_id: str) -> str:
        self.resume_calls.append({'member': member, 'session_id': session_id})
        return session_id

    def _setup_open_conversation(self, context_id, session_id, member='proj/worker'):
        bus = _make_bus(self.tmpdir)
        bus.create_agent_context(context_id, 'proj/lead', member)
        bus.set_agent_context_session_id(context_id, session_id)
        # Simulate Reply having been called (session closed, conversation open)
        bus.close_agent_context(context_id)
        bus.close()

    def test_send_with_open_context_calls_resume_fn_not_spawn_fn(self):
        """SC3: Send with existing context_id and open conversation must call resume_fn."""
        from orchestrator.bus_event_listener import BusEventListener

        CTX_ID = 'agent:proj/lead:proj/worker:followup-1'
        PRIOR_SESSION = 'session-from-prior-turn'

        self._setup_open_conversation(CTX_ID, PRIOR_SESSION)

        listener = BusEventListener(
            bus_db_path=self.bus_db,
            spawn_fn=self._capture_spawn,
            resume_fn=self._capture_resume,
            initiator_agent_id='proj/lead',
        )

        async def run():
            send_path, reply_path, close_path = await listener.start()
            try:
                reader, writer = await asyncio.open_unix_connection(send_path)
                writer.write(
                    json.dumps({
                        'type': 'send',
                        'member': 'proj/worker',
                        'composite': 'follow-up message',
                        'context_id': CTX_ID,
                    }).encode() + b'\n'
                )
                await writer.drain()
                await reader.readline()
                writer.close()
                await asyncio.sleep(0.1)
            finally:
                await listener.stop()

        _run(run())

        self.assertEqual(
            len(self.spawn_calls),
            0,
            'spawn_fn must NOT be called for a follow-up to an open conversation',
        )
        self.assertEqual(
            len(self.resume_calls),
            1,
            'resume_fn must be called for a follow-up to an open conversation',
        )
        self.assertEqual(
            self.resume_calls[0]['session_id'],
            PRIOR_SESSION,
            f"resume_fn must receive the prior session_id '{PRIOR_SESSION}'",
        )

    def test_send_without_context_id_still_uses_spawn_fn(self):
        """SC1: Send without context_id (new conversation) must still call spawn_fn."""
        from orchestrator.bus_event_listener import BusEventListener

        listener = BusEventListener(
            bus_db_path=self.bus_db,
            spawn_fn=self._capture_spawn,
            resume_fn=self._capture_resume,
            initiator_agent_id='proj/lead',
        )

        async def run():
            send_path, reply_path, close_path = await listener.start()
            try:
                reader, writer = await asyncio.open_unix_connection(send_path)
                writer.write(
                    json.dumps({
                        'type': 'send',
                        'member': 'proj/worker',
                        'composite': 'first message',
                        'context_id': '',
                    }).encode() + b'\n'
                )
                await writer.drain()
                await reader.readline()
                writer.close()
                await asyncio.sleep(0.1)
            finally:
                await listener.stop()

        _run(run())

        self.assertEqual(
            len(self.spawn_calls),
            1,
            'spawn_fn must be called for a new conversation (no context_id)',
        )
        self.assertEqual(
            len(self.resume_calls),
            0,
            'resume_fn must NOT be called for a new conversation',
        )


# ── SC7: Dispatch rejects follow-up to a closed conversation ─────────────────


class TestFollowUpRejectedForClosedConversation(unittest.TestCase):
    """SC7: Send with context_id pointing to a closed conversation must return
    an error, not spawn a fresh session or resume."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.bus_db = os.path.join(self.tmpdir, 'bus.db')
        self.spawn_calls = []
        self.resume_calls = []

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    async def _capture_spawn(self, member, composite, context_id):
        self.spawn_calls.append(context_id)
        return ('new-session', '')

    async def _capture_resume(self, member, composite, session_id, context_id):
        self.resume_calls.append(session_id)
        return session_id

    def _setup_closed_conversation(self, context_id, session_id):
        bus = _make_bus(self.tmpdir)
        bus.create_agent_context(context_id, 'proj/lead', 'proj/worker')
        bus.set_agent_context_session_id(context_id, session_id)
        bus.close_agent_context(context_id)
        bus.close_agent_conversation(context_id)  # originator closes
        bus.close()

    def test_send_to_closed_conversation_returns_error(self):
        """SC7: Send with context_id for a closed conversation must return
        {status: 'error'} and not spawn or resume."""
        from orchestrator.bus_event_listener import BusEventListener

        CTX_ID = 'agent:proj/lead:proj/worker:closed-conv-1'
        SESSION_ID = 'prior-session-closed'

        self._setup_closed_conversation(CTX_ID, SESSION_ID)

        responses = []
        listener = BusEventListener(
            bus_db_path=self.bus_db,
            spawn_fn=self._capture_spawn,
            resume_fn=self._capture_resume,
            initiator_agent_id='proj/lead',
        )

        async def run():
            send_path, reply_path, close_path = await listener.start()
            try:
                reader, writer = await asyncio.open_unix_connection(send_path)
                writer.write(
                    json.dumps({
                        'type': 'send',
                        'member': 'proj/worker',
                        'composite': 'follow-up to closed',
                        'context_id': CTX_ID,
                    }).encode() + b'\n'
                )
                await writer.drain()
                line = await reader.readline()
                responses.append(json.loads(line.decode()))
                writer.close()
                await asyncio.sleep(0.05)
            finally:
                await listener.stop()

        _run(run())

        self.assertEqual(len(responses), 1)
        self.assertEqual(
            responses[0]['status'],
            'error',
            'Send to closed conversation must return {status: error}',
        )
        self.assertIn(
            'closed',
            responses[0].get('reason', '').lower(),
            'Error reason must mention the conversation is closed',
        )
        self.assertEqual(
            len(self.spawn_calls),
            0,
            'spawn_fn must NOT be called when conversation is closed',
        )
        self.assertEqual(
            len(self.resume_calls),
            0,
            'resume_fn must NOT be called when conversation is closed',
        )


# ── SC2: CloseConversation via close socket ───────────────────────────────────


class TestCloseConversationSocket(unittest.TestCase):
    """SC2: BusEventListener must expose a close socket for CloseConversation
    MCP tool calls. Only the originator can close a conversation."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.bus_db = os.path.join(self.tmpdir, 'bus.db')

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _setup_open_context(self, context_id, initiator_agent_id='proj/lead'):
        bus = _make_bus(self.tmpdir)
        bus.create_agent_context(context_id, initiator_agent_id, 'proj/worker')
        bus.set_agent_context_session_id(context_id, 'session-abc')
        bus.close()

    def test_close_socket_is_started(self):
        """SC2: BusEventListener.start() must return a close socket path."""
        from orchestrator.bus_event_listener import BusEventListener

        listener = BusEventListener(bus_db_path=self.bus_db)

        async def run():
            result = await listener.start()
            await listener.stop()
            return result

        paths = _run(run())
        self.assertEqual(
            len(paths),
            3,
            'BusEventListener.start() must return (send_path, reply_path, close_path)',
        )
        send_path, reply_path, close_path = paths
        self.assertTrue(close_path, 'close socket path must be non-empty')

    def test_close_conversation_via_socket_sets_conversation_closed(self):
        """SC2: posting to close socket must set conversation_status='closed'."""
        from orchestrator.bus_event_listener import BusEventListener

        CTX_ID = 'agent:proj/lead:proj/worker:close-socket-1'
        self._setup_open_context(CTX_ID, 'proj/lead')

        listener = BusEventListener(
            bus_db_path=self.bus_db,
            initiator_agent_id='proj/lead',
        )

        async def run():
            send_path, reply_path, close_path = await listener.start()
            try:
                reader, writer = await asyncio.open_unix_connection(close_path)
                writer.write(
                    json.dumps({
                        'type': 'close_conversation',
                        'context_id': CTX_ID,
                        'caller_agent_id': 'proj/lead',
                    }).encode() + b'\n'
                )
                await writer.drain()
                line = await reader.readline()
                response = json.loads(line.decode())
                writer.close()
                await asyncio.sleep(0.05)
                return response
            finally:
                await listener.stop()

        response = _run(run())

        self.assertEqual(
            response['status'],
            'ok',
            'CloseConversation must return {status: ok}',
        )
        bus = _make_bus(self.tmpdir)
        try:
            ctx = bus.get_agent_context(CTX_ID)
            self.assertEqual(
                ctx['conversation_status'],
                'closed',
                'conversation_status must be closed after CloseConversation socket call',
            )
        finally:
            bus.close()


# ── SC4: Human interjection via interjection socket ──────────────────────────


class TestInterjectionSocket(unittest.TestCase):
    """SC4: BusEventListener must expose an interjection socket so the bridge
    can inject a human message into an open conversation and trigger --resume."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.bus_db = os.path.join(self.tmpdir, 'bus.db')
        self.reinvoke_calls = []
        self.inject_calls = []

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _setup_open_context_with_session(self, context_id, session_id):
        bus = _make_bus(self.tmpdir)
        bus.create_agent_context(context_id, 'proj/lead', 'proj/worker')
        bus.set_agent_context_session_id(context_id, session_id)
        bus.close()

    async def _capture_reinvoke(self, context_id, session_id, message):
        self.reinvoke_calls.append({
            'context_id': context_id,
            'session_id': session_id,
            'message': message,
        })

    def test_interjection_socket_triggers_reinvoke_on_open_conversation(self):
        """SC4: posting to interjection socket must trigger reinvoke_fn
        with the active session_id for that conversation."""
        from orchestrator.bus_event_listener import BusEventListener

        CTX_ID = 'agent:proj/lead:proj/worker:interject-1'
        ACTIVE_SESSION = 'active-agent-session'

        self._setup_open_context_with_session(CTX_ID, ACTIVE_SESSION)

        listener = BusEventListener(
            bus_db_path=self.bus_db,
            reinvoke_fn=self._capture_reinvoke,
        )

        async def run():
            send_path, reply_path, close_path = await listener.start()
            # The interjection socket should be at a 4th path, or the bus
            # listener exposes it as listener.interjection_socket_path
            interjection_path = listener.interjection_socket_path
            try:
                reader, writer = await asyncio.open_unix_connection(interjection_path)
                writer.write(
                    json.dumps({
                        'type': 'interject',
                        'context_id': CTX_ID,
                        'message': 'Human follow-up question',
                    }).encode() + b'\n'
                )
                await writer.drain()
                line = await reader.readline()
                response = json.loads(line.decode())
                writer.close()
                await asyncio.sleep(0.15)
                return response
            finally:
                await listener.stop()

        response = _run(run())

        self.assertEqual(
            response['status'],
            'ok',
            'Interjection must return {status: ok}',
        )
        self.assertEqual(
            len(self.reinvoke_calls),
            1,
            'reinvoke_fn must be called once for the interjection',
        )
        call = self.reinvoke_calls[0]
        self.assertEqual(
            call['session_id'],
            ACTIVE_SESSION,
            f"reinvoke_fn must receive the active session_id '{ACTIVE_SESSION}'",
        )
        self.assertEqual(
            call['context_id'],
            CTX_ID,
            'reinvoke_fn must receive the conversation context_id',
        )
        self.assertEqual(
            call['message'],
            'Human follow-up question',
            'reinvoke_fn must receive the human message verbatim',
        )

    def test_interjection_on_closed_conversation_returns_error(self):
        """SC7: interjecting into a closed conversation must be rejected."""
        from orchestrator.bus_event_listener import BusEventListener

        CTX_ID = 'agent:proj/lead:proj/worker:interject-closed'
        SESSION_ID = 'closed-session'

        bus = _make_bus(self.tmpdir)
        bus.create_agent_context(CTX_ID, 'proj/lead', 'proj/worker')
        bus.set_agent_context_session_id(CTX_ID, SESSION_ID)
        bus.close_agent_conversation(CTX_ID)
        bus.close()

        listener = BusEventListener(
            bus_db_path=self.bus_db,
            reinvoke_fn=self._capture_reinvoke,
        )

        async def run():
            _, _, _ = await listener.start()
            interjection_path = listener.interjection_socket_path
            try:
                reader, writer = await asyncio.open_unix_connection(interjection_path)
                writer.write(
                    json.dumps({
                        'type': 'interject',
                        'context_id': CTX_ID,
                        'message': 'Too late',
                    }).encode() + b'\n'
                )
                await writer.drain()
                line = await reader.readline()
                response = json.loads(line.decode())
                writer.close()
                await asyncio.sleep(0.05)
                return response
            finally:
                await listener.stop()

        response = _run(run())

        self.assertEqual(
            response['status'],
            'error',
            'Interjecting into a closed conversation must return error',
        )
        self.assertEqual(
            len(self.reinvoke_calls),
            0,
            'reinvoke_fn must NOT be called for a closed conversation interjection',
        )


# ── SC5: Parallel conversations work independently ───────────────────────────


class TestParallelConversations(unittest.TestCase):
    """SC5: Multiple open conversations per agent must work independently.
    Each context_id/session_id pair is autonomous."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.bus = _make_bus(self.tmpdir)

    def tearDown(self):
        self.bus.close()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_closing_one_conversation_does_not_affect_others(self):
        """SC5: close_agent_conversation on one context_id must not affect
        a parallel context_id to the same recipient."""
        self.bus.create_agent_context('ctx-A', 'proj/lead', 'proj/worker')
        self.bus.set_agent_context_session_id('ctx-A', 'session-A')
        self.bus.create_agent_context('ctx-B', 'proj/lead', 'proj/worker')
        self.bus.set_agent_context_session_id('ctx-B', 'session-B')

        self.bus.close_agent_conversation('ctx-A')

        ctx_a = self.bus.get_agent_context('ctx-A')
        ctx_b = self.bus.get_agent_context('ctx-B')

        self.assertEqual(
            ctx_a['conversation_status'],
            'closed',
            'ctx-A conversation must be closed',
        )
        self.assertEqual(
            ctx_b['conversation_status'],
            'open',
            'ctx-B conversation must remain open — closing ctx-A must not affect it',
        )

    def test_parallel_conversations_have_independent_session_ids(self):
        """SC5: parallel conversations to the same recipient have independent session_ids."""
        self.bus.create_agent_context('ctx-X', 'proj/lead', 'proj/worker')
        self.bus.set_agent_context_session_id('ctx-X', 'session-X')
        self.bus.create_agent_context('ctx-Y', 'proj/lead', 'proj/worker')
        self.bus.set_agent_context_session_id('ctx-Y', 'session-Y')

        ctx_x = self.bus.get_agent_context('ctx-X')
        ctx_y = self.bus.get_agent_context('ctx-Y')

        self.assertNotEqual(
            ctx_x['session_id'],
            ctx_y['session_id'],
            'Parallel conversations must have independent session_ids',
        )
        self.assertEqual(ctx_x['session_id'], 'session-X')
        self.assertEqual(ctx_y['session_id'], 'session-Y')


# ── SC2: CloseConversation MCP tool ──────────────────────────────────────────


class TestCloseConversationMCPTool(unittest.TestCase):
    """SC2: mcp_server must expose a close_conversation_handler for the
    CloseConversation MCP tool. Posts to CLOSE_CONV_SOCKET."""

    def test_close_conversation_handler_exists(self):
        """SC2: close_conversation_handler must exist in orchestrator.mcp_server."""
        from orchestrator import mcp_server
        self.assertTrue(
            hasattr(mcp_server, 'close_conversation_handler'),
            'mcp_server must have close_conversation_handler for CloseConversation tool',
        )

    def test_close_conversation_handler_posts_to_close_socket(self):
        """SC2: close_conversation_handler must post to CLOSE_CONV_SOCKET."""
        from orchestrator.mcp_server import close_conversation_handler

        posts = []

        async def capture_post(context_id: str) -> str:
            posts.append(context_id)
            return json.dumps({'status': 'ok'})

        result = _run(close_conversation_handler(
            'ctx-close-1',
            post_fn=capture_post,
        ))

        self.assertEqual(len(posts), 1)
        self.assertEqual(posts[0], 'ctx-close-1')
        response = json.loads(result)
        self.assertEqual(response['status'], 'ok')


# ── SC8: Bridge interjection routing ─────────────────────────────────────────


class TestBridgeInterjectionRouting(unittest.TestCase):
    """SC8: The bridge's POST /api/conversations/{agent:...} endpoint must route
    through _handle_agent_conversation_post → _find_interjection_socket → the
    interjection socket server, triggering --resume on the active session.

    This covers the chat-dialog entry point that was previously untested.
    """

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_post_to_agent_conversation_forwards_to_interjection_socket(self):
        """SC8: POST /api/conversations/agent:... must reach the interjection socket."""
        import asyncio
        import json
        import os
        from aiohttp import web
        from aiohttp.test_utils import TestClient, TestServer

        conv_id = 'agent:proj-lead:proj-worker:test-sc8-1'
        received = {}

        async def run():
            # Start a mock interjection socket server that records what it receives.
            sock_path = os.path.join(self.tmpdir, 'interject.sock')

            async def handle_interjection(reader, writer):
                line = await reader.readline()
                payload = json.loads(line.decode())
                received['payload'] = payload
                writer.write(json.dumps({'status': 'ok'}).encode() + b'\n')
                await writer.drain()
                writer.close()

            sock_server = await asyncio.start_unix_server(handle_interjection, path=sock_path)

            try:
                # Build a minimal bridge with _find_interjection_socket mocked
                # to return the socket path above.  This isolates the bridge-side
                # routing logic (_handle_agent_conversation_post) from project
                # discovery (_resolve_session_infra).
                from bridge.server import TeaPartyBridge
                bridge = TeaPartyBridge(
                    teaparty_home=self.tmpdir,
                    static_dir=self.tmpdir,
                )
                bridge._find_interjection_socket = lambda cid: sock_path

                app = web.Application()
                app.router.add_post(
                    '/api/conversations/{id}',
                    bridge._handle_conversation_post,
                )

                async with TestClient(TestServer(app)) as client:
                    resp = await client.post(
                        f'/api/conversations/{conv_id}',
                        json={'content': 'hello from human'},
                    )
                    data = await resp.json()

                self.assertEqual(resp.status, 200, f'expected 200, got {resp.status}: {data}')
                self.assertEqual(data.get('status'), 'ok')
            finally:
                sock_server.close()
                await sock_server.wait_closed()

        _run(run())

        self.assertIn('payload', received, 'interjection socket must receive a payload')
        self.assertEqual(received['payload'].get('type'), 'interject')
        self.assertEqual(received['payload'].get('context_id'), conv_id)
        self.assertEqual(received['payload'].get('message'), 'hello from human')

    def test_post_to_agent_conversation_returns_404_when_socket_not_found(self):
        """SC8: POST to agent conversation with no active session must return 404."""
        import asyncio
        from aiohttp import web
        from aiohttp.test_utils import TestClient, TestServer

        conv_id = 'agent:proj-lead:proj-worker:test-sc8-2'

        async def run():
            from bridge.server import TeaPartyBridge
            bridge = TeaPartyBridge(
                teaparty_home=self.tmpdir,
                static_dir=self.tmpdir,
            )
            # No active session — _find_interjection_socket returns empty string.
            bridge._find_interjection_socket = lambda cid: ''

            app = web.Application()
            app.router.add_post(
                '/api/conversations/{id}',
                bridge._handle_conversation_post,
            )

            async with TestClient(TestServer(app)) as client:
                resp = await client.post(
                    f'/api/conversations/{conv_id}',
                    json={'content': 'hello'},
                )
                data = await resp.json(content_type=None)
                return resp.status, data

        status, data = _run(run())
        self.assertEqual(status, 404)
        self.assertIn('error', data)


# ── SC2: Worktree cleanup and originator identity (findings 1 & 2) ────────────


class TestWorktreeCleanupOnClose(unittest.TestCase):
    """Finding 1: CloseConversation must trigger worktree cleanup via cleanup_fn.
    The agent_worktree_path stored at spawn time must be passed to cleanup_fn
    when the conversation closes."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_close_conversation_triggers_cleanup_fn_with_worktree_path(self):
        """cleanup_fn must be called with the stored agent_worktree_path on close."""
        from orchestrator.bus_event_listener import BusEventListener

        CTX_ID = 'agent:proj/lead:proj/worker:cleanup-test-1'
        WORKTREE_PATH = os.path.join(self.tmpdir, 'agents', 'fake-worktree')
        cleanup_calls = []

        async def mock_cleanup(worktree_path: str) -> None:
            cleanup_calls.append(worktree_path)

        bus = _make_bus(self.tmpdir)
        bus.create_agent_context(CTX_ID, 'proj/lead', 'proj/worker')
        bus.set_agent_context_worktree_path(CTX_ID, WORKTREE_PATH)
        bus.close()

        listener = BusEventListener(
            bus_db_path=os.path.join(self.tmpdir, 'bus.db'),
            cleanup_fn=mock_cleanup,
            initiator_agent_id='proj/lead',
        )

        async def run():
            _, _, close_path = await listener.start()
            try:
                reader, writer = await asyncio.open_unix_connection(close_path)
                writer.write(
                    json.dumps({
                        'type': 'close_conversation',
                        'context_id': CTX_ID,
                        'caller_agent_id': 'proj/lead',
                    }).encode() + b'\n'
                )
                await writer.drain()
                line = await reader.readline()
                response = json.loads(line.decode())
                writer.close()
                await asyncio.sleep(0.1)
                return response
            finally:
                await listener.stop()

        response = _run(run())
        self.assertEqual(response['status'], 'ok')
        self.assertEqual(
            cleanup_calls,
            [WORKTREE_PATH],
            'cleanup_fn must be called with the stored worktree path on close',
        )

    def test_close_with_no_worktree_path_does_not_call_cleanup_fn(self):
        """cleanup_fn must not be called when no worktree path was stored."""
        from orchestrator.bus_event_listener import BusEventListener

        CTX_ID = 'agent:proj/lead:proj/worker:cleanup-no-path'
        cleanup_calls = []

        async def mock_cleanup(worktree_path: str) -> None:
            cleanup_calls.append(worktree_path)

        bus = _make_bus(self.tmpdir)
        bus.create_agent_context(CTX_ID, 'proj/lead', 'proj/worker')
        # No worktree path set
        bus.close()

        listener = BusEventListener(
            bus_db_path=os.path.join(self.tmpdir, 'bus.db'),
            cleanup_fn=mock_cleanup,
        )

        async def run():
            _, _, close_path = await listener.start()
            try:
                reader, writer = await asyncio.open_unix_connection(close_path)
                writer.write(
                    json.dumps({'type': 'close_conversation', 'context_id': CTX_ID}).encode() + b'\n'
                )
                await writer.drain()
                line = await reader.readline()
                response = json.loads(line.decode())
                writer.close()
                await asyncio.sleep(0.05)
                return response
            finally:
                await listener.stop()

        response = _run(run())
        self.assertEqual(response['status'], 'ok')
        self.assertEqual(
            cleanup_calls, [],
            'cleanup_fn must not be called when no worktree path is stored',
        )


class TestOriginatorOnlyClose(unittest.TestCase):
    """Finding 2: CloseConversation must enforce that only the initiator may
    close a conversation when caller_agent_id is provided."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_originator_can_close_own_conversation(self):
        """Originator posting caller_agent_id matching initiator_agent_id must succeed."""
        from orchestrator.bus_event_listener import BusEventListener

        CTX_ID = 'agent:proj/lead:proj/worker:originator-close-ok'
        bus = _make_bus(self.tmpdir)
        bus.create_agent_context(CTX_ID, 'proj/lead', 'proj/worker')
        bus.close()

        listener = BusEventListener(bus_db_path=os.path.join(self.tmpdir, 'bus.db'))

        async def run():
            _, _, close_path = await listener.start()
            try:
                reader, writer = await asyncio.open_unix_connection(close_path)
                writer.write(
                    json.dumps({
                        'type': 'close_conversation',
                        'context_id': CTX_ID,
                        'caller_agent_id': 'proj/lead',
                    }).encode() + b'\n'
                )
                await writer.drain()
                return json.loads((await reader.readline()).decode())
            finally:
                await listener.stop()

        response = _run(run())
        self.assertEqual(response['status'], 'ok')

        bus = _make_bus(self.tmpdir)
        try:
            ctx = bus.get_agent_context(CTX_ID)
            self.assertEqual(ctx['conversation_status'], 'closed')
        finally:
            bus.close()

    def test_non_originator_close_is_rejected(self):
        """Non-originator posting caller_agent_id that differs from initiator must get error."""
        from orchestrator.bus_event_listener import BusEventListener

        CTX_ID = 'agent:proj/lead:proj/worker:non-originator-close'
        bus = _make_bus(self.tmpdir)
        bus.create_agent_context(CTX_ID, 'proj/lead', 'proj/worker')
        bus.close()

        listener = BusEventListener(bus_db_path=os.path.join(self.tmpdir, 'bus.db'))

        async def run():
            _, _, close_path = await listener.start()
            try:
                reader, writer = await asyncio.open_unix_connection(close_path)
                writer.write(
                    json.dumps({
                        'type': 'close_conversation',
                        'context_id': CTX_ID,
                        'caller_agent_id': 'proj/worker',  # wrong — worker is not the initiator
                    }).encode() + b'\n'
                )
                await writer.drain()
                return json.loads((await reader.readline()).decode())
            finally:
                await listener.stop()

        response = _run(run())
        self.assertEqual(
            response['status'],
            'error',
            'non-originator must be rejected',
        )
        self.assertIn('originator', response.get('reason', '').lower())

        bus = _make_bus(self.tmpdir)
        try:
            ctx = bus.get_agent_context(CTX_ID)
            self.assertEqual(
                ctx['conversation_status'],
                'open',
                'conversation must remain open after rejected close attempt',
            )
        finally:
            bus.close()

    def test_close_without_caller_agent_id_is_allowed(self):
        """Close request without caller_agent_id bypasses identity check (backward compat)."""
        from orchestrator.bus_event_listener import BusEventListener

        CTX_ID = 'agent:proj/lead:proj/worker:no-agent-id-close'
        bus = _make_bus(self.tmpdir)
        bus.create_agent_context(CTX_ID, 'proj/lead', 'proj/worker')
        bus.close()

        listener = BusEventListener(bus_db_path=os.path.join(self.tmpdir, 'bus.db'))

        async def run():
            _, _, close_path = await listener.start()
            try:
                reader, writer = await asyncio.open_unix_connection(close_path)
                writer.write(
                    json.dumps({'type': 'close_conversation', 'context_id': CTX_ID}).encode() + b'\n'
                )
                await writer.drain()
                return json.loads((await reader.readline()).decode())
            finally:
                await listener.stop()

        response = _run(run())
        self.assertEqual(response['status'], 'ok')


# ── SC8: Bridge interjection socket discovery ─────────────────────────────────


class TestFindInterjectionSocket(unittest.TestCase):
    """SC8: _find_interjection_socket must locate the interjection socket by
    scanning active session buses for the matching agent context, resolving
    the session's infra_dir, and reading the interjection_socket file.

    This tests the discovery logic that was previously mocked in
    TestBridgeInterjectionRouting — the materialization of SC4's claim that
    'the chat dialog already carries the conversation_id.'
    """

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_find_interjection_socket_returns_path_for_matching_context(self):
        """_find_interjection_socket must return the socket path when the conv_id
        exists in an active bus and the infra_dir has an interjection_socket file."""
        from bridge.server import TeaPartyBridge
        from orchestrator.messaging import SqliteMessageBus

        conv_id = 'agent:proj-lead:proj-worker:find-sock-1'
        session_id = 'test-session-findme'
        expected_socket = os.path.join(self.tmpdir, 'real-interject.sock')

        # Create a real bus with the context record
        bus_db = os.path.join(self.tmpdir, 'bus.db')
        bus = SqliteMessageBus(bus_db)
        bus.create_agent_context(conv_id, 'proj/lead', 'proj/worker')

        # Create an infra_dir with the interjection_socket file
        infra_dir = os.path.join(self.tmpdir, 'infra', session_id)
        os.makedirs(infra_dir)
        with open(os.path.join(infra_dir, 'interjection_socket'), 'w') as f:
            f.write(expected_socket + '\n')  # trailing newline — strip() must handle it

        try:
            bridge = TeaPartyBridge(teaparty_home=self.tmpdir, static_dir=self.tmpdir)
            bridge._buses[session_id] = bus
            bridge._resolve_session_infra = lambda sid: infra_dir if sid == session_id else None

            result = bridge._find_interjection_socket(conv_id)
        finally:
            bus.close()

        self.assertEqual(
            result,
            expected_socket,
            '_find_interjection_socket must return the socket path from the infra file',
        )

    def test_find_interjection_socket_returns_empty_when_no_matching_bus(self):
        """_find_interjection_socket must return '' when no active bus has the context."""
        from bridge.server import TeaPartyBridge
        from orchestrator.messaging import SqliteMessageBus

        conv_id = 'agent:proj-lead:proj-worker:find-sock-notfound'

        # Bus has no record for this conv_id
        bus_db = os.path.join(self.tmpdir, 'bus.db')
        bus = SqliteMessageBus(bus_db)
        bus.create_agent_context('agent:other:context:xyz', 'proj/lead', 'proj/worker')

        try:
            bridge = TeaPartyBridge(teaparty_home=self.tmpdir, static_dir=self.tmpdir)
            bridge._buses['session-other'] = bus
            bridge._resolve_session_infra = lambda sid: self.tmpdir

            result = bridge._find_interjection_socket(conv_id)
        finally:
            bus.close()

        self.assertEqual(result, '', '_find_interjection_socket must return empty string when no match')

    def test_find_interjection_socket_returns_empty_when_socket_file_missing(self):
        """_find_interjection_socket must return '' when infra_dir has no socket file."""
        from bridge.server import TeaPartyBridge
        from orchestrator.messaging import SqliteMessageBus

        conv_id = 'agent:proj-lead:proj-worker:find-sock-nofile'
        session_id = 'test-session-nofile'

        bus_db = os.path.join(self.tmpdir, 'bus.db')
        bus = SqliteMessageBus(bus_db)
        bus.create_agent_context(conv_id, 'proj/lead', 'proj/worker')

        # infra_dir exists but has no interjection_socket file
        infra_dir = os.path.join(self.tmpdir, 'infra-nofile')
        os.makedirs(infra_dir)

        try:
            bridge = TeaPartyBridge(teaparty_home=self.tmpdir, static_dir=self.tmpdir)
            bridge._buses[session_id] = bus
            bridge._resolve_session_infra = lambda sid: infra_dir

            result = bridge._find_interjection_socket(conv_id)
        finally:
            bus.close()

        self.assertEqual(result, '', '_find_interjection_socket must return empty string when socket file missing')


if __name__ == '__main__':
    unittest.main()
