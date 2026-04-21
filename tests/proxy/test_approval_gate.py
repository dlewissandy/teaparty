#!/usr/bin/env python3
"""Tests for approval_gate.py — confidence-based CfA approval gate.

Covers:
 1. Cold start — always escalate when < 5 samples
 2. High confidence binary — auto-approve after many approvals
 3. Low confidence — escalate when correction/rejection rate is high
 4. Generative states — higher threshold applies
 5. Record outcome — counters update correctly
 6. Bayesian smoothing — confidence converges to actual rate
 7. Persistence round-trip — save and load model
 8. Mixed task types — different confidence per task type at same state
 9. Full learning loop: 10 approvals → auto-approve; then 3 corrections → escalate
"""
import json
import os
import shutil
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from teaparty.proxy.approval_gate import (
    COLD_START_THRESHOLD,
    EXPLORE_RATE,
    STALENESS_DAYS,
    BINARY_STATES,
    GENERATIVE_STATES,
    ConfidenceEntry,
    ConfidenceModel,
    ProxyDecision,
    compute_confidence,
    is_generative_state,
    load_model,
    make_model,
    record_outcome,
    save_model,
    should_escalate,
    _check_content,
    _extract_question_patterns,
    ARTIFACT_LENGTH_RATIO_LOW,
    ARTIFACT_LENGTH_RATIO_HIGH,
    QUESTION_PATTERN_MIN_OCCURRENCES,
    PRINCIPLE_VIOLATION_THRESHOLD,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_model(
    global_threshold: float = 0.8,
    generative_threshold: float = 0.95,
) -> ConfidenceModel:
    """Return a fresh empty ConfidenceModel."""
    return make_model(
        global_threshold=global_threshold,
        generative_threshold=generative_threshold,
    )


def _make_entry(
    state: str = 'PLAN_ASSERT',
    task_type: str = 'test-project',
    approve_count: int = 0,
    correct_count: int = 0,
    reject_count: int = 0,
    total_count: int = 0,
    last_updated: str = '',
    ema_approval_rate: float = None,
) -> ConfidenceEntry:
    """Return a ConfidenceEntry with specified counts.

    When ema_approval_rate is not specified, it is bootstrapped from the
    Laplace rate — mirroring the backward-compat logic in production code
    for old entries that predate the EMA field.
    """
    if ema_approval_rate is None:
        if total_count > 0:
            ema_approval_rate = (approve_count + 1) / (total_count + 2)
        else:
            ema_approval_rate = 0.5
    return ConfidenceEntry(
        state=state,
        task_type=task_type,
        approve_count=approve_count,
        correct_count=correct_count,
        reject_count=reject_count,
        total_count=total_count,
        last_updated=last_updated or date.today().isoformat(),
        ema_approval_rate=ema_approval_rate,
    )


def _model_with_entry(entry: ConfidenceEntry, **model_kwargs) -> ConfidenceModel:
    """Build a ConfidenceModel with a single pre-loaded entry."""
    from dataclasses import asdict
    model = _make_model(**model_kwargs)
    key = f"{entry.state}|{entry.task_type}"
    entries = {key: asdict(entry)}
    return ConfidenceModel(
        entries=entries,
        global_threshold=model.global_threshold,
        generative_threshold=model.generative_threshold,
    )


def _record_n(model: ConfidenceModel, state: str, task_type: str, outcome: str, n: int) -> ConfidenceModel:
    """Record the same outcome n times."""
    for _ in range(n):
        model = record_outcome(model, state, task_type, outcome)
    return model


# All existing tests use DeterministicProxyTestCase which disables random
# exploration so that auto-approve decisions are deterministic.
# Exploration-specific tests at the bottom use unittest.TestCase directly.

class DeterministicProxyTestCase(unittest.TestCase):
    """Base class that disables random exploration for deterministic tests."""

    def setUp(self):
        self._explore_patcher = patch('teaparty.proxy.approval_gate.random.random', return_value=1.0)
        self._explore_patcher.start()

    def tearDown(self):
        self._explore_patcher.stop()


# ── 1. Cold start ─────────────────────────────────────────────────────────────

class TestColdStart(DeterministicProxyTestCase):

    def test_new_state_always_escalates(self):
        """With no observations at all the proxy must escalate."""
        model = _make_model()
        decision = should_escalate(model, 'PLAN_ASSERT', 'new-project')
        self.assertEqual(decision.action, 'escalate')

    def test_fewer_than_threshold_samples_always_escalates(self):
        """With fewer than COLD_START_THRESHOLD samples the proxy must escalate."""
        model = _make_model()
        for i in range(COLD_START_THRESHOLD - 1):
            model = record_outcome(model, 'PLAN_ASSERT', 'my-project', 'approve')

        decision = should_escalate(model, 'PLAN_ASSERT', 'my-project')
        self.assertEqual(decision.action, 'escalate')
        self.assertIn('Cold start', decision.reasoning)

    def test_exactly_threshold_samples_no_longer_cold_start(self):
        """At exactly COLD_START_THRESHOLD approvals cold-start no longer applies."""
        model = _make_model()
        model = _record_n(model, 'PLAN_ASSERT', 'my-project', 'approve', COLD_START_THRESHOLD)

        decision = should_escalate(model, 'PLAN_ASSERT', 'my-project')
        # All approvals — should auto-approve (confidence is high)
        self.assertEqual(decision.action, 'auto-approve')

    def test_cold_start_confidence_is_zero(self):
        """Cold-start decisions always report confidence 0.0."""
        model = _make_model()
        decision = should_escalate(model, 'WORK_ASSERT', 'any-project')
        self.assertEqual(decision.confidence, 0.0)


# ── 2. High confidence binary — auto-approve ──────────────────────────────────

class TestHighConfidenceBinary(DeterministicProxyTestCase):

    def test_all_approvals_auto_approves(self):
        """10 approvals with 0 corrections → auto-approve at binary threshold."""
        entry = _make_entry(
            state='PLAN_ASSERT',
            task_type='steady-project',
            approve_count=10,
            total_count=10,
        )
        model = _model_with_entry(entry)
        decision = should_escalate(model, 'PLAN_ASSERT', 'steady-project')
        self.assertEqual(decision.action, 'auto-approve')
        self.assertGreater(decision.confidence, 0.8)

    def test_decision_fields_populated(self):
        """A successful auto-approve decision has all ProxyDecision fields set."""
        entry = _make_entry(approve_count=20, total_count=20)
        model = _model_with_entry(entry)
        decision = should_escalate(model, 'PLAN_ASSERT', 'test-project')

        self.assertIsInstance(decision, ProxyDecision)
        self.assertIsInstance(decision.action, str)
        self.assertIsInstance(decision.confidence, float)
        self.assertIsInstance(decision.reasoning, str)
        self.assertIsInstance(decision.predicted_response, str)
        self.assertTrue(len(decision.reasoning) > 0)

    def test_approve_predicted_response(self):
        """Auto-approve decisions report 'approve' as predicted response."""
        entry = _make_entry(approve_count=10, total_count=10)
        model = _model_with_entry(entry)
        decision = should_escalate(model, 'PLAN_ASSERT', 'test-project')
        self.assertEqual(decision.predicted_response, 'approve')


# ── 3. Low confidence — escalate ──────────────────────────────────────────────

class TestLowConfidenceEscalates(DeterministicProxyTestCase):

    def test_high_correction_rate_escalates(self):
        """High correction rate keeps confidence below threshold → escalate."""
        # 3 approvals, 7 corrections out of 10 total
        entry = _make_entry(
            approve_count=3,
            correct_count=7,
            total_count=10,
        )
        model = _model_with_entry(entry)
        decision = should_escalate(model, 'PLAN_ASSERT', 'test-project')
        self.assertEqual(decision.action, 'escalate')

    def test_mixed_outcomes_below_threshold_escalates(self):
        """When confidence is between 0.5 and 0.8 the proxy still escalates."""
        # 7 approvals out of 10 → confidence ~= (7+1)/(10+2) = 0.667
        entry = _make_entry(
            approve_count=7,
            reject_count=3,
            total_count=10,
        )
        model = _model_with_entry(entry)
        decision = should_escalate(model, 'PLAN_ASSERT', 'test-project')
        self.assertEqual(decision.action, 'escalate')
        self.assertLess(decision.confidence, 0.8)

    def test_zero_approvals_escalates(self):
        """Zero approvals with many total observations → escalate."""
        entry = _make_entry(
            approve_count=0,
            reject_count=10,
            total_count=10,
        )
        model = _model_with_entry(entry)
        decision = should_escalate(model, 'PLAN_ASSERT', 'test-project')
        self.assertEqual(decision.action, 'escalate')

    def test_reasoning_mentions_counts(self):
        """Escalate reasoning reports the raw approval and total counts."""
        entry = _make_entry(
            approve_count=4,
            correct_count=6,
            total_count=10,
        )
        model = _model_with_entry(entry)
        decision = should_escalate(model, 'PLAN_ASSERT', 'test-project')
        self.assertEqual(decision.action, 'escalate')
        self.assertIn('4', decision.reasoning)   # approve_count
        self.assertIn('10', decision.reasoning)  # total_count


# ── 4. Generative states — higher threshold ───────────────────────────────────

class TestGenerativeStates(DeterministicProxyTestCase):

    def test_no_generative_states_remain(self):
        """With intent/planning moved to skill-based termination, no gate
        state needs the higher generative threshold — WORK_ASSERT is binary."""
        self.assertFalse(is_generative_state('WORK_ASSERT'))

    def test_generative_state_auto_approves_when_very_high_confidence(self):
        """Generative state auto-approves only when confidence clears 0.95."""
        # 20 approvals out of 20 → confidence = (20+1)/(20+2) ≈ 0.955 > 0.95
        entry = _make_entry(
            state='WORK_ASSERT',
            task_type='well-calibrated',
            approve_count=20,
            total_count=20,
        )
        model = _model_with_entry(entry, generative_threshold=0.95)
        decision = should_escalate(model, 'WORK_ASSERT', 'well-calibrated')
        self.assertEqual(decision.action, 'auto-approve')


# ── 5. Record outcome — counter updates ───────────────────────────────────────

class TestRecordOutcome(unittest.TestCase):

    def test_approve_increments_approve_and_total(self):
        model = _make_model()
        model = record_outcome(model, 'PLAN_ASSERT', 'proj', 'approve')
        key = 'PLAN_ASSERT|proj'
        entry = ConfidenceEntry(**model.entries[key])
        self.assertEqual(entry.approve_count, 1)
        self.assertEqual(entry.total_count, 1)
        self.assertEqual(entry.correct_count, 0)
        self.assertEqual(entry.reject_count, 0)

    def test_correct_increments_correct_and_total(self):
        model = _make_model()
        model = record_outcome(model, 'WORK_ASSERT', 'proj', 'correct')
        key = 'WORK_ASSERT|proj'
        entry = ConfidenceEntry(**model.entries[key])
        self.assertEqual(entry.correct_count, 1)
        self.assertEqual(entry.total_count, 1)
        self.assertEqual(entry.approve_count, 0)

    def test_reject_increments_reject_and_total(self):
        model = _make_model()
        model = record_outcome(model, 'WORK_ASSERT', 'proj', 'reject')
        key = 'WORK_ASSERT|proj'
        entry = ConfidenceEntry(**model.entries[key])
        self.assertEqual(entry.reject_count, 1)
        self.assertEqual(entry.total_count, 1)

    def test_withdraw_increments_reject_counter(self):
        """Withdraw is grouped with reject for confidence tracking purposes."""
        model = _make_model()
        model = record_outcome(model, 'PLAN_ASSERT', 'proj', 'withdraw')
        key = 'PLAN_ASSERT|proj'
        entry = ConfidenceEntry(**model.entries[key])
        self.assertEqual(entry.reject_count, 1)
        self.assertEqual(entry.total_count, 1)

    def test_clarify_only_increments_total(self):
        """'clarify' is a non-approval signal — it increments total but no sub-counter."""
        model = _make_model()
        model = record_outcome(model, 'WORK_ASSERT', 'proj', 'clarify')
        key = 'WORK_ASSERT|proj'
        entry = ConfidenceEntry(**model.entries[key])
        self.assertEqual(entry.total_count, 1)
        self.assertEqual(entry.approve_count, 0)
        self.assertEqual(entry.correct_count, 0)
        self.assertEqual(entry.reject_count, 0)

    def test_creates_new_entry_for_unseen_pair(self):
        """record_outcome creates a new ConfidenceEntry if the pair is new."""
        model = _make_model()
        self.assertNotIn('WORK_ASSERT|brand-new', model.entries)
        model = record_outcome(model, 'WORK_ASSERT', 'brand-new', 'approve')
        self.assertIn('WORK_ASSERT|brand-new', model.entries)

    def test_invalid_outcome_raises_value_error(self):
        model = _make_model()
        with self.assertRaises(ValueError):
            record_outcome(model, 'PLAN_ASSERT', 'proj', 'not-valid')

    def test_record_does_not_mutate_original(self):
        """record_outcome must return a new model without modifying the original."""
        model = _make_model()
        original_entries = dict(model.entries)
        _ = record_outcome(model, 'PLAN_ASSERT', 'proj', 'approve')
        self.assertEqual(model.entries, original_entries,
                         "Original model must not be mutated")

    def test_multiple_records_accumulate(self):
        """Successive record_outcome calls accumulate counts correctly."""
        model = _make_model()
        model = _record_n(model, 'PLAN_ASSERT', 'proj', 'approve', 5)
        model = _record_n(model, 'PLAN_ASSERT', 'proj', 'correct', 2)
        model = _record_n(model, 'PLAN_ASSERT', 'proj', 'reject', 1)

        key = 'PLAN_ASSERT|proj'
        entry = ConfidenceEntry(**model.entries[key])
        self.assertEqual(entry.approve_count, 5)
        self.assertEqual(entry.correct_count, 2)
        self.assertEqual(entry.reject_count, 1)
        self.assertEqual(entry.total_count, 8)


# ── 6. Bayesian smoothing ─────────────────────────────────────────────────────

class TestBayesianSmoothing(unittest.TestCase):

    def test_zero_total_returns_zero(self):
        entry = _make_entry(approve_count=0, total_count=0)
        self.assertEqual(compute_confidence(entry), 0.0)

    def test_all_approvals_approaches_one(self):
        """100% approval rate converges toward 1.0 with Laplace smoothing."""
        entry = _make_entry(approve_count=100, total_count=100)
        conf = compute_confidence(entry)
        # (100+1)/(100+2) ≈ 0.990
        self.assertAlmostEqual(conf, 101 / 102, places=6)
        self.assertGreater(conf, 0.98)

    def test_no_approvals_approaches_zero(self):
        """0% approval rate: (0+1)/(N+2) shrinks as N grows."""
        entry = _make_entry(approve_count=0, total_count=100)
        conf = compute_confidence(entry)
        # (0+1)/(100+2) ≈ 0.0098
        self.assertAlmostEqual(conf, 1 / 102, places=6)
        self.assertLess(conf, 0.02)

    def test_smoothing_formula_exact(self):
        """Laplace smoothing: confidence = (approve+1) / (total+2)."""
        entry = _make_entry(approve_count=4, total_count=10)
        expected = (4 + 1) / (10 + 2)
        self.assertAlmostEqual(compute_confidence(entry), expected, places=10)

    def test_single_sample_not_extreme(self):
        """One approval should not produce confidence of 1.0."""
        entry = _make_entry(approve_count=1, total_count=1)
        conf = compute_confidence(entry)
        self.assertLess(conf, 1.0)
        self.assertGreater(conf, 0.5)  # (1+1)/(1+2) ≈ 0.667

    def test_confidence_converges_to_true_rate(self):
        """With large N, smoothed confidence converges toward the true rate."""
        # 80% approval rate with many observations
        entry = _make_entry(approve_count=800, total_count=1000)
        conf = compute_confidence(entry)
        self.assertAlmostEqual(conf, 0.8, delta=0.005)


# ── 7. Persistence round-trip ─────────────────────────────────────────────────

class TestPersistence(DeterministicProxyTestCase):

    def setUp(self):
        super().setUp()
        self.tmpdir = tempfile.mkdtemp()
        self.model_path = os.path.join(self.tmpdir, '.proxy-confidence.json')

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)
        super().tearDown()

    def test_save_creates_file(self):
        model = _make_model()
        save_model(model, self.model_path)
        self.assertTrue(os.path.isfile(self.model_path))

    def test_load_missing_returns_empty_model(self):
        missing = os.path.join(self.tmpdir, 'nonexistent.json')
        model = load_model(missing)
        self.assertIsInstance(model, ConfidenceModel)
        self.assertEqual(model.entries, {})
        self.assertEqual(model.global_threshold, 0.8)

    def test_round_trip_empty_model(self):
        model = _make_model()
        save_model(model, self.model_path)
        loaded = load_model(self.model_path)
        self.assertEqual(loaded.entries, {})
        self.assertEqual(loaded.global_threshold, model.global_threshold)
        self.assertEqual(loaded.generative_threshold, model.generative_threshold)

    def test_round_trip_with_entries(self):
        """save → load preserves all entry fields."""
        model = _make_model()
        model = _record_n(model, 'PLAN_ASSERT', 'my-proj', 'approve', 7)
        model = _record_n(model, 'PLAN_ASSERT', 'my-proj', 'correct', 2)
        model = _record_n(model, 'WORK_ASSERT', 'other-proj', 'approve', 5)

        save_model(model, self.model_path)
        loaded = load_model(self.model_path)

        self.assertEqual(set(loaded.entries.keys()), set(model.entries.keys()))

        plan_entry = ConfidenceEntry(**loaded.entries['PLAN_ASSERT|my-proj'])
        self.assertEqual(plan_entry.approve_count, 7)
        self.assertEqual(plan_entry.correct_count, 2)
        self.assertEqual(plan_entry.total_count, 9)

        work_entry = ConfidenceEntry(**loaded.entries['WORK_ASSERT|other-proj'])
        self.assertEqual(work_entry.approve_count, 5)
        self.assertEqual(work_entry.total_count, 5)

    def test_round_trip_preserves_thresholds(self):
        model = make_model(global_threshold=0.75, generative_threshold=0.92)
        save_model(model, self.model_path)
        loaded = load_model(self.model_path)
        self.assertAlmostEqual(loaded.global_threshold, 0.75, places=5)
        self.assertAlmostEqual(loaded.generative_threshold, 0.92, places=5)

    def test_load_corrupted_json_returns_empty_model(self):
        Path(self.model_path).write_text('not valid json{{')
        model = load_model(self.model_path)
        self.assertIsInstance(model, ConfidenceModel)
        self.assertEqual(model.entries, {})

    def test_save_creates_parent_directories(self):
        nested = os.path.join(self.tmpdir, 'deep', 'nested', 'model.json')
        model = _make_model()
        save_model(model, nested)
        self.assertTrue(os.path.isfile(nested))

    def test_loaded_model_gives_same_decision(self):
        """A model round-tripped through disk produces the same decision."""
        model = _make_model()
        model = _record_n(model, 'WORK_ASSERT', 'stable-proj', 'approve', 15)

        decision_before = should_escalate(model, 'WORK_ASSERT', 'stable-proj')
        save_model(model, self.model_path)
        loaded = load_model(self.model_path)
        decision_after = should_escalate(loaded, 'WORK_ASSERT', 'stable-proj')

        self.assertEqual(decision_before.action, decision_after.action)
        self.assertAlmostEqual(decision_before.confidence, decision_after.confidence, places=6)


