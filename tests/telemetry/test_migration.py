"""Migration tests: legacy metrics.db → telemetry.db (Issue #405)."""
from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest

from teaparty import telemetry
from teaparty.telemetry import events as E
from teaparty.telemetry.migration import migrate_metrics_db


def _seed_legacy_metrics_db(path: str, rows: list[tuple]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    conn = sqlite3.connect(path)
    try:
        conn.execute('''
            CREATE TABLE turn_metrics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                agent_name TEXT NOT NULL,
                timestamp REAL NOT NULL,
                cost_usd REAL NOT NULL DEFAULT 0.0,
                input_tokens INTEGER NOT NULL DEFAULT 0,
                output_tokens INTEGER NOT NULL DEFAULT 0,
                duration_ms INTEGER NOT NULL DEFAULT 0,
                exit_code INTEGER NOT NULL DEFAULT 0
            )
        ''')
        conn.executemany(
            'INSERT INTO turn_metrics '
            '(session_id, agent_name, timestamp, cost_usd, input_tokens, '
            'output_tokens, duration_ms, exit_code) '
            'VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
            rows,
        )
        conn.commit()
    finally:
        conn.close()


class MetricsDbMigrationTests(unittest.TestCase):

    def setUp(self) -> None:
        telemetry.reset_for_tests()
        self.home = tempfile.mkdtemp(prefix='telemetry-migrate-')
        telemetry.set_teaparty_home(self.home)

    def tearDown(self) -> None:
        telemetry.reset_for_tests()

    def test_migration_writes_turn_complete_events_and_renames_source(
        self,
    ) -> None:
        # Two legacy files under two scopes.
        mgmt_db = os.path.join(self.home, 'management', 'metrics.db')
        comics_db = os.path.join(self.home, 'comics', 'metrics.db')

        _seed_legacy_metrics_db(mgmt_db, [
            ('sess-a', 'office-manager', 1000.0, 0.10, 100, 20, 500, 0),
            ('sess-a', 'office-manager', 1001.0, 0.20, 200, 30, 700, 0),
        ])
        _seed_legacy_metrics_db(comics_db, [
            ('sess-b', 'comics-lead', 1002.0, 1.50, 300, 40, 900, 0),
        ])

        written = migrate_metrics_db(self.home)
        self.assertEqual(written, 3, 'all three legacy rows must be migrated')

        # Old files renamed, not deleted.
        self.assertFalse(os.path.exists(mgmt_db))
        self.assertFalse(os.path.exists(comics_db))
        self.assertTrue(os.path.exists(mgmt_db + '.migrated'))
        self.assertTrue(os.path.exists(comics_db + '.migrated'))

        # turn_complete events written with scope and cost preserved.
        mgmt_events = telemetry.query_events(
            event_type=E.TURN_COMPLETE, scope='management',
        )
        comics_events = telemetry.query_events(
            event_type=E.TURN_COMPLETE, scope='comics',
        )
        self.assertEqual(len(mgmt_events), 2)
        self.assertEqual(len(comics_events), 1)

        costs = sorted(e.data['cost_usd'] for e in mgmt_events)
        self.assertEqual(costs, [0.10, 0.20])
        self.assertEqual(comics_events[0].data['cost_usd'], 1.50)

        # migration_run audit event recorded.
        audits = telemetry.query_events(event_type=E.MIGRATION_RUN)
        self.assertEqual(len(audits), 1)
        self.assertEqual(audits[0].data['files_migrated'], 2)
        self.assertEqual(audits[0].data['events_written'], 3)

    def test_migration_is_idempotent(self) -> None:
        mgmt_db = os.path.join(self.home, 'management', 'metrics.db')
        _seed_legacy_metrics_db(mgmt_db, [
            ('sess-a', 'office-manager', 1000.0, 0.10, 100, 20, 500, 0),
        ])

        first = migrate_metrics_db(self.home)
        second = migrate_metrics_db(self.home)

        self.assertEqual(first, 1)
        self.assertEqual(
            second, 0,
            'second run must be a no-op — source files were renamed',
        )
        # Exactly one migrated turn_complete event (not two).
        events = telemetry.query_events(event_type=E.TURN_COMPLETE)
        self.assertEqual(
            len(events), 1,
            'idempotency: the same row must not be inserted twice',
        )


if __name__ == '__main__':
    unittest.main()
