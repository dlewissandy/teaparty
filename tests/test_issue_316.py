"""Tests for issue #316: bridge server static dir never created, silent 403.

Acceptance criteria:
1. _build_app() raises FileNotFoundError if static_dir does not exist.
2. _build_app() registers the static '/' route when static_dir exists.
3. server.py docstring does not reference the stale placeholder path
   'projects/POC/bridge/static'.
"""
import inspect
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


class TestServerDocstringNotStale(unittest.TestCase):
    """server.py must not reference the stale placeholder path 'projects/POC/bridge/static'."""

    def _server_source(self):
        from projects.POC.bridge import server
        return inspect.getsource(server)

    def test_docstring_does_not_reference_stale_static_dir(self):
        source = self._server_source()
        self.assertNotIn(
            "projects/POC/bridge/static",
            source,
            "server.py still references the stale placeholder path "
            "'projects/POC/bridge/static' — update the docstring example",
        )
