#!/usr/bin/env python3
"""One-shot CLI to backfill telemetry from historical stream files.

Usage:
    uv run python -m teaparty.scripts.backfill_telemetry
    uv run python -m teaparty.scripts.backfill_telemetry --project /path/to/project
    uv run python -m teaparty.scripts.backfill_telemetry --teaparty-home ~/.teaparty

The script discovers project roots from the teaparty configuration at
``{teaparty_home}/teaparty.yaml`` (or the ``--project`` override), then
walks each project's ``.teaparty/jobs/job-*/`` tree, parses the
per-phase stream JSONL files, and emits MESSAGE_RECORDED /
TOOL_CALL_COMPLETE / DISPATCH_EDGE / JOB_CREATED rows for runs that
pre-date the in-process emission paths landing in the bus.

The backfill is idempotent — running twice is a no-op.
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

import yaml

from teaparty import telemetry
from teaparty.telemetry.backfill import (
    backfill_all,
    backfill_project,
)


_log = logging.getLogger('teaparty.scripts.backfill_telemetry')


def _discover_projects(teaparty_home: str) -> list[tuple[str, Path]]:
    """Read the projects list from ``{teaparty_home}/teaparty.yaml``.

    Falls back to scanning every direct subdirectory containing a
    ``.teaparty/jobs/`` tree if the config file is absent — same
    convention the bridge uses on first launch.
    """
    cfg_path = Path(teaparty_home) / 'teaparty.yaml'
    projects: list[tuple[str, Path]] = []
    if cfg_path.exists():
        try:
            cfg = yaml.safe_load(cfg_path.read_text()) or {}
        except (OSError, yaml.YAMLError):
            cfg = {}
        for entry in (cfg.get('projects') or []):
            if not isinstance(entry, dict):
                continue
            name = entry.get('name') or entry.get('slug') or ''
            root = entry.get('root') or entry.get('path') or ''
            if name and root:
                projects.append((name, Path(os.path.expanduser(root))))
    return projects


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            'Backfill telemetry.db with MESSAGE_RECORDED / '
            'TOOL_CALL_COMPLETE / DISPATCH_EDGE / JOB_CREATED rows '
            'extracted from historical stream JSONL files.'
        ),
    )
    parser.add_argument(
        '--teaparty-home',
        default=os.environ.get('TEAPARTY_HOME')
                or os.path.expanduser('~/.teaparty'),
        help='Teaparty home directory (default: $TEAPARTY_HOME or ~/.teaparty)',
    )
    parser.add_argument(
        '--project',
        action='append',
        default=[],
        help='Backfill a specific project root path. May be repeated. '
             'Overrides the projects discovered from teaparty.yaml.',
    )
    parser.add_argument(
        '--verbose', '-v', action='store_true',
        help='Enable debug logging.',
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format='%(asctime)s %(levelname)s %(name)s %(message)s',
    )

    telemetry.set_teaparty_home(args.teaparty_home)

    if args.project:
        projects = [
            (Path(p).name, Path(os.path.expanduser(p)))
            for p in args.project
        ]
    else:
        projects = _discover_projects(args.teaparty_home)
        if not projects:
            _log.error(
                'No projects found in %s/teaparty.yaml. '
                'Pass --project /path/to/project to backfill explicitly.',
                args.teaparty_home,
            )
            return 1
    counts = backfill_all(projects)

    print(
        f'Backfill summary:\n'
        f'  job dirs visited:        {counts.job_dirs_visited}\n'
        f'  jobs inserted:           {counts.jobs_inserted}\n'
        f'  jobs skipped (existing): {counts.jobs_skipped}\n'
        f'  streams parsed:          {counts.streams_parsed}\n'
        f'  messages inserted:       {counts.messages_inserted}\n'
        f'  messages skipped (dedup):{counts.messages_skipped}\n'
        f'  tool calls inserted:     {counts.tool_calls_inserted}\n'
        f'  dispatch edges inserted: {counts.dispatch_edges_inserted}\n'
        f'  dispatch edges skipped:  {counts.dispatch_edges_skipped}'
    )
    return 0


if __name__ == '__main__':
    sys.exit(main())
