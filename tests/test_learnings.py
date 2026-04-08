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
sys.path.insert(0, str(Path(__file__).parent.parent))

from teaparty.learning.episodic.summarize import promote
from teaparty.learning.extract import (
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

        with patch('teaparty.learning.episodic.summarize.summarize', side_effect=fake_summarize):
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

        with patch('teaparty.learning.episodic.summarize.summarize', side_effect=fake_summarize):
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

        with patch('teaparty.learning.episodic.summarize.summarize', side_effect=fake_summarize):
            promote('team', self.session_dir, '', '')

        # art, writing, editorial, research should not appear in outputs
        for unexpected_team in ('art', 'writing', 'editorial', 'research', 'configuration'):
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

        with patch('teaparty.learning.episodic.summarize.summarize', side_effect=fake_summarize):
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

        with patch('teaparty.learning.episodic.summarize.summarize', side_effect=fake_summarize):
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

        with patch('teaparty.learning.episodic.summarize.summarize', side_effect=fake_summarize):
            with patch('teaparty.learning.episodic.summarize._try_compact'):
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

        with patch('teaparty.learning.episodic.summarize.summarize', side_effect=fake_summarize):
            with patch('teaparty.learning.episodic.summarize._try_compact'):
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

        with patch('teaparty.learning.episodic.summarize.summarize', return_value=0):
            with patch('teaparty.learning.episodic.summarize._try_compact',
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

        with patch('teaparty.learning.episodic.summarize.summarize', side_effect=fake_summarize):
            with patch('teaparty.learning.episodic.summarize._try_compact'):
                promote('project', self.session_dir, self.project_dir, '')

        self.assertIn(inst_path, contexts)

    def test_project_scope_writes_to_project_dir(self):
        _nonempty(os.path.join(self.session_dir, 'institutional.md'))

        outputs = []

        def fake_summarize(stream, output, ctx, scope, **kw):
            outputs.append(output)
            return 0

        with patch('teaparty.learning.episodic.summarize.summarize', side_effect=fake_summarize):
            with patch('teaparty.learning.episodic.summarize._try_compact'):
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

        with patch('teaparty.learning.episodic.summarize.summarize', side_effect=fake_summarize):
            with patch('teaparty.learning.episodic.summarize._try_compact'):
                promote('project', self.session_dir, self.project_dir, '')

        self.assertIn('project-institutional', scopes)
        self.assertIn('project-tasks', scopes)

    def test_project_scope_compacts_project_institutional(self):
        _nonempty(os.path.join(self.session_dir, 'institutional.md'))

        compact_calls = []

        with patch('teaparty.learning.episodic.summarize.summarize', return_value=0):
            with patch('teaparty.learning.episodic.summarize._try_compact',
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

        with patch('teaparty.learning.episodic.summarize.summarize', side_effect=fake_summarize):
            with patch('teaparty.learning.episodic.summarize._try_compact'):
                promote('global', '', self.project_dir, self.projects_dir)

        self.assertIn(inst_path, contexts)

    def test_global_scope_writes_to_projects_dir(self):
        _nonempty(os.path.join(self.project_dir, 'institutional.md'))

        outputs = []

        def fake_summarize(stream, output, ctx, scope, **kw):
            outputs.append(output)
            return 0

        with patch('teaparty.learning.episodic.summarize.summarize', side_effect=fake_summarize):
            with patch('teaparty.learning.episodic.summarize._try_compact'):
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

        with patch('teaparty.learning.episodic.summarize.summarize', side_effect=fake_summarize):
            with patch('teaparty.learning.episodic.summarize._try_compact'):
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

        with patch('teaparty.learning.episodic.summarize.summarize', side_effect=fake_summarize):
            with patch('teaparty.learning.episodic.summarize._try_compact'):
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

        with patch('teaparty.learning.episodic.summarize.summarize', side_effect=fake_summarize):
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

        with patch('teaparty.learning.episodic.summarize.summarize', side_effect=fake_summarize):
            promote('prospective', self.session_dir, self.project_dir, '',
                    premortem_file=custom)

        self.assertTrue(any(custom in c for c in calls))

    def test_prospective_output_has_prospective_suffix(self):
        _nonempty(os.path.join(self.session_dir, '.premortem.md'))

        outputs = []

        def fake_summarize(stream, output, ctx, scope, **kw):
            outputs.append(output)
            return 0

        with patch('teaparty.learning.episodic.summarize.summarize', side_effect=fake_summarize):
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

        with patch('teaparty.learning.episodic.summarize.summarize', side_effect=fake_summarize):
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

        with patch('teaparty.learning.episodic.summarize.summarize', side_effect=fake_summarize):
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

        with patch('teaparty.learning.episodic.summarize.summarize', side_effect=fake_summarize):
            promote('in-flight', self.session_dir, self.project_dir, '',
                    assumptions_file=custom)

        self.assertTrue(any(custom in c for c in calls))

    def test_in_flight_output_has_inflight_suffix(self):
        _nonempty(os.path.join(self.session_dir, '.assumptions.jsonl'))

        outputs = []

        def fake_summarize(stream, output, ctx, scope, **kw):
            outputs.append(output)
            return 0

        with patch('teaparty.learning.episodic.summarize.summarize', side_effect=fake_summarize):
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

        with patch('teaparty.learning.episodic.summarize.summarize', side_effect=fake_summarize):
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

        with patch('teaparty.learning.episodic.summarize.summarize', side_effect=fake_summarize):
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

        with patch('teaparty.learning.episodic.summarize.summarize', side_effect=fake_summarize):
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

        with patch('teaparty.learning.episodic.summarize.summarize', side_effect=fake_summarize):
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

        with patch('teaparty.learning.episodic.summarize.summarize', side_effect=fake_summarize):
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
        return patch('teaparty.learning.extract._call_promote')

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
        with patch('teaparty.learning.extract._run_summarize') as mock_run, \
             patch('teaparty.learning.extract._call_promote') as mock_promote:
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
        with patch('teaparty.learning.extract._run_summarize') as mock_run, \
             patch('teaparty.learning.extract._call_promote') as mock_promote:
            _run(extract_learnings(
                infra_dir=self.infra_dir,
                project_dir=self.project_dir,
                session_worktree=self.tmpdir,
                task='Test task',
                poc_root=self.poc_root,
            ))

        self.assertEqual(mock_run.call_count, 3, "Expected 3 _run_summarize calls")
        self.assertEqual(mock_promote.call_count, 7, "Expected 7 _call_promote calls")


# ── compact_file() wiring through promote path (issue #86) ───────────────────

class TestCompactFileWiring(unittest.TestCase):
    """Verify compact_file() is called after institutional.md writes.

    compact_file() is called inside promote() via _try_compact() for the
    session, project, and global scopes. Because _call_promote imports
    promote() via sys.path (not the dotted module path), standard
    unittest.mock.patch cannot intercept _try_compact. These tests verify
    the behavior by monkey-patching the sys.path-loaded module directly.
    """

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        # POC scripts directory: tests/ -> orchestrator/ -> POC/ -> scripts/
        self.scripts_dir = str(
            Path(__file__).parent.parent / 'teaparty' / 'learning' / 'episodic'
        )
        self._sys_path_before = sys.path[:]

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)
        # Restore sys.path exactly to the state before this test ran.
        # _load_summarize_session adds scripts_dir; this undoes only what was added.
        sys.path[:] = self._sys_path_before

    def _load_summarize_session(self):
        """Get the summarize_session module that _call_promote will use.

        _call_promote adds scripts_dir to sys.path and does
        'from summarize_session import promote'. To intercept _try_compact,
        we pre-load the module into sys.modules so _call_promote's import
        reuses the same instance we can monkey-patch.
        """
        if self.scripts_dir not in sys.path:
            sys.path.insert(0, self.scripts_dir)
        # Always reload to ensure we get the real module with all attributes
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            'summarize',
            os.path.join(self.scripts_dir, 'summarize.py'),
        )
        mod = importlib.util.module_from_spec(spec)
        sys.modules['summarize'] = mod
        spec.loader.exec_module(mod)
        return mod

    def test_session_scope_calls_try_compact_on_institutional(self):
        """promote('session') calls _try_compact on session/institutional.md."""
        mod = self._load_summarize_session()
        original_compact = mod._try_compact
        original_summarize = mod.summarize

        compact_calls = []
        mod._try_compact = lambda path: compact_calls.append(path)
        mod.summarize = lambda *a, **kw: 0

        try:
            # Create team institutional.md so session has input
            team_dir = os.path.join(self.tmpdir, 'coding')
            os.makedirs(team_dir)
            _nonempty(os.path.join(team_dir, 'institutional.md'))

            from teaparty.learning.extract import _call_promote
            _call_promote(self.scripts_dir, 'session',
                          session_dir=self.tmpdir, project_dir='', output_dir='')

            expected = os.path.join(self.tmpdir, 'institutional.md')
            self.assertIn(expected, compact_calls,
                          f"Expected compact on {expected}, got: {compact_calls}")
        finally:
            mod._try_compact = original_compact
            mod.summarize = original_summarize

    def test_project_scope_calls_try_compact_on_institutional(self):
        """promote('project') calls _try_compact on project/institutional.md."""
        mod = self._load_summarize_session()
        original_compact = mod._try_compact
        original_summarize = mod.summarize

        compact_calls = []
        mod._try_compact = lambda path: compact_calls.append(path)
        mod.summarize = lambda *a, **kw: 0

        try:
            session_dir = os.path.join(self.tmpdir, 'session')
            project_dir = os.path.join(self.tmpdir, 'project')
            os.makedirs(session_dir)
            os.makedirs(project_dir)
            _nonempty(os.path.join(session_dir, 'institutional.md'))

            from teaparty.learning.extract import _call_promote
            _call_promote(self.scripts_dir, 'project',
                          session_dir=session_dir, project_dir=project_dir, output_dir='')

            expected = os.path.join(project_dir, 'institutional.md')
            self.assertIn(expected, compact_calls,
                          f"Expected compact on {expected}, got: {compact_calls}")
        finally:
            mod._try_compact = original_compact
            mod.summarize = original_summarize

    def test_global_scope_calls_try_compact_on_institutional(self):
        """promote('global') calls _try_compact on projects/institutional.md."""
        mod = self._load_summarize_session()
        original_compact = mod._try_compact
        original_summarize = mod.summarize

        compact_calls = []
        mod._try_compact = lambda path: compact_calls.append(path)
        mod.summarize = lambda *a, **kw: 0

        try:
            projects_dir = os.path.join(self.tmpdir, 'projects')
            project_dir = os.path.join(projects_dir, 'myproj')
            os.makedirs(project_dir)
            _nonempty(os.path.join(project_dir, 'institutional.md'))

            from teaparty.learning.extract import _call_promote
            _call_promote(self.scripts_dir, 'global',
                          session_dir='', project_dir=project_dir,
                          output_dir=projects_dir)

            expected = os.path.join(projects_dir, 'institutional.md')
            self.assertIn(expected, compact_calls,
                          f"Expected compact on {expected}, got: {compact_calls}")
        finally:
            mod._try_compact = original_compact
            mod.summarize = original_summarize

    def test_team_scope_does_not_compact(self):
        """promote('team') does NOT call _try_compact (no institutional.md at team level)."""
        mod = self._load_summarize_session()
        original_compact = mod._try_compact
        original_summarize = mod.summarize

        compact_calls = []
        mod._try_compact = lambda path: compact_calls.append(path)
        mod.summarize = lambda *a, **kw: 0

        try:
            # Create dispatch memory
            dispatch_dir = os.path.join(self.tmpdir, 'coding', 'dispatch-001')
            os.makedirs(dispatch_dir)
            _nonempty(os.path.join(dispatch_dir, 'MEMORY.md'))

            from teaparty.learning.extract import _call_promote
            _call_promote(self.scripts_dir, 'team',
                          session_dir=self.tmpdir, project_dir='', output_dir='')

            self.assertEqual(compact_calls, [],
                             f"team scope should not compact, but got: {compact_calls}")
        finally:
            mod._try_compact = original_compact
            mod.summarize = original_summarize


# ── _call_promote import path (issue #85 verification) ───────────────────────

class TestCallPromoteImportPath(unittest.TestCase):
    """Verify _call_promote can import promote() from the real scripts dir."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        # Use the actual scripts directory from the project
        self.scripts_dir = str(
            Path(__file__).parent.parent / 'teaparty' / 'learning' / 'episodic'
        )

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_call_promote_imports_promote_from_real_scripts_dir(self):
        """_call_promote successfully imports and calls promote() using the
        real scripts_dir path (not mocked). This verifies the sys.path
        manipulation works end-to-end.
        """
        from teaparty.learning.extract import _call_promote
        # Team scope with empty session_dir returns 1 (missing session_dir)
        # but the important thing is it doesn't raise an ImportError.
        # We patch summarize to avoid real LLM calls.
        with patch('teaparty.learning.episodic.summarize.summarize', return_value=0):
            _call_promote(self.scripts_dir, 'team', session_dir='', project_dir='', output_dir='')

    def test_call_promote_invokes_all_seven_scopes_without_import_error(self):
        """Each of the 7 promote scopes can be imported and dispatched."""
        from teaparty.learning.extract import _call_promote
        scopes = ['team', 'session', 'project', 'global',
                  'prospective', 'in-flight', 'corrective']
        with patch('teaparty.learning.episodic.summarize.summarize', return_value=0):
            for scope in scopes:
                with self.subTest(scope=scope):
                    # Should not raise ImportError or AttributeError
                    _call_promote(
                        self.scripts_dir, scope,
                        session_dir=self.tmpdir,
                        project_dir=self.tmpdir,
                        output_dir=self.tmpdir,
                    )

    def test_call_promote_cleans_up_sys_path(self):
        """_call_promote must not leave scripts_dir permanently added to sys.path."""
        from teaparty.learning.extract import _call_promote
        before_count = sys.path.count(self.scripts_dir)
        with patch('teaparty.learning.episodic.summarize.summarize', return_value=0):
            _call_promote(self.scripts_dir, 'team', session_dir='', project_dir='', output_dir='')
        after_count = sys.path.count(self.scripts_dir)
        self.assertEqual(after_count, before_count,
                         "_call_promote must not net-add scripts_dir to sys.path")


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

        with patch.dict('sys.modules', {'summarize': type(sys)('summarize')}):
            import sys as _sys
            _sys.modules['summarize'].summarize = fake_summarize
            from teaparty.learning.extract import _run_summarize
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

        with patch.dict('sys.modules', {'summarize': type(sys)('summarize')}):
            sys.modules['summarize'].summarize = fake_summarize
            from teaparty.learning.extract import _run_summarize
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

        with patch.dict('sys.modules', {'summarize': type(sys)('summarize')}):
            sys.modules['summarize'].summarize = fake_summarize
            from teaparty.learning.extract import _run_summarize
            _run_summarize(self.scripts_dir, self.infra_dir,
                           scope='observations', output='/tmp/out.md')

        self.assertEqual(len(calls), 0)

    def test_logs_errors_instead_of_swallowing(self):
        """Errors are logged, not silently swallowed."""
        self._make_stream('.intent-stream.jsonl')

        def boom(*a, **kw):
            raise RuntimeError('test explosion')

        with patch.dict('sys.modules', {'summarize': type(sys)('summarize')}):
            sys.modules['summarize'].summarize = boom
            from teaparty.learning.extract import _run_summarize

            import logging
            with self.assertLogs('teaparty.learning.extract', level='WARNING') as cm:
                _run_summarize(self.scripts_dir, self.infra_dir,
                               scope='observations', output='/tmp/out.md')

            self.assertTrue(any('test explosion' in msg for msg in cm.output))


# ── Promotion chain: recurrence detection (issue #217) ───────────────────────

class TestRecurrenceDetection(unittest.TestCase):
    """Session→project promotion requires N recurrences via similarity."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.project_dir = os.path.join(self.tmpdir, 'project')
        os.makedirs(self.project_dir)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _make_session_dir(self, session_name: str) -> str:
        """Create a job directory with a tasks/ subdirectory."""
        session_dir = os.path.join(
            self.project_dir, '.teaparty', 'jobs', session_name,
        )
        os.makedirs(os.path.join(session_dir, 'tasks'), exist_ok=True)
        return session_dir

    def _make_session_learning(self, session_dir: str, content: str) -> str:
        """Write a learning entry to a session's tasks/ directory."""
        from teaparty.learning.episodic.entry import make_entry, serialize_entry
        entry = make_entry(content, type='procedural', domain='task')
        fname = f'{entry.id}.md'
        fpath = os.path.join(session_dir, 'tasks', fname)
        Path(fpath).write_text(serialize_entry(entry))
        return fpath

    def test_learning_below_threshold_not_promoted(self):
        """A learning seen in only 1 session is not promoted to project scope."""
        from teaparty.learning.promotion import find_recurring_learnings

        s1 = self._make_session_dir('session-20260301-100000')
        self._make_session_learning(s1, 'Always run lint before committing code.')

        result = find_recurring_learnings(
            self.project_dir, min_recurrences=3, similarity_fn=_exact_match,
        )
        self.assertEqual(len(result.to_promote), 0)

    def test_learning_at_threshold_is_promoted(self):
        """A learning seen in 3 distinct sessions qualifies for promotion."""
        from teaparty.learning.promotion import find_recurring_learnings

        for i in range(3):
            s = self._make_session_dir(f'session-2026030{i+1}-100000')
            self._make_session_learning(s, 'Always run lint before committing code.')

        result = find_recurring_learnings(
            self.project_dir, min_recurrences=3, similarity_fn=_exact_match,
        )
        self.assertEqual(len(result.to_promote), 1)
        self.assertIn('lint', result.to_promote[0].content)

    def test_recurrence_uses_similarity_not_exact_match(self):
        """Semantically similar learnings across sessions count as recurrences."""
        from teaparty.learning.promotion import find_recurring_learnings

        variations = [
            'Always run lint before committing code.',
            'Run the linter before every commit to catch issues early.',
            'Lint your code before commits to avoid CI failures.',
        ]
        for i, text in enumerate(variations):
            s = self._make_session_dir(f'session-2026030{i+1}-100000')
            self._make_session_learning(s, text)

        # With a similarity function that considers these as matching
        def _always_similar(a: str, b: str) -> float:
            return 0.95  # above any reasonable threshold

        result = find_recurring_learnings(
            self.project_dir, min_recurrences=3, similarity_fn=_always_similar,
        )
        self.assertEqual(len(result.to_promote), 1)

    def test_distinct_learnings_not_conflated(self):
        """Learnings on different topics don't count toward each other's recurrence."""
        from teaparty.learning.promotion import find_recurring_learnings

        for i in range(3):
            s = self._make_session_dir(f'session-2026030{i+1}-100000')
            # Only "lint" appears in all 3, "database" only in 2
            self._make_session_learning(s, 'Always run lint before committing code.')
            if i < 2:
                self._make_session_learning(s, 'Backup the database before migration.')

        result = find_recurring_learnings(
            self.project_dir, min_recurrences=3, similarity_fn=_exact_match,
        )
        # Only the lint learning qualifies (3 recurrences); database has only 2
        self.assertEqual(len(result.to_promote), 1)
        self.assertIn('lint', result.to_promote[0].content)

    def test_already_promoted_learnings_not_re_promoted(self):
        """Learnings that already exist at project scope are not duplicated."""
        from teaparty.learning.promotion import find_recurring_learnings
        from teaparty.learning.episodic.entry import make_entry, serialize_entry

        # Create 3 sessions with same learning
        for i in range(3):
            s = self._make_session_dir(f'session-2026030{i+1}-100000')
            self._make_session_learning(s, 'Always run lint before committing code.')

        # Also write it at project scope already
        tasks_dir = os.path.join(self.project_dir, 'tasks')
        os.makedirs(tasks_dir, exist_ok=True)
        entry = make_entry('Always run lint before committing code.',
                           type='procedural', domain='task')
        Path(os.path.join(tasks_dir, f'{entry.id}.md')).write_text(
            serialize_entry(entry))

        result = find_recurring_learnings(
            self.project_dir, min_recurrences=3, similarity_fn=_exact_match,
        )
        self.assertEqual(len(result.to_promote), 0)

    def test_matching_project_entries_are_reinforced(self):
        """When session learnings match existing project entries, reinforce the project entry."""
        from teaparty.learning.promotion import find_recurring_learnings
        from teaparty.learning.episodic.entry import make_entry, serialize_entry

        # Create 3 sessions with same learning
        for i in range(3):
            s = self._make_session_dir(f'session-2026030{i+1}-100000')
            self._make_session_learning(s, 'Always run lint before committing code.')

        # Write matching entry at project scope
        tasks_dir = os.path.join(self.project_dir, 'tasks')
        os.makedirs(tasks_dir, exist_ok=True)
        entry = make_entry('Always run lint before committing code.',
                           type='procedural', domain='task')
        entry_path = os.path.join(tasks_dir, f'{entry.id}.md')
        Path(entry_path).write_text(serialize_entry(entry))

        result = find_recurring_learnings(
            self.project_dir, min_recurrences=3, similarity_fn=_exact_match,
        )
        # Nothing to promote (already exists), but should reinforce
        self.assertEqual(len(result.to_promote), 0)
        self.assertEqual(len(result.to_reinforce), 1)
        self.assertIn(entry_path, result.to_reinforce)

    def test_institutional_learnings_scanned_for_recurrence(self):
        """Session institutional.md entries are also scanned for recurrence."""
        from teaparty.learning.promotion import find_recurring_learnings
        from teaparty.learning.episodic.entry import make_entry, serialize_entry

        for i in range(3):
            s = self._make_session_dir(f'session-2026030{i+1}-100000')
            entry = make_entry('Always review PRs before merging.',
                               type='directive', domain='team')
            inst_path = os.path.join(s, 'institutional.md')
            Path(inst_path).write_text(serialize_entry(entry))

        result = find_recurring_learnings(
            self.project_dir, min_recurrences=3, similarity_fn=_exact_match,
        )
        self.assertEqual(len(result.to_promote), 1)
        self.assertIn('review PRs', result.to_promote[0].content)


# ── Promotion chain: proxy exclusion (issue #217) ────────────────────────────

class TestProxyExclusion(unittest.TestCase):
    """Proxy learnings must not be promoted through the chain."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.project_dir = os.path.join(self.tmpdir, 'project')
        os.makedirs(self.project_dir)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _make_session_dir(self, session_name: str) -> str:
        session_dir = os.path.join(
            self.project_dir, '.sessions', session_name,
        )
        os.makedirs(session_dir, exist_ok=True)
        return session_dir

    def test_proxy_md_excluded_from_promotion(self):
        """Learnings from proxy.md are excluded from session→project promotion."""
        from teaparty.learning.promotion import is_proxy_learning

        self.assertTrue(is_proxy_learning('/some/path/proxy.md'))
        self.assertTrue(is_proxy_learning('/project/proxy.md'))

    def test_proxy_tasks_excluded_from_promotion(self):
        """Learnings from proxy-tasks/ are excluded from promotion."""
        from teaparty.learning.promotion import is_proxy_learning

        self.assertTrue(is_proxy_learning('/project/proxy-tasks/correction-abc.md'))
        self.assertTrue(is_proxy_learning('/project/proxy-tasks/pattern-xyz.md'))

    def test_non_proxy_not_excluded(self):
        """Regular task and institutional learnings are not excluded."""
        from teaparty.learning.promotion import is_proxy_learning

        self.assertFalse(is_proxy_learning('/project/tasks/20260301.md'))
        self.assertFalse(is_proxy_learning('/project/institutional.md'))

    def test_recurring_proxy_learnings_not_promoted(self):
        """Even if proxy learnings recur across sessions, they don't promote."""
        from teaparty.learning.promotion import find_recurring_learnings
        from teaparty.learning.episodic.entry import make_entry, serialize_entry

        for i in range(3):
            session_dir = self._make_session_dir(f'session-2026030{i+1}-100000')
            proxy_tasks = os.path.join(session_dir, 'proxy-tasks')
            os.makedirs(proxy_tasks, exist_ok=True)
            entry = make_entry('User prefers verbose explanations.',
                               type='declarative', domain='task')
            Path(os.path.join(proxy_tasks, f'{entry.id}.md')).write_text(
                serialize_entry(entry))

        result = find_recurring_learnings(
            self.project_dir, min_recurrences=3, similarity_fn=_exact_match,
        )
        self.assertEqual(len(result.to_promote), 0)


# ── Promotion chain: project→global filtering (issue #217) ───────────────────

class TestProjectAgnosticFiltering(unittest.TestCase):
    """Project→global promotion requires project-agnostic LLM judgment."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.project_dir = os.path.join(self.tmpdir, 'project')
        os.makedirs(os.path.join(self.project_dir, 'tasks'), exist_ok=True)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _make_project_learning(self, content: str) -> str:
        from teaparty.learning.episodic.entry import make_entry, serialize_entry
        entry = make_entry(content, type='procedural', domain='task')
        fpath = os.path.join(self.project_dir, 'tasks', f'{entry.id}.md')
        Path(fpath).write_text(serialize_entry(entry))
        return fpath

    def test_project_specific_learning_not_promoted_to_global(self):
        """A learning tied to a specific codebase does not promote to global."""
        from teaparty.learning.promotion import filter_project_agnostic

        learnings_with_judgment = [
            ('Use SQLAlchemy for the TeaParty database layer.', False),
        ]

        def mock_judge(content: str) -> bool:
            for text, result in learnings_with_judgment:
                if text == content:
                    return result
            return False

        self._make_project_learning(learnings_with_judgment[0][0])
        from teaparty.learning.episodic.entry import make_entry
        entry = make_entry(learnings_with_judgment[0][0])

        result = filter_project_agnostic([entry], judge_fn=mock_judge)
        self.assertEqual(len(result), 0)

    def test_project_agnostic_learning_promoted_to_global(self):
        """A generalizable learning passes the filter for global promotion."""
        from teaparty.learning.promotion import filter_project_agnostic

        def mock_judge(content: str) -> bool:
            return True  # judge says it's generalizable

        from teaparty.learning.episodic.entry import make_entry
        entry = make_entry('Always run tests before merging to main.')

        result = filter_project_agnostic([entry], judge_fn=mock_judge)
        self.assertEqual(len(result), 1)

    def test_llm_failure_defaults_to_not_promoting(self):
        """If the LLM judge fails, the learning is NOT promoted (conservative)."""
        from teaparty.learning.promotion import filter_project_agnostic

        def failing_judge(content: str) -> bool:
            raise RuntimeError('LLM call failed')

        from teaparty.learning.episodic.entry import make_entry
        entry = make_entry('Always run tests before merging.')

        result = filter_project_agnostic([entry], judge_fn=failing_judge)
        self.assertEqual(len(result), 0)


# ── Promotion chain: MemoryEntry metadata (issue #217) ───────────────────────

class TestPromotionMetadata(unittest.TestCase):
    """MemoryEntry gains optional promoted_from and promoted_at fields."""

    def test_entry_has_promoted_from_field(self):
        """MemoryEntry has a promoted_from field defaulting to empty string."""
        from teaparty.learning.episodic.entry import MemoryEntry
        entry = MemoryEntry(
            id='test-id', type='procedural', domain='task',
            importance=0.5, phase='unknown', status='active',
            reinforcement_count=0, last_reinforced='2026-03-01',
            created_at='2026-03-01', content='test',
        )
        self.assertEqual(entry.promoted_from, '')

    def test_entry_has_promoted_at_field(self):
        """MemoryEntry has a promoted_at field defaulting to empty string."""
        from teaparty.learning.episodic.entry import MemoryEntry
        entry = MemoryEntry(
            id='test-id', type='procedural', domain='task',
            importance=0.5, phase='unknown', status='active',
            reinforcement_count=0, last_reinforced='2026-03-01',
            created_at='2026-03-01', content='test',
        )
        self.assertEqual(entry.promoted_at, '')

    def test_serialize_includes_promotion_metadata(self):
        """Serialization includes promoted_from and promoted_at when non-empty."""
        from teaparty.learning.episodic.entry import MemoryEntry, serialize_entry
        entry = MemoryEntry(
            id='test-id', type='procedural', domain='task',
            importance=0.5, phase='unknown', status='active',
            reinforcement_count=0, last_reinforced='2026-03-01',
            created_at='2026-03-01', content='test content',
            promoted_from='session', promoted_at='2026-03-26',
        )
        text = serialize_entry(entry)
        self.assertIn('promoted_from: session', text)
        self.assertIn("promoted_at: '2026-03-26'", text)

    def test_parse_entry_with_promotion_metadata(self):
        """Entries with promotion metadata round-trip through parse/serialize."""
        from teaparty.learning.episodic.entry import parse_entry

        text = """---
id: abc-123
type: procedural
domain: task
importance: 0.7
phase: unknown
status: active
reinforcement_count: 2
last_reinforced: '2026-03-20'
created_at: '2026-03-01'
promoted_from: session
promoted_at: '2026-03-26'
---
Always run lint before committing."""
        entry = parse_entry(text)
        self.assertEqual(entry.promoted_from, 'session')
        self.assertEqual(entry.promoted_at, '2026-03-26')

    def test_parse_entry_without_promotion_metadata_defaults(self):
        """Existing entries without promotion fields parse with empty defaults."""
        from teaparty.learning.episodic.entry import parse_entry

        text = """---
id: abc-123
type: procedural
domain: task
importance: 0.7
phase: unknown
status: active
reinforcement_count: 2
last_reinforced: '2026-03-20'
created_at: '2026-03-01'
---
A learning without promotion metadata."""
        entry = parse_entry(text)
        self.assertEqual(entry.promoted_from, '')
        self.assertEqual(entry.promoted_at, '')


# ── Promotion chain: integration with extract_learnings (issue #217) ─────────

class TestPromotionIntegration(unittest.TestCase):
    """extract_learnings() triggers promotion evaluation after rollup scopes."""

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

    def test_extract_learnings_runs_promotion_evaluation(self):
        """extract_learnings includes a promotion-evaluation scope."""
        scopes_run = []

        async def tracking_run_scope(scope_name, fn, *args, **kwargs):
            scopes_run.append(scope_name)

        with patch('teaparty.learning.extract._run_summarize'), \
             patch('teaparty.learning.extract._call_promote'):
            with patch('teaparty.learning.extract._evaluate_promotions') as mock_eval:
                _run(extract_learnings(
                    infra_dir=self.infra_dir,
                    project_dir=self.project_dir,
                    session_worktree=self.tmpdir,
                    task='Test task',
                    poc_root=self.poc_root,
                ))
                mock_eval.assert_called_once()


# ── Similarity helper for tests ──────────────────────────────────────────────

def _exact_match(a: str, b: str) -> float:
    """Exact case-insensitive match returns 1.0, else 0.0."""
    return 1.0 if a.strip().lower() == b.strip().lower() else 0.0


if __name__ == '__main__':
    unittest.main()
