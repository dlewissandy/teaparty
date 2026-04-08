#!/usr/bin/env python3
"""Tests for Phase 3 changes to memory_indexer.py.

Covers:
 - Entry-aware chunking (chunk_by_entries)
 - compute_prominence() correctness
 - apply_prominence_weights() with DB
 - No evergreen exemption (files without date in path still decay)
 - SUCCESS CRITERION 5: low-prominence entry ranks below high-prominence entry
"""
import json
import math
import os
import sqlite3
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from teaparty.learning.episodic.indexer import (
    chunk_by_entries,
    chunk_text,
    compute_prominence,
    apply_prominence_weights,
    index_file,
    open_db,
    HALF_LIFE_DAYS,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_structured_entry(
    importance: float = 0.5,
    last_reinforced: str = '',
    reinforcement_count: int = 0,
    status: str = 'active',
    content: str = 'Test learning entry.',
) -> str:
    today = date.today().isoformat()
    lr = last_reinforced or today
    return (
        "---\n"
        "id: test-entry-id\n"
        f"type: procedural\n"
        f"domain: team\n"
        f"importance: {importance}\n"
        f"phase: unknown\n"
        f"status: {status}\n"
        f"reinforcement_count: {reinforcement_count}\n"
        f"last_reinforced: {lr}\n"
        f"created_at: {today}\n"
        "---\n"
        f"{content}\n"
    )


def _make_two_entry_file(
    imp1: float, lr1: str, rc1: int,
    imp2: float, lr2: str, rc2: int,
) -> str:
    e1 = _make_structured_entry(importance=imp1, last_reinforced=lr1, reinforcement_count=rc1,
                                 content="Learning A: agents should parallelize dispatch calls.")
    e2 = _make_structured_entry(importance=imp2, last_reinforced=lr2, reinforcement_count=rc2,
                                 content="Learning B: memory compaction prevents unbounded growth.")
    return e1 + "\n" + e2


# ── chunk_by_entries ──────────────────────────────────────────────────────────

class TestChunkByEntries(unittest.TestCase):

    def test_structured_entries_produce_one_chunk_per_entry(self):
        """Each YAML frontmatter entry becomes exactly one chunk."""
        text = _make_two_entry_file(0.5, '', 0, 0.7, '', 0)
        chunks = chunk_by_entries(text)
        self.assertEqual(len(chunks), 2, f"Expected 2 chunks, got {len(chunks)}")

    def test_structured_chunk_has_metadata(self):
        """Entry-aware chunks carry frontmatter metadata."""
        text = _make_structured_entry(importance=0.8, reinforcement_count=3)
        chunks = chunk_by_entries(text)
        self.assertEqual(len(chunks), 1)
        content, metadata, offset = chunks[0]
        self.assertIn('importance', metadata, "Chunk metadata missing 'importance'")
        self.assertAlmostEqual(float(metadata['importance']), 0.8, places=5)
        self.assertEqual(int(metadata['reinforcement_count']), 3)

    def test_plain_text_falls_back_to_character_chunking(self):
        """Plain markdown (no frontmatter) falls back to chunk_text."""
        text = "# Header\n\nSome plain text.\n" * 20
        chunks_entry = chunk_by_entries(text)
        chunks_plain = chunk_text(text)
        # Both should produce the same content (entry chunker delegates)
        self.assertEqual(len(chunks_entry), len(chunks_plain))
        for (ec, em, eo), (pc, po) in zip(chunks_entry, chunks_plain):
            self.assertEqual(ec, pc)
            self.assertEqual(em, {})

    def test_single_entry_no_separator_required(self):
        """Single structured entry is returned as one chunk."""
        text = _make_structured_entry(content="Single entry content.")
        chunks = chunk_by_entries(text)
        self.assertEqual(len(chunks), 1)
        content, metadata, offset = chunks[0]
        self.assertIn('Single entry content', content)

    def test_char_offset_increases_monotonically(self):
        """char_offset for each subsequent entry must be >= previous."""
        text = _make_two_entry_file(0.5, '', 0, 0.7, '', 0)
        chunks = chunk_by_entries(text)
        if len(chunks) >= 2:
            self.assertGreaterEqual(chunks[1][2], chunks[0][2])


# ── compute_prominence ────────────────────────────────────────────────────────

class TestComputeProminence(unittest.TestCase):

    def test_high_importance_recent_scores_high(self):
        """High importance + recent date → prominence near importance × 1."""
        today = date.today()
        metadata = {
            'importance': '0.9',
            'last_reinforced': today.isoformat(),
            'reinforcement_count': '0',
            'status': 'active',
        }
        p = compute_prominence(metadata, today=today)
        self.assertGreater(p, 0.8, f"Expected prominence > 0.8, got {p}")

    def test_low_importance_old_scores_low(self):
        """Low importance + 180 days ago → very low prominence."""
        old_date = (date.today() - timedelta(days=180)).isoformat()
        metadata = {
            'importance': '0.2',
            'last_reinforced': old_date,
            'reinforcement_count': '0',
            'status': 'active',
        }
        p = compute_prominence(metadata, today=date.today())
        self.assertLess(p, 0.1, f"Expected prominence < 0.1, got {p}")

    def test_retired_returns_zero(self):
        """Retired entries must have prominence 0.0."""
        metadata = {'importance': '0.9', 'status': 'retired',
                    'reinforcement_count': '0', 'last_reinforced': date.today().isoformat()}
        p = compute_prominence(metadata)
        self.assertEqual(p, 0.0)

    def test_no_evergreen_exemption_for_files_without_date_in_path(self):
        """Files without a date in their path must NOT be treated as evergreen.

        SUCCESS CRITERION: project MEMORY.md (path has no YYYY-MM-DD) must still decay.
        """
        plain_path = '/project/MEMORY.md'  # no date in path
        metadata = {}  # no frontmatter metadata (legacy format)
        today = date.today()
        # Should use 30-day default age, not be exempt
        p = compute_prominence(metadata, source_path=plain_path, today=today)
        # A 30-day old entry with default importance 0.5 decays based on HALF_LIFE_DAYS
        expected = 0.5 * math.exp(-math.log(2) / HALF_LIFE_DAYS * 30)
        self.assertAlmostEqual(p, expected, places=4,
                               msg="Files without date in path should use 30-day default, not be exempt")
        self.assertLess(p, 0.5, "Undated file must not receive full (evergreen-like) score")

    def test_frontmatter_date_takes_precedence_over_path_date(self):
        """last_reinforced from frontmatter must override date inferred from path."""
        # Path has 2020 date (old), but frontmatter has today (recent)
        old_path = '/memory/2020-01-01/MEMORY.md'
        today = date.today()
        metadata = {
            'importance': '0.5',
            'last_reinforced': today.isoformat(),  # today
            'reinforcement_count': '0',
            'status': 'active',
        }
        p_today = compute_prominence(metadata, source_path=old_path, today=today)

        # Now use old date in frontmatter (should decay significantly)
        metadata_old = dict(metadata)
        metadata_old['last_reinforced'] = '2020-01-01'
        p_old = compute_prominence(metadata_old, source_path=old_path, today=today)

        self.assertGreater(p_today, p_old,
                           "Frontmatter date (today) should give higher prominence than old frontmatter date")

    def test_reinforcement_boosts_prominence(self):
        """Higher reinforcement_count yields proportionally higher prominence."""
        today = date.today()
        base = {
            'importance': '0.5',
            'last_reinforced': today.isoformat(),
            'status': 'active',
        }
        meta_r0 = dict(base, reinforcement_count='0')
        meta_r5 = dict(base, reinforcement_count='5')
        p0 = compute_prominence(meta_r0, today=today)
        p5 = compute_prominence(meta_r5, today=today)
        self.assertAlmostEqual(p5, p0 * 6, places=4,
                               msg="reinforcement_count=5 should give 6× prominence of count=0")

    def test_default_metadata_uses_half_life_default(self):
        """Empty metadata → importance=0.5, 30-day default age, decayed by HALF_LIFE_DAYS."""
        today = date.today()
        p = compute_prominence({}, today=today)
        expected = 0.5 * math.exp(-math.log(2) / HALF_LIFE_DAYS * 30)
        self.assertAlmostEqual(p, expected, places=4)


# ── apply_prominence_weights ──────────────────────────────────────────────────

class TestApplyProminenceWeights(unittest.TestCase):

    def _make_db_with_chunks(self, chunks_data):
        """Create an in-memory DB with chunks. chunks_data: [(source, content, metadata_dict)]."""
        conn = sqlite3.connect(":memory:")
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS chunks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT NOT NULL,
                content TEXT NOT NULL,
                char_offset INTEGER NOT NULL,
                metadata TEXT
            );
        """)
        for source, content, meta in chunks_data:
            conn.execute(
                "INSERT INTO chunks (source, content, char_offset, metadata) VALUES (?, ?, 0, ?)",
                (source, content, json.dumps(meta) if meta else None),
            )
        conn.commit()
        return conn

    def test_returns_weighted_results(self):
        """apply_prominence_weights returns non-empty list for valid inputs."""
        today = date.today()
        meta = {'importance': '0.8', 'last_reinforced': today.isoformat(),
                'reinforcement_count': '0', 'status': 'active'}
        conn = self._make_db_with_chunks([('/mem/MEMORY.md', 'Content A', meta)])
        results = [('/mem/MEMORY.md', 'Content A', -1.0)]  # BM25-style negative score
        out = apply_prominence_weights(results, conn, today=today)
        conn.close()
        self.assertEqual(len(out), 1)
        source, content, score = out[0]
        self.assertGreater(score, 0.0)

    def test_retired_entries_excluded(self):
        """Retired entries must be filtered out of results."""
        meta = {'importance': '0.9', 'status': 'retired', 'reinforcement_count': '0',
                'last_reinforced': date.today().isoformat()}
        conn = self._make_db_with_chunks([('/mem/MEMORY.md', 'Retired content', meta)])
        results = [('/mem/MEMORY.md', 'Retired content', -0.5)]
        out = apply_prominence_weights(results, conn)
        conn.close()
        self.assertEqual(len(out), 0, "Retired entry must be excluded from results")

    def test_handles_no_metadata(self):
        """Chunks with no metadata (legacy) still get a default prominence weight."""
        conn = self._make_db_with_chunks([('/project/MEMORY.md', 'Legacy content', None)])
        results = [('/project/MEMORY.md', 'Legacy content', -1.0)]
        out = apply_prominence_weights(results, conn)
        conn.close()
        # Should still return a result (not excluded), with non-zero score
        self.assertEqual(len(out), 1)
        self.assertGreater(out[0][2], 0.0)


# ── SUCCESS CRITERION 5 ───────────────────────────────────────────────────────

class TestProminenceRankingCriterion5(unittest.TestCase):
    """SUCCESS CRITERION 5: low-prominence entry ranks below high-prominence recent entry."""

    def test_high_prominence_ranks_above_low_prominence(self):
        """After prominence weighting, high-prominence entry has higher score."""
        today = date.today()
        old_date = (today - timedelta(days=90)).isoformat()

        # High prominence: high importance, recent, reinforced
        meta_high = {
            'importance': '0.9',
            'last_reinforced': today.isoformat(),
            'reinforcement_count': '3',
            'status': 'active',
        }
        # Low prominence: low importance, old, no reinforcement
        meta_low = {
            'importance': '0.2',
            'last_reinforced': old_date,
            'reinforcement_count': '0',
            'status': 'active',
        }

        conn = sqlite3.connect(":memory:")
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS chunks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT NOT NULL,
                content TEXT NOT NULL,
                char_offset INTEGER NOT NULL,
                metadata TEXT
            );
        """)
        conn.execute(
            "INSERT INTO chunks (source, content, char_offset, metadata) VALUES (?, ?, 0, ?)",
            ('/mem/MEMORY.md', 'High prominence content: parallel dispatch.', json.dumps(meta_high)),
        )
        conn.execute(
            "INSERT INTO chunks (source, content, char_offset, metadata) VALUES (?, ?, 0, ?)",
            ('/mem/MEMORY.md', 'Low prominence content: outdated stale directive.', json.dumps(meta_low)),
        )
        conn.commit()

        # Simulate retrieval results (equal BM25 scores to isolate prominence effect)
        raw_results = [
            ('/mem/MEMORY.md', 'High prominence content: parallel dispatch.', -1.0),
            ('/mem/MEMORY.md', 'Low prominence content: outdated stale directive.', -1.0),
        ]

        weighted = apply_prominence_weights(raw_results, conn, today=today)
        conn.close()

        self.assertEqual(len(weighted), 2, "Both active entries should be in results")

        # Map content → score
        scores = {content: score for _, content, score in weighted}
        high_score = scores.get('High prominence content: parallel dispatch.', 0.0)
        low_score = scores.get('Low prominence content: outdated stale directive.', 0.0)

        self.assertGreater(
            high_score, low_score,
            f"HIGH prominence entry ({high_score:.4f}) must rank above "
            f"LOW prominence entry ({low_score:.4f})",
        )

    def test_importance_alone_differentiates_ranking(self):
        """With same date, higher importance → higher prominence."""
        today = date.today()
        meta_hi = {'importance': '0.9', 'last_reinforced': today.isoformat(),
                   'reinforcement_count': '0', 'status': 'active'}
        meta_lo = {'importance': '0.2', 'last_reinforced': today.isoformat(),
                   'reinforcement_count': '0', 'status': 'active'}

        p_hi = compute_prominence(meta_hi, today=today)
        p_lo = compute_prominence(meta_lo, today=today)
        self.assertGreater(p_hi, p_lo)

    def test_recency_alone_differentiates_ranking(self):
        """With same importance, more recent → higher prominence."""
        today = date.today()
        recent = today.isoformat()
        old = (today - timedelta(days=60)).isoformat()
        base_meta = {'importance': '0.5', 'reinforcement_count': '0', 'status': 'active'}

        p_recent = compute_prominence(dict(base_meta, last_reinforced=recent), today=today)
        p_old = compute_prominence(dict(base_meta, last_reinforced=old), today=today)
        self.assertGreater(p_recent, p_old)


