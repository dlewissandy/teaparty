#!/usr/bin/env python3
"""Tests for learnings.py — all 10 scope implementations.

Covers:
 1. promote() in summarize_session.py for each of the 7 new scopes
 2. _promote_* helpers in learnings.py wiring
 3. extract_learnings() runs all scopes without raising

All tests mock the LLM call (summarize_session.summarize) so no real
claude invocations occur.
"""
import asyncio
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent.parent))

from projects.POC.scripts.summarize_session import promote
from projects.POC.orchestrator.learnings import (
    _promote_team,
    _promote_session,
    _promote_project,
    _promote_global,
    _promote_prospective,
    _promote_in_flight,
    _promote_corrective,
    extract_learnings,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _run(coro):
    return asyncio.run(coro)


def _write(path: str, content: str = "## [2026-01-01] Learning\n**Context:** test\n**Learning:** test\n**Action:** test\n") -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(content)


def _touch(path: str) -> None:
    """Create an empty file (to test is-file checks without content)."""
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).touch()


def _nonempty(path: str) -> None:
    """Write minimal non-empty content."""
    _write(path)


# ── promote() — team scope ────────────────────────────────────────────────────

class TestPromoteTeam(unittest.TestCase):
    """promote('team') rolls up dispatch MEMORY.md files into team typed stores."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.session_dir = self.tmpdir

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _make_dispatch_memory(self, team: str, dispatch: str = 'dispatch-001') -> str:
        path = os.path.join(self.session_dir, team, dispatch, 'MEMORY.md')
        _nonempty(path)
        return path

    def test_team_scope_skips_when_no_dispatch_memories(self):
        """When no dispatch MEMORY.md files exist, promote returns 0 without error."""
        result = promote('team', self.session_dir, '', '')
        self.assertEqual(result, 0)

    def test_team_scope_creates_institutional_and_tasks(self):
        """When dispatch MEMORYs exist, both institutional.md and tasks/<ts>.md are created."""
        self._make_dispatch_memory('coding')

        calls = []

        def fake_summarize(stream, output, ctx, scope, **kw):
            calls.append({'scope': scope, 'output': output, 'ctx': ctx})
            return 0

        with patch('projects.POC.scripts.summarize_session.summarize', side_effect=fake_summarize):
            result = promote('team', self.session_dir, '', '')

        self.assertEqual(result, 0)
        scopes_called = [c['scope'] for c in calls]
        self.assertIn('team-rollup-institutional', scopes_called)
        self.assertIn('team-rollup-tasks', scopes_called)

    def test_team_scope_output_paths(self):
        """Institutional output goes to session/<team>/institutional.md."""
        self._make_dispatch_memory('art')

        outputs = []

        def fake_summarize(stream, output, ctx, scope, **kw):
            outputs.append(output)
            return 0

        with patch('projects.POC.scripts.summarize_session.summarize', side_effect=fake_summarize):
            promote('team', self.session_dir, '', '')

        inst_outputs = [o for o in outputs if o.endswith('institutional.md')]
        self.assertTrue(any('art' in o for o in inst_outputs),
                        f"Expected art/institutional.md in outputs, got: {outputs}")

    def test_team_scope_skips_teams_with_no_memory(self):
        """Teams with no dispatch MEMORYs are silently skipped."""
        # Only coding has a dispatch memory
        self._make_dispatch_memory('coding')

        calls = []

        def fake_summarize(stream, output, ctx, scope, **kw):
            calls.append(output)
            return 0

        with patch('projects.POC.scripts.summarize_session.summarize', side_effect=fake_summarize):
            promote('team', self.session_dir, '', '')

        # art, writing, editorial, research should not appear in outputs
        for unexpected_team in ('art', 'writing', 'editorial', 'research'):
            for output in calls:
                self.assertNotIn(
                    f'/{unexpected_team}/', output,
                    f"Unexpected output for {unexpected_team}: {output}",
                )

    def test_team_scope_missing_session_dir_returns_1(self):
        result = promote('team', '', '', '')
        self.assertEqual(result, 1)


# ── promote() — session scope ─────────────────────────────────────────────────

class TestPromoteSession(unittest.TestCase):
    """promote('session') rolls up team files into session-level typed stores."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.session_dir = self.tmpdir

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_session_scope_skips_when_no_team_files(self):
        """When no team files exist, promote returns 0 (skip, not error)."""
        result = promote('session', self.session_dir, '', '')
        self.assertEqual(result, 0)

    def test_session_scope_uses_institutional_over_legacy(self):
        """Prefers team/institutional.md over team/MEMORY.md when both present."""
        team_dir = os.path.join(self.session_dir, 'coding')
        inst_path = os.path.join(team_dir, 'institutional.md')
        legacy_path = os.path.join(team_dir, 'MEMORY.md')
        _nonempty(inst_path)
        _nonempty(legacy_path)

        contexts_used = []

        def fake_summarize(stream, output, ctx, scope, **kw):
            contexts_used.extend(ctx)
            return 0

        with patch('projects.POC.scripts.summarize_session.summarize', side_effect=fake_summarize):
            promote('session', self.session_dir, '', '')

        self.assertIn(inst_path, contexts_used)
        self.assertNotIn(legacy_path, contexts_used)

    def test_session_scope_falls_back_to_legacy_memory(self):
        """Falls back to MEMORY.md when institutional.md is absent."""
        team_dir = os.path.join(self.session_dir, 'writing')
        legacy_path = os.path.join(team_dir, 'MEMORY.md')
        _nonempty(legacy_path)

        contexts_used = []

        def fake_summarize(stream, output, ctx, scope, **kw):
            contexts_used.extend(ctx)
            return 0

        with patch('projects.POC.scripts.summarize_session.summarize', side_effect=fake_summarize):
            promote('session', self.session_dir, '', '')

        self.assertIn(legacy_path, contexts_used)

    def test_session_scope_creates_institutional_and_tasks(self):
        """Both session-institutional and session-tasks scopes are called."""
        inst_path = os.path.join(self.session_dir, 'art', 'institutional.md')
        _nonempty(inst_path)

        scopes = []

        def fake_summarize(stream, output, ctx, scope, **kw):
            scopes.append(scope)
            return 0

        with patch('projects.POC.scripts.summarize_session.summarize', side_effect=fake_summarize):
            with patch('projects.POC.scripts.summarize_session._try_compact'):
                promote('session', self.session_dir, '', '')

        self.assertIn('session-institutional', scopes)
        self.assertIn('session-tasks', scopes)

    def test_session_scope_tasks_output_goes_to_session_tasks_dir(self):
        """Task output path is inside session_dir/tasks/."""
        _nonempty(os.path.join(self.session_dir, 'art', 'institutional.md'))

        outputs = []

        def fake_summarize(stream, output, ctx, scope, **kw):
            outputs.append(output)
            return 0

        with patch('projects.POC.scripts.summarize_session.summarize', side_effect=fake_summarize):
            with patch('projects.POC.scripts.summarize_session._try_compact'):
                promote('session', self.session_dir, '', '')

        tasks_outputs = [o for o in outputs if 'tasks' in o]
        self.assertTrue(
            any(o.startswith(os.path.join(self.session_dir, 'tasks')) for o in tasks_outputs),
            f"Expected output in session/tasks/, got: {outputs}",
        )

    def test_session_scope_compacts_institutional(self):
        """_try_compact is called on the session institutional.md."""
        _nonempty(os.path.join(self.session_dir, 'art', 'institutional.md'))

        compact_calls = []

        with patch('projects.POC.scripts.summarize_session.summarize', return_value=0):
            with patch('projects.POC.scripts.summarize_session._try_compact',
                       side_effect=compact_calls.append):
                promote('session', self.session_dir, '', '')

        expected = os.path.join(self.session_dir, 'institutional.md')
        self.assertIn(expected, compact_calls)


