#!/usr/bin/env python3
"""Tests for the experimentation harness (issue #129).

Covers:
 1. EventCollector — event indexing, JSONL persistence, summarization
 2. PatternProvider — seeded reproducibility, decision boundary, reset
 3. ScriptedProvider — cursor advance, exhaustion (last decision repeats)
 4. AlwaysApproveProvider — baseline behavior
 5. make_provider factory — all modes + error on unknown mode
 6. ExperimentConfig — results_dir computation, results_base override
 7. CorpusConfig — YAML loading, make_config overrides, unknown override behavior
 8. analyze.py — descriptive stats (sample variance), Cohen's d, condition summary
 9. suppress_backtracks — Orchestrator skips backtrack loops when flag is set
10. report.py — markdown_table formatting

Uses unittest.TestCase with _make_*() helpers per project conventions.
"""
import asyncio
import json
import math
import os
import random
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

# Add repo root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from experiments.collector import EventCollector, PhaseTimings, TokenUsage
from experiments.config import ExperimentConfig, TaskDefinition, CorpusConfig, load_corpus
from experiments.input_providers import (
    AlwaysApproveProvider,
    PatternProvider,
    ScriptedProvider,
    make_provider,
)
from experiments.analyze import (
    _cohens_d,
    _descriptive_stats,
    _extract_metric,
    analyze_experiment,
    condition_summary,
    group_by_condition,
    load_all_runs,
)
from experiments.report import markdown_table, format_stats

from projects.POC.orchestrator.events import Event, EventBus, EventType, InputRequest


# ── Helpers ───────────────────────────────────────────────────────────────────

def _run(coro):
    """Run a coroutine synchronously for testing."""
    return asyncio.run(coro)


def _make_event(
    event_type: EventType = EventType.LOG,
    data: dict | None = None,
    session_id: str = 'test-session',
    timestamp: float = 0.0,
) -> Event:
    return Event(
        type=event_type,
        data=data or {},
        session_id=session_id,
        timestamp=timestamp or __import__('time').time(),
    )


def _make_input_request(
    state: str = 'INTENT_ASSERT',
    type_: str = 'approval',
) -> InputRequest:
    return InputRequest(type=type_, state=state)


def _make_metrics(
    condition: str = 'ctrl',
    backtrack_count: int = 0,
    elapsed_seconds: float = 10.0,
    terminal_state: str = 'COMPLETED_WORK',
    proxy_mean_confidence: float = 0.75,
    proxy_auto_approvals: int = 3,
    proxy_escalations: int = 1,
    state_transitions: int = 8,
) -> dict:
    return {
        'experiment': 'test-exp',
        'condition': condition,
        'run_id': 'run-001',
        'terminal_state': terminal_state,
        'backtrack_count': backtrack_count,
        'elapsed_seconds': elapsed_seconds,
        'state_transitions': state_transitions,
        'proxy': {
            'total_decisions': proxy_auto_approvals + proxy_escalations,
            'auto_approvals': proxy_auto_approvals,
            'escalations': proxy_escalations,
            'mean_confidence': proxy_mean_confidence,
        },
        'input_responses': 2,
        'total_events': 15,
    }


# ── EventCollector ────────────────────────────────────────────────────────────

