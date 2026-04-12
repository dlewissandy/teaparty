"""Specification tests for issue #406: stats bar component and server endpoints.

Covers:
  - stats-bar.js exists and exposes the required public API (#406 AC1)
  - stats-bar.js contains all internal state symbols (#406 AC1, AC11)
  - Single-codepath enforcement: no stats-bar DOM built outside stats-bar.js (#406 AC11)
  - Every non-excluded page mounts the stats bar (#406 AC2)
  - Excluded pages are explicitly excluded (#406 AC2)
  - /api/telemetry/stats/{scope} accepts agent/session/time_range params (#406 AC8)
  - /api/telemetry/chart/{chart_type} exists for each required chart type (#406 AC9)
  - Chart endpoints return structurally correct JSON (#406 AC6, AC7)
  - stats.html contains time-range selector and reads URL params (#406 AC6)
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import tempfile
import time
import types
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
STATIC_DIR = REPO_ROOT / 'teaparty' / 'bridge' / 'static'

STATS_BAR_JS  = STATIC_DIR / 'stats-bar.js'
INDEX_HTML    = STATIC_DIR / 'index.html'
CONFIG_HTML   = STATIC_DIR / 'config.html'
STATS_HTML    = STATIC_DIR / 'stats.html'
ARTIFACTS_HTML = STATIC_DIR / 'artifacts.html'
STYLES_CSS    = STATIC_DIR / 'styles.css'

# Internal state symbols that must live exclusively in stats-bar.js.
# Their presence in consumer pages would mean a second implementation exists.
STATS_BAR_STATE_SYMBOLS = [
    'StatsBar',
    'stats-bar',
    'stats-bar-cell',
    '_statsBarState',
]

# Public API the module must expose.
STATS_BAR_PUBLIC_API = [
    'StatsBar.mount',
    'StatsBar.unmount',
]

# Chart types the graph page must support (AC7).
REQUIRED_CHART_TYPES = [
    'cost_over_time',
    'turns_per_day',
    'active_sessions_timeline',
    'phase_distribution',
    'backtrack_cost',
    'escalation_outcomes',
    'withdrawal_phases',
    'gate_pass_rate',
]


def _read(path: Path) -> str:
    return path.read_text(encoding='utf-8')


# ── Module existence and public API ──────────────────────────────────────────


class StatsBarModuleExistsTests(unittest.TestCase):
    """stats-bar.js must exist and expose the public mount/unmount API (#406 AC1)."""

    def test_stats_bar_js_exists(self) -> None:
        """stats-bar.js must be present in the static directory."""
        self.assertTrue(
            STATS_BAR_JS.exists(),
            'stats-bar.js is missing from teaparty/bridge/static/ — '
            'the stats bar component has not been created (#406 AC1)',
        )

    def test_stats_bar_exposes_mount(self) -> None:
        """stats-bar.js must define StatsBar.mount."""
        if not STATS_BAR_JS.exists():
            self.skipTest('stats-bar.js not yet created')
        src = _read(STATS_BAR_JS)
        self.assertIn(
            'mount', src,
            'stats-bar.js does not define a mount function — '
            'pages cannot attach the stats bar (#406 AC1)',
        )

    def test_stats_bar_exposes_unmount(self) -> None:
        """stats-bar.js must define StatsBar.unmount."""
        if not STATS_BAR_JS.exists():
            self.skipTest('stats-bar.js not yet created')
        src = _read(STATS_BAR_JS)
        self.assertIn(
            'unmount', src,
            'stats-bar.js does not define an unmount function — '
            'scope navigation will leak subscriptions (#406 AC1)',
        )

    def test_stats_bar_exposes_StatsBar_namespace(self) -> None:
        """stats-bar.js must expose the StatsBar namespace."""
        if not STATS_BAR_JS.exists():
            self.skipTest('stats-bar.js not yet created')
        src = _read(STATS_BAR_JS)
        self.assertIn(
            'StatsBar', src,
            'stats-bar.js does not expose the StatsBar namespace — '
            'consumer pages cannot call StatsBar.mount (#406 AC1)',
        )

    def test_stats_bar_contains_stats_bar_cell_class(self) -> None:
        """stats-bar.js must build cells with the stats-bar-cell class."""
        if not STATS_BAR_JS.exists():
            self.skipTest('stats-bar.js not yet created')
        src = _read(STATS_BAR_JS)
        self.assertIn(
            'stats-bar-cell', src,
            'stats-bar.js does not use the stats-bar-cell CSS class — '
            'the DOM structure is incomplete (#406 AC3)',
        )

    def test_stats_bar_subscribes_to_telemetry_event(self) -> None:
        """stats-bar.js must handle telemetry_event WebSocket messages (#406 AC4)."""
        if not STATS_BAR_JS.exists():
            self.skipTest('stats-bar.js not yet created')
        src = _read(STATS_BAR_JS)
        self.assertIn(
            'telemetry_event', src,
            'stats-bar.js does not handle "telemetry_event" WS messages — '
            'the stats bar will not update in real time (#406 AC4)',
        )

    def test_stats_bar_has_click_navigation(self) -> None:
        """stats-bar.js must navigate to the stats graph page on click (#406 AC5)."""
        if not STATS_BAR_JS.exists():
            self.skipTest('stats-bar.js not yet created')
        src = _read(STATS_BAR_JS)
        self.assertIn(
            'stats.html', src,
            'stats-bar.js does not navigate to stats.html on click — '
            'click-through to the graph view is broken (#406 AC5)',
        )

    def test_stats_bar_has_scope_url_param(self) -> None:
        """stats-bar.js must encode scope in the click-through URL (#406 AC5)."""
        if not STATS_BAR_JS.exists():
            self.skipTest('stats-bar.js not yet created')
        src = _read(STATS_BAR_JS)
        self.assertIn(
            'scope', src,
            'stats-bar.js does not pass scope in the navigation URL — '
            'the stats graph page will not receive the current context (#406 AC5)',
        )

    def test_stats_bar_fetches_baseline_on_mount(self) -> None:
        """stats-bar.js must fetch baseline from /api/telemetry/stats/ on mount (#406 AC10)."""
        if not STATS_BAR_JS.exists():
            self.skipTest('stats-bar.js not yet created')
        src = _read(STATS_BAR_JS)
        self.assertIn(
            '/api/telemetry/stats/', src,
            'stats-bar.js does not fetch from /api/telemetry/stats/ — '
            'the baseline-then-incremental model is broken (#406 AC10)',
        )

    def test_stats_bar_has_four_core_cells(self) -> None:
        """stats-bar.js must reference all four core cell labels (#406 AC3)."""
        if not STATS_BAR_JS.exists():
            self.skipTest('stats-bar.js not yet created')
        src = _read(STATS_BAR_JS)
        # Check for the four core stat names (case-insensitive substring match).
        for label in ('cost', 'turns', 'active', 'gates'):
            self.assertIn(
                label.lower(), src.lower(),
                f'stats-bar.js does not reference the "{label}" cell — '
                f'the core cells are incomplete (#406 AC3)',
            )


# ── Single-codepath enforcement ───────────────────────────────────────────────


class SingleCodepathEnforcementTests(unittest.TestCase):
    """Stats-bar DOM and state must live only in stats-bar.js (#406 AC11)."""

    def _offenders(self, symbol: str, exclude: set[str]) -> list[str]:
        """Files in STATIC_DIR containing symbol, minus those in exclude."""
        found = []
        for path in sorted(STATIC_DIR.rglob('*')):
            if not path.is_file():
                continue
            if path.suffix.lower() not in {'.html', '.js', '.mjs', '.ts'}:
                continue
            if path.name in exclude:
                continue
            try:
                content = path.read_text(encoding='utf-8')
            except OSError:
                continue
            if symbol in content:
                found.append(path.name)
        return found

    def test_stats_bar_class_absent_from_index_html(self) -> None:
        """index.html must not build stats-bar DOM (only mount the component)."""
        src = _read(INDEX_HTML)
        self.assertNotIn(
            'stats-bar-cell', src,
            'index.html builds stats-bar-cell DOM directly — '
            'this is a second implementation violating the single-codepath rule (#406 AC11)',
        )

    def test_stats_bar_class_absent_from_config_html(self) -> None:
        """config.html must not build stats-bar DOM (only mount the component)."""
        src = _read(CONFIG_HTML)
        self.assertNotIn(
            'stats-bar-cell', src,
            'config.html builds stats-bar-cell DOM directly — '
            'this is a second implementation violating the single-codepath rule (#406 AC11)',
        )

    def test_stats_bar_state_symbols_absent_from_consumer_pages(self) -> None:
        """_statsBarState and similar private symbols must not appear in consumer pages."""
        allowed = {'stats-bar.js', 'styles.css'}
        offenders = self._offenders('_statsBarState', allowed)
        self.assertEqual(
            offenders, [],
            f'Private stats-bar state symbol "_statsBarState" found in consumer '
            f'pages {offenders} — stats-bar state must live only in stats-bar.js (#406 AC11)',
        )


# ── Per-page mounting ─────────────────────────────────────────────────────────


class PerPageMountingTests(unittest.TestCase):
    """Every non-excluded page must load stats-bar.js and have a mount slot (#406 AC2)."""

    def _assert_loads_stats_bar(self, path: Path, page_name: str) -> None:
        src = _read(path)
        self.assertIn(
            'stats-bar.js', src,
            f'{page_name} does not load stats-bar.js — '
            f'the stats bar will not appear on this page (#406 AC2)',
        )

    def _assert_has_mount_slot(self, path: Path, page_name: str) -> None:
        src = _read(path)
        self.assertIn(
            'stats-bar-slot', src,
            f'{page_name} does not have a <div id="stats-bar-slot"> — '
            f'there is no mount point for the stats bar (#406 AC2)',
        )

    def _assert_mounts_stats_bar(self, path: Path, page_name: str) -> None:
        src = _read(path)
        self.assertIn(
            'StatsBar.mount', src,
            f'{page_name} does not call StatsBar.mount — '
            f'the stats bar is loaded but never attached (#406 AC2)',
        )

    def test_index_html_loads_stats_bar_js(self) -> None:
        """index.html must load stats-bar.js."""
        self._assert_loads_stats_bar(INDEX_HTML, 'index.html')

    def test_index_html_has_stats_bar_slot(self) -> None:
        """index.html must have a stats-bar-slot div."""
        self._assert_has_mount_slot(INDEX_HTML, 'index.html')

    def test_index_html_mounts_stats_bar_org_wide(self) -> None:
        """index.html must call StatsBar.mount with org-wide scope."""
        self._assert_mounts_stats_bar(INDEX_HTML, 'index.html')
        src = _read(INDEX_HTML)
        # Org-wide mount uses scope: null
        self.assertIn(
            'scope: null', src,
            'index.html StatsBar.mount call must use scope: null for org-wide stats; '
            'the home page will show scoped stats instead of org-wide (#406 AC2)',
        )

    def test_config_html_loads_stats_bar_js(self) -> None:
        """config.html must load stats-bar.js."""
        self._assert_loads_stats_bar(CONFIG_HTML, 'config.html')

    def test_config_html_has_stats_bar_slot(self) -> None:
        """config.html must have a stats-bar-slot div."""
        self._assert_has_mount_slot(CONFIG_HTML, 'config.html')

    def test_config_html_mounts_stats_bar_on_scope_change(self) -> None:
        """config.html must call StatsBar.mount from its scope loader paths."""
        self._assert_mounts_stats_bar(CONFIG_HTML, 'config.html')

    def test_config_html_unmounts_before_remount(self) -> None:
        """config.html must call StatsBar.unmount before re-mounting on scope change."""
        src = _read(CONFIG_HTML)
        self.assertIn(
            'StatsBar.unmount', src,
            'config.html does not call StatsBar.unmount — '
            'scope navigation will stack subscriptions and duplicate DOM (#406 AC1)',
        )

    def test_config_html_management_scope(self) -> None:
        """config.html loadGlobal path must mount with scope 'management'."""
        src = _read(CONFIG_HTML)
        self.assertIn(
            "'management'", src,
            "config.html does not pass scope: 'management' for the management team — "
            'the management config page will show org-wide stats instead (#406 AC2)',
        )

    def test_artifacts_html_explicitly_excluded(self) -> None:
        """artifacts.html must not load stats-bar.js or mount the stats bar."""
        src = _read(ARTIFACTS_HTML)
        self.assertNotIn(
            'stats-bar.js', src,
            'artifacts.html loads stats-bar.js — '
            'the artifacts page is explicitly excluded from the stats bar (#406 AC2)',
        )
        self.assertNotIn(
            'StatsBar', src,
            'artifacts.html references StatsBar — '
            'the artifacts page is explicitly excluded from the stats bar (#406 AC2)',
        )

    def test_artifacts_html_has_exclusion_comment(self) -> None:
        """artifacts.html must contain a comment explaining why it has no stats bar."""
        src = _read(ARTIFACTS_HTML)
        self.assertIn(
            '406', src,
            'artifacts.html has no exclusion comment referencing #406 — '
            'a future contributor will not know why this page lacks a stats bar (#406 AC2)',
        )

    def test_stats_html_excluded_from_stats_bar(self) -> None:
        """stats.html (the graph page) must not mount the stats bar on itself."""
        src = _read(STATS_HTML)
        self.assertNotIn(
            'StatsBar.mount', src,
            'stats.html mounts the stats bar on itself — '
            'the graph page is the click-through destination, not a host (#406 AC2)',
        )


# ── Stats graph page (stats.html redesign) ───────────────────────────────────


class StatsGraphPageTests(unittest.TestCase):
    """stats.html must be the graph view with URL params and charts (#406 AC6, AC7)."""

    def test_stats_html_reads_scope_url_param(self) -> None:
        """stats.html must read the scope URL parameter."""
        src = _read(STATS_HTML)
        self.assertIn(
            'scope', src,
            'stats.html does not read the "scope" URL parameter — '
            'click-through navigation from the stats bar will show unscoped charts (#406 AC6)',
        )

    def test_stats_html_has_time_range_selector(self) -> None:
        """stats.html must have a time-range selector driven by URL or DOM (#406 AC6)."""
        src = _read(STATS_HTML)
        # Must have time_range as a URL param or a JS variable — not just
        # incidental "7 days" text in a chart title.
        has_time_range_param = (
            'time_range' in src
            or 'timeRange' in src
            or 'time-range' in src
        )
        self.assertTrue(
            has_time_range_param,
            'stats.html does not handle a time_range URL/state variable — '
            'users cannot change the chart time window (#406 AC6)',
        )

    def test_stats_html_uses_telemetry_chart_api(self) -> None:
        """stats.html must fetch data from /api/telemetry/chart/."""
        src = _read(STATS_HTML)
        self.assertIn(
            '/api/telemetry/chart/', src,
            'stats.html does not fetch from /api/telemetry/chart/ — '
            'the chart data source is missing (#406 AC7)',
        )

    def test_stats_html_references_all_required_charts(self) -> None:
        """stats.html must reference all 8 required chart types (#406 AC7)."""
        src = _read(STATS_HTML)
        for chart_type in REQUIRED_CHART_TYPES:
            self.assertIn(
                chart_type, src,
                f'stats.html does not reference chart type "{chart_type}" — '
                f'this chart is missing from the graph page (#406 AC7)',
            )

    def test_stats_html_no_longer_calls_legacy_api_stats(self) -> None:
        """stats.html must not call the legacy /api/stats endpoint (#406)."""
        src = _read(STATS_HTML)
        self.assertNotIn(
            "'/api/stats'", src,
            "stats.html still calls legacy '/api/stats' — "
            'the old stats page was not replaced (#406)',
        )
        self.assertNotIn(
            '"/api/stats"', src,
            'stats.html still calls legacy "/api/stats" — '
            'the old stats page was not replaced (#406)',
        )

    def test_stats_html_does_not_load_stats_bar_js(self) -> None:
        """stats.html must not load stats-bar.js (it is the drill-down target)."""
        src = _read(STATS_HTML)
        self.assertNotIn(
            'stats-bar.js', src,
            'stats.html loads stats-bar.js — '
            'the graph page is the stats bar click target, not a host (#406 AC2)',
        )


# ── CSS: stats-bar classes defined in styles.css ─────────────────────────────


class StatsCSSTests(unittest.TestCase):
    """styles.css must define the stats-bar CSS classes (#406 AC3)."""

    def test_styles_css_defines_stats_bar_class(self) -> None:
        """styles.css must define .stats-bar."""
        src = _read(STYLES_CSS)
        self.assertIn(
            '.stats-bar', src,
            'styles.css does not define .stats-bar — '
            'the stats bar will have no styling (#406 AC3)',
        )

    def test_styles_css_defines_stats_bar_cell_class(self) -> None:
        """styles.css must define .stats-bar-cell."""
        src = _read(STYLES_CSS)
        self.assertIn(
            '.stats-bar-cell', src,
            'styles.css does not define .stats-bar-cell — '
            'individual metric cells will have no styling (#406 AC3)',
        )


# ── Server endpoint: /api/telemetry/stats/{scope} with new params ─────────────


class TelemetryStatsEndpointTests(unittest.TestCase):
    """
    /api/telemetry/stats/{scope} must accept agent, session, time_range (#406 AC8).

    These tests use the aiohttp TestServer with a minimal bridge shim so the
    real _handle_telemetry_stats production code is exercised — no mocking of
    the handler itself.
    """

    def _make_home(self) -> str:
        from teaparty import telemetry
        home = tempfile.mkdtemp(prefix='tp406-server-test-')
        self.addCleanup(shutil.rmtree, home, True)
        self.addCleanup(telemetry.reset_for_tests)
        telemetry.set_teaparty_home(home)
        return home

    def _run(self, coro):
        return asyncio.get_event_loop().run_until_complete(coro)

    def _make_app(self):
        """Build a minimal aiohttp app that routes the telemetry endpoints."""
        from aiohttp import web
        from teaparty.bridge import server as srv_mod

        # We need a bridge instance with _handle_telemetry_stats wired up.
        # Construct the smallest possible one.
        import types
        bridge = types.SimpleNamespace(
            teaparty_home=self._home,
            _ws_clients=set(),
        )
        # Bind the real handler method to our bridge shim.
        import teaparty.bridge.server as _srv
        handler = _srv.TeaPartyBridge._handle_telemetry_stats.__get__(
            bridge, _srv.TeaPartyBridge,
        )

        app = web.Application()
        app.router.add_get('/api/telemetry/stats/{scope}', handler)
        return app

    def setUp(self) -> None:
        from teaparty import telemetry
        self._home = self._make_home()
        # Seed some events for the query.
        telemetry.record_event('turn_complete', scope='proj',
                               agent_name='worker', session_id='sess1',
                               data={'cost_usd': 0.05})
        telemetry.record_event('turn_complete', scope='proj',
                               agent_name='other-agent', session_id='sess2',
                               data={'cost_usd': 0.10})

    def test_stats_endpoint_accepts_agent_query_param(self) -> None:
        """/api/telemetry/stats/proj?agent=worker must return filtered stats."""
        from aiohttp.test_utils import TestServer, TestClient
        app = self._make_app()

        async def _run():
            async with TestClient(TestServer(app)) as client:
                resp = await client.get('/api/telemetry/stats/proj?agent=worker')
                self.assertEqual(resp.status, 200,
                    'GET /api/telemetry/stats/proj?agent=worker must return 200; '
                    f'got {resp.status}')
                data = await resp.json()
                self.assertIn('total_cost', data,
                    'Response body missing "total_cost" key (#406 AC8)')
                # cost must be only the worker's turns, not other-agent's
                self.assertAlmostEqual(data['total_cost'], 0.05, places=4,
                    msg=f'?agent=worker filter must return 0.05 cost; '
                        f'got {data["total_cost"]} (other-agent cost is leaking through)')

        self._run(_run())

    def test_stats_endpoint_accepts_session_query_param(self) -> None:
        """/api/telemetry/stats/proj?session=sess1 must return filtered stats."""
        from aiohttp.test_utils import TestServer, TestClient
        app = self._make_app()

        async def _run():
            async with TestClient(TestServer(app)) as client:
                resp = await client.get('/api/telemetry/stats/proj?session=sess1')
                self.assertEqual(resp.status, 200,
                    'GET /api/telemetry/stats/proj?session=sess1 must return 200; '
                    f'got {resp.status}')
                data = await resp.json()
                self.assertIn('total_cost', data,
                    'Response body missing "total_cost" key (#406 AC8)')
                self.assertAlmostEqual(data['total_cost'], 0.05, places=4,
                    msg=f'?session=sess1 filter must return 0.05 cost; '
                        f'got {data["total_cost"]}')

        self._run(_run())

    def test_stats_endpoint_accepts_time_range_param(self) -> None:
        """/api/telemetry/stats/proj?time_range=today must return 200."""
        from aiohttp.test_utils import TestServer, TestClient
        app = self._make_app()

        async def _run():
            async with TestClient(TestServer(app)) as client:
                resp = await client.get('/api/telemetry/stats/proj?time_range=today')
                self.assertEqual(resp.status, 200,
                    'GET /api/telemetry/stats/proj?time_range=today must return 200; '
                    f'got {resp.status}')
                data = await resp.json()
                self.assertIn('total_cost', data,
                    'Response body missing "total_cost" key for time_range=today')

        self._run(_run())

    def test_stats_endpoint_response_has_all_required_fields(self) -> None:
        """/api/telemetry/stats/proj must return all stats-bar fields."""
        from aiohttp.test_utils import TestServer, TestClient
        app = self._make_app()

        async def _run():
            async with TestClient(TestServer(app)) as client:
                resp = await client.get('/api/telemetry/stats/proj')
                self.assertEqual(resp.status, 200)
                data = await resp.json()
                required = {
                    'total_cost', 'turn_count', 'active_sessions',
                    'gates_awaiting_input', 'backtrack_count',
                    'gate_pass_rate',
                }
                missing = required - data.keys()
                self.assertEqual(
                    missing, set(),
                    f'/api/telemetry/stats/proj is missing required fields: {missing} '
                    f'(#406 AC8)',
                )

        self._run(_run())


# ── Server endpoint: /api/telemetry/chart/{chart_type} ───────────────────────


class TelemetryChartEndpointTests(unittest.TestCase):
    """
    /api/telemetry/chart/{chart_type} must exist for each required type (#406 AC9).
    """

    def _make_home(self) -> str:
        from teaparty import telemetry
        home = tempfile.mkdtemp(prefix='tp406-chart-test-')
        self.addCleanup(shutil.rmtree, home, True)
        self.addCleanup(telemetry.reset_for_tests)
        telemetry.set_teaparty_home(home)
        return home

    def _run(self, coro):
        return asyncio.get_event_loop().run_until_complete(coro)

    def _make_app(self):
        from aiohttp import web
        import teaparty.bridge.server as _srv
        import types

        bridge = types.SimpleNamespace(
            teaparty_home=self._home,
            _ws_clients=set(),
        )
        handler = _srv.TeaPartyBridge._handle_telemetry_chart.__get__(
            bridge, _srv.TeaPartyBridge,
        )
        app = web.Application()
        app.router.add_get('/api/telemetry/chart/{chart_type}', handler)
        return app

    def setUp(self) -> None:
        self._home = self._make_home()

    def _check_chart_endpoint(self, chart_type: str) -> None:
        from aiohttp.test_utils import TestServer, TestClient
        app = self._make_app()

        async def _run():
            async with TestClient(TestServer(app)) as client:
                resp = await client.get(f'/api/telemetry/chart/{chart_type}')
                self.assertEqual(
                    resp.status, 200,
                    f'GET /api/telemetry/chart/{chart_type} must return 200; '
                    f'got {resp.status} — this chart endpoint is missing (#406 AC9)',
                )
                data = await resp.json()
                self.assertIsInstance(data, dict,
                    f'/api/telemetry/chart/{chart_type} must return a JSON object; '
                    f'got {type(data).__name__}')
                self.assertIn('data', data,
                    f'/api/telemetry/chart/{chart_type} response must have a "data" key; '
                    f'got keys {list(data.keys())}')

        self._run(_run())

    def test_chart_cost_over_time(self) -> None:
        """GET /api/telemetry/chart/cost_over_time must return 200 with data key."""
        self._check_chart_endpoint('cost_over_time')

    def test_chart_turns_per_day(self) -> None:
        """GET /api/telemetry/chart/turns_per_day must return 200 with data key."""
        self._check_chart_endpoint('turns_per_day')

    def test_chart_active_sessions_timeline(self) -> None:
        """GET /api/telemetry/chart/active_sessions_timeline must return 200."""
        self._check_chart_endpoint('active_sessions_timeline')

    def test_chart_phase_distribution(self) -> None:
        """GET /api/telemetry/chart/phase_distribution must return 200."""
        self._check_chart_endpoint('phase_distribution')

    def test_chart_backtrack_cost(self) -> None:
        """GET /api/telemetry/chart/backtrack_cost must return 200."""
        self._check_chart_endpoint('backtrack_cost')

    def test_chart_escalation_outcomes(self) -> None:
        """GET /api/telemetry/chart/escalation_outcomes must return 200."""
        self._check_chart_endpoint('escalation_outcomes')

    def test_chart_withdrawal_phases(self) -> None:
        """GET /api/telemetry/chart/withdrawal_phases must return 200."""
        self._check_chart_endpoint('withdrawal_phases')

    def test_chart_gate_pass_rate(self) -> None:
        """GET /api/telemetry/chart/gate_pass_rate must return 200."""
        self._check_chart_endpoint('gate_pass_rate')

    def test_unknown_chart_type_returns_404(self) -> None:
        """GET /api/telemetry/chart/no_such_chart must return 404 or 400."""
        from aiohttp.test_utils import TestServer, TestClient
        app = self._make_app()

        async def _run():
            async with TestClient(TestServer(app)) as client:
                resp = await client.get('/api/telemetry/chart/no_such_chart')
                self.assertIn(
                    resp.status, {400, 404},
                    f'Unknown chart type must return 400 or 404; got {resp.status}',
                )

        self._run(_run())

    def test_chart_scope_filter_accepted(self) -> None:
        """Chart endpoints must accept scope query param without error."""
        from aiohttp.test_utils import TestServer, TestClient
        app = self._make_app()

        async def _run():
            async with TestClient(TestServer(app)) as client:
                resp = await client.get(
                    '/api/telemetry/chart/cost_over_time?scope=myproject'
                )
                self.assertEqual(resp.status, 200,
                    'cost_over_time?scope=myproject must return 200; '
                    f'got {resp.status} — scope filtering is broken (#406 AC9)')

        self._run(_run())


if __name__ == '__main__':
    unittest.main()
