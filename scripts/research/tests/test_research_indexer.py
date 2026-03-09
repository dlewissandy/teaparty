"""Tests for scripts/research/research_indexer.py"""

import json
import os
import shutil
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

# Allow importing from scripts/research/
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import research_indexer as ri


class TestParseFrontmatter(unittest.TestCase):
    """Tests for parse_frontmatter()."""

    def test_valid_frontmatter(self):
        text = '---\npaper_id: "2505.07087"\ntitle: "Test Paper"\nyear: 2025\n---\n\n## Abstract\n\nSome text.'
        meta, body = ri.parse_frontmatter(text)
        self.assertEqual(meta["paper_id"], "2505.07087")
        self.assertEqual(meta["title"], "Test Paper")
        self.assertEqual(meta["year"], 2025)
        self.assertIn("## Abstract", body)

    def test_no_frontmatter(self):
        text = "Just some markdown text."
        meta, body = ri.parse_frontmatter(text)
        self.assertEqual(meta, {})
        self.assertEqual(body, text)

    def test_json_array_in_frontmatter(self):
        text = '---\nauthors: ["Alice", "Bob"]\n---\n\nBody.'
        meta, body = ri.parse_frontmatter(text)
        self.assertEqual(meta["authors"], ["Alice", "Bob"])

    def test_numeric_values(self):
        text = '---\nyear: 2025\ncitation_count: 42\n---\n\nBody.'
        meta, body = ri.parse_frontmatter(text)
        self.assertEqual(meta["year"], 2025)
        self.assertEqual(meta["citation_count"], 42)

    def test_unclosed_frontmatter(self):
        text = "---\ntitle: Test\nNo closing delimiter."
        meta, body = ri.parse_frontmatter(text)
        self.assertEqual(meta, {})


class TestExtractSections(unittest.TestCase):
    """Tests for extract_sections()."""

    def test_standard_sections(self):
        body = "## Abstract\n\nThis is the abstract.\n\n## Notes\n\nSome notes.\n\n## Relevance\n\nRelevance info."
        sections = ri.extract_sections(body)
        self.assertIn("abstract", sections)
        self.assertIn("notes", sections)
        self.assertIn("relevance", sections)
        self.assertEqual(sections["abstract"], "This is the abstract.")

    def test_no_sections(self):
        body = "Just plain text without headers."
        sections = ri.extract_sections(body)
        self.assertEqual(sections, {})

    def test_full_text_section(self):
        body = "## Full Text\n\nExtracted from PDF."
        sections = ri.extract_sections(body)
        self.assertIn("full_text", sections)


class TestChunkText(unittest.TestCase):
    """Tests for chunk_text()."""

    def test_short_text(self):
        chunks = ri.chunk_text("Hello world", chunk_size=100, overlap=20)
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0][0], "Hello world")
        self.assertEqual(chunks[0][1], 0)

    def test_overlap_chunks(self):
        text = "A" * 200
        chunks = ri.chunk_text(text, chunk_size=100, overlap=20)
        self.assertGreater(len(chunks), 1)
        # Second chunk starts at offset 80 (100 - 20)
        self.assertEqual(chunks[1][1], 80)

    def test_empty_text(self):
        chunks = ri.chunk_text("")
        self.assertEqual(chunks, [])

    def test_whitespace_only(self):
        chunks = ri.chunk_text("   \n\n  ")
        self.assertEqual(chunks, [])


class TestChunkPaper(unittest.TestCase):
    """Tests for chunk_paper()."""

    def test_abstract_only(self):
        sections = {"abstract": "This is a test abstract."}
        chunks = ri.chunk_paper({}, sections)
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0][1], "abstract")

    def test_placeholder_sections_ignored(self):
        sections = {
            "abstract": "Real abstract.",
            "notes": "[To be filled during deep reading]",
            "relevance": "[To be filled: alignment, differences, extensions]",
        }
        chunks = ri.chunk_paper({}, sections)
        # Only abstract should be chunked
        self.assertEqual(len(chunks), 1)

    def test_tldr_from_metadata(self):
        meta = {"tldr": "A short summary of the paper."}
        sections = {"abstract": "Full abstract."}
        chunks = ri.chunk_paper(meta, sections)
        section_tags = [c[1] for c in chunks]
        self.assertIn("tldr", section_tags)

    def test_filled_notes(self):
        sections = {
            "abstract": "Abstract.",
            "notes": "This paper presents a novel approach to memory management.",
        }
        chunks = ri.chunk_paper({}, sections)
        section_tags = [c[1] for c in chunks]
        self.assertIn("notes", section_tags)


