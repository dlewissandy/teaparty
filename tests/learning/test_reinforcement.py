#!/usr/bin/env python3
"""Tests for Phase 5: track_reinforcement.py.

Covers:
 - reinforce_entries() increments reinforcement_count for retrieved IDs
 - last_reinforced is updated to today
 - Non-retrieved entries are unchanged
 - Retired entries are not reinforced
 - File I/O round-trip through MEMORY.md
"""
import os
import shutil
import sys
import tempfile
import unittest
from dataclasses import replace
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from teaparty.learning.episodic.entry import make_entry, parse_memory_file, serialize_memory_file, MemoryEntry
from teaparty.learning.episodic.reinforce import reinforce_entries, load_ids


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_entry(importance: float = 0.5, reinforcement_count: int = 0) -> MemoryEntry:
    return make_entry(
        f'Test learning (importance={importance})',
        type='procedural', domain='team',
        importance=importance, phase='unknown',
    )


# ── reinforce_entries ─────────────────────────────────────────────────────────

class TestReinforceEntries(unittest.TestCase):

    def test_retrieved_entry_count_incremented(self):
        """Entries whose ID is in retrieved_ids get reinforcement_count += 1."""
        e = _make_entry()
        self.assertEqual(e.reinforcement_count, 0)

        updated, count = reinforce_entries([e], retrieved_ids={e.id})
        self.assertEqual(count, 1)
        self.assertEqual(updated[0].reinforcement_count, 1)

    def test_multiple_increments_cumulative(self):
        """Reinforcement count accumulates across multiple calls."""
        e = _make_entry()
        updated, _ = reinforce_entries([e], {e.id})
        updated, _ = reinforce_entries(updated, {updated[0].id})
        self.assertEqual(updated[0].reinforcement_count, 2)

    def test_last_reinforced_set_to_today(self):
        """last_reinforced is updated to today's date after reinforcement."""
        old_date = '2020-01-01'
        e = _make_entry()
        e = replace(e, last_reinforced=old_date)

        updated, _ = reinforce_entries([e], {e.id})
        self.assertEqual(updated[0].last_reinforced, date.today().isoformat())

    def test_non_retrieved_entries_unchanged(self):
        """Entries not in retrieved_ids are not modified."""
        e1 = _make_entry()
        e2 = _make_entry()

        updated, count = reinforce_entries([e1, e2], retrieved_ids={e1.id})
        self.assertEqual(count, 1)

        # e2 must be unchanged
        e2_updated = next(e for e in updated if e.id == e2.id)
        self.assertEqual(e2_updated.reinforcement_count, 0)

    def test_retired_entries_not_reinforced(self):
        """Retired entries must not be reinforced even if their ID is in retrieved_ids."""
        e = _make_entry()
        retired = replace(e, status='retired')

        updated, count = reinforce_entries([retired], {retired.id})
        self.assertEqual(count, 0, "Retired entries must not be reinforced")
        self.assertEqual(updated[0].reinforcement_count, 0)

    def test_empty_retrieved_ids_changes_nothing(self):
        """Empty set of retrieved IDs results in no changes."""
        entries = [_make_entry() for _ in range(3)]
        updated, count = reinforce_entries(entries, retrieved_ids=set())
        self.assertEqual(count, 0)
        for e in updated:
            self.assertEqual(e.reinforcement_count, 0)

    def test_empty_entries_is_safe(self):
        """Empty entries list returns empty without error."""
        updated, count = reinforce_entries([], {'some-id'})
        self.assertEqual(updated, [])
        self.assertEqual(count, 0)

    def test_ids_not_present_in_entries_is_safe(self):
        """IDs that don't match any entry produce count=0."""
        e = _make_entry()
        updated, count = reinforce_entries([e], {'non-existent-id'})
        self.assertEqual(count, 0)
        self.assertEqual(updated[0].reinforcement_count, 0)


# ── load_ids ──────────────────────────────────────────────────────────────────

