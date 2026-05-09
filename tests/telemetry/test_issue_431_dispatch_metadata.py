"""Specification tests for Issue #431.

Make telemetry.db self-sufficient for cost / Gantt / dispatch-tree analyses
by recording every additive field, table, and event the issue specifies.
Each test maps to one or more acceptance criteria in the issue comment.

The tests drive the public interface (``record_event`` and helpers) and
read back via SQLite directly so the contract is observable from
``telemetry.db`` alone — no stream files, no bus joins, no metadata.json.
"""
from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import unittest

from teaparty import telemetry
from teaparty.telemetry import events as E


def _make_home() -> str:
    home = tempfile.mkdtemp(prefix='telemetry-431-')
    telemetry.set_teaparty_home(home)
    return home


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f'PRAGMA table_info({table})')}


def _indexes(conn: sqlite3.Connection) -> set[str]:
    return {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index' "
        "AND name NOT LIKE 'sqlite_%'"
    )}


def _tables(conn: sqlite3.Connection) -> set[str]:
    return {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' "
        "AND name NOT LIKE 'sqlite_%'"
    )}


class SchemaExtensionTests(unittest.TestCase):
    """AC 9 + AC 11: events table has dispatch-tree linkage columns +
    sidecar tables exist with the expected shape."""

    def setUp(self) -> None:
        telemetry.reset_for_tests()
        self.home = _make_home()

    def tearDown(self) -> None:
        telemetry.reset_for_tests()

    def test_events_table_has_dispatch_tree_linkage_columns(self) -> None:
        # Trigger schema apply.
        telemetry.record_event(E.TURN_START, scope='management')
        db = os.path.join(self.home, 'telemetry.db')
        conn = sqlite3.connect(db)
        try:
            cols = _columns(conn, 'events')
        finally:
            conn.close()
        for required in (
            'turn_id', 'conversation_id', 'parent_session_id',
            'job_id', 'dispatch_depth', 'cost_source',
        ):
            self.assertIn(
                required, cols,
                f'events table is missing required indexed column {required!r}',
            )

    def test_events_table_has_indexes_on_dispatch_tree_columns(self) -> None:
        telemetry.record_event(E.TURN_START, scope='management')
        db = os.path.join(self.home, 'telemetry.db')
        conn = sqlite3.connect(db)
        try:
            idx = _indexes(conn)
        finally:
            conn.close()
        for required in (
            'idx_events_conversation', 'idx_events_parent_session',
            'idx_events_job', 'idx_events_turn_id',
        ):
            self.assertIn(
                required, idx,
                f'expected index {required!r} on events table',
            )

    def test_session_messages_sidecar_table_has_primary_key_on_session_message(
        self,
    ) -> None:
        telemetry.record_event(E.TURN_START, scope='management')
        db = os.path.join(self.home, 'telemetry.db')
        conn = sqlite3.connect(db)
        try:
            self.assertIn(
                'session_messages', _tables(conn),
                'session_messages sidecar table must exist for per-message '
                'dedupe (Issue #431 AC 6)',
            )
            cols = _columns(conn, 'session_messages')
            for required in (
                'session_id', 'message_id', 'ts', 'model',
                'input_tokens', 'output_tokens', 'cache_read_tokens',
                'cache_5m_tokens', 'cache_1h_tokens', 'stop_reason',
            ):
                self.assertIn(
                    required, cols,
                    f'session_messages must have column {required!r}',
                )
            # PRIMARY KEY contract: (session_id, message_id) must be unique.
            pk_cols = [
                row[1] for row in conn.execute(
                    'PRAGMA table_info(session_messages)'
                )
                if row[5] > 0  # row[5] = pk position (>0 means part of PK)
            ]
            self.assertEqual(
                set(pk_cols), {'session_id', 'message_id'},
                'session_messages PRIMARY KEY must be (session_id, message_id) '
                f'— got {pk_cols!r}',
            )
        finally:
            conn.close()

    def test_dispatch_edges_sidecar_table_has_expected_columns(self) -> None:
        telemetry.record_event(E.TURN_START, scope='management')
        db = os.path.join(self.home, 'telemetry.db')
        conn = sqlite3.connect(db)
        try:
            self.assertIn(
                'dispatch_edges', _tables(conn),
                'dispatch_edges sidecar table must exist (Issue #431 AC 7)',
            )
            cols = _columns(conn, 'dispatch_edges')
            for required in (
                'parent_session_id', 'child_session_id', 'member',
                'skill', 'task_summary', 'ts', 'job_id',
            ):
                self.assertIn(
                    required, cols,
                    f'dispatch_edges must have column {required!r}',
                )
        finally:
            conn.close()

    def test_model_pricing_table_seeded_with_current_models(self) -> None:
        telemetry.record_event(E.TURN_START, scope='management')
        db = os.path.join(self.home, 'telemetry.db')
        conn = sqlite3.connect(db)
        try:
            self.assertIn(
                'model_pricing', _tables(conn),
                'model_pricing sidecar table must exist (Issue #431 AC 11)',
            )
            cols = _columns(conn, 'model_pricing')
            for required in (
                'model', 'price_input', 'price_output',
                'price_cache_read', 'price_cache_5m', 'price_cache_1h',
            ):
                self.assertIn(
                    required, cols,
                    f'model_pricing must have column {required!r}',
                )
            models = {
                r[0] for r in conn.execute(
                    'SELECT model FROM model_pricing'
                )
            }
            for model in ('claude-opus-4-7', 'claude-sonnet-4-6',
                          'claude-haiku-4-5'):
                self.assertIn(
                    model, models,
                    f'model_pricing must seed pricing for {model!r}',
                )
            # Prices must be positive (non-zero rates).
            row = conn.execute(
                'SELECT price_input, price_output, price_cache_read, '
                'price_cache_5m, price_cache_1h FROM model_pricing '
                "WHERE model = 'claude-opus-4-7'"
            ).fetchone()
            self.assertTrue(
                all(p > 0 for p in row),
                f'opus pricing must be non-zero, got {row}',
            )
        finally:
            conn.close()

    def test_schema_migration_is_idempotent_across_existing_databases(
        self,
    ) -> None:
        """A pre-existing telemetry.db with the old (Issue #405) schema
        must accept the Issue #431 column additions without error."""
        # Reset and build an old-shape db by hand at the same path.
        telemetry.reset_for_tests()
        old_home = tempfile.mkdtemp(prefix='telemetry-431-old-')
        db = os.path.join(old_home, 'telemetry.db')
        conn = sqlite3.connect(db)
        try:
            conn.execute(
                'CREATE TABLE events (id INTEGER PRIMARY KEY AUTOINCREMENT,'
                'ts REAL NOT NULL, scope TEXT NOT NULL, agent_name TEXT,'
                'session_id TEXT, event_type TEXT NOT NULL, data TEXT NOT NULL,'
                'is_aggregate INTEGER NOT NULL DEFAULT 0)'
            )
            conn.execute(
                'INSERT INTO events (ts, scope, event_type, data) '
                "VALUES (1.0, 'management', 'turn_complete', '{\"cost_usd\": 0.1}')"
            )
            conn.commit()
        finally:
            conn.close()
        # Now point telemetry at this pre-existing db and record an event.
        # The migration must add the new columns and seed sidecar tables
        # without OperationalError on the existing rows.
        telemetry.set_teaparty_home(old_home)
        telemetry.record_event(E.TURN_START, scope='management')
        conn = sqlite3.connect(db)
        try:
            cols = _columns(conn, 'events')
            self.assertIn('conversation_id', cols)
            self.assertIn('job_id', cols)
            self.assertIn('turn_id', cols)
            # Existing rows survive.
            count = conn.execute('SELECT COUNT(*) FROM events').fetchone()[0]
            self.assertEqual(count, 2)
        finally:
            conn.close()


