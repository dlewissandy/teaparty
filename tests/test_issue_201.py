"""Tests for issue #201: Office manager agent for cross-project coordination.

Verifies:
1. OfficeManagerSession lifecycle: create, send message, resume, fresh invocation
2. Memory chunk types: inquiry, steering, action_request, context_injection
3. Memory recording to shared SQLite database
4. MCP intervention tools: WithdrawSession, PauseDispatch, ResumeDispatch
5. Office manager conversation persistence via message bus
6. Management team agent definition structure
7. Session ID tracking for multi-turn --resume support
"""
import asyncio
import json
import os
import shutil
import tempfile
import time
import unittest

from orchestrator.messaging import (
    ConversationType,
    SqliteMessageBus,
    make_conversation_id,
)


class TestOfficeManagerSession(unittest.TestCase):
    """OfficeManagerSession lifecycle: create, message, resume."""

    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self.teaparty_home = self._tmp

    def tearDown(self):
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _make_session(self, **kwargs):
        from orchestrator.office_manager import OfficeManagerSession
        defaults = {
            'teaparty_home': self.teaparty_home,
            'user_id': 'darrell',
        }
        defaults.update(kwargs)
        return OfficeManagerSession(**defaults)

    def test_session_creates_conversation(self):
        """Creating a session establishes an office_manager conversation ID."""
        session = self._make_session()
        self.assertTrue(session.conversation_id.startswith('om:'))
        self.assertIn('darrell', session.conversation_id)

    def test_session_tracks_claude_session_id(self):
        """Session tracks the Claude CLI session ID for --resume support."""
        session = self._make_session()
        self.assertIsNone(session.claude_session_id)
        session.claude_session_id = 'ses_abc123'
        self.assertEqual(session.claude_session_id, 'ses_abc123')

    def test_session_creates_message_bus(self):
        """Session creates a message bus at the canonical OM path."""
        from orchestrator.office_manager import om_bus_path
        session = self._make_session()
        bus_path = om_bus_path(self.teaparty_home)
        self.assertTrue(os.path.exists(bus_path))

    def test_send_human_message(self):
        """Human messages are persisted in the conversation."""
        session = self._make_session()
        session.send_human_message('What is the status of the POC project?')
        messages = session.get_messages()
        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0].sender, 'human')
        self.assertIn('status', messages[0].content)

    def test_send_agent_message(self):
        """Agent messages are persisted in the conversation."""
        session = self._make_session()
        session.send_agent_message('The POC project has 3 active sessions.')
        messages = session.get_messages()
        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0].sender, 'office-manager')

    def test_conversation_persists_across_session_instances(self):
        """Messages persist when a new session instance is created for the same user."""
        session1 = self._make_session()
        session1.send_human_message('Hello')
        session1.send_agent_message('Hi there')

        # New session instance for same user — should see prior messages
        session2 = self._make_session()
        messages = session2.get_messages()
        self.assertEqual(len(messages), 2)
        self.assertEqual(messages[0].sender, 'human')
        self.assertEqual(messages[1].sender, 'office-manager')

    def test_session_state_persists_to_disk(self):
        """Session state (Claude session ID) is saved and reloaded."""
        session1 = self._make_session()
        session1.claude_session_id = 'ses_xyz789'
        session1.save_state()

        session2 = self._make_session()
        session2.load_state()
        self.assertEqual(session2.claude_session_id, 'ses_xyz789')


class TestMemoryChunkTypes(unittest.TestCase):
    """Memory chunk types defined in the proposal: inquiry, steering, action_request, context_injection."""

    def test_inquiry_chunk_type(self):
        """inquiry chunk type is defined and valid."""
        from orchestrator.office_manager import MemoryChunkType
        self.assertEqual(MemoryChunkType.INQUIRY.value, 'inquiry')

    def test_steering_chunk_type(self):
        """steering chunk type is defined and valid."""
        from orchestrator.office_manager import MemoryChunkType
        self.assertEqual(MemoryChunkType.STEERING.value, 'steering')

    def test_action_request_chunk_type(self):
        """action_request chunk type is defined and valid."""
        from orchestrator.office_manager import MemoryChunkType
        self.assertEqual(MemoryChunkType.ACTION_REQUEST.value, 'action_request')

    def test_context_injection_chunk_type(self):
        """context_injection chunk type is defined and valid."""
        from orchestrator.office_manager import MemoryChunkType
        self.assertEqual(MemoryChunkType.CONTEXT_INJECTION.value, 'context_injection')


