#!/usr/bin/env python3
"""Failing tests (TDD) for issue #198: Integrate proxy learning with the
broader learning system.

The proxy and the learning system maintain separate memory stores with no
bidirectional feedback:
  - Proxy corrections stay in .proxy-confidence-*.json / proxy_memory.db
  - Task learnings stay in tasks/ markdown files
  - The proxy never sees task learnings; agents never see proxy corrections

These tests verify three integration points:

1. Proxy corrections → learning entries:
   When _proxy_record() records a correction, a structured YAML-frontmattered
   markdown entry is written to proxy-tasks/ in memory_entry.py format.

2. Learning entries → proxy retrieval context:
   When consult_proxy() gathers context, it retrieves relevant task learnings
   from the learning system's retrieve() function.

3. Unified storage format:
   Proxy-generated learning entries are stored as YAML-frontmattered markdown
   compatible with memory_entry.py, indexed by memory_indexer.py.
"""
import asyncio
import inspect
import json
import os
import sys
import tempfile
import shutil
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock, AsyncMock

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent.parent))


def _run(coro):
    return asyncio.run(coro)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_approval_gate(tmpdir, proxy_enabled=True, never_escalate=True):
    """Create an ApprovalGate with a temp model path."""
    from projects.POC.orchestrator.actors import ApprovalGate
    model_path = os.path.join(tmpdir, 'project', '.proxy-confidence.json')
    os.makedirs(os.path.dirname(model_path), exist_ok=True)
    Path(model_path).write_text('{}')
    return ApprovalGate(
        proxy_model_path=model_path,
        input_provider=AsyncMock(return_value='approve'),
        poc_root=tmpdir,
        proxy_enabled=proxy_enabled,
        never_escalate=never_escalate,
    )


def _make_actor_context(tmpdir, state='PLAN_ASSERT', task='test task'):
    """Create a minimal ActorContext for testing."""
    from projects.POC.orchestrator.actors import ActorContext
    from projects.POC.orchestrator.events import EventBus
    infra_dir = os.path.join(tmpdir, 'infra')
    worktree = os.path.join(tmpdir, 'worktree')
    os.makedirs(infra_dir, exist_ok=True)
    os.makedirs(worktree, exist_ok=True)
    return ActorContext(
        state=state,
        phase='planning',
        task=task,
        infra_dir=infra_dir,
        project_workdir=tmpdir,
        session_worktree=worktree,
        stream_file='.plan-stream.jsonl',
        phase_spec=MagicMock(
            artifact='PLAN.md',
            stream_file='.plan-stream.jsonl',
            settings_overlay={},
        ),
        poc_root=tmpdir,
        event_bus=EventBus(),
        session_id='test-session',
        env_vars={'POC_PROJECT': 'test', 'POC_TEAM': ''},
    )


# ── 1. Proxy corrections produce structured learning entries ────────────────

