"""Tests for Issue #244: Contradiction detection for task and institutional learnings.

Extends the proxy contradiction machinery (#228) to task-based and institutional
learnings. After learning extraction writes new entries, the system detects
contradictions with existing entries at the same scope, classifies by cause,
and resolves them.

Classification causes for task/institutional learnings differ from proxy:
- temporal_obsolescence: was true earlier, no longer applies (like preference_drift)
- scope_dependent: true at one scope level, false at another
- genuine_tension: unresolved real disagreement between learnings
- retrieval_noise: entries appear related but are about different things

Resolution:
- temporal_obsolescence -> DELETE older entry
- scope_dependent -> preserve both with scope annotation
- genuine_tension -> preserve both (flag for human review)
- retrieval_noise -> preserve both (no action needed)
"""
from __future__ import annotations

import os
import tempfile
import unittest

from projects.POC.scripts.memory_entry import MemoryEntry


def _make_entry(
    content: str = 'Test learning entry',
    entry_id: str = '',
    importance: float = 0.5,
    created_at: str = '2026-03-01',
    domain: str = 'task',
    type: str = 'procedural',
    phase: str = 'implementation',
    reinforcement_count: int = 0,
) -> MemoryEntry:
    """Create a MemoryEntry for testing learning consolidation."""
    import uuid
    return MemoryEntry(
        id=entry_id or str(uuid.uuid4()),
        type=type,
        domain=domain,
        importance=importance,
        phase=phase,
        status='active',
        reinforcement_count=reinforcement_count,
        last_reinforced=created_at,
        created_at=created_at,
        content=content,
    )


# ── Classification causes ────────────────────────────────────────────────────


class TestLearningConflictClassificationConstants(unittest.TestCase):
    """Classification cause constants must be importable."""

    def test_cause_constants_exist(self):
        from projects.POC.orchestrator.learning_consolidation import (
            CAUSE_TEMPORAL_OBSOLESCENCE,
            CAUSE_SCOPE_DEPENDENT,
            CAUSE_GENUINE_TENSION,
            CAUSE_RETRIEVAL_NOISE,
        )
        self.assertEqual(CAUSE_TEMPORAL_OBSOLESCENCE, 'temporal_obsolescence')
        self.assertEqual(CAUSE_SCOPE_DEPENDENT, 'scope_dependent')
        self.assertEqual(CAUSE_GENUINE_TENSION, 'genuine_tension')
        self.assertEqual(CAUSE_RETRIEVAL_NOISE, 'retrieval_noise')


# ── Finding conflicting entry pairs ──────────────────────────────────────────


class TestFindConflictingEntries(unittest.TestCase):
    """find_conflicting_entries() identifies candidate conflicts among MemoryEntry
    objects based on content similarity."""

    def test_function_exists_and_is_callable(self):
        from projects.POC.orchestrator.learning_consolidation import find_conflicting_entries
        self.assertTrue(callable(find_conflicting_entries))

    def test_unrelated_entries_no_conflict(self):
        """Entries about completely different topics produce no conflicts."""
        from projects.POC.orchestrator.learning_consolidation import find_conflicting_entries

        entries = [
            _make_entry('Always run tests before committing code changes'),
            _make_entry('Use vim keybindings for faster editing'),
            _make_entry('Database migrations need rollback plans'),
        ]
        pairs = find_conflicting_entries(entries)
        self.assertEqual(len(pairs), 0)

    def test_contradictory_entries_detected(self):
        """Entries about the same topic with opposing guidance are flagged."""
        from projects.POC.orchestrator.learning_consolidation import find_conflicting_entries

        entries = [
            _make_entry('Always run tests before committing code changes'),
            _make_entry('Skip tests for documentation-only changes before committing'),
        ]
        pairs = find_conflicting_entries(entries)
        self.assertGreaterEqual(len(pairs), 1)

    def test_empty_list_returns_empty(self):
        from projects.POC.orchestrator.learning_consolidation import find_conflicting_entries
        self.assertEqual(find_conflicting_entries([]), [])

    def test_single_entry_returns_empty(self):
        from projects.POC.orchestrator.learning_consolidation import find_conflicting_entries
        self.assertEqual(find_conflicting_entries([_make_entry()]), [])

    def test_entries_unchanged_after_detection(self):
        """Detection is read-only on the entry list."""
        from projects.POC.orchestrator.learning_consolidation import find_conflicting_entries

        entries = [
            _make_entry('Always run tests before committing', entry_id='a'),
            _make_entry('Skip tests for docs-only changes before committing', entry_id='b'),
        ]
        original_ids = [e.id for e in entries]
        original_content = [e.content for e in entries]

        find_conflicting_entries(entries)

        self.assertEqual([e.id for e in entries], original_ids)
        self.assertEqual([e.content for e in entries], original_content)