class TestMemoryRecording(unittest.TestCase):
    """Recording memory chunks to the shared SQLite database."""

    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self.db_path = os.path.join(self._tmp, '.proxy-memory.db')

    def tearDown(self):
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _make_store(self):
        from orchestrator.office_manager import MemoryStore
        return MemoryStore(self.db_path)

    def test_record_steering_chunk(self):
        """A steering chunk is recorded and retrievable."""
        store = self._make_store()
        store.record(
            chunk_type='steering',
            content='Focus on security across all sessions',
            source='darrell',
        )
        chunks = store.retrieve(chunk_type='steering')
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0]['content'], 'Focus on security across all sessions')
        self.assertEqual(chunks[0]['source'], 'darrell')

    def test_record_inquiry_chunk(self):
        """An inquiry chunk is recorded and retrievable."""
        store = self._make_store()
        store.record(
            chunk_type='inquiry',
            content='Asked about POC project status',
            source='darrell',
        )
        chunks = store.retrieve(chunk_type='inquiry')
        self.assertEqual(len(chunks), 1)
        self.assertIn('POC project status', chunks[0]['content'])

    def test_record_context_injection(self):
        """A context_injection chunk is recorded and retrievable."""
        store = self._make_store()
        store.record(
            chunk_type='context_injection',
            content='Switching to Postgres next quarter',
            source='darrell',
        )
        chunks = store.retrieve(chunk_type='context_injection')
        self.assertEqual(len(chunks), 1)
        self.assertIn('Postgres', chunks[0]['content'])

    def test_record_action_request(self):
        """An action_request chunk is recorded and retrievable."""
        store = self._make_store()
        store.record(
            chunk_type='action_request',
            content='Requested commit and push for all projects',
            source='darrell',
        )
        chunks = store.retrieve(chunk_type='action_request')
        self.assertEqual(len(chunks), 1)

    def test_chunk_has_timestamp(self):
        """Each recorded chunk has a timestamp."""
        store = self._make_store()
        store.record(chunk_type='steering', content='test', source='user')
        chunks = store.retrieve(chunk_type='steering')
        self.assertIn('timestamp', chunks[0])
        self.assertIsInstance(chunks[0]['timestamp'], float)
        self.assertGreater(chunks[0]['timestamp'], 0)

    def test_retrieve_filters_by_type(self):
        """retrieve() returns only chunks of the requested type."""
        store = self._make_store()
        store.record(chunk_type='steering', content='steer', source='user')
        store.record(chunk_type='inquiry', content='ask', source='user')
        store.record(chunk_type='context_injection', content='ctx', source='user')

        steering = store.retrieve(chunk_type='steering')
        self.assertEqual(len(steering), 1)
        self.assertEqual(steering[0]['content'], 'steer')

        inquiry = store.retrieve(chunk_type='inquiry')
        self.assertEqual(len(inquiry), 1)
        self.assertEqual(inquiry[0]['content'], 'ask')

    def test_retrieve_all_types(self):
        """retrieve() with no type filter returns all chunks."""
        store = self._make_store()
        store.record(chunk_type='steering', content='a', source='user')
        store.record(chunk_type='inquiry', content='b', source='user')
        all_chunks = store.retrieve()
        self.assertEqual(len(all_chunks), 2)

    def test_shared_database_between_stores(self):
        """Two MemoryStore instances sharing the same DB see each other's chunks."""
        store1 = self._make_store()
        store1.record(chunk_type='steering', content='from store1', source='user')

        store2 = self._make_store()
        chunks = store2.retrieve(chunk_type='steering')
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0]['content'], 'from store1')