class TestProxyCorrectionEmitsLearningEntry(unittest.TestCase):
    """When the proxy records a correction, it must write a YAML-frontmattered
    markdown entry to proxy-tasks/ in the project directory."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_proxy_record_creates_proxy_tasks_entry_on_correction(self):
        """_proxy_record with outcome='correct' must create a file in proxy-tasks/."""
        gate = _make_approval_gate(self.tmpdir)
        project_dir = os.path.join(self.tmpdir, 'project')

        # Simulate a correction
        with patch('projects.POC.orchestrator.actors.load_model', return_value={}), \
             patch('projects.POC.orchestrator.actors.save_model'), \
             patch('projects.POC.orchestrator.actors.record_outcome', return_value={}), \
             patch('projects.POC.orchestrator.actors.resolve_team_model_path',
                   return_value=gate.proxy_model_path), \
             patch('projects.POC.orchestrator.actors._extract_question_patterns',
                   return_value=[]):
            gate._proxy_record(
                state='PLAN_ASSERT',
                project_slug='test',
                outcome='correct',
                artifact_path='',
                feedback='Missing rollback strategy',
                conversation='HUMAN: This plan needs a rollback strategy.',
                team='',
            )

        # Verify a learning entry was written to proxy-tasks/
        proxy_tasks_dir = os.path.join(project_dir, 'proxy-tasks')
        self.assertTrue(
            os.path.isdir(proxy_tasks_dir),
            "proxy-tasks/ directory must be created when a correction is recorded. "
            "_proxy_record() must emit structured learning entries on corrections."
        )
        md_files = [f for f in os.listdir(proxy_tasks_dir) if f.endswith('.md')]
        self.assertGreater(
            len(md_files), 0,
            "proxy-tasks/ must contain at least one .md file after a correction. "
            "_proxy_record() must write a YAML-frontmattered entry for each correction."
        )

    def test_proxy_correction_entry_has_valid_frontmatter(self):
        """The correction entry must have YAML frontmatter compatible with memory_entry.py."""
        gate = _make_approval_gate(self.tmpdir)
        project_dir = os.path.join(self.tmpdir, 'project')

        with patch('projects.POC.orchestrator.actors.load_model', return_value={}), \
             patch('projects.POC.orchestrator.actors.save_model'), \
             patch('projects.POC.orchestrator.actors.record_outcome', return_value={}), \
             patch('projects.POC.orchestrator.actors.resolve_team_model_path',
                   return_value=gate.proxy_model_path), \
             patch('projects.POC.orchestrator.actors._extract_question_patterns',
                   return_value=[]):
            gate._proxy_record(
                state='PLAN_ASSERT',
                project_slug='test',
                outcome='correct',
                feedback='Add error handling for edge cases',
                conversation='HUMAN: Add error handling.',
                team='',
            )

        proxy_tasks_dir = os.path.join(project_dir, 'proxy-tasks')
        if not os.path.isdir(proxy_tasks_dir):
            self.fail("proxy-tasks/ directory not created")

        md_files = [f for f in os.listdir(proxy_tasks_dir) if f.endswith('.md')]
        if not md_files:
            self.fail("No .md files in proxy-tasks/")

        from projects.POC.scripts.memory_entry import parse_memory_file
        content = Path(os.path.join(proxy_tasks_dir, md_files[0])).read_text()
        entries = parse_memory_file(content)
        self.assertGreater(
            len(entries), 0,
            "The correction file must parse into at least one MemoryEntry. "
            "Proxy correction entries must use the same YAML frontmatter format "
            "as other learning entries (memory_entry.py)."
        )
        entry = entries[0]
        self.assertEqual(entry.type, 'corrective',
                         "Proxy correction entries must have type='corrective'.")
        self.assertEqual(entry.status, 'active',
                         "New entries must have status='active'.")
        self.assertGreater(entry.importance, 0.5,
                           "Corrective learnings should have importance > 0.5.")

    def test_proxy_record_does_not_emit_entry_on_approve(self):
        """Approvals don't need learning entries — only corrections do."""
        gate = _make_approval_gate(self.tmpdir)
        project_dir = os.path.join(self.tmpdir, 'project')

        with patch('projects.POC.orchestrator.actors.load_model', return_value={}), \
             patch('projects.POC.orchestrator.actors.save_model'), \
             patch('projects.POC.orchestrator.actors.record_outcome', return_value={}), \
             patch('projects.POC.orchestrator.actors.resolve_team_model_path',
                   return_value=gate.proxy_model_path), \
             patch('projects.POC.orchestrator.actors._extract_question_patterns',
                   return_value=[]):
            gate._proxy_record(
                state='PLAN_ASSERT',
                project_slug='test',
                outcome='approve',
                team='',
            )

        proxy_tasks_dir = os.path.join(project_dir, 'proxy-tasks')
        if os.path.isdir(proxy_tasks_dir):
            md_files = [f for f in os.listdir(proxy_tasks_dir) if f.endswith('.md')]
            self.assertEqual(
                len(md_files), 0,
                "Approvals must NOT produce learning entries in proxy-tasks/. "
                "Only corrections carry actionable learning signal."
            )

    def test_correction_entry_includes_cfa_state_in_content(self):
        """The learning entry content must include the CfA state for retrieval context."""
        gate = _make_approval_gate(self.tmpdir)
        project_dir = os.path.join(self.tmpdir, 'project')

        with patch('projects.POC.orchestrator.actors.load_model', return_value={}), \
             patch('projects.POC.orchestrator.actors.save_model'), \
             patch('projects.POC.orchestrator.actors.record_outcome', return_value={}), \
             patch('projects.POC.orchestrator.actors.resolve_team_model_path',
                   return_value=gate.proxy_model_path), \
             patch('projects.POC.orchestrator.actors._extract_question_patterns',
                   return_value=[]):
            gate._proxy_record(
                state='PLAN_ASSERT',
                project_slug='test',
                outcome='correct',
                feedback='Missing rollback strategy',
                conversation='HUMAN: Where is the rollback plan?',
                team='',
            )

        proxy_tasks_dir = os.path.join(project_dir, 'proxy-tasks')
        if not os.path.isdir(proxy_tasks_dir):
            self.fail("proxy-tasks/ not created")

        md_files = [f for f in os.listdir(proxy_tasks_dir) if f.endswith('.md')]
        if not md_files:
            self.fail("No .md files in proxy-tasks/")

        content = Path(os.path.join(proxy_tasks_dir, md_files[0])).read_text()
        self.assertIn(
            'PLAN_ASSERT', content,
            "Entry content must include the CfA state (PLAN_ASSERT) so retrieval "
            "can match corrections to the relevant gate context."
        )
        self.assertIn(
            'rollback', content.lower(),
            "Entry content must include the correction feedback text."
        )


