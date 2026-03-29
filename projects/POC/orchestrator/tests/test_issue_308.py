"""Tests for issue #308: bridge server REST endpoints and WebSocket.

Verifies:
- REST endpoint behavior (unit, real SQLite fixtures)
- WebSocket state-change event emission (StatePoller unit tests)
- Conversation ID format: colon separator, regression guard for #279
"""
import asyncio
import json
import os
import shutil
import tempfile
import unittest
from unittest.mock import MagicMock

from projects.POC.bridge.server import TeaPartyBridge, _parse_artifacts, _resolve_conversation_type
from projects.POC.bridge.poller import StatePoller
from projects.POC.orchestrator.messaging import (
    ConversationType,
    SqliteMessageBus,
    make_conversation_id,
)


# ── Test bridge subclass: disables background tasks ───────────────────────────

class _TestBridge(TeaPartyBridge):
    """TeaPartyBridge with startup/cleanup disabled for unit testing.

    Tests manage bus lifecycle directly. Startup background tasks (poller,
    relay) are not started so tests are deterministic.
    """
    async def _on_startup(self, app):
        pass

    async def _on_cleanup(self, app):
        pass  # Tests manage bus lifecycle via tearDown / addCleanup


def _make_bridge(teaparty_home, projects_dir):
    return _TestBridge(
        teaparty_home=teaparty_home,
        projects_dir=projects_dir,
        static_dir=os.path.join(teaparty_home, 'static'),
    )


def _run_async(coro):
    """Run a coroutine on a fresh event loop."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ── Pure helper: _resolve_conversation_type ───────────────────────────────────

class TestResolveConversationType(unittest.TestCase):
    """_resolve_conversation_type converts query strings to ConversationType enum."""

    def test_project_session_returns_enum_member(self):
        result = _resolve_conversation_type('project_session')
        self.assertIs(result, ConversationType.PROJECT_SESSION)

    def test_office_manager_returns_enum_member(self):
        result = _resolve_conversation_type('office_manager')
        self.assertIs(result, ConversationType.OFFICE_MANAGER)

    def test_subteam_returns_enum_member(self):
        result = _resolve_conversation_type('SUBTEAM')
        self.assertIs(result, ConversationType.SUBTEAM)

    def test_case_normalized_to_upper_before_lookup(self):
        result = _resolve_conversation_type('project_session')
        self.assertEqual(result, ConversationType['PROJECT_SESSION'])

    def test_unknown_type_raises_key_error(self):
        with self.assertRaises(KeyError):
            _resolve_conversation_type('not_a_real_type')

    def test_empty_string_raises_key_error(self):
        with self.assertRaises(KeyError):
            _resolve_conversation_type('')


# ── Pure helper: _parse_artifacts ─────────────────────────────────────────────

class TestParseArtifacts(unittest.TestCase):
    """_parse_artifacts parses ## headings into {heading: body} dict."""

    def test_parses_multiple_sections(self):
        content = "## Overview\nThis is the overview.\n## Goals\nGoal 1\nGoal 2\n"
        result = _parse_artifacts(content)
        self.assertEqual(result['Overview'], 'This is the overview.')
        self.assertEqual(result['Goals'], 'Goal 1\nGoal 2')

    def test_empty_content_returns_empty_dict(self):
        self.assertEqual(_parse_artifacts(''), {})

    def test_content_without_headings_returns_empty_dict(self):
        self.assertEqual(_parse_artifacts('No headings here\n'), {})

    def test_section_body_is_stripped(self):
        content = "## Title\n\n  Body text  \n\n"
        result = _parse_artifacts(content)
        self.assertEqual(result['Title'], 'Body text')

    def test_heading_text_extracted_correctly(self):
        content = "## My Section Title\ncontent"
        result = _parse_artifacts(content)
        self.assertIn('My Section Title', result)

    def test_single_section_no_trailing_newline(self):
        content = "## Summary\nJust one line"
        result = _parse_artifacts(content)
        self.assertEqual(result['Summary'], 'Just one line')


# ── Conversation ID format: colon separator (#279 regression guard) ───────────

