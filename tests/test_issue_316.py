"""Tests for issue #316: bridge server static dir never created, silent 403.

Acceptance criteria:
1. _build_app() raises FileNotFoundError if static_dir does not exist.
2. _build_app() registers the static '/' route when static_dir exists.
3. server.py docstring does not reference the stale placeholder path
   'projects/POC/bridge/static'.
"""
import os
import tempfile
import unittest


def _make_bridge(teaparty_home, projects_dir, static_dir):
    from projects.POC.bridge.server import TeaPartyBridge
    return TeaPartyBridge(
        teaparty_home=teaparty_home,
        projects_dir=projects_dir,
        static_dir=static_dir,
    )


def _registered_paths(app):
    """Return the set of canonical paths registered on an aiohttp app."""
    return {r.canonical for r in app.router.resources()}


class TestMissingStaticDirRaises(unittest.TestCase):
    """_build_app() must raise FileNotFoundError when static_dir does not exist."""

    def test_build_app_raises_when_static_dir_missing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            missing = os.path.join(tmpdir, 'does_not_exist')
            bridge = _make_bridge(tmpdir, tmpdir, missing)
            with self.assertRaises(FileNotFoundError):
                bridge._build_app()

    def test_error_message_identifies_missing_dir(self):
        """The FileNotFoundError message should include the missing path."""
        with tempfile.TemporaryDirectory() as tmpdir:
            missing = os.path.join(tmpdir, 'no_such_static')
            bridge = _make_bridge(tmpdir, tmpdir, missing)
            with self.assertRaises(FileNotFoundError) as ctx:
                bridge._build_app()
            self.assertIn('no_such_static', str(ctx.exception))


class TestStaticRouteRegistered(unittest.TestCase):
    """_build_app() must register the static '/' route when static_dir exists."""

    def test_static_route_registered_when_dir_exists(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            static_dir = os.path.join(tmpdir, 'static')
            os.makedirs(static_dir)
            bridge = _make_bridge(tmpdir, tmpdir, static_dir)
            app = bridge._build_app()
            # aiohttp uses StaticResource; its canonical is '' (empty string)
            # for add_static('/', ...).  Count resources before and after to
            # verify the static route is registered.
            resources = list(app.router.resources())
            api_only = len([
                r for r in resources
                if r.canonical.startswith('/api') or r.canonical == '/ws'
            ])
            # There must be at least one non-API, non-WebSocket resource (the static one).
            self.assertGreater(
                len(resources),
                api_only,
                f"Static route not registered. All resources: "
                f"{[r.canonical for r in resources]}",
            )

    def test_static_route_has_show_index_enabled(self):
        """Static route must use show_index=True so GET / serves index.html.

        Without show_index=True, aiohttp returns 403 for directory requests
        (including GET /) even when the static dir and index.html exist.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            static_dir = os.path.join(tmpdir, 'static')
            os.makedirs(static_dir)
            bridge = _make_bridge(tmpdir, tmpdir, static_dir)
            app = bridge._build_app()
            from aiohttp.web_urldispatcher import StaticResource
            static_resources = [
                r for r in app.router.resources()
                if isinstance(r, StaticResource)
            ]
            self.assertTrue(
                static_resources,
                'No StaticResource registered — static route missing',
            )
            for r in static_resources:
                self.assertTrue(
                    r._show_index,
                    'StaticResource must have show_index=True; '
                    'without it GET / returns 403 instead of index.html',
                )


class TestStaticDirExists(unittest.TestCase):
    """projects/POC/bridge/static/ must exist and contain the required HTML pages."""

    def _static_dir(self):
        repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        return os.path.join(repo_root, 'projects', 'POC', 'bridge', 'static')

    def test_static_directory_exists(self):
        d = self._static_dir()
        self.assertTrue(
            os.path.isdir(d),
            f'projects/POC/bridge/static/ does not exist: {d}',
        )

    def test_required_html_pages_present(self):
        d = self._static_dir()
        required = ['index.html', 'artifacts.html', 'chat.html', 'config.html', 'stats.html', 'styles.css']
        for name in required:
            self.assertTrue(
                os.path.isfile(os.path.join(d, name)),
                f'projects/POC/bridge/static/{name} is missing',
            )

    def test_html_pages_use_real_api_not_data_js(self):
        """HTML files must call real /api/ endpoints, not reference data.js."""
        d = self._static_dir()
        html_files = ['index.html', 'artifacts.html', 'chat.html', 'config.html', 'stats.html']
        for name in html_files:
            path = os.path.join(d, name)
            if not os.path.isfile(path):
                continue
            content = open(path).read()
            self.assertNotIn(
                'data.js',
                content,
                f'{name} must not reference data.js — it must use real fetch(\'/api/...\') calls',
            )