class RecordEventDispatchLinkageTests(unittest.TestCase):
    """AC 9 + AC 4: record_event accepts and persists the linkage kwargs."""

    def setUp(self) -> None:
        telemetry.reset_for_tests()
        self.home = _make_home()

    def tearDown(self) -> None:
        telemetry.reset_for_tests()

    def test_record_event_persists_linkage_kwargs_into_columns(self) -> None:
        telemetry.record_event(
            E.TURN_COMPLETE, scope='comics',
            agent_name='comics-lead', session_id='sess-A',
            data={'cost_usd': 0.10},
            turn_id='turn-1',
            conversation_id='dispatch:abc123',
            parent_session_id='sess-parent',
            job_id='job-2026-05-09-000001',
            dispatch_depth=2,
        )
        db = os.path.join(self.home, 'telemetry.db')
        conn = sqlite3.connect(db)
        try:
            row = conn.execute(
                'SELECT turn_id, conversation_id, parent_session_id, '
                'job_id, dispatch_depth FROM events WHERE session_id=?',
                ('sess-A',),
            ).fetchone()
        finally:
            conn.close()
        self.assertEqual(
            row,
            ('turn-1', 'dispatch:abc123', 'sess-parent',
             'job-2026-05-09-000001', 2),
            'linkage kwargs must be persisted into indexed columns, '
            f'got {row!r}',
        )

    def test_record_event_accepts_missing_linkage_kwargs_for_compat(
        self,
    ) -> None:
        """Existing call sites that do not pass linkage kwargs must still
        succeed — the columns are nullable."""
        rid = telemetry.record_event(
            E.TURN_COMPLETE, scope='management', session_id='sess-B',
            data={'cost_usd': 0.0},
        )
        self.assertIsInstance(
            rid, int,
            'record_event must accept calls without the new linkage kwargs',
        )
        db = os.path.join(self.home, 'telemetry.db')
        conn = sqlite3.connect(db)
        try:
            row = conn.execute(
                'SELECT turn_id, conversation_id, parent_session_id, '
                'job_id, dispatch_depth FROM events WHERE id=?',
                (rid,),
            ).fetchone()
        finally:
            conn.close()
        self.assertEqual(
            row, (None, None, None, None, None),
            'linkage columns must default to NULL when caller omits them',
        )

    def test_turn_id_pairs_turn_start_with_turn_complete(self) -> None:
        """AC 4 — TURN_START and TURN_COMPLETE for the same launch share
        a turn_id, so analysts can pair spans without ordering tricks."""
        telemetry.record_event(
            E.TURN_START, scope='management', session_id='sess-C',
            turn_id='turn-XYZ',
        )
        telemetry.record_event(
            E.TURN_COMPLETE, scope='management', session_id='sess-C',
            data={'cost_usd': 0.05}, turn_id='turn-XYZ',
        )
        db = os.path.join(self.home, 'telemetry.db')
        conn = sqlite3.connect(db)
        try:
            rows = conn.execute(
                'SELECT event_type FROM events WHERE turn_id=? ORDER BY ts, id',
                ('turn-XYZ',),
            ).fetchall()
        finally:
            conn.close()
        self.assertEqual(
            [r[0] for r in rows],
            [E.TURN_START, E.TURN_COMPLETE],
            'turn_id index must return both span endpoints in order',
        )


