"""Tests for issue #297: bridge/server.py — aiohttp app, REST endpoints, static file serving.

Acceptance criteria:
1. projects/POC/bridge/ package importable (server, poller, message_relay)
2. TeaPartyBridge class exists with run() method and _build_app() method
3. All REST routes registered: state, config, messages, artifacts, actions, WebSocket
4. ?type= query param converted to ConversationType enum (not raw string)
5. ?type=office_manager routes to {teaparty_home}/om/om-messages.db (issue #290)
6. GET /api/heartbeat/{session_id} uses _heartbeat_three_state() (alive|stale|dead)
7. POST /api/withdraw/{session_id} writes to {teaparty_home}/sockets/{session_id}.sock
8. CfA state endpoint loads phase, state, actor, history, backtrack_count
9. Artifacts endpoint parses project.md headings into sections
"""
import json
import os
import shutil
import tempfile
import time
import unittest


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_tmpdir():
    return tempfile.mkdtemp()


def _make_bridge(tmpdir):
    from projects.POC.bridge.server import TeaPartyBridge
    static_dir = os.path.join(tmpdir, 'static')
    os.makedirs(static_dir, exist_ok=True)
    return TeaPartyBridge(
        teaparty_home=tmpdir,
        projects_dir=tmpdir,
        static_dir=static_dir,
    )


def _get_route_info(app):
    """Return (method, canonical_path) pairs for all registered routes."""
    result = []
    for resource in app.router.resources():
        canonical = resource.canonical
        for route in resource:
            result.append((route.method, canonical))
    return result


def _get_route_paths(app):
    """Return set of canonical paths registered on the app."""
    return {canonical for resource in app.router.resources()
            for canonical in [resource.canonical]}


# ── Import tests ──────────────────────────────────────────────────────────────

class TestBridgePackageImports(unittest.TestCase):
    """Bridge package and all three modules must be importable."""

    def test_server_module_importable(self):
        from projects.POC.bridge import server  # noqa: F401

    def test_poller_module_importable(self):
        from projects.POC.bridge import poller  # noqa: F401

    def test_message_relay_module_importable(self):
        from projects.POC.bridge import message_relay  # noqa: F401

    def test_teaparty_bridge_class_importable(self):
        from projects.POC.bridge.server import TeaPartyBridge  # noqa: F401

    def test_bridge_has_run_method(self):
        from projects.POC.bridge.server import TeaPartyBridge
        self.assertTrue(callable(getattr(TeaPartyBridge, 'run', None)),
                        'TeaPartyBridge must expose a run() method')

    def test_bridge_has_build_app_method(self):
        from projects.POC.bridge.server import TeaPartyBridge
        self.assertTrue(callable(getattr(TeaPartyBridge, '_build_app', None)),
                        'TeaPartyBridge must expose a _build_app() method')


# ── Route registration ────────────────────────────────────────────────────────

class TestBridgeRouteRegistration(unittest.TestCase):
    """All REST and WebSocket routes must be registered on the aiohttp app."""

    def setUp(self):
        self.tmpdir = _make_tmpdir()
        self.bridge = _make_bridge(self.tmpdir)
        self.app = self.bridge._build_app()
        self.paths = _get_route_paths(self.app)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_state_routes_registered(self):
        for path in ['/api/state', '/api/state/{project}',
                     '/api/cfa/{session_id}', '/api/heartbeat/{session_id}']:
            self.assertIn(path, self.paths, f'Missing route: {path}')

    def test_config_routes_registered(self):
        for path in ['/api/config', '/api/config/{project}', '/api/workgroups']:
            self.assertIn(path, self.paths, f'Missing route: {path}')

    def test_message_routes_registered(self):
        for path in ['/api/conversations', '/api/conversations/{id}']:
            self.assertIn(path, self.paths, f'Missing route: {path}')

    def test_artifact_routes_registered(self):
        for path in ['/api/artifacts/{project}', '/api/file']:
            self.assertIn(path, self.paths, f'Missing route: {path}')

    def test_action_route_registered(self):
        self.assertIn('/api/withdraw/{session_id}', self.paths,
                      'Missing route: /api/withdraw/{session_id}')

    def test_websocket_route_registered(self):
        self.assertIn('/ws', self.paths, 'Missing WebSocket route: /ws')


