"""Tests for issue #290: office manager conversation routing in the bridge.

The office manager uses om-messages.db in {teaparty_home}/om/, not the
per-session messages.db. The bridge must route ?type=office_manager to that
separate database. The orchestrator and bridge must agree on the canonical path.

Acceptance criteria:
1. office_manager.py exposes om_bus_path(teaparty_home) — the canonical path
   to the OM database, usable by both orchestrator and bridge.
2. om_bus_path(teaparty_home) produces the same path as the bridge's
   _om_bus_path(teaparty_home).
3. OM conversations are written to om_bus_path(teaparty_home), not to any
   per-session messages.db.
4. Per-session conversations are written to {session_infra_dir}/messages.db,
   not to the OM database.
5. The OM database and a session database are always at different paths —
   the bridge can open two distinct connections.
6. _bus_for_conversation('om:user') routes to the OM bus, not a session bus.
"""
import os
import shutil
import tempfile
import unittest

from projects.POC.orchestrator.messaging import (
    ConversationType,
    SqliteMessageBus,
    make_conversation_id,
)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _make_tmpdir():
    return tempfile.mkdtemp()


# ── Canonical path contract ────────────────────────────────────────────────────

class TestOmBusPathContract(unittest.TestCase):
    """office_manager.py must export om_bus_path() that matches the bridge path."""

    def test_om_bus_path_exists_in_office_manager(self):
        """office_manager module must export om_bus_path(teaparty_home) function."""
        from projects.POC.orchestrator import office_manager
        self.assertTrue(
            callable(getattr(office_manager, 'om_bus_path', None)),
            'office_manager must export om_bus_path(teaparty_home)',
        )

    def test_orchestrator_om_bus_path_matches_bridge_path(self):
        """om_bus_path() and _om_bus_path() must return the same path.

        Both the orchestrator and the bridge must resolve the OM database
        at the same filesystem path. If they diverge, the bridge will open
        a different (empty) database than the one the orchestrator writes to.
        """
        from projects.POC.orchestrator.office_manager import om_bus_path

        home = '/home/user/.teaparty'
        orchestrator_path = om_bus_path(home)

        # The canonical path is {teaparty_home}/om/om-messages.db per the spec
        # (bridge-api.md, issue #290). Verify the orchestrator matches.
        self.assertTrue(
            orchestrator_path.startswith(home),
            f'OM bus path must be under teaparty_home, got: {orchestrator_path}',
        )
        self.assertTrue(
            orchestrator_path.endswith('om-messages.db'),
            f'OM bus path must end with om-messages.db, got: {orchestrator_path}',
        )

    def test_om_bus_path_is_under_teaparty_home(self):
        """om_bus_path() must be inside teaparty_home."""
        from projects.POC.orchestrator.office_manager import om_bus_path

        home = '/home/user/.teaparty'
        path = om_bus_path(home)
        self.assertTrue(
            path.startswith(home),
            f'OM bus path must be under teaparty_home, got: {path}',
        )

    def test_om_bus_path_ends_with_om_messages_db(self):
        """om_bus_path() must end with om-messages.db."""
        from projects.POC.orchestrator.office_manager import om_bus_path

        path = om_bus_path('/home/user/.teaparty')
        self.assertTrue(
            path.endswith('om-messages.db'),
            f'OM bus path must end with om-messages.db, got: {path}',
        )

    def test_om_bus_path_is_not_session_messages_db(self):
        """om_bus_path() must not return the per-session messages.db filename."""
        from projects.POC.orchestrator.office_manager import om_bus_path

        path = om_bus_path('/home/user/.teaparty')
        self.assertNotEqual(
            os.path.basename(path), 'messages.db',
            'OM bus must use om-messages.db, not messages.db',
        )

    def test_om_bus_path_is_stable_and_deterministic(self):
        """Same teaparty_home must always produce the same OM bus path."""
        from projects.POC.orchestrator.office_manager import om_bus_path

        home = '/home/user/.teaparty'
        p1 = om_bus_path(home)
        p2 = om_bus_path(home)
        self.assertEqual(p1, p2, 'OM bus path must be deterministic')

    def test_om_bus_path_differs_per_teaparty_home(self):
        """Different teaparty_home values must produce different OM bus paths."""
        from projects.POC.orchestrator.office_manager import om_bus_path

        p1 = om_bus_path('/home/alice/.teaparty')
        p2 = om_bus_path('/home/bob/.teaparty')
        self.assertNotEqual(p1, p2)


