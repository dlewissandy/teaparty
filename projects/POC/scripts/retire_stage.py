#!/usr/bin/env python3
"""Retire task-domain memory entries from a specific project stage.

Called when a stage transition is detected. Marks all entries with
domain='task' that were created during the old stage as 'retired'.

Team-domain entries (domain='team') survive stage transitions unchanged —
they capture composition knowledge that remains relevant across stages.

Usage:
    retire_stage.py --old-stage <stage> --memory <path> [--memory <path> ...]

Exit codes:
    0: success
    1: error
"""
import argparse
import sys
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from memory_entry import parse_memory_file, serialize_memory_file


def retire_stage_entries(entries: list, old_phase: str) -> tuple:
    """Mark task-domain entries from old stage as 'retired'.

    Returns (updated_entries, retired_count).
    Only active entries with domain='task' and matching phase are retired.
    Team-domain entries are untouched.
    """
    updated = []
    retired_count = 0
    for entry in entries:
        if (
            entry.domain == 'task'
            and entry.phase == old_phase
            and entry.status == 'active'
        ):
            updated.append(replace(entry, status='retired'))
            retired_count += 1
        else:
            updated.append(entry)
    return updated, retired_count


def main() -> int:
    parser = argparse.ArgumentParser(
        description='Retire task-domain entries from a completed project phase'
    )
    parser.add_argument(
        '--old-stage', required=True,
        help='The stage being retired (e.g. "specification")',
    )
    parser.add_argument(
        '--memory', action='append', default=[], dest='memory_files',
        help='MEMORY.md file to process (repeatable)',
    )
    args = parser.parse_args()

    old_phase = args.old_stage.strip()
    if not old_phase or old_phase == 'unknown':
        print('[retire_stage] No valid old phase to retire — skipping.', file=sys.stderr)
        return 0

    total_retired = 0
    for mem_path_str in args.memory_files:
        mem_path = Path(mem_path_str)
        if not mem_path.is_file():
            continue

        try:
            text = mem_path.read_text(errors='replace')
        except OSError as e:
            print(f'[retire_stage] Cannot read {mem_path}: {e}', file=sys.stderr)
            continue

        entries = parse_memory_file(text)
        if not entries:
            continue

        updated, count = retire_stage_entries(entries, old_phase)
        if count > 0:
            try:
                mem_path.write_text(serialize_memory_file(updated))
                print(
                    f'[retire_stage] Retired {count} task-domain "{old_phase}" '
                    f'entries from {mem_path}',
                    file=sys.stderr,
                )
                total_retired += count
            except OSError as e:
                print(f'[retire_stage] Cannot write {mem_path}: {e}', file=sys.stderr)

    print(f'[retire_stage] Total retired: {total_retired}', file=sys.stderr)
    return 0


if __name__ == '__main__':
    sys.exit(main())