class TurnStartTaxonomyTests(unittest.TestCase):
    """AC 2: TURN_START.data.trigger ∈ {new, dispatch, resume, wake}."""

    def setUp(self) -> None:
        telemetry.reset_for_tests()
        self.home = _make_home()

    def tearDown(self) -> None:
        telemetry.reset_for_tests()

    def test_all_four_triggers_are_distinguishable_in_telemetry(self) -> None:
        for trig in ('new', 'dispatch', 'resume', 'wake'):
            telemetry.record_event(
                E.TURN_START, scope='management',
                session_id=f'sess-{trig}',
                data={'trigger': trig},
            )
        evs = telemetry.query_events(event_type=E.TURN_START)
        triggers = {e.data.get('trigger') for e in evs}
        self.assertEqual(
            triggers, {'new', 'dispatch', 'resume', 'wake'},
            'all four trigger taxa must round-trip through telemetry — '
            f'got {triggers}',
        )

    def test_teaparty_turns_per_session_query_is_answerable_from_telemetry(
        self,
    ) -> None:
        """The motivating query: how many teaparty turns did session X take?
        Must be answerable without leaving the events table."""
        # Three TURN_STARTs for one session: an initial dispatch, then a
        # resume and a wake (the spec's two new categories).
        telemetry.record_event(
            E.TURN_START, scope='management', session_id='sess-X',
            data={'trigger': 'dispatch'},
        )
        telemetry.record_event(
            E.TURN_START, scope='management', session_id='sess-X',
            data={'trigger': 'resume'},
        )
        telemetry.record_event(
            E.TURN_START, scope='management', session_id='sess-X',
            data={'trigger': 'wake'},
        )
        db = os.path.join(self.home, 'telemetry.db')
        conn = sqlite3.connect(db)
        try:
            count = conn.execute(
                "SELECT COUNT(*) FROM events "
                "WHERE event_type='turn_start' AND session_id='sess-X'"
            ).fetchone()[0]
        finally:
            conn.close()
        self.assertEqual(
            count, 3,
            'pure-SQL teaparty-turns-per-session count must equal the '
            f'number of TURN_START rows — got {count}',
        )