class TestEventCollector(unittest.TestCase):
    """EventCollector event indexing, JSONL persistence, and summarization."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix='exp_test_')

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _make_collector(self, **kwargs):
        defaults = dict(
            output_dir=self.tmpdir,
            experiment='test-exp',
            condition='ctrl',
            run_id='run-001',
        )
        defaults.update(kwargs)
        return EventCollector(**defaults)

    def test_state_changed_event_indexed(self):
        """STATE_CHANGED events are captured in _state_transitions."""
        collector = self._make_collector()
        event = _make_event(
            EventType.STATE_CHANGED,
            data={
                'previous_state': 'PROPOSAL',
                'state': 'INTENT_ASSERT',
                'action': 'propose',
                'phase': 'intent',
                'backtrack_count': 0,
            },
        )
        _run(collector.on_event(event))
        self.assertEqual(len(collector._state_transitions), 1)
        self.assertEqual(collector._state_transitions[0]['state'], 'INTENT_ASSERT')

    def test_phase_timing_tracked(self):
        """PHASE_STARTED and PHASE_COMPLETED events produce correct duration."""
        collector = self._make_collector()

        start_event = _make_event(
            EventType.PHASE_STARTED,
            data={'phase': 'intent', 'stream_file': '.intent-stream.jsonl'},
            timestamp=1000.0,
        )
        end_event = _make_event(
            EventType.PHASE_COMPLETED,
            data={'phase': 'intent', 'state': 'INTENT'},
            timestamp=1005.0,
        )
        _run(collector.on_event(start_event))
        _run(collector.on_event(end_event))

        self.assertIn('intent', collector._phase_timings)
        self.assertAlmostEqual(collector._phase_timings['intent'].duration, 5.0)

    def test_proxy_decision_indexed(self):
        """LOG events with category=proxy_decision are captured."""
        collector = self._make_collector()
        event = _make_event(
            EventType.LOG,
            data={
                'category': 'proxy_decision',
                'state': 'INTENT_ASSERT',
                'decision': 'auto-approve',
                'confidence': 0.92,
                'reasoning': 'High confidence',
            },
        )
        _run(collector.on_event(event))
        self.assertEqual(len(collector._proxy_decisions), 1)
        self.assertEqual(collector._proxy_decisions[0]['decision'], 'auto-approve')
        self.assertAlmostEqual(collector._proxy_decisions[0]['confidence'], 0.92)

    def test_proxy_decision_captures_richer_fields(self):
        """proxy_decision events capture confidence_laplace, confidence_ema, exploration_forced."""
        collector = self._make_collector()
        event = _make_event(
            EventType.LOG,
            data={
                'category': 'proxy_decision',
                'state': 'PLAN_ASSERT',
                'decision': 'escalate',
                'confidence': 0.75,
                'confidence_laplace': 0.80,
                'confidence_ema': 0.75,
                'exploration_forced': True,
                'reasoning': 'Exploration escalation',
            },
        )
        _run(collector.on_event(event))
        d = collector._proxy_decisions[0]
        self.assertAlmostEqual(d['confidence_laplace'], 0.80)
        self.assertAlmostEqual(d['confidence_ema'], 0.75)
        self.assertTrue(d['exploration_forced'])

    def test_summarize_proxy_richer_metrics(self):
        """summarize() includes exploration_escalations, mean_confidence_laplace, mean_confidence_ema."""
        collector = self._make_collector()
        for i, (decision, expl, laplace, ema) in enumerate([
            ('auto-approve', False, 0.90, 0.85),
            ('escalate', True, 0.88, 0.82),
            ('escalate', False, 0.60, 0.55),
        ]):
            _run(collector.on_event(_make_event(
                EventType.LOG,
                data={
                    'category': 'proxy_decision',
                    'state': 'PLAN_ASSERT',
                    'decision': decision,
                    'confidence': min(laplace, ema),
                    'confidence_laplace': laplace,
                    'confidence_ema': ema,
                    'exploration_forced': expl,
                },
            )))

        metrics = collector.summarize()
        proxy = metrics['proxy']
        self.assertEqual(proxy['exploration_escalations'], 1)
        self.assertAlmostEqual(proxy['mean_confidence_laplace'], (0.90 + 0.88 + 0.60) / 3, places=4)
        self.assertAlmostEqual(proxy['mean_confidence_ema'], (0.85 + 0.82 + 0.55) / 3, places=4)

    def test_session_completed_captures_terminal_state(self):
        """SESSION_COMPLETED sets terminal_state and backtrack_count."""
        collector = self._make_collector()
        event = _make_event(
            EventType.SESSION_COMPLETED,
            data={'terminal_state': 'COMPLETED_WORK', 'backtrack_count': 2},
        )
        _run(collector.on_event(event))
        self.assertEqual(collector._terminal_state, 'COMPLETED_WORK')
        self.assertEqual(collector._backtrack_count, 2)

    def test_events_written_to_jsonl(self):
        """Events are persisted to events.jsonl in append mode."""
        collector = self._make_collector()
        event1 = _make_event(EventType.LOG, data={'msg': 'hello'})
        event2 = _make_event(EventType.LOG, data={'msg': 'world'})
        _run(collector.on_event(event1))
        _run(collector.on_event(event2))

        events_path = os.path.join(self.tmpdir, 'events.jsonl')
        self.assertTrue(os.path.isfile(events_path))

        with open(events_path) as f:
            lines = [line.strip() for line in f if line.strip()]
        self.assertEqual(len(lines), 2)

        record1 = json.loads(lines[0])
        self.assertEqual(record1['experiment'], 'test-exp')
        self.assertEqual(record1['condition'], 'ctrl')
        self.assertEqual(record1['msg'], 'hello')

    def test_write_metrics_creates_json(self):
        """write_metrics() creates a valid metrics.json file."""
        collector = self._make_collector()
        event = _make_event(
            EventType.SESSION_COMPLETED,
            data={'terminal_state': 'COMPLETED_WORK', 'backtrack_count': 1},
        )
        _run(collector.on_event(event))

        path = collector.write_metrics()
        self.assertTrue(os.path.isfile(path))

        with open(path) as f:
            metrics = json.load(f)
        self.assertEqual(metrics['terminal_state'], 'COMPLETED_WORK')
        self.assertEqual(metrics['backtrack_count'], 1)
        self.assertEqual(metrics['experiment'], 'test-exp')

    def test_summarize_proxy_mean_confidence(self):
        """summarize() computes correct mean confidence from proxy decisions."""
        collector = self._make_collector()
        for conf in [0.8, 0.9, 1.0]:
            event = _make_event(
                EventType.LOG,
                data={
                    'category': 'proxy_decision',
                    'state': 'PLAN_ASSERT',
                    'decision': 'auto-approve',
                    'confidence': conf,
                },
            )
            _run(collector.on_event(event))

        metrics = collector.summarize()
        self.assertAlmostEqual(metrics['proxy']['mean_confidence'], 0.9, places=4)
        self.assertEqual(metrics['proxy']['auto_approvals'], 3)

    def test_input_received_indexed(self):
        """INPUT_RECEIVED events are captured."""
        collector = self._make_collector()
        event = _make_event(
            EventType.INPUT_RECEIVED,
            data={'response': 'approve'},
        )
        _run(collector.on_event(event))
        self.assertEqual(len(collector._input_responses), 1)

    def test_stream_data_result_success_captures_tokens(self):
        """STREAM_DATA with result/success captures token usage and cost."""
        collector = self._make_collector()

        # Start a phase so tokens are attributed
        _run(collector.on_event(_make_event(
            EventType.PHASE_STARTED,
            data={'phase': 'intent'},
            timestamp=1000.0,
        )))

        # Simulate a result/success stream event
        _run(collector.on_event(_make_event(
            EventType.STREAM_DATA,
            data={
                'type': 'result',
                'subtype': 'success',
                'total_cost_usd': 0.0325,
                'num_turns': 5,
                'usage': {
                    'input_tokens': 1500,
                    'output_tokens': 800,
                    'cache_read_input_tokens': 200,
                    'cache_creation_input_tokens': 50,
                },
            },
        )))

        # Session-level tokens
        self.assertEqual(collector._session_tokens.input_tokens, 1500)
        self.assertEqual(collector._session_tokens.output_tokens, 800)
        self.assertEqual(collector._session_tokens.cache_read_tokens, 200)
        self.assertEqual(collector._session_tokens.cache_creation_tokens, 50)
        self.assertAlmostEqual(collector._session_tokens.cost_usd, 0.0325)
        self.assertEqual(collector._session_tokens.num_turns, 5)
        self.assertEqual(collector._session_tokens.invocations, 1)

        # Phase-level tokens
        self.assertIn('intent', collector._phase_tokens)
        self.assertEqual(collector._phase_tokens['intent'].input_tokens, 1500)
        self.assertEqual(collector._phase_tokens['intent'].output_tokens, 800)

    def test_stream_data_accumulates_across_invocations(self):
        """Multiple result/success events accumulate tokens and cost."""
        collector = self._make_collector()

        _run(collector.on_event(_make_event(
            EventType.PHASE_STARTED, data={'phase': 'planning'}, timestamp=1000.0,
        )))
        _run(collector.on_event(_make_event(
            EventType.STREAM_DATA,
            data={
                'type': 'result', 'subtype': 'success',
                'total_cost_usd': 0.01, 'num_turns': 3,
                'usage': {'input_tokens': 500, 'output_tokens': 200},
            },
        )))
        _run(collector.on_event(_make_event(
            EventType.STREAM_DATA,
            data={
                'type': 'result', 'subtype': 'success',
                'total_cost_usd': 0.02, 'num_turns': 4,
                'usage': {'input_tokens': 700, 'output_tokens': 300},
            },
        )))

        self.assertEqual(collector._session_tokens.input_tokens, 1200)
        self.assertEqual(collector._session_tokens.output_tokens, 500)
        self.assertAlmostEqual(collector._session_tokens.cost_usd, 0.03)
        self.assertEqual(collector._session_tokens.num_turns, 7)
        self.assertEqual(collector._session_tokens.invocations, 2)

    def test_stream_data_task_notification_captures_usage(self):
        """STREAM_DATA with system/task_notification captures token usage."""
        collector = self._make_collector()

        _run(collector.on_event(_make_event(
            EventType.PHASE_STARTED, data={'phase': 'execution'}, timestamp=1000.0,
        )))
        _run(collector.on_event(_make_event(
            EventType.STREAM_DATA,
            data={
                'type': 'system', 'subtype': 'task_notification',
                'usage': {'input_tokens': 300, 'output_tokens': 100},
            },
        )))

        self.assertEqual(collector._session_tokens.input_tokens, 300)
        self.assertEqual(collector._session_tokens.output_tokens, 100)
        self.assertEqual(collector._phase_tokens['execution'].input_tokens, 300)

    def test_stream_data_no_phase_still_tracks_session_tokens(self):
        """Token data outside a phase still accumulates at session level."""
        collector = self._make_collector()

        _run(collector.on_event(_make_event(
            EventType.STREAM_DATA,
            data={
                'type': 'result', 'subtype': 'success',
                'total_cost_usd': 0.05, 'num_turns': 2,
                'usage': {'input_tokens': 1000, 'output_tokens': 500},
            },
        )))

        self.assertEqual(collector._session_tokens.input_tokens, 1000)
        self.assertAlmostEqual(collector._session_tokens.cost_usd, 0.05)
        # No phase tokens since no phase was started
        self.assertEqual(len(collector._phase_tokens), 0)

    def test_stream_data_per_phase_attribution(self):
        """Tokens are attributed to the correct phase when phases change."""
        collector = self._make_collector()

        # Intent phase
        _run(collector.on_event(_make_event(
            EventType.PHASE_STARTED, data={'phase': 'intent'}, timestamp=1000.0,
        )))
        _run(collector.on_event(_make_event(
            EventType.STREAM_DATA,
            data={
                'type': 'result', 'subtype': 'success',
                'total_cost_usd': 0.01, 'num_turns': 2,
                'usage': {'input_tokens': 400, 'output_tokens': 100},
            },
        )))
        _run(collector.on_event(_make_event(
            EventType.PHASE_COMPLETED, data={'phase': 'intent'}, timestamp=1010.0,
        )))

        # Planning phase
        _run(collector.on_event(_make_event(
            EventType.PHASE_STARTED, data={'phase': 'planning'}, timestamp=1010.0,
        )))
        _run(collector.on_event(_make_event(
            EventType.STREAM_DATA,
            data={
                'type': 'result', 'subtype': 'success',
                'total_cost_usd': 0.03, 'num_turns': 5,
                'usage': {'input_tokens': 1200, 'output_tokens': 600},
            },
        )))

        # Check per-phase attribution
        self.assertEqual(collector._phase_tokens['intent'].input_tokens, 400)
        self.assertEqual(collector._phase_tokens['planning'].input_tokens, 1200)

        # Session totals
        self.assertEqual(collector._session_tokens.input_tokens, 1600)
        self.assertEqual(collector._session_tokens.output_tokens, 700)
        self.assertAlmostEqual(collector._session_tokens.cost_usd, 0.04)

    def test_summarize_includes_token_accounting(self):
        """summarize() includes tokens dict with session totals and per-phase."""
        collector = self._make_collector()

        _run(collector.on_event(_make_event(
            EventType.PHASE_STARTED, data={'phase': 'intent'}, timestamp=1000.0,
        )))
        _run(collector.on_event(_make_event(
            EventType.STREAM_DATA,
            data={
                'type': 'result', 'subtype': 'success',
                'total_cost_usd': 0.025, 'num_turns': 3,
                'usage': {
                    'input_tokens': 1000,
                    'output_tokens': 500,
                    'cache_read_input_tokens': 100,
                    'cache_creation_input_tokens': 20,
                },
            },
        )))

        metrics = collector.summarize()
        self.assertIn('tokens', metrics)
        tokens = metrics['tokens']

        self.assertEqual(tokens['input_tokens'], 1000)
        self.assertEqual(tokens['output_tokens'], 500)
        self.assertEqual(tokens['total_tokens'], 1500)
        self.assertEqual(tokens['cache_read_tokens'], 100)
        self.assertEqual(tokens['cache_creation_tokens'], 20)
        self.assertAlmostEqual(tokens['cost_usd'], 0.025)
        self.assertEqual(tokens['num_turns'], 3)
        self.assertEqual(tokens['invocations'], 1)

        # Per-phase breakdown
        self.assertIn('by_phase', tokens)
        self.assertIn('intent', tokens['by_phase'])
        self.assertEqual(tokens['by_phase']['intent']['input_tokens'], 1000)

    def test_stream_data_ignores_irrelevant_events(self):
        """STREAM_DATA events without result/success or task_notification are ignored."""
        collector = self._make_collector()

        # assistant event (not token-relevant)
        _run(collector.on_event(_make_event(
            EventType.STREAM_DATA,
            data={'type': 'assistant', 'message': {'content': []}},
        )))

        # system/init (not token-relevant)
        _run(collector.on_event(_make_event(
            EventType.STREAM_DATA,
            data={'type': 'system', 'subtype': 'init', 'session_id': 'abc'},
        )))

        # system/task_progress (skipped — too noisy, only capture final)
        _run(collector.on_event(_make_event(
            EventType.STREAM_DATA,
            data={
                'type': 'system', 'subtype': 'task_progress',
                'usage': {'input_tokens': 999, 'output_tokens': 999},
            },
        )))

        self.assertEqual(collector._session_tokens.input_tokens, 0)
        self.assertEqual(collector._session_tokens.output_tokens, 0)


# ── TokenUsage ───────────────────────────────────────────────────────────────

class TestTokenUsage(unittest.TestCase):
    """TokenUsage dataclass accumulation and serialization."""

    def test_add_usage_accumulates(self):
        """add_usage() accumulates tokens, cost, and turns."""
        tu = TokenUsage()
        tu.add_usage({'input_tokens': 100, 'output_tokens': 50}, cost=0.01, turns=2)
        tu.add_usage({'input_tokens': 200, 'output_tokens': 75}, cost=0.02, turns=3)
        self.assertEqual(tu.input_tokens, 300)
        self.assertEqual(tu.output_tokens, 125)
        self.assertAlmostEqual(tu.cost_usd, 0.03)
        self.assertEqual(tu.num_turns, 5)
        self.assertEqual(tu.invocations, 2)

    def test_add_usage_handles_missing_fields(self):
        """add_usage() handles missing fields in usage dict gracefully."""
        tu = TokenUsage()
        tu.add_usage({})
        self.assertEqual(tu.input_tokens, 0)
        self.assertEqual(tu.output_tokens, 0)
        self.assertEqual(tu.cache_read_tokens, 0)
        self.assertEqual(tu.invocations, 1)

    def test_to_dict_includes_total(self):
        """to_dict() includes computed total_tokens field."""
        tu = TokenUsage()
        tu.add_usage({'input_tokens': 500, 'output_tokens': 200}, cost=0.015, turns=3)
        d = tu.to_dict()
        self.assertEqual(d['total_tokens'], 700)
        self.assertEqual(d['input_tokens'], 500)
        self.assertEqual(d['output_tokens'], 200)
        self.assertAlmostEqual(d['cost_usd'], 0.015)
        self.assertEqual(d['invocations'], 1)

    def test_to_dict_rounds_cost(self):
        """to_dict() rounds cost to 6 decimal places."""
        tu = TokenUsage()
        tu.add_usage({}, cost=0.00123456789)
        d = tu.to_dict()
        self.assertEqual(d['cost_usd'], 0.001235)


# ── PhaseTimings ──────────────────────────────────────────────────────────────

class TestPhaseTimings(unittest.TestCase):
    """PhaseTimings dataclass edge cases."""

    def test_duration_when_both_set(self):
        pt = PhaseTimings(phase='intent', start=100.0, end=105.0)
        self.assertAlmostEqual(pt.duration, 5.0)

    def test_duration_zero_when_end_missing(self):
        pt = PhaseTimings(phase='intent', start=100.0)
        self.assertEqual(pt.duration, 0.0)

    def test_duration_zero_when_start_missing(self):
        pt = PhaseTimings(phase='intent', end=105.0)
        self.assertEqual(pt.duration, 0.0)


# ── Input Providers ───────────────────────────────────────────────────────────

class TestAlwaysApproveProvider(unittest.TestCase):
    """AlwaysApproveProvider returns 'approve' for every state."""

    def test_approves_intent_assert(self):
        provider = AlwaysApproveProvider()
        result = _run(provider(_make_input_request('INTENT_ASSERT')))
        self.assertEqual(result, 'approve')

    def test_approves_plan_assert(self):
        provider = AlwaysApproveProvider()
        result = _run(provider(_make_input_request('PLAN_ASSERT')))
        self.assertEqual(result, 'approve')

    def test_approves_merge_conflict(self):
        provider = AlwaysApproveProvider()
        result = _run(provider(_make_input_request('MERGE_CONFLICT', type_='merge_conflict')))
        self.assertEqual(result, 'approve')


class TestScriptedProvider(unittest.TestCase):
    """ScriptedProvider replays decisions from a per-state script."""

    def _make_provider(self, script=None):
        return ScriptedProvider(script or {
            'INTENT_ASSERT': ['approve'],
            'PLAN_ASSERT': ['correct: add tests', 'approve'],
        })

    def test_follows_script_in_order(self):
        provider = self._make_provider()
        r1 = _run(provider(_make_input_request('PLAN_ASSERT')))
        r2 = _run(provider(_make_input_request('PLAN_ASSERT')))
        self.assertEqual(r1, 'correct: add tests')
        self.assertEqual(r2, 'approve')

    def test_repeats_last_decision_when_exhausted(self):
        """After all scripted decisions are used, the last one repeats."""
        provider = self._make_provider()
        _run(provider(_make_input_request('PLAN_ASSERT')))  # correct
        _run(provider(_make_input_request('PLAN_ASSERT')))  # approve
        r3 = _run(provider(_make_input_request('PLAN_ASSERT')))  # still approve
        self.assertEqual(r3, 'approve')

    def test_unscripted_state_defaults_to_approve(self):
        provider = self._make_provider()
        result = _run(provider(_make_input_request('WORK_ASSERT')))
        self.assertEqual(result, 'approve')

    def test_reset_clears_cursors(self):
        provider = self._make_provider()
        _run(provider(_make_input_request('PLAN_ASSERT')))  # advance cursor
        provider.reset()
        result = _run(provider(_make_input_request('PLAN_ASSERT')))
        self.assertEqual(result, 'correct: add tests')  # back to first

    def test_independent_cursors_per_state(self):
        """Each state has its own cursor."""
        provider = self._make_provider()
        r_intent = _run(provider(_make_input_request('INTENT_ASSERT')))
        r_plan = _run(provider(_make_input_request('PLAN_ASSERT')))
        self.assertEqual(r_intent, 'approve')
        self.assertEqual(r_plan, 'correct: add tests')


class TestPatternProvider(unittest.TestCase):
    """PatternProvider uses seeded RNG for reproducible stochastic decisions."""

    def test_same_seed_produces_identical_sequence(self):
        """Two providers with the same seed produce the same decisions."""
        p1 = PatternProvider(rates={'S': 0.5}, seed=42)
        p2 = PatternProvider(rates={'S': 0.5}, seed=42)
        req = _make_input_request('S')

        decisions1 = [_run(p1(req)) for _ in range(10)]
        decisions2 = [_run(p2(req)) for _ in range(10)]
        self.assertEqual(decisions1, decisions2)

    def test_decision_boundary_explicit(self):
        """Verify the decision boundary against hand-computed RNG values.

        random.Random(42).random() produces:
          0.6394... → with rate=0.5: 0.6394 >= 0.5 → correct
          0.0250... → with rate=0.5: 0.0250 <  0.5 → approve
        """
        rng = random.Random(42)
        first_roll = rng.random()   # 0.6394...
        second_roll = rng.random()  # 0.0250...

        provider = PatternProvider(rates={'S': 0.5}, seed=42)
        req = _make_input_request('S')

        r1 = _run(provider(req))
        r2 = _run(provider(req))

        # first_roll ≈ 0.639 >= 0.5 → correction
        self.assertTrue(r1.startswith('correct:'), f'Expected correction, got {r1!r} (roll={first_roll:.4f})')
        # second_roll ≈ 0.025 < 0.5 → approve
        self.assertEqual(r2, 'approve', f'Expected approve (roll={second_roll:.4f})')

    def test_rate_zero_always_rejects(self):
        provider = PatternProvider(rates={'S': 0.0}, seed=42)
        req = _make_input_request('S')
        for _ in range(10):
            result = _run(provider(req))
            self.assertTrue(result.startswith('correct:'))

    def test_rate_one_always_approves(self):
        provider = PatternProvider(rates={'S': 1.0}, seed=42)
        req = _make_input_request('S')
        for _ in range(10):
            self.assertEqual(_run(provider(req)), 'approve')

    def test_default_rate_used_for_unspecified_state(self):
        provider = PatternProvider(rates={}, seed=42, default_rate=1.0)
        result = _run(provider(_make_input_request('UNKNOWN_STATE')))
        self.assertEqual(result, 'approve')

    def test_reset_with_same_seed_replays(self):
        provider = PatternProvider(rates={'S': 0.5}, seed=42)
        req = _make_input_request('S')
        first_run = [_run(provider(req)) for _ in range(5)]

        provider.reset(seed=42)
        second_run = [_run(provider(req)) for _ in range(5)]
        self.assertEqual(first_run, second_run)

    def test_reset_without_seed_clears_log_only(self):
        """reset() without a seed clears the decision log but continues the RNG sequence."""
        provider = PatternProvider(rates={'S': 0.5}, seed=42)
        req = _make_input_request('S')
        _run(provider(req))
        _run(provider(req))
        self.assertEqual(len(provider.decisions), 2)

        provider.reset()  # No seed → clears log, keeps RNG state
        self.assertEqual(len(provider.decisions), 0)

    def test_decisions_log_records_rolls(self):
        provider = PatternProvider(rates={'S': 0.5}, seed=42)
        _run(provider(_make_input_request('S')))
        self.assertEqual(len(provider.decisions), 1)
        entry = provider.decisions[0]
        self.assertEqual(entry['state'], 'S')
        self.assertEqual(entry['rate'], 0.5)
        self.assertIn('roll', entry)
        self.assertIn('decision', entry)

    def test_correction_feedback_customizable(self):
        provider = PatternProvider(
            rates={'S': 0.0},
            seed=42,
            correction_feedback='add tests and docs',
        )
        result = _run(provider(_make_input_request('S')))
        self.assertEqual(result, 'correct: add tests and docs')


class TestMakeProviderFactory(unittest.TestCase):
    """make_provider() factory dispatches correctly."""

    def test_auto_approve_mode(self):
        provider = make_provider('auto-approve')
        self.assertIsInstance(provider, AlwaysApproveProvider)

    def test_scripted_mode(self):
        provider = make_provider('scripted', script={'S': ['approve']})
        self.assertIsInstance(provider, ScriptedProvider)

    def test_scripted_mode_requires_script(self):
        with self.assertRaises(ValueError):
            make_provider('scripted')

    def test_pattern_mode(self):
        provider = make_provider('pattern', rates={'S': 0.5}, seed=99)
        self.assertIsInstance(provider, PatternProvider)

    def test_unknown_mode_raises(self):
        with self.assertRaises(ValueError) as ctx:
            make_provider('unknown-mode')
        self.assertIn('unknown-mode', str(ctx.exception))


# ── ExperimentConfig ──────────────────────────────────────────────────────────

class TestExperimentConfig(unittest.TestCase):
    """ExperimentConfig dataclass and results_dir computation."""

    def _make_config(self, **overrides):
        defaults = dict(
            experiment='test-exp',
            condition='ctrl',
            task='Do the thing',
            task_id='t-001',
        )
        defaults.update(overrides)
        return ExperimentConfig(**defaults)

    def test_results_dir_default_layout(self):
        """Default results_dir is experiments/results/<experiment>/<condition>/<task_id>."""
        cfg = self._make_config()
        self.assertTrue(cfg.results_dir.endswith('results/test-exp/ctrl/t-001'))

    def test_results_dir_with_explicit_base(self):
        cfg = self._make_config(results_base='/tmp/my-results')
        self.assertEqual(cfg.results_dir, '/tmp/my-results/test-exp/ctrl/t-001')

    def test_default_values(self):
        cfg = self._make_config()
        self.assertEqual(cfg.project, 'POC')
        self.assertFalse(cfg.flat)
        self.assertFalse(cfg.skip_intent)
        self.assertTrue(cfg.backtracks_enabled)
        self.assertEqual(cfg.input_mode, 'pattern')
        self.assertEqual(cfg.approval_seed, 42)
        self.assertIsNone(cfg.regret_weight)


# ── CorpusConfig ──────────────────────────────────────────────────────────────

class TestCorpusConfig(unittest.TestCase):
    """CorpusConfig and YAML loading."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix='corpus_test_')

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write_corpus_yaml(self, content: str) -> str:
        path = os.path.join(self.tmpdir, 'test-corpus.yaml')
        with open(path, 'w') as f:
            f.write(content)
        return path

    def test_load_corpus_basic(self):
        path = self._write_corpus_yaml("""
experiment: test-exp
default_condition: ctrl
tasks:
  - id: t-001
    text: "Task one"
    tier: simple
  - id: t-002
    text: "Task two"
""")
        corpus = load_corpus(path)
        self.assertEqual(corpus.experiment, 'test-exp')
        self.assertEqual(len(corpus.tasks), 2)
        self.assertEqual(corpus.tasks[0].id, 't-001')
        self.assertEqual(corpus.tasks[0].tier, 'simple')
        self.assertEqual(corpus.tasks[1].tier, 'medium')  # default tier

    def test_load_corpus_with_defaults(self):
        path = self._write_corpus_yaml("""
experiment: proxy-conv
default_condition: dual-signal
default_input_mode: pattern
default_approval_rates:
  INTENT_ASSERT: 0.95
  PLAN_ASSERT: 0.80
default_approval_seed: 99
default_rate: 0.9
tasks:
  - id: pc-001
    text: "Add health check"
""")
        corpus = load_corpus(path)
        self.assertEqual(corpus.default_condition, 'dual-signal')
        self.assertEqual(corpus.default_approval_seed, 99)
        self.assertAlmostEqual(corpus.default_approval_rates['PLAN_ASSERT'], 0.80)

    def test_make_config_uses_corpus_defaults(self):
        corpus = CorpusConfig(
            experiment='test-exp',
            default_condition='ctrl',
            default_input_mode='auto-approve',
            default_approval_seed=99,
            tasks=[TaskDefinition(id='t-001', text='Do it')],
        )
        cfg = corpus.make_config(corpus.tasks[0])
        self.assertEqual(cfg.experiment, 'test-exp')
        self.assertEqual(cfg.condition, 'ctrl')
        self.assertEqual(cfg.input_mode, 'auto-approve')
        self.assertEqual(cfg.approval_seed, 99)
        self.assertEqual(cfg.task, 'Do it')
        self.assertEqual(cfg.task_id, 't-001')

    def test_make_config_condition_override(self):
        corpus = CorpusConfig(
            experiment='test-exp',
            default_condition='ctrl',
            tasks=[TaskDefinition(id='t-001', text='Do it')],
        )
        cfg = corpus.make_config(corpus.tasks[0], condition='treatment')
        self.assertEqual(cfg.condition, 'treatment')

    def test_make_config_passes_known_overrides(self):
        corpus = CorpusConfig(
            experiment='test-exp',
            tasks=[TaskDefinition(id='t-001', text='Do it')],
        )
        cfg = corpus.make_config(
            corpus.tasks[0],
            flat=True,
            skip_intent=True,
            regret_weight=5,
            backtracks_enabled=False,
        )
        self.assertTrue(cfg.flat)
        self.assertTrue(cfg.skip_intent)
        self.assertEqual(cfg.regret_weight, 5)
        self.assertFalse(cfg.backtracks_enabled)

    def test_make_config_ignores_unknown_overrides(self):
        """Unknown override keys are silently dropped."""
        corpus = CorpusConfig(
            experiment='test-exp',
            tasks=[TaskDefinition(id='t-001', text='Do it')],
        )
        # 'suppress_backtracks' is not in the allowlist — should not raise
        cfg = corpus.make_config(corpus.tasks[0], suppress_backtracks=True)
        # The config should not have a 'suppress_backtracks' attribute
        self.assertFalse(hasattr(cfg, 'suppress_backtracks')
                         and getattr(cfg, 'suppress_backtracks', False))

    def test_real_corpus_file_loads(self):
        """The actual proxy-convergence.yaml corpus loads correctly."""
        corpus_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            'corpus', 'proxy-convergence.yaml',
        )
        if not os.path.exists(corpus_path):
            self.skipTest('proxy-convergence.yaml not found')

        corpus = load_corpus(corpus_path)
        self.assertEqual(corpus.experiment, 'proxy-convergence')
        self.assertGreater(len(corpus.tasks), 0)
        for task in corpus.tasks:
            self.assertTrue(task.id)
            self.assertTrue(task.text)