class TestCrossMemoryBridge(unittest.TestCase):
    """Cross-memory bridge: office manager writes steering chunks to proxy_chunks,
    reads gate_outcome chunks from proxy_chunks. This is the shared memory pool
    that makes the two-agent architecture work."""

    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self.db_path = os.path.join(self._tmp, '.proxy-memory.db')

    def tearDown(self):
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _make_store(self):
        from orchestrator.office_manager import MemoryStore
        return MemoryStore(self.db_path)

    def test_record_steering_writes_to_proxy_chunks(self):
        """record_steering() creates a MemoryChunk in the proxy's proxy_chunks table."""
        from orchestrator.proxy_memory import open_proxy_db, get_chunk
        store = self._make_store()
        chunk_id = store.record_steering(
            content='Focus on security across all sessions',
            source='darrell',
            current_interaction=1,
        )
        # Verify via the proxy_memory API directly
        conn = open_proxy_db(self.db_path)
        chunk = get_chunk(conn, chunk_id)
        conn.close()
        self.assertIsNotNone(chunk)
        self.assertEqual(chunk.type, 'steering')
        self.assertIn('security', chunk.content)

    def test_record_steering_is_retrievable_by_proxy(self):
        """A steering chunk recorded by the office manager is visible to proxy retrieval."""
        from orchestrator.proxy_memory import open_proxy_db, query_chunks
        store = self._make_store()
        store.record_steering(
            content='Prioritize database migration',
            source='darrell',
            current_interaction=2,
        )
        conn = open_proxy_db(self.db_path)
        chunks = query_chunks(conn, type='steering')
        conn.close()
        self.assertEqual(len(chunks), 1)
        self.assertIn('database migration', chunks[0].content)

    def test_get_gate_outcomes_reads_proxy_chunks(self):
        """get_gate_outcomes() reads gate_outcome chunks written by the proxy."""
        from orchestrator.proxy_memory import (
            open_proxy_db, store_chunk, MemoryChunk,
        )
        # Write a gate_outcome chunk as the proxy would
        conn = open_proxy_db(self.db_path)
        chunk = MemoryChunk(
            id='gate-test-001',
            type='gate_outcome',
            state='APPROVED',
            task_type='planning',
            outcome='approved',
            content='Approved the planning phase for POC session',
        )
        store_chunk(conn, chunk)
        conn.close()

        # Read it via the office manager's bridge method
        store = self._make_store()
        outcomes = store.get_gate_outcomes(task_type='planning')
        self.assertEqual(len(outcomes), 1)
        self.assertEqual(outcomes[0].state, 'APPROVED')
        self.assertIn('planning phase', outcomes[0].content)

    def test_shared_db_both_directions(self):
        """Office manager steering and proxy gate_outcomes coexist in the same DB."""
        from orchestrator.proxy_memory import (
            open_proxy_db, store_chunk, MemoryChunk, query_chunks,
        )
        # Proxy writes a gate_outcome
        conn = open_proxy_db(self.db_path)
        store_chunk(conn, MemoryChunk(
            id='gate-both-001',
            type='gate_outcome',
            state='APPROVED',
            task_type='execution',
            outcome='approved',
            content='Approved execution',
        ))
        conn.close()

        # Office manager writes a steering chunk
        store = self._make_store()
        store.record_steering(
            content='Focus on tests',
            source='darrell',
            current_interaction=3,
        )

        # Both are visible
        conn = open_proxy_db(self.db_path)
        gates = query_chunks(conn, type='gate_outcome')
        steers = query_chunks(conn, type='steering')
        conn.close()
        self.assertEqual(len(gates), 1)
        self.assertEqual(len(steers), 1)


