"""Tests for issue #295: heartbeat liveness classification belongs in heartbeat.py.

Requirements:
1. _heartbeat_three_state() is importable from orchestrator.heartbeat
2. _ALIVE_THRESHOLD and _DEAD_THRESHOLD are importable from orchestrator.heartbeat
3. _heartbeat_three_state() returns alive|stale|dead using the 30s/300s thresholds
4. bridge/server.py imports _heartbeat_three_state from orchestrator.heartbeat
5. bridge-api spec references orchestrator.heartbeat for _heartbeat_three_state
"""
import ast
import os
import tempfile
import time
import unittest


class TestHeartbeatLivenessInHeartbeatModule(unittest.TestCase):
    """_heartbeat_three_state and thresholds must live in orchestrator.heartbeat."""

    def test_heartbeat_three_state_importable_from_heartbeat(self):
        """_heartbeat_three_state must be importable from orchestrator.heartbeat."""
        from orchestrator.heartbeat import _heartbeat_three_state  # noqa: F401

    def test_alive_threshold_importable_from_heartbeat(self):
        """_ALIVE_THRESHOLD must be importable from orchestrator.heartbeat."""
        from orchestrator.heartbeat import _ALIVE_THRESHOLD  # noqa: F401

    def test_dead_threshold_importable_from_heartbeat(self):
        """_DEAD_THRESHOLD must be importable from orchestrator.heartbeat."""
        from orchestrator.heartbeat import _DEAD_THRESHOLD  # noqa: F401

    def test_alive_threshold_is_30_seconds(self):
        """_ALIVE_THRESHOLD must be 30 seconds (one BEAT_INTERVAL)."""
        from orchestrator.heartbeat import _ALIVE_THRESHOLD
        self.assertEqual(_ALIVE_THRESHOLD, 30)

    def test_dead_threshold_is_300_seconds(self):
        """_DEAD_THRESHOLD must be 300 seconds (5 minutes)."""
        from orchestrator.heartbeat import _DEAD_THRESHOLD
        self.assertEqual(_DEAD_THRESHOLD, 300)


class TestHeartbeatThreeStateClassification(unittest.TestCase):
    """_heartbeat_three_state() in heartbeat.py must correctly classify liveness."""

    def _make_heartbeat_file(self, tmpdir: str, status: str = 'running') -> str:
        """Create a .heartbeat file in tmpdir and return infra_dir path."""
        import json
        hb_path = os.path.join(tmpdir, '.heartbeat')
        data = {'pid': os.getpid(), 'status': status, 'role': 'test', 'started': time.time()}
        with open(hb_path, 'w') as f:
            json.dump(data, f)
        return tmpdir

    def test_fresh_heartbeat_is_alive(self):
        """Heartbeat with mtime < 30s returns 'alive'."""
        from orchestrator.heartbeat import _heartbeat_three_state
        with tempfile.TemporaryDirectory() as tmpdir:
            self._make_heartbeat_file(tmpdir)
            result = _heartbeat_three_state(tmpdir)
            self.assertEqual(result, 'alive')

    def test_heartbeat_older_than_30s_is_stale(self):
        """Heartbeat with mtime between 30s and 300s returns 'stale'."""
        from orchestrator.heartbeat import _heartbeat_three_state
        with tempfile.TemporaryDirectory() as tmpdir:
            self._make_heartbeat_file(tmpdir)
            hb_path = os.path.join(tmpdir, '.heartbeat')
            # Set mtime to 60 seconds ago (stale but not dead)
            old_mtime = time.time() - 60
            os.utime(hb_path, (old_mtime, old_mtime))
            result = _heartbeat_three_state(tmpdir)
            self.assertEqual(result, 'stale')

    def test_heartbeat_older_than_300s_is_dead(self):
        """Heartbeat with mtime > 300s returns 'dead'."""
        from orchestrator.heartbeat import _heartbeat_three_state
        with tempfile.TemporaryDirectory() as tmpdir:
            self._make_heartbeat_file(tmpdir)
            hb_path = os.path.join(tmpdir, '.heartbeat')
            # Set mtime to 400 seconds ago (dead)
            old_mtime = time.time() - 400
            os.utime(hb_path, (old_mtime, old_mtime))
            result = _heartbeat_three_state(tmpdir)
            self.assertEqual(result, 'dead')

    def test_terminal_heartbeat_is_dead(self):
        """Heartbeat with terminal status (completed/withdrawn) returns 'dead'."""
        from orchestrator.heartbeat import _heartbeat_three_state
        for terminal_status in ('completed', 'withdrawn'):
            with self.subTest(status=terminal_status):
                with tempfile.TemporaryDirectory() as tmpdir:
                    self._make_heartbeat_file(tmpdir, status=terminal_status)
                    result = _heartbeat_three_state(tmpdir)
                    self.assertEqual(result, 'dead',
                        f"Expected 'dead' for terminal status '{terminal_status}'")

    def test_missing_heartbeat_file_is_dead(self):
        """Missing .heartbeat file returns 'dead'."""
        from orchestrator.heartbeat import _heartbeat_three_state
        with tempfile.TemporaryDirectory() as tmpdir:
            result = _heartbeat_three_state(tmpdir)
            self.assertEqual(result, 'dead')