class TestConversationIdFormat(unittest.TestCase):
    """make_conversation_id uses ':' separator — regression guard for #279."""

    def test_project_session_id_format(self):
        cid = make_conversation_id(ConversationType.PROJECT_SESSION, '20260327-143000')
        self.assertEqual(cid, 'session:20260327-143000')

    def test_office_manager_id_format(self):
        cid = make_conversation_id(ConversationType.OFFICE_MANAGER, 'darrell')
        self.assertEqual(cid, 'om:darrell')

    def test_all_conversation_types_contain_colon_separator(self):
        for conv_type in ConversationType:
            cid = make_conversation_id(conv_type, 'test')
            self.assertIn(':', cid,
                f'{conv_type.name} conversation ID missing colon separator: {cid!r}')

    def test_id_does_not_start_or_end_with_colon(self):
        cid = make_conversation_id(ConversationType.PROJECT_SESSION, '20260327-143000')
        self.assertFalse(cid.startswith(':'), f'ID starts with colon: {cid!r}')
        self.assertFalse(cid.endswith(':'), f'ID ends with colon: {cid!r}')

    def test_bridge_bus_routing_uses_om_prefix_for_office_manager(self):
        """Conversations with 'om:' prefix route to the OM bus."""
        cid = make_conversation_id(ConversationType.OFFICE_MANAGER, 'darrell')
        self.assertTrue(cid.startswith('om:'),
            f'Office manager conversation must start with om:, got: {cid!r}')


# ── REST: conversations list ──────────────────────────────────────────────────

class TestRestConversationsList(unittest.TestCase):
    """GET /api/conversations passes ConversationType enum to active_conversations()."""

    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self.db_path = os.path.join(self._tmp, 'messages.db')
        self.bus = SqliteMessageBus(self.db_path)
        self.bus.create_conversation(ConversationType.PROJECT_SESSION, 'sess-a')

    def tearDown(self):
        self.bus.close()
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_type_filter_returns_conversations_of_that_type(self):
        """?type=project_session returns only project_session conversations."""
        bridge = _make_bridge(self._tmp, self._tmp)
        bridge._buses['sess-a'] = self.bus

        async def _run():
            from aiohttp.test_utils import TestClient, TestServer
            app = bridge._build_app()
            async with TestClient(TestServer(app)) as client:
                resp = await client.get('/api/conversations?type=project_session')
                self.assertEqual(resp.status, 200)
                data = await resp.json()
                ids = [c['id'] for c in data]
                expected_id = make_conversation_id(ConversationType.PROJECT_SESSION, 'sess-a')
                self.assertIn(expected_id, ids)

        _run_async(_run())

    def test_type_filter_excludes_other_types(self):
        """?type=subteam does not return project_session conversations."""
        bridge = _make_bridge(self._tmp, self._tmp)
        bridge._buses['sess-a'] = self.bus

        async def _run():
            from aiohttp.test_utils import TestClient, TestServer
            app = bridge._build_app()
            async with TestClient(TestServer(app)) as client:
                resp = await client.get('/api/conversations?type=subteam')
                self.assertEqual(resp.status, 200)
                data = await resp.json()
                session_id = make_conversation_id(ConversationType.PROJECT_SESSION, 'sess-a')
                ids = [c['id'] for c in data]
                self.assertNotIn(session_id, ids)

        _run_async(_run())

    def test_unknown_type_returns_400(self):
        """?type=not_a_type returns HTTP 400."""
        bridge = _make_bridge(self._tmp, self._tmp)

        async def _run():
            from aiohttp.test_utils import TestClient, TestServer
            app = bridge._build_app()
            async with TestClient(TestServer(app)) as client:
                resp = await client.get('/api/conversations?type=not_a_type')
                self.assertEqual(resp.status, 400)

        _run_async(_run())

    def test_no_filter_aggregates_all_buses(self):
        """GET without ?type= returns conversations from all active buses."""
        db2 = os.path.join(self._tmp, 'messages2.db')
        bus2 = SqliteMessageBus(db2)
        self.addCleanup(bus2.close)
        bus2.create_conversation(ConversationType.SUBTEAM, 'team-x')

        bridge = _make_bridge(self._tmp, self._tmp)
        bridge._buses['b1'] = self.bus
        bridge._buses['b2'] = bus2

        async def _run():
            from aiohttp.test_utils import TestClient, TestServer
            app = bridge._build_app()
            async with TestClient(TestServer(app)) as client:
                resp = await client.get('/api/conversations')
                self.assertEqual(resp.status, 200)
                data = await resp.json()
                ids = [c['id'] for c in data]
                session_id = make_conversation_id(ConversationType.PROJECT_SESSION, 'sess-a')
                team_id = make_conversation_id(ConversationType.SUBTEAM, 'team-x')
                self.assertIn(session_id, ids)
                self.assertIn(team_id, ids)

        _run_async(_run())

    def test_active_conversations_receives_enum_not_string(self):
        """Verify the enum path: a raw string breaks active_conversations(); bridge uses enum.

        bridge-api.md: active_conversations takes a ConversationType enum member, not a string.
        Passing a raw string causes an AttributeError (str has no .value). The bridge must
        convert the ?type= query parameter via _resolve_conversation_type before calling the bus.
        """
        bridge = _make_bridge(self._tmp, self._tmp)
        bridge._buses['sess-a'] = self.bus

        async def _run():
            from aiohttp.test_utils import TestClient, TestServer
            app = bridge._build_app()
            async with TestClient(TestServer(app)) as client:
                # Direct test: calling active_conversations with a raw string raises AttributeError
                with self.assertRaises(AttributeError):
                    self.bus.active_conversations('project_session')  # type: ignore
                # Bridge converts to enum first — conversations are found
                resp = await client.get('/api/conversations?type=project_session')
                data = await resp.json()
                self.assertGreater(len(data), 0,
                    'Bridge must use ConversationType enum, not raw string')

        _run_async(_run())