# ── Classifying conflicts ────────────────────────────────────────────────────


class TestClassifyLearningConflict(unittest.TestCase):
    """classify_learning_conflict() classifies a pair by cause."""

    def test_function_exists_and_is_callable(self):
        from projects.POC.orchestrator.learning_consolidation import classify_learning_conflict
        self.assertTrue(callable(classify_learning_conflict))

    def test_large_date_gap_is_temporal_obsolescence(self):
        """Entries with a large creation date gap on the same topic ->
        temporal_obsolescence (the older one may no longer apply)."""
        from projects.POC.orchestrator.learning_consolidation import classify_learning_conflict

        older = _make_entry(
            'Always run full test suite before merging',
            entry_id='old', created_at='2025-06-01',
        )
        newer = _make_entry(
            'Skip full test suite for documentation-only PRs before merging',
            entry_id='new', created_at='2026-03-15',
        )
        result = classify_learning_conflict(older, newer)
        self.assertEqual(result.cause, 'temporal_obsolescence')

    def test_same_date_high_reinforcement_is_genuine_tension(self):
        """Entries from similar timeframes, both well-reinforced ->
        genuine_tension (both have been validated by experience)."""
        from projects.POC.orchestrator.learning_consolidation import classify_learning_conflict

        a = _make_entry(
            'Parallelize test execution for faster CI feedback',
            entry_id='a', created_at='2026-03-10',
            reinforcement_count=5,
        )
        b = _make_entry(
            'Run tests sequentially to avoid shared-state flakiness',
            entry_id='b', created_at='2026-03-12',
            reinforcement_count=4,
        )
        result = classify_learning_conflict(a, b)
        self.assertEqual(result.cause, 'genuine_tension')

    def test_returns_valid_cause(self):
        """Classification must return one of the four valid causes."""
        from projects.POC.orchestrator.learning_consolidation import (
            classify_learning_conflict,
            VALID_CAUSES,
        )

        a = _make_entry('Always use type hints', entry_id='a')
        b = _make_entry('Skip type hints for quick scripts', entry_id='b')
        result = classify_learning_conflict(a, b)
        self.assertIn(result.cause, VALID_CAUSES)

    def test_ambiguous_defaults_to_genuine_tension(self):
        """When classification is ambiguous, default to genuine_tension
        (preserve both, flag for review) rather than silently deleting."""
        from projects.POC.orchestrator.learning_consolidation import classify_learning_conflict

        a = _make_entry(
            'Always validate input at API boundaries',
            entry_id='a', created_at='2026-03-10',
            reinforcement_count=1,
        )
        b = _make_entry(
            'Trust internal callers — skip validation between services',
            entry_id='b', created_at='2026-03-11',
            reinforcement_count=1,
        )
        result = classify_learning_conflict(a, b)
        # Should not be temporal_obsolescence (dates too close)
        # Default should preserve both
        self.assertIn(result.cause, {'genuine_tension', 'scope_dependent'})


# ── Classification result structure ──────────────────────────────────────────