# ── 8. Mixed task types ───────────────────────────────────────────────────────

class TestMixedTaskTypes(DeterministicProxyTestCase):

    def test_different_task_types_tracked_independently(self):
        """Two different task types at the same state have independent confidence."""
        from dataclasses import asdict

        reliable_entry = _make_entry(
            state='PLAN_ASSERT',
            task_type='reliable-proj',
            approve_count=10,
            total_count=10,
        )
        unreliable_entry = _make_entry(
            state='PLAN_ASSERT',
            task_type='unreliable-proj',
            approve_count=2,
            reject_count=8,
            total_count=10,
        )
        model = ConfidenceModel(
            entries={
                'PLAN_ASSERT|reliable-proj': asdict(reliable_entry),
                'PLAN_ASSERT|unreliable-proj': asdict(unreliable_entry),
            },
            global_threshold=0.8,
            generative_threshold=0.95,
        )

        reliable_decision = should_escalate(model, 'PLAN_ASSERT', 'reliable-proj')
        unreliable_decision = should_escalate(model, 'PLAN_ASSERT', 'unreliable-proj')

        self.assertEqual(reliable_decision.action, 'auto-approve')
        self.assertEqual(unreliable_decision.action, 'escalate')

    def test_unknown_task_type_always_escalates(self):
        """A task type with no history cold-starts even if another type has history."""
        from dataclasses import asdict
        known_entry = _make_entry(
            state='PLAN_ASSERT',
            task_type='known-proj',
            approve_count=50,
            total_count=50,
        )
        model = ConfidenceModel(
            entries={'PLAN_ASSERT|known-proj': asdict(known_entry)},
            global_threshold=0.8,
            generative_threshold=0.95,
        )

        decision = should_escalate(model, 'PLAN_ASSERT', 'unknown-proj')
        self.assertEqual(decision.action, 'escalate')
        self.assertIn('Cold start', decision.reasoning)

    def test_same_state_multiple_task_types_accumulate_separately(self):
        """Recording for one task type does not affect another at the same state."""
        model = _make_model()
        model = _record_n(model, 'PLAN_ASSERT', 'proj-a', 'approve', 10)
        model = _record_n(model, 'PLAN_ASSERT', 'proj-b', 'reject', 10)

        key_a = 'PLAN_ASSERT|proj-a'
        key_b = 'PLAN_ASSERT|proj-b'

        entry_a = ConfidenceEntry(**model.entries[key_a])
        entry_b = ConfidenceEntry(**model.entries[key_b])

        self.assertEqual(entry_a.approve_count, 10)
        self.assertEqual(entry_a.reject_count, 0)
        self.assertEqual(entry_b.approve_count, 0)
        self.assertEqual(entry_b.reject_count, 10)


