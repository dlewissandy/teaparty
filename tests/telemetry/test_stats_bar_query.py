"""Specification tests for issue #406: stats-bar query helper extensions.

The stats bar requires:
  1. Consistent agent/session filtering across all aggregation helpers.
  2. A ``gate_pass_rate()`` helper (new; not in #405).
  3. A ``stats_summary()`` convenience function that calls every helper
     once and returns a single dict — the canonical response shape for
     the ``/api/telemetry/stats/{scope}`` endpoint.

Each test is load-bearing: it imports or calls a symbol that does not
exist before the fix and would raise ``ImportError`` or ``TypeError``
if the fix were reverted.
"""
from __future__ import annotations

import tempfile
import time
import unittest

from teaparty import telemetry
from teaparty.telemetry import events as E


def _make_home(tc: unittest.TestCase) -> str:
    home = tempfile.mkdtemp(prefix='tp406-query-test-')
    telemetry.set_teaparty_home(home)
    tc.addCleanup(telemetry.reset_for_tests)
    return home


class TotalCostAgentFilterTests(unittest.TestCase):
    """total_cost() must accept agent and session keyword args (#406 AC8)."""

    def setUp(self) -> None:
        telemetry.reset_for_tests()
        _make_home(self)

    def test_total_cost_accepts_agent_kwarg(self) -> None:
        """total_cost(agent=...) must be accepted without TypeError."""
        telemetry.record_event(E.TURN_COMPLETE, scope='alpha',
                               agent_name='bot-1', data={'cost_usd': 0.05})
        telemetry.record_event(E.TURN_COMPLETE, scope='alpha',
                               agent_name='bot-2', data={'cost_usd': 0.10})

        cost_bot1 = telemetry.total_cost(scope='alpha', agent='bot-1')
        cost_bot2 = telemetry.total_cost(scope='alpha', agent='bot-2')
        cost_all  = telemetry.total_cost(scope='alpha')

        self.assertAlmostEqual(cost_bot1, 0.05, places=4,
            msg='total_cost(agent="bot-1") must sum only bot-1 turns')
        self.assertAlmostEqual(cost_bot2, 0.10, places=4,
            msg='total_cost(agent="bot-2") must sum only bot-2 turns')
        self.assertAlmostEqual(cost_all, 0.15, places=4,
            msg='total_cost(scope only) must sum all turns in scope')

    def test_total_cost_agent_filter_excludes_other_scopes(self) -> None:
        """total_cost(scope=S, agent=A) must not count turns in other scopes."""
        telemetry.record_event(E.TURN_COMPLETE, scope='alpha',
                               agent_name='shared', data={'cost_usd': 0.03})
        telemetry.record_event(E.TURN_COMPLETE, scope='beta',
                               agent_name='shared', data={'cost_usd': 0.07})

        cost = telemetry.total_cost(scope='alpha', agent='shared')
        self.assertAlmostEqual(cost, 0.03, places=4,
            msg='total_cost(scope="alpha", agent="shared") must exclude '
                'the beta-scope turn for the same agent')

    def test_total_cost_accepts_session_kwarg(self) -> None:
        """total_cost(session=...) must be accepted without TypeError."""
        telemetry.record_event(E.TURN_COMPLETE, scope='alpha',
                               session_id='s1', data={'cost_usd': 0.04})
        telemetry.record_event(E.TURN_COMPLETE, scope='alpha',
                               session_id='s2', data={'cost_usd': 0.08})

        cost_s1 = telemetry.total_cost(scope='alpha', session='s1')
        self.assertAlmostEqual(cost_s1, 0.04, places=4,
            msg='total_cost(session="s1") must sum only s1 turns')


class ActiveSessionsAgentFilterTests(unittest.TestCase):
    """active_sessions() must accept agent kwarg (#406 AC8)."""

    def setUp(self) -> None:
        telemetry.reset_for_tests()
        _make_home(self)

    def test_active_sessions_accepts_agent_kwarg(self) -> None:
        """active_sessions(agent=...) must not raise TypeError."""
        telemetry.record_event(E.SESSION_CREATE, scope='proj',
                               agent_name='wkr', session_id='s10')
        telemetry.record_event(E.SESSION_CREATE, scope='proj',
                               agent_name='mgr', session_id='s11')

        active_wkr = telemetry.active_sessions(scope='proj', agent='wkr')
        self.assertEqual(active_wkr, ['s10'],
            msg='active_sessions(agent="wkr") must return only wkr sessions, '
                f'got {active_wkr}')

    def test_active_sessions_agent_filter_excludes_closed(self) -> None:
        """active_sessions(agent=A) must exclude sessions closed for A."""
        telemetry.record_event(E.SESSION_CREATE, scope='proj',
                               agent_name='wkr', session_id='s20')
        telemetry.record_event(E.SESSION_CLOSED, scope='proj',
                               agent_name='wkr', session_id='s20')
        telemetry.record_event(E.SESSION_CREATE, scope='proj',
                               agent_name='wkr', session_id='s21')

        active = telemetry.active_sessions(scope='proj', agent='wkr')
        self.assertEqual(active, ['s21'],
            msg='active_sessions must exclude closed sessions; '
                f'expected ["s21"], got {active}')