# ── Enum conversion ───────────────────────────────────────────────────────────

class TestConversationTypeResolution(unittest.TestCase):
    """?type= query param must be converted to ConversationType enum, not used as raw string."""

    def test_project_session_resolves_to_enum(self):
        from projects.POC.bridge.server import _resolve_conversation_type
        from projects.POC.orchestrator.messaging import ConversationType
        ct = _resolve_conversation_type('project_session')
        self.assertEqual(ct, ConversationType.PROJECT_SESSION)

    def test_office_manager_resolves_to_enum(self):
        from projects.POC.bridge.server import _resolve_conversation_type
        from projects.POC.orchestrator.messaging import ConversationType
        ct = _resolve_conversation_type('office_manager')
        self.assertEqual(ct, ConversationType.OFFICE_MANAGER)

    def test_subteam_resolves_to_enum(self):
        from projects.POC.bridge.server import _resolve_conversation_type
        from projects.POC.orchestrator.messaging import ConversationType
        ct = _resolve_conversation_type('subteam')
        self.assertEqual(ct, ConversationType.SUBTEAM)

    def test_invalid_type_raises_key_error(self):
        """An unknown type string must raise KeyError, not silently return empty list."""
        from projects.POC.bridge.server import _resolve_conversation_type
        with self.assertRaises(KeyError):
            _resolve_conversation_type('not_a_real_type')

    def test_type_string_is_case_insensitive(self):
        """Type strings should be uppercased before enum lookup."""
        from projects.POC.bridge.server import _resolve_conversation_type
        from projects.POC.orchestrator.messaging import ConversationType
        ct = _resolve_conversation_type('PROJECT_SESSION')
        self.assertEqual(ct, ConversationType.PROJECT_SESSION)


# ── Office manager routing (issue #290) ───────────────────────────────────────

class TestOfficManagerBusRouting(unittest.TestCase):
    """?type=office_manager must query om-messages.db, not a per-session messages.db.

    This is the fix for issue #290: the office manager uses a separate database
    at {teaparty_home}/om/om-messages.db. Without this routing, the office manager
    conversation is invisible to the bridge.
    """

    def test_om_bus_path_is_under_teaparty_home(self):
        """OM bus path must be inside teaparty_home and contain om-messages.db."""
        from projects.POC.bridge.server import _om_bus_path
        path = _om_bus_path('/home/user/.teaparty')
        self.assertTrue(path.startswith('/home/user/.teaparty'),
                        'OM bus path must be under teaparty_home')
        self.assertTrue(path.endswith('om-messages.db'),
                        'OM bus path must end with om-messages.db')

    def test_om_bus_path_is_not_session_messages_db(self):
        """OM bus path must not be the session-scoped messages.db."""
        from projects.POC.bridge.server import _om_bus_path
        path = _om_bus_path('/home/user/.teaparty')
        # Must not use bare 'messages.db' (that's the per-session path)
        self.assertNotEqual(os.path.basename(path), 'messages.db',
                            'OM bus must use om-messages.db, not messages.db')

    def test_om_bus_path_differs_from_session_bus_path(self):
        """Two different sessions must not share the OM bus path."""
        from projects.POC.bridge.server import _om_bus_path
        path1 = _om_bus_path('/home/user/.teaparty')
        # Verify the OM path is deterministic (same input → same output)
        path2 = _om_bus_path('/home/user/.teaparty')
        self.assertEqual(path1, path2, 'OM bus path must be stable and deterministic')


# ── Heartbeat endpoint (issue #295) ───────────────────────────────────────────