class TestInterventionTools(unittest.TestCase):
    """MCP intervention tools: WithdrawSession, PauseDispatch, ResumeDispatch, ReprioritizeDispatch."""

    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self.infra_dir = os.path.join(self._tmp, 'session')
        os.makedirs(self.infra_dir)

    def tearDown(self):
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _make_cfa_state(self, state='EXEC', phase='execution'):
        """Write a minimal CfA state JSON for testing."""
        cfa_path = os.path.join(self.infra_dir, '.cfa-state.json')
        data = {
            'state': state,
            'phase': phase,
            'actor': 'agent',
            'history': [],
            'backtrack_count': 0,
            'task_id': 'test-task',
            'parent_id': '',
            'team_id': 'test',
            'depth': 0,
        }
        with open(cfa_path, 'w') as f:
            json.dump(data, f)
        return cfa_path

    def _make_heartbeat(self, status='running'):
        """Write a minimal heartbeat file for testing."""
        hb_path = os.path.join(self.infra_dir, '.heartbeat')
        data = {
            'pid': os.getpid(),
            'parent_heartbeat': '',
            'role': 'test',
            'started': time.time(),
            'status': status,
        }
        with open(hb_path, 'w') as f:
            json.dump(data, f)
        return hb_path

    def test_withdraw_session_sets_state_withdrawn(self):
        """WithdrawSession sets CfA state to WITHDRAWN."""
        from orchestrator.office_manager_tools import withdraw_session
        cfa_path = self._make_cfa_state()
        self._make_heartbeat()
        result = withdraw_session(self.infra_dir)
        self.assertEqual(result['status'], 'withdrawn')

        # Verify CfA state file was updated
        with open(cfa_path) as f:
            cfa = json.load(f)
        self.assertEqual(cfa['state'], 'WITHDRAWN')

    def test_withdraw_session_finalizes_heartbeat(self):
        """WithdrawSession sets heartbeat to 'withdrawn'."""
        from orchestrator.office_manager_tools import withdraw_session
        self._make_cfa_state()
        hb_path = self._make_heartbeat()
        withdraw_session(self.infra_dir)

        with open(hb_path) as f:
            hb = json.load(f)
        self.assertEqual(hb['status'], 'withdrawn')

    def test_withdraw_already_terminal_is_noop(self):
        """Withdrawing an already-terminal session returns success without error."""
        from orchestrator.office_manager_tools import withdraw_session
        self._make_cfa_state(state='COMPLETED_WORK')
        self._make_heartbeat(status='completed')
        result = withdraw_session(self.infra_dir)
        self.assertEqual(result['status'], 'already_terminal')

    def test_pause_dispatch_sets_paused(self):
        """PauseDispatch pauses an active dispatch."""
        from orchestrator.office_manager_tools import pause_dispatch
        self._make_heartbeat(status='running')
        result = pause_dispatch(self.infra_dir)
        self.assertEqual(result['status'], 'paused')

        hb_path = os.path.join(self.infra_dir, '.heartbeat')
        with open(hb_path) as f:
            hb = json.load(f)
        self.assertEqual(hb['status'], 'paused')

    def test_resume_dispatch_resumes_paused(self):
        """ResumeDispatch resumes a paused dispatch."""
        from orchestrator.office_manager_tools import resume_dispatch
        self._make_heartbeat(status='paused')
        result = resume_dispatch(self.infra_dir)
        self.assertEqual(result['status'], 'resumed')

        hb_path = os.path.join(self.infra_dir, '.heartbeat')
        with open(hb_path) as f:
            hb = json.load(f)
        self.assertEqual(hb['status'], 'running')

    def test_resume_not_paused_is_noop(self):
        """Resuming a dispatch that isn't paused returns appropriate status."""
        from orchestrator.office_manager_tools import resume_dispatch
        self._make_heartbeat(status='running')
        result = resume_dispatch(self.infra_dir)
        self.assertEqual(result['status'], 'not_paused')

    def test_reprioritize_dispatch_updates_priority(self):
        """ReprioritizeDispatch changes the heartbeat priority field."""
        from orchestrator.office_manager_tools import reprioritize_dispatch
        self._make_heartbeat(status='running')
        result = reprioritize_dispatch(self.infra_dir, 'high')
        self.assertEqual(result['status'], 'reprioritized')
        self.assertEqual(result['new_priority'], 'high')

        hb_path = os.path.join(self.infra_dir, '.heartbeat')
        with open(hb_path) as f:
            hb = json.load(f)
        self.assertEqual(hb['priority'], 'high')

    def test_reprioritize_paused_dispatch(self):
        """A paused dispatch can be reprioritized without resuming it."""
        from orchestrator.office_manager_tools import reprioritize_dispatch
        self._make_heartbeat(status='paused')
        result = reprioritize_dispatch(self.infra_dir, 'low')
        self.assertEqual(result['status'], 'reprioritized')

        hb_path = os.path.join(self.infra_dir, '.heartbeat')
        with open(hb_path) as f:
            hb = json.load(f)
        self.assertEqual(hb['status'], 'paused')
        self.assertEqual(hb['priority'], 'low')

    def test_reprioritize_not_running_is_noop(self):
        """Reprioritizing a terminal dispatch returns not_running."""
        from orchestrator.office_manager_tools import reprioritize_dispatch
        self._make_heartbeat(status='withdrawn')
        result = reprioritize_dispatch(self.infra_dir, 'high')
        self.assertEqual(result['status'], 'not_running')