class TestLearningConflictClassificationResult(unittest.TestCase):
    """The classification result carries structured data."""

    def test_result_has_cause_and_action(self):
        from projects.POC.orchestrator.learning_consolidation import classify_learning_conflict

        a = _make_entry('Always use linting', entry_id='a')
        b = _make_entry('Disable linting for generated code', entry_id='b')
        result = classify_learning_conflict(a, b)
        self.assertTrue(hasattr(result, 'cause'))
        self.assertTrue(hasattr(result, 'action'))
        self.assertIsInstance(result.cause, str)
        self.assertIsInstance(result.action, str)

    def test_result_has_entry_ids(self):
        from projects.POC.orchestrator.learning_consolidation import classify_learning_conflict

        a = _make_entry('Use linting', entry_id='entry-a')
        b = _make_entry('Disable linting', entry_id='entry-b')
        result = classify_learning_conflict(a, b)
        self.assertEqual(result.entry_a_id, 'entry-a')
        self.assertEqual(result.entry_b_id, 'entry-b')

    def test_temporal_obsolescence_recommends_prefer_newer(self):
        from projects.POC.orchestrator.learning_consolidation import classify_learning_conflict

        older = _make_entry('Old practice', entry_id='old', created_at='2025-01-01')
        newer = _make_entry('New practice replacing old', entry_id='new', created_at='2026-03-15')
        result = classify_learning_conflict(older, newer)
        if result.cause == 'temporal_obsolescence':
            self.assertIn('newer', result.action.lower())

    def test_genuine_tension_recommends_flag(self):
        from projects.POC.orchestrator.learning_consolidation import classify_learning_conflict

        a = _make_entry('Approach A', entry_id='a', created_at='2026-03-10',
                         reinforcement_count=5)
        b = _make_entry('Approach B', entry_id='b', created_at='2026-03-12',
                         reinforcement_count=5)
        result = classify_learning_conflict(a, b)
        if result.cause == 'genuine_tension':
            self.assertIn('flag', result.action.lower())


# ── Consolidation (resolution) ───────────────────────────────────────────────


class TestConsolidateLearningEntries(unittest.TestCase):
    """consolidate_learning_entries() applies resolution to a list of entries."""

    def test_function_exists_and_is_callable(self):
        from projects.POC.orchestrator.learning_consolidation import consolidate_learning_entries
        self.assertTrue(callable(consolidate_learning_entries))

    def test_non_conflicting_entries_unchanged(self):
        from projects.POC.orchestrator.learning_consolidation import consolidate_learning_entries

        entries = [
            _make_entry('Use git branches for features', entry_id='a'),
            _make_entry('Write docstrings for public APIs', entry_id='b'),
            _make_entry('Run linter before push', entry_id='c'),
        ]
        result, decisions = consolidate_learning_entries(entries)
        result_ids = {e.id for e in result}
        self.assertEqual(result_ids, {'a', 'b', 'c'})

    def test_temporal_obsolescence_removes_older(self):
        """When a pair is classified as temporal_obsolescence, the older
        entry is removed."""
        from projects.POC.orchestrator.learning_consolidation import consolidate_learning_entries

        older = _make_entry(
            'Always run full test suite before merging PRs',
            entry_id='old', created_at='2025-01-01',
        )
        newer = _make_entry(
            'Skip full test suite for documentation-only PRs before merging',
            entry_id='new', created_at='2026-03-15',
        )
        result, decisions = consolidate_learning_entries([older, newer])
        result_ids = {e.id for e in result}
        self.assertIn('new', result_ids)
        self.assertNotIn('old', result_ids)

    def test_genuine_tension_preserves_both(self):
        """Genuine tension preserves both entries."""
        from projects.POC.orchestrator.learning_consolidation import consolidate_learning_entries

        a = _make_entry(
            'Parallelize test execution for faster CI',
            entry_id='a', created_at='2026-03-10',
            reinforcement_count=5,
        )
        b = _make_entry(
            'Run tests sequentially to avoid flakiness',
            entry_id='b', created_at='2026-03-12',
            reinforcement_count=4,
        )
        result, decisions = consolidate_learning_entries([a, b])
        result_ids = {e.id for e in result}
        self.assertEqual(result_ids, {'a', 'b'})

    def test_genuine_tension_reduces_importance(self):
        """Entries in genuine tension get importance reduced so they decay
        faster at retrieval time (#218 interaction)."""
        from projects.POC.orchestrator.learning_consolidation import consolidate_learning_entries

        original_importance = 0.8
        a = _make_entry(
            'Always run tests before committing code changes to the repository',
            entry_id='a', created_at='2026-03-10',
            reinforcement_count=5, importance=original_importance,
        )
        b = _make_entry(
            'Skip tests before committing documentation-only code changes',
            entry_id='b', created_at='2026-03-12',
            reinforcement_count=4, importance=original_importance,
        )
        result, decisions = consolidate_learning_entries([a, b])
        for entry in result:
            self.assertLess(entry.importance, original_importance)

    def test_returns_decisions_for_auditability(self):
        from projects.POC.orchestrator.learning_consolidation import consolidate_learning_entries

        entries = [
            _make_entry('Always run tests before committing'),
            _make_entry('Skip tests for docs-only changes before committing'),
        ]
        result, decisions = consolidate_learning_entries(entries)
        self.assertIsInstance(decisions, list)

    def test_classifier_can_override_heuristic(self):
        """When an LLM classifier is provided, it overrides heuristic."""
        from projects.POC.orchestrator.learning_consolidation import (
            consolidate_learning_entries,
            CAUSE_TEMPORAL_OBSOLESCENCE,
        )

        a = _make_entry('Old approach', entry_id='old', created_at='2026-03-10')
        b = _make_entry('New approach', entry_id='new', created_at='2026-03-11')

        def mock_classifier(ea, eb):
            return CAUSE_TEMPORAL_OBSOLESCENCE

        result, decisions = consolidate_learning_entries(
            [a, b], classifier=mock_classifier,
        )
        result_ids = {e.id for e in result}
        self.assertIn('new', result_ids)
        self.assertNotIn('old', result_ids)