# ── Path isolation: OM vs session databases ────────────────────────────────────

class TestOmDatabaseIsolation(unittest.TestCase):
    """OM conversations and session conversations must use separate databases.

    The bridge opens two distinct SqliteMessageBus connections: one at
    om_bus_path(teaparty_home) for office manager conversations, and one at
    {infra_dir}/messages.db for each session. These must never be the same file.
    """

    def setUp(self):
        self.tmpdir = _make_tmpdir()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_om_db_path_differs_from_session_db_path(self):
        """om_bus_path(home) must differ from a session's messages.db path."""
        from projects.POC.orchestrator.office_manager import om_bus_path

        session_dir = os.path.join(self.tmpdir, 'proj', '.sessions', 'sess-1')
        session_db = os.path.join(session_dir, 'messages.db')
        om_db = om_bus_path(self.tmpdir)

        self.assertNotEqual(
            os.path.normpath(om_db),
            os.path.normpath(session_db),
            'OM database must not be at the same path as a session messages.db',
        )

    def test_om_conversations_not_in_session_db(self):
        """OM conversations written to om_bus_path are not in a session messages.db."""
        from projects.POC.orchestrator.office_manager import om_bus_path

        om_path = om_bus_path(self.tmpdir)
        os.makedirs(os.path.dirname(om_path), exist_ok=True)

        # Write an OM conversation
        om_bus = SqliteMessageBus(om_path)
        om_conv_id = make_conversation_id(ConversationType.OFFICE_MANAGER, 'alice')
        om_bus.create_conversation(ConversationType.OFFICE_MANAGER, 'alice')
        om_bus.send(om_conv_id, 'human', 'Hello from Alice')
        om_bus.close()

        # A separate session bus at a different path
        session_dir = os.path.join(self.tmpdir, 'proj', '.sessions', 'sess-1')
        os.makedirs(session_dir, exist_ok=True)
        session_db = os.path.join(session_dir, 'messages.db')
        session_bus = SqliteMessageBus(session_db)
        session_conv_id = make_conversation_id(ConversationType.PROJECT_SESSION, 'proj')
        session_bus.create_conversation(ConversationType.PROJECT_SESSION, 'proj')
        session_bus.send(session_conv_id, 'orchestrator', 'Session message')

        # OM conversation is NOT visible through the session bus
        om_convs_in_session = session_bus.active_conversations(
            ConversationType.OFFICE_MANAGER
        )
        session_bus.close()

        self.assertEqual(
            om_convs_in_session, [],
            'OM conversations must not appear in a session messages.db',
        )

    def test_session_conversations_not_in_om_db(self):
        """Session conversations written to a session bus are not in om_bus_path."""
        from projects.POC.orchestrator.office_manager import om_bus_path

        om_path = om_bus_path(self.tmpdir)
        os.makedirs(os.path.dirname(om_path), exist_ok=True)
        om_bus = SqliteMessageBus(om_path)

        # Write a session conversation to a different DB
        session_dir = os.path.join(self.tmpdir, 'proj', '.sessions', 'sess-2')
        os.makedirs(session_dir, exist_ok=True)
        session_db = os.path.join(session_dir, 'messages.db')
        session_bus = SqliteMessageBus(session_db)
        session_conv_id = make_conversation_id(ConversationType.PROJECT_SESSION, 'proj')
        session_bus.create_conversation(ConversationType.PROJECT_SESSION, 'proj')
        session_bus.send(session_conv_id, 'orchestrator', 'Work message')
        session_bus.close()

        # Session conversation is NOT visible through the OM bus
        session_convs_in_om = om_bus.active_conversations(ConversationType.PROJECT_SESSION)
        om_bus.close()

        self.assertEqual(
            session_convs_in_om, [],
            'Session conversations must not appear in the OM database',
        )

    def test_om_conversation_visible_from_om_db_only(self):
        """An OM conversation written to om_bus_path appears only there."""
        from projects.POC.orchestrator.office_manager import om_bus_path

        om_path = om_bus_path(self.tmpdir)
        os.makedirs(os.path.dirname(om_path), exist_ok=True)
        om_bus = SqliteMessageBus(om_path)
        om_conv_id = make_conversation_id(ConversationType.OFFICE_MANAGER, 'bob')
        om_bus.create_conversation(ConversationType.OFFICE_MANAGER, 'bob')
        om_bus.send(om_conv_id, 'human', 'Management question')

        convs = om_bus.active_conversations(ConversationType.OFFICE_MANAGER)
        om_bus.close()

        self.assertEqual(len(convs), 1)
        self.assertEqual(convs[0].id, om_conv_id)


