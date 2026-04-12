"""Specification tests for record_event + query_events (Issue #405).

These tests encode the success criteria from the issue: one database,
one table, one write path, one read path, broadcast on write, failure
tolerance, and idempotent schema creation.
"""
from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import tempfile
import threading
import time
import unittest

from teaparty import telemetry
from teaparty.telemetry import events as E
from teaparty.telemetry import record as _record
from teaparty.telemetry.schema import apply_schema


def _make_home() -> str:
    home = tempfile.mkdtemp(prefix='telemetry-test-')
    telemetry.set_teaparty_home(home)
    return home


class RecordEventTests(unittest.TestCase):

    def setUp(self) -> None:
        telemetry.reset_for_tests()
        self.home = _make_home()

    def tearDown(self) -> None:
        telemetry.reset_for_tests()

    # ── Success criterion 1: one database, at the expected path ──────────
    def test_writes_to_single_telemetry_db_at_home_root(self) -> None:
        telemetry.record_event(
            E.TURN_COMPLETE, scope='management',
            data={'cost_usd': 0.01},
        )
        db = os.path.join(self.home, 'telemetry.db')
        self.assertTrue(
            os.path.exists(db),
            'record_event must persist to {teaparty_home}/telemetry.db',
        )
        # No other telemetry database must appear alongside it.
        self.assertNotIn(
            'metrics.db', os.listdir(self.home),
            'telemetry package must not create per-scope metrics.db files',
        )

    # ── Success criterion 2: one table with indexed columns ──────────────
    def test_schema_has_events_table_with_all_indexes(self) -> None:
        telemetry.record_event(E.TURN_START, scope='management')
        db = os.path.join(self.home, 'telemetry.db')
        conn = sqlite3.connect(db)
        try:
            tables = {r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name NOT LIKE 'sqlite_%'"
            ).fetchall()}
            self.assertEqual(
                tables, {'events'},
                f'events must be the only telemetry table, found: {tables}',
            )
            indexes = {r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index' "
                "AND name NOT LIKE 'sqlite_%'"
            ).fetchall()}
            expected = {
                'idx_events_ts', 'idx_events_scope_ts',
                'idx_events_agent_ts', 'idx_events_session',
                'idx_events_type_ts',
            }
            self.assertTrue(
                expected.issubset(indexes),
                f'missing indexes: {expected - indexes}',
            )
        finally:
            conn.close()

    # ── Write path returns row id and row is present with correct fields
    def test_record_event_returns_row_id_and_row_is_queryable(self) -> None:
        rid = telemetry.record_event(
            E.PHASE_CHANGED,
            scope='comics', agent_name='comics-lead',
            session_id='sess-1',
            data={'old_phase': 'intent', 'new_phase': 'planning',
                  'state_machine': 'cfa'},
            ts=1000.0,
        )
        self.assertIsInstance(rid, int)
        self.assertGreater(rid, 0)

        found = telemetry.query_events(session='sess-1')
        self.assertEqual(len(found), 1)
        ev = found[0]
        self.assertEqual(ev.id, rid)
        self.assertEqual(ev.ts, 1000.0)
        self.assertEqual(ev.scope, 'comics')
        self.assertEqual(ev.agent_name, 'comics-lead')
        self.assertEqual(ev.session_id, 'sess-1')
        self.assertEqual(ev.event_type, E.PHASE_CHANGED)
        self.assertEqual(ev.data['new_phase'], 'planning')

    # ── Success criterion 9: failure tolerance ───────────────────────────
    def test_record_event_never_raises_on_write_failure(self) -> None:
        """A broken connection must not propagate as an exception."""
        # Close the connection out from under record_event so the INSERT
        # fails — simulates disk-full / readonly / corruption.
        with _record._lock:
            _record._conn.close()
            _record._conn = sqlite3.connect(':memory:', check_same_thread=False)
            # Deliberately do NOT apply_schema — INSERT will fail.

        # Must not raise; must return None.
        try:
            result = telemetry.record_event(E.TURN_START, scope='management')
        except Exception as exc:  # pragma: no cover
            self.fail(f'record_event raised on write failure: {exc}')
        self.assertIsNone(
            result,
            'record_event must return None when the INSERT fails',
        )

    # ── WAL mode ──────────────────────────────────────────────────────────
    def test_telemetry_db_uses_wal_journal_mode(self) -> None:
        telemetry.record_event(E.TURN_START, scope='management')
        db = os.path.join(self.home, 'telemetry.db')
        conn = sqlite3.connect(db)
        try:
            mode = conn.execute('PRAGMA journal_mode').fetchone()[0]
            self.assertEqual(
                mode.lower(), 'wal',
                f'telemetry.db must use WAL journal mode, got {mode}',
            )
        finally:
            conn.close()

    # ── Idempotent schema application ────────────────────────────────────
    def test_apply_schema_is_idempotent(self) -> None:
        db = os.path.join(self.home, 'telemetry.db')
        conn = sqlite3.connect(db)
        try:
            apply_schema(conn)
            apply_schema(conn)  # second call must not raise
            count = conn.execute('SELECT COUNT(*) FROM events').fetchone()[0]
            self.assertEqual(count, 0)
        finally:
            conn.close()

    # ── Success criterion 6: broadcast fires after commit ────────────────
    def test_broadcast_hook_receives_event_payload(self) -> None:
        received: list[dict] = []

        def sync_broadcaster(payload: dict) -> None:
            received.append(payload)

        telemetry.set_broadcaster(sync_broadcaster)

        telemetry.record_event(
            E.TURN_COMPLETE, scope='management',
            agent_name='office-manager', session_id='s1',
            data={'cost_usd': 0.5},
        )

        self.assertEqual(len(received), 1)
        payload = received[0]
        self.assertEqual(payload['type'], 'telemetry_event')
        self.assertEqual(payload['event_type'], E.TURN_COMPLETE)
        self.assertEqual(payload['scope'], 'management')
        self.assertEqual(payload['agent_name'], 'office-manager')
        self.assertEqual(payload['session_id'], 's1')
        self.assertEqual(payload['data']['cost_usd'], 0.5)

    def test_broadcast_hook_swallows_handler_exceptions(self) -> None:
        def bad_broadcaster(payload: dict) -> None:
            raise RuntimeError('boom')

        telemetry.set_broadcaster(bad_broadcaster)
        # Must not raise from record_event.
        telemetry.record_event(E.TURN_START, scope='management')
        # And the row must still have been inserted.
        self.assertEqual(
            len(telemetry.query_events(event_type=E.TURN_START)), 1,
        )

    def test_async_broadcast_is_scheduled_on_stored_loop(self) -> None:
        """When the broadcaster is async, record_event must schedule it
        on the event loop set via set_broadcaster."""
        received: list[dict] = []
        done_event = asyncio.Event()

        async def main() -> None:
            loop = asyncio.get_running_loop()

            async def async_broadcaster(payload: dict) -> None:
                received.append(payload)
                done_event.set()

            telemetry.set_broadcaster(async_broadcaster, loop)

            # Fire record_event from a worker thread — simulates call
            # from sync code running off the loop.
            def worker() -> None:
                telemetry.record_event(E.TURN_START, scope='management')

            t = threading.Thread(target=worker)
            t.start()
            t.join()
            # The coroutine is scheduled on this loop — yield so it runs.
            # Use asyncio.wait_for with a generous timeout for determinism.
            try:
                await asyncio.wait_for(done_event.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                self.fail('async broadcaster was never scheduled')

        asyncio.run(main())
        self.assertEqual(len(received), 1)
        self.assertEqual(received[0]['event_type'], E.TURN_START)

    # ── Concurrency: many writers, no lost rows ──────────────────────────
    def test_concurrent_writers_do_not_lose_rows(self) -> None:
        N_THREADS = 8
        N_PER_THREAD = 25

        def worker(idx: int) -> None:
            for i in range(N_PER_THREAD):
                telemetry.record_event(
                    E.TURN_START, scope='management',
                    session_id=f's{idx}',
                    data={'i': i},
                )

        threads = [threading.Thread(target=worker, args=(i,))
                   for i in range(N_THREADS)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        total = len(telemetry.query_events(event_type=E.TURN_START))
        self.assertEqual(
            total, N_THREADS * N_PER_THREAD,
            f'concurrent writes lost rows: expected '
            f'{N_THREADS * N_PER_THREAD}, got {total}',
        )


class QueryEventsTests(unittest.TestCase):

    def setUp(self) -> None:
        telemetry.reset_for_tests()
        self.home = _make_home()
        # Seed a known event log.
        def rec(et, *, scope='management', agent=None, session=None,
                data=None, ts=None):
            telemetry.record_event(
                et, scope=scope, agent_name=agent, session_id=session,
                data=data or {}, ts=ts,
            )

        # 3 completed turns in management, 2 in comics
        rec(E.TURN_COMPLETE, data={'cost_usd': 0.10}, ts=100)
        rec(E.TURN_COMPLETE, data={'cost_usd': 0.20}, ts=200)
        rec(E.TURN_COMPLETE, data={'cost_usd': 0.05}, ts=300)
        rec(E.TURN_COMPLETE, scope='comics',
            data={'cost_usd': 1.00}, ts=400)
        rec(E.TURN_COMPLETE, scope='comics',
            data={'cost_usd': 2.00}, ts=500)

        # Two phase backtracks
        rec(E.PHASE_BACKTRACK, scope='comics',
            data={'kind': 'plan_to_intent',
                  'cost_of_work_being_discarded': 0.30}, ts=600)
        rec(E.PHASE_BACKTRACK, scope='comics',
            data={'kind': 'work_to_plan',
                  'cost_of_work_being_discarded': 0.70}, ts=601)

        # Phase transitions
        rec(E.PHASE_CHANGED, scope='comics',
            data={'new_phase': 'planning'}, ts=700)
        rec(E.PHASE_CHANGED, scope='comics',
            data={'new_phase': 'planning'}, ts=701)
        rec(E.PHASE_CHANGED, scope='comics',
            data={'new_phase': 'execution'}, ts=702)

        # Escalation chain
        rec(E.ESCALATION_REQUESTED, scope='management', ts=800)
        rec(E.ESCALATION_REQUESTED, scope='management', ts=801)
        rec(E.PROXY_ANSWERED, scope='management', ts=802)
        rec(E.ESCALATION_RESOLVED, scope='management',
            data={'final_answer_source': 'proxy'}, ts=803)
        rec(E.ESCALATION_RESOLVED, scope='management',
            data={'final_answer_source': 'human'}, ts=804)

        # Session lifecycle: s1 open, s2 closed, s3 withdrawn
        rec(E.SESSION_CREATE, session='s1', ts=900)
        rec(E.SESSION_CREATE, session='s2', ts=901)
        rec(E.SESSION_CREATE, session='s3', ts=902)
        rec(E.SESSION_COMPLETE, session='s2', ts=903)
        rec(E.SESSION_WITHDRAWN, session='s3',
            data={'phase_at_withdrawal': 'planning'}, ts=904)

        # Gate awaiting input on s4
        rec(E.GATE_INPUT_REQUESTED, session='s4',
            data={'gate_type': 'plan_assert', 'question_len': 42}, ts=910)
        # And a gate on s5 that was answered
        rec(E.GATE_INPUT_REQUESTED, session='s5',
            data={'gate_type': 'exec_assert'}, ts=911)
        rec(E.GATE_INPUT_RECEIVED, session='s5',
            data={'gate_type': 'exec_assert'}, ts=912)

    def tearDown(self) -> None:
        telemetry.reset_for_tests()

    def test_query_events_orders_by_timestamp(self) -> None:
        evs = telemetry.query_events(event_type=E.TURN_COMPLETE)
        self.assertEqual([e.ts for e in evs], [100, 200, 300, 400, 500])

    def test_query_events_filters_by_scope(self) -> None:
        mgmt = telemetry.query_events(event_type=E.TURN_COMPLETE,
                                      scope='management')
        comics = telemetry.query_events(event_type=E.TURN_COMPLETE,
                                        scope='comics')
        self.assertEqual(len(mgmt), 3)
        self.assertEqual(len(comics), 2)

    def test_query_events_time_range(self) -> None:
        evs = telemetry.query_events(
            event_type=E.TURN_COMPLETE, start_ts=150, end_ts=450,
        )
        self.assertEqual([e.ts for e in evs], [200, 300, 400])

    def test_query_events_event_types_or(self) -> None:
        evs = telemetry.query_events(
            event_types=[E.PHASE_CHANGED, E.PHASE_BACKTRACK],
        )
        self.assertEqual(len(evs), 5)

    def test_total_cost_scope_filter(self) -> None:
        self.assertAlmostEqual(
            telemetry.total_cost(), 0.10 + 0.20 + 0.05 + 1.00 + 2.00,
        )
        self.assertAlmostEqual(
            telemetry.total_cost(scope='comics'), 3.00,
        )
        self.assertAlmostEqual(
            telemetry.total_cost(scope='management'), 0.35,
        )

    def test_total_cost_time_range(self) -> None:
        self.assertAlmostEqual(
            telemetry.total_cost(time_range=(150, 450)), 0.20 + 0.05 + 1.00,
        )

    def test_turn_count_filters(self) -> None:
        self.assertEqual(telemetry.turn_count(), 5)
        self.assertEqual(telemetry.turn_count(scope='comics'), 2)

    def test_backtrack_count_by_kind(self) -> None:
        self.assertEqual(telemetry.backtrack_count(), 2)
        self.assertEqual(
            telemetry.backtrack_count(kind='plan_to_intent'), 1,
        )
        self.assertEqual(
            telemetry.backtrack_count(kind='work_to_intent'), 0,
        )

    def test_backtrack_cost_sums_discarded_work(self) -> None:
        self.assertAlmostEqual(telemetry.backtrack_cost(), 1.00)
        self.assertAlmostEqual(
            telemetry.backtrack_cost(kind='plan_to_intent'), 0.30,
        )

    def test_phase_distribution_counts_new_phase(self) -> None:
        dist = telemetry.phase_distribution(scope='comics')
        self.assertEqual(dist, {'planning': 2, 'execution': 1})

    def test_escalation_stats_per_stage(self) -> None:
        stats = telemetry.escalation_stats(scope='management')
        self.assertEqual(stats['requested'], 2)
        self.assertEqual(stats['proxy_answered'], 1)
        self.assertEqual(stats['resolved'], 2)

    def test_proxy_answer_rate(self) -> None:
        rate = telemetry.proxy_answer_rate(scope='management')
        self.assertEqual(rate['total'], 2)
        self.assertEqual(rate['by_proxy'], 1)
        self.assertEqual(rate['by_human'], 1)
        self.assertAlmostEqual(rate['proxy_rate'], 0.5)

    def test_active_sessions_excludes_closed_and_withdrawn(self) -> None:
        active = telemetry.active_sessions()
        self.assertEqual(active, ['s1'])

    def test_gates_awaiting_input_excludes_received(self) -> None:
        gates = telemetry.gates_awaiting_input()
        self.assertEqual(len(gates), 1)
        self.assertEqual(gates[0]['session_id'], 's4')
        self.assertEqual(gates[0]['gate_type'], 'plan_assert')
        self.assertEqual(gates[0]['question_len'], 42)

    def test_withdrawal_phase_distribution(self) -> None:
        dist = telemetry.withdrawal_phase_distribution()
        self.assertEqual(dist, {'planning': 1})


class UnconfiguredTests(unittest.TestCase):
    """Behavior when set_teaparty_home has not been called."""

    def setUp(self) -> None:
        telemetry.reset_for_tests()
        # Clear the env fallback too so the test is hermetic.
        self._prev = os.environ.pop('TEAPARTY_HOME', None)

    def tearDown(self) -> None:
        if self._prev is not None:
            os.environ['TEAPARTY_HOME'] = self._prev
        telemetry.reset_for_tests()

    def test_record_event_without_home_does_not_raise(self) -> None:
        result = telemetry.record_event(E.TURN_START, scope='management')
        self.assertIsNone(result)

    def test_query_events_without_home_returns_empty_list(self) -> None:
        self.assertEqual(telemetry.query_events(), [])


if __name__ == '__main__':
    unittest.main()