# ── analyze.py ────────────────────────────────────────────────────────────────

class TestDescriptiveStats(unittest.TestCase):
    """_descriptive_stats computes correct sample statistics."""

    def test_empty_list(self):
        stats = _descriptive_stats([])
        self.assertEqual(stats['n'], 0)
        self.assertEqual(stats['mean'], 0)

    def test_single_value(self):
        stats = _descriptive_stats([5.0])
        self.assertEqual(stats['mean'], 5.0)
        self.assertEqual(stats['median'], 5.0)
        self.assertEqual(stats['min'], 5.0)
        self.assertEqual(stats['max'], 5.0)
        self.assertEqual(stats['n'], 1)

    def test_mean_and_median_odd(self):
        stats = _descriptive_stats([1, 2, 3, 4, 5])
        self.assertAlmostEqual(stats['mean'], 3.0)
        self.assertAlmostEqual(stats['median'], 3.0)

    def test_median_even(self):
        stats = _descriptive_stats([1, 2, 3, 4])
        self.assertAlmostEqual(stats['median'], 2.5)

    def test_sample_std_not_population_std(self):
        """For [2, 4]: sample std = sqrt(2) ≈ 1.4142, population std = 1.0.

        Experiment analysis with small n should use Bessel's correction (n-1).
        """
        stats = _descriptive_stats([2.0, 4.0])
        expected_sample_std = math.sqrt(
            sum((x - 3.0) ** 2 for x in [2.0, 4.0]) / (2 - 1)
        )
        self.assertAlmostEqual(
            stats['std'], expected_sample_std, places=4,
            msg=f'Expected sample std {expected_sample_std:.4f}, got {stats["std"]:.4f}. '
                'Should use n-1 (Bessel\'s correction), not n.',
        )

    def test_known_values(self):
        """Verify with a known dataset: [10, 20, 30, 40, 50]."""
        values = [10, 20, 30, 40, 50]
        stats = _descriptive_stats(values)
        self.assertAlmostEqual(stats['mean'], 30.0)
        self.assertAlmostEqual(stats['median'], 30.0)
        self.assertEqual(stats['min'], 10)
        self.assertEqual(stats['max'], 50)
        # Sample std: sqrt(250/4) = sqrt(62.5) ≈ 7.9057
        expected_std = math.sqrt(sum((x - 30) ** 2 for x in values) / (5 - 1))
        self.assertAlmostEqual(stats['std'], expected_std, places=3)