# ── 9. Full learning loop ─────────────────────────────────────────────────────

class TestFullLearningLoop(DeterministicProxyTestCase):

    def test_ten_approvals_then_auto_approve(self):
        """After 10 approvals the proxy should auto-approve."""
        model = _make_model()
        model = _record_n(model, 'PLAN_ASSERT', 'evolving-proj', 'approve', 10)

        decision = should_escalate(model, 'PLAN_ASSERT', 'evolving-proj')
        self.assertEqual(decision.action, 'auto-approve',
                         f"Expected auto-approve after 10 approvals, got: {decision.reasoning}")

    def test_corrections_after_approvals_drop_confidence(self):
        """3 corrections after 10 approvals should push confidence below threshold."""
        model = _make_model()
        model = _record_n(model, 'PLAN_ASSERT', 'evolving-proj', 'approve', 10)
        model = _record_n(model, 'PLAN_ASSERT', 'evolving-proj', 'correct', 3)

        # confidence = (10+1)/(13+2) = 11/15 ≈ 0.733 < 0.80
        decision = should_escalate(model, 'PLAN_ASSERT', 'evolving-proj')
        self.assertEqual(decision.action, 'escalate',
                         f"Expected escalate after corrections, got: {decision.reasoning}")

    def test_full_loop_confidence_values(self):
        """Verify confidence values at each stage of the learning loop.

        confidence = min(laplace, ema). After pure approvals, EMA > Laplace
        so confidence = Laplace. After corrections with asymmetric regret
        (REGRET_WEIGHT=3), EMA crashes well below Laplace, so confidence
        tracks EMA — this is the intended least-regret behavior.
        """
        model = _make_model()

        # Stage 1: cold start
        d0 = should_escalate(model, 'PLAN_ASSERT', 'loop-proj')
        self.assertEqual(d0.action, 'escalate')
        self.assertEqual(d0.confidence, 0.0)

        # Stage 2: after 10 approvals
        model = _record_n(model, 'PLAN_ASSERT', 'loop-proj', 'approve', 10)
        d1 = should_escalate(model, 'PLAN_ASSERT', 'loop-proj')
        # Laplace = (10+1)/(10+2) = 11/12 ≈ 0.917
        # EMA > Laplace after pure approvals, so confidence = Laplace
        expected_after_10 = 11 / 12
        self.assertAlmostEqual(d1.confidence, expected_after_10, places=6)
        self.assertEqual(d1.action, 'auto-approve')

        # Stage 3: after 3 corrections (asymmetric regret = 9 EMA decay steps)
        model = _record_n(model, 'PLAN_ASSERT', 'loop-proj', 'correct', 3)
        d2 = should_escalate(model, 'PLAN_ASSERT', 'loop-proj')
        laplace_after = 11 / 15  # ≈ 0.733
        # EMA crashed well below Laplace due to regret weighting,
        # so confidence = EMA << Laplace
        self.assertLess(d2.confidence, laplace_after,
                        "EMA should be below Laplace after corrections with regret weighting")
        self.assertLess(d2.confidence, 0.1,
                        "3 corrections × REGRET_WEIGHT=3 = 9 decay steps should crash EMA")
        self.assertEqual(d2.action, 'escalate')

    def test_recovery_after_corrections(self):
        """After corrections erode confidence, further approvals can restore it."""
        model = _make_model()
        model = _record_n(model, 'PLAN_ASSERT', 'recovery-proj', 'approve', 10)
        model = _record_n(model, 'PLAN_ASSERT', 'recovery-proj', 'correct', 3)

        # Verify we're currently escalating
        d_low = should_escalate(model, 'PLAN_ASSERT', 'recovery-proj')
        self.assertEqual(d_low.action, 'escalate')

        # Now add more approvals to push confidence back above threshold
        model = _record_n(model, 'PLAN_ASSERT', 'recovery-proj', 'approve', 10)

        d_recovered = should_escalate(model, 'PLAN_ASSERT', 'recovery-proj')
        # confidence = (20+1)/(23+2) = 21/25 = 0.84 > 0.80
        self.assertEqual(d_recovered.action, 'auto-approve',
                         f"Expected recovery to auto-approve, got: {d_recovered.reasoning}")