class GatesAwaitingInputAgentFilterTests(unittest.TestCase):
    """gates_awaiting_input() must accept agent kwarg (#406 AC8)."""

    def setUp(self) -> None:
        telemetry.reset_for_tests()
        _make_home(self)

    def test_gates_awaiting_accepts_agent_kwarg(self) -> None:
        """gates_awaiting_input(agent=...) must not raise TypeError."""
        telemetry.record_event(E.GATE_INPUT_REQUESTED, scope='proj',
                               agent_name='agt', session_id='s30',
                               data={'gate_type': 'intent'})

        gates = telemetry.gates_awaiting_input(scope='proj', agent='agt')
        self.assertEqual(len(gates), 1,
            msg='gates_awaiting_input(agent="agt") must return the open gate, '
                f'got {gates}')

    def test_gates_awaiting_agent_filter_excludes_other_agents(self) -> None:
        """gates_awaiting_input(agent=A) must not include gates for other agents."""
        telemetry.record_event(E.GATE_INPUT_REQUESTED, scope='proj',
                               agent_name='other', session_id='s31',
                               data={'gate_type': 'plan'})

        gates = telemetry.gates_awaiting_input(scope='proj', agent='agt-x')
        self.assertEqual(gates, [],
            msg='gates_awaiting_input(agent="agt-x") must be empty when '
                'only "other" has open gates')


class GatePassRateTests(unittest.TestCase):
    """gate_pass_rate() — new helper required by #406 AC8 / success criterion 9."""

    def setUp(self) -> None:
        telemetry.reset_for_tests()
        _make_home(self)

    def test_gate_pass_rate_exists(self) -> None:
        """gate_pass_rate must be importable from teaparty.telemetry.query."""
        from teaparty.telemetry.query import gate_pass_rate  # noqa: F401

    def test_gate_pass_rate_empty_db(self) -> None:
        """gate_pass_rate() on empty db must return empty dict, not raise."""
        from teaparty.telemetry.query import gate_pass_rate
        result = gate_pass_rate()
        self.assertIsInstance(result, dict,
            msg='gate_pass_rate() must return a dict, not raise on empty db')
        self.assertEqual(result, {},
            msg='gate_pass_rate() must return {} when no gate events exist')

    def test_gate_pass_rate_counts_by_gate_type(self) -> None:
        """gate_pass_rate() must return pass/(pass+fail) per gate_type."""
        from teaparty.telemetry.query import gate_pass_rate
        # intent gate: 2 passed, 1 failed → rate = 2/3
        for _ in range(2):
            telemetry.record_event(E.GATE_PASSED, scope='p',
                                   data={'gate_type': 'intent'})
        telemetry.record_event(E.GATE_FAILED, scope='p',
                               data={'gate_type': 'intent'})
        # plan gate: 1 passed, 0 failed → rate = 1/1
        telemetry.record_event(E.GATE_PASSED, scope='p',
                               data={'gate_type': 'plan'})

        result = gate_pass_rate(scope='p')

        self.assertIn('intent', result,
            msg='gate_pass_rate must have entry for "intent" gate type')
        self.assertIn('plan', result,
            msg='gate_pass_rate must have entry for "plan" gate type')

        intent = result['intent']
        self.assertEqual(intent['passed'], 2,
            msg=f'intent gate: expected 2 passed, got {intent["passed"]}')
        self.assertEqual(intent['failed'], 1,
            msg=f'intent gate: expected 1 failed, got {intent["failed"]}')
        self.assertAlmostEqual(intent['rate'], 2/3, places=4,
            msg=f'intent gate: expected rate 0.6667, got {intent["rate"]}')

        plan = result['plan']
        self.assertEqual(plan['passed'], 1,
            msg=f'plan gate: expected 1 passed, got {plan["passed"]}')
        self.assertEqual(plan['failed'], 0,
            msg=f'plan gate: expected 0 failed, got {plan["failed"]}')
        self.assertAlmostEqual(plan['rate'], 1.0, places=4,
            msg=f'plan gate: expected rate 1.0, got {plan["rate"]}')

    def test_gate_pass_rate_scope_filter(self) -> None:
        """gate_pass_rate(scope=S) must exclude events from other scopes."""
        from teaparty.telemetry.query import gate_pass_rate
        telemetry.record_event(E.GATE_PASSED, scope='alpha',
                               data={'gate_type': 'intent'})
        telemetry.record_event(E.GATE_FAILED, scope='beta',
                               data={'gate_type': 'intent'})

        result = gate_pass_rate(scope='alpha')
        self.assertIn('intent', result,
            msg='gate_pass_rate(scope="alpha") must include alpha intent gate')
        # beta's failure must not bleed in
        self.assertEqual(result['intent']['failed'], 0,
            msg='gate_pass_rate(scope="alpha") must not count beta failures; '
                f'got failed={result["intent"]["failed"]}')

    def test_gate_pass_rate_accepts_agent_session_time_range(self) -> None:
        """gate_pass_rate must accept agent, session, time_range kwargs."""
        from teaparty.telemetry.query import gate_pass_rate
        telemetry.record_event(E.GATE_PASSED, scope='p',
                               agent_name='agt', session_id='s1',
                               data={'gate_type': 'intent'})
        # Should not raise TypeError for any supported keyword argument.
        gate_pass_rate(scope='p', agent='agt')
        gate_pass_rate(scope='p', session='s1')
        gate_pass_rate(scope='p', time_range=(0.0, time.time() + 1))