# ── REST: conversation GET ────────────────────────────────────────────────────

class TestRestConversationGet(unittest.TestCase):
    """GET /api/conversations/{id} returns messages since correct timestamp."""

    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self.db_path = os.path.join(self._tmp, 'messages.db')
        self.bus = SqliteMessageBus(self.db_path)
        self.conv = self.bus.create_conversation(ConversationType.PROJECT_SESSION, 'get-test')

    def tearDown(self):
        self.bus.close()
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_returns_all_messages_when_since_is_zero(self):
        """Messages since ts=0 returns all messages in the conversation."""
        self.bus.send(self.conv.id, 'orchestrator', 'First message')

        bridge = _make_bridge(self._tmp, self._tmp)
        bridge._buses['get-test'] = self.bus

        async def _run():
            from aiohttp.test_utils import TestClient, TestServer
            app = bridge._build_app()
            async with TestClient(TestServer(app)) as client:
                resp = await client.get(f'/api/conversations/{self.conv.id}?since=0')
                self.assertEqual(resp.status, 200)
                data = await resp.json()
                self.assertEqual(len(data), 1)
                self.assertEqual(data[0]['content'], 'First message')
                self.assertEqual(data[0]['sender'], 'orchestrator')

        _run_async(_run())

    def test_returns_only_messages_after_timestamp(self):
        """Messages after a cutoff timestamp excludes earlier messages."""
        import time
        self.bus.send(self.conv.id, 'orchestrator', 'Old message')
        cutoff = time.time()
        self.bus.send(self.conv.id, 'human', 'New message')

        bridge = _make_bridge(self._tmp, self._tmp)
        bridge._buses['get-test'] = self.bus

        async def _run():
            from aiohttp.test_utils import TestClient, TestServer
            app = bridge._build_app()
            async with TestClient(TestServer(app)) as client:
                resp = await client.get(f'/api/conversations/{self.conv.id}?since={cutoff}')
                self.assertEqual(resp.status, 200)
                data = await resp.json()
                contents = [m['content'] for m in data]
                self.assertIn('New message', contents)
                self.assertNotIn('Old message', contents)

        _run_async(_run())

    def test_message_fields_are_correctly_serialized(self):
        """Returned message objects have id, conversation, sender, content, timestamp."""
        self.bus.send(self.conv.id, 'orchestrator', 'Check fields')

        bridge = _make_bridge(self._tmp, self._tmp)
        bridge._buses['get-test'] = self.bus

        async def _run():
            from aiohttp.test_utils import TestClient, TestServer
            app = bridge._build_app()
            async with TestClient(TestServer(app)) as client:
                resp = await client.get(f'/api/conversations/{self.conv.id}?since=0')
                data = await resp.json()
                self.assertEqual(len(data), 1)
                msg = data[0]
                for field in ('id', 'conversation', 'sender', 'content', 'timestamp'):
                    self.assertIn(field, msg, f'Missing field: {field}')
                self.assertEqual(msg['content'], 'Check fields')

        _run_async(_run())

    def test_unknown_conversation_returns_200_empty_list(self):
        """Unknown conversation ID returns 200 with empty list (not 404)."""
        bridge = _make_bridge(self._tmp, self._tmp)

        async def _run():
            from aiohttp.test_utils import TestClient, TestServer
            app = bridge._build_app()
            async with TestClient(TestServer(app)) as client:
                resp = await client.get('/api/conversations/session:nonexistent?since=0')
                self.assertEqual(resp.status, 200)
                data = await resp.json()
                self.assertEqual(data, [])

        _run_async(_run())


# ── REST: conversation POST ───────────────────────────────────────────────────