class TestDatabase(unittest.TestCase):
    """Tests for database operations."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, "test.db")

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_init_db(self):
        ri.init_db(self.db_path)
        self.assertTrue(os.path.exists(self.db_path))
        conn = sqlite3.connect(self.db_path)
        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()]
        conn.close()
        self.assertIn("papers", tables)
        self.assertIn("chunks", tables)
        self.assertIn("file_meta", tables)

    def test_open_db_creates_schema(self):
        conn = ri.open_db(self.db_path)
        # Verify papers table exists
        conn.execute("SELECT COUNT(*) FROM papers")
        # Verify chunks table exists
        conn.execute("SELECT COUNT(*) FROM chunks")
        conn.close()

    def _make_paper_md(self, paper_id="2505.07087", title="Test Paper",
                       abstract="Test abstract", notes=""):
        """Create a paper markdown file and return its path."""
        content = (
            f'---\n'
            f'paper_id: "{paper_id}"\n'
            f'title: "{title}"\n'
            f'authors: ["Alice Smith"]\n'
            f'year: 2025\n'
            f'venue: "arXiv preprint"\n'
            f'citation_count: 10\n'
            f'source_type: "preprint"\n'
            f'pdf_url: ""\n'
            f'arxiv_id: "{paper_id}"\n'
            f'doi: ""\n'
            f's2_id: ""\n'
            f'fetched_at: "2026-03-09"\n'
            f'discovery_level: 0\n'
            f'---\n\n'
            f'## Abstract\n\n{abstract}\n\n'
            f'## Notes\n\n{notes or "[To be filled during deep reading]"}\n\n'
            f'## Relevance\n\n[To be filled: alignment, differences, extensions]\n'
        )
        papers_dir = os.path.join(self.tmpdir, "papers")
        os.makedirs(papers_dir, exist_ok=True)
        path = os.path.join(papers_dir, f"{paper_id}.md")
        Path(path).write_text(content)
        return path

    def test_index_paper_file(self):
        conn = ri.open_db(self.db_path)
        path = self._make_paper_md()
        count = ri.index_paper_file(conn, path)
        self.assertGreater(count, 0)

        # Verify paper record
        row = conn.execute("SELECT title FROM papers WHERE id = '2505.07087'").fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row[0], "Test Paper")

        # Verify chunks
        chunks = conn.execute("SELECT COUNT(*) FROM chunks WHERE paper_id = '2505.07087'").fetchone()
        self.assertEqual(chunks[0], count)
        conn.close()

    def test_index_paper_reindex_updates(self):
        conn = ri.open_db(self.db_path)
        path = self._make_paper_md(abstract="First version")
        ri.index_paper_file(conn, path)

        # Modify and reindex
        Path(path).write_text(Path(path).read_text().replace("First version", "Updated abstract"))
        count = ri.index_paper_file(conn, path)
        self.assertGreater(count, 0)

        # Should still have one paper record
        total = conn.execute("SELECT COUNT(*) FROM papers").fetchone()[0]
        self.assertEqual(total, 1)
        conn.close()

    def test_index_directory(self):
        conn = ri.open_db(self.db_path)
        self._make_paper_md("paper1", "Paper One", "Abstract one")
        self._make_paper_md("paper2", "Paper Two", "Abstract two")

        papers_dir = os.path.join(self.tmpdir, "papers")
        count = ri.index_directory(conn, papers_dir)
        self.assertGreater(count, 0)

        total = conn.execute("SELECT COUNT(*) FROM papers").fetchone()[0]
        self.assertEqual(total, 2)
        conn.close()

    def test_needs_reindex_new_file(self):
        conn = ri.open_db(self.db_path)
        path = self._make_paper_md()
        stale = ri.needs_reindex(conn, [path])
        self.assertEqual(stale, [path])
        conn.close()

    def test_needs_reindex_up_to_date(self):
        conn = ri.open_db(self.db_path)
        path = self._make_paper_md()
        ri.index_paper_file(conn, path)
        stale = ri.needs_reindex(conn, [path])
        self.assertEqual(stale, [])
        conn.close()


class TestRetrieval(unittest.TestCase):
    """Tests for retrieval functions."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, "test.db")
        self.conn = ri.open_db(self.db_path)
        self._index_test_papers()

    def tearDown(self):
        self.conn.close()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _make_paper_md(self, paper_id, title, abstract, citation_count=10,
                       source_type="preprint", notes=""):
        content = (
            f'---\n'
            f'paper_id: "{paper_id}"\n'
            f'title: "{title}"\n'
            f'authors: ["Test Author"]\n'
            f'year: 2025\n'
            f'venue: "Test Venue"\n'
            f'citation_count: {citation_count}\n'
            f'source_type: "{source_type}"\n'
            f'pdf_url: ""\n'
            f'arxiv_id: "{paper_id}"\n'
            f'doi: ""\n'
            f's2_id: ""\n'
            f'fetched_at: "2026-03-09"\n'
            f'discovery_level: 0\n'
            f'---\n\n'
            f'## Abstract\n\n{abstract}\n\n'
            f'## Notes\n\n{notes or "[To be filled during deep reading]"}\n\n'
            f'## Relevance\n\n[To be filled: alignment, differences, extensions]\n'
        )
        papers_dir = os.path.join(self.tmpdir, "papers")
        os.makedirs(papers_dir, exist_ok=True)
        path = os.path.join(papers_dir, f"{paper_id}.md")
        Path(path).write_text(content)
        return path

    def _index_test_papers(self):
        p1 = self._make_paper_md(
            "paper1", "Agent Memory Architecture",
            "This paper presents a novel memory architecture for autonomous agents.",
            citation_count=100, source_type="peer-reviewed",
        )
        p2 = self._make_paper_md(
            "paper2", "Multi-Agent Coordination",
            "Coordination mechanisms for multi-agent systems using shared memory.",
            citation_count=50, source_type="peer-reviewed",
        )
        p3 = self._make_paper_md(
            "paper3", "Neural Network Training",
            "A new approach to training deep neural networks efficiently.",
            citation_count=5, source_type="preprint",
        )
        for path in [p1, p2, p3]:
            ri.index_paper_file(self.conn, path)

    def test_retrieve_bm25_basic(self):
        results = ri.retrieve_bm25(self.conn, "memory architecture agent", top_k=5)
        self.assertGreater(len(results), 0)
        # First result should be about memory architecture
        self.assertIn("paper1", results[0]["paper_id"])

    def test_retrieve_bm25_empty_query(self):
        results = ri.retrieve_bm25(self.conn, "", top_k=5)
        self.assertEqual(results, [])

    def test_retrieve_bm25_no_match(self):
        results = ri.retrieve_bm25(self.conn, "quantum entanglement teleportation", top_k=5)
        self.assertEqual(results, [])

    def test_retrieve_bm25_section_filter(self):
        results = ri.retrieve_bm25(self.conn, "memory", top_k=5, section_filter="abstract")
        for r in results:
            self.assertEqual(r["section"], "abstract")

    def test_score_results_citation_boost(self):
        # Manually construct results with different ranks to avoid single-result normalization
        results = [
            {"paper_id": "paper1", "content": "memory", "section": "abstract",
             "rank": -2.0, "citation_count": 100, "source_type": "peer-reviewed"},
            {"paper_id": "paper2", "content": "memory shared", "section": "abstract",
             "rank": -1.0, "citation_count": 5, "source_type": "preprint"},
        ]
        scored = ri.score_results(results)
        self.assertEqual(len(scored), 2)
        for r in scored:
            self.assertIn("score", r)
        # Paper1 has better BM25 rank AND higher citations, so should score highest
        self.assertGreater(scored[0]["score"], scored[1]["score"])

    def test_mmr_rerank_diversity(self):
        # Create results with duplicate content
        results = [
            {"paper_id": "a", "content": "memory architecture agent system", "score": 1.0},
            {"paper_id": "b", "content": "memory architecture agent system design", "score": 0.9},
            {"paper_id": "c", "content": "neural network training optimization", "score": 0.8},
        ]
        reranked = ri.mmr_rerank(results, top_k=3)
        self.assertEqual(len(reranked), 3)

    def test_mmr_rerank_single_result(self):
        results = [{"paper_id": "a", "content": "test", "score": 1.0}]
        reranked = ri.mmr_rerank(results, top_k=5)
        self.assertEqual(len(reranked), 1)

    def test_retrieve_full_pipeline(self):
        results = ri.retrieve(self.conn, "memory architecture", top_k=3)
        self.assertGreater(len(results), 0)
        self.assertLessEqual(len(results), 3)

    def test_format_results(self):
        results = ri.retrieve(self.conn, "memory architecture", top_k=3)
        formatted = ri.format_results(results, self.conn)
        self.assertIn("Research Index Results", formatted)
        self.assertIn("Agent Memory Architecture", formatted)


class TestStats(unittest.TestCase):
    """Tests for print_stats()."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, "test.db")

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_stats_empty_db(self):
        conn = ri.open_db(self.db_path)
        # Should not raise
        ri.print_stats(conn)
        conn.close()

    def test_stats_with_data(self):
        conn = ri.open_db(self.db_path)
        conn.execute(
            "INSERT INTO papers (id, title, year, venue, source_type, citation_count, level) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("test1", "Test Paper", 2025, "NeurIPS", "peer-reviewed", 42, 0),
        )
        conn.commit()
        # Should not raise
        ri.print_stats(conn)
        conn.close()


if __name__ == "__main__":
    unittest.main()
