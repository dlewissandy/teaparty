#!/usr/bin/env python3
"""Tests for issue #148: Eliminate dual-location artifact bookkeeping.

Session artifacts (INTENT.md, PLAN.md) should exist in exactly one location
(infra_dir) after relocation — not in both the worktree and infra_dir.

Covers:
  1. _relocate_misplaced_artifact moves (not copies) the source file.
  2. _commit_artifacts does NOT commit INTENT.md on INTENT_ASSERT.
  3. _commit_artifacts does NOT commit PLAN.md on PLAN_ASSERT.
  4. _commit_artifacts still commits deliverables on TASK_ASSERT.
"""
import asyncio
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent.parent))

from projects.POC.orchestrator.actors import _relocate_misplaced_artifact
from projects.POC.orchestrator.engine import Orchestrator
from projects.POC.orchestrator.events import EventBus
from projects.POC.scripts.cfa_state import make_initial_state, transition


def _run(coro):
    return asyncio.run(coro)


def _make_stream(tmpdir, events):
    """Write a minimal stream JSONL with tool-use events."""
    path = os.path.join(tmpdir, '.stream.jsonl')
    with open(path, 'w') as f:
        for tool_name, file_path in events:
            evt = {
                'type': 'assistant',
                'message': {
                    'content': [{
                        'type': 'tool_use',
                        'name': tool_name,
                        'input': {'file_path': file_path},
                    }],
                },
            }
            f.write(json.dumps(evt) + '\n')
    return path


def _init_git_repo(path):
    """Initialize a git repo with an initial commit."""
    subprocess.run(['git', 'init', '-b', 'main'], cwd=path, capture_output=True, check=True)
    subprocess.run(['git', 'config', 'user.email', 'test@test.com'], cwd=path, capture_output=True, check=True)
    subprocess.run(['git', 'config', 'user.name', 'Test'], cwd=path, capture_output=True, check=True)
    Path(os.path.join(path, '.gitkeep')).touch()
    subprocess.run(['git', 'add', '.'], cwd=path, capture_output=True, check=True)
    subprocess.run(['git', 'commit', '-m', 'init'], cwd=path, capture_output=True, check=True)


def _git_log_oneline(worktree, path=None):
    """Return list of one-line log entries, optionally filtered to a path."""
    cmd = ['git', 'log', '--oneline']
    if path:
        cmd += ['--', path]
    r = subprocess.run(cmd, cwd=worktree, capture_output=True, text=True)
    return [line for line in r.stdout.strip().splitlines() if line]


def _make_orchestrator(tmpdir, cfa_state=None):
    """Create a minimal Orchestrator with a real git worktree."""
    infra_dir = os.path.join(tmpdir, '.session')
    worktree = os.path.join(tmpdir, 'worktree')
    project_dir = os.path.join(tmpdir, 'project')
    os.makedirs(infra_dir, exist_ok=True)
    os.makedirs(worktree, exist_ok=True)
    os.makedirs(project_dir, exist_ok=True)

    _init_git_repo(worktree)

    if cfa_state is None:
        cfa = make_initial_state(task_id='test')
        cfa = transition(cfa, 'propose')   # → PROPOSAL
    else:
        cfa = cfa_state

    config = MagicMock()
    bus = EventBus()

    return Orchestrator(
        cfa_state=cfa,
        phase_config=config,
        event_bus=bus,
        input_provider=AsyncMock(),
        infra_dir=infra_dir,
        project_workdir=project_dir,
        session_worktree=worktree,
        proxy_model_path=os.path.join(tmpdir, '.proxy.json'),
        project_slug='test-project',
        poc_root=tmpdir,
        task='test task',
        session_id='20260325-120000',
    )


def _make_actor_result(action='approve'):
    from projects.POC.orchestrator.actors import ActorResult
    return ActorResult(action=action, data={})


# ── Relocate uses move, not copy ──────────────────────────────────────────


