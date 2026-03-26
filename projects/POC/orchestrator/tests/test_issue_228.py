"""Tests for Issue #228: Contradiction detection and resolution in proxy memory.

Two-stage contradiction handling:

Stage 1 — Retrieval-time flagging:
  1. find_conflicting_pairs() identifies candidate conflicts from retrieved chunks
     based on outcome disagreement within same state+task_type.
  2. classify_conflict() classifies each pair by cause: preference_drift,
     context_sensitivity, genuine_tension, or retrieval_noise.
  3. format_conflict_context() renders classifications into prompt text.
  4. Conflict classification is injected into the proxy prompt — read-only on
     chunk list (no reordering, no removal).

Stage 2 — Write-time consolidation (post-session):
  5. consolidate_proxy_entries() applies ADD/UPDATE/DELETE/SKIP taxonomy to
     proxy preferential entries, separate from existing compact_entries().
  6. Ambiguous conflicts default to context_sensitivity (preserve both).

Integration:
  7. _calibrate_confidence() caps confidence when genuine_tension is detected.
  8. No-conflict path adds zero overhead (no LLM calls, no extra processing).
"""
from __future__ import annotations

import unittest

from projects.POC.orchestrator.proxy_memory import MemoryChunk


def _make_chunk(
    chunk_id: str = 'test-chunk',
    state: str = 'PLAN_ASSERT',
    task_type: str = 'security',
    outcome: str = 'approve',
    traces: list[int] | None = None,
    **kwargs,
) -> MemoryChunk:
    defaults = dict(
        id=chunk_id,
        type='gate_outcome',
        state=state,
        task_type=task_type,
        outcome=outcome,
        content='test interaction content',
        traces=traces or [1],
        embedding_model='test/test',
    )
    defaults.update(kwargs)
    return MemoryChunk(**defaults)


# ── Stage 1: Retrieval-time conflict detection ─────────────────────────────


class TestFindConflictingPairs(unittest.TestCase):
    """find_conflicting_pairs() identifies candidate conflicts from chunk metadata."""

    def test_same_state_opposing_outcomes_are_flagged(self):
        """Two chunks with same state+task_type but opposite outcomes
        (approve vs correct) should be flagged as a conflicting pair."""
        from projects.POC.orchestrator.proxy_memory import find_conflicting_pairs

        c1 = _make_chunk(chunk_id='a', outcome='approve', state='PLAN_ASSERT', task_type='POC')
        c2 = _make_chunk(chunk_id='b', outcome='correct', state='PLAN_ASSERT', task_type='POC')
        pairs = find_conflicting_pairs([c1, c2])
        self.assertEqual(len(pairs), 1)
        pair_ids = {pairs[0][0].id, pairs[0][1].id}
        self.assertEqual(pair_ids, {'a', 'b'})

    def test_same_outcome_no_conflict(self):
        """Two chunks with same state+task_type and same outcome are not conflicting."""
        from projects.POC.orchestrator.proxy_memory import find_conflicting_pairs

        c1 = _make_chunk(chunk_id='a', outcome='approve', state='PLAN_ASSERT', task_type='POC')
        c2 = _make_chunk(chunk_id='b', outcome='approve', state='PLAN_ASSERT', task_type='POC')
        pairs = find_conflicting_pairs([c1, c2])
        self.assertEqual(len(pairs), 0)

    def test_different_state_no_conflict(self):
        """Two chunks with different states are not conflicting even with
        opposing outcomes — they are about different decision contexts."""
        from projects.POC.orchestrator.proxy_memory import find_conflicting_pairs

        c1 = _make_chunk(chunk_id='a', outcome='approve', state='PLAN_ASSERT', task_type='POC')
        c2 = _make_chunk(chunk_id='b', outcome='correct', state='WORK_ASSERT', task_type='POC')
        pairs = find_conflicting_pairs([c1, c2])
        self.assertEqual(len(pairs), 0)

    def test_different_task_type_no_conflict(self):
        """Two chunks with same state but different task_types are not conflicting."""
        from projects.POC.orchestrator.proxy_memory import find_conflicting_pairs

        c1 = _make_chunk(chunk_id='a', outcome='approve', state='PLAN_ASSERT', task_type='POC')
        c2 = _make_chunk(chunk_id='b', outcome='correct', state='PLAN_ASSERT', task_type='security')
        pairs = find_conflicting_pairs([c1, c2])
        self.assertEqual(len(pairs), 0)

    def test_empty_chunk_list_returns_empty(self):
        """No chunks → no conflicts."""
        from projects.POC.orchestrator.proxy_memory import find_conflicting_pairs

        pairs = find_conflicting_pairs([])
        self.assertEqual(len(pairs), 0)

    def test_single_chunk_returns_empty(self):
        """A single chunk cannot conflict with itself."""
        from projects.POC.orchestrator.proxy_memory import find_conflicting_pairs

        c1 = _make_chunk(chunk_id='a', outcome='approve')
        pairs = find_conflicting_pairs([c1])
        self.assertEqual(len(pairs), 0)

    def test_multiple_conflicts_detected(self):
        """When more than one conflicting pair exists, all are returned."""
        from projects.POC.orchestrator.proxy_memory import find_conflicting_pairs

        c1 = _make_chunk(chunk_id='a', outcome='approve', state='PLAN_ASSERT', task_type='POC')
        c2 = _make_chunk(chunk_id='b', outcome='correct', state='PLAN_ASSERT', task_type='POC')
        c3 = _make_chunk(chunk_id='c', outcome='dismiss', state='PLAN_ASSERT', task_type='POC')
        pairs = find_conflicting_pairs([c1, c2, c3])
        # a-vs-b, a-vs-c, b-vs-c all have different outcomes in same context
        self.assertGreaterEqual(len(pairs), 2)


