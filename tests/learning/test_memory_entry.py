#!/usr/bin/env python3
"""Tests for memory_entry.py — entry schema and YAML frontmatter parsing."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from teaparty.learning.episodic.entry import (
    MemoryEntry,
    REQUIRED_FIELDS,
    make_entry,
    parse_entry,
    parse_frontmatter,
    parse_memory_file,
    serialize_entry,
    serialize_memory_file,
)


class TestMemoryEntry(unittest.TestCase):

    def _make_entry(self, **kwargs) -> MemoryEntry:
        """Create a test MemoryEntry with sensible defaults."""
        defaults = dict(
            content="Test learning content about coordination patterns",
            type="procedural",
            domain="team",
            importance=0.7,
            phase="specification",
        )
        defaults.update(kwargs)
        return make_entry(**defaults)

    # ── make_entry ──────────────────────────────────────────────────────────

    def test_make_entry_generates_unique_ids(self):
        e1 = self._make_entry()
        e2 = self._make_entry()
        self.assertNotEqual(e1.id, e2.id)

    def test_make_entry_defaults(self):
        e = make_entry("some content")
        self.assertEqual(e.status, "active")
        self.assertEqual(e.reinforcement_count, 0)
        self.assertEqual(e.domain, "team")
        self.assertEqual(e.type, "procedural")
        self.assertEqual(e.phase, "unknown")
        self.assertEqual(e.importance, 0.5)
        self.assertEqual(e.content, "some content")

    def test_make_entry_clamps_importance(self):
        e = make_entry("x", importance=1.5)
        self.assertEqual(e.importance, 1.0)
        e2 = make_entry("x", importance=-0.5)
        self.assertEqual(e2.importance, 0.0)

    # ── serialize + parse round-trip ────────────────────────────────────────

    def test_yaml_round_trip(self):
        original = self._make_entry(importance=0.8, phase="implementation")
        serialized = serialize_entry(original)
        parsed = parse_entry(serialized)

        self.assertEqual(parsed.id, original.id)
        self.assertEqual(parsed.type, original.type)
        self.assertEqual(parsed.domain, original.domain)
        self.assertAlmostEqual(parsed.importance, original.importance, places=5)
        self.assertEqual(parsed.phase, original.phase)
        self.assertEqual(parsed.status, original.status)
        self.assertEqual(parsed.reinforcement_count, original.reinforcement_count)
        self.assertEqual(parsed.last_reinforced, original.last_reinforced)
        self.assertEqual(parsed.created_at, original.created_at)
        self.assertEqual(parsed.content.strip(), original.content.strip())

    def test_every_entry_has_required_fields(self):
        """SUCCESS CRITERION 4: parse produces entries with all required fields."""
        entry = self._make_entry()
        serialized = serialize_entry(entry)
        parsed = parse_entry(serialized)

        for field_name in REQUIRED_FIELDS:
            val = getattr(parsed, field_name)
            self.assertIsNotNone(val, f"Field '{field_name}' is None")
            if isinstance(val, str):
                self.assertTrue(len(val) > 0, f"Field '{field_name}' is empty string")

    # ── Old-format parsing ──────────────────────────────────────────────────

    def test_parse_old_format_gets_defaults(self):
        old_entry = "## [2026-01-01] Session Learning\n**Context:** Testing\n**Learning:** Agents work better in parallel.\n**Action:** Parallelize dispatches."
        parsed = parse_entry(old_entry)

        self.assertEqual(parsed.domain, "team")
        self.assertEqual(parsed.status, "active")
        self.assertAlmostEqual(parsed.importance, 0.5, places=5)
        self.assertIsNotNone(parsed.id)
        self.assertTrue(len(parsed.id) > 0)
        # Old-format content preserved
        self.assertIn("Session Learning", parsed.content)

    def test_parse_old_format_generates_uuid(self):
        parsed = parse_entry("## [2026-01-01] Team Learning\nSome content")
        # id should look like a UUID (36 chars with hyphens)
        self.assertEqual(len(parsed.id), 36)
        parts = parsed.id.split('-')
        self.assertEqual(len(parts), 5)

    # ── parse_memory_file ────────────────────────────────────────────────────

    def test_parse_memory_file_empty(self):
        self.assertEqual(parse_memory_file(""), [])
        self.assertEqual(parse_memory_file("   \n  "), [])

    def test_parse_memory_file_mixed_formats(self):
        """Two old-format + two new-format entries = 4 MemoryEntry objects."""
        e1 = self._make_entry(content="New format entry 1")
        e2 = self._make_entry(content="New format entry 2")
        new_part = serialize_memory_file([e1, e2])
        old_part = (
            "## [2026-01-01] Session Learning\nOld format content A\n\n"
            "## [2026-01-02] Session Learning\nOld format content B"
        )
        combined = old_part + "\n\n" + new_part
        parsed = parse_memory_file(combined)
        self.assertEqual(len(parsed), 4, f"Expected 4 entries, got {len(parsed)}: {[e.content[:40] for e in parsed]}")

    def test_parse_memory_file_new_format_only(self):
        entries = [self._make_entry(content=f"Entry {i}") for i in range(3)]
        text = serialize_memory_file(entries)
        parsed = parse_memory_file(text)
        self.assertEqual(len(parsed), 3)
        for i, p in enumerate(parsed):
            self.assertIn(f"Entry {i}", p.content)

    # ── serialize_memory_file ────────────────────────────────────────────────

    def test_serialize_memory_file_empty(self):
        self.assertEqual(serialize_memory_file([]), "")

    def test_serialize_memory_file_round_trip(self):
        entries = [self._make_entry(content=f"Learning about topic {i}", importance=0.1 * (i + 1)) for i in range(5)]
        text = serialize_memory_file(entries)
        reparsed = parse_memory_file(text)
        self.assertEqual(len(reparsed), 5)
        for original, reparsed_entry in zip(entries, reparsed):
            self.assertEqual(original.id, reparsed_entry.id)
            self.assertAlmostEqual(original.importance, reparsed_entry.importance, places=5)

    # ── parse_frontmatter ────────────────────────────────────────────────────

    def test_parse_frontmatter_basic(self):
        text = "---\nid: abc-123\ntype: procedural\ndomain: team\nimportance: 0.7\n---\nContent here"
        meta, content = parse_frontmatter(text)
        self.assertEqual(meta['id'], 'abc-123')
        self.assertEqual(meta['type'], 'procedural')
        self.assertAlmostEqual(meta['importance'], 0.7, places=5)
        self.assertEqual(content, 'Content here')

    def test_parse_frontmatter_missing_raises(self):
        with self.assertRaises(ValueError):
            parse_frontmatter("## [2026-01-01] No frontmatter here")

    def test_parse_frontmatter_typed_values(self):
        text = "---\nimportance: 0.8\nreinforcement_count: 5\n---\ncontent"
        meta, _ = parse_frontmatter(text)
        self.assertIsInstance(meta['importance'], float)
        self.assertIsInstance(meta['reinforcement_count'], int)
        self.assertEqual(meta['reinforcement_count'], 5)


if __name__ == '__main__':
    unittest.main()