# ── index_file integration ────────────────────────────────────────────────────

class TestIndexFileIntegration(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, '.memory.db')
        self.mem_path = os.path.join(self.tmpdir, 'MEMORY.md')

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_index_structured_file_stores_metadata(self):
        """index_file on structured MEMORY.md stores YAML metadata JSON in chunks."""
        text = _make_structured_entry(importance=0.75, reinforcement_count=2)
        Path(self.mem_path).write_text(text)

        conn = open_db(self.db_path)
        count = index_file(conn, self.mem_path)
        conn.commit()

        self.assertEqual(count, 1)

        row = conn.execute("SELECT metadata FROM chunks WHERE source = ?", (self.mem_path,)).fetchone()
        self.assertIsNotNone(row, "No chunk found in DB after index_file")
        self.assertIsNotNone(row[0], "metadata column is NULL for structured entry")

        meta = json.loads(row[0])
        self.assertAlmostEqual(float(meta.get('importance', 0)), 0.75, places=4)
        self.assertEqual(int(meta.get('reinforcement_count', -1)), 2)
        conn.close()

    def test_index_plain_file_stores_null_or_empty_metadata(self):
        """index_file on plain markdown stores NULL or empty metadata (not structured entry)."""
        text = "# Plain header\n\nSome plain text without frontmatter.\n" * 5
        Path(self.mem_path).write_text(text)

        conn = open_db(self.db_path)
        count = index_file(conn, self.mem_path)
        conn.commit()

        self.assertGreater(count, 0)
        rows = conn.execute("SELECT metadata FROM chunks WHERE source = ?", (self.mem_path,)).fetchall()
        # All metadata should be NULL or empty dict (no frontmatter parsed)
        for row in rows:
            if row[0]:
                meta = json.loads(row[0])
                self.assertEqual(meta, {})
        conn.close()


if __name__ == '__main__':
    unittest.main()
