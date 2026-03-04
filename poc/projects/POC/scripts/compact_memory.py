#!/usr/bin/env python3
"""Compaction engine for project MEMORY.md files.

Reads a MEMORY.md, deduplicates and merges entries, rewrites the file
atomically. Prevents append-only growth of memory files.

Usage:
    compact_memory.py --input <path> [--output <path>]

If --output is omitted, overwrites --input in-place.

Algorithm:
1. Parse all entries via parse_memory_file()
2. Deduplicate by id (same id → keep highest importance version)
3. Content-similarity dedup: Jaccard > 0.8 on token sets → merge entries
4. Drop retired entries (status == 'retired')
5. Write atomically (tempfile → os.replace)

Returns (input_count, output_count) when used as a library.
"""
import argparse
import os
import re
import sys
import tempfile
from pathlib import Path

# Add scripts dir to path for memory_entry import
sys.path.insert(0, str(Path(__file__).parent))
from memory_entry import (
    MemoryEntry,
    parse_memory_file,
    serialize_memory_file,
    make_entry,
)


# ── Token similarity ───────────────────────────────────────────────────────────

def _tokenize(text: str) -> set:
    """Extract word tokens from text for Jaccard similarity."""
    return set(re.findall(r'[a-z0-9]+', text.lower()))


def _jaccard(a: set, b: set) -> float:
    """Jaccard similarity between two token sets."""
    if not a and not b:
        return 1.0
    union = a | b
    if not union:
        return 0.0
    return len(a & b) / len(union)


# ── Deduplication ─────────────────────────────────────────────────────────────

def _dedup_by_id(entries: list) -> list:
    """Keep one entry per id — the one with highest importance."""
    seen = {}
    for e in entries:
        if e.id not in seen or e.importance > seen[e.id].importance:
            seen[e.id] = e
    # Preserve original order of first appearance
    result = []
    seen_ids = set()
    for e in entries:
        if e.id not in seen_ids:
            result.append(seen[e.id])
            seen_ids.add(e.id)
    return result


def _merge_entries(a: MemoryEntry, b: MemoryEntry) -> MemoryEntry:
    """Merge two similar entries, keeping the best attributes of each."""
    from memory_entry import VALID_STATUSES
    # Keep higher importance
    if a.importance >= b.importance:
        base, other = a, b
    else:
        base, other = b, a

    # Most recent last_reinforced date
    try:
        date_a = a.last_reinforced
        date_b = b.last_reinforced
        last_reinforced = max(date_a, date_b)
    except Exception:
        last_reinforced = base.last_reinforced

    # Keep longer content
    content = a.content if len(a.content) >= len(b.content) else b.content

    from dataclasses import replace
    return replace(
        base,
        reinforcement_count=max(a.reinforcement_count, b.reinforcement_count),
        last_reinforced=last_reinforced,
        content=content,
        status='compacted',
    )


def _dedup_by_similarity(entries: list, threshold: float = 0.8) -> list:
    """Merge active entries with Jaccard similarity above threshold."""
    if len(entries) <= 1:
        return entries

    # Only consider active entries for similarity merging
    active = [e for e in entries if e.status == 'active']
    non_active = [e for e in entries if e.status != 'active']

    tokens = [_tokenize(e.content) for e in active]
    merged_flags = [False] * len(active)
    result = []

    for i in range(len(active)):
        if merged_flags[i]:
            continue
        current = active[i]
        for j in range(i + 1, len(active)):
            if merged_flags[j]:
                continue
            if _jaccard(tokens[i], tokens[j]) > threshold:
                current = _merge_entries(current, active[j])
                merged_flags[j] = True
        result.append(current)

    return result + non_active


# ── Main compaction ───────────────────────────────────────────────────────────

def compact_entries(entries: list) -> list:
    """Apply full compaction pipeline to a list of MemoryEntry objects.

    1. Drop retired entries
    2. Dedup by id
    3. Merge similar active entries
    Returns compacted list.
    """
    # Drop retired entries
    active = [e for e in entries if e.status != 'retired']

    # Dedup by id
    deduped = _dedup_by_id(active)

    # Merge similar entries
    merged = _dedup_by_similarity(deduped)

    return merged


def compact_file(input_path: str, output_path: str = None) -> tuple:
    """Compact a MEMORY.md file. Returns (input_count, output_count).

    If output_path is None, overwrites input_path in-place.
    Write is atomic: uses tempfile + os.replace().
    """
    input_path = str(input_path)
    if output_path is None:
        output_path = input_path

    # Read input
    try:
        with open(input_path, 'r') as f:
            text = f.read()
    except FileNotFoundError:
        return (0, 0)

    if not text.strip():
        return (0, 0)

    # Parse
    entries = parse_memory_file(text)
    input_count = len(entries)

    if not entries:
        return (0, 0)

    # Compact
    compacted = compact_entries(entries)
    output_count = len(compacted)

    # Serialize
    output_text = serialize_memory_file(compacted)

    # Atomic write
    output_dir = os.path.dirname(os.path.abspath(output_path))
    try:
        fd, tmp_path = tempfile.mkstemp(dir=output_dir, suffix='.tmp')
        try:
            with os.fdopen(fd, 'w') as f:
                f.write(output_text)
                if output_text and not output_text.endswith('\n'):
                    f.write('\n')
            os.replace(tmp_path, output_path)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
    except Exception as e:
        print(f"[compact_memory] Write failed: {e}", file=sys.stderr)
        return (input_count, input_count)  # No change on error

    print(
        f"[compact_memory] {input_path}: {input_count} → {output_count} entries",
        file=sys.stderr,
    )
    return (input_count, output_count)


# ── CLI ────────────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(description="Compact a MEMORY.md file")
    parser.add_argument('--input', required=True, help='Input MEMORY.md path')
    parser.add_argument('--output', default=None, help='Output path (default: overwrite input)')
    args = parser.parse_args()

    if not os.path.isfile(args.input):
        print(f"[compact_memory] Input file not found: {args.input}", file=sys.stderr)
        return 0  # Not an error — called speculatively

    try:
        input_count, output_count = compact_file(args.input, args.output)
    except Exception as e:
        print(f"[compact_memory] Error: {e}", file=sys.stderr)
        return 1

    return 0


if __name__ == '__main__':
    sys.exit(main())