# ── promote() — project scope ─────────────────────────────────────────────────

class TestPromoteProject(unittest.TestCase):
    """promote('project') rolls up session files into project-level typed stores."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.session_dir = os.path.join(self.tmpdir, 'session')
        self.project_dir = os.path.join(self.tmpdir, 'project')
        os.makedirs(self.session_dir)
        os.makedirs(self.project_dir)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_project_scope_skips_when_no_session_files(self):
        result = promote('project', self.session_dir, self.project_dir, '')
        self.assertEqual(result, 0)

    def test_project_scope_reads_session_institutional(self):
        inst_path = os.path.join(self.session_dir, 'institutional.md')
        _nonempty(inst_path)

        contexts = []

        def fake_summarize(stream, output, ctx, scope, **kw):
            contexts.extend(ctx)
            return 0

        with patch('projects.POC.scripts.summarize_session.summarize', side_effect=fake_summarize):
            with patch('projects.POC.scripts.summarize_session._try_compact'):
                promote('project', self.session_dir, self.project_dir, '')

        self.assertIn(inst_path, contexts)

    def test_project_scope_writes_to_project_dir(self):
        _nonempty(os.path.join(self.session_dir, 'institutional.md'))

        outputs = []

        def fake_summarize(stream, output, ctx, scope, **kw):
            outputs.append(output)
            return 0

        with patch('projects.POC.scripts.summarize_session.summarize', side_effect=fake_summarize):
            with patch('projects.POC.scripts.summarize_session._try_compact'):
                promote('project', self.session_dir, self.project_dir, '')

        self.assertTrue(
            any(o.startswith(self.project_dir) for o in outputs),
            f"Expected output under project_dir, got: {outputs}",
        )

    def test_project_scope_calls_both_subscopes(self):
        _nonempty(os.path.join(self.session_dir, 'institutional.md'))

        scopes = []

        def fake_summarize(stream, output, ctx, scope, **kw):
            scopes.append(scope)
            return 0

        with patch('projects.POC.scripts.summarize_session.summarize', side_effect=fake_summarize):
            with patch('projects.POC.scripts.summarize_session._try_compact'):
                promote('project', self.session_dir, self.project_dir, '')

        self.assertIn('project-institutional', scopes)
        self.assertIn('project-tasks', scopes)

    def test_project_scope_compacts_project_institutional(self):
        _nonempty(os.path.join(self.session_dir, 'institutional.md'))

        compact_calls = []

        with patch('projects.POC.scripts.summarize_session.summarize', return_value=0):
            with patch('projects.POC.scripts.summarize_session._try_compact',
                       side_effect=compact_calls.append):
                promote('project', self.session_dir, self.project_dir, '')

        expected = os.path.join(self.project_dir, 'institutional.md')
        self.assertIn(expected, compact_calls)


# ── promote() — global scope ─────────────────────────────────────────────────

class TestPromoteGlobal(unittest.TestCase):
    """promote('global') reads project institutional.md → projects/ typed stores."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.projects_dir = os.path.join(self.tmpdir, 'projects')
        self.project_dir = os.path.join(self.projects_dir, 'my-project')
        os.makedirs(self.project_dir)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_global_scope_skips_when_no_project_institutional(self):
        result = promote('global', '', self.project_dir, self.projects_dir)
        self.assertEqual(result, 0)

    def test_global_scope_reads_project_institutional(self):
        inst_path = os.path.join(self.project_dir, 'institutional.md')
        _nonempty(inst_path)

        contexts = []

        def fake_summarize(stream, output, ctx, scope, **kw):
            contexts.extend(ctx)
            return 0

        with patch('projects.POC.scripts.summarize_session.summarize', side_effect=fake_summarize):
            with patch('projects.POC.scripts.summarize_session._try_compact'):
                promote('global', '', self.project_dir, self.projects_dir)

        self.assertIn(inst_path, contexts)

    def test_global_scope_writes_to_projects_dir(self):
        _nonempty(os.path.join(self.project_dir, 'institutional.md'))

        outputs = []

        def fake_summarize(stream, output, ctx, scope, **kw):
            outputs.append(output)
            return 0

        with patch('projects.POC.scripts.summarize_session.summarize', side_effect=fake_summarize):
            with patch('projects.POC.scripts.summarize_session._try_compact'):
                promote('global', '', self.project_dir, self.projects_dir)

        self.assertTrue(
            any(o.startswith(self.projects_dir) for o in outputs),
            f"Expected output under projects_dir, got: {outputs}",
        )

    def test_global_scope_calls_both_subscopes(self):
        _nonempty(os.path.join(self.project_dir, 'institutional.md'))

        scopes = []

        def fake_summarize(stream, output, ctx, scope, **kw):
            scopes.append(scope)
            return 0

        with patch('projects.POC.scripts.summarize_session.summarize', side_effect=fake_summarize):
            with patch('projects.POC.scripts.summarize_session._try_compact'):
                promote('global', '', self.project_dir, self.projects_dir)

        self.assertIn('global-institutional', scopes)
        self.assertIn('global-tasks', scopes)

    def test_global_scope_falls_back_to_parent_dir_when_output_dir_empty(self):
        """When output_dir is empty, falls back to dirname(project_dir)."""
        _nonempty(os.path.join(self.project_dir, 'institutional.md'))

        outputs = []

        def fake_summarize(stream, output, ctx, scope, **kw):
            outputs.append(output)
            return 0

        with patch('projects.POC.scripts.summarize_session.summarize', side_effect=fake_summarize):
            with patch('projects.POC.scripts.summarize_session._try_compact'):
                # output_dir is empty — should derive from project_dir
                promote('global', '', self.project_dir, '')

        expected_prefix = self.projects_dir
        self.assertTrue(
            any(o.startswith(expected_prefix) for o in outputs),
            f"Expected output under {expected_prefix}, got: {outputs}",
        )

    def test_global_scope_missing_project_dir_returns_1(self):
        result = promote('global', '', '', '')
        self.assertEqual(result, 1)