class TurnCompleteAdditiveFieldsTests(unittest.TestCase):
    """AC 1 + AC 3: TURN_COMPLETE carries the SDK result fields and a
    cost_source tag identifying the authoritative source."""

    def setUp(self) -> None:
        telemetry.reset_for_tests()
        self.home = _make_home()

    def tearDown(self) -> None:
        telemetry.reset_for_tests()

    def test_turn_complete_round_trips_all_sdk_result_fields(self) -> None:
        sdk_payload = {
            # Existing fields (do not change).
            'duration_ms': 12_500,
            'wall_duration_ms': 13_200,
            'cost_usd': 0.0123,
            'input_tokens': 500,
            'output_tokens': 1500,
            'cache_read_tokens': 8000,
            'cache_create_tokens': 2000,
            'tools_called': {'Bash': 7, 'Read': 3},
            'exit_code': 0,
            'response_text_len': 4321,
            # Additive fields (Issue #431).
            'num_turns': 14,
            'duration_api_ms': 11_800,
            'stop_reason': 'end_turn',
            'is_error': False,
            'api_error_status': None,
            'cache_5m_tokens': 1500,
            'cache_1h_tokens': 500,
            'model': 'claude-opus-4-7',
            'claude_session_uuid': 'abc-uuid-xyz',
        }
        telemetry.record_event(
            E.TURN_COMPLETE, scope='management',
            agent_name='exec-lead', session_id='sess-Q',
            data=sdk_payload,
            cost_source='stream_result',
        )
        ev = telemetry.query_events(event_type=E.TURN_COMPLETE)[0]
        for k, v in sdk_payload.items():
            self.assertEqual(
                ev.data.get(k), v,
                f'TURN_COMPLETE.data.{k} must round-trip — '
                f'expected {v!r}, got {ev.data.get(k)!r}',
            )

    def test_turn_complete_cost_source_is_stored_as_indexed_column(
        self,
    ) -> None:
        """cost_source belongs on the events table as a column (not a
        JSON key) so analysts can disagree-detect across sources with a
        plain GROUP BY."""
        for src, sid in (
            ('stream_result', 'sess-1'),
            ('bridge_turn', 'sess-2'),
            ('computed', 'sess-3'),
        ):
            telemetry.record_event(
                E.TURN_COMPLETE, scope='management',
                session_id=sid,
                data={'cost_usd': 0.10},
                cost_source=src,
            )
        db = os.path.join(self.home, 'telemetry.db')
        conn = sqlite3.connect(db)
        try:
            rows = dict(conn.execute(
                'SELECT session_id, cost_source FROM events '
                "WHERE event_type='turn_complete' ORDER BY session_id"
            ).fetchall())
        finally:
            conn.close()
        self.assertEqual(
            rows,
            {'sess-1': 'stream_result',
             'sess-2': 'bridge_turn',
             'sess-3': 'computed'},
            f'cost_source must be indexed-column accessible — got {rows!r}',
        )


class ToolCallCompleteTests(unittest.TestCase):
    """AC 5: per-tool-call records subsume the tools_called dict."""

    def setUp(self) -> None:
        telemetry.reset_for_tests()
        self.home = _make_home()

    def tearDown(self) -> None:
        telemetry.reset_for_tests()

    def test_tool_call_complete_carries_required_fields(self) -> None:
        telemetry.record_event(
            E.TOOL_CALL_COMPLETE, scope='management',
            agent_name='exec-lead', session_id='sess-T',
            data={
                'tool_use_id': 'toolu_xyz',
                'tool_name': 'mcp__teaparty-config__Delegate',
                'mcp_server': 'teaparty-config',
                'start_ts': 1000.0,
                'end_ts': 1003.5,
                'duration_ms': 3500,
                'is_error': False,
                'input_size': 250,
                'output_size': 800,
                'parent_session_id': 'sess-T',
                'child_session_id': 'sess-child-1',
            },
        )
        evs = telemetry.query_events(event_type=E.TOOL_CALL_COMPLETE)
        self.assertEqual(len(evs), 1)
        d = evs[0].data
        self.assertEqual(d['tool_name'],
                         'mcp__teaparty-config__Delegate')
        self.assertEqual(d['mcp_server'], 'teaparty-config')
        self.assertEqual(d['child_session_id'], 'sess-child-1')
        self.assertEqual(d['duration_ms'], 3500)

    def test_tools_called_count_is_derivable_from_tool_call_complete(
        self,
    ) -> None:
        """The current ``tools_called`` count dict on TURN_COMPLETE is
        subsumed by `SELECT tool_name, COUNT(*)` over TOOL_CALL_COMPLETE."""
        for name, n in (('Bash', 7), ('Read', 3), ('Edit', 2)):
            for _ in range(n):
                telemetry.record_event(
                    E.TOOL_CALL_COMPLETE, scope='management',
                    session_id='sess-U',
                    data={'tool_name': name, 'is_error': False},
                )
        db = os.path.join(self.home, 'telemetry.db')
        conn = sqlite3.connect(db)
        try:
            rows = dict(conn.execute(
                "SELECT json_extract(data, '$.tool_name'), COUNT(*) "
                "FROM events WHERE event_type='tool_call_complete' "
                "GROUP BY json_extract(data, '$.tool_name')"
            ).fetchall())
        finally:
            conn.close()
        self.assertEqual(
            rows, {'Bash': 7, 'Read': 3, 'Edit': 2},
            f'tools_called count must be reproducible by GROUP BY — '
            f'got {rows!r}',
        )

    def test_tool_call_latency_outliers_query_runs_against_telemetry(
        self,
    ) -> None:
        """The issue's outlier query must execute against telemetry.db
        without joins to any external source."""
        for dur in (100, 500, 5000, 30_000):
            telemetry.record_event(
                E.TOOL_CALL_COMPLETE, scope='management',
                session_id='sess-V',
                data={'tool_name': 'Bash', 'mcp_server': None,
                      'duration_ms': dur, 'is_error': False},
            )
        db = os.path.join(self.home, 'telemetry.db')
        conn = sqlite3.connect(db)
        try:
            row = conn.execute(
                "SELECT json_extract(data, '$.tool_name'), "
                "MAX(json_extract(data, '$.duration_ms')), COUNT(*) "
                "FROM events WHERE event_type='tool_call_complete' "
                "GROUP BY json_extract(data, '$.tool_name') "
                "ORDER BY MAX(json_extract(data, '$.duration_ms')) DESC "
                "LIMIT 1"
            ).fetchone()
        finally:
            conn.close()
        self.assertEqual(
            row[0], 'Bash',
            f'top-tool query must return Bash — got {row[0]!r}',
        )
        self.assertEqual(
            row[1], 30_000,
            f'max duration must be 30000ms — got {row[1]!r}',
        )
        self.assertEqual(
            row[2], 4,
            f'tool count must be 4 — got {row[2]!r}',
        )