# ── 10. Team-scoped model paths ──────────────────────────────────────────────

class TestTeamScopedModels(DeterministicProxyTestCase):

    def setUp(self):
        super().setUp()
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)
        super().tearDown()

    def test_resolve_team_model_path(self):
        from teaparty.proxy.approval_gate import resolve_team_model_path
        base = '/path/to/.proxy-confidence.json'
        self.assertEqual(
            resolve_team_model_path(base, 'coding'),
            '/path/to/.proxy-confidence-coding.json'
        )

    def test_resolve_team_model_path_empty_team(self):
        from teaparty.proxy.approval_gate import resolve_team_model_path
        base = '/path/to/.proxy-confidence.json'
        self.assertEqual(resolve_team_model_path(base, ''), base)

    def test_resolve_team_model_path_various_teams(self):
        from teaparty.proxy.approval_gate import resolve_team_model_path
        base = '/data/.proxy-confidence.json'
        self.assertEqual(
            resolve_team_model_path(base, 'art'),
            '/data/.proxy-confidence-art.json'
        )
        self.assertEqual(
            resolve_team_model_path(base, 'research'),
            '/data/.proxy-confidence-research.json'
        )

    def test_independent_team_models(self):
        """Two teams write to different files and don't cross-contaminate."""
        from teaparty.proxy.approval_gate import resolve_team_model_path

        base = os.path.join(self.tmpdir, '.proxy-confidence.json')
        coding_path = resolve_team_model_path(base, 'coding')
        art_path = resolve_team_model_path(base, 'art')

        # Build separate models
        coding_model = _make_model()
        coding_model = _record_n(coding_model, 'PLAN_ASSERT', 'proj', 'approve', 10)
        save_model(coding_model, coding_path)

        art_model = _make_model()
        art_model = _record_n(art_model, 'PLAN_ASSERT', 'proj', 'reject', 10)
        save_model(art_model, art_path)

        # Load and verify independence
        loaded_coding = load_model(coding_path)
        loaded_art = load_model(art_path)

        coding_decision = should_escalate(loaded_coding, 'PLAN_ASSERT', 'proj')
        art_decision = should_escalate(loaded_art, 'PLAN_ASSERT', 'proj')

        self.assertEqual(coding_decision.action, 'auto-approve')
        self.assertEqual(art_decision.action, 'escalate')

    def test_uber_model_separate_from_team_models(self):
        """The uber-level model at the base path is separate from team-scoped models."""
        from teaparty.proxy.approval_gate import resolve_team_model_path

        base = os.path.join(self.tmpdir, '.proxy-confidence.json')
        coding_path = resolve_team_model_path(base, 'coding')

        # Write uber model
        uber_model = _make_model()
        uber_model = _record_n(uber_model, 'WORK_ASSERT', 'proj', 'approve', 8)
        save_model(uber_model, base)

        # Write coding model
        coding_model = _make_model()
        coding_model = _record_n(coding_model, 'WORK_ASSERT', 'proj', 'reject', 8)
        save_model(coding_model, coding_path)

        # Verify files are different
        self.assertTrue(os.path.isfile(base))
        self.assertTrue(os.path.isfile(coding_path))
        self.assertNotEqual(base, coding_path)

        loaded_uber = load_model(base)
        loaded_coding = load_model(coding_path)

        uber_decision = should_escalate(loaded_uber, 'WORK_ASSERT', 'proj')
        coding_decision = should_escalate(loaded_coding, 'WORK_ASSERT', 'proj')

        self.assertEqual(uber_decision.action, 'auto-approve')
        self.assertEqual(coding_decision.action, 'escalate')


# ── 11. WORK_ASSERT gate ───────────────────────────────────────────────────

