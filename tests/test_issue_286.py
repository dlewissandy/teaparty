"""Tests for issue #286: bridge startup constructor args and static_dir.

Acceptance criteria:
1. Spec Startup example does not reference docs/proposals/ui-redesign/mockup as static_dir
2. Spec Startup section clarifies poc_root = os.path.join(projects_dir, 'POC')
3. server.py module docstring does not show docs/proposals/ui-redesign/mockup as static_dir
4. _on_startup initializes StateReader with poc_root derived from projects_dir, not teaparty_home
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

    def test_spec_startup_clarifies_poc_root_derivation(self):
        """Startup section must show that poc_root is derived from projects_dir.

        An implementer reading only the constructor example saw teaparty_home and
        projects_dir — with no poc_root arg — but step 1 referenced poc_root without
        explaining where it came from.  The spec must make the derivation explicit:
        poc_root = os.path.join(projects_dir, 'POC').
        """
        spec = _read_spec()
        # The spec must mention the derivation so implementers know poc_root ≠ teaparty_home
        self.assertIn(
            'poc_root',
            spec,
            'Startup section must reference poc_root',
        )
        # Must explain the join, not just name poc_root in passing
        self.assertTrue(
            'projects_dir' in spec and 'POC' in spec,
            'Startup section must show poc_root is derived from projects_dir/POC',
        )


# ── Module docstring check ─────────────────────────────────────────────────────

class TestBridgeServerDocstring(unittest.TestCase):
    """server.py module docstring must not show the proposal mockup as static_dir."""

    def test_module_docstring_does_not_reference_mockup(self):
        """Module docstring example must not use docs/proposals/ui-redesign/mockup.

        The docstring is the first thing an implementer reads; it must show a
        correct, deployable static_dir.
        """
        from projects.POC.bridge import server
        doc = server.__doc__ or ''
        self.assertNotIn(
            'docs/proposals/ui-redesign/mockup',
            doc,
            'server.py module docstring must not reference the proposal mockup directory',
        )


# ── Behavioral: StateReader receives poc_root from projects_dir, not teaparty_home ──

class TestBridgeStateReaderInitialization(unittest.TestCase):
    """_on_startup must initialize StateReader with poc_root = projects_dir/POC.

    Issue #286: An implementer following the old spec would pass teaparty_home
    (~/.teaparty) as poc_root.  StateReader would then scan ~/.teaparty for
    worktrees.json and project sessions — the wrong location — producing silently
    empty state.  The bridge must derive poc_root = os.path.join(projects_dir, 'POC').
    """

    def setUp(self):
        self.tmpdir = _make_tmpdir()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_startup_passes_projects_dir_slash_poc_as_poc_root(self):
        """StateReader must receive os.path.join(projects_dir, 'POC') as poc_root."""
        from unittest.mock import patch, MagicMock
        from projects.POC.bridge.server import TeaPartyBridge

        teaparty_home = os.path.join(self.tmpdir, 'home', '.teaparty')
        projects_dir = os.path.join(self.tmpdir, 'git', 'teaparty', 'projects')
        expected_poc_root = os.path.join(projects_dir, 'POC')

        bridge = TeaPartyBridge(
            teaparty_home=teaparty_home,
            projects_dir=projects_dir,
            static_dir=os.path.join(self.tmpdir, 'static'),
        )

        captured = []

        class CapturingStateReader:
            def __init__(self_inner, poc_root, *args, **kwargs):
                captured.append(poc_root)

            def reload(self_inner):
                return []

        async def run():
            fake_app = {}
            with patch('projects.POC.bridge.server.StateReader', CapturingStateReader), \
                 patch('projects.POC.bridge.server.StatePoller') as MockPoller, \
                 patch('projects.POC.bridge.server.MessageRelay') as MockRelay, \
                 patch('asyncio.create_task', return_value=MagicMock()), \
                 patch('projects.POC.bridge.server._om_bus_path', return_value='/tmp/om.db'), \
                 patch('projects.POC.bridge.server.SqliteMessageBus') as MockBus, \
                 patch('os.makedirs'):
                MockBus.return_value = MagicMock()
                MockPoller.return_value = MagicMock(run=MagicMock(return_value=None))
                MockRelay.return_value = MagicMock(run=MagicMock(return_value=None))
                await bridge._on_startup(fake_app)

        asyncio.run(run())

        self.assertEqual(len(captured), 1,
                         'StateReader must be initialized exactly once in _on_startup')
        actual_poc_root = captured[0]
        self.assertEqual(
            actual_poc_root, expected_poc_root,
            f'StateReader poc_root must be projects_dir/POC ({expected_poc_root!r}), '
            f'got {actual_poc_root!r}',
        )
        self.assertNotEqual(
            actual_poc_root, teaparty_home,
            'StateReader must NOT use teaparty_home as poc_root — '
            'teaparty_home is the runtime data dir, poc_root is the source dir',
        )

    def test_poc_root_and_teaparty_home_are_distinct_paths(self):
        """poc_root (projects_dir/POC) and teaparty_home (~/.teaparty) must differ.

        This is the structural invariant the issue describes: the bridge receives
        both paths for different purposes and must not conflate them.
        """
        from projects.POC.bridge.server import TeaPartyBridge

        teaparty_home = os.path.join(self.tmpdir, '.teaparty')
        projects_dir = os.path.join(self.tmpdir, 'projects')

        bridge = TeaPartyBridge(
            teaparty_home=teaparty_home,
            projects_dir=projects_dir,
            static_dir=os.path.join(self.tmpdir, 'static'),
        )

        derived_poc_root = os.path.join(bridge.projects_dir, 'POC')
        self.assertNotEqual(
            derived_poc_root, bridge.teaparty_home,
            'poc_root (projects_dir/POC) must differ from teaparty_home',
        )


if __name__ == '__main__':
    unittest.main()