class MessageRecordedDedupeTests(unittest.TestCase):
    """AC 6: MESSAGE_RECORDED is dedupe-keyed on (session_id, message_id)."""

    def setUp(self) -> None:
        telemetry.reset_for_tests()
        self.home = _make_home()

    def tearDown(self) -> None:
        telemetry.reset_for_tests()

    def test_record_message_dedupes_on_session_id_and_message_id(
        self,
    ) -> None:
        """One Claude API response can emit multiple SDK ``assistant``
        events sharing one message_id and one usage object. Naively
        summing all of them double-counts. record_message must enforce
        first-write-wins via the (session_id, message_id) PRIMARY KEY."""
        usage = {
            'model': 'claude-opus-4-7',
            'input_tokens': 100,
            'output_tokens': 200,
            'cache_read_tokens': 8000,
            'cache_5m_tokens': 1500,
            'cache_1h_tokens': 500,
            'stop_reason': 'tool_use',
        }
        # Three SDK ``assistant`` events arrive with the same message_id
        # because the response had three content blocks (thinking,
        # tool_use, text). They share one usage object.
        for _ in range(3):
            telemetry.record_message(
                session_id='sess-M', message_id='msg_dedupe_1',
                ts=1000.0, **usage,
            )
        db = os.path.join(self.home, 'telemetry.db')
        conn = sqlite3.connect(db)
        try:
            row_count = conn.execute(
                'SELECT COUNT(*) FROM session_messages '
                'WHERE session_id=? AND message_id=?',
                ('sess-M', 'msg_dedupe_1'),
            ).fetchone()[0]
            row = conn.execute(
                'SELECT input_tokens, output_tokens FROM session_messages '
                'WHERE session_id=? AND message_id=?',
                ('sess-M', 'msg_dedupe_1'),
            ).fetchone()
        finally:
            conn.close()
        self.assertEqual(
            row_count, 1,
            f'session_messages must contain exactly ONE row per '
            f'(session_id, message_id) — got {row_count}',
        )
        self.assertEqual(
            row, (100, 200),
            f'first-write-wins: tokens must be the first usage observed, '
            f'not summed — got {row}',
        )

    def test_record_message_emits_message_recorded_event_only_once(
        self,
    ) -> None:
        """The MESSAGE_RECORDED event is for live broadcasters; firing
        it on every duplicate write would flood the WebSocket channel
        and overcount in any downstream that joins on the events
        table. record_message must emit the event only on a fresh
        insert (rowcount > 0)."""
        for _ in range(3):
            telemetry.record_message(
                session_id='sess-O', message_id='msg-once', ts=1000.0,
                model='claude-opus-4-7',
                input_tokens=10, output_tokens=20,
                cache_read_tokens=0, cache_5m_tokens=0,
                cache_1h_tokens=0, stop_reason='end_turn',
            )
        events = telemetry.query_events(event_type=E.MESSAGE_RECORDED)
        msg_events = [e for e in events
                      if e.data.get('message_id') == 'msg-once']
        self.assertEqual(
            len(msg_events), 1,
            f'MESSAGE_RECORDED must fire exactly once per unique '
            f'message_id even when record_message is called repeatedly '
            f'— got {len(msg_events)}',
        )

    def test_record_message_tracks_distinct_messages_separately(self) -> None:
        for mid, n_in in (('msg-1', 100), ('msg-2', 250)):
            telemetry.record_message(
                session_id='sess-N', message_id=mid, ts=1000.0,
                model='claude-opus-4-7',
                input_tokens=n_in, output_tokens=42,
                cache_read_tokens=0, cache_5m_tokens=0,
                cache_1h_tokens=0, stop_reason='end_turn',
            )
        db = os.path.join(self.home, 'telemetry.db')
        conn = sqlite3.connect(db)
        try:
            rows = dict(conn.execute(
                'SELECT message_id, input_tokens FROM session_messages '
                'WHERE session_id=?',
                ('sess-N',),
            ).fetchall())
        finally:
            conn.close()
        self.assertEqual(
            rows, {'msg-1': 100, 'msg-2': 250},
            f'distinct message_ids must produce distinct rows — got {rows!r}',
        )


