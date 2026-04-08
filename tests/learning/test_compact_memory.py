#!/usr/bin/env python3
"""Tests for compact_memory.py — compaction engine."""
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from teaparty.learning.episodic.entry import make_entry, serialize_memory_file, parse_memory_file, MemoryEntry
from teaparty.learning.episodic.compact import compact_file, compact_entries


class TestCompactMemory(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.memory_path = os.path.join(self.tmpdir, "MEMORY.md")

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write_memory_file(self, path, entries):
        """Write a list of MemoryEntry objects to a MEMORY.md file."""
        text = serialize_memory_file(entries)
        with open(path, 'w') as f:
            f.write(text)

    def _make_entry(self, content="Test learning", **kwargs):
        """Create a MemoryEntry with test defaults."""
        defaults = dict(type="procedural", domain="team", importance=0.5, phase="specification")
        defaults.update(kwargs)
        return make_entry(content, **defaults)

    def _read_entries(self, path):
        """Read and parse entries from a MEMORY.md file."""
        with open(path) as f:
            text = f.read()
        return parse_memory_file(text)

    # ── No monotonic growth ──────────────────────────────────────────────────

    def test_two_cycles_no_monotonic_growth(self):
        """SUCCESS CRITERION 3: two compaction cycles do not grow the file."""
        # Write 10 entries with somewhat overlapping content
        entries = []
        for i in range(10):
            content = f"## [2026-03-0{i%9+1}] Session Learning\nAgents should parallelize dispatch calls. Entry variant {i}."
            entries.append(self._make_entry(content=content, importance=0.3 + i * 0.05))

        self._write_memory_file(self.memory_path, entries)

        # First compaction
        compact_file(self.memory_path)
        after_first = self._read_entries(self.memory_path)
        count_first = len(after_first)

        # Second compaction
        compact_file(self.memory_path)
        after_second = self._read_entries(self.memory_path)
        count_second = len(after_second)

        self.assertLessEqual(count_second, count_first,
            f"File grew after second compaction: {count_first} -> {count_second}")

    def test_idempotent(self):
        """Compacting twice produces same count both times."""
        entries = [self._make_entry(content=f"Distinct learning {i}", importance=0.5) for i in range(5)]
        self._write_memory_file(self.memory_path, entries)

        compact_file(self.memory_path)
        after_first = self._read_entries(self.memory_path)
        count_first = len(after_first)

        compact_file(self.memory_path)
        after_second = self._read_entries(self.memory_path)
        count_second = len(after_second)

        self.assertEqual(count_first, count_second)

    # ── ID deduplication ─────────────────────────────────────────────────────

    def test_duplicate_ids_deduplicated(self):
        """Two entries with same id -> keep the one with higher importance."""
        shared_id = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"

        e1 = make_entry("Low importance learning", importance=0.3, domain="team", phase="spec")
        e1 = MemoryEntry(
            id=shared_id, type=e1.type, domain=e1.domain, importance=0.3,
            phase=e1.phase, status="active", reinforcement_count=0,
            last_reinforced=e1.last_reinforced, created_at=e1.created_at,
            content="Low importance learning",
        )

        e2 = make_entry("High importance learning", importance=0.8, domain="team", phase="spec")
        e2 = MemoryEntry(
            id=shared_id, type=e2.type, domain=e2.domain, importance=0.8,
            phase=e2.phase, status="active", reinforcement_count=0,
            last_reinforced=e2.last_reinforced, created_at=e2.created_at,
            content="High importance learning",
        )

        self._write_memory_file(self.memory_path, [e1, e2])
        compact_file(self.memory_path)

        result = self._read_entries(self.memory_path)
        self.assertEqual(len(result), 1, f"Expected 1 entry after dedup, got {len(result)}")
        self.assertAlmostEqual(result[0].importance, 0.8, places=5)

    # ── Retired entry removal ─────────────────────────────────────────────────

    def test_retired_entries_removed(self):
        """Active entries kept, retired entries dropped."""
        from dataclasses import replace

        active_entries = [self._make_entry(content=f"Active entry {i}") for i in range(3)]
        retired_base = self._make_entry(content="Retired entry A")
        retired_1 = replace(retired_base, status="retired", id="retired-id-1")
        retired_2 = replace(retired_base, status="retired", id="retired-id-2", content="Retired entry B")

        all_entries = active_entries + [retired_1, retired_2]
        self._write_memory_file(self.memory_path, all_entries)

        compact_file(self.memory_path)
        result = self._read_entries(self.memory_path)

        self.assertEqual(len(result), 3, f"Expected 3 active entries, got {len(result)}")
        for e in result:
            self.assertNotEqual(e.status, "retired")

    # ── Frontmatter completeness (success criterion 4) ────────────────────────

    def test_all_entries_valid_frontmatter(self):
        """SUCCESS CRITERION 4: after compact, every entry has all required fields."""
        from teaparty.learning.episodic.entry import REQUIRED_FIELDS

        entries = [self._make_entry(content=f"Entry {i}") for i in range(5)]
        self._write_memory_file(self.memory_path, entries)

        compact_file(self.memory_path)
        result = self._read_entries(self.memory_path)

        self.assertGreater(len(result), 0)
        for entry in result:
            for field_name in REQUIRED_FIELDS:
                val = getattr(entry, field_name)
                self.assertIsNotNone(val, f"Entry missing field '{field_name}'")
                if isinstance(val, str):
                    self.assertTrue(len(val) > 0, f"Entry field '{field_name}' is empty")

    # ── Atomic write ─────────────────────────────────────────────────────────

    def test_atomic_write(self):
        """Compact writes atomically — file is valid after operation."""
        entries = [self._make_entry(content=f"Entry {i}") for i in range(3)]
        self._write_memory_file(self.memory_path, entries)

        compact_file(self.memory_path)

        # File should still be parseable
        with open(self.memory_path) as f:
            text = f.read()
        result = parse_memory_file(text)
        self.assertIsInstance(result, list)

    # ── Return value ──────────────────────────────────────────────────────────

    def test_compact_file_returns_counts(self):
        """compact_file returns (input_count, output_count) tuple."""
        entries = [self._make_entry(content=f"Distinct entry {i}") for i in range(4)]
        self._write_memory_file(self.memory_path, entries)

        result = compact_file(self.memory_path)
        self.assertIsInstance(result, tuple)
        self.assertEqual(len(result), 2)
        input_count, output_count = result
        self.assertEqual(input_count, 4)
        self.assertLessEqual(output_count, input_count)

    def test_compact_nonexistent_file(self):
        """compact_file on missing file returns (0, 0) without error."""
        result = compact_file("/nonexistent/path/MEMORY.md")
        self.assertEqual(result, (0, 0))

    # ── compact_entries (library function) ───────────────────────────────────

    def test_compact_entries_direct(self):
        """compact_entries() on a list of entries returns compacted list."""
        entries = [self._make_entry(content=f"Entry {i}") for i in range(5)]
        result = compact_entries(entries)
        self.assertIsInstance(result, list)
        self.assertLessEqual(len(result), len(entries))


if __name__ == '__main__':
    unittest.main()