class TestIntentAssertGate(DeterministicProxyTestCase):
    """WORK_ASSERT is a binary state used at the intent phase gate in run.sh.
    Verify the proxy correctly handles it alongside PLAN_ASSERT/WORK_ASSERT."""

    def test_intent_assert_is_binary(self):
        """WORK_ASSERT should be in the BINARY_STATES list."""
        self.assertIn('WORK_ASSERT', BINARY_STATES)

    def test_intent_assert_cold_start_escalates(self):
        """No history → always escalate."""
        model = _make_model()
        decision = should_escalate(model, 'WORK_ASSERT', 'default')
        self.assertEqual(decision.action, 'escalate')

    def test_intent_assert_auto_approve_after_training(self):
        """After enough approvals, proxy should auto-approve intent."""
        model = _make_model()
        model = _record_n(model, 'WORK_ASSERT', 'default', 'approve', 10)
        decision = should_escalate(model, 'WORK_ASSERT', 'default')
        self.assertEqual(decision.action, 'auto-approve')

    def test_intent_assert_corrections_erode_confidence(self):
        """Corrections after approvals push confidence below threshold."""
        model = _make_model()
        model = _record_n(model, 'WORK_ASSERT', 'default', 'approve', 8)
        model = _record_n(model, 'WORK_ASSERT', 'default', 'reject', 4)
        decision = should_escalate(model, 'WORK_ASSERT', 'default')
        self.assertEqual(decision.action, 'escalate')

    def test_intent_assert_independent_from_plan_assert(self):
        """WORK_ASSERT and PLAN_ASSERT are tracked independently."""
        model = _make_model()
        model = _record_n(model, 'PLAN_ASSERT', 'default', 'approve', 20)
        model = _record_n(model, 'WORK_ASSERT', 'default', 'reject', 3)

        plan_decision = should_escalate(model, 'PLAN_ASSERT', 'default')
        intent_decision = should_escalate(model, 'WORK_ASSERT', 'default')

        self.assertEqual(plan_decision.action, 'auto-approve')
        self.assertEqual(intent_decision.action, 'escalate')

    def test_intent_assert_uses_binary_threshold(self):
        """WORK_ASSERT should use the binary threshold (0.8), not generative (0.95)."""
        self.assertFalse(is_generative_state('WORK_ASSERT'))


# ── 12. Text differential learning ──────────────────────────────────────────

class TestTextDifferentials(unittest.TestCase):
    """Per spec Section 9.2: the proxy records what the human changed,
    not just binary approve/reject."""

    def test_record_with_differential_stores_it(self):
        """record_outcome with a diff summary stores a TextDifferential."""
        model = _make_model()
        model = record_outcome(
            model, 'WORK_ASSERT', 'proj', 'correct',
            differential_summary='Fix the header formatting',
        )
        key = 'WORK_ASSERT|proj'
        entry = ConfidenceEntry(**model.entries[key])
        self.assertEqual(len(entry.differentials), 1)
        diff = entry.differentials[0]
        self.assertEqual(diff['outcome'], 'correct')
        self.assertEqual(diff['summary'], 'Fix the header formatting')
        self.assertIn('2026', diff['timestamp'])

    def test_approve_does_not_store_differential(self):
        """approve outcomes don't store differentials even if text is provided."""
        model = _make_model()
        model = record_outcome(
            model, 'PLAN_ASSERT', 'proj', 'approve',
            differential_summary='looks fine',
        )
        key = 'PLAN_ASSERT|proj'
        entry = ConfidenceEntry(**model.entries[key])
        self.assertEqual(len(entry.differentials), 0)

    def test_multiple_differentials_accumulate(self):
        """Multiple corrections accumulate differentials."""
        model = _make_model()
        model = record_outcome(model, 'WORK_ASSERT', 'proj', 'correct',
                               differential_summary='Fix header')
        model = record_outcome(model, 'WORK_ASSERT', 'proj', 'correct',
                               differential_summary='Fix footer')
        model = record_outcome(model, 'WORK_ASSERT', 'proj', 'reject',
                               differential_summary='Wrong approach')
        key = 'WORK_ASSERT|proj'
        entry = ConfidenceEntry(**model.entries[key])
        self.assertEqual(len(entry.differentials), 3)
        summaries = [d['summary'] for d in entry.differentials]
        self.assertEqual(summaries, ['Fix header', 'Fix footer', 'Wrong approach'])

    def test_differential_capped_at_max(self):
        """Differentials are capped at MAX_DIFFERENTIALS_PER_ENTRY."""
        from teaparty.proxy.approval_gate import MAX_DIFFERENTIALS_PER_ENTRY
        model = _make_model()
        for i in range(MAX_DIFFERENTIALS_PER_ENTRY + 5):
            model = record_outcome(
                model, 'WORK_ASSERT', 'proj', 'correct',
                differential_summary=f'correction {i}',
            )
        key = 'WORK_ASSERT|proj'
        entry = ConfidenceEntry(**model.entries[key])
        self.assertEqual(len(entry.differentials), MAX_DIFFERENTIALS_PER_ENTRY)
        # The oldest 5 should have been evicted — last entry should be the most recent
        self.assertEqual(entry.differentials[-1]['summary'], f'correction {MAX_DIFFERENTIALS_PER_ENTRY + 4}')

    def test_differential_summary_truncated_at_500_chars(self):
        """Long differential summaries are truncated to 500 chars."""
        model = _make_model()
        long_summary = 'x' * 1000
        model = record_outcome(
            model, 'WORK_ASSERT', 'proj', 'correct',
            differential_summary=long_summary,
        )
        key = 'WORK_ASSERT|proj'
        entry = ConfidenceEntry(**model.entries[key])
        self.assertEqual(len(entry.differentials[0]['summary']), 500)

    def test_empty_differential_not_stored(self):
        """Empty diff summary is not stored."""
        model = _make_model()
        model = record_outcome(
            model, 'WORK_ASSERT', 'proj', 'correct',
            differential_summary='',
        )
        key = 'WORK_ASSERT|proj'
        entry = ConfidenceEntry(**model.entries[key])
        self.assertEqual(len(entry.differentials), 0)

    def test_differentials_survive_round_trip(self):
        """Differentials persist through save/load cycle."""
        tmpdir = tempfile.mkdtemp()
        try:
            model_path = os.path.join(tmpdir, 'model.json')
            model = _make_model()
            model = record_outcome(model, 'WORK_ASSERT', 'proj', 'correct',
                                   differential_summary='Fix the colors')
            save_model(model, model_path)
            loaded = load_model(model_path)

            key = 'WORK_ASSERT|proj'
            entry = ConfidenceEntry(**loaded.entries[key])
            self.assertEqual(len(entry.differentials), 1)
            self.assertEqual(entry.differentials[0]['summary'], 'Fix the colors')
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_backward_compat_entry_without_differentials(self):
        """Old model files missing 'differentials' field still load correctly."""
        tmpdir = tempfile.mkdtemp()
        try:
            model_path = os.path.join(tmpdir, 'model.json')
            # Write a model file without differentials field (old format)
            old_format = {
                'global_threshold': 0.8,
                'generative_threshold': 0.95,
                'entries': {
                    'PLAN_ASSERT|old-proj': {
                        'state': 'PLAN_ASSERT',
                        'task_type': 'old-proj',
                        'approve_count': 5,
                        'correct_count': 1,
                        'reject_count': 0,
                        'total_count': 6,
                        'last_updated': '2026-01-01',
                        # No 'differentials' field — old format
                    }
                }
            }
            with open(model_path, 'w') as f:
                json.dump(old_format, f)

            loaded = load_model(model_path)
            # Should be able to record new outcomes (with backward compat)
            updated = record_outcome(loaded, 'PLAN_ASSERT', 'old-proj', 'correct',
                                     differential_summary='Add error handling')
            key = 'PLAN_ASSERT|old-proj'
            entry = ConfidenceEntry(**updated.entries[key])
            self.assertEqual(entry.correct_count, 2)
            self.assertEqual(len(entry.differentials), 1)
            self.assertEqual(entry.differentials[0]['summary'], 'Add error handling')
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