class DispatchEdgeTests(unittest.TestCase):
    """AC 7: Delegate edges land in dispatch_edges sidecar."""

    def setUp(self) -> None:
        telemetry.reset_for_tests()
        self.home = _make_home()

    def tearDown(self) -> None:
        telemetry.reset_for_tests()

    def test_record_dispatch_edge_persists_to_sidecar(self) -> None:
        telemetry.record_dispatch_edge(
            parent_session_id='sess-parent',
            child_session_id='sess-child',
            member='qa-reviewer', skill='attempt-task',
            task_summary='review the PR for issue #N',
            ts=1234567.0, job_id='job-abc',
        )
        db = os.path.join(self.home, 'telemetry.db')
        conn = sqlite3.connect(db)
        try:
            row = conn.execute(
                'SELECT parent_session_id, child_session_id, member, '
                'skill, ts, job_id FROM dispatch_edges'
            ).fetchone()
        finally:
            conn.close()
        self.assertEqual(
            row,
            ('sess-parent', 'sess-child', 'qa-reviewer',
             'attempt-task', 1234567.0, 'job-abc'),
            f'dispatch_edges row must round-trip — got {row!r}',
        )

    def test_dispatch_tree_for_job_is_query_able_in_pure_sql(self) -> None:
        """The motivating dispatch-tree query must run against
        telemetry.db without leaving the database."""
        telemetry.record_dispatch_edge(
            parent_session_id='sess-root', child_session_id='sess-A',
            member='exec-lead', skill='attempt-task',
            task_summary='exec', ts=1.0, job_id='job-J',
        )
        telemetry.record_dispatch_edge(
            parent_session_id='sess-A', child_session_id='sess-B',
            member='developer', skill=None,
            task_summary='write code', ts=2.0, job_id='job-J',
        )
        telemetry.record_dispatch_edge(
            parent_session_id='sess-A', child_session_id='sess-C',
            member='qa-reviewer', skill=None,
            task_summary='review', ts=3.0, job_id='job-J',
        )
        # Different job — must not appear in the result.
        telemetry.record_dispatch_edge(
            parent_session_id='sess-other', child_session_id='sess-Z',
            member='developer', skill=None,
            task_summary='other', ts=10.0, job_id='job-OTHER',
        )
        db = os.path.join(self.home, 'telemetry.db')
        conn = sqlite3.connect(db)
        try:
            rows = conn.execute(
                'SELECT child_session_id, member FROM dispatch_edges '
                'WHERE job_id=? ORDER BY ts',
                ('job-J',),
            ).fetchall()
        finally:
            conn.close()
        self.assertEqual(
            rows,
            [('sess-A', 'exec-lead'),
             ('sess-B', 'developer'),
             ('sess-C', 'qa-reviewer')],
            f'dispatch_edges must be queryable by job_id — got {rows!r}',
        )