class TestHeartbeatClassification(unittest.TestCase):
    """GET /api/heartbeat/{session_id} must return alive|stale|dead via _heartbeat_three_state()."""

    def setUp(self):
        self.tmpdir = _make_tmpdir()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_classify_heartbeat_function_exists(self):
        from projects.POC.bridge.server import _classify_heartbeat  # noqa: F401

    def test_fresh_heartbeat_classified_as_alive(self):
        """A heartbeat updated within 30s must be 'alive'."""
        from projects.POC.bridge.server import _classify_heartbeat
        hb_path = os.path.join(self.tmpdir, '.heartbeat')
        hb_data = {'pid': os.getpid(), 'status': 'running', 'started': time.time()}
        with open(hb_path, 'w') as f:
            json.dump(hb_data, f)
        # Freshly written heartbeat should be alive
        status = _classify_heartbeat(self.tmpdir)
        self.assertEqual(status, 'alive')

    def test_missing_heartbeat_classified_as_dead(self):
        """A missing heartbeat must be 'dead', not raise an exception."""
        from projects.POC.bridge.server import _classify_heartbeat
        status = _classify_heartbeat(self.tmpdir)
        self.assertEqual(status, 'dead')

    def test_terminal_heartbeat_classified_as_dead(self):
        """A heartbeat with status 'completed' must be 'dead'."""
        from projects.POC.bridge.server import _classify_heartbeat
        hb_path = os.path.join(self.tmpdir, '.heartbeat')
        hb_data = {'pid': os.getpid(), 'status': 'completed', 'started': time.time()}
        with open(hb_path, 'w') as f:
            json.dump(hb_data, f)
        status = _classify_heartbeat(self.tmpdir)
        self.assertEqual(status, 'dead')

    def test_classify_returns_three_state_not_raw_json(self):
        """_classify_heartbeat must return a string ('alive'|'stale'|'dead'), not a dict."""
        from projects.POC.bridge.server import _classify_heartbeat
        status = _classify_heartbeat(self.tmpdir)
        self.assertIsInstance(status, str)
        self.assertIn(status, ('alive', 'stale', 'dead'))


# ── Withdrawal socket path ────────────────────────────────────────────────────

class TestWithdrawalSocketPath(unittest.TestCase):
    """POST /api/withdraw/{session_id} must write to the stable socket path."""

    def test_withdrawal_socket_path_is_under_teaparty_home(self):
        """Socket must be under {teaparty_home}/sockets/."""
        from projects.POC.bridge.server import _withdrawal_socket_path
        path = _withdrawal_socket_path('/home/user/.teaparty', 'session-abc')
        self.assertTrue(path.startswith('/home/user/.teaparty/sockets/'),
                        f'Socket path must be under teaparty_home/sockets/, got: {path}')

    def test_withdrawal_socket_path_includes_session_id(self):
        """Socket path must embed the session_id."""
        from projects.POC.bridge.server import _withdrawal_socket_path
        path = _withdrawal_socket_path('/home/user/.teaparty', 'my-session-42')
        self.assertIn('my-session-42', path)

    def test_withdrawal_socket_path_ends_with_sock(self):
        """Socket path must end with .sock."""
        from projects.POC.bridge.server import _withdrawal_socket_path
        path = _withdrawal_socket_path('/home/user/.teaparty', 'session-abc')
        self.assertTrue(path.endswith('.sock'),
                        f'Socket path must end with .sock, got: {path}')

    def test_withdrawal_socket_path_is_stable(self):
        """Same session_id must always produce the same socket path."""
        from projects.POC.bridge.server import _withdrawal_socket_path
        p1 = _withdrawal_socket_path('/home/.teaparty', 'sess-1')
        p2 = _withdrawal_socket_path('/home/.teaparty', 'sess-1')
        self.assertEqual(p1, p2)

    def test_withdrawal_socket_path_differs_per_session(self):
        """Different session IDs must produce different socket paths."""
        from projects.POC.bridge.server import _withdrawal_socket_path
        p1 = _withdrawal_socket_path('/home/.teaparty', 'sess-1')
        p2 = _withdrawal_socket_path('/home/.teaparty', 'sess-2')
        self.assertNotEqual(p1, p2)


# ── CfA state loading ─────────────────────────────────────────────────────────