class TestRestConversationPost(unittest.TestCase):
    """POST /api/conversations/{id} writes to SQLite, readable by second bus."""

    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self.db_path = os.path.join(self._tmp, 'messages.db')
        self.bus = SqliteMessageBus(self.db_path)
        self.conv = self.bus.create_conversation(ConversationType.PROJECT_SESSION, 'post-test')

    def tearDown(self):
        self.bus.close()
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_post_persists_message_to_sqlite(self):
        """POSTed message is written to SQLite and readable via the same bus."""
        bridge = _make_bridge(self._tmp, self._tmp)
        bridge._buses['post-test'] = self.bus

        async def _run():
            from aiohttp.test_utils import TestClient, TestServer
            app = bridge._build_app()
            async with TestClient(TestServer(app)) as client:
                resp = await client.post(
                    f'/api/conversations/{self.conv.id}',
                    json={'content': 'Human response here'},
                )
                self.assertEqual(resp.status, 200)
                messages = self.bus.receive(self.conv.id, since_timestamp=0.0)
                contents = [m.content for m in messages]
                self.assertIn('Human response here', contents)

        _run_async(_run())

    def test_post_readable_by_second_bus_instance(self):
        """Message posted via REST is readable by a second SqliteMessageBus on same db."""
        bridge = _make_bridge(self._tmp, self._tmp)
        bridge._buses['post-test'] = self.bus

        async def _run():
            from aiohttp.test_utils import TestClient, TestServer
            app = bridge._build_app()
            async with TestClient(TestServer(app)) as client:
                await client.post(
                    f'/api/conversations/{self.conv.id}',
                    json={'content': 'Cross-instance message'},
                )

        _run_async(_run())
        # Open second bus after the write — must be readable
        bus2 = SqliteMessageBus(self.db_path)
        try:
            messages = bus2.receive(self.conv.id, since_timestamp=0.0)
            contents = [m.content for m in messages]
            self.assertIn('Cross-instance message', contents)
        finally:
            bus2.close()

    def test_post_returns_message_id(self):
        """POST returns JSON object with non-empty 'id' field."""
        bridge = _make_bridge(self._tmp, self._tmp)
        bridge._buses['post-test'] = self.bus

        async def _run():
            from aiohttp.test_utils import TestClient, TestServer
            app = bridge._build_app()
            async with TestClient(TestServer(app)) as client:
                resp = await client.post(
                    f'/api/conversations/{self.conv.id}',
                    json={'content': 'Check ID'},
                )
                data = await resp.json()
                self.assertIn('id', data)
                self.assertIsInstance(data['id'], str)
                self.assertGreater(len(data['id']), 0)

        _run_async(_run())

    def test_post_empty_content_returns_400(self):
        """POST with empty content returns HTTP 400."""
        bridge = _make_bridge(self._tmp, self._tmp)
        bridge._buses['post-test'] = self.bus

        async def _run():
            from aiohttp.test_utils import TestClient, TestServer
            app = bridge._build_app()
            async with TestClient(TestServer(app)) as client:
                resp = await client.post(
                    f'/api/conversations/{self.conv.id}',
                    json={'content': ''},
                )
                self.assertEqual(resp.status, 400)

        _run_async(_run())

    def test_post_unknown_conversation_returns_404(self):
        """POST to an unknown conversation ID returns HTTP 404."""
        bridge = _make_bridge(self._tmp, self._tmp)

        async def _run():
            from aiohttp.test_utils import TestClient, TestServer
            app = bridge._build_app()
            async with TestClient(TestServer(app)) as client:
                resp = await client.post(
                    '/api/conversations/session:does-not-exist',
                    json={'content': 'Hello'},
                )
                self.assertEqual(resp.status, 404)

        _run_async(_run())

    def test_post_sender_is_human(self):
        """Messages written via POST are stored with sender='human'."""
        bridge = _make_bridge(self._tmp, self._tmp)
        bridge._buses['post-test'] = self.bus

        async def _run():
            from aiohttp.test_utils import TestClient, TestServer
            app = bridge._build_app()
            async with TestClient(TestServer(app)) as client:
                await client.post(
                    f'/api/conversations/{self.conv.id}',
                    json={'content': 'Human speaks'},
                )

        _run_async(_run())
        messages = self.bus.receive(self.conv.id, since_timestamp=0.0)
        human_messages = [m for m in messages if m.sender == 'human']
        self.assertEqual(len(human_messages), 1)
        self.assertEqual(human_messages[0].content, 'Human speaks')


# ── REST: artifacts ───────────────────────────────────────────────────────────