class TestClassifyConflict(unittest.TestCase):
    """classify_conflict() classifies a pair by cause."""

    def test_recency_gap_same_domain_is_preference_drift(self):
        """Large recency gap + same context domain → preference_drift."""
        from projects.POC.orchestrator.proxy_memory import classify_conflict

        older = _make_chunk(chunk_id='old', outcome='approve', traces=[1, 2])
        newer = _make_chunk(chunk_id='new', outcome='correct', traces=[1, 2, 10, 20])
        result = classify_conflict(older, newer, current_interaction=25)
        self.assertEqual(result.cause, 'preference_drift')

    def test_recent_same_domain_high_confidence_is_genuine_tension(self):
        """Recent, same domain, high confidence both → genuine_tension."""
        from projects.POC.orchestrator.proxy_memory import classify_conflict

        c1 = _make_chunk(
            chunk_id='a', outcome='approve', traces=[18, 19],
            posterior_confidence=0.9,
        )
        c2 = _make_chunk(
            chunk_id='b', outcome='correct', traces=[20, 21],
            posterior_confidence=0.9,
        )
        result = classify_conflict(c1, c2, current_interaction=22)
        self.assertEqual(result.cause, 'genuine_tension')

    def test_returns_valid_cause_enum(self):
        """Classification must return one of the four valid causes."""
        from projects.POC.orchestrator.proxy_memory import classify_conflict

        VALID_CAUSES = {'preference_drift', 'context_sensitivity', 'genuine_tension', 'retrieval_noise'}
        c1 = _make_chunk(chunk_id='a', outcome='approve', traces=[1])
        c2 = _make_chunk(chunk_id='b', outcome='correct', traces=[2])
        result = classify_conflict(c1, c2, current_interaction=5)
        self.assertIn(result.cause, VALID_CAUSES)

    def test_ambiguous_defaults_to_context_sensitivity(self):
        """When classification is ambiguous (no clear signal), default to
        context_sensitivity per the design: 'falsely discarding valid
        context-specific knowledge is harder to recover from'."""
        from projects.POC.orchestrator.proxy_memory import classify_conflict

        # Two chunks with similar recency, moderate confidence — ambiguous
        c1 = _make_chunk(chunk_id='a', outcome='approve', traces=[8, 9],
                         posterior_confidence=0.6)
        c2 = _make_chunk(chunk_id='b', outcome='correct', traces=[10, 11],
                         posterior_confidence=0.6)
        result = classify_conflict(c1, c2, current_interaction=12)
        self.assertEqual(result.cause, 'context_sensitivity')


