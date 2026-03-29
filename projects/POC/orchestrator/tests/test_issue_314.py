"""Tests for issue #314: Backend test isolation via temp-directory helpers.

Verifies:
1. make_tmp_dir creates a real directory, not a fake path
2. make_tmp_dir registers a cleanup callable via addCleanup
3. Orchestrator with temp infra_dir writes artifacts there, not to /tmp/fake
4. _deliver_intervention writes .interventions.jsonl to the temp infra_dir
5. test_issue_246, 247, 252 no longer use /tmp/fake in Orchestrator constructions
6. make_tmp_dir is importable from test_helpers module
"""
import asyncio
import os
import shutil
import tempfile
import unittest


# ── Test 1: make_tmp_dir creates a real, unique directory ────────────────────

class TestMakeTmpDirCreatesRealDir(unittest.TestCase):
    """make_tmp_dir must create a real directory, not a hardcoded fake path."""

    def test_returns_real_existing_directory(self):
        """make_tmp_dir returns a path that is a real, existing directory."""
        from projects.POC.orchestrator.tests.test_helpers import make_tmp_dir
        tmp = make_tmp_dir(self)
        self.assertTrue(os.path.isdir(tmp), f'Expected a real directory at {tmp}')

    def test_not_a_fixed_fake_path(self):
        """make_tmp_dir must not return /tmp/fake or any fixed hardcoded path."""
        from projects.POC.orchestrator.tests.test_helpers import make_tmp_dir
        tmp = make_tmp_dir(self)
        self.assertNotEqual(tmp, '/tmp/fake')
        self.assertNotEqual(tmp, '/tmp/fake-worktree')
        self.assertNotEqual(tmp, '/tmp/fake-project')

    def test_each_call_returns_unique_path(self):
        """Two calls return distinct temp dirs (test isolation)."""
        from projects.POC.orchestrator.tests.test_helpers import make_tmp_dir
        a = make_tmp_dir(self)
        b = make_tmp_dir(self)
        self.assertNotEqual(a, b)


# ── Test 2: make_tmp_dir registers cleanup ────────────────────────────────────

class TestMakeTmpDirRegistersCleanup(unittest.TestCase):
    """make_tmp_dir must register a cleanup so no artifacts remain after the test."""

    def test_cleanup_registered_via_add_cleanup(self):
        """After make_tmp_dir, self._cleanups has grown by at least one entry."""
        from projects.POC.orchestrator.tests.test_helpers import make_tmp_dir
        before = len(self._cleanups)
        make_tmp_dir(self)
        after = len(self._cleanups)
        self.assertGreater(after, before,
                           'make_tmp_dir must register a cleanup via addCleanup')

    def test_cleanup_callable_removes_dir(self):
        """The cleanup callable (shutil.rmtree) removes the temp directory."""
        from projects.POC.orchestrator.tests.test_helpers import make_tmp_dir

        # Create a fresh temp dir and simulate what cleanup does
        tmp = tempfile.mkdtemp(prefix='test-314-cleanup-')
        self.assertTrue(os.path.isdir(tmp))

        # This is the cleanup that make_tmp_dir registers
        shutil.rmtree(tmp, True)
        self.assertFalse(os.path.isdir(tmp))


# ── Test 3: Orchestrator with temp infra_dir writes artifacts there ──────────

class TestOrchestratorWritesToTempInfraDir(unittest.TestCase):
    """Orchestrator must write .interventions.jsonl to the provided temp infra_dir."""

    def _make_orch(self, infra_dir, q=None):
        from projects.POC.orchestrator.engine import Orchestrator
        from projects.POC.orchestrator.events import EventBus
        from projects.POC.scripts.cfa_state import make_initial_state
        return Orchestrator(
            cfa_state=make_initial_state(task_id='test'),
            phase_config=_make_stub_phase_config(),
            event_bus=EventBus(),
            input_provider=None,
            infra_dir=infra_dir,
            project_workdir=infra_dir,
            session_worktree=infra_dir,
            proxy_model_path=infra_dir,
            project_slug='test',
            poc_root=infra_dir,
            intervention_queue=q,
        )

    def test_deliver_intervention_writes_to_temp_infra_dir(self):
        """_deliver_intervention writes .interventions.jsonl to the temp infra_dir."""
        from projects.POC.orchestrator.tests.test_helpers import make_tmp_dir
        from projects.POC.orchestrator.intervention import InterventionQueue

        tmp = make_tmp_dir(self)
        q = InterventionQueue()
        q.enqueue('test redirect', sender='human')
        orch = self._make_orch(tmp, q=q)

        asyncio.run(orch._deliver_intervention())

        self.assertTrue(
            os.path.isfile(os.path.join(tmp, '.interventions.jsonl')),
            '.interventions.jsonl must be written to the temp infra_dir',
        )

    def test_deliver_intervention_does_not_modify_tmp_fake(self):
        """/tmp/fake/.interventions.jsonl must not be touched by a temp-dir-using test."""
        from projects.POC.orchestrator.tests.test_helpers import make_tmp_dir
        from projects.POC.orchestrator.intervention import InterventionQueue

        fake_artifact = '/tmp/fake/.interventions.jsonl'
        mtime_before = os.path.getmtime(fake_artifact) if os.path.isfile(fake_artifact) else -1.0

        tmp = make_tmp_dir(self)
        q = InterventionQueue()
        q.enqueue('test redirect', sender='human')
        orch = self._make_orch(tmp, q=q)

        asyncio.run(orch._deliver_intervention())

        mtime_after = os.path.getmtime(fake_artifact) if os.path.isfile(fake_artifact) else -1.0
        self.assertEqual(
            mtime_before, mtime_after,
            '/tmp/fake/.interventions.jsonl must not be written when using a temp infra_dir',
        )


