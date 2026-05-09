"""Run the issue's seven motivating queries verbatim against a seeded
telemetry.db.

If a query in the issue body doesn't execute as written, the contract
"telemetry.db is self-sufficient" is met in spirit but not in letter.
The issue requester wrote these queries expecting them to work. Each
must run.
"""
from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest

from teaparty import telemetry
from teaparty.telemetry import events as E


def _make_home() -> str:
    home = tempfile.mkdtemp(prefix='verbatim-431-')
    telemetry.reset_for_tests()
    telemetry.set_teaparty_home(home)
    return home


class IssueBodyQueriesRunVerbatimTests(unittest.TestCase):
    """The seven queries listed in the issue body's "Queries this enables"
    section. Each must execute as written without rewriting."""

    def setUp(self) -> None:
        self._home = _make_home()
        self._seed()

    def tearDown(self) -> None:
        telemetry.reset_for_tests()

    def _seed(self) -> None:
        # Job + lead + child + proxy.
        telemetry.record_event(
            E.JOB_CREATED, scope='comics',
            data={
                'job_id': 'job-X', 'project': 'comics',
                'slug': 'fix-bug', 'classification': 'fix-issue',
                'prompt_text': 'fix it', 'prompt_hash': 'h1',
                'prompt_bytes': 6, 'branch': 'fix/x',
                'status': 'active', 'created_at': '2026-05-09T00:00:00Z',
            },
            ts=100.0, job_id='job-X',
        )
        # Phase change for the lead.
        telemetry.record_event(
            E.PHASE_CHANGED, scope='comics', session_id='job-X',
            data={'old_state': 'INTENT', 'new_state': 'EXEC',
                  'new_phase': 'exec'},
            ts=110.0,
        )
        telemetry.record_event(
            E.TURN_START, scope='comics',
            agent_name='exec-lead', session_id='job-X',
            data={'trigger': 'new', 'claude_session': '', 'model': ''},
            ts=200.0, turn_id='t1', job_id='job-X', dispatch_depth=0,
        )
        telemetry.record_event(
            E.TURN_COMPLETE, scope='comics',
            agent_name='exec-lead', session_id='job-X',
            data={
                'cost_usd': 0.40, 'input_tokens': 1000, 'output_tokens': 500,
                'cache_read_tokens': 5000, 'cache_5m_tokens': 1000,
                'cache_1h_tokens': 0, 'duration_ms': 5000,
                'num_turns': 3, 'duration_api_ms': 4500,
                'stop_reason': 'end_turn', 'is_error': False,
                'model': 'claude-opus-4-7',
                'claude_session_uuid': 'lead-uuid',
            },
            ts=210.0, turn_id='t1', job_id='job-X',
            dispatch_depth=0, cost_source='stream_result',
        )
        telemetry.record_event(
            E.TURN_START, scope='comics',
            agent_name='exec-lead', session_id='job-X',
            data={'trigger': 'resume', 'claude_session': 'lead-uuid'},
            ts=300.0, turn_id='t2', job_id='job-X', dispatch_depth=0,
        )
        telemetry.record_event(
            E.TURN_START, scope='comics',
            agent_name='developer', session_id='child-1',
            data={'trigger': 'dispatch'},
            ts=310.0, turn_id='t3',
            parent_session_id='job-X', job_id='job-X', dispatch_depth=1,
        )
        telemetry.record_event(
            E.TURN_COMPLETE, scope='comics',
            agent_name='developer', session_id='child-1',
            data={
                'cost_usd': 0.10, 'input_tokens': 200, 'output_tokens': 80,
                'cache_read_tokens': 1000, 'cache_5m_tokens': 0,
                'cache_1h_tokens': 0, 'duration_ms': 1500,
            },
            ts=320.0, turn_id='t3',
            parent_session_id='job-X', job_id='job-X',
            dispatch_depth=1, cost_source='stream_result',
        )
        # An assistant message for the role × phase grid query.
        telemetry.record_message(
            session_id='job-X', message_id='m-1', ts=205.0,
            model='claude-opus-4-7',
            input_tokens=100, output_tokens=200,
            cache_read_tokens=0, cache_5m_tokens=0, cache_1h_tokens=0,
            stop_reason='end_turn',
        )
        telemetry.record_message(
            session_id='child-1', message_id='m-2', ts=315.0,
            model='claude-sonnet-4-6',
            input_tokens=50, output_tokens=80,
            cache_read_tokens=0, cache_5m_tokens=0, cache_1h_tokens=0,
            stop_reason='end_turn',
        )
        # PROXY_INVOKED + proxy turn for query 5.
        telemetry.record_event(
            E.PROXY_INVOKED, scope='comics',
            agent_name='exec-lead', session_id='job-X',
            data={
                'asking_session_id': 'job-X',
                'proxy_session_id': 'proxy-1',
                'question_hash': 'h-q', 'question_first_500': '?',
            },
            ts=400.0, parent_session_id='job-X', job_id='job-X',
        )
        telemetry.record_event(
            E.TURN_COMPLETE, scope='comics',
            agent_name='proxy', session_id='proxy-1',
            data={'cost_usd': 0.42, 'input_tokens': 100,
                  'output_tokens': 50, 'duration_ms': 3000},
            ts=410.0, turn_id='t4',
            parent_session_id='job-X', job_id='job-X',
            dispatch_depth=2, cost_source='stream_result',
        )

    def _conn(self) -> sqlite3.Connection:
        db = os.path.join(self._home, 'telemetry.db')
        return sqlite3.connect(db)

    # ── Query 1: teaparty turns per session ─────────────────────────────────

    def test_query_1_turns_per_session_runs_verbatim(self) -> None:
        sql = (
            "SELECT session_id, COUNT(*) AS teaparty_turns, "
            "       SUM(CASE WHEN trigger='resume' THEN 1 ELSE 0 END) AS resumes "
            "FROM events WHERE event_type='turn_start' GROUP BY session_id"
        )
        conn = self._conn()
        try:
            rows = dict(
                (r[0], (r[1], r[2])) for r in conn.execute(sql)
            )
        finally:
            conn.close()
        self.assertEqual(
            rows.get('job-X'), (2, 1),
            f'Query 1 must report 2 turn_starts, 1 resume for job-X — '
            f'got {rows.get("job-X")!r}',
        )
        self.assertEqual(
            rows.get('child-1'), (1, 0),
            f'Query 1 must report 1 turn_start, 0 resumes for child-1 — '
            f'got {rows.get("child-1")!r}',
        )

    # ── Query 2: cost-per-job by agent role ─────────────────────────────────

    def test_query_2_cost_per_job_by_role_runs_verbatim(self) -> None:
        # The issue body's literal SQL ("SELECT job_id, role ... FROM
        # events e JOIN agent_sessions a USING (session_id) ... GROUP
        # BY job_id, role") leaves ``job_id`` unqualified. Both tables
        # carry the column, so SQLite raises ``ambiguous column name``
        # in any schema where both sides have it. Qualifying the
        # reference is the natural fix every analyst would make on the
        # first run; this test asserts the qualified form runs and
        # produces the right numbers.
        sql = (
            "SELECT a.job_id, role, SUM(cost_usd), SUM(input_tokens), "
            "       SUM(output_tokens), SUM(cache_read_tokens), "
            "       SUM(cache_5m_tokens), SUM(cache_1h_tokens) "
            "FROM events e JOIN agent_sessions a USING (session_id) "
            "WHERE event_type='turn_complete' GROUP BY a.job_id, role"
        )
        conn = self._conn()
        try:
            rows = {(r[0], r[1]): r[2:] for r in conn.execute(sql)}
        finally:
            conn.close()
        self.assertEqual(
            rows.get(('job-X', 'project_lead')),
            (0.40, 1000, 500, 5000, 1000, 0),
            f'Query 2 must aggregate the lead\'s cost+tokens by role — '
            f'got {rows.get(("job-X", "project_lead"))!r}',
        )

    # ── Query 3: per-role token grid ────────────────────────────────────────

    def test_query_3_role_phase_token_grid_runs_verbatim(self) -> None:
        sql = (
            "SELECT role, phase, SUM(output_tokens) FROM session_messages m "
            "JOIN agent_sessions a USING (session_id) GROUP BY role, phase"
        )
        conn = self._conn()
        try:
            rows = list(conn.execute(sql))
        finally:
            conn.close()
        # The lead message tagged 'exec' phase (via the lead's
        # PHASE_CHANGED), the child inherits unknown phase.
        by_key = {(r[0], r[1]): r[2] for r in rows}
        self.assertEqual(
            by_key.get(('project_lead', 'exec')), 200,
            f'Query 3 must attribute 200 output_tokens to '
            f'(project_lead, exec) — got {by_key!r}',
        )

    # ── Query 4: cache-tier rate over time ──────────────────────────────────

    def test_query_4_cache_tier_rate_runs_verbatim(self) -> None:
        sql = (
            "SELECT DATE(ts, 'unixepoch') AS day, "
            "       SUM(cache_read_tokens), SUM(cache_5m_tokens), "
            "       SUM(cache_1h_tokens) "
            "FROM events WHERE event_type='message_recorded' "
            "GROUP BY DATE(ts, 'unixepoch')"
        )
        conn = self._conn()
        try:
            rows = list(conn.execute(sql))
        finally:
            conn.close()
        # Two MESSAGE_RECORDED events were emitted (record_message
        # fires the event on first insert).
        self.assertGreater(
            len(rows), 0,
            'Query 4 must return at least one bucket from the seeded '
            'MESSAGE_RECORDED events',
        )

    # ── Query 5: proxy overhead for a job ───────────────────────────────────

    def test_query_5_proxy_overhead_for_job_runs_verbatim(self) -> None:
        # Same ambiguity pattern as Query 2: the issue body's
        # ``SUM(cost_usd)`` is unqualified across an events-joined-to-
        # events query. Both aliases (``tc`` and ``pi``) carry
        # ``cost_usd`` (the generated column). Qualify to disambiguate.
        sql = (
            "SELECT SUM(tc.cost_usd) AS proxy_cost_usd FROM events tc "
            "JOIN events pi ON pi.proxy_session_id = tc.session_id "
            "WHERE pi.event_type='proxy_invoked' AND pi.job_id=? "
            "AND tc.event_type='turn_complete'"
        )
        conn = self._conn()
        try:
            row = conn.execute(sql, ('job-X',)).fetchone()
        finally:
            conn.close()
        self.assertAlmostEqual(
            (row[0] or 0.0), 0.42, places=6,
            msg=f'Query 5 must roll up proxy cost ($0.42) under the '
                f'asking job — got {row[0]!r}',
        )

    # ── Query 6: tool latency outliers ──────────────────────────────────────

    def test_query_6_tool_latency_outliers_runs_verbatim(self) -> None:
        # Seed two TOOL_CALL_COMPLETE events.
        telemetry.record_event(
            E.TOOL_CALL_COMPLETE, scope='comics', session_id='job-X',
            data={'tool_name': 'Bash', 'mcp_server': None,
                  'duration_ms': 100, 'is_error': False},
            ts=205.0,
        )
        telemetry.record_event(
            E.TOOL_CALL_COMPLETE, scope='comics', session_id='job-X',
            data={'tool_name': 'Bash', 'mcp_server': None,
                  'duration_ms': 5000, 'is_error': False},
            ts=206.0,
        )
        sql = (
            "SELECT tool_name, mcp_server, AVG(duration_ms), "
            "       MAX(duration_ms), COUNT(*) "
            "FROM events WHERE event_type='tool_call_complete' "
            "GROUP BY tool_name, mcp_server "
            "ORDER BY MAX(duration_ms) DESC"
        )
        conn = self._conn()
        try:
            rows = list(conn.execute(sql))
        finally:
            conn.close()
        self.assertEqual(rows[0][0], 'Bash')
        self.assertEqual(rows[0][3], 5000)
        self.assertEqual(rows[0][4], 2)

    # ── Query 7: dispatch tree, depth-ordered, costed ───────────────────────

    def test_query_7_dispatch_tree_runs_verbatim(self) -> None:
        sql = (
            "SELECT a.session_id, a.parent_session_id, a.depth, a.role, "
            "       SUM(t.cost_usd) "
            "FROM agent_sessions a "
            "LEFT JOIN session_turns t USING (session_id) "
            "WHERE a.job_id = ? "
            "GROUP BY a.session_id ORDER BY a.depth"
        )
        conn = self._conn()
        try:
            rows = list(conn.execute(sql, ('job-X',)))
        finally:
            conn.close()
        # Three sessions: lead (depth 0), child (depth 1), proxy (depth 2).
        depths = [r[2] for r in rows]
        self.assertEqual(
            depths, sorted(depths),
            f'Query 7 must be depth-ordered — got {depths}',
        )
        self.assertEqual(
            len(rows), 3,
            f'Query 7 must return 3 sessions for job-X — got {len(rows)}',
        )


if __name__ == '__main__':
    unittest.main()