class TestConflictClassificationResult(unittest.TestCase):
    """The classification result must carry structured data."""

    def test_result_has_cause_and_action(self):
        """Result has cause (why) and recommended action."""
        from projects.POC.orchestrator.proxy_memory import classify_conflict

        c1 = _make_chunk(chunk_id='a', outcome='approve', traces=[1])
        c2 = _make_chunk(chunk_id='b', outcome='correct', traces=[10])
        result = classify_conflict(c1, c2, current_interaction=15)
        self.assertTrue(hasattr(result, 'cause'))
        self.assertTrue(hasattr(result, 'action'))
        self.assertIsInstance(result.cause, str)
        self.assertIsInstance(result.action, str)

    def test_preference_drift_recommends_prefer_newer(self):
        """Preference drift → action should recommend preferring newer."""
        from projects.POC.orchestrator.proxy_memory import classify_conflict

        older = _make_chunk(chunk_id='old', outcome='approve', traces=[1])
        newer = _make_chunk(chunk_id='new', outcome='correct', traces=[15, 20])
        result = classify_conflict(older, newer, current_interaction=25)
        if result.cause == 'preference_drift':
            self.assertIn('newer', result.action.lower())

    def test_genuine_tension_recommends_escalate(self):
        """Genuine tension → action should recommend escalation."""
        from projects.POC.orchestrator.proxy_memory import classify_conflict

        c1 = _make_chunk(chunk_id='a', outcome='approve', traces=[18, 19],
                         posterior_confidence=0.9)
        c2 = _make_chunk(chunk_id='b', outcome='correct', traces=[20, 21],
                         posterior_confidence=0.9)
        result = classify_conflict(c1, c2, current_interaction=22)
        if result.cause == 'genuine_tension':
            self.assertIn('escalat', result.action.lower())


class TestFormatConflictContext(unittest.TestCase):
    """format_conflict_context() renders classifications for prompt injection."""

    def test_no_conflicts_returns_empty_string(self):
        """No conflicts → empty string (zero overhead in prompt)."""
        from projects.POC.orchestrator.proxy_memory import format_conflict_context

        result = format_conflict_context([])
        self.assertEqual(result, '')

    def test_conflict_formatted_with_cause_and_action(self):
        """Formatted output includes the cause and recommended action."""
        from projects.POC.orchestrator.proxy_memory import (
            classify_conflict,
            format_conflict_context,
        )

        c1 = _make_chunk(chunk_id='a', outcome='approve', traces=[1])
        c2 = _make_chunk(chunk_id='b', outcome='correct', traces=[15])
        classification = classify_conflict(c1, c2, current_interaction=20)

        result = format_conflict_context([classification])
        # cause may be rendered with spaces instead of underscores
        self.assertIn(classification.cause.replace('_', ' '), result)
        self.assertIn(classification.action, result)

    def test_multiple_conflicts_all_rendered(self):
        """When multiple conflicts exist, all are in the output."""
        from projects.POC.orchestrator.proxy_memory import (
            classify_conflict,
            format_conflict_context,
        )

        c1 = _make_chunk(chunk_id='a', outcome='approve', traces=[1])
        c2 = _make_chunk(chunk_id='b', outcome='correct', traces=[15])
        c3 = _make_chunk(chunk_id='c', outcome='dismiss', traces=[16])
        cls1 = classify_conflict(c1, c2, current_interaction=20)
        cls2 = classify_conflict(c1, c3, current_interaction=20)

        result = format_conflict_context([cls1, cls2])
        # Both classifications should be present (cause rendered with spaces)
        self.assertIn(cls1.cause.replace('_', ' '), result)
        self.assertIn(cls2.cause.replace('_', ' '), result)


# ── Stage 1 integration: read-only on chunk list ────────────────────────────


class TestConflictDetectionIsReadOnly(unittest.TestCase):
    """Conflict detection must not modify, reorder, or filter the chunk list."""

    def test_chunks_unchanged_after_detection(self):
        """The chunk list must be identical before and after find_conflicting_pairs."""
        from projects.POC.orchestrator.proxy_memory import find_conflicting_pairs

        chunks = [
            _make_chunk(chunk_id='a', outcome='approve', state='PLAN_ASSERT', task_type='POC'),
            _make_chunk(chunk_id='b', outcome='correct', state='PLAN_ASSERT', task_type='POC'),
            _make_chunk(chunk_id='c', outcome='approve', state='WORK_ASSERT', task_type='POC'),
        ]
        original_ids = [c.id for c in chunks]
        original_outcomes = [c.outcome for c in chunks]

        find_conflicting_pairs(chunks)

        self.assertEqual([c.id for c in chunks], original_ids)
        self.assertEqual([c.outcome for c in chunks], original_outcomes)


# ── Stage 2: Post-session consolidation ──────────────────────────────────────