# ── 13. Escalation state proxy recording ──────────────────────────────────────

class TestEscalationRecording(unittest.TestCase):
    """Verify proxy_record works for ESCALATE states (WORK_ASSERT,
    PLANNING_ESCALATE) with differentials."""

    def test_record_clarify_on_intent_escalate(self):
        """Clarify on WORK_ASSERT records correctly."""
        model = _make_model()
        model = record_outcome(
            model, 'WORK_ASSERT', 'proj', 'clarify',
            differential_summary='Output should be a single doc',
        )
        key = 'WORK_ASSERT|proj'
        entry = ConfidenceEntry(**model.entries[key])
        self.assertEqual(entry.total_count, 1)
        self.assertEqual(entry.approve_count, 0)
        self.assertEqual(entry.correct_count, 0)
        # clarify only increments total, not any sub-counter
        self.assertEqual(len(entry.differentials), 1)
        self.assertEqual(entry.differentials[0]['outcome'], 'clarify')

    def test_record_withdraw_on_planning_escalate(self):
        """Withdraw on PLANNING_ESCALATE records correctly."""
        model = _make_model()
        model = record_outcome(model, 'PLANNING_ESCALATE', 'proj', 'withdraw')
        key = 'PLANNING_ESCALATE|proj'
        entry = ConfidenceEntry(**model.entries[key])
        self.assertEqual(entry.reject_count, 1)
        self.assertEqual(entry.total_count, 1)

    def test_record_clarify_on_planning_escalate_with_differential(self):
        """Clarify on PLANNING_ESCALATE records correctly with differential."""
        model = _make_model()
        model = record_outcome(
            model, 'PLANNING_ESCALATE', 'proj2', 'clarify',
            differential_summary='Use the REST API not GraphQL',
        )
        key = 'PLANNING_ESCALATE|proj2'
        entry = ConfidenceEntry(**model.entries[key])
        self.assertEqual(entry.total_count, 1)
        self.assertEqual(len(entry.differentials), 1)
        self.assertEqual(entry.differentials[0]['summary'], 'Use the REST API not GraphQL')



# ── 14. Generative proxy response ───────────────────────────────────────────

class TestGenerativeResponse(unittest.TestCase):
    """Tests for generate_response() — predicting human responses from
    differential history.

    generate_response() always returns a GenerativeResponse (never None).
    Callers decide whether to act on it based on confidence vs threshold.
    Issue #138: the differential between prediction and human answer is the
    highest-value learning signal — requires a prediction to exist.
    """

    def test_low_observation_count_returns_low_confidence(self):
        """With few observations, confidence is below the generative threshold."""
        from teaparty.proxy.approval_gate import generate_response, GenerativeResponse
        model = _make_model()
        model = record_outcome(model, 'WORK_ASSERT', 'proj', 'correct',
                               differential_summary='Fix colors')
        result = generate_response(model, 'WORK_ASSERT', 'proj')
        self.assertIsInstance(result, GenerativeResponse)
        self.assertLess(result.confidence, model.generative_threshold)

    def test_no_differentials_returns_low_confidence_response(self):
        """With no differentials, response has low confidence and generic text."""
        from teaparty.proxy.approval_gate import generate_response, GenerativeResponse
        model = _make_model()
        # Record enough approvals to pass cold start but no differentials
        model = _record_n(model, 'PLAN_ASSERT', 'proj', 'approve', 10)
        result = generate_response(model, 'PLAN_ASSERT', 'proj')
        self.assertIsInstance(result, GenerativeResponse)
        self.assertLessEqual(result.confidence, 0.1)

    def test_below_threshold_still_returns_response(self):
        """generate_response returns a response even when confidence < threshold."""
        from teaparty.proxy.approval_gate import generate_response, GenerativeResponse
        model = _make_model()
        # Mix of approvals and corrections → confidence below 0.80
        model = _record_n(model, 'WORK_ASSERT', 'proj', 'approve', 3)
        for i in range(4):
            model = record_outcome(model, 'WORK_ASSERT', 'proj', 'correct',
                                   differential_summary=f'Fix issue {i}')
        result = generate_response(model, 'WORK_ASSERT', 'proj')
        self.assertIsInstance(result, GenerativeResponse)
        self.assertLess(result.confidence, model.generative_threshold)

    def test_returns_response_when_confident_with_differentials(self):
        """generate_response returns a prediction when confidence is high."""
        from teaparty.proxy.approval_gate import generate_response, GenerativeResponse
        model = _make_model()
        # Many approvals + one correction with differential
        model = _record_n(model, 'WORK_ASSERT', 'proj', 'approve', 10)
        model = record_outcome(model, 'WORK_ASSERT', 'proj', 'correct',
                               differential_summary='Always check error codes')
        # More approvals to push confidence back above threshold
        model = _record_n(model, 'WORK_ASSERT', 'proj', 'approve', 10)
        result = generate_response(model, 'WORK_ASSERT', 'proj')
        self.assertIsNotNone(result)
        self.assertIsInstance(result, GenerativeResponse)
        self.assertEqual(result.action, 'correct')
        self.assertEqual(result.text, 'Always check error codes')
        self.assertGreater(result.confidence, 0.8)

    def test_generative_state_below_threshold_returns_low_confidence(self):
        """Below generative_threshold, response confidence reflects the gap."""
        from teaparty.proxy.approval_gate import generate_response, GenerativeResponse
        model = _make_model(generative_threshold=0.95)
        # 9 approvals + 1 correction → confidence ~= (9+1)/(11+2) = 0.769
        model = _record_n(model, 'WORK_ASSERT', 'proj', 'approve', 9)
        model = record_outcome(model, 'WORK_ASSERT', 'proj', 'correct',
                               differential_summary='Use markdown format')
        result = generate_response(model, 'WORK_ASSERT', 'proj')
        self.assertIsInstance(result, GenerativeResponse)
        self.assertLess(result.confidence, model.generative_threshold)

    def test_returns_most_recent_differential(self):
        """generate_response returns the most recent differential text."""
        from teaparty.proxy.approval_gate import generate_response
        model = _make_model()
        model = _record_n(model, 'WORK_ASSERT', 'proj', 'approve', 15)
        model = record_outcome(model, 'WORK_ASSERT', 'proj', 'correct',
                               differential_summary='Old fix')
        model = record_outcome(model, 'WORK_ASSERT', 'proj', 'correct',
                               differential_summary='Recent fix')
        # Add more approvals to maintain high confidence
        model = _record_n(model, 'WORK_ASSERT', 'proj', 'approve', 10)
        result = generate_response(model, 'WORK_ASSERT', 'proj')
        self.assertIsNotNone(result)
        self.assertEqual(result.text, 'Recent fix')

    def test_unseen_state_returns_zero_confidence(self):
        """generate_response returns a low-confidence response for a state with no history."""
        from teaparty.proxy.approval_gate import generate_response, GenerativeResponse
        model = _make_model()
        result = generate_response(model, 'PLANNING_ESCALATE', 'proj')
        self.assertIsInstance(result, GenerativeResponse)
        self.assertEqual(result.confidence, 0.0)


# ── 10. Exploration and staleness ────────────────────────────────────────────