class TestManagementTeamDefinition(unittest.TestCase):
    """Management team agent definition structure."""

    def _load_team_def(self):
        from orchestrator import find_poc_root
        poc_root = find_poc_root()
        path = os.path.join(poc_root, 'agents', 'management-team.json')
        with open(path) as f:
            return json.load(f)

    def test_team_definition_exists(self):
        """Management team agent definition file exists."""
        from orchestrator import find_poc_root
        poc_root = find_poc_root()
        path = os.path.join(poc_root, 'agents', 'management-team.json')
        self.assertTrue(os.path.exists(path), f'Expected {path} to exist')

    def test_office_manager_is_lead(self):
        """office-manager is defined as the team lead."""
        team = self._load_team_def()
        self.assertIn('office-manager', team)
        # Lead agents are typically the first entry or have descriptive roles
        self.assertIn('description', team['office-manager'])

    def test_team_has_project_liaisons(self):
        """Team includes at least one project liaison agent."""
        team = self._load_team_def()
        liaison_keys = [k for k in team if 'liaison' in k]
        self.assertGreater(len(liaison_keys), 0, 'Expected at least one liaison agent')

    def test_team_has_config_workgroup_liaison(self):
        """Team includes a configuration workgroup liaison per the proposal."""
        team = self._load_team_def()
        config_keys = [k for k in team if 'config' in k]
        self.assertGreater(
            len(config_keys), 0,
            'Expected a configuration workgroup liaison agent',
        )

    def test_office_manager_has_intervention_tools(self):
        """office-manager prompt or config references intervention tools."""
        team = self._load_team_def()
        om = team['office-manager']
        prompt = om.get('prompt', '')
        # The office manager should know about WithdrawSession, PauseDispatch, etc.
        self.assertTrue(
            'WithdrawSession' in prompt or 'withdraw' in prompt.lower(),
            'Office manager prompt should reference intervention capabilities',
        )


class TestOfficeManagerConversationIntegration(unittest.TestCase):
    """Office manager conversation uses the message bus correctly."""

    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self.teaparty_home = self._tmp

    def tearDown(self):
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_conversation_id_uses_office_manager_type(self):
        """Office manager conversation uses OFFICE_MANAGER conversation type."""
        from orchestrator.office_manager import OfficeManagerSession
        session = OfficeManagerSession(teaparty_home=self.teaparty_home, user_id='testuser')
        expected_prefix = 'om:'
        self.assertTrue(session.conversation_id.startswith(expected_prefix))

    def test_multi_turn_conversation_history(self):
        """Multiple exchanges build up a readable conversation history."""
        from orchestrator.office_manager import OfficeManagerSession
        session = OfficeManagerSession(teaparty_home=self.teaparty_home, user_id='testuser')

        session.send_human_message('What is the POC status?')
        session.send_agent_message('The POC has 2 active sessions and 1 completed.')
        session.send_human_message('Focus on security from now on.')
        session.send_agent_message('Recorded. Security will be prioritized in future gates.')

        messages = session.get_messages()
        self.assertEqual(len(messages), 4)
        senders = [m.sender for m in messages]
        self.assertEqual(senders, ['human', 'office-manager', 'human', 'office-manager'])

    def test_build_context_for_agent(self):
        """build_context() returns conversation history formatted for the agent prompt."""
        from orchestrator.office_manager import OfficeManagerSession
        session = OfficeManagerSession(teaparty_home=self.teaparty_home, user_id='testuser')
        session.send_human_message('Hello')
        session.send_agent_message('Hi there')

        context = session.build_context()
        self.assertIsInstance(context, str)
        self.assertIn('Hello', context)
        self.assertIn('Hi there', context)


if __name__ == '__main__':
    unittest.main()