class TestRelocateMovesNotCopies(unittest.TestCase):
    """_relocate_misplaced_artifact must move the source file, not copy it.

    After relocation, the artifact should exist only in infra_dir.
    The source (e.g. worktree copy) must be removed.  Issue #148.
    """

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.infra_dir = os.path.join(self.tmpdir, 'infra')
        self.worktree = os.path.join(self.tmpdir, 'worktree')
        os.makedirs(self.infra_dir)
        os.makedirs(self.worktree)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_source_removed_after_relocation(self):
        """After relocation, the source file must not exist — move semantics."""
        worktree_intent = os.path.join(self.worktree, 'INTENT.md')
        Path(worktree_intent).write_text('# Intent\nDo the thing.')

        stream = _make_stream(self.infra_dir, [('Write', worktree_intent)])

        result = _relocate_misplaced_artifact(self.infra_dir, stream, 'INTENT.md')

        self.assertTrue(result)
        # Target must exist in infra_dir
        infra_intent = os.path.join(self.infra_dir, 'INTENT.md')
        self.assertTrue(os.path.exists(infra_intent))
        self.assertEqual(Path(infra_intent).read_text(), '# Intent\nDo the thing.')
        # Source must be GONE (move, not copy)
        self.assertFalse(
            os.path.exists(worktree_intent),
            'Source file must be removed after relocation (move, not copy)',
        )

    def test_plan_source_removed_after_relocation(self):
        """Move semantics apply to PLAN.md too."""
        worktree_plan = os.path.join(self.worktree, 'PLAN.md')
        Path(worktree_plan).write_text('# Plan\nStep 1.')

        stream = _make_stream(self.infra_dir, [('Write', worktree_plan)])

        result = _relocate_misplaced_artifact(self.infra_dir, stream, 'PLAN.md')

        self.assertTrue(result)
        self.assertTrue(os.path.exists(os.path.join(self.infra_dir, 'PLAN.md')))
        self.assertFalse(
            os.path.exists(worktree_plan),
            'PLAN.md source must be removed after relocation',
        )


# ── _commit_artifacts must NOT commit INTENT.md or PLAN.md ────────────────


class TestNoIntentCommitOnAssert(unittest.TestCase):
    """_commit_artifacts must not commit INTENT.md to the worktree.  Issue #148."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_intent_not_committed_on_assert(self):
        """INTENT.md must NOT appear in git history after INTENT_ASSERT transition."""
        cfa = make_initial_state(task_id='test')
        cfa = transition(cfa, 'propose')  # → PROPOSAL

        orch = _make_orchestrator(self.tmpdir, cfa_state=cfa)
        Path(orch.session_worktree, 'INTENT.md').write_text('# Intent\nDo a thing.\n')

        _run(orch._transition('assert', _make_actor_result(action='assert')))

        self.assertEqual(orch.cfa.state, 'INTENT_ASSERT')
        log = _git_log_oneline(orch.session_worktree, 'INTENT.md')
        self.assertEqual(
            len(log), 0,
            'INTENT.md must not be committed to the worktree (lives in infra_dir only)',
        )


class TestNoPlanCommitOnAssert(unittest.TestCase):
    """_commit_artifacts must not commit PLAN.md to the worktree.  Issue #148."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_plan_not_committed_on_assert(self):
        """PLAN.md must NOT appear in git history after PLAN_ASSERT transition."""
        cfa = make_initial_state(task_id='test')
        cfa = transition(cfa, 'propose')       # → PROPOSAL
        cfa = transition(cfa, 'auto-approve')   # → INTENT
        cfa = transition(cfa, 'plan')           # → DRAFT

        orch = _make_orchestrator(self.tmpdir, cfa_state=cfa)
        Path(orch.session_worktree, 'PLAN.md').write_text('# Plan\nStep 1.\n')

        _run(orch._transition('assert', _make_actor_result(action='assert')))

        self.assertEqual(orch.cfa.state, 'PLAN_ASSERT')
        log = _git_log_oneline(orch.session_worktree, 'PLAN.md')
        self.assertEqual(
            len(log), 0,
            'PLAN.md must not be committed to the worktree (lives in infra_dir only)',
        )


class TestTaskAssertStillCommitsDeliverables(unittest.TestCase):
    """TASK_ASSERT must still commit deliverables — only INTENT/PLAN are excluded."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_deliverables_still_committed(self):
        """Execution deliverables are committed at TASK_ASSERT as before."""
        cfa = make_initial_state(task_id='test')
        cfa = transition(cfa, 'propose')       # → PROPOSAL
        cfa = transition(cfa, 'auto-approve')   # → INTENT
        cfa = transition(cfa, 'plan')           # → DRAFT
        cfa = transition(cfa, 'auto-approve')   # → PLAN
        cfa = transition(cfa, 'delegate')       # → TASK
        cfa = transition(cfa, 'accept')         # → TASK_IN_PROGRESS

        orch = _make_orchestrator(self.tmpdir, cfa_state=cfa)
        Path(orch.session_worktree, 'output.py').write_text('print("hello")\n')

        _run(orch._transition('assert', _make_actor_result(action='assert')))

        self.assertEqual(orch.cfa.state, 'TASK_ASSERT')
        log = _git_log_oneline(orch.session_worktree)
        # init + execution commit = 2
        self.assertEqual(len(log), 2)
        self.assertIn('Execution: assert', log[0])


if __name__ == '__main__':
    unittest.main()