class TestRestArtifacts(unittest.TestCase):
    """GET /api/artifacts/{project} parses project.md sections correctly."""

    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        proj_dir = os.path.join(self._tmp, 'myproject')
        os.makedirs(proj_dir)
        with open(os.path.join(proj_dir, 'project.md'), 'w') as f:
            f.write("## Overview\nProject overview text.\n## Goals\nBe better.\n")

    def tearDown(self):
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_returns_parsed_section_dict(self):
        """Sections from project.md returned as {heading: body} dict."""
        bridge = _make_bridge(self._tmp, self._tmp)

        async def _run():
            from aiohttp.test_utils import TestClient, TestServer
            app = bridge._build_app()
            async with TestClient(TestServer(app)) as client:
                resp = await client.get('/api/artifacts/myproject')
                self.assertEqual(resp.status, 200)
                data = await resp.json()
                self.assertIn('Overview', data)
                self.assertIn('Goals', data)
                self.assertEqual(data['Overview'], 'Project overview text.')
                self.assertEqual(data['Goals'], 'Be better.')

        _run_async(_run())

    def test_missing_project_returns_404(self):
        """GET /api/artifacts/{nonexistent} returns HTTP 404."""
        bridge = _make_bridge(self._tmp, self._tmp)

        async def _run():
            from aiohttp.test_utils import TestClient, TestServer
            app = bridge._build_app()
            async with TestClient(TestServer(app)) as client:
                resp = await client.get('/api/artifacts/nonexistent')
                self.assertEqual(resp.status, 404)

        _run_async(_run())


# ── REST: config ──────────────────────────────────────────────────────────────

class TestRestConfig(unittest.TestCase):
    """GET /api/config returns correct structure from known YAML fixtures."""

    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        teaparty_dir = os.path.join(self._tmp, '.teaparty')
        os.makedirs(teaparty_dir)
        with open(os.path.join(teaparty_dir, 'teaparty.yaml'), 'w') as f:
            f.write("""\
name: Test Org
description: Test organization
lead: lead-agent
decider: darrell
agents:
  - lead-agent
humans:
  - name: darrell
    role: decider
skills: []
hooks: []
scheduled: []
projects: []
workgroups: []
""")

    def tearDown(self):
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_config_returns_management_team_and_projects(self):
        """GET /api/config returns management_team with name/lead and projects list."""
        bridge = _make_bridge(
            os.path.join(self._tmp, '.teaparty'), self._tmp
        )

        async def _run():
            from aiohttp.test_utils import TestClient, TestServer
            app = bridge._build_app()
            async with TestClient(TestServer(app)) as client:
                resp = await client.get('/api/config')
                self.assertEqual(resp.status, 200)
                data = await resp.json()
                self.assertIn('management_team', data)
                self.assertIn('projects', data)
                mt = data['management_team']
                self.assertEqual(mt['name'], 'Test Org')
                self.assertEqual(mt['lead'], 'lead-agent')
                self.assertIsInstance(mt['agents'], list)
                self.assertIn('lead-agent', mt['agents'])

        _run_async(_run())

    def test_config_missing_yaml_returns_null_team_and_empty_projects(self):
        """GET /api/config with missing teaparty.yaml returns null management_team."""
        bridge = _make_bridge(
            os.path.join(self._tmp, 'nonexistent'), self._tmp
        )

        async def _run():
            from aiohttp.test_utils import TestClient, TestServer
            app = bridge._build_app()
            async with TestClient(TestServer(app)) as client:
                resp = await client.get('/api/config')
                self.assertEqual(resp.status, 200)
                data = await resp.json()
                self.assertIsNone(data['management_team'])
                self.assertEqual(data['projects'], [])

        _run_async(_run())


# ── REST: workgroups ──────────────────────────────────────────────────────────