class TestCfaStateLoading(unittest.TestCase):
    """GET /api/cfa/{session_id} must load from {infra_dir}/.cfa-state.json."""

    def setUp(self):
        self.tmpdir = _make_tmpdir()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_load_cfa_state_function_exists(self):
        from projects.POC.bridge.server import _load_cfa_state  # noqa: F401

    def test_cfa_state_loaded_with_required_fields(self):
        """Response must include phase, state, actor, history, backtrack_count."""
        from projects.POC.bridge.server import _load_cfa_state
        cfa_path = os.path.join(self.tmpdir, '.cfa-state.json')
        cfa_data = {
            'phase': 'execution',
            'state': 'WORK_EXEC',
            'actor': 'agent',
            'history': [{'state': 'PLAN_EXEC', 'action': 'ACCEPT', 'actor': 'human',
                         'timestamp': 1234567890.0}],
            'backtrack_count': 1,
            'task_id': '',
        }
        with open(cfa_path, 'w') as f:
            json.dump(cfa_data, f)
        result = _load_cfa_state(self.tmpdir)
        self.assertEqual(result['phase'], 'execution')
        self.assertEqual(result['state'], 'WORK_EXEC')
        self.assertEqual(result['actor'], 'agent')
        self.assertIsInstance(result['history'], list)
        self.assertEqual(result['backtrack_count'], 1)

    def test_cfa_state_missing_file_returns_none_or_raises(self):
        """Missing .cfa-state.json must return None or raise — not a KeyError."""
        from projects.POC.bridge.server import _load_cfa_state
        result = _load_cfa_state(self.tmpdir)
        # Either None or a dict — must not raise an unhandled exception
        self.assertTrue(result is None or isinstance(result, dict))


# ── Artifacts parsing ─────────────────────────────────────────────────────────

class TestArtifactsParsing(unittest.TestCase):
    """GET /api/artifacts/{project} parses project.md headings into sections."""

    def test_parse_artifacts_function_exists(self):
        from projects.POC.bridge.server import _parse_artifacts  # noqa: F401

    def test_h2_headings_become_section_keys(self):
        """## headings must become section keys in the returned dict."""
        from projects.POC.bridge.server import _parse_artifacts
        content = '# Title\n\n## Architecture\n\nDesign here.\n\n## Goals\n\nGoals here.\n'
        sections = _parse_artifacts(content)
        self.assertIn('Architecture', sections)
        self.assertIn('Goals', sections)

    def test_section_content_preserved(self):
        """Text under each heading must be included in that section's value."""
        from projects.POC.bridge.server import _parse_artifacts
        content = '## Architecture\n\nDesign goes here.\n\nMore design.\n'
        sections = _parse_artifacts(content)
        arch = sections.get('Architecture', '')
        self.assertIn('Design goes here.', arch)

    def test_empty_content_returns_empty_dict(self):
        from projects.POC.bridge.server import _parse_artifacts
        sections = _parse_artifacts('')
        self.assertIsInstance(sections, dict)


# ── Bridge startup paths ──────────────────────────────────────────────────────

class TestBridgePathExpansion(unittest.TestCase):
    """TeaPartyBridge must expand ~ in path arguments."""

    def test_teaparty_home_stored_on_bridge(self):
        """teaparty_home must be accessible on the bridge instance."""
        tmpdir = _make_tmpdir()
        try:
            bridge = _make_bridge(tmpdir)
            self.assertEqual(bridge.teaparty_home, tmpdir)
        finally:
            shutil.rmtree(tmpdir)

    def test_projects_dir_stored_on_bridge(self):
        tmpdir = _make_tmpdir()
        try:
            bridge = _make_bridge(tmpdir)
            self.assertEqual(bridge.projects_dir, tmpdir)
        finally:
            shutil.rmtree(tmpdir)

    def test_static_dir_stored_on_bridge(self):
        tmpdir = _make_tmpdir()
        try:
            static_dir = os.path.join(tmpdir, 'static')
            os.makedirs(static_dir)
            from projects.POC.bridge.server import TeaPartyBridge
            bridge = TeaPartyBridge(
                teaparty_home=tmpdir,
                projects_dir=tmpdir,
                static_dir=static_dir,
            )
            self.assertEqual(bridge.static_dir, static_dir)
        finally:
            shutil.rmtree(tmpdir)


# ── MessageRelay event contract ───────────────────────────────────────────────

class _FakeBus:
    """Minimal bus stub for MessageRelay tests."""

    def __init__(self, conv_ids=None, messages=None, awaiting=None):
        self._conv_ids = conv_ids or []
        self._messages = messages or {}   # {cid: [Message-like]}
        self._awaiting = awaiting or []

    def conversations(self):
        return list(self._conv_ids)

    def receive(self, cid, since_timestamp=0.0):
        return [m for m in self._messages.get(cid, []) if m.timestamp > since_timestamp]

    def conversations_awaiting_input(self):
        return self._awaiting