# ── File-level consolidation ─────────────────────────────────────────────────


class TestConsolidateLearningFile(unittest.TestCase):
    """consolidate_learning_file() operates on a directory of learning files."""

    def test_function_exists_and_is_callable(self):
        from projects.POC.orchestrator.learning_consolidation import consolidate_learning_file
        self.assertTrue(callable(consolidate_learning_file))

    def test_consolidates_task_directory(self):
        """Given a tasks/ directory with contradictory entries, consolidation
        removes the older one and writes an audit log."""
        from projects.POC.orchestrator.learning_consolidation import consolidate_learning_file
        from projects.POC.scripts.memory_entry import serialize_entry

        with tempfile.TemporaryDirectory() as tmpdir:
            tasks_dir = os.path.join(tmpdir, 'tasks')
            os.makedirs(tasks_dir)

            old_entry = _make_entry(
                'Always run full test suite before merging PRs',
                entry_id='old-entry', created_at='2025-01-01',
            )
            new_entry = _make_entry(
                'Skip full test suite for documentation-only PRs before merging',
                entry_id='new-entry', created_at='2026-03-15',
            )

            with open(os.path.join(tasks_dir, 'old-entry.md'), 'w') as f:
                f.write(serialize_entry(old_entry))
            with open(os.path.join(tasks_dir, 'new-entry.md'), 'w') as f:
                f.write(serialize_entry(new_entry))

            removed, log_entries = consolidate_learning_file(tasks_dir)
            self.assertEqual(removed, 1)
            # Old file removed, new file survives
            self.assertFalse(os.path.exists(os.path.join(tasks_dir, 'old-entry.md')))
            self.assertTrue(os.path.exists(os.path.join(tasks_dir, 'new-entry.md')))

    def test_empty_directory_no_op(self):
        from projects.POC.orchestrator.learning_consolidation import consolidate_learning_file

        with tempfile.TemporaryDirectory() as tmpdir:
            removed, log_entries = consolidate_learning_file(tmpdir)
            self.assertEqual(removed, 0)
            self.assertEqual(log_entries, [])

    def test_single_file_no_op(self):
        from projects.POC.orchestrator.learning_consolidation import consolidate_learning_file
        from projects.POC.scripts.memory_entry import serialize_entry

        with tempfile.TemporaryDirectory() as tmpdir:
            entry = _make_entry('Only one learning here', entry_id='solo')
            with open(os.path.join(tmpdir, 'solo.md'), 'w') as f:
                f.write(serialize_entry(entry))

            removed, log_entries = consolidate_learning_file(tmpdir)
            self.assertEqual(removed, 0)

    def test_multi_entry_file_preserves_surviving_entries(self):
        """If a file has multiple entries and only one is deleted, the
        other entries in that file must survive (not be lost by os.remove)."""
        from projects.POC.orchestrator.learning_consolidation import consolidate_learning_file
        from projects.POC.scripts.memory_entry import (
            serialize_memory_file, parse_memory_file,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            # One file with two entries: old contradicts separate new entry
            old_entry = _make_entry(
                'Always run full test suite before merging PRs',
                entry_id='old-multi', created_at='2025-01-01',
            )
            unrelated = _make_entry(
                'Use descriptive variable names for clarity',
                entry_id='unrelated', created_at='2025-06-01',
            )
            # Write both entries into one file
            multi_path = os.path.join(tmpdir, 'combined.md')
            with open(multi_path, 'w') as f:
                f.write(serialize_memory_file([old_entry, unrelated]))

            # Separate file with the contradicting newer entry
            new_entry = _make_entry(
                'Skip full test suite for documentation-only PRs before merging',
                entry_id='new-entry', created_at='2026-03-15',
            )
            with open(os.path.join(tmpdir, 'new-entry.md'), 'w') as f:
                from projects.POC.scripts.memory_entry import serialize_entry
                f.write(serialize_entry(new_entry))

            removed, decisions = consolidate_learning_file(tmpdir)

            # The unrelated entry must survive
            surviving_entries = []
            for fname in os.listdir(tmpdir):
                if fname.endswith('.md'):
                    with open(os.path.join(tmpdir, fname)) as f:
                        surviving_entries.extend(parse_memory_file(f.read()))
            surviving_ids = {e.id for e in surviving_entries}
            self.assertIn('unrelated', surviving_ids,
                          'Unrelated entry in multi-entry file must not be lost')
            self.assertIn('new-entry', surviving_ids)


# ── Institutional file consolidation ─────────────────────────────────────────


class TestConsolidateInstitutionalFile(unittest.TestCase):
    """consolidate_institutional_file() consolidates a multi-entry institutional.md."""

    def test_function_exists_and_is_callable(self):
        from projects.POC.orchestrator.learning_consolidation import consolidate_institutional_file
        self.assertTrue(callable(consolidate_institutional_file))

    def test_consolidates_contradictory_entries(self):
        """When institutional.md has contradictory entries, consolidation resolves them."""
        from projects.POC.orchestrator.learning_consolidation import consolidate_institutional_file
        from projects.POC.scripts.memory_entry import serialize_entry, serialize_memory_file

        with tempfile.TemporaryDirectory() as tmpdir:
            inst_path = os.path.join(tmpdir, 'institutional.md')

            old_entry = _make_entry(
                'All PRs require two approvals before merging',
                entry_id='old-inst', created_at='2025-01-01',
                domain='team', type='directive',
            )
            new_entry = _make_entry(
                'Documentation-only PRs require one approval before merging',
                entry_id='new-inst', created_at='2026-03-15',
                domain='team', type='directive',
            )

            with open(inst_path, 'w') as f:
                f.write(serialize_memory_file([old_entry, new_entry]))

            removed, log_entries = consolidate_institutional_file(inst_path)
            self.assertEqual(removed, 1)
            # File still exists (with surviving entry)
            self.assertTrue(os.path.exists(inst_path))
            # Verify only the newer entry survives
            from projects.POC.scripts.memory_entry import parse_memory_file
            with open(inst_path) as f:
                surviving = parse_memory_file(f.read())
            self.assertEqual(len(surviving), 1)
            self.assertEqual(surviving[0].id, 'new-inst')


# ── Idempotency: importance reduction must not compound ──────────────────────


class TestImportanceReductionIdempotency(unittest.TestCase):
    """Importance reduction must apply once, not compound across sessions."""

    def test_already_decayed_ids_skipped(self):
        """Entries in already_decayed_ids are not reduced again."""
        from projects.POC.orchestrator.learning_consolidation import consolidate_learning_entries

        a = _make_entry(
            'Always run tests before committing code changes to the repository',
            entry_id='a', created_at='2026-03-10',
            reinforcement_count=5, importance=0.56,  # already reduced from 0.8
        )
        b = _make_entry(
            'Skip tests before committing documentation-only code changes',
            entry_id='b', created_at='2026-03-12',
            reinforcement_count=4, importance=0.56,
        )
        result, decisions = consolidate_learning_entries(
            [a, b], already_decayed_ids={'a', 'b'},
        )
        # Importance should NOT be reduced further
        for entry in result:
            self.assertEqual(entry.importance, 0.56)

    def test_new_tension_pair_gets_decayed(self):
        """A tension pair not in already_decayed_ids DOES get reduced."""
        from projects.POC.orchestrator.learning_consolidation import consolidate_learning_entries

        a = _make_entry(
            'Always run tests before committing code changes to the repository',
            entry_id='a', created_at='2026-03-10',
            reinforcement_count=5, importance=0.8,
        )
        b = _make_entry(
            'Skip tests before committing documentation-only code changes',
            entry_id='b', created_at='2026-03-12',
            reinforcement_count=4, importance=0.8,
        )
        result, decisions = consolidate_learning_entries(
            [a, b], already_decayed_ids=set(),
        )
        for entry in result:
            self.assertLess(entry.importance, 0.8)


# ── Persistence: task file rewrite on importance change ──────────────────────


class TestTaskFilePersistence(unittest.TestCase):
    """consolidate_learning_file() must rewrite task files when importance changes."""

    def test_importance_persisted_to_disk(self):
        """After consolidation, surviving task files reflect reduced importance."""
        from projects.POC.orchestrator.learning_consolidation import consolidate_learning_file
        from projects.POC.scripts.memory_entry import serialize_entry, parse_memory_file

        with tempfile.TemporaryDirectory() as tmpdir:
            a = _make_entry(
                'Always run tests before committing code changes to the repository',
                entry_id='entry-a', created_at='2026-03-10',
                reinforcement_count=5, importance=0.8,
            )
            b = _make_entry(
                'Skip tests before committing documentation-only code changes',
                entry_id='entry-b', created_at='2026-03-12',
                reinforcement_count=4, importance=0.8,
            )

            path_a = os.path.join(tmpdir, 'entry-a.md')
            path_b = os.path.join(tmpdir, 'entry-b.md')
            with open(path_a, 'w') as f:
                f.write(serialize_entry(a))
            with open(path_b, 'w') as f:
                f.write(serialize_entry(b))

            consolidate_learning_file(tmpdir)

            # Re-read files from disk — importance should be reduced
            with open(path_a) as f:
                reread_a = parse_memory_file(f.read())
            with open(path_b) as f:
                reread_b = parse_memory_file(f.read())

            if reread_a:
                self.assertLess(reread_a[0].importance, 0.8)
            if reread_b:
                self.assertLess(reread_b[0].importance, 0.8)


# ── Pipeline wiring ──────────────────────────────────────────────────────────


class TestPipelineWiring(unittest.TestCase):
    """The consolidation step is wired into the learning extraction pipeline."""

    def test_consolidate_task_and_institutional_learnings_exists(self):
        """The pipeline helper function must be importable from learnings.py."""
        from projects.POC.orchestrator.learnings import _consolidate_task_and_institutional
        self.assertTrue(callable(_consolidate_task_and_institutional))


if __name__ == '__main__':
    unittest.main()