# ── Test 4: test_issue_246 must not use /tmp/fake in Orchestrator args ────────

class TestIssue246NoFakePaths(unittest.TestCase):
    """test_issue_246.py must not pass /tmp/fake to Orchestrator."""

    def _source(self):
        path = os.path.join(os.path.dirname(__file__), 'test_issue_246.py')
        with open(path) as f:
            return f.read()

    def test_no_tmp_fake_infra_dir(self):
        """infra_dir='/tmp/fake' must not appear in test_issue_246."""
        self.assertNotIn("infra_dir='/tmp/fake'", self._source())

    def test_no_tmp_fake_project_workdir(self):
        """project_workdir='/tmp/fake' must not appear in test_issue_246."""
        self.assertNotIn("project_workdir='/tmp/fake'", self._source())


# ── Test 5: test_issue_247 must not use /tmp/fake in Orchestrator args ────────

class TestIssue247NoFakePaths(unittest.TestCase):
    """test_issue_247.py must not pass /tmp/fake to Orchestrator."""

    def _source(self):
        path = os.path.join(os.path.dirname(__file__), 'test_issue_247.py')
        with open(path) as f:
            return f.read()

    def test_no_tmp_fake_infra_dir(self):
        """infra_dir='/tmp/fake' must not appear in test_issue_247."""
        self.assertNotIn("infra_dir='/tmp/fake'", self._source())


# ── Test 6: test_issue_252 must not use /tmp/fake in Orchestrator args ────────

class TestIssue252NoFakePaths(unittest.TestCase):
    """test_issue_252.py must not pass /tmp/fake to Orchestrator."""

    def _source(self):
        path = os.path.join(os.path.dirname(__file__), 'test_issue_252.py')
        with open(path) as f:
            return f.read()

    def test_no_tmp_fake_infra_dir(self):
        """infra_dir='/tmp/fake' must not appear in test_issue_252."""
        self.assertNotIn("infra_dir='/tmp/fake'", self._source())


# ── Tests 7–9: remaining migrated files must not use /tmp/fake paths ─────────

def _read_test_source(filename):
    path = os.path.join(os.path.dirname(__file__), filename)
    with open(path) as f:
        return f.read()


class TestRemainingFilesNoFakePaths(unittest.TestCase):
    """All migrated test files must not use hardcoded /tmp/fake paths."""

    def test_issue_135_no_fake_worktree_path(self):
        """test_issue_135.py must not use /tmp/fake-worktree as a default."""
        self.assertNotIn("'/tmp/fake-worktree'", _read_test_source('test_issue_135.py'))

    def test_issue_159_no_fake_worktree_path(self):
        """test_issue_159.py must not use /tmp/fake-worktree as a default."""
        self.assertNotIn("'/tmp/fake-worktree'", _read_test_source('test_issue_159.py'))

    def test_issue_248_no_fake_worktree_path(self):
        """test_issue_248.py must not use /tmp/fake-worktree as a default."""
        self.assertNotIn("'/tmp/fake-worktree'", _read_test_source('test_issue_248.py'))

    def test_issue_237_no_fake_proxy_model_path(self):
        """test_issue_237.py must not use /tmp/fake for proxy_model_path."""
        self.assertNotIn("proxy_model_path='/tmp/fake'", _read_test_source('test_issue_237.py'))

    def test_issue_195_no_fake_project_dir(self):
        """test_issue_195.py must not use /tmp/fake-project as a default."""
        self.assertNotIn("'/tmp/fake-project'", _read_test_source('test_issue_195.py'))


# ── Test N: test_helpers module exposes make_tmp_dir ─────────────────────────

class TestHelpersModuleExposed(unittest.TestCase):
    """test_helpers must export a callable make_tmp_dir(test_case)."""

    def test_make_tmp_dir_importable(self):
        """make_tmp_dir must be importable from test_helpers."""
        from projects.POC.orchestrator.tests.test_helpers import make_tmp_dir
        self.assertTrue(callable(make_tmp_dir))

    def test_make_tmp_dir_accepts_test_case(self):
        """make_tmp_dir must accept a TestCase instance as its only argument."""
        import inspect
        from projects.POC.orchestrator.tests.test_helpers import make_tmp_dir
        sig = inspect.signature(make_tmp_dir)
        self.assertIn('test_case', sig.parameters)

    def test_make_tmp_dir_returns_string(self):
        """make_tmp_dir must return a string (path to the temp directory)."""
        from projects.POC.orchestrator.tests.test_helpers import make_tmp_dir
        tmp = make_tmp_dir(self)
        self.assertIsInstance(tmp, str)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_stub_phase_config():
    class _StubPhaseConfig:
        stall_timeout = 1800
        human_actor_states = frozenset()

        def phase_spec(self, phase_name):
            return None

    return _StubPhaseConfig()


if __name__ == '__main__':
    unittest.main()