class TestRestWorkgroups(unittest.TestCase):
    """GET /api/workgroups returns correct structure from known YAML fixtures."""

    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        teaparty_dir = os.path.join(self._tmp, '.teaparty')
        workgroups_dir = os.path.join(teaparty_dir, 'workgroups')
        os.makedirs(workgroups_dir)
        # Management team references workgroup by config path
        with open(os.path.join(teaparty_dir, 'teaparty.yaml'), 'w') as f:
            f.write("""\
name: Test Org
description: Test
lead: lead-agent
decider: darrell
agents:
  - lead-agent
humans: []
skills: []
hooks: []
scheduled: []
projects: []
workgroups:
  - name: Backend
    config: workgroups/backend.yaml
""")
        with open(os.path.join(workgroups_dir, 'backend.yaml'), 'w') as f:
            f.write("""\
name: Backend
description: Backend workgroup
lead: backend-lead
agents:
  - backend-lead
skills: []
norms: {}
budget: {}
""")

    def tearDown(self):
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_workgroups_returns_list_with_workgroup_names(self):
        """GET /api/workgroups returns a list containing workgroup name."""
        bridge = _make_bridge(
            os.path.join(self._tmp, '.teaparty'), self._tmp
        )

        async def _run():
            from aiohttp.test_utils import TestClient, TestServer
            app = bridge._build_app()
            async with TestClient(TestServer(app)) as client:
                resp = await client.get('/api/workgroups')
                self.assertEqual(resp.status, 200)
                data = await resp.json()
                self.assertIsInstance(data, list)
                names = [w['name'] for w in data]
                self.assertIn('Backend', names)

        _run_async(_run())

    def test_workgroups_returns_empty_list_when_none_configured(self):
        """GET /api/workgroups returns [] when no workgroups are configured."""
        # Create team with no workgroups
        alt_home = os.path.join(self._tmp, 'alt')
        os.makedirs(alt_home)
        with open(os.path.join(alt_home, 'teaparty.yaml'), 'w') as f:
            f.write("name: Empty\ndescription: x\nlead: x\ndecider: x\nagents: []\n"
                    "humans: []\nskills: []\nhooks: []\nscheduled: []\nprojects: []\n"
                    "workgroups: []\n")
        bridge = _make_bridge(alt_home, self._tmp)

        async def _run():
            from aiohttp.test_utils import TestClient, TestServer
            app = bridge._build_app()
            async with TestClient(TestServer(app)) as client:
                resp = await client.get('/api/workgroups')
                self.assertEqual(resp.status, 200)
                data = await resp.json()
                self.assertEqual(data, [])

        _run_async(_run())


# ── REST: state ───────────────────────────────────────────────────────────────

class TestRestState(unittest.TestCase):
    """GET /api/state returns correct session structure from a known worktrees.json."""

    def setUp(self):
        # Directory layout:
        #   root/                    ← repo_root (StateReader manifest_path)
        #   root/worktrees.json      ← manifest
        #   root/projects/           ← projects_dir (bridge projects_dir)
        #   root/projects/POC/       ← poc_root (StateReader)
        #   root/projects/POC/.sessions/SESID/
        self._root = tempfile.mkdtemp()
        self._projects_dir = os.path.join(self._root, 'projects')
        os.makedirs(self._projects_dir)

    def tearDown(self):
        shutil.rmtree(self._root, ignore_errors=True)

    def _make_session_fixture(self, session_id='20260101-120000', cfa_state='PLAN_ASSERT'):
        """Create a minimal session dir and matching worktrees.json."""
        sessions_dir = os.path.join(self._projects_dir, 'POC', '.sessions', session_id)
        os.makedirs(sessions_dir)
        with open(os.path.join(sessions_dir, '.cfa-state.json'), 'w') as f:
            json.dump({
                'phase': 'planning',
                'state': cfa_state,
                'actor': 'human',
                'history': [],
                'backtrack_count': 0,
            }, f)
        # StateReader: repo_root = dirname(dirname(poc_root))
        #   poc_root = projects_dir/POC
        #   repo_root = dirname(projects_dir) = self._root
        manifest = {
            'worktrees': [{
                'name': f'POC-{session_id}',
                'path': sessions_dir,
                'type': 'session',
                'session_id': session_id,
                'task': 'Test task',
                'status': 'active',
            }]
        }
        with open(os.path.join(self._root, 'worktrees.json'), 'w') as f:
            json.dump(manifest, f)
        return session_id

    def test_state_returns_list_of_projects(self):
        """GET /api/state returns a JSON array of project objects."""
        self._make_session_fixture()
        bridge = _make_bridge(self._root, self._projects_dir)

        async def _run():
            from aiohttp.test_utils import TestClient, TestServer
            app = bridge._build_app()
            async with TestClient(TestServer(app)) as client:
                resp = await client.get('/api/state')
                self.assertEqual(resp.status, 200)
                data = await resp.json()
                self.assertIsInstance(data, list)

        _run_async(_run())

    def test_state_project_contains_sessions(self):
        """GET /api/state project includes sessions array with the fixture session."""
        session_id = self._make_session_fixture()
        bridge = _make_bridge(self._root, self._projects_dir)

        async def _run():
            from aiohttp.test_utils import TestClient, TestServer
            app = bridge._build_app()
            async with TestClient(TestServer(app)) as client:
                resp = await client.get('/api/state')
                data = await resp.json()
                poc = next((p for p in data if p['slug'] == 'POC'), None)
                self.assertIsNotNone(poc, 'POC project missing from /api/state')
                session_ids = [s['session_id'] for s in poc['sessions']]
                self.assertIn(session_id, session_ids)

        _run_async(_run())

    def test_state_session_has_cfa_fields_from_fixture(self):
        """Session objects include cfa_phase/cfa_state/cfa_actor from .cfa-state.json."""
        session_id = self._make_session_fixture()
        bridge = _make_bridge(self._root, self._projects_dir)

        async def _run():
            from aiohttp.test_utils import TestClient, TestServer
            app = bridge._build_app()
            async with TestClient(TestServer(app)) as client:
                resp = await client.get('/api/state')
                data = await resp.json()
                poc = next(p for p in data if p['slug'] == 'POC')
                session = next(s for s in poc['sessions'] if s['session_id'] == session_id)
                self.assertIn('cfa_phase', session)
                self.assertIn('cfa_state', session)
                self.assertIn('cfa_actor', session)
                self.assertEqual(session['cfa_phase'], 'planning')
                self.assertEqual(session['cfa_state'], 'PLAN_ASSERT')

        _run_async(_run())

    def test_state_project_has_required_fields(self):
        """Project objects include slug, sessions, active_count, attention_count."""
        self._make_session_fixture()
        bridge = _make_bridge(self._root, self._projects_dir)

        async def _run():
            from aiohttp.test_utils import TestClient, TestServer
            app = bridge._build_app()
            async with TestClient(TestServer(app)) as client:
                resp = await client.get('/api/state')
                data = await resp.json()
                poc = next(p for p in data if p['slug'] == 'POC')
                for field in ('slug', 'sessions', 'active_count', 'attention_count'):
                    self.assertIn(field, poc, f'Missing field: {field}')

        _run_async(_run())