class TestBridgeServerImportsFromHeartbeat(unittest.TestCase):
    """bridge/server.py must import _heartbeat_three_state from orchestrator.heartbeat."""

    def _get_server_source(self) -> str:
        """Return the source of bridge/server.py as a string."""
        server_path = os.path.join(
            os.path.dirname(__file__), '..', 'bridge', 'server.py'
        )
        server_path = os.path.normpath(server_path)
        with open(server_path) as f:
            return f.read()

    def test_server_imports_heartbeat_three_state_from_heartbeat_not_state_reader(self):
        """bridge/server.py must not import _heartbeat_three_state from state_reader."""
        source = self._get_server_source()
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                if node.module and 'state_reader' in node.module:
                    names = [alias.name for alias in node.names]
                    self.assertNotIn(
                        '_heartbeat_three_state', names,
                        "bridge/server.py must import _heartbeat_three_state from "
                        "orchestrator.heartbeat, not orchestrator.state_reader"
                    )

    def test_server_imports_heartbeat_three_state_from_heartbeat_module(self):
        """bridge/server.py must import _heartbeat_three_state from orchestrator.heartbeat."""
        source = self._get_server_source()
        tree = ast.parse(source)
        found = False
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                if node.module and 'heartbeat' in node.module and 'state_reader' not in node.module:
                    names = [alias.name for alias in node.names]
                    if '_heartbeat_three_state' in names:
                        found = True
                        break
        self.assertTrue(
            found,
            "bridge/server.py must import _heartbeat_three_state from orchestrator.heartbeat"
        )


class TestBridgeApiSpecReferencesCorrectModule(unittest.TestCase):
    """bridge-api spec must reference orchestrator.heartbeat for _heartbeat_three_state."""

    def _get_spec_content(self) -> str:
        spec_path = os.path.join(
            os.path.dirname(__file__), '..',
            'docs', 'proposals', 'ui-redesign', 'references', 'bridge-api.md'
        )
        spec_path = os.path.normpath(spec_path)
        with open(spec_path) as f:
            return f.read()

    def test_spec_does_not_reference_state_reader_for_heartbeat_classification(self):
        """The bridge-api spec must not say _heartbeat_three_state comes from state_reader."""
        content = self._get_spec_content()
        # Check both backtick-quoted and plain variants of the wrong module reference
        self.assertNotIn(
            'orchestrator.state_reader` (30s/300s thresholds)',
            content,
            "bridge-api spec must not reference orchestrator.state_reader for "
            "_heartbeat_three_state; it lives in orchestrator.heartbeat"
        )

    def test_spec_references_heartbeat_module_for_heartbeat_classification(self):
        """The bridge-api spec must reference orchestrator.heartbeat for _heartbeat_three_state."""
        content = self._get_spec_content()
        self.assertIn(
            'orchestrator.heartbeat',
            content,
            "bridge-api spec must reference orchestrator.heartbeat for liveness classification"
        )


if __name__ == '__main__':
    unittest.main()