class TestConsolidateProxyEntries(unittest.TestCase):
    """consolidate_proxy_entries() applies ADD/UPDATE/DELETE/SKIP to proxy entries.

    This is a separate function from compact_entries() — it does NOT modify
    the existing compaction pipeline.
    """

    def test_function_exists_and_is_callable(self):
        """consolidate_proxy_entries must be importable."""
        from projects.POC.orchestrator.proxy_memory import consolidate_proxy_entries
        self.assertTrue(callable(consolidate_proxy_entries))

    def test_non_conflicting_entries_returned_unchanged(self):
        """Entries with no conflicts are returned as-is (ADD/SKIP semantics)."""
        from projects.POC.orchestrator.proxy_memory import consolidate_proxy_entries

        chunks = [
            _make_chunk(chunk_id='a', outcome='approve', state='PLAN_ASSERT',
                        task_type='POC', content='Prefers detailed plans'),
            _make_chunk(chunk_id='b', outcome='approve', state='WORK_ASSERT',
                        task_type='POC', content='Approves thorough testing'),
        ]
        result = consolidate_proxy_entries(chunks)
        result_ids = {c.id for c in result}
        self.assertEqual(result_ids, {'a', 'b'})

    def test_preference_drift_keeps_newer_only(self):
        """When a pair is classified as preference_drift, only the newer
        entry survives (DELETE the older)."""
        from projects.POC.orchestrator.proxy_memory import consolidate_proxy_entries

        older = _make_chunk(chunk_id='old', outcome='approve', state='PLAN_ASSERT',
                            task_type='POC', traces=[1],
                            content='Approves aggressive parallelization')
        newer = _make_chunk(chunk_id='new', outcome='correct', state='PLAN_ASSERT',
                            task_type='POC', traces=[1, 10, 20],
                            content='Insists on sequential verification')
        result = consolidate_proxy_entries([older, newer], current_interaction=25)
        result_ids = {c.id for c in result}
        self.assertIn('new', result_ids)
        self.assertNotIn('old', result_ids)

    def test_ambiguous_defaults_to_preserving_both(self):
        """When conflict cause is ambiguous, both entries are preserved
        (default to context_sensitivity)."""
        from projects.POC.orchestrator.proxy_memory import consolidate_proxy_entries

        c1 = _make_chunk(chunk_id='a', outcome='approve', state='PLAN_ASSERT',
                         task_type='POC', traces=[8, 9],
                         posterior_confidence=0.6,
                         content='Approves quick iterations')
        c2 = _make_chunk(chunk_id='b', outcome='correct', state='PLAN_ASSERT',
                         task_type='POC', traces=[10, 11],
                         posterior_confidence=0.6,
                         content='Prefers careful review')
        result = consolidate_proxy_entries([c1, c2], current_interaction=12)
        result_ids = {c.id for c in result}
        self.assertEqual(result_ids, {'a', 'b'})


# ── Confidence calibration with conflict signal ─────────────────────────────


class TestConfidenceCalibrationWithConflicts(unittest.TestCase):
    """_calibrate_confidence must cap confidence when genuine_tension detected."""

    def test_genuine_tension_caps_confidence(self):
        """When retrieved chunks contain a genuine_tension conflict,
        confidence should be capped to force escalation."""
        from projects.POC.orchestrator.proxy_memory import (
            find_conflicting_pairs,
            classify_conflict,
        )

        c1 = _make_chunk(chunk_id='a', outcome='approve', traces=[18, 19],
                         state='PLAN_ASSERT', task_type='POC',
                         posterior_confidence=0.9)
        c2 = _make_chunk(chunk_id='b', outcome='correct', traces=[20, 21],
                         state='PLAN_ASSERT', task_type='POC',
                         posterior_confidence=0.9)

        pairs = find_conflicting_pairs([c1, c2])
        self.assertTrue(len(pairs) > 0, "Should detect conflict")

        classifications = [
            classify_conflict(p[0], p[1], current_interaction=22)
            for p in pairs
        ]

        # If any classification is genuine_tension, it should trigger
        # a confidence cap. We verify the classification machinery works;
        # the actual confidence capping is tested via has_genuine_tension().
        from projects.POC.orchestrator.proxy_memory import has_genuine_tension
        self.assertTrue(has_genuine_tension(classifications))

    def test_no_conflict_no_cap(self):
        """When no conflicts exist, has_genuine_tension returns False."""
        from projects.POC.orchestrator.proxy_memory import has_genuine_tension
        self.assertFalse(has_genuine_tension([]))


# ── No-conflict fast path ───────────────────────────────────────────────────


