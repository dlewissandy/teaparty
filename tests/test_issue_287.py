"""Tests for issue #287: bridge-api.md must acknowledge synchronous SQLite I/O constraint.

Acceptance criteria:
1. bridge-api.md explicitly states that SqliteMessageBus uses synchronous sqlite3 I/O
2. bridge-api.md explicitly states this blocks aiohttp's event loop per I/O call
3. bridge-api.md bounds the scale assumption where synchronous I/O is acceptable
   (e.g., local disk, WAL mode, single-user, small number of concurrent sessions)
4. bridge-api.md names the async alternative (run_in_executor or aiosqlite) for when
   scale assumptions are violated
"""
import os
import unittest

_REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), '..'))
_BRIDGE_API = os.path.join(
    _REPO_ROOT, 'docs', 'proposals', 'ui-redesign', 'references', 'bridge-api.md'
)


class TestBridgeApiSyncIoDocumentation(unittest.TestCase):
    """bridge-api.md must explicitly acknowledge the synchronous SQLite I/O assumption."""

    def setUp(self):
        with open(_BRIDGE_API) as f:
            self._src = f.read()
        self._lower = self._src.lower()

    def test_synchronous_sqlite_io_acknowledged(self):
        """bridge-api.md must state that SqliteMessageBus uses synchronous sqlite3 I/O."""
        has_sync = (
            'synchronous' in self._lower
            or 'blocking' in self._lower
        )
        self.assertTrue(
            has_sync,
            "bridge-api.md must acknowledge that SqliteMessageBus uses synchronous (blocking) sqlite3 I/O"
        )

    def test_event_loop_blocking_acknowledged(self):
        """bridge-api.md must state that synchronous I/O blocks aiohttp's event loop."""
        has_event_loop = (
            'event loop' in self._lower
            or 'blocks' in self._lower
        )
        self.assertTrue(
            has_event_loop,
            "bridge-api.md must acknowledge that synchronous sqlite3 I/O blocks aiohttp's event loop"
        )

    def test_scale_assumption_for_sync_io_bounded(self):
        """bridge-api.md must bound the conditions where synchronous I/O is acceptable."""
        # Must name at least two of: local disk, WAL mode, single-user, small session count
        conditions = [
            'local disk' in self._lower,
            'wal' in self._lower,
            'single-user' in self._lower or 'single user' in self._lower,
            'concurrent session' in self._lower,
            'handful' in self._lower,
        ]
        met = sum(conditions)
        self.assertGreaterEqual(
            met, 2,
            "bridge-api.md must bound the scale assumption for synchronous I/O "
            "(e.g., local disk, WAL mode, single-user, small number of concurrent sessions)"
        )

    def test_async_alternative_named(self):
        """bridge-api.md must name the async I/O alternative for when scale assumptions break."""
        has_async_path = (
            'run_in_executor' in self._src
            or 'aiosqlite' in self._lower
        )
        self.assertTrue(
            has_async_path,
            "bridge-api.md must name the async path (run_in_executor or aiosqlite) "
            "as the migration target when scale assumptions are violated"
        )


if __name__ == '__main__':
    unittest.main()
