"""One-time migration from per-scope metrics.db files (Issue #405).

Walks ``{teaparty_home}`` for any ``*/metrics.db`` files, reads every
row from the legacy ``turn_metrics`` table, writes a corresponding
``turn_complete`` event into ``telemetry.db``, and renames the source
file to ``metrics.db.migrated`` so the migration is idempotent.

Running twice is a no-op: the second pass sees only already-renamed
files. The rename happens after the commit, so a crash mid-migration
leaves the source file in place and the next run retries.
"""
from __future__ import annotations

import logging
import os
import sqlite3
import time
from typing import Iterator

from teaparty.telemetry.events import MIGRATION_RUN, TURN_COMPLETE
from teaparty.telemetry.record import record_event, _ensure_conn, _lock


_log = logging.getLogger('teaparty.telemetry.migration')


def _iter_old_metrics_dbs(teaparty_home: str) -> Iterator[tuple[str, str]]:
    """Yield ``(scope, db_path)`` for every un-migrated ``metrics.db``
    found under ``teaparty_home``. Scope is the parent directory name."""
    if not os.path.isdir(teaparty_home):
        return
    for root, dirs, files in os.walk(teaparty_home):
        # Do not descend into the telemetry DB itself or any .migrated files.
        if 'metrics.db' in files:
            db_path = os.path.join(root, 'metrics.db')
            scope = os.path.basename(root) or 'management'
            yield scope, db_path


def migrate_metrics_db(teaparty_home: str) -> int:
    """Migrate every legacy ``metrics.db`` under ``teaparty_home``.

    Returns the number of events written. Never raises — a failure on
    one source file is logged and skipped so the migration makes
    progress on the rest.
    """
    total = 0
    migrated_files = 0
    for scope, db_path in list(_iter_old_metrics_dbs(teaparty_home)):
        try:
            written = _migrate_one(scope, db_path)
        except Exception:
            _log.warning(
                'telemetry.migrate_metrics_db: failed on %s',
                db_path, exc_info=True,
            )
            continue
        total += written
        migrated_files += 1
        try:
            os.rename(db_path, db_path + '.migrated')
        except OSError:
            _log.warning(
                'telemetry.migrate_metrics_db: rename failed for %s',
                db_path, exc_info=True,
            )

    if migrated_files:
        record_event(
            MIGRATION_RUN,
            scope='management',
            data={
                'migration_name': 'metrics_db_to_events',
                'files_migrated': migrated_files,
                'events_written': total,
            },
        )
    return total


def _migrate_one(scope: str, db_path: str) -> int:
    """Read every row from a legacy metrics.db and emit turn_complete
    events. Returns the number of rows migrated."""
    conn_old = sqlite3.connect(db_path)
    try:
        conn_old.row_factory = sqlite3.Row
        try:
            rows = conn_old.execute(
                'SELECT session_id, agent_name, timestamp, cost_usd, '
                'input_tokens, output_tokens, duration_ms, exit_code '
                'FROM turn_metrics ORDER BY id ASC'
            ).fetchall()
        except sqlite3.DatabaseError:
            return 0
    finally:
        conn_old.close()

    target = _ensure_conn()
    if target is None:
        _log.warning(
            'telemetry.migrate_metrics_db: no telemetry.db configured'
        )
        return 0

    import json
    count = 0
    with _lock:
        for row in rows:
            data = {
                'duration_ms':    row['duration_ms'],
                'exit_code':      row['exit_code'],
                'cost_usd':       row['cost_usd'],
                'input_tokens':   row['input_tokens'],
                'output_tokens':  row['output_tokens'],
                'cache_read_tokens':   0,
                'cache_create_tokens': 0,
                'response_text_len':   0,
                'tools_called':        {},
                'migrated_from':       'metrics.db',
            }
            target.execute(
                'INSERT INTO events '
                '(ts, scope, agent_name, session_id, event_type, data) '
                'VALUES (?, ?, ?, ?, ?, ?)',
                (
                    float(row['timestamp'] or time.time()),
                    scope,
                    row['agent_name'],
                    row['session_id'],
                    TURN_COMPLETE,
                    json.dumps(data),
                ),
            )
            count += 1
        target.commit()
    return count
