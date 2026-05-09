"""HTTP endpoint tests for the /api/analysis/* routes (Issue #431).

The endpoints are thin wrappers around teaparty.telemetry query helpers
that read from spec-aligned views. The tests drive the real handler
methods (bound to a minimal aiohttp app) so the route, the handler,
and the underlying SQL all run end-to-end.
"""
from __future__ import annotations

import asyncio
import os
import shutil
import tempfile
import types
import unittest


def _make_home() -> str:
    from teaparty import telemetry
    home = tempfile.mkdtemp(prefix='analysis-431-')
    telemetry.reset_for_tests()
    telemetry.set_teaparty_home(home)
    return home


def _seed(telemetry) -> None:
    """Seed a small but representative event log."""
    # Job-A
    telemetry.record_event(
        'job_created', scope='comics',
        data={
            'job_id': 'job-A', 'project': 'comics',
            'slug': 'fix-bug', 'classification': 'fix-issue',
            'prompt_text': 'fix it', 'prompt_hash': 'h1',
            'prompt_bytes': 6, 'branch': 'fix/x',
            'status': 'active', 'created_at': '2026-05-09T00:00:00Z',
        },
        ts=100.0, job_id='job-A',
    )
    # Lead session for job-A.
    telemetry.record_event(
        'turn_complete', scope='comics',
        agent_name='exec-lead', session_id='job-A',
        data={'cost_usd': 0.40, 'input_tokens': 1000, 'output_tokens': 500,
              'duration_ms': 5000},
        ts=200.0, turn_id='t1', job_id='job-A',
        dispatch_depth=0, cost_source='stream_result',
    )
    # Specialist child of job-A.
    telemetry.record_event(
        'turn_complete', scope='comics',
        agent_name='developer', session_id='child-1',
        data={'cost_usd': 0.10, 'input_tokens': 200, 'output_tokens': 80,
              'duration_ms': 1500},
        ts=300.0, turn_id='t2', parent_session_id='job-A', job_id='job-A',
        dispatch_depth=1, cost_source='stream_result',
    )
    # A second job-B with the same prompt_hash for prompt-groups.
    telemetry.record_event(
        'job_created', scope='comics',
        data={
            'job_id': 'job-B', 'project': 'comics',
            'slug': 'fix-bug', 'classification': 'fix-issue',
            'prompt_text': 'fix it', 'prompt_hash': 'h1',
            'prompt_bytes': 6, 'branch': 'fix/y',
            'status': 'active', 'created_at': '2026-05-10T00:00:00Z',
        },
        ts=400.0, job_id='job-B',
    )


