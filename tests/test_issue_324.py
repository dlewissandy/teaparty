"""Tests for issue #324: GET / must serve index.html, not a directory listing.

Acceptance criteria:
1. GET / returns 200 with the contents of bridge/static/index.html
2. The response Content-Type is text/html
3. GET / does not return a directory listing (no file-browser HTML)
"""
import asyncio
import os
import shutil
import tempfile
import unittest


def _make_tmpdir():
    return tempfile.mkdtemp()


def _make_bridge_with_index(tmpdir, index_content='<html>dashboard</html>'):
    from bridge.server import TeaPartyBridge
    static_dir = os.path.join(tmpdir, 'static')
    os.makedirs(static_dir, exist_ok=True)
    with open(os.path.join(static_dir, 'index.html'), 'w') as f:
        f.write(index_content)
    return TeaPartyBridge(
        teaparty_home=tmpdir,
        static_dir=static_dir,
    )


def _run(coro):
    return asyncio.run(coro)


# ── Route registration ────────────────────────────────────────────────────────

class TestRootRouteRegistered(unittest.TestCase):
    """GET / must be registered as an explicit route, not only via the static handler."""

    def setUp(self):
        self.tmpdir = _make_tmpdir()
        self.bridge = _make_bridge_with_index(self.tmpdir)
        self.app = self.bridge._build_app()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_root_path_registered_as_explicit_get_route(self):
        """'/' must appear as an explicit GET route, not just a catch-all static resource."""
        explicit_routes = [
            (route.method, resource.canonical)
            for resource in self.app.router.resources()
            for route in resource
            if resource.canonical == '/'
        ]
        methods = [m for m, _ in explicit_routes]
        self.assertIn('GET', methods,
                      "GET / must be registered as an explicit route so it returns index.html")


# ── Functional: GET / returns index.html ─────────────────────────────────────

class TestRootServesIndexHtml(unittest.TestCase):
    """GET / must return the contents of bridge/static/index.html."""

    def setUp(self):
        self.tmpdir = _make_tmpdir()
        self.index_content = '<html><body>TeaParty Dashboard</body></html>'
        self.bridge = _make_bridge_with_index(self.tmpdir, self.index_content)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_get_root_returns_200(self):
        """GET / must return HTTP 200."""
        from aiohttp.test_utils import TestClient, TestServer

        async def run():
            app = self.bridge._build_app()
            async with TestClient(TestServer(app)) as client:
                resp = await client.get('/')
                return resp.status

        status = _run(run())
        self.assertEqual(status, 200, "GET / must return 200, not a directory listing or redirect")

    def test_get_root_content_type_is_html(self):
        """GET / must return Content-Type: text/html."""
        from aiohttp.test_utils import TestClient, TestServer

        async def run():
            app = self.bridge._build_app()
            async with TestClient(TestServer(app)) as client:
                resp = await client.get('/')
                return resp.content_type

        content_type = _run(run())
        self.assertIn('text/html', content_type,
                      f"GET / must return text/html, got: {content_type}")

    def test_get_root_body_is_index_html_content(self):
        """GET / must return the contents of index.html, not a directory listing."""
        from aiohttp.test_utils import TestClient, TestServer

        async def run():
            app = self.bridge._build_app()
            async with TestClient(TestServer(app)) as client:
                resp = await client.get('/')
                return await resp.text()

        body = _run(run())
        self.assertIn('TeaParty Dashboard', body,
                      "GET / must serve index.html content, not a directory listing")
        # Directory listings typically contain <a href=... for filenames
        self.assertNotIn('<a href="index.html"', body,
                         "GET / must not serve a file browser — serve index.html directly")