class TestCohensD(unittest.TestCase):
    """Cohen's d effect size computation."""

    def test_identical_groups(self):
        d = _cohens_d([5, 5, 5], [5, 5, 5])
        self.assertAlmostEqual(d, 0.0)

    def test_large_effect(self):
        """[2, 4] vs [6, 8]: means 3 vs 7, pooled std = sqrt(2), d ≈ -2.83."""
        d = _cohens_d([2.0, 4.0], [6.0, 8.0])
        expected = (3.0 - 7.0) / math.sqrt(2)
        self.assertAlmostEqual(d, expected, places=3)

    def test_too_few_samples_returns_zero(self):
        self.assertAlmostEqual(_cohens_d([1], [2]), 0.0)
        self.assertAlmostEqual(_cohens_d([], [1, 2]), 0.0)


class TestExtractMetric(unittest.TestCase):
    """_extract_metric navigates dot-delimited paths."""

    def test_flat_key(self):
        val = _extract_metric({'backtrack_count': 3}, 'backtrack_count')
        self.assertEqual(val, 3)

    def test_nested_key(self):
        val = _extract_metric(
            {'proxy': {'mean_confidence': 0.85}},
            'proxy.mean_confidence',
        )
        self.assertAlmostEqual(val, 0.85)

    def test_missing_key_returns_none(self):
        val = _extract_metric({'a': 1}, 'b')
        self.assertIsNone(val)

    def test_deeply_missing_returns_none(self):
        val = _extract_metric({'a': {'b': 1}}, 'a.c')
        self.assertIsNone(val)