class ProxyInvokedTests(unittest.TestCase):
    """AC 8: PROXY_INVOKED links asking session to proxy session, and the
    proxy's own turn events carry parent_session_id = asking_session_id."""

    def setUp(self) -> None:
        telemetry.reset_for_tests()
        self.home = _make_home()

    def tearDown(self) -> None:
        telemetry.reset_for_tests()

    def test_proxy_invoked_event_carries_dispatch_edge_metadata(self) -> None:
        telemetry.record_event(
            E.PROXY_INVOKED, scope='management',
            agent_name='exec-lead', session_id='sess-asking',
            data={
                'asking_session_id': 'sess-asking',
                'asking_agent_name': 'exec-lead',
                'proxy_session_id': 'proxy-jobid-deadbeef',
                'question_hash': 'sha1-abc',
                'question_first_500': 'Should we use an X or a Y?',
                'job_id': 'job-J',
            },
            ts=2000.0,
            parent_session_id=None,
            job_id='job-J',
        )
        evs = telemetry.query_events(event_type=E.PROXY_INVOKED)
        self.assertEqual(len(evs), 1)
        d = evs[0].data
        self.assertEqual(d['asking_session_id'], 'sess-asking')
        self.assertEqual(d['proxy_session_id'], 'proxy-jobid-deadbeef')
        self.assertTrue(
            d['question_first_500'].startswith('Should we'),
            'question_first_500 must carry the leading prose',
        )

    def test_proxy_overhead_query_rolls_up_via_parent_session_id(
        self,
    ) -> None:
        """The motivating query: proxy overhead per job. Must run via the
        proxy session's own TURN_COMPLETE rows joined on parent_session_id
        ← PROXY_INVOKED.proxy_session_id."""
        # The asking agent fires AskQuestion.
        telemetry.record_event(
            E.PROXY_INVOKED, scope='management',
            agent_name='exec-lead', session_id='sess-asking',
            data={
                'asking_session_id': 'sess-asking',
                'proxy_session_id': 'proxy-J-1',
                'question_hash': 'h1', 'question_first_500': '?',
                'job_id': 'job-J',
            },
            job_id='job-J',
        )
        # The proxy session runs and incurs cost — its TURN_COMPLETE
        # carries parent_session_id = the asking session.
        telemetry.record_event(
            E.TURN_COMPLETE, scope='management',
            agent_name='proxy', session_id='proxy-J-1',
            data={'cost_usd': 0.42},
            parent_session_id='sess-asking',
            job_id='job-J',
        )
        # A second proxy invocation in the same job.
        telemetry.record_event(
            E.PROXY_INVOKED, scope='management',
            agent_name='exec-lead', session_id='sess-asking',
            data={
                'asking_session_id': 'sess-asking',
                'proxy_session_id': 'proxy-J-2',
                'question_hash': 'h2', 'question_first_500': '?',
                'job_id': 'job-J',
            },
            job_id='job-J',
        )
        telemetry.record_event(
            E.TURN_COMPLETE, scope='management',
            agent_name='proxy', session_id='proxy-J-2',
            data={'cost_usd': 0.13},
            parent_session_id='sess-asking',
            job_id='job-J',
        )
        # Unrelated job — must not contribute to the rollup.
        telemetry.record_event(
            E.TURN_COMPLETE, scope='management',
            agent_name='proxy', session_id='proxy-OTHER',
            data={'cost_usd': 99.99},
            parent_session_id='sess-other-asking',
            job_id='job-OTHER',
        )
        db = os.path.join(self.home, 'telemetry.db')
        conn = sqlite3.connect(db)
        try:
            cost = conn.execute(
                "SELECT SUM(json_extract(data, '$.cost_usd')) "
                "FROM events tc "
                "WHERE tc.event_type='turn_complete' "
                "AND tc.session_id IN ("
                "  SELECT json_extract(data, '$.proxy_session_id') "
                "  FROM events WHERE event_type='proxy_invoked' "
                "  AND job_id=?)",
                ('job-J',),
            ).fetchone()[0]
        finally:
            conn.close()
        self.assertAlmostEqual(
            cost, 0.55, places=6,
            msg=f'proxy overhead for job-J must equal 0.42 + 0.13 = 0.55 — '
                f'got {cost}',
        )


class JobCreatedTests(unittest.TestCase):
    """AC 10: JOB_CREATED carries the job-level metadata block."""

    def setUp(self) -> None:
        telemetry.reset_for_tests()
        self.home = _make_home()

    def tearDown(self) -> None:
        telemetry.reset_for_tests()

    def test_job_created_records_full_metadata(self) -> None:
        telemetry.record_event(
            E.JOB_CREATED, scope='comics',
            data={
                'job_id': 'job-2026-05-09-000001',
                'project': 'comics',
                'slug': 'fix-issue-431',
                'classification': 'fix-issue',
                'prompt_text': 'Fix the bug',
                'prompt_hash': 'sha1abc',
                'prompt_bytes': 11,
                'branch': 'fix/issue-431',
                'status': 'open',
                'created_at': '2026-05-09T12:00:00Z',
            },
            job_id='job-2026-05-09-000001',
        )
        evs = telemetry.query_events(event_type=E.JOB_CREATED)
        self.assertEqual(len(evs), 1)
        d = evs[0].data
        for key in (
            'job_id', 'project', 'slug', 'classification', 'prompt_text',
            'prompt_hash', 'prompt_bytes', 'branch', 'status', 'created_at',
        ):
            self.assertIn(
                key, d,
                f'JOB_CREATED.data must include {key!r} — got {sorted(d)}',
            )

    def test_byte_identical_prompts_group_by_prompt_hash(self) -> None:
        """The motivating analytics query: how many times have we run a
        byte-identical prompt? Must be answerable by GROUP BY prompt_hash."""
        for jid, slug in (
            ('job-A', 'redo-1'), ('job-B', 'redo-1'), ('job-C', 'other'),
        ):
            telemetry.record_event(
                E.JOB_CREATED, scope='comics',
                data={
                    'job_id': jid, 'project': 'comics', 'slug': slug,
                    'classification': 'fix-issue',
                    'prompt_hash': 'h-X' if slug == 'redo-1' else 'h-Y',
                    'prompt_bytes': 99, 'created_at': '...'
                },
                job_id=jid,
            )
        db = os.path.join(self.home, 'telemetry.db')
        conn = sqlite3.connect(db)
        try:
            rows = dict(conn.execute(
                "SELECT json_extract(data, '$.prompt_hash'), COUNT(*) "
                "FROM events WHERE event_type='job_created' "
                "GROUP BY json_extract(data, '$.prompt_hash')"
            ).fetchall())
        finally:
            conn.close()
        self.assertEqual(
            rows, {'h-X': 2, 'h-Y': 1},
            f'prompt-hash GROUP BY must return 2 + 1 = 3 jobs — got {rows!r}',
        )