# ── promote() — prospective scope ─────────────────────────────────────────────

class TestPromoteProspective(unittest.TestCase):
    """promote('prospective') extracts pre-mortem accuracy learnings."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.session_dir = os.path.join(self.tmpdir, 'session')
        self.project_dir = os.path.join(self.tmpdir, 'project')
        os.makedirs(self.session_dir)
        os.makedirs(self.project_dir)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_prospective_skips_when_no_premortem_file(self):
        result = promote('prospective', self.session_dir, self.project_dir, '')
        self.assertEqual(result, 0)

    def test_prospective_uses_default_premortem_path(self):
        """Default pre-mortem path is session_dir/.premortem.md."""
        premortem = os.path.join(self.session_dir, '.premortem.md')
        _nonempty(premortem)

        calls = []

        def fake_summarize(stream, output, ctx, scope, **kw):
            calls.append({'scope': scope, 'ctx': ctx, 'output': output})
            return 0

        with patch('projects.POC.scripts.summarize_session.summarize', side_effect=fake_summarize):
            promote('prospective', self.session_dir, self.project_dir, '')

        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]['scope'], 'prospective')
        self.assertIn(premortem, calls[0]['ctx'])

    def test_prospective_uses_explicit_premortem_path(self):
        custom = os.path.join(self.tmpdir, 'custom-premortem.md')
        _nonempty(custom)

        calls = []

        def fake_summarize(stream, output, ctx, scope, **kw):
            calls.append(ctx)
            return 0

        with patch('projects.POC.scripts.summarize_session.summarize', side_effect=fake_summarize):
            promote('prospective', self.session_dir, self.project_dir, '',
                    premortem_file=custom)

        self.assertTrue(any(custom in c for c in calls))

    def test_prospective_output_has_prospective_suffix(self):
        _nonempty(os.path.join(self.session_dir, '.premortem.md'))

        outputs = []

        def fake_summarize(stream, output, ctx, scope, **kw):
            outputs.append(output)
            return 0

        with patch('projects.POC.scripts.summarize_session.summarize', side_effect=fake_summarize):
            promote('prospective', self.session_dir, self.project_dir, '')

        self.assertTrue(
            any(o.endswith('-prospective.md') for o in outputs),
            f"Expected -prospective.md suffix, got: {outputs}",
        )

    def test_prospective_output_goes_to_project_tasks(self):
        _nonempty(os.path.join(self.session_dir, '.premortem.md'))

        outputs = []

        def fake_summarize(stream, output, ctx, scope, **kw):
            outputs.append(output)
            return 0

        with patch('projects.POC.scripts.summarize_session.summarize', side_effect=fake_summarize):
            promote('prospective', self.session_dir, self.project_dir, '')

        tasks_dir = os.path.join(self.project_dir, 'tasks')
        self.assertTrue(
            any(o.startswith(tasks_dir) for o in outputs),
            f"Expected output under project/tasks/, got: {outputs}",
        )


# ── promote() — in-flight scope ───────────────────────────────────────────────

class TestPromoteInFlight(unittest.TestCase):
    """promote('in-flight') extracts assumption drift learnings."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.session_dir = os.path.join(self.tmpdir, 'session')
        self.project_dir = os.path.join(self.tmpdir, 'project')
        os.makedirs(self.session_dir)
        os.makedirs(self.project_dir)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_in_flight_skips_when_no_assumptions_file(self):
        result = promote('in-flight', self.session_dir, self.project_dir, '')
        self.assertEqual(result, 0)

    def test_in_flight_uses_default_assumptions_path(self):
        """Default assumptions path is session_dir/.assumptions.jsonl."""
        assumptions = os.path.join(self.session_dir, '.assumptions.jsonl')
        _nonempty(assumptions)

        calls = []

        def fake_summarize(stream, output, ctx, scope, **kw):
            calls.append({'scope': scope, 'ctx': ctx})
            return 0

        with patch('projects.POC.scripts.summarize_session.summarize', side_effect=fake_summarize):
            promote('in-flight', self.session_dir, self.project_dir, '')

        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]['scope'], 'in-flight')
        self.assertIn(assumptions, calls[0]['ctx'])

    def test_in_flight_uses_explicit_assumptions_path(self):
        custom = os.path.join(self.tmpdir, 'custom-assumptions.jsonl')
        _nonempty(custom)

        calls = []

        def fake_summarize(stream, output, ctx, scope, **kw):
            calls.append(ctx)
            return 0

        with patch('projects.POC.scripts.summarize_session.summarize', side_effect=fake_summarize):
            promote('in-flight', self.session_dir, self.project_dir, '',
                    assumptions_file=custom)

        self.assertTrue(any(custom in c for c in calls))

    def test_in_flight_output_has_inflight_suffix(self):
        _nonempty(os.path.join(self.session_dir, '.assumptions.jsonl'))

        outputs = []

        def fake_summarize(stream, output, ctx, scope, **kw):
            outputs.append(output)
            return 0

        with patch('projects.POC.scripts.summarize_session.summarize', side_effect=fake_summarize):
            promote('in-flight', self.session_dir, self.project_dir, '')

        self.assertTrue(
            any(o.endswith('-inflight.md') for o in outputs),
            f"Expected -inflight.md suffix, got: {outputs}",
        )

    def test_in_flight_output_goes_to_project_tasks(self):
        _nonempty(os.path.join(self.session_dir, '.assumptions.jsonl'))

        outputs = []

        def fake_summarize(stream, output, ctx, scope, **kw):
            outputs.append(output)
            return 0

        with patch('projects.POC.scripts.summarize_session.summarize', side_effect=fake_summarize):
            promote('in-flight', self.session_dir, self.project_dir, '')

        tasks_dir = os.path.join(self.project_dir, 'tasks')
        self.assertTrue(
            any(o.startswith(tasks_dir) for o in outputs),
            f"Expected output under project/tasks/, got: {outputs}",
        )