class TestExploration(unittest.TestCase):
    """Tests for the explore/exploit balance (ε-greedy exploration)."""

    def test_exploration_triggers_escalation(self):
        """When random < EXPLORE_RATE, escalate even with high confidence."""
        entry = _make_entry(approve_count=20, total_count=20)
        model = _model_with_entry(entry)
        with patch('teaparty.proxy.approval_gate.random.random', return_value=0.0):
            decision = should_escalate(model, 'PLAN_ASSERT', 'test-project')
        self.assertEqual(decision.action, 'escalate')
        self.assertIn('Exploration', decision.reasoning)

    def test_no_exploration_when_random_above_rate(self):
        """When random >= EXPLORE_RATE, auto-approve as normal."""
        entry = _make_entry(approve_count=20, total_count=20)
        model = _model_with_entry(entry)
        with patch('teaparty.proxy.approval_gate.random.random', return_value=1.0):
            decision = should_escalate(model, 'PLAN_ASSERT', 'test-project')
        self.assertEqual(decision.action, 'auto-approve')

    def test_exploration_preserves_confidence_value(self):
        """Exploration decisions still report the actual confidence."""
        entry = _make_entry(approve_count=10, total_count=10)
        model = _model_with_entry(entry)
        with patch('teaparty.proxy.approval_gate.random.random', return_value=0.0):
            decision = should_escalate(model, 'PLAN_ASSERT', 'test-project')
        self.assertGreater(decision.confidence, 0.8)
        self.assertEqual(decision.action, 'escalate')

    def test_exploration_does_not_affect_cold_start(self):
        """Cold start escalation takes priority over exploration."""
        model = _make_model()
        with patch('teaparty.proxy.approval_gate.random.random', return_value=1.0):
            decision = should_escalate(model, 'PLAN_ASSERT', 'new-proj')
        self.assertEqual(decision.action, 'escalate')
        self.assertIn('Cold start', decision.reasoning)

    def test_exploration_does_not_affect_low_confidence(self):
        """Low confidence escalation takes priority — no double reasoning."""
        entry = _make_entry(approve_count=3, correct_count=7, total_count=10)
        model = _model_with_entry(entry)
        with patch('teaparty.proxy.approval_gate.random.random', return_value=1.0):
            decision = should_escalate(model, 'PLAN_ASSERT', 'test-project')
        self.assertEqual(decision.action, 'escalate')
        self.assertNotIn('Exploration', decision.reasoning)


class TestStaleness(unittest.TestCase):
    """Tests for the staleness guard — force escalation after too long."""

    def test_stale_entry_forces_escalation(self):
        """Entry older than STALENESS_DAYS forces escalation."""
        from datetime import timedelta
        old_date = (date.today() - timedelta(days=STALENESS_DAYS + 1)).isoformat()
        entry = _make_entry(approve_count=20, total_count=20, last_updated=old_date)
        model = _model_with_entry(entry)
        with patch('teaparty.proxy.approval_gate.random.random', return_value=1.0):
            decision = should_escalate(model, 'PLAN_ASSERT', 'test-project')
        self.assertEqual(decision.action, 'escalate')
        self.assertIn('Stale', decision.reasoning)

    def test_fresh_entry_not_stale(self):
        """Entry updated today is not stale."""
        entry = _make_entry(
            approve_count=20, total_count=20,
            last_updated=date.today().isoformat(),
        )
        model = _model_with_entry(entry)
        with patch('teaparty.proxy.approval_gate.random.random', return_value=1.0):
            decision = should_escalate(model, 'PLAN_ASSERT', 'test-project')
        self.assertEqual(decision.action, 'auto-approve')

    def test_staleness_checked_before_exploration(self):
        """Stale entries escalate with staleness reasoning, not exploration."""
        from datetime import timedelta
        old_date = (date.today() - timedelta(days=STALENESS_DAYS + 1)).isoformat()
        entry = _make_entry(approve_count=20, total_count=20, last_updated=old_date)
        model = _model_with_entry(entry)
        # Even if exploration would not trigger (random=1.0), staleness wins
        with patch('teaparty.proxy.approval_gate.random.random', return_value=1.0):
            decision = should_escalate(model, 'PLAN_ASSERT', 'test-project')
        self.assertIn('Stale', decision.reasoning)

    def test_unparseable_date_treated_as_stale(self):
        """Entries with bad date strings are treated as stale."""
        entry = _make_entry(approve_count=20, total_count=20, last_updated='bad-date')
        model = _model_with_entry(entry)
        with patch('teaparty.proxy.approval_gate.random.random', return_value=1.0):
            decision = should_escalate(model, 'PLAN_ASSERT', 'test-project')
        self.assertEqual(decision.action, 'escalate')


# ── 15. Content-awareness checks ─────────────────────────────────────────────

class TestContentAwareness(DeterministicProxyTestCase):
    """Phase 1 and Phase 2a/2b content-awareness checks in should_escalate()."""

    def setUp(self):
        super().setUp()
        self._tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self._tmpdir, ignore_errors=True)
        super().tearDown()

    def _make_trained_entry(self, approve_count=10, differentials=None, question_patterns=None):
        entry = _make_entry(approve_count=approve_count, total_count=approve_count, ema_approval_rate=0.9)
        if differentials is not None:
            entry.differentials = differentials
        if question_patterns is not None:
            entry.question_patterns = question_patterns
        return entry

    def _write_artifact(self, text):
        path = os.path.join(self._tmpdir, 'artifact.md')
        Path(path).write_text(text)
        return path

    def test_length_anomaly_short_triggers_escalation(self):
        entry = self._make_trained_entry()
        entry.artifact_lengths = [1000] * 5
        path = self._write_artifact('a' * 200)
        model = _model_with_entry(entry)
        decision = should_escalate(model, entry.state, entry.task_type, artifact_path=path)
        self.assertEqual(decision.action, 'escalate')
        self.assertIn('short', decision.reasoning.lower())

    def test_length_anomaly_long_triggers_escalation(self):
        entry = self._make_trained_entry()
        entry.artifact_lengths = [500] * 5
        path = self._write_artifact('a' * 1200)
        model = _model_with_entry(entry)
        decision = should_escalate(model, entry.state, entry.task_type, artifact_path=path)
        self.assertEqual(decision.action, 'escalate')
        self.assertIn('long', decision.reasoning.lower())

    def test_novelty_detection_correction_keywords_trigger_escalation(self):
        diff = {
            'outcome': 'correct',
            'summary': 'error handling missing in export function',
            'reasoning': '',
            'timestamp': '2026-01-01',
        }
        entry = self._make_trained_entry(differentials=[diff])
        artifact_text = 'The export function processes data. Error handling has not been addressed.'
        path = self._write_artifact(artifact_text)
        model = _model_with_entry(entry)
        decision = should_escalate(model, entry.state, entry.task_type, artifact_path=path)
        self.assertEqual(decision.action, 'escalate')
        self.assertIn('correction', decision.reasoning.lower())

    def test_missing_artifact_path_degrades_gracefully(self):
        entry = self._make_trained_entry()
        model = _model_with_entry(entry)
        decision = should_escalate(model, entry.state, entry.task_type, artifact_path='')
        self.assertIn(decision.action, ('auto-approve', 'escalate'))

    def test_unreadable_artifact_degrades_gracefully(self):
        entry = self._make_trained_entry()
        model = _model_with_entry(entry)
        artifact_path = '/nonexistent/path/that/will/never/exist-proxy-test.md'
        decision = should_escalate(model, entry.state, entry.task_type, artifact_path=artifact_path)
        self.assertIn(decision.action, ('auto-approve', 'escalate'))

    def test_cold_start_suppresses_content_checks(self):
        entry = _make_entry(approve_count=2, total_count=2)  # below threshold of 5
        diff = {'outcome': 'correct', 'summary': 'error handling missing', 'reasoning': '', 'timestamp': '2026-01-01'}
        entry.differentials = [diff]
        path = self._write_artifact('error handling is implemented here')
        model = _model_with_entry(entry)
        decision = should_escalate(model, entry.state, entry.task_type, artifact_path=path)
        self.assertEqual(decision.action, 'escalate')
        self.assertIn('cold', decision.reasoning.lower())

    def test_content_check_fires_independently_of_high_confidence(self):
        entry = _make_entry(approve_count=20, total_count=20, ema_approval_rate=0.95)
        diff = {'outcome': 'correct', 'summary': 'error handling missing in export function', 'reasoning': '', 'timestamp': '2026-01-01'}
        entry.differentials = [diff]
        path = self._write_artifact('the export function processes errors')
        model = _model_with_entry(entry)
        decision = should_escalate(model, entry.state, entry.task_type, artifact_path=path)
        self.assertEqual(decision.action, 'escalate')
        self.assertIn('correction', decision.reasoning.lower())


