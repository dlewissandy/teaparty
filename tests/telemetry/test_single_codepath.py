"""CI-style grep check: telemetry is the only writer/reader (Issue #405).

The ticket's success criteria 3 and 4 require that no file outside
``teaparty/telemetry/`` writes to or reads from the events table. This
test enforces that invariant so the audit phase catches regressions.
"""
from __future__ import annotations

import os
import re
import unittest


def _repo_root() -> str:
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.dirname(os.path.dirname(here))


def _walk_py(root: str):
    for dirpath, dirnames, files in os.walk(root):
        # Skip virtualenvs, build output, and worktrees under the repo.
        dirnames[:] = [
            d for d in dirnames
            if d not in {'.venv', '.git', '.worktrees', 'node_modules',
                         '__pycache__', 'dist', 'build'}
        ]
        for f in files:
            if f.endswith('.py'):
                yield os.path.join(dirpath, f)


class SingleCodepathTests(unittest.TestCase):

    def setUp(self) -> None:
        self.repo = _repo_root()
        self.telemetry_dir = os.path.join(
            self.repo, 'teaparty', 'telemetry',
        )

    def _offenders(self, pattern: re.Pattern) -> list[str]:
        offenders = []
        for path in _walk_py(os.path.join(self.repo, 'teaparty')):
            if path.startswith(self.telemetry_dir):
                continue
            try:
                with open(path, encoding='utf-8') as f:
                    content = f.read()
            except OSError:
                continue
            if pattern.search(content):
                offenders.append(os.path.relpath(path, self.repo))
        return offenders

    def test_no_inserts_into_events_outside_telemetry(self) -> None:
        offenders = self._offenders(
            re.compile(r'INSERT\s+INTO\s+events', re.IGNORECASE),
        )
        self.assertEqual(
            offenders, [],
            'Only teaparty/telemetry/ may INSERT INTO events. '
            f'Offending files: {offenders}',
        )

    def test_no_selects_from_events_outside_telemetry(self) -> None:
        offenders = self._offenders(
            re.compile(r'FROM\s+events\b', re.IGNORECASE),
        )
        self.assertEqual(
            offenders, [],
            'Only teaparty/telemetry/ may SELECT FROM events. '
            f'Offending files: {offenders}',
        )

    def test_no_metrics_db_create_table_outside_telemetry(self) -> None:
        offenders = self._offenders(
            re.compile(r'CREATE\s+TABLE[^(]*turn_metrics', re.IGNORECASE),
        )
        self.assertEqual(
            offenders, [],
            'Legacy turn_metrics table must not be created anywhere. '
            f'Offending files: {offenders}',
        )

    def test_no_metrics_db_path_references_outside_telemetry(self) -> None:
        # Only telemetry/migration.py may mention the legacy filename.
        offenders = self._offenders(re.compile(r"['\"]metrics\.db['\"]"))
        self.assertEqual(
            offenders, [],
            'References to legacy metrics.db must live only under '
            f'teaparty/telemetry/. Offending files: {offenders}',
        )


if __name__ == '__main__':
    unittest.main()