# ── promote() — corrective scope ─────────────────────────────────────────────

class TestPromoteCorrective(unittest.TestCase):
    """promote('corrective') extracts error pattern learnings from exec stream."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.session_dir = os.path.join(self.tmpdir, 'session')
        self.project_dir = os.path.join(self.tmpdir, 'project')
        os.makedirs(self.session_dir)
        os.makedirs(self.project_dir)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_corrective_skips_when_no_exec_stream(self):
        result = promote('corrective', self.session_dir, self.project_dir, '')
        self.assertEqual(result, 0)

    def test_corrective_uses_exec_stream(self):
        exec_stream = os.path.join(self.session_dir, '.exec-stream.jsonl')
        _nonempty(exec_stream)

        calls = []

        def fake_summarize(stream, output, ctx, scope, **kw):
            calls.append({'scope': scope, 'stream': stream})
            return 0

        with patch('projects.POC.scripts.summarize_session.summarize', side_effect=fake_summarize):
            promote('corrective', self.session_dir, self.project_dir, '')

        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]['scope'], 'corrective')
        self.assertEqual(calls[0]['stream'], exec_stream)

    def test_corrective_output_has_corrective_suffix(self):
        _nonempty(os.path.join(self.session_dir, '.exec-stream.jsonl'))

        outputs = []

        def fake_summarize(stream, output, ctx, scope, **kw):
            outputs.append(output)
            return 0

        with patch('projects.POC.scripts.summarize_session.summarize', side_effect=fake_summarize):
            promote('corrective', self.session_dir, self.project_dir, '')

        self.assertTrue(
            any(o.endswith('-corrective.md') for o in outputs),
            f"Expected -corrective.md suffix, got: {outputs}",
        )

    def test_corrective_output_goes_to_project_tasks(self):
        _nonempty(os.path.join(self.session_dir, '.exec-stream.jsonl'))

        outputs = []

        def fake_summarize(stream, output, ctx, scope, **kw):
            outputs.append(output)
            return 0

        with patch('projects.POC.scripts.summarize_session.summarize', side_effect=fake_summarize):
            promote('corrective', self.session_dir, self.project_dir, '')

        tasks_dir = os.path.join(self.project_dir, 'tasks')
        self.assertTrue(
            any(o.startswith(tasks_dir) for o in outputs),
            f"Expected output under project/tasks/, got: {outputs}",
        )

    def test_corrective_uses_explicit_stream_path(self):
        """stream_path kwarg overrides default exec stream discovery."""
        custom_stream = os.path.join(self.tmpdir, 'custom-stream.jsonl')
        _nonempty(custom_stream)

        calls = []

        def fake_summarize(stream, output, ctx, scope, **kw):
            calls.append(stream)
            return 0

        with patch('projects.POC.scripts.summarize_session.summarize', side_effect=fake_summarize):
            promote('corrective', self.session_dir, self.project_dir, '',
                    stream_path=custom_stream)

        self.assertIn(custom_stream, calls)


# ── promote() — unknown scope ─────────────────────────────────────────────────

class TestPromoteUnknownScope(unittest.TestCase):
    def test_unknown_scope_returns_1(self):
        result = promote('nonexistent-scope', '', '', '')
        self.assertEqual(result, 1)


# ── learnings.py helpers wiring ───────────────────────────────────────────────

class TestLearningsHelpers(unittest.TestCase):
    """Verify each _promote_* helper calls promote() with the right scope."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _patch_call_promote(self):
        return patch('projects.POC.orchestrator.learnings._call_promote')

    def test_promote_team_calls_team_scope(self):
        with self._patch_call_promote() as mock:
            _promote_team(infra_dir=self.tmpdir, scripts_dir='/scripts')
        mock.assert_called_once()
        args, kwargs = mock.call_args
        self.assertEqual(args[1], 'team')

    def test_promote_session_calls_session_scope(self):
        with self._patch_call_promote() as mock:
            _promote_session(infra_dir=self.tmpdir, scripts_dir='/scripts')
        mock.assert_called_once()
        args, kwargs = mock.call_args
        self.assertEqual(args[1], 'session')

    def test_promote_project_calls_project_scope(self):
        with self._patch_call_promote() as mock:
            _promote_project(
                infra_dir=self.tmpdir,
                project_dir=self.tmpdir,
                scripts_dir='/scripts',
            )
        mock.assert_called_once()
        args, kwargs = mock.call_args
        self.assertEqual(args[1], 'project')

    def test_promote_global_calls_global_scope(self):
        project_dir = os.path.join(self.tmpdir, 'my-project')
        with self._patch_call_promote() as mock:
            _promote_global(
                project_dir=project_dir,
                scripts_dir='/scripts',
                session_dir=self.tmpdir,
            )
        mock.assert_called_once()
        args, kwargs = mock.call_args
        self.assertEqual(args[1], 'global')

    def test_promote_prospective_calls_prospective_scope(self):
        with self._patch_call_promote() as mock:
            _promote_prospective(
                infra_dir=self.tmpdir,
                project_dir=self.tmpdir,
                scripts_dir='/scripts',
            )
        mock.assert_called_once()
        args, kwargs = mock.call_args
        self.assertEqual(args[1], 'prospective')

    def test_promote_in_flight_calls_in_flight_scope(self):
        with self._patch_call_promote() as mock:
            _promote_in_flight(
                infra_dir=self.tmpdir,
                project_dir=self.tmpdir,
                scripts_dir='/scripts',
            )
        mock.assert_called_once()
        args, kwargs = mock.call_args
        self.assertEqual(args[1], 'in-flight')

    def test_promote_corrective_calls_corrective_scope(self):
        with self._patch_call_promote() as mock:
            _promote_corrective(
                infra_dir=self.tmpdir,
                project_dir=self.tmpdir,
                scripts_dir='/scripts',
            )
        mock.assert_called_once()
        args, kwargs = mock.call_args
        self.assertEqual(args[1], 'corrective')