class TestGroupByCondition(unittest.TestCase):

    def test_groups_correctly(self):
        runs = [
            _make_metrics(condition='ctrl'),
            _make_metrics(condition='treatment'),
            _make_metrics(condition='ctrl'),
        ]
        groups = group_by_condition(runs)
        self.assertEqual(len(groups['ctrl']), 2)
        self.assertEqual(len(groups['treatment']), 1)


class TestConditionSummary(unittest.TestCase):

    def test_empty_runs(self):
        summary = condition_summary([])
        self.assertEqual(summary['n'], 0)

    def test_completion_rate(self):
        runs = [
            _make_metrics(terminal_state='COMPLETED_WORK'),
            _make_metrics(terminal_state='COMPLETED_WORK'),
            _make_metrics(terminal_state='WITHDRAWN'),
        ]
        summary = condition_summary(runs)
        self.assertEqual(summary['n'], 3)
        self.assertEqual(summary['completed'], 2)
        self.assertAlmostEqual(summary['completion_rate'], 2 / 3)


class TestAnalyzeExperiment(unittest.TestCase):
    """Full experiment analysis pipeline."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix='analyze_test_')

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write_metrics(self, experiment, condition, task_id, metrics):
        d = os.path.join(self.tmpdir, experiment, condition, task_id)
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, 'metrics.json'), 'w') as f:
            json.dump(metrics, f)

    def test_no_results_returns_error(self):
        report = analyze_experiment('nonexistent', results_base=self.tmpdir)
        self.assertEqual(report['total_runs'], 0)
        self.assertIn('error', report)

    def test_single_condition(self):
        self._write_metrics('exp', 'ctrl', 't-001', _make_metrics(condition='ctrl'))
        self._write_metrics('exp', 'ctrl', 't-002', _make_metrics(condition='ctrl'))

        report = analyze_experiment('exp', results_base=self.tmpdir)
        self.assertEqual(report['total_runs'], 2)
        self.assertIn('ctrl', report['conditions'])
        self.assertEqual(report['conditions']['ctrl']['n'], 2)

    def test_two_conditions_compared(self):
        for i in range(3):
            self._write_metrics(
                'exp', 'ctrl', f't-{i:03d}',
                _make_metrics(condition='ctrl', backtrack_count=i),
            )
            self._write_metrics(
                'exp', 'treatment', f't-{i:03d}',
                _make_metrics(condition='treatment', backtrack_count=i + 5),
            )

        report = analyze_experiment('exp', results_base=self.tmpdir)
        self.assertEqual(report['total_runs'], 6)
        self.assertIn('backtrack_count', report['comparisons'])


# ── report.py ─────────────────────────────────────────────────────────────────

class TestMarkdownTable(unittest.TestCase):
    """markdown_table produces correct markdown."""

    def test_basic_table(self):
        rows = [{'a': 1, 'b': 'hello'}, {'a': 2, 'b': 'world'}]
        table = markdown_table(rows, ['a', 'b'])
        lines = table.split('\n')
        self.assertEqual(len(lines), 4)  # header + separator + 2 rows
        self.assertIn('| a | b |', lines[0])
        self.assertIn('| --- | --- |', lines[1])

    def test_float_formatting(self):
        rows = [{'x': 3.14159}]
        table = markdown_table(rows, ['x'])
        self.assertIn('3.1416', table)

    def test_empty_rows(self):
        self.assertEqual(markdown_table([], ['a']), '')

    def test_empty_columns(self):
        self.assertEqual(markdown_table([{'a': 1}], []), '')


class TestFormatStats(unittest.TestCase):

    def test_with_label(self):
        stats = {'mean': 3.0, 'median': 3.0, 'std': 1.0, 'min': 1.0, 'max': 5.0, 'n': 5}
        result = format_stats(stats, 'backtracks')
        self.assertIn('backtracks:', result)
        self.assertIn('mean=3.00', result)

    def test_no_data(self):
        result = format_stats({'n': 0}, 'backtracks')
        self.assertIn('no data', result)


# ── suppress_backtracks (engine.py) ───────────────────────────────────────────

class TestSuppressBacktracks(unittest.TestCase):
    """Orchestrator.suppress_backtracks prevents cross-phase backtrack loops.

    When suppress_backtracks=True and a phase returns backtrack_to='planning'
    or backtrack_to='intent', the orchestrator should NOT loop back —
    it should fall through to completion.
    """

    def _make_orchestrator(self, suppress_backtracks=False, **kwargs):
        from projects.POC.orchestrator.engine import Orchestrator
        from projects.POC.orchestrator.phase_config import PhaseSpec
        from projects.POC.scripts.cfa_state import CfaState

        cfa = CfaState(
            state='PROPOSAL',
            phase='intent',
            actor='agent',
            history=[],
            backtrack_count=0,
        )

        phase_config = MagicMock()
        phase_config.stall_timeout = 1800
        phase_config.human_actor_states = frozenset()
        phase_config.phase.return_value = PhaseSpec(
            name='intent',
            agent_file='agents/intent-team.json',
            lead='intent-lead',
            permission_mode='acceptEdits',
            stream_file='.intent-stream.jsonl',
            artifact=None,
            approval_state='INTENT_ASSERT',
            escalation_state='INTENT_ESCALATE',
            escalation_file='.intent-escalation.md',
            settings_overlay={},
        )

        event_bus = MagicMock(spec=EventBus)
        event_bus.publish = AsyncMock()

        return Orchestrator(
            cfa_state=cfa,
            phase_config=phase_config,
            event_bus=event_bus,
            input_provider=AsyncMock(return_value='approve'),
            infra_dir='/tmp/infra',
            project_workdir='/tmp/project',
            session_worktree='/tmp/worktree',
            proxy_model_path='/tmp/proxy.json',
            project_slug='test-project',
            poc_root='/tmp/poc',
            task='Do the thing',
            session_id='test-session',
            suppress_backtracks=suppress_backtracks,
            **kwargs,
        )

    def test_suppress_backtracks_flag_stored(self):
        orch = self._make_orchestrator(suppress_backtracks=True)
        self.assertTrue(orch.suppress_backtracks)

    def test_suppress_backtracks_default_false(self):
        orch = self._make_orchestrator()
        self.assertFalse(orch.suppress_backtracks)

    def test_backtrack_suppressed_does_not_loop(self):
        """When suppress_backtracks=True and execution returns backtrack_to='planning',
        the orchestrator should NOT re-enter the planning phase.

        We mock _run_phase to:
          1. Return PhaseResult() for intent (phase completes normally)
          2. Return PhaseResult() for planning (phase completes normally)
          3. Return PhaseResult(backtrack_to='planning') for first execution call
          4. Return PhaseResult(terminal=True, terminal_state='COMPLETED_WORK')
             for the second execution call

        With suppress_backtracks=True, after step 3 the engine should NOT loop
        back to planning. Instead it should fall through.
        """
        from projects.POC.orchestrator.engine import Orchestrator, PhaseResult

        orch = self._make_orchestrator(suppress_backtracks=True)

        call_count = {'intent': 0, 'planning': 0, 'execution': 0}

        async def mock_run_phase(phase_name):
            call_count[phase_name] = call_count.get(phase_name, 0) + 1

            if phase_name == 'intent':
                return PhaseResult()  # completes normally
            elif phase_name == 'planning':
                return PhaseResult()  # completes normally
            elif phase_name == 'execution':
                if call_count['execution'] == 1:
                    return PhaseResult(backtrack_to='planning')
                else:
                    return PhaseResult(terminal=True, terminal_state='COMPLETED_WORK')
            return PhaseResult(terminal=True, terminal_state='COMPLETED_WORK')

        async def mock_auto_bridge():
            pass  # no-op

        orch._run_phase = mock_run_phase
        orch._auto_bridge = mock_auto_bridge
        orch.skip_intent = False

        result = _run(orch.run())

        # With suppress_backtracks=True, planning should only be called once
        # (not re-entered after the execution backtrack)
        self.assertEqual(call_count['planning'], 1,
                         f'Planning was called {call_count["planning"]} times; '
                         'should be 1 when backtracks are suppressed')


if __name__ == '__main__':
    unittest.main()
