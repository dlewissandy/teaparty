"""Tests for StateReader._find_dispatches_for_session (issue #111 fix).

Fix 1: Dynamic team discovery replaced the hardcoded teams tuple
('art', 'writing', 'editorial', 'research', 'coding') with directory
scanning, so any team name is discovered automatically.
"""
import os
import tempfile
import unittest

from projects.POC.tui.state_reader import StateReader


def _make_state_reader() -> StateReader:
    """Create a StateReader with throwaway paths (no filesystem reads needed)."""
    return StateReader(poc_root='/tmp/poc', projects_dir='/tmp/projects')


def _make_sess_dir(base: str, *names: str) -> str:
    """Create a session directory under base and return its path."""
    sess_dir = os.path.join(base, *names)
    os.makedirs(sess_dir, exist_ok=True)
    return sess_dir


def _make_team_dispatch(sess_dir: str, team: str, dispatch_ts: str) -> str:
    """Create {sess_dir}/{team}/{dispatch_ts}/ and return dispatch_dir path."""
    dispatch_dir = os.path.join(sess_dir, team, dispatch_ts)
    os.makedirs(dispatch_dir, exist_ok=True)
    return dispatch_dir


def _make_file(directory: str, filename: str, content: str = '') -> str:
    """Create a regular file inside directory and return its path."""
    path = os.path.join(directory, filename)
    with open(path, 'w') as f:
        f.write(content)
    return path