class AnalysisEndpointTests(unittest.TestCase):

    def _run(self, coro):
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()

    def _make_app(self):
        from aiohttp import web
        import teaparty.bridge.server as _srv
        bridge = types.SimpleNamespace(
            teaparty_home=self._home, _ws_clients=set(),
        )
        cls = _srv.TeaPartyBridge
        app = web.Application()
        app.router.add_get(
            '/api/analysis/jobs',
            cls._handle_analysis_jobs.__get__(bridge, cls),
        )
        app.router.add_get(
            '/api/analysis/sessions',
            cls._handle_analysis_sessions.__get__(bridge, cls),
        )
        app.router.add_get(
            '/api/analysis/job-cost',
            cls._handle_analysis_job_cost.__get__(bridge, cls),
        )
        app.router.add_get(
            '/api/analysis/prompt-groups',
            cls._handle_analysis_prompt_groups.__get__(bridge, cls),
        )
        app.router.add_get(
            '/api/analysis/gantt/{job_id}',
            cls._handle_analysis_gantt.__get__(bridge, cls),
        )
        app.router.add_get(
            '/api/analysis/token-grid',
            cls._handle_analysis_token_grid.__get__(bridge, cls),
        )
        return app

    def setUp(self) -> None:
        from teaparty import telemetry
        self._home = _make_home()
        self.addCleanup(shutil.rmtree, self._home, True)
        self.addCleanup(telemetry.reset_for_tests)
        _seed(telemetry)

    def test_jobs_endpoint_returns_seeded_jobs(self) -> None:
        from aiohttp.test_utils import TestServer, TestClient
        app = self._make_app()

        async def _run():
            async with TestClient(TestServer(app)) as client:
                resp = await client.get('/api/analysis/jobs?project=comics')
                self.assertEqual(resp.status, 200)
                body = await resp.json()
                ids = sorted(j['job_id'] for j in body['jobs'])
                self.assertEqual(
                    ids, ['job-A', 'job-B'],
                    f'jobs endpoint must return both seeded jobs — got {ids}',
                )
        self._run(_run())

    def test_job_cost_endpoint_groups_by_role_and_agent(self) -> None:
        from aiohttp.test_utils import TestServer, TestClient
        app = self._make_app()

        async def _run():
            async with TestClient(TestServer(app)) as client:
                resp = await client.get('/api/analysis/job-cost?job=job-A')
                self.assertEqual(resp.status, 200)
                body = await resp.json()
                rows = {r['agent_name']: r['cost_usd'] for r in body['rows']}
                self.assertEqual(
                    rows, {'exec-lead': 0.40, 'developer': 0.10},
                    f'job-cost rows must group by agent — got {rows}',
                )
        self._run(_run())

    def test_prompt_groups_endpoint_collapses_byte_identical(self) -> None:
        from aiohttp.test_utils import TestServer, TestClient
        app = self._make_app()

        async def _run():
            async with TestClient(TestServer(app)) as client:
                resp = await client.get(
                    '/api/analysis/prompt-groups?project=comics'
                )
                self.assertEqual(resp.status, 200)
                body = await resp.json()
                self.assertEqual(len(body['groups']), 1)
                self.assertEqual(body['groups'][0]['prompt_hash'], 'h1')
                self.assertEqual(
                    body['groups'][0]['jobs'], 2,
                    f'two byte-identical jobs must collapse to one group with '
                    f'count=2 — got {body["groups"]}',
                )
        self._run(_run())

    def test_gantt_endpoint_returns_sessions_intervals_tools_edges(
        self,
    ) -> None:
        from aiohttp.test_utils import TestServer, TestClient
        app = self._make_app()

        async def _run():
            async with TestClient(TestServer(app)) as client:
                resp = await client.get('/api/analysis/gantt/job-A')
                self.assertEqual(resp.status, 200)
                body = await resp.json()
                self.assertEqual(body['job_id'], 'job-A')
                # Sessions for job-A: lead + specialist.
                sids = sorted(s['session_id'] for s in body['sessions'])
                self.assertEqual(
                    sids, ['child-1', 'job-A'],
                    f'gantt must include both job-A sessions — got {sids}',
                )
                self.assertIn('phase_intervals', body)
                self.assertIn('tool_spans', body)
                self.assertIn('dispatch_edges', body)
        self._run(_run())

    def test_sessions_endpoint_filters_by_job(self) -> None:
        from aiohttp.test_utils import TestServer, TestClient
        app = self._make_app()

        async def _run():
            async with TestClient(TestServer(app)) as client:
                resp = await client.get('/api/analysis/sessions?job=job-A')
                self.assertEqual(resp.status, 200)
                body = await resp.json()
                roles = {s['session_id']: s['role'] for s in body['sessions']}
                self.assertEqual(
                    roles,
                    {'job-A': 'project_lead', 'child-1': 'specialist'},
                    f'sessions endpoint must inherit role from agent_sessions '
                    f'view — got {roles}',
                )
        self._run(_run())


class AnalysisDashboardPagesTests(unittest.TestCase):
    """The Gantt and token-grid HTML pages must exist, link to the
    analysis API, and be reachable from the home page."""

    def _read(self, name: str) -> str:
        path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
            'teaparty', 'bridge', 'static', name,
        )
        with open(path) as f:
            return f.read()

    def test_gantt_page_exists_and_calls_gantt_endpoint(self) -> None:
        src = self._read('gantt.html')
        self.assertIn(
            "/api/analysis/gantt/", src,
            'gantt.html must fetch from /api/analysis/gantt/<job_id> — '
            'without this the page renders but pulls no data',
        )
        self.assertIn(
            'sessions', src,
            'gantt.html must reference the sessions array in the '
            'response payload',
        )
        self.assertIn(
            'tool_spans', src,
            'gantt.html must render tool spans (the unique value of '
            'TOOL_CALL_COMPLETE on a Gantt chart)',
        )
        self.assertIn(
            'dispatch_edges', src,
            'gantt.html must draw dispatch edges connecting parent/child '
            'sessions — that is what makes it a tree, not just bars',
        )

    def test_token_grid_page_exists_and_calls_token_grid_endpoint(
        self,
    ) -> None:
        src = self._read('token-grid.html')
        self.assertIn(
            '/api/analysis/token-grid', src,
            'token-grid.html must fetch from /api/analysis/token-grid',
        )
        # The page pivots on role × phase, so both must be referenced.
        self.assertIn('role', src.lower())
        self.assertIn('phase', src.lower())

    def test_home_page_links_to_token_grid(self) -> None:
        src = self._read('index.html')
        self.assertIn(
            'token-grid.html', src,
            'index.html must link to token-grid.html so users can '
            'reach the new token-grid dashboard from the home page',
        )


if __name__ == '__main__':
    unittest.main()