# ── 2. consult_proxy retrieves task learnings from the learning system ──────

class TestConsultProxyRetrievesTaskLearnings(unittest.TestCase):
    """consult_proxy() must retrieve relevant task learnings from the
    learning system, not just ACT-R memories and flat patterns."""

    def test_consult_proxy_calls_retrieve_for_task_learnings(self):
        """consult_proxy must retrieve task learnings from the learning system."""
        # consult_proxy delegates to _retrieve_task_learnings, which calls
        # memory_indexer.retrieve. Verify both the delegation and the
        # underlying retrieval path exist.
        from projects.POC.orchestrator.proxy_agent import consult_proxy
        source = inspect.getsource(consult_proxy)

        self.assertIn(
            '_retrieve_task_learnings', source,
            "consult_proxy() must call _retrieve_task_learnings() to get "
            "organizational task knowledge from memory_indexer.retrieve()."
        )

        # Verify the helper actually uses memory_indexer.retrieve with learning_type
        from projects.POC.orchestrator.proxy_agent import _retrieve_task_learnings
        helper_source = inspect.getsource(_retrieve_task_learnings)
        self.assertIn('memory_indexer', helper_source)
        self.assertIn('learning_type', helper_source)

    def test_consult_proxy_passes_task_context_to_retrieval(self):
        """The retrieval call must use the gate question as task context."""
        from projects.POC.orchestrator.proxy_agent import _retrieve_task_learnings
        source = inspect.getsource(_retrieve_task_learnings)

        # The retrieval must receive the question as the task parameter
        self.assertIn(
            'question', source,
            "_retrieve_task_learnings must use the gate question as retrieval context."
        )
        self.assertIn(
            'retrieve', source,
            "_retrieve_task_learnings must call memory_indexer.retrieve()."
        )


# ── 3. Proxy learning entries use proxy-tasks/ and are retrievable ──────────