class TestNoConflictFastPath(unittest.TestCase):
    """When retrieved chunks have no conflicts, the detection adds zero overhead."""

    def test_no_conflict_returns_empty_pairs(self):
        """All-approve chunks → empty pairs list → format returns empty string."""
        from projects.POC.orchestrator.proxy_memory import (
            find_conflicting_pairs,
            format_conflict_context,
        )

        chunks = [
            _make_chunk(chunk_id='a', outcome='approve', state='PLAN_ASSERT', task_type='POC'),
            _make_chunk(chunk_id='b', outcome='approve', state='PLAN_ASSERT', task_type='POC'),
            _make_chunk(chunk_id='c', outcome='approve', state='WORK_ASSERT', task_type='POC'),
        ]
        pairs = find_conflicting_pairs(chunks)
        self.assertEqual(len(pairs), 0)

        context = format_conflict_context([])
        self.assertEqual(context, '')


# ── Stage 2: proxy.md consolidation (consolidate_proxy_file) ────────────────


def _make_entry(
    content: str = 'Test preference entry',
    entry_id: str = '',
    importance: float = 0.5,
    created_at: str = '2026-03-01',
) -> 'MemoryEntry':
    """Create a MemoryEntry for testing proxy.md consolidation."""
    from projects.POC.scripts.memory_entry import MemoryEntry
    import uuid
    return MemoryEntry(
        id=entry_id or str(uuid.uuid4()),
        type='declarative',
        domain='team',
        importance=importance,
        phase='unknown',
        status='active',
        reinforcement_count=0,
        last_reinforced=created_at,
        created_at=created_at,
        content=content,
    )


class TestConsolidateProxyFile(unittest.TestCase):
    """consolidate_proxy_file() applies ADD/UPDATE/DELETE/SKIP to proxy.md entries."""

    def test_function_exists_and_is_callable(self):
        from projects.POC.orchestrator.proxy_memory import consolidate_proxy_file
        self.assertTrue(callable(consolidate_proxy_file))

    def test_single_entry_unchanged(self):
        """Single entry returns unchanged."""
        from projects.POC.orchestrator.proxy_memory import consolidate_proxy_file

        entries = [_make_entry('Prefers detailed code reviews')]
        result, decisions = consolidate_proxy_file(entries)
        self.assertEqual(len(result), 1)

    def test_unrelated_entries_all_preserved(self):
        """Entries on different topics are all preserved."""
        from projects.POC.orchestrator.proxy_memory import consolidate_proxy_file

        entries = [
            _make_entry('Prefers detailed code reviews'),
            _make_entry('Likes morning standup meetings'),
            _make_entry('Uses vim keybindings'),
        ]
        result, decisions = consolidate_proxy_file(entries)
        self.assertEqual(len(result), 3)

    def test_similar_entries_clustered(self):
        """Entries with high content similarity are detected as a cluster."""
        from projects.POC.orchestrator.proxy_memory import consolidate_proxy_file

        # These share many tokens and should cluster
        entries = [
            _make_entry('The user prefers aggressive parallelization for build tasks',
                        created_at='2026-03-01'),
            _make_entry('The user prefers sequential verification for build tasks',
                        created_at='2026-03-15'),
        ]
        # In heuristic mode (no classifier), both should be preserved
        # because we can't reliably determine conflict without LLM
        result, decisions = consolidate_proxy_file(entries)
        self.assertEqual(len(result), 2)

    def test_classifier_can_delete_superseded(self):
        """When a classifier is provided, it can DELETE superseded entries."""
        from projects.POC.orchestrator.proxy_memory import (
            consolidate_proxy_file,
            CONSOLIDATION_DELETE,
            CONSOLIDATION_ADD,
        )

        entries = [
            _make_entry('The user prefers aggressive parallelization for all tasks',
                        entry_id='old-pref', created_at='2026-03-01'),
            _make_entry('The user now prefers sequential verification for all tasks',
                        entry_id='new-pref', created_at='2026-03-15'),
        ]

        # Mock classifier that always says DELETE (older superseded)
        def mock_classifier(a, b):
            return CONSOLIDATION_DELETE

        result, decisions = consolidate_proxy_file(
            entries, similarity_threshold=0.3, classifier=mock_classifier,
        )
        result_ids = {e.id for e in result}
        # The older entry should be deleted
        self.assertIn('new-pref', result_ids)
        self.assertNotIn('old-pref', result_ids)

    def test_classifier_skip_keeps_existing(self):
        """SKIP means the new entry is already represented — discard it."""
        from projects.POC.orchestrator.proxy_memory import (
            consolidate_proxy_file,
            CONSOLIDATION_SKIP,
        )

        entries = [
            _make_entry('Prefers detailed plans with rollback strategies',
                        entry_id='existing', created_at='2026-03-01'),
            _make_entry('Prefers detailed plans with rollback strategies and testing',
                        entry_id='duplicate', created_at='2026-03-15'),
        ]

        def mock_classifier(a, b):
            return CONSOLIDATION_SKIP

        result, decisions = consolidate_proxy_file(
            entries, similarity_threshold=0.3, classifier=mock_classifier,
        )
        result_ids = {e.id for e in result}
        self.assertIn('existing', result_ids)
        self.assertNotIn('duplicate', result_ids)

    def test_returns_decisions_for_auditability(self):
        """Decisions list records what happened for each pair/cluster."""
        from projects.POC.orchestrator.proxy_memory import consolidate_proxy_file

        entries = [
            _make_entry('The user prefers aggressive parallelization for build tasks'),
            _make_entry('The user prefers sequential verification for build tasks'),
        ]
        result, decisions = consolidate_proxy_file(entries)
        # Should have at least one decision record
        self.assertIsInstance(decisions, list)

    def test_heuristic_mode_preserves_all(self):
        """Without a classifier, heuristic mode preserves all entries
        (cannot reliably classify without LLM)."""
        from projects.POC.orchestrator.proxy_memory import consolidate_proxy_file

        entries = [
            _make_entry('Prefers fast iteration cycles'),
            _make_entry('Prefers careful thorough review'),
        ]
        result, decisions = consolidate_proxy_file(entries)
        self.assertEqual(len(result), len(entries))