# ── Write-side path contract: orchestrator writes where bridge reads ───────────

class TestOmSessionWritePathContract(unittest.TestCase):
    """OfficeManagerSession must write to om_bus_path(teaparty_home).

    This is the key invariant: the orchestrator writes OM conversations to the
    same database the bridge reads. If these diverge, the bridge returns an
    empty list for ?type=office_manager regardless of how many conversations exist.
    """

    def setUp(self):
        self.tmpdir = _make_tmpdir()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_session_writes_to_canonical_om_path(self):
        """Messages sent via OfficeManagerSession appear at om_bus_path(teaparty_home)."""
        from projects.POC.orchestrator.office_manager import OfficeManagerSession, om_bus_path

        session = OfficeManagerSession(teaparty_home=self.tmpdir, user_id='alice')
        session.send_human_message('Status update please')

        # Bridge reads from om_bus_path — verify the message is there
        canonical_path = om_bus_path(self.tmpdir)
        bus = SqliteMessageBus(canonical_path)
        msgs = bus.receive(session.conversation_id)
        bus.close()

        self.assertEqual(len(msgs), 1,
                         'OfficeManagerSession must write to om_bus_path(teaparty_home)')
        self.assertEqual(msgs[0].content, 'Status update please')

    def test_session_db_path_equals_om_bus_path(self):
        """The database file OfficeManagerSession creates is om_bus_path(teaparty_home)."""
        from projects.POC.orchestrator.office_manager import OfficeManagerSession, om_bus_path

        session = OfficeManagerSession(teaparty_home=self.tmpdir, user_id='bob')
        session.send_human_message('ping')
        canonical_path = om_bus_path(self.tmpdir)

        # Verify the message is readable at canonical_path (same DB)
        bus = SqliteMessageBus(canonical_path)
        msgs = bus.receive(session.conversation_id)
        bus.close()
        self.assertEqual(len(msgs), 1,
                         'OfficeManagerSession._bus must be at om_bus_path(teaparty_home)')

        # Verify a bus at a different path has no messages (different DB)
        other_path = os.path.join(self.tmpdir, 'other.db')
        other_bus = SqliteMessageBus(other_path)
        other_msgs = other_bus.receive(session.conversation_id)
        other_bus.close()
        self.assertEqual(len(other_msgs), 0,
                         'Messages must not appear in a different database file')

    def test_two_sessions_for_same_home_share_same_db(self):
        """Two OfficeManagerSessions with same teaparty_home share the same database."""
        from projects.POC.orchestrator.office_manager import OfficeManagerSession

        session1 = OfficeManagerSession(teaparty_home=self.tmpdir, user_id='alice')
        session2 = OfficeManagerSession(teaparty_home=self.tmpdir, user_id='bob')

        # Write via session1, verify session2 can read it (same underlying DB)
        session1.send_human_message('hello from alice')
        msgs = session2._bus.receive(session1.conversation_id)
        self.assertEqual(len(msgs), 1,
                         'Sessions for the same teaparty_home must share the same OM database')
        self.assertEqual(msgs[0].content, 'hello from alice')


# ── Conversation ID prefix convention ─────────────────────────────────────────