# ── StatePoller WebSocket events ──────────────────────────────────────────────

def _make_session(session_id, cfa_state='', cfa_phase='', heartbeat_status='alive',
                  infra_dir=''):
    """Create a duck-typed session for StatePoller tests."""
    s = MagicMock()
    s.session_id = session_id
    s.cfa_state = cfa_state
    s.cfa_phase = cfa_phase
    s.heartbeat_status = heartbeat_status
    s.infra_dir = infra_dir
    return s


def _make_project(sessions):
    p = MagicMock()
    p.sessions = sessions
    return p


class TestStatePollerEvents(unittest.TestCase):
    """StatePoller emits correct WebSocket events on state transitions."""

    def setUp(self):
        self.events = []

        async def broadcast(event):
            self.events.append(event)

        reader = MagicMock()
        self.poller = StatePoller(reader, broadcast, poll_interval=1.0)

    def _run_polls(self, sessions_per_poll):
        """Run a sequence of polls, each with a different session list."""
        async def _run():
            for sessions in sessions_per_poll:
                self.poller._state_reader.reload.return_value = [_make_project(sessions)]
                await self.poller.poll_once()

        _run_async(_run())

    def test_no_events_on_first_poll(self):
        """No events emitted on the first poll — no baseline to diff against."""
        sessions = [_make_session('s1', cfa_state='PLAN_ASSERT', cfa_phase='planning')]
        self._run_polls([sessions])
        self.assertEqual(self.events, [])

    def test_state_changed_fires_on_cfa_state_change(self):
        """state_changed event fires when CfA state changes between polls."""
        s1 = [_make_session('s1', cfa_state='PLAN_ASSERT', cfa_phase='planning')]
        s2 = [_make_session('s1', cfa_state='INTENT_ASSERT', cfa_phase='intent')]
        self._run_polls([s1, s2])
        state_events = [e for e in self.events if e['type'] == 'state_changed']
        self.assertEqual(len(state_events), 1)
        self.assertEqual(state_events[0]['state'], 'INTENT_ASSERT')
        self.assertEqual(state_events[0]['phase'], 'intent')
        self.assertEqual(state_events[0]['session_id'], 's1')

    def test_state_changed_fires_on_cfa_phase_change(self):
        """state_changed event fires when CfA phase changes even if state stays same."""
        s1 = [_make_session('s1', cfa_state='PLAN_ASSERT', cfa_phase='planning')]
        s2 = [_make_session('s1', cfa_state='PLAN_ASSERT', cfa_phase='execution')]
        self._run_polls([s1, s2])
        state_events = [e for e in self.events if e['type'] == 'state_changed']
        self.assertEqual(len(state_events), 1)

    def test_no_state_changed_when_state_and_phase_unchanged(self):
        """No state_changed event emitted across three polls with identical state."""
        sessions = [_make_session('s1', cfa_state='PLAN_ASSERT', cfa_phase='planning')]
        self._run_polls([sessions, sessions, sessions])
        state_events = [e for e in self.events if e['type'] == 'state_changed']
        self.assertEqual(len(state_events), 0)

    def test_heartbeat_fires_only_on_liveness_transition(self):
        """heartbeat event fires exactly once when heartbeat_status transitions."""
        s_alive = [_make_session('s1', cfa_state='PLAN_ASSERT', heartbeat_status='alive')]
        s_stale = [_make_session('s1', cfa_state='PLAN_ASSERT', heartbeat_status='stale')]
        # Poll 3 is still stale — no new event
        self._run_polls([s_alive, s_stale, s_stale])
        hb_events = [e for e in self.events if e['type'] == 'heartbeat']
        self.assertEqual(len(hb_events), 1)
        self.assertEqual(hb_events[0]['status'], 'stale')
        self.assertEqual(hb_events[0]['session_id'], 's1')

    def test_no_heartbeat_when_liveness_status_unchanged(self):
        """No heartbeat event emitted across three polls with identical heartbeat status."""
        s = [_make_session('s1', cfa_state='PLAN_ASSERT', heartbeat_status='alive')]
        self._run_polls([s, s, s])
        hb_events = [e for e in self.events if e['type'] == 'heartbeat']
        self.assertEqual(len(hb_events), 0)

    def test_session_completed_fires_on_completed_work(self):
        """session_completed event fires when session enters COMPLETED_WORK state."""
        s1 = [_make_session('s1', cfa_state='PLAN_ASSERT')]
        s2 = [_make_session('s1', cfa_state='COMPLETED_WORK')]
        self._run_polls([s1, s2])
        completion_events = [e for e in self.events if e['type'] == 'session_completed']
        self.assertEqual(len(completion_events), 1)
        self.assertEqual(completion_events[0]['terminal_state'], 'COMPLETED_WORK')
        self.assertEqual(completion_events[0]['session_id'], 's1')

    def test_session_completed_fires_on_withdrawn(self):
        """session_completed event fires when session enters WITHDRAWN state."""
        s1 = [_make_session('s1', cfa_state='PLAN_ASSERT')]
        s2 = [_make_session('s1', cfa_state='WITHDRAWN')]
        self._run_polls([s1, s2])
        completion_events = [e for e in self.events if e['type'] == 'session_completed']
        self.assertEqual(len(completion_events), 1)
        self.assertEqual(completion_events[0]['terminal_state'], 'WITHDRAWN')

    def test_no_duplicate_session_completed_on_repeated_terminal_polls(self):
        """session_completed fires once — subsequent polls in terminal state emit nothing."""
        s1 = [_make_session('s1', cfa_state='PLAN_ASSERT')]
        s2 = [_make_session('s1', cfa_state='COMPLETED_WORK')]
        s3 = [_make_session('s1', cfa_state='COMPLETED_WORK')]  # Same terminal state
        self._run_polls([s1, s2, s3])
        completion_events = [e for e in self.events if e['type'] == 'session_completed']
        self.assertEqual(len(completion_events), 1)

    def test_bus_closed_when_session_reaches_terminal_state(self):
        """StatePoller closes the session bus when session reaches a terminal state."""
        mock_bus = MagicMock()
        s1 = [_make_session('s1', cfa_state='PLAN_ASSERT', infra_dir='/fake/infra')]
        s2 = [_make_session('s1', cfa_state='COMPLETED_WORK', infra_dir='/fake/infra')]

        async def _run():
            self.poller._state_reader.reload.return_value = [_make_project(s1)]
            await self.poller.poll_once()
            # Inject bus as if bus_factory had opened it
            self.poller._buses['s1'] = mock_bus
            self.poller._state_reader.reload.return_value = [_make_project(s2)]
            await self.poller.poll_once()

        _run_async(_run())
        mock_bus.close.assert_called_once()
        self.assertNotIn('s1', self.poller._buses)

    def test_no_event_emitted_on_session_first_seen_even_if_terminal(self):
        """A session first seen already in a terminal state does not emit events."""
        s1 = [_make_session('s1', cfa_state='COMPLETED_WORK')]
        self._run_polls([s1])
        self.assertEqual(self.events, [])


if __name__ == '__main__':
    unittest.main()