class ConversationSpanTests(unittest.TestCase):
    """AC 12: conversation span events bookend the conversation lifecycle."""

    def setUp(self) -> None:
        telemetry.reset_for_tests()
        self.home = _make_home()

    def tearDown(self) -> None:
        telemetry.reset_for_tests()

    def test_conversation_open_and_close_events_are_recorded(self) -> None:
        telemetry.record_event(
            E.CONVERSATION_OPENED, scope='management',
            session_id='sess-A',
            data={'conversation_id': 'dispatch:abc', 'opened_by': 'exec-lead'},
            conversation_id='dispatch:abc',
        )
        telemetry.record_event(
            E.CONVERSATION_CLOSED, scope='management',
            session_id='sess-A',
            data={'conversation_id': 'dispatch:abc', 'closed_by': 'exec-lead',
                  'merge_status': 'clean'},
            conversation_id='dispatch:abc',
        )
        db = os.path.join(self.home, 'telemetry.db')
        conn = sqlite3.connect(db)
        try:
            row_types = [r[0] for r in conn.execute(
                "SELECT event_type FROM events "
                "WHERE conversation_id='dispatch:abc' ORDER BY ts, id"
            ).fetchall()]
        finally:
            conn.close()
        self.assertEqual(
            row_types,
            [E.CONVERSATION_OPENED, E.CONVERSATION_CLOSED],
            'conversation span must contain open + close events keyed by '
            f'conversation_id — got {row_types!r}',
        )


class BackwardCompatibilityTests(unittest.TestCase):
    """AC 14 + AC 15: forward-only and no regressions."""

    def setUp(self) -> None:
        telemetry.reset_for_tests()
        self.home = _make_home()

    def tearDown(self) -> None:
        telemetry.reset_for_tests()

    def test_query_events_works_with_old_shape_rows(self) -> None:
        """A row inserted before #431 (no linkage columns populated) must
        still come back from query_events and not crash any aggregator."""
        # Insert an old-shape row directly via the connection to bypass
        # any new defaults the writer applies.
        telemetry.record_event(E.TURN_START, scope='management')  # bootstrap
        db = os.path.join(self.home, 'telemetry.db')
        conn = sqlite3.connect(db)
        try:
            conn.execute(
                'INSERT INTO events (ts, scope, event_type, data) '
                'VALUES (?, ?, ?, ?)',
                (1000.0, 'management', E.TURN_COMPLETE,
                 json.dumps({'cost_usd': 1.23})),
            )
            conn.commit()
        finally:
            conn.close()
        # The query helper must not raise and must return both rows.
        evs = telemetry.query_events(event_type=E.TURN_COMPLETE)
        self.assertEqual(len(evs), 1)
        # Aggregators must tolerate the missing keys.
        cost = telemetry.total_cost()
        self.assertAlmostEqual(
            cost, 1.23, places=6,
            msg=f'total_cost must accept legacy rows — got {cost}',
        )

    def test_existing_event_type_constants_remain_unchanged(self) -> None:
        """Don't rename the existing event-type constants (call sites
        across orchestrator/bridge depend on them)."""
        # Sample of the constants the existing call sites import.
        self.assertEqual(E.TURN_START, 'turn_start')
        self.assertEqual(E.TURN_COMPLETE, 'turn_complete')
        self.assertEqual(E.PROXY_CONSIDERED, 'proxy_considered')
        self.assertEqual(E.JOB_CREATED, 'job_created')
        self.assertEqual(E.SESSION_CREATE, 'session_create')

    def test_new_event_type_constants_are_defined(self) -> None:
        for name in (
            'TOOL_CALL_COMPLETE', 'MESSAGE_RECORDED',
            'DISPATCH_EDGE', 'PROXY_INVOKED',
            'CONVERSATION_OPENED', 'CONVERSATION_CLOSED',
        ):
            self.assertTrue(
                hasattr(E, name),
                f'teaparty.telemetry.events must define {name!r}',
            )


if __name__ == '__main__':
    unittest.main()