class TestProxyLearningEntriesRetrievable(unittest.TestCase):
    """Proxy-generated learning entries must be stored in proxy-tasks/ with
    YAML frontmatter and be retrievable via memory_indexer.retrieve()."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_proxy_entry_classified_as_proxy_type(self):
        """Files in proxy-tasks/ must be classified as 'proxy' learning type."""
        from projects.POC.scripts.memory_indexer import classify_learning_type
        path = os.path.join(self.tmpdir, 'project', 'proxy-tasks', 'correction-001.md')
        self.assertEqual(
            classify_learning_type(path), 'proxy',
            "Proxy correction entries in proxy-tasks/ must be classified as "
            "'proxy' by classify_learning_type()."
        )

    def test_proxy_entry_indexable_by_memory_indexer(self):
        """Proxy correction entries must be indexable by memory_indexer."""
        from projects.POC.scripts.memory_indexer import open_db, index_file

        # Create a proxy correction entry
        entry_path = os.path.join(self.tmpdir, 'proxy-tasks', 'correction-001.md')
        os.makedirs(os.path.dirname(entry_path), exist_ok=True)
        Path(entry_path).write_text(
            "---\n"
            "id: test-correction-001\n"
            "type: corrective\n"
            "domain: task\n"
            "importance: 0.8\n"
            "phase: planning\n"
            "status: active\n"
            "reinforcement_count: 0\n"
            "last_reinforced: '2026-03-26'\n"
            "created_at: '2026-03-26'\n"
            "---\n"
            "## Proxy Correction at PLAN_ASSERT\n"
            "**Correction:** Plans for database migrations must include rollback strategies.\n"
            "**State:** PLAN_ASSERT\n"
            "**Project:** test\n"
        )

        db_path = os.path.join(self.tmpdir, '.memory.db')
        conn = open_db(db_path)
        try:
            index_file(conn, entry_path)
            count = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
            self.assertGreater(
                count, 0,
                "Proxy correction entries must be indexable into the memory DB. "
                "The entry uses standard YAML frontmatter and should chunk normally."
            )
        finally:
            conn.close()


# ── 4. CfA state → phase mapping ───────────────────────────────────────────

class TestCfaStateToPhaseMapping(unittest.TestCase):
    """Proxy correction entries need a phase field. CfA states must map to
    valid phases so retrieval filtering works correctly."""

    def test_state_to_phase_mapping_exists(self):
        """A mapping from CfA states to learning phases must exist in actors.py."""
        try:
            from projects.POC.orchestrator.actors import _CFA_STATE_TO_PHASE
        except ImportError:
            self.fail(
                "actors.py must export a _CFA_STATE_TO_PHASE mapping from "
                "CfA states (INTENT_ASSERT, PLAN_ASSERT, etc.) to memory entry "
                "phases (specification, planning, implementation)."
            )

        # Verify all approval gate states are mapped
        for state in ('INTENT_ASSERT', 'PLAN_ASSERT', 'TASK_ASSERT', 'WORK_ASSERT'):
            self.assertIn(
                state, _CFA_STATE_TO_PHASE,
                f"{state} must be mapped to a phase in _CFA_STATE_TO_PHASE."
            )

    def test_mapped_phases_are_meaningful(self):
        """Mapped phases must be non-empty strings."""
        from projects.POC.orchestrator.actors import _CFA_STATE_TO_PHASE
        for state, phase in _CFA_STATE_TO_PHASE.items():
            self.assertIsInstance(phase, str)
            self.assertTrue(
                len(phase) > 0,
                f"Phase for {state} must be a non-empty string."
            )


# ── 5. Learning retrieval context injected into proxy prompt ────────────────

class TestLearningContextInProxyPrompt(unittest.TestCase):
    """consult_proxy must inject retrieved task learnings into the proxy
    agent's prompt, alongside ACT-R memories and behavioral patterns."""

    def test_run_proxy_agent_accepts_task_learnings_parameter(self):
        """run_proxy_agent() must accept a task_learnings parameter."""
        from projects.POC.orchestrator.proxy_agent import run_proxy_agent
        sig = inspect.signature(run_proxy_agent)
        self.assertIn(
            'task_learnings', sig.parameters,
            "run_proxy_agent() must accept a 'task_learnings' parameter so "
            "retrieved task learnings can be injected into the proxy prompt."
        )


if __name__ == '__main__':
    unittest.main()