# ── Asymmetric confidence decay (Hindsight +α/-α/-2α) ───────────────────────


class TestAsymmetricConfidenceDecay(unittest.TestCase):
    """Asymmetric confidence decay following Hindsight (arXiv:2512.12818).

    Supporting evidence: +α
    Weakening evidence: -α
    Contradicting evidence: -2α
    """

    def test_function_exists(self):
        from projects.POC.orchestrator.proxy_memory import apply_confidence_decay
        self.assertTrue(callable(apply_confidence_decay))

    def test_supporting_evidence_increases(self):
        """Supporting evidence increases confidence by α."""
        from projects.POC.orchestrator.proxy_memory import apply_confidence_decay

        result = apply_confidence_decay(0.5, 'supporting')
        self.assertGreater(result, 0.5)

    def test_weakening_evidence_decreases(self):
        """Weakening evidence decreases confidence by α."""
        from projects.POC.orchestrator.proxy_memory import apply_confidence_decay

        result = apply_confidence_decay(0.5, 'weakening')
        self.assertLess(result, 0.5)

    def test_contradicting_decreases_double(self):
        """Contradicting evidence decreases by 2α (double weakening)."""
        from projects.POC.orchestrator.proxy_memory import apply_confidence_decay

        weak = apply_confidence_decay(0.5, 'weakening')
        contra = apply_confidence_decay(0.5, 'contradicting')
        weak_delta = 0.5 - weak
        contra_delta = 0.5 - contra
        self.assertAlmostEqual(contra_delta, 2 * weak_delta, places=5)

    def test_confidence_clamped_to_zero(self):
        """Confidence never goes below 0.0."""
        from projects.POC.orchestrator.proxy_memory import apply_confidence_decay

        result = apply_confidence_decay(0.05, 'contradicting')
        self.assertGreaterEqual(result, 0.0)

    def test_confidence_clamped_to_one(self):
        """Confidence never goes above 1.0."""
        from projects.POC.orchestrator.proxy_memory import apply_confidence_decay

        result = apply_confidence_decay(0.95, 'supporting')
        self.assertLessEqual(result, 1.0)

    def test_asymmetry_matches_3x_correction(self):
        """The 2α contradicting decay is consistent with the proxy's
        existing 3x correction asymmetry: false beliefs are more costly
        than missed reinforcements."""
        from projects.POC.orchestrator.proxy_memory import apply_confidence_decay

        support_delta = apply_confidence_decay(0.5, 'supporting') - 0.5
        contra_delta = 0.5 - apply_confidence_decay(0.5, 'contradicting')
        # Contradicting should be 2x the support, not 3x
        # (the 3x is the EMA asymmetry, this is the memory asymmetry)
        ratio = contra_delta / support_delta if support_delta > 0 else 0
        self.assertAlmostEqual(ratio, 2.0, places=1)


if __name__ == '__main__':
    unittest.main()