# ── extract_learnings() integration ──────────────────────────────────────────

class TestExtractLearningsIntegration(unittest.TestCase):
    """extract_learnings() runs all 10 scopes without raising."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.infra_dir = os.path.join(self.tmpdir, 'infra')
        self.project_dir = os.path.join(self.tmpdir, 'project')
        self.poc_root = self.tmpdir
        os.makedirs(self.infra_dir)
        os.makedirs(self.project_dir)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_extract_learnings_runs_without_raising(self):
        """extract_learnings completes without raising even when all inputs are absent."""
        with patch('projects.POC.orchestrator.learnings._run_summarize') as mock_run, \
             patch('projects.POC.orchestrator.learnings._call_promote') as mock_promote:
            _run(extract_learnings(
                infra_dir=self.infra_dir,
                project_dir=self.project_dir,
                session_worktree=self.tmpdir,
                task='Test task',
                poc_root=self.poc_root,
            ))

        # Original 3 scopes via _run_summarize (scope is a keyword arg)
        scopes_run = [call.kwargs.get('scope') for call in mock_run.call_args_list]
        self.assertIn('observations', scopes_run)
        self.assertIn('escalation', scopes_run)
        self.assertIn('intent-alignment', scopes_run)

        # 7 new scopes via _call_promote
        scopes_promoted = [call.args[1] for call in mock_promote.call_args_list]
        self.assertIn('team', scopes_promoted)
        self.assertIn('session', scopes_promoted)
        self.assertIn('project', scopes_promoted)
        self.assertIn('global', scopes_promoted)
        self.assertIn('prospective', scopes_promoted)
        self.assertIn('in-flight', scopes_promoted)
        self.assertIn('corrective', scopes_promoted)

    def test_extract_learnings_calls_all_10_scopes(self):
        """All 10 scopes are triggered — 3 via _run_summarize, 7 via _call_promote."""
        with patch('projects.POC.orchestrator.learnings._run_summarize') as mock_run, \
             patch('projects.POC.orchestrator.learnings._call_promote') as mock_promote:
            _run(extract_learnings(
                infra_dir=self.infra_dir,
                project_dir=self.project_dir,
                session_worktree=self.tmpdir,
                task='Test task',
                poc_root=self.poc_root,
            ))

        self.assertEqual(mock_run.call_count, 3, "Expected 3 _run_summarize calls")
        self.assertEqual(mock_promote.call_count, 7, "Expected 7 _call_promote calls")


# ── _run_summarize() direct-call behavior (issue #115 fixes) ─────────────────

class TestRunSummarize(unittest.TestCase):
    """Verify _run_summarize calls summarize() directly with correct args."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.scripts_dir = os.path.join(self.tmpdir, 'scripts')
        self.infra_dir = os.path.join(self.tmpdir, 'infra')
        os.makedirs(self.scripts_dir)
        os.makedirs(self.infra_dir)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _make_stream(self, name: str) -> str:
        path = os.path.join(self.infra_dir, name)
        Path(path).write_text('{"type":"test"}\n')
        return path

    def test_observations_uses_intent_stream(self):
        """observations scope reads .intent-stream.jsonl, not exec stream."""
        self._make_stream('.intent-stream.jsonl')
        self._make_stream('.exec-stream.jsonl')

        calls = []

        def fake_summarize(stream_path, output_path, ctx, scope, **kw):
            calls.append({'stream': stream_path, 'scope': scope})
            return 0

        with patch.dict('sys.modules', {'summarize_session': type(sys)('summarize_session')}):
            import sys as _sys
            _sys.modules['summarize_session'].summarize = fake_summarize
            from projects.POC.orchestrator.learnings import _run_summarize
            _run_summarize(self.scripts_dir, self.infra_dir,
                           scope='observations', output='/tmp/out.md')

        self.assertEqual(len(calls), 1)
        self.assertIn('.intent-stream.jsonl', calls[0]['stream'])

    def test_intent_alignment_uses_exec_stream(self):
        """intent-alignment scope reads .exec-stream.jsonl."""
        self._make_stream('.exec-stream.jsonl')

        calls = []

        def fake_summarize(stream_path, output_path, ctx, scope, **kw):
            calls.append({'stream': stream_path, 'scope': scope})
            return 0

        with patch.dict('sys.modules', {'summarize_session': type(sys)('summarize_session')}):
            sys.modules['summarize_session'].summarize = fake_summarize
            from projects.POC.orchestrator.learnings import _run_summarize
            _run_summarize(self.scripts_dir, self.infra_dir,
                           scope='intent-alignment', output='/tmp/out.md')

        self.assertEqual(len(calls), 1)
        self.assertIn('.exec-stream.jsonl', calls[0]['stream'])

    def test_skips_when_stream_missing(self):
        """Returns silently when the required stream file doesn't exist."""
        # No stream files created
        calls = []

        def fake_summarize(stream_path, output_path, ctx, scope, **kw):
            calls.append(scope)
            return 0

        with patch.dict('sys.modules', {'summarize_session': type(sys)('summarize_session')}):
            sys.modules['summarize_session'].summarize = fake_summarize
            from projects.POC.orchestrator.learnings import _run_summarize
            _run_summarize(self.scripts_dir, self.infra_dir,
                           scope='observations', output='/tmp/out.md')

        self.assertEqual(len(calls), 0)

    def test_logs_errors_instead_of_swallowing(self):
        """Errors are printed to stderr, not silently swallowed."""
        self._make_stream('.intent-stream.jsonl')

        def boom(*a, **kw):
            raise RuntimeError('test explosion')

        with patch.dict('sys.modules', {'summarize_session': type(sys)('summarize_session')}):
            sys.modules['summarize_session'].summarize = boom
            from projects.POC.orchestrator.learnings import _run_summarize

            import io
            captured = io.StringIO()
            with patch('sys.stderr', captured):
                _run_summarize(self.scripts_dir, self.infra_dir,
                               scope='observations', output='/tmp/out.md')

            self.assertIn('test explosion', captured.getvalue())


if __name__ == '__main__':
    unittest.main()
