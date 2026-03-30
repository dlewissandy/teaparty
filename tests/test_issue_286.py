"""Tests for issue #286: bridge startup constructor args and static_dir.

Acceptance criteria:
1. Spec Startup example does not reference docs/proposals/ui-redesign/mockup as static_dir
2. Spec Startup section clarifies poc_root = os.path.join(projects_dir, 'POC')
3. server.py module docstring does not show docs/proposals/ui-redesign/mockup as static_dir
4. TeaPartyBridge creates a single StateReader with poc_root = projects_dir/POC (not teaparty_home)
5. REST state handlers use the shared StateReader instance, not per-request instantiation
"""
import asyncio
import os
import shutil
import tempfile
import unittest


# ── Helpers ───────────────────────────────────────────────────────────────────

def _spec_path():
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(
        repo_root, 'docs', 'proposals', 'ui-redesign', 'references', 'bridge-api.md'
    )


def _read_spec():
    with open(_spec_path()) as f:
        return f.read()


def _make_tmpdir():
    return tempfile.mkdtemp()


def _make_bridge(tmpdir):
    from bridge.server import TeaPartyBridge
    return TeaPartyBridge(
        teaparty_home=os.path.join(tmpdir, '.teaparty'),
        static_dir=os.path.join(tmpdir, 'static'),
    )


# ── Spec document checks ──────────────────────────────────────────────────────

class TestBridgeApiSpecStartup(unittest.TestCase):
    """The bridge-api spec Startup section must document correct paths.

    Issue #286: Spec showed docs/proposals/ui-redesign/mockup as static_dir
    (a proposal artifact, not a deployable path) and did not clarify how
    poc_root is derived from projects_dir.
    """

    def test_spec_startup_does_not_reference_mockup_as_static_dir(self):
        """Startup example must not use docs/proposals/ui-redesign/mockup as static_dir.

        That directory is a proposal artifact with hardcoded data.js — not a
        deployable static asset directory.
        """
        spec = _read_spec()
        self.assertNotIn(
            'docs/proposals/ui-redesign/mockup',
            spec,
            'bridge-api.md must not reference the proposal mockup directory as static_dir',
        )

    def test_spec_startup_documents_registry_based_discovery(self):
        """Startup section must document registry-based project discovery via teaparty_home.

        Issue #310 replaced projects_dir with registry-based discovery.
        The spec must show that projects come from teaparty_home/teaparty.yaml,
        not from a projects_dir argument.
        """
        spec = _read_spec()
        self.assertNotIn(
            'projects_dir',
            spec,
            "bridge-api.md must not reference projects_dir — registry-based discovery is used",
        )

    def test_spec_startup_documents_shared_state_reader_instance(self):
        """Startup section must state that StateReader is a single shared instance.

        The original spec implied a per-request StateReader; the actual implementation
        (and the spec) must make clear that one instance is created at startup and
        reused by both the polling loop and REST handlers.
        """
        spec = _read_spec()
        self.assertIn(
            'single',
            spec,
            'Startup section must document that StateReader is a single shared instance',
        )


# ── Module docstring check ─────────────────────────────────────────────────────

class TestBridgeServerDocstring(unittest.TestCase):
    """server.py module docstring must not show the proposal mockup as static_dir."""

    def test_module_docstring_does_not_reference_mockup(self):
        """Module docstring example must not use docs/proposals/ui-redesign/mockup.

        The docstring is the first thing an implementer reads; it must show a
        correct, deployable static_dir.
        """
        from bridge import server
        doc = server.__doc__ or ''
        self.assertNotIn(
            'docs/proposals/ui-redesign/mockup',
            doc,
            'server.py module docstring must not reference the proposal mockup directory',
        )


# ── Behavioral: single StateReader with correct poc_root ─────────────────────

class TestBridgeStateReaderInitialization(unittest.TestCase):
    """TeaPartyBridge must create exactly one StateReader using registry-based discovery.

    Issue #286: An implementer following the old spec would pass teaparty_home
    (~/.teaparty) as poc_root.  StateReader would then scan ~/.teaparty for
    worktrees.json and project sessions — the wrong location — producing silently
    empty state.  Issue #310 removed projects_dir entirely: the bridge now uses
    registry-based discovery via teaparty_home, with a single shared StateReader.
    """

    def setUp(self):
        self.tmpdir = _make_tmpdir()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_bridge_has_state_reader_attribute(self):
        """Bridge must store a single _state_reader attribute."""
        bridge = _make_bridge(self.tmpdir)
        self.assertTrue(hasattr(bridge, '_state_reader'),
                        'Bridge must have a _state_reader attribute')

    def test_state_reader_repo_root_is_not_teaparty_home(self):
        """StateReader.repo_root must differ from teaparty_home.

        repo_root is the repo checkout; teaparty_home is the runtime config dir.
        Confusing the two produces silently empty state — no sessions, no conversations.
        """
        bridge = _make_bridge(self.tmpdir)
        self.assertNotEqual(
            bridge._state_reader.repo_root, bridge.teaparty_home,
            'StateReader.repo_root must differ from teaparty_home',
        )

    def test_state_all_handler_uses_shared_state_reader(self):
        """GET /api/state must call reload() on the shared _state_reader, not a new instance.

        Creating a new StateReader per request bypasses the shared instance and
        duplicates the poc_root derivation in a way that can silently diverge.
        """
        from unittest.mock import MagicMock
        bridge = _make_bridge(self.tmpdir)

        reload_calls = []
        bridge._state_reader.reload = lambda: reload_calls.append(True) or []

        fake_request = MagicMock()
        asyncio.run(bridge._handle_state_all(fake_request))

        self.assertEqual(len(reload_calls), 1,
                         '_handle_state_all must call reload() on the shared _state_reader')

    def test_state_project_handler_uses_shared_state_reader(self):
        """GET /api/state/{project} must use the shared _state_reader, not a new instance."""
        from unittest.mock import MagicMock
        bridge = _make_bridge(self.tmpdir)

        reload_calls = []
        bridge._state_reader.reload = lambda: reload_calls.append(True) or []
        bridge._state_reader.find_project = lambda slug: None

        fake_request = MagicMock()
        fake_request.match_info = {'project': 'test-project'}
        asyncio.run(bridge._handle_state_project(fake_request))

        self.assertEqual(len(reload_calls), 1,
                         '_handle_state_project must call reload() on the shared _state_reader')


if __name__ == '__main__':
    unittest.main()