class TestLoadIds(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.ids_file = os.path.join(self.tmpdir, 'ids.txt')

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_loads_ids_from_file(self):
        """load_ids returns a set of IDs from the file."""
        ids = ['abc-123', 'def-456', 'ghi-789']
        Path(self.ids_file).write_text('\n'.join(ids) + '\n')
        result = load_ids(self.ids_file)
        self.assertEqual(result, set(ids))

    def test_ignores_blank_lines(self):
        """Blank lines in the IDs file are ignored."""
        Path(self.ids_file).write_text('abc-123\n\n   \ndef-456\n')
        result = load_ids(self.ids_file)
        self.assertEqual(result, {'abc-123', 'def-456'})

    def test_missing_file_returns_empty_set(self):
        """Missing IDs file returns empty set without error."""
        result = load_ids('/nonexistent/path/ids.txt')
        self.assertIsInstance(result, set)
        self.assertEqual(len(result), 0)

    def test_empty_file_returns_empty_set(self):
        """Empty IDs file returns empty set."""
        Path(self.ids_file).write_text('')
        result = load_ids(self.ids_file)
        self.assertEqual(result, set())


# ── File I/O round-trip ───────────────────────────────────────────────────────

class TestReinforcementFileRoundTrip(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.mem_path = os.path.join(self.tmpdir, 'MEMORY.md')
        self.ids_file = os.path.join(self.tmpdir, 'ids.txt')

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_round_trip_preserves_all_fields(self):
        """Reinforcement round-trip preserves all non-reinforcement fields."""
        e = _make_entry(importance=0.7)
        Path(self.mem_path).write_text(serialize_memory_file([e]))
        Path(self.ids_file).write_text(e.id + '\n')

        # Run reinforcement
        ids = load_ids(self.ids_file)
        entries = parse_memory_file(Path(self.mem_path).read_text())
        updated, count = reinforce_entries(entries, ids)
        Path(self.mem_path).write_text(serialize_memory_file(updated))

        # Re-read and verify
        result = parse_memory_file(Path(self.mem_path).read_text())
        self.assertEqual(len(result), 1)
        e_updated = result[0]

        self.assertEqual(e_updated.id, e.id)
        self.assertAlmostEqual(e_updated.importance, 0.7, places=5)
        self.assertEqual(e_updated.domain, e.domain)
        self.assertEqual(e_updated.type, e.type)
        self.assertEqual(e_updated.reinforcement_count, 1)
        self.assertEqual(e_updated.last_reinforced, date.today().isoformat())

    def test_track_reinforcement_main_updates_file(self):
        """track_reinforcement.py main() updates MEMORY.md correctly."""
        from teaparty.learning.episodic.reinforce import main as track_main

        e = _make_entry(importance=0.6)
        Path(self.mem_path).write_text(serialize_memory_file([e]))
        Path(self.ids_file).write_text(e.id + '\n')

        import sys
        sys.argv = ['track_reinforcement.py', '--ids-file', self.ids_file,
                    '--memory', self.mem_path]
        track_main()

        result = parse_memory_file(Path(self.mem_path).read_text())
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].reinforcement_count, 1)
        self.assertEqual(result[0].last_reinforced, date.today().isoformat())

    def test_prominence_increases_after_reinforcement(self):
        """After reinforcement, prominence is higher than before (reinforcement_count boost)."""
        import math
        from teaparty.learning.episodic.indexer import compute_prominence

        e = _make_entry(importance=0.5)
        today = date.today()

        meta_before = {
            'importance': str(e.importance),
            'last_reinforced': today.isoformat(),
            'reinforcement_count': '0',
            'status': 'active',
        }
        meta_after = dict(meta_before, reinforcement_count='1')

        p_before = compute_prominence(meta_before, today=today)
        p_after = compute_prominence(meta_after, today=today)

        self.assertGreater(p_after, p_before,
                           "Prominence must increase after reinforcement")
        self.assertAlmostEqual(p_after, p_before * 2, places=4,
                               msg="reinforcement_count=1 should double prominence")


if __name__ == '__main__':
    unittest.main()