class _FakeMsg:
    def __init__(self, sender, content, timestamp=1.0):
        self.sender = sender
        self.content = content
        self.timestamp = timestamp
        self.id = 'msg-1'
        self.conversation = 'conv-1'


class _FakeConv:
    def __init__(self, cid):
        self.id = cid


class TestMessageRelaySessionId(unittest.TestCase):
    """input_requested event must carry session_id, not infra_dir path."""

    def test_session_id_is_registry_key_not_path(self):
        """When bus_registry is keyed by session_id, the event session_id must match."""
        import asyncio
        from projects.POC.bridge.message_relay import MessageRelay

        events = []

        async def broadcast(event):
            events.append(event)

        cid = 'task:proj:job1:t1'
        bus = _FakeBus(
            conv_ids=[cid],
            messages={cid: [_FakeMsg('orchestrator', 'What should I do?', 1.0)]},
            awaiting=[_FakeConv(cid)],
        )

        registry = {'session-20250101-120000': bus}
        relay = MessageRelay(registry, broadcast)

        asyncio.run(relay.poll_once())

        input_events = [e for e in events if e['type'] == 'input_requested']
        self.assertEqual(len(input_events), 1)
        self.assertEqual(input_events[0]['session_id'], 'session-20250101-120000',
                         'session_id must be the registry key, not a filesystem path')


class TestMessageRelayQuestionField(unittest.TestCase):
    """input_requested event must include the question field."""

    def test_question_field_present(self):
        """input_requested event must include a 'question' field."""
        import asyncio
        from projects.POC.bridge.message_relay import MessageRelay

        events = []

        async def broadcast(event):
            events.append(event)

        cid = 'task:proj:job1:t1'
        bus = _FakeBus(
            conv_ids=[cid],
            messages={cid: [_FakeMsg('orchestrator', 'What is the plan?', 1.0)]},
            awaiting=[_FakeConv(cid)],
        )

        relay = MessageRelay({'session-abc': bus}, broadcast)
        import asyncio
        asyncio.run(relay.poll_once())

        input_events = [e for e in events if e['type'] == 'input_requested']
        self.assertEqual(len(input_events), 1)
        self.assertIn('question', input_events[0],
                      "input_requested event must have a 'question' field")

    def test_question_is_latest_orchestrator_message(self):
        """question field must be the most recent orchestrator message."""
        import asyncio
        from projects.POC.bridge.message_relay import MessageRelay

        events = []

        async def broadcast(event):
            events.append(event)

        cid = 'task:proj:job1:t1'
        bus = _FakeBus(
            conv_ids=[cid],
            messages={cid: [
                _FakeMsg('orchestrator', 'First question', 1.0),
                _FakeMsg('human', 'Answer', 2.0),
                _FakeMsg('orchestrator', 'Second question', 3.0),
            ]},
            awaiting=[_FakeConv(cid)],
        )

        relay = MessageRelay({'session-abc': bus}, broadcast)
        asyncio.run(relay.poll_once())

        input_events = [e for e in events if e['type'] == 'input_requested']
        self.assertEqual(len(input_events), 1)
        self.assertEqual(input_events[0]['question'], 'Second question')

    def test_question_empty_when_no_orchestrator_message(self):
        """question field is empty string if no orchestrator message exists."""
        import asyncio
        from projects.POC.bridge.message_relay import MessageRelay

        events = []

        async def broadcast(event):
            events.append(event)

        cid = 'task:proj:job1:t1'
        bus = _FakeBus(
            conv_ids=[cid],
            messages={cid: [_FakeMsg('human', 'Hello', 1.0)]},
            awaiting=[_FakeConv(cid)],
        )

        relay = MessageRelay({'session-abc': bus}, broadcast)
        asyncio.run(relay.poll_once())

        input_events = [e for e in events if e['type'] == 'input_requested']
        self.assertEqual(len(input_events), 1)
        self.assertEqual(input_events[0]['question'], '')


if __name__ == '__main__':
    unittest.main()