# ── 16. Question pattern learning ─────────────────────────────────────────────

class TestQuestionPatternLearning(DeterministicProxyTestCase):
    """Phase 2b -- question pattern accumulation and triggering."""

    def setUp(self):
        super().setUp()
        self._tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self._tmpdir, ignore_errors=True)
        super().tearDown()

    def _write_artifact(self, text):
        path = os.path.join(self._tmpdir, 'artifact.md')
        Path(path).write_text(text)
        return path

    def test_question_pattern_recorded_after_record_outcome(self):
        model = _make_model()
        updated = record_outcome(
            model, 'PLAN_ASSERT', 'test-project', 'correct',
            question_patterns=[{
                'question': 'Did you handle errors?',
                'concern': 'error_handling',
                'reasoning': 'because silent failures are worse than noisy ones',
                'disposition': 'correct',
                'timestamp': '2026-01-01',
            }],
        )
        key = 'PLAN_ASSERT|test-project'
        raw = updated.entries[key]
        qps = raw.get('question_patterns', [])
        self.assertEqual(len(qps), 1)
        self.assertEqual(qps[0]['concern'], 'error_handling')

    def test_phase_2b_fires_when_artifact_lacks_concern_keywords(self):
        qp = {
            'question': 'Did you handle errors?',
            'concern': 'error_handling',
            'reasoning': '',
            'disposition': 'correct',
            'timestamp': '2026-01-01',
        }
        entry = _make_entry(approve_count=10, total_count=10, ema_approval_rate=0.9)
        entry.question_patterns = [qp, qp]  # 2 occurrences >= QUESTION_PATTERN_MIN_OCCURRENCES
        path = self._write_artifact('The function processes the input and returns the result.')
        model = _model_with_entry(entry)
        decision = should_escalate(model, entry.state, entry.task_type, artifact_path=path)
        self.assertEqual(decision.action, 'escalate')
        self.assertIn('error_handling', decision.reasoning)

    def test_phase_2b_includes_reasoning_in_escalation_message(self):
        reasoning_text = 'silent failures are worse than noisy ones'
        qp = {
            'question': 'Did you handle errors?',
            'concern': 'error_handling',
            'reasoning': reasoning_text,
            'disposition': 'correct',
            'timestamp': '2026-01-01',
        }
        entry = _make_entry(approve_count=10, total_count=10, ema_approval_rate=0.9)
        entry.question_patterns = [qp, qp]
        path = self._write_artifact('The function processes the input and returns the result.')
        model = _model_with_entry(entry)
        decision = should_escalate(model, entry.state, entry.task_type, artifact_path=path)
        self.assertEqual(decision.action, 'escalate')
        self.assertIn(reasoning_text, decision.reasoning)

    def test_extract_question_patterns_captures_reasoning_from_because_clause(self):
        dialog = 'You should handle errors because silent failures are worse than noisy ones'
        patterns = _extract_question_patterns(dialog, 'correct')
        self.assertTrue(len(patterns) > 0)
        error_patterns = [p for p in patterns if p.get('concern') == 'error_handling']
        self.assertTrue(len(error_patterns) > 0)
        self.assertTrue(len(error_patterns[0].get('reasoning', '')) > 0)


# ── 17. [CONFIRM:] marker escalation ──────────────────────────────────────────

class TestConfirmMarkerEscalation(DeterministicProxyTestCase):
    """Proxy flag awareness: [CONFIRM:] markers in artifacts force escalation
    regardless of confidence level, per intent-team-improvements backlog."""

    def setUp(self):
        super().setUp()
        self._tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self._tmpdir, ignore_errors=True)
        super().tearDown()

    def _write_artifact(self, text):
        path = os.path.join(self._tmpdir, 'artifact.md')
        Path(path).write_text(text)
        return path

    def _make_trained_model(self, **entry_kw):
        """Build a model with a trained entry that would normally auto-approve."""
        entry = _make_entry(
            approve_count=entry_kw.get('approve_count', 10),
            total_count=entry_kw.get('total_count', 10),
            ema_approval_rate=entry_kw.get('ema_approval_rate', 0.9),
        )
        return _model_with_entry(entry), entry

    def test_single_confirm_marker_forces_escalation(self):
        """An artifact with one [CONFIRM:] marker must escalate."""
        model, entry = self._make_trained_model()
        path = self._write_artifact(
            "## Intent\nBuild the widget.\n\n"
            "[CONFIRM: Should the widget support dark mode?]\n"
        )
        decision = should_escalate(model, entry.state, entry.task_type, artifact_path=path)
        self.assertEqual(decision.action, 'escalate')
        self.assertIn('CONFIRM', decision.reasoning)
        self.assertIn('1', decision.reasoning)  # "1 unresolved [CONFIRM:]"

    def test_multiple_confirm_markers_reported(self):
        """All [CONFIRM:] markers are listed in the reasoning."""
        model, entry = self._make_trained_model()
        path = self._write_artifact(
            "## Intent\nBuild the widget.\n\n"
            "[CONFIRM: Should the widget support dark mode?]\n"
            "[CONFIRM: Is the target audience developers or designers?]\n"
        )
        decision = should_escalate(model, entry.state, entry.task_type, artifact_path=path)
        self.assertEqual(decision.action, 'escalate')
        self.assertIn('2', decision.reasoning)  # "2 unresolved [CONFIRM:]"
        self.assertIn('dark mode', decision.reasoning)
        self.assertIn('target audience', decision.reasoning)

    def test_no_confirm_marker_allows_auto_approve(self):
        """A clean artifact with no markers auto-approves when confidence is high."""
        model, entry = self._make_trained_model()
        path = self._write_artifact(
            "## Intent\nBuild the widget.\n\n"
            "All questions have been resolved.\n"
        )
        decision = should_escalate(model, entry.state, entry.task_type, artifact_path=path)
        self.assertEqual(decision.action, 'auto-approve')

    def test_confirm_marker_takes_priority_over_content_checks(self):
        """[CONFIRM:] detection fires before length anomaly or novelty checks."""
        entry = _make_entry(
            approve_count=10, total_count=10, ema_approval_rate=0.9,
        )
        # Set up artifact lengths so a short artifact would trigger length anomaly
        entry.artifact_lengths = [1000] * 5
        model = _model_with_entry(entry)
        # Artifact is very short (would trigger length anomaly) AND has a CONFIRM marker
        path = self._write_artifact("[CONFIRM: Is this correct?]")
        decision = should_escalate(model, entry.state, entry.task_type, artifact_path=path)
        self.assertEqual(decision.action, 'escalate')
        # Should mention CONFIRM, not length anomaly — CONFIRM fires first
        self.assertIn('CONFIRM', decision.reasoning)
        self.assertNotIn('short', decision.reasoning.lower())


if __name__ == '__main__':
    unittest.main()