class StatsSummaryTests(unittest.TestCase):
    """stats_summary() — convenience aggregation function required by #406 AC8."""

    def setUp(self) -> None:
        telemetry.reset_for_tests()
        _make_home(self)

    def test_stats_summary_exists(self) -> None:
        """stats_summary must be importable from teaparty.telemetry.query."""
        from teaparty.telemetry.query import stats_summary  # noqa: F401

    def test_stats_summary_returns_all_required_keys(self) -> None:
        """stats_summary() must return a dict with all stats-bar keys."""
        from teaparty.telemetry.query import stats_summary
        result = stats_summary()
        required_keys = {
            'cost_today',
            'turn_count_today',
            'active_sessions',
            'gates_waiting',
            'backtrack_count_today',
            'escalation_count_today',
            'proxy_answered_fraction',
            'gate_pass_rate',
        }
        missing = required_keys - result.keys()
        self.assertEqual(missing, set(),
            msg=f'stats_summary() is missing required keys: {missing}')

    def test_stats_summary_accepts_scope_agent_session_time_range(self) -> None:
        """stats_summary must accept scope, agent, session, time_range kwargs."""
        from teaparty.telemetry.query import stats_summary
        now = time.time()
        # Should not raise TypeError for any supported keyword argument.
        stats_summary(scope='proj')
        stats_summary(scope='proj', agent='agt')
        stats_summary(scope='proj', session='s1')
        stats_summary(scope='proj', time_range=(now - 86400, now))

    def test_stats_summary_computes_correct_cost_today(self) -> None:
        """stats_summary()['cost_today'] must match total_cost for today."""
        from teaparty.telemetry.query import stats_summary
        telemetry.record_event(E.TURN_COMPLETE, scope='proj',
                               data={'cost_usd': 0.12})
        telemetry.record_event(E.TURN_COMPLETE, scope='proj',
                               data={'cost_usd': 0.08})

        result = stats_summary(scope='proj')
        self.assertAlmostEqual(result['cost_today'], 0.20, places=4,
            msg=f'stats_summary cost_today must be 0.20, got {result["cost_today"]}')

    def test_stats_summary_computes_active_sessions_count(self) -> None:
        """stats_summary()['active_sessions'] must be an integer count."""
        from teaparty.telemetry.query import stats_summary
        telemetry.record_event(E.SESSION_CREATE, scope='proj', session_id='s1')
        telemetry.record_event(E.SESSION_CREATE, scope='proj', session_id='s2')
        telemetry.record_event(E.SESSION_CLOSED, scope='proj', session_id='s1')

        result = stats_summary(scope='proj')
        self.assertEqual(result['active_sessions'], 1,
            msg=f'stats_summary active_sessions must be 1 (one open), '
                f'got {result["active_sessions"]}')

    def test_stats_summary_scope_filter_isolates_costs(self) -> None:
        """stats_summary(scope=A) must not include costs from scope B."""
        from teaparty.telemetry.query import stats_summary
        telemetry.record_event(E.TURN_COMPLETE, scope='A', data={'cost_usd': 1.0})
        telemetry.record_event(E.TURN_COMPLETE, scope='B', data={'cost_usd': 9.0})

        result_a = stats_summary(scope='A')
        self.assertAlmostEqual(result_a['cost_today'], 1.0, places=4,
            msg=f'stats_summary(scope="A") must not include B cost; '
                f'got {result_a["cost_today"]}')

    def test_stats_summary_gates_waiting_count(self) -> None:
        """stats_summary()['gates_waiting'] must be an integer count of open gates."""
        from teaparty.telemetry.query import stats_summary
        telemetry.record_event(E.GATE_INPUT_REQUESTED, scope='proj',
                               session_id='s1', data={'gate_type': 'intent'})
        telemetry.record_event(E.GATE_INPUT_REQUESTED, scope='proj',
                               session_id='s2', data={'gate_type': 'plan'})
        telemetry.record_event(E.GATE_INPUT_RECEIVED, scope='proj',
                               session_id='s1', data={'gate_type': 'intent'})

        result = stats_summary(scope='proj')
        self.assertEqual(result['gates_waiting'], 1,
            msg=f'stats_summary gates_waiting must be 1 (one open gate), '
                f'got {result["gates_waiting"]}')


if __name__ == '__main__':
    unittest.main()