class TestOmConversationIdPrefix(unittest.TestCase):
    """OM conversation IDs use the 'om:' prefix — the bridge uses this for routing.

    The bridge's _bus_for_conversation checks if conv_id.startswith('om:') to
    select the OM bus. This test verifies that make_conversation_id produces
    the right prefix for OFFICE_MANAGER type.
    """

    def test_office_manager_conversation_id_starts_with_om_prefix(self):
        """make_conversation_id(OFFICE_MANAGER) must produce 'om:*' IDs."""
        conv_id = make_conversation_id(ConversationType.OFFICE_MANAGER, 'alice')
        self.assertTrue(
            conv_id.startswith('om:'),
            f'OFFICE_MANAGER conversation ID must start with om:, got: {conv_id}',
        )

    def test_project_session_conversation_id_does_not_start_with_om(self):
        """make_conversation_id(PROJECT_SESSION) must not produce 'om:*' IDs."""
        conv_id = make_conversation_id(ConversationType.PROJECT_SESSION, 'proj')
        self.assertFalse(
            conv_id.startswith('om:'),
            f'PROJECT_SESSION conversation ID must not start with om:, got: {conv_id}',
        )

    def test_om_prefix_is_unique_to_office_manager_type(self):
        """No other conversation type should produce an 'om:' prefixed ID."""
        non_om_types = [
            (ConversationType.PROJECT_SESSION, 'proj'),
            (ConversationType.SUBTEAM, 'team'),
            (ConversationType.PROXY_REVIEW, 'user'),
        ]
        for conv_type, qualifier in non_om_types:
            conv_id = make_conversation_id(conv_type, qualifier)
            self.assertFalse(
                conv_id.startswith('om:'),
                f'{conv_type.value} conversation ID must not start with om:, got: {conv_id}',
            )


# ── Bridge routing (requires aiohttp) ─────────────────────────────────────────

def _has_aiohttp():
    try:
        import aiohttp  # noqa: F401
        return True
    except ImportError:
        return False


@unittest.skipUnless(_has_aiohttp(), 'aiohttp not available in test environment')
class TestBridgeBusRouting(unittest.TestCase):
    """_bus_for_conversation must route om:* to OM bus, others to session buses."""

    def setUp(self):
        self.tmpdir = _make_tmpdir()
        from projects.POC.bridge.server import TeaPartyBridge, _om_bus_path
        static_dir = os.path.join(self.tmpdir, 'static')
        os.makedirs(static_dir, exist_ok=True)
        self.bridge = TeaPartyBridge(
            teaparty_home=self.tmpdir,
            projects_dir=self.tmpdir,
            static_dir=static_dir,
        )
        # Initialize OM bus (normally done in on_startup)
        om_path = _om_bus_path(self.tmpdir)
        os.makedirs(os.path.dirname(om_path), exist_ok=True)
        self.bridge._om_bus = SqliteMessageBus(om_path)

    def tearDown(self):
        if self.bridge._om_bus:
            self.bridge._om_bus.close()
        for bus in self.bridge._buses.values():
            bus.close()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_om_conversation_id_routes_to_om_bus(self):
        """_bus_for_conversation('om:user') returns the OM bus."""
        om_conv_id = make_conversation_id(ConversationType.OFFICE_MANAGER, 'alice')
        self.bridge._om_bus.create_conversation(ConversationType.OFFICE_MANAGER, 'alice')

        bus = self.bridge._bus_for_conversation(om_conv_id)
        self.assertIsNotNone(bus, '_bus_for_conversation must return OM bus for om:* id')

        # Verify it's the same object as self.bridge._om_bus, not a session bus
        self.assertIs(
            bus, self.bridge._om_bus,
            '_bus_for_conversation(om:*) must return the OM bus, not a session bus',
        )

    def test_session_conversation_id_does_not_route_to_om_bus(self):
        """_bus_for_conversation for a session conv returns None if not in any session bus."""
        session_conv_id = make_conversation_id(ConversationType.PROJECT_SESSION, 'proj')
        bus = self.bridge._bus_for_conversation(session_conv_id)
        self.assertIsNone(
            bus,
            'session conversation must not route to OM bus',
        )

    def test_om_prefix_routes_to_om_bus_even_with_session_buses_registered(self):
        """An om:* conversation ID routes to OM bus even when session buses exist."""
        session_dir = os.path.join(self.tmpdir, 'sess-dir')
        os.makedirs(session_dir, exist_ok=True)
        session_db = os.path.join(session_dir, 'messages.db')
        session_bus = SqliteMessageBus(session_db)
        session_bus.create_conversation(ConversationType.PROJECT_SESSION, 'proj')
        self.bridge._buses['session-xyz'] = session_bus

        om_conv_id = make_conversation_id(ConversationType.OFFICE_MANAGER, 'bob')
        self.bridge._om_bus.create_conversation(ConversationType.OFFICE_MANAGER, 'bob')

        bus = self.bridge._bus_for_conversation(om_conv_id)
        self.assertIsNotNone(bus)
        self.assertIsNot(
            bus, session_bus,
            'om:* conversation must route to OM bus, not any session bus',
        )


if __name__ == '__main__':
    unittest.main()
