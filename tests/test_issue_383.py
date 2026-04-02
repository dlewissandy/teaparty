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
            send_path, reply_path = await listener.start()
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

    async def _capture_spawn(self, member: str, composite: str, context_id: str) -> str:
        self.spawn_calls.append({'member': member, 'context_id': context_id})
        return 'new-session-id'

    async def _capture_resume(self, member: str, composite: str, session_id: str) -> str:
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
            send_path, reply_path = await listener.start()
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
            send_path, reply_path = await listener.start()
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
        return 'new-session'

    async def _capture_resume(self, member, composite, session_id):
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
            send_path, reply_path = await listener.start()
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


if __name__ == '__main__':
    unittest.main()