class TestFindDispatchesForSession(unittest.TestCase):
    """Tests for _find_dispatches_for_session with dynamic team discovery."""

    def setUp(self) -> None:
        self._tmpdir = tempfile.mkdtemp()
        self.reader = _make_state_reader()

    def tearDown(self) -> None:
        import shutil
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    # ------------------------------------------------------------------
    # Fix 1: "tasks" team is now discovered (was not in hardcoded list)
    # ------------------------------------------------------------------

    def test_novel_team_name_is_discovered(self) -> None:
        """A team not in the old hardcoded list ('tasks') is found."""
        sess_dir = _make_sess_dir(self._tmpdir, 'sess1')
        dispatch_ts = '20260312-090000'
        _make_team_dispatch(sess_dir, 'tasks', dispatch_ts)

        # Provide a matching manifest entry so we get a real entry back.
        dispatch_by_sid = {
            dispatch_ts: {
                'name': 'tasks-dispatch',
                'path': '/some/path',
                'type': 'dispatch',
                'team': 'tasks',
                'task': 'Do something',
                'session_id': dispatch_ts,
                'status': 'active',
            }
        }

        results = self.reader._find_dispatches_for_session(sess_dir, dispatch_by_sid)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['session_id'], dispatch_ts)
        self.assertEqual(results[0]['team'], 'tasks')

    def test_novel_team_without_manifest_entry_produces_synthetic_entry(self) -> None:
        """A 'tasks' dispatch with no manifest entry still surfaces as synthetic."""
        sess_dir = _make_sess_dir(self._tmpdir, 'sess2')
        dispatch_ts = '20260312-091500'
        _make_team_dispatch(sess_dir, 'tasks', dispatch_ts)

        results = self.reader._find_dispatches_for_session(sess_dir, {})

        self.assertEqual(len(results), 1)
        entry = results[0]
        self.assertEqual(entry['session_id'], dispatch_ts)
        self.assertEqual(entry['team'], 'tasks')
        self.assertEqual(entry['type'], 'dispatch')

    # ------------------------------------------------------------------
    # Hidden files / dirs are skipped
    # ------------------------------------------------------------------

    def test_hidden_file_is_skipped(self) -> None:
        """.cfa-state.json (a hidden file) at the session level is not treated as a team."""
        sess_dir = _make_sess_dir(self._tmpdir, 'sess3')
        _make_file(sess_dir, '.cfa-state.json', '{}')
        # Also add a valid team so we know scanning still works.
        dispatch_ts = '20260312-100000'
        _make_team_dispatch(sess_dir, 'coding', dispatch_ts)

        results = self.reader._find_dispatches_for_session(sess_dir, {})

        session_ids = [r['session_id'] for r in results]
        self.assertIn(dispatch_ts, session_ids)
        # No entry whose name starts with '.' should appear as a team.
        for r in results:
            self.assertFalse(r.get('team', '').startswith('.'),
                             f"Hidden entry leaked into results: {r}")

    def test_hidden_directory_is_skipped(self) -> None:
        """.git/ at the session level is not treated as a team directory."""
        sess_dir = _make_sess_dir(self._tmpdir, 'sess4')
        # Create a .git dir with a digit-named subdir to be sure it's the
        # dot-check that blocks it, not the inner-dir check.
        hidden_dir = os.path.join(sess_dir, '.git', '20260312-110000')
        os.makedirs(hidden_dir, exist_ok=True)

        results = self.reader._find_dispatches_for_session(sess_dir, {})

        self.assertEqual(results, [])

    # ------------------------------------------------------------------
    # Regular files at session level are skipped
    # ------------------------------------------------------------------

    def test_regular_files_at_session_level_are_skipped(self) -> None:
        """INTENT.md, session.log, plan.md are files — not directories — and are ignored."""
        sess_dir = _make_sess_dir(self._tmpdir, 'sess5')
        for filename in ('INTENT.md', 'session.log', 'plan.md'):
            _make_file(sess_dir, filename)

        results = self.reader._find_dispatches_for_session(sess_dir, {})

        self.assertEqual(results, [])

    # ------------------------------------------------------------------
    # Standard teams still work
    # ------------------------------------------------------------------

    def test_standard_teams_are_discovered(self) -> None:
        """coding, research, writing, editorial, art all surface dispatches."""
        sess_dir = _make_sess_dir(self._tmpdir, 'sess6')
        standard_teams = ('coding', 'research', 'writing', 'editorial', 'art')
        dispatch_ts = '20260312-120000'

        for team in standard_teams:
            _make_team_dispatch(sess_dir, team, dispatch_ts)

        results = self.reader._find_dispatches_for_session(sess_dir, {})

        found_teams = {r['team'] for r in results}
        self.assertEqual(found_teams, set(standard_teams))

    def test_multiple_dispatches_per_team(self) -> None:
        """Two dispatch timestamps under the same team both appear."""
        sess_dir = _make_sess_dir(self._tmpdir, 'sess7')
        ts1 = '20260312-130000'
        ts2 = '20260312-140000'
        _make_team_dispatch(sess_dir, 'coding', ts1)
        _make_team_dispatch(sess_dir, 'coding', ts2)

        results = self.reader._find_dispatches_for_session(sess_dir, {})

        session_ids = [r['session_id'] for r in results]
        self.assertIn(ts1, session_ids)
        self.assertIn(ts2, session_ids)
        self.assertEqual(len(results), 2)

    # ------------------------------------------------------------------
    # Empty team directories produce no dispatches
    # ------------------------------------------------------------------

    def test_empty_team_directory_produces_no_dispatches(self) -> None:
        """A team dir with no dispatch subdirs contributes nothing."""
        sess_dir = _make_sess_dir(self._tmpdir, 'sess8')
        empty_team_dir = os.path.join(sess_dir, 'coding')
        os.makedirs(empty_team_dir, exist_ok=True)

        results = self.reader._find_dispatches_for_session(sess_dir, {})

        self.assertEqual(results, [])

    def test_team_dir_with_only_files_produces_no_dispatches(self) -> None:
        """A team dir containing only regular files (no timestamp subdirs) is empty."""
        sess_dir = _make_sess_dir(self._tmpdir, 'sess9')
        team_dir = os.path.join(sess_dir, 'research')
        os.makedirs(team_dir, exist_ok=True)
        _make_file(team_dir, 'notes.txt')

        results = self.reader._find_dispatches_for_session(sess_dir, {})

        self.assertEqual(results, [])

    def test_team_subdir_not_starting_with_digit_is_skipped(self) -> None:
        """A subdir under a team that does not start with a digit is not a dispatch."""
        sess_dir = _make_sess_dir(self._tmpdir, 'sess10')
        # 'shared' does not start with a digit, so it should be skipped.
        non_ts_dir = os.path.join(sess_dir, 'coding', 'shared')
        os.makedirs(non_ts_dir, exist_ok=True)

        results = self.reader._find_dispatches_for_session(sess_dir, {})

        self.assertEqual(results, [])

    # ------------------------------------------------------------------
    # Manifest entry augmentation (_infra_dir injection)
    # ------------------------------------------------------------------

    def test_manifest_entry_gets_infra_dir_injected(self) -> None:
        """When a dispatch has a manifest entry, _infra_dir is set to its directory."""
        sess_dir = _make_sess_dir(self._tmpdir, 'sess11')
        dispatch_ts = '20260312-150000'
        dispatch_dir = _make_team_dispatch(sess_dir, 'coding', dispatch_ts)

        dispatch_by_sid = {
            dispatch_ts: {
                'name': 'coding-dispatch',
                'path': '/wt/coding',
                'type': 'dispatch',
                'team': 'coding',
                'task': 'Write code',
                'session_id': dispatch_ts,
                'status': 'complete',
            }
        }

        results = self.reader._find_dispatches_for_session(sess_dir, dispatch_by_sid)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['_infra_dir'], dispatch_dir)
        # Original entry dict must not be mutated.
        self.assertNotIn('_infra_dir', dispatch_by_sid[dispatch_ts])

    # ------------------------------------------------------------------
    # OSError on unreadable sess_dir returns empty list
    # ------------------------------------------------------------------

    def test_missing_sess_dir_returns_empty_list(self) -> None:
        """If sess_dir does not exist, return [] without raising."""
        results = self.reader._find_dispatches_for_session(
            '/nonexistent/path/that/does/not/exist', {}
        )
        self.assertEqual(results, [])

    # ------------------------------------------------------------------
    # Mixed directory contents (files + teams + hidden)
    # ------------------------------------------------------------------

    def test_mixed_contents_only_team_dispatches_returned(self) -> None:
        """Session dir with files, hidden dirs, and real teams returns only dispatches."""
        sess_dir = _make_sess_dir(self._tmpdir, 'sess12')

        # Regular files — must be ignored.
        for filename in ('INTENT.md', 'session.log', '.cfa-state.json', '.running'):
            _make_file(sess_dir, filename)

        # Hidden directory — must be ignored.
        os.makedirs(os.path.join(sess_dir, '.git'), exist_ok=True)

        # Valid teams.
        ts_coding = '20260312-160000'
        ts_tasks = '20260312-161500'
        _make_team_dispatch(sess_dir, 'coding', ts_coding)
        _make_team_dispatch(sess_dir, 'tasks', ts_tasks)

        results = self.reader._find_dispatches_for_session(sess_dir, {})

        session_ids = {r['session_id'] for r in results}
        self.assertEqual(session_ids, {ts_coding, ts_tasks})


if __name__ == '__main__':
    unittest.main()
