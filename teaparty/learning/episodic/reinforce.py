#!/usr/bin/env python3
"""Increment reinforcement_count for memory entries that were retrieved this session.

Called at end-of-session with a file listing entry IDs that were retrieved at
session start by memory_indexer.py. Updates reinforcement_count and last_reinforced
in each MEMORY.md file that contains matching entries.

Higher reinforcement_count entries get higher prominence in future retrievals,
implementing a "use it or lose it" memory strengthening signal.

Usage:
    track_reinforcement.py --ids-file <path> --memory <path> [--memory <path> ...]

The ids-file contains one entry UUID per line (blank lines ignored).

Exit codes:
    0: success
    1: error
"""
import argparse
import sys
from dataclasses import replace
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from teaparty.learning.episodic.entry import parse_memory_file, serialize_memory_file


def reinforce_entries(entries: list, retrieved_ids: set) -> tuple:
    """Increment reinforcement_count for entries whose id is in retrieved_ids.

    Also updates last_reinforced to today's date.

    Returns (updated_entries, reinforced_count).
    """
    today = date.today().isoformat()
    updated = []
    reinforced_count = 0

    for entry in entries:
        if entry.id in retrieved_ids and entry.status == 'active':
            updated.append(replace(
                entry,
                reinforcement_count=entry.reinforcement_count + 1,
                last_reinforced=today,
            ))
            reinforced_count += 1
        else:
            updated.append(entry)

    return updated, reinforced_count


def load_ids(ids_file: str) -> set:
    """Read entry IDs from a file, one per line. Returns a set of non-empty strings."""
    p = Path(ids_file)
    if not p.is_file():
        return set()
    lines = p.read_text(errors='replace').splitlines()
    return {line.strip() for line in lines if line.strip()}


def main() -> int:
    parser = argparse.ArgumentParser(
        description='Increment reinforcement_count for retrieved memory entries'
    )
    parser.add_argument(
        '--ids-file', required=True,
        help='File containing retrieved entry IDs (one UUID per line)',
    )
    parser.add_argument(
        '--memory', action='append', default=[], dest='memory_files',
        help='MEMORY.md file to update (repeatable)',
    )
    args = parser.parse_args()

    retrieved_ids = load_ids(args.ids_file)
    if not retrieved_ids:
        print('[track_reinforcement] No retrieved entry IDs to process.', file=sys.stderr)
        return 0

    print(f'[track_reinforcement] Processing {len(retrieved_ids)} retrieved IDs.', file=sys.stderr)

    total_reinforced = 0
    for mem_path_str in args.memory_files:
        mem_path = Path(mem_path_str)
        if not mem_path.is_file():
            continue

        try:
            text = mem_path.read_text(errors='replace')
        except OSError as e:
            print(f'[track_reinforcement] Cannot read {mem_path}: {e}', file=sys.stderr)
            continue

        entries = parse_memory_file(text)
        if not entries:
            continue

        updated, count = reinforce_entries(entries, retrieved_ids)
        if count > 0:
            try:
                mem_path.write_text(serialize_memory_file(updated))
                print(
                    f'[track_reinforcement] Reinforced {count} entries in {mem_path}',
                    file=sys.stderr,
                )
                total_reinforced += count
            except OSError as e:
                print(f'[track_reinforcement] Cannot write {mem_path}: {e}', file=sys.stderr)

    print(f'[track_reinforcement] Total reinforced: {total_reinforced}', file=sys.stderr)
    return 0


if __name__ == '__main__':
    sys.exit(main())
