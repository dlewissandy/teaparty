"""Tests for issue #306: Update teaparty.sh after repo flattening and registry migration.

Acceptance criteria:
1. teaparty.sh invokes bridge via 'python3 -m bridge' (not projects.POC.bridge)
2. bridge/__main__.py defines --port but not --project-dir
3. bridge/__main__.py prints http://localhost:{port} before starting the server
4. The URL print uses args.port, not a hardcoded value
"""
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).parent.parent


class TestTeapartyShEntryPoint(unittest.TestCase):
    """teaparty.sh must invoke bridge via the flat module path."""

    def _get_script(self) -> str:
        path = _REPO_ROOT / 'teaparty.sh'
        self.assertTrue(path.exists(), f'teaparty.sh not found at {path}')
        return path.read_text()

    def test_script_uses_flat_bridge_module(self):
        """teaparty.sh must invoke python3 -m bridge, not projects.POC.bridge."""
        source = self._get_script()
        self.assertIn(
            '-m bridge',
            source,
            'teaparty.sh must invoke bridge via python3 -m bridge',
        )

    def test_script_does_not_reference_projects_poc_bridge(self):
        """teaparty.sh must not reference the old projects.POC.bridge path."""
        source = self._get_script()
        self.assertNotIn(
            'projects.POC.bridge',
            source,
            'teaparty.sh must not reference the old projects.POC.bridge module path',
        )

    def test_script_does_not_pass_project_dir(self):
        """teaparty.sh must not pass --project-dir; discovery is registry-only."""
        source = self._get_script()
        self.assertNotIn(
            '--project-dir',
            source,
            'teaparty.sh must not pass --project-dir; project discovery is registry-only',
        )


class TestBridgeMainArgParser(unittest.TestCase):
    """bridge/__main__.py must expose --port and not --project-dir."""

    def _get_main_source(self) -> str:
        path = _REPO_ROOT / 'bridge' / '__main__.py'
        self.assertTrue(path.exists(), f'bridge/__main__.py not found at {path}')
        return path.read_text()

    def test_port_argument_present(self):
        """bridge/__main__.py must define a --port argument."""
        source = self._get_main_source()
        self.assertIn(
            '--port',
            source,
            'bridge/__main__.py must define --port to allow the user to customise the port',
        )

    def test_no_project_dir_argument(self):
        """bridge/__main__.py must not define --project-dir; discovery is registry-only."""
        source = self._get_main_source()
        self.assertNotIn(
            '--project-dir',
            source,
            'bridge/__main__.py must not define --project-dir; project discovery is registry-only',
        )


class TestBridgeMainPrintsLocalURL(unittest.TestCase):
    """bridge/__main__.py must print a localhost URL before starting the server."""

    def _get_main_source(self) -> str:
        path = _REPO_ROOT / 'bridge' / '__main__.py'
        self.assertTrue(path.exists(), f'bridge/__main__.py not found at {path}')
        return path.read_text()

    def test_localhost_url_printed(self):
        """bridge/__main__.py must print http://localhost: so the user can open the dashboard."""
        source = self._get_main_source()
        self.assertIn(
            'http://localhost:',
            source,
            'bridge/__main__.py must print the localhost URL on startup '
            'so the user can open the dashboard in a browser',
        )

    def test_url_uses_args_port_not_hardcoded(self):
        """The URL print must embed args.port on the same line as localhost."""
        source = self._get_main_source()
        localhost_lines = [l for l in source.splitlines() if 'localhost' in l]
        self.assertTrue(
            any('args.port' in l for l in localhost_lines),
            'The localhost URL print must use args.port (not a hardcoded port number) '
            'so that custom --port values are reflected',
        )

    def test_url_print_appears_before_bridge_run(self):
        """The URL print must appear before bridge.run() in source order."""
        source = self._get_main_source()
        localhost_idx = source.find('http://localhost:')
        run_idx = source.find('bridge.run(')
        self.assertGreater(
            localhost_idx, 0,
            'http://localhost: not found in bridge/__main__.py',
        )
        self.assertGreater(
            run_idx, 0,
            'bridge.run( not found in bridge/__main__.py',
        )
        self.assertLess(
            localhost_idx, run_idx,
            'URL print must appear before bridge.run() so the user sees it before the server blocks',
        )


if __name__ == '__main__':
    unittest.main()
