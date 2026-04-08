"""Tests for scripts/research/fetch_semantic_scholar.py.

Run with:
    PYTHONPATH=. uv run pytest scripts/research/tests/test_fetch_semantic_scholar.py -v
"""

from __future__ import annotations

import importlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from teaparty.learning.research import fetch_semantic_scholar as fss


# ---------------------------------------------------------------------------
# Canned S2 response factory
# ---------------------------------------------------------------------------

def _make_s2_paper(
    paper_id="abc123",
    title="Test Paper",
    abstract="Test abstract",
    year=2025,
    citation_count=42,
    venue="NeurIPS",
    arxiv_id="2505.07087",
    doi="10.1234/test",
    pdf_url="https://example.com/paper.pdf",
    tldr_text="A short summary",
    categories=None,
    authors=None,
):
    return {
        "paperId": paper_id,
        "title": title,
        "abstract": abstract,
        "year": year,
        "citationCount": citation_count,
        "referenceCount": 20,
        "venue": venue,
        "openAccessPdf": {"url": pdf_url} if pdf_url else None,
        "externalIds": {
            "ArXiv": arxiv_id,
            "DOI": doi,
        },
        "tldr": {"model": "tldr@v2.0.0", "text": tldr_text} if tldr_text else None,
        "s2FieldsOfStudy": [
            {"category": c, "source": "s2-fos-model"}
            for c in (categories or ["Computer Science"])
        ],
        "authors": [
            {"name": n} for n in (authors or ["Alice Smith", "Bob Jones"])
        ],
    }


# ---------------------------------------------------------------------------
# _normalize_paper_id
# ---------------------------------------------------------------------------

class TestNormalizePaperId(unittest.TestCase):

    def test_normalize_paper_id_arxiv_bare(self):
        result = fss._normalize_paper_id("2505.07087")
        self.assertEqual(result, "ARXIV:2505.07087")

    def test_normalize_paper_id_arxiv_versioned(self):
        result = fss._normalize_paper_id("2505.07087v2")
        self.assertEqual(result, "ARXIV:2505.07087v2")

    def test_normalize_paper_id_doi(self):
        result = fss._normalize_paper_id("10.1145/123.456")
        self.assertEqual(result, "DOI:10.1145/123.456")

    def test_normalize_paper_id_already_prefixed(self):
        result = fss._normalize_paper_id("ARXIV:2505.07087")
        self.assertEqual(result, "ARXIV:2505.07087")

    def test_normalize_paper_id_already_prefixed_doi(self):
        result = fss._normalize_paper_id("DOI:10.1145/3442188.3445922")
        self.assertEqual(result, "DOI:10.1145/3442188.3445922")

    def test_normalize_paper_id_integer(self):
        # Pure integer corpus ID passes through unchanged
        result = fss._normalize_paper_id("12345678")
        self.assertEqual(result, "12345678")

    def test_normalize_paper_id_strips_whitespace(self):
        result = fss._normalize_paper_id("  2505.07087  ")
        self.assertEqual(result, "ARXIV:2505.07087")

    def test_normalize_paper_id_unknown_passthrough(self):
        # Unrecognized forms pass through for the API to reject
        result = fss._normalize_paper_id("some-random-id")
        self.assertEqual(result, "some-random-id")


# ---------------------------------------------------------------------------
# _clean_text
# ---------------------------------------------------------------------------

class TestCleanText(unittest.TestCase):

    def test_clean_text_collapses_internal_whitespace(self):
        result = fss._clean_text("hello   world\t\nnewline")
        self.assertEqual(result, "hello world newline")

    def test_clean_text_strips_leading_trailing(self):
        result = fss._clean_text("  padded  ")
        self.assertEqual(result, "padded")

    def test_clean_text_none_returns_empty_string(self):
        result = fss._clean_text(None)
        self.assertEqual(result, "")

    def test_clean_text_empty_string_returns_empty_string(self):
        result = fss._clean_text("")
        self.assertEqual(result, "")

    def test_clean_text_already_clean(self):
        result = fss._clean_text("already clean")
        self.assertEqual(result, "already clean")


# ---------------------------------------------------------------------------
# _extract_paper
# ---------------------------------------------------------------------------

class TestExtractPaper(unittest.TestCase):

    def test_extract_paper_full(self):
        raw = _make_s2_paper()
        paper = fss._extract_paper(raw)

        self.assertEqual(paper["s2_id"], "abc123")
        self.assertEqual(paper["arxiv_id"], "2505.07087")
        self.assertEqual(paper["doi"], "10.1234/test")
        self.assertEqual(paper["title"], "Test Paper")
        self.assertEqual(paper["abstract"], "Test abstract")
        self.assertEqual(paper["year"], 2025)
        self.assertEqual(paper["citation_count"], 42)
        self.assertEqual(paper["venue"], "NeurIPS")
        self.assertEqual(paper["pdf_url"], "https://example.com/paper.pdf")
        self.assertEqual(paper["tldr"], "A short summary")
        self.assertEqual(paper["authors"], ["Alice Smith", "Bob Jones"])
        self.assertEqual(paper["categories"], ["Computer Science"])

    def test_extract_paper_minimal(self):
        # Only paperId present; everything else null/absent
        raw = {"paperId": "min123"}
        paper = fss._extract_paper(raw)

        self.assertEqual(paper["s2_id"], "min123")
        self.assertEqual(paper["arxiv_id"], "")
        self.assertEqual(paper["doi"], "")
        self.assertEqual(paper["title"], "")
        self.assertEqual(paper["abstract"], "")
        self.assertEqual(paper["year"], 0)
        self.assertEqual(paper["citation_count"], 0)
        self.assertEqual(paper["venue"], "")
        self.assertEqual(paper["pdf_url"], "")
        self.assertEqual(paper["tldr"], "")
        self.assertEqual(paper["authors"], [])
        self.assertEqual(paper["categories"], [])

    def test_extract_paper_source_type_preprint_empty_venue(self):
        raw = _make_s2_paper(venue="")
        paper = fss._extract_paper(raw)
        self.assertEqual(paper["source_type"], "preprint")

    def test_extract_paper_source_type_preprint_arxiv_venue(self):
        raw = _make_s2_paper(venue="arXiv preprint")
        paper = fss._extract_paper(raw)
        self.assertEqual(paper["source_type"], "preprint")

    def test_extract_paper_source_type_peer_reviewed(self):
        raw = _make_s2_paper(venue="NeurIPS")
        paper = fss._extract_paper(raw)
        self.assertEqual(paper["source_type"], "peer-reviewed")

    def test_extract_paper_canonical_id_priority_arxiv_wins(self):
        # arXiv ID takes priority over DOI and S2 id
        raw = _make_s2_paper(arxiv_id="2505.07087", doi="10.1234/test", paper_id="s2abc")
        paper = fss._extract_paper(raw)
        self.assertEqual(paper["canonical_id"], "2505.07087")

    def test_extract_paper_canonical_id_doi_over_s2(self):
        # No arXiv; DOI takes priority over S2 corpus ID
        raw = _make_s2_paper(arxiv_id=None, doi="10.1234/test", paper_id="s2abc")
        # externalIds will have DOI but not ArXiv
        raw["externalIds"] = {"DOI": "10.1234/test"}
        paper = fss._extract_paper(raw)
        self.assertEqual(paper["canonical_id"], "10.1234/test")

    def test_extract_paper_canonical_id_s2_fallback(self):
        # No arXiv, no DOI -> falls back to S2 paper ID
        raw = _make_s2_paper(arxiv_id=None, doi=None, paper_id="s2only")
        raw["externalIds"] = {}
        paper = fss._extract_paper(raw)
        self.assertEqual(paper["canonical_id"], "s2only")

    def test_extract_paper_deduplicates_categories(self):
        raw = _make_s2_paper(categories=["CS", "CS", "Math"])
        paper = fss._extract_paper(raw)
        self.assertEqual(paper["categories"], ["CS", "Math"])

    def test_extract_paper_no_open_access_pdf(self):
        raw = _make_s2_paper(pdf_url=None)
        paper = fss._extract_paper(raw)
        self.assertEqual(paper["pdf_url"], "")

    def test_extract_paper_no_tldr(self):
        raw = _make_s2_paper(tldr_text=None)
        paper = fss._extract_paper(raw)
        self.assertEqual(paper["tldr"], "")

    def test_extract_paper_year_coerced_to_int(self):
        raw = _make_s2_paper(year=2023)
        paper = fss._extract_paper(raw)
        self.assertIsInstance(paper["year"], int)
        self.assertEqual(paper["year"], 2023)


# ---------------------------------------------------------------------------
# _apply_filters
# ---------------------------------------------------------------------------

class TestApplyFilters(unittest.TestCase):

    def _make_paper(self, citation_count=10, year=2024):
        raw = _make_s2_paper(citation_count=citation_count, year=year)
        return fss._extract_paper(raw)

    def test_apply_filters_citations_threshold(self):
        papers = [
            self._make_paper(citation_count=5),
            self._make_paper(citation_count=10),
            self._make_paper(citation_count=50),
        ]
        result = fss._apply_filters(papers, min_citations=10, year_range=None)
        self.assertEqual(len(result), 2)
        self.assertTrue(all(p["citation_count"] >= 10 for p in result))

    def test_apply_filters_citations_zero_passes_all(self):
        papers = [
            self._make_paper(citation_count=0),
            self._make_paper(citation_count=1),
        ]
        result = fss._apply_filters(papers, min_citations=0, year_range=None)
        self.assertEqual(len(result), 2)

    def test_apply_filters_year_range(self):
        papers = [
            self._make_paper(year=2020),
            self._make_paper(year=2023),
            self._make_paper(year=2025),
        ]
        result = fss._apply_filters(papers, min_citations=0, year_range="2022-2024")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["year"], 2023)

    def test_apply_filters_year_range_lower_bound_only(self):
        papers = [
            self._make_paper(year=2020),
            self._make_paper(year=2024),
            self._make_paper(year=2025),
        ]
        # "2023-9999" style: only lower bound matters in practice
        result = fss._apply_filters(papers, min_citations=0, year_range="2023-9999")
        self.assertEqual(len(result), 2)
        for p in result:
            self.assertGreaterEqual(p["year"], 2023)

    def test_apply_filters_no_filters_passes_everything(self):
        papers = [self._make_paper() for _ in range(5)]
        result = fss._apply_filters(papers, min_citations=0, year_range=None)
        self.assertEqual(len(result), 5)

    def test_apply_filters_combined_citations_and_year(self):
        papers = [
            self._make_paper(citation_count=100, year=2019),  # fails year
            self._make_paper(citation_count=5, year=2023),    # fails citations
            self._make_paper(citation_count=50, year=2023),   # passes both
        ]
        result = fss._apply_filters(papers, min_citations=10, year_range="2021-2025")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["citation_count"], 50)


# ---------------------------------------------------------------------------
# _build_dedup_index
# ---------------------------------------------------------------------------

class TestBuildDedupIndex(unittest.TestCase):

    def test_build_dedup_index_maps_all_three_id_types(self):
        entry = {
            "doi": "10.1234/test",
            "arxiv_id": "2505.07087",
            "s2_id": "abc123",
            "title": "Some Paper",
        }
        index = fss._build_dedup_index([entry])

        self.assertIn("10.1234/test", index)
        self.assertIn("2505.07087", index)
        self.assertIn("abc123", index)
        self.assertEqual(index["10.1234/test"], 0)
        self.assertEqual(index["2505.07087"], 0)
        self.assertEqual(index["abc123"], 0)

    def test_build_dedup_index_multiple_entries(self):
        entries = [
            {"doi": "10.1/a", "arxiv_id": "", "s2_id": "s1"},
            {"doi": "10.2/b", "arxiv_id": "1234.56789", "s2_id": "s2"},
        ]
        index = fss._build_dedup_index(entries)

        self.assertEqual(index["10.1/a"], 0)
        self.assertEqual(index["s1"], 0)
        self.assertEqual(index["10.2/b"], 1)
        self.assertEqual(index["1234.56789"], 1)
        self.assertEqual(index["s2"], 1)

    def test_build_dedup_index_empty_ids_not_indexed(self):
        entries = [{"doi": "", "arxiv_id": "", "s2_id": "", "title": "Ghost"}]
        index = fss._build_dedup_index(entries)
        self.assertEqual(len(index), 0)

    def test_build_dedup_index_empty_list(self):
        index = fss._build_dedup_index([])
        self.assertEqual(index, {})


# ---------------------------------------------------------------------------
# _merge_into_registry
# ---------------------------------------------------------------------------

class TestMergeIntoRegistry(unittest.TestCase):

    def _make_entry(self, **overrides):
        base = {
            "id": "2505.07087",
            "title": "Test Paper",
            "authors": ["Alice Smith"],
            "year": 2025,
            "venue": "NeurIPS",
            "source_type": "peer-reviewed",
            "citation_count": 42,
            "abstract": "Test abstract",
            "pdf_url": "https://example.com/paper.pdf",
            "arxiv_id": "2505.07087",
            "doi": "10.1234/test",
            "s2_id": "abc123",
            "categories": ["Computer Science"],
            "tldr": "Short summary",
            "fetched_at": "2026-03-09",
            "discovery_level": 0,
            "discovery_query": "agentic AI",
            "discovered_via": "s2_search",
        }
        base.update(overrides)
        return base

    def test_merge_existing_fills_empty_fields(self):
        # Existing entry has empty abstract; incoming has it filled
        existing = self._make_entry(abstract="", tldr="")
        registry = [existing]
        index = fss._build_dedup_index(registry)

        new_entry = self._make_entry(abstract="Filled abstract", tldr="Filled tldr")
        matched = fss._merge_into_registry(registry, index, new_entry)

        self.assertTrue(matched)
        self.assertEqual(registry[0]["abstract"], "Filled abstract")
        self.assertEqual(registry[0]["tldr"], "Filled tldr")

    def test_merge_existing_does_not_overwrite_non_empty_fields(self):
        # Existing title is present; incoming has a different title; existing wins
        existing = self._make_entry(title="Original Title")
        registry = [existing]
        index = fss._build_dedup_index(registry)

        new_entry = self._make_entry(title="Different Title")
        fss._merge_into_registry(registry, index, new_entry)

        self.assertEqual(registry[0]["title"], "Original Title")

    def test_merge_no_match_returns_false(self):
        # Registry contains a different paper; new_entry has no overlapping IDs
        existing = self._make_entry(
            arxiv_id="9999.99999",
            doi="10.9999/other",
            s2_id="zzz999",
        )
        registry = [existing]
        index = fss._build_dedup_index(registry)

        new_entry = self._make_entry(
            arxiv_id="1111.11111",
            doi="10.1111/new",
            s2_id="newid",
        )
        result = fss._merge_into_registry(registry, index, new_entry)

        self.assertFalse(result)
        # Registry unchanged
        self.assertEqual(len(registry), 1)

    def test_merge_match_via_doi(self):
        existing = self._make_entry(doi="10.1234/test", arxiv_id="", s2_id="")
        registry = [existing]
        index = fss._build_dedup_index(registry)

        new_entry = self._make_entry(doi="10.1234/test", abstract="New abstract")
        # existing abstract is non-empty, so it won't be overwritten
        matched = fss._merge_into_registry(registry, index, new_entry)
        self.assertTrue(matched)

    def test_merge_match_via_s2_id(self):
        existing = self._make_entry(arxiv_id="", doi="", s2_id="s2only")
        registry = [existing]
        index = fss._build_dedup_index(registry)

        new_entry = self._make_entry(arxiv_id="", doi="", s2_id="s2only")
        matched = fss._merge_into_registry(registry, index, new_entry)
        self.assertTrue(matched)

    def test_merge_updates_index_with_newly_learned_ids(self):
        # Existing has s2_id but no doi; incoming fills doi
        existing = self._make_entry(doi="", s2_id="s2abc", arxiv_id="")
        registry = [existing]
        index = fss._build_dedup_index(registry)
        self.assertNotIn("10.1234/filled", index)

        new_entry = self._make_entry(doi="10.1234/filled", s2_id="s2abc", arxiv_id="")
        fss._merge_into_registry(registry, index, new_entry)

        # The index should now include the newly filled doi
        self.assertIn("10.1234/filled", index)


# ---------------------------------------------------------------------------
# _make_registry_entry
# ---------------------------------------------------------------------------

class TestMakeRegistryEntry(unittest.TestCase):

    def test_make_registry_entry_all_fields_present(self):
        raw = _make_s2_paper()
        paper = fss._extract_paper(raw)
        entry = fss._make_registry_entry(
            paper,
            discovery_level=1,
            discovery_query="agentic AI",
            discovered_via="s2_search",
        )

        self.assertEqual(entry["id"], paper["canonical_id"])
        self.assertEqual(entry["title"], paper["title"])
        self.assertEqual(entry["authors"], paper["authors"])
        self.assertEqual(entry["year"], paper["year"])
        self.assertEqual(entry["venue"], paper["venue"])
        self.assertEqual(entry["source_type"], paper["source_type"])
        self.assertEqual(entry["citation_count"], paper["citation_count"])
        self.assertEqual(entry["abstract"], paper["abstract"])
        self.assertEqual(entry["pdf_url"], paper["pdf_url"])
        self.assertEqual(entry["arxiv_id"], paper["arxiv_id"])
        self.assertEqual(entry["doi"], paper["doi"])
        self.assertEqual(entry["s2_id"], paper["s2_id"])
        self.assertEqual(entry["categories"], paper["categories"])
        self.assertEqual(entry["tldr"], paper["tldr"])
        self.assertEqual(entry["discovery_level"], 1)
        self.assertEqual(entry["discovery_query"], "agentic AI")
        self.assertEqual(entry["discovered_via"], "s2_search")
        # fetched_at is today's ISO date
        self.assertRegex(entry["fetched_at"], r"^\d{4}-\d{2}-\d{2}$")


# ---------------------------------------------------------------------------
# _write_paper_markdown
# ---------------------------------------------------------------------------

class TestWritePaperMarkdown(unittest.TestCase):

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _paper(self, **overrides):
        raw = _make_s2_paper(**overrides)
        return fss._extract_paper(raw)

    def test_write_paper_markdown_creates_file(self):
        paper = self._paper()
        path = fss._write_paper_markdown(
            paper,
            output_dir=self.tmpdir,
            discovery_level=0,
            discovery_query="agentic AI",
            discovered_via="s2_search",
        )
        self.assertTrue(path.exists())
        content = path.read_text(encoding="utf-8")

        # Front matter fields
        self.assertIn('title: "Test Paper"', content)
        self.assertIn('year: 2025', content)
        self.assertIn('citation_count: 42', content)
        self.assertIn('source_type: "peer-reviewed"', content)
        self.assertIn('arxiv_id: "2505.07087"', content)
        self.assertIn('doi: "10.1234/test"', content)
        self.assertIn('discovery_query: "agentic AI"', content)
        self.assertIn('discovered_via: "s2_search"', content)
        self.assertIn('discovery_level: 0', content)

        # Markdown sections
        self.assertIn("## Abstract", content)
        self.assertIn("Test abstract", content)
        self.assertIn("## Notes", content)
        self.assertIn("## Relevance", content)

    def test_write_paper_markdown_with_tldr(self):
        paper = self._paper(tldr_text="Concise summary of findings")
        path = fss._write_paper_markdown(
            paper,
            output_dir=self.tmpdir,
            discovery_level=0,
            discovery_query="test query",
            discovered_via="s2_search",
        )
        content = path.read_text(encoding="utf-8")
        self.assertIn("## TL;DR", content)
        self.assertIn("Concise summary of findings", content)

    def test_write_paper_markdown_without_tldr_omits_section(self):
        paper = self._paper(tldr_text=None)
        path = fss._write_paper_markdown(
            paper,
            output_dir=self.tmpdir,
            discovery_level=0,
            discovery_query="test",
            discovered_via="s2_search",
        )
        content = path.read_text(encoding="utf-8")
        self.assertNotIn("## TL;DR", content)

    def test_write_paper_markdown_safe_filename(self):
        # DOI-based canonical IDs contain slashes; must be sanitised for filename
        raw = _make_s2_paper(arxiv_id=None, doi="10.1145/123.456", paper_id="doionly")
        raw["externalIds"] = {"DOI": "10.1145/123.456"}
        paper = fss._extract_paper(raw)
        path = fss._write_paper_markdown(
            paper,
            output_dir=self.tmpdir,
            discovery_level=0,
            discovery_query="test",
            discovered_via="s2_search",
        )
        # Filename must not contain a slash
        self.assertNotIn("/", path.name)
        self.assertTrue(path.exists())

    def test_write_paper_markdown_no_abstract_placeholder(self):
        paper = self._paper(abstract=None)
        # _make_s2_paper passes abstract to the raw dict; override directly
        raw = _make_s2_paper()
        raw["abstract"] = None
        paper = fss._extract_paper(raw)
        path = fss._write_paper_markdown(
            paper,
            output_dir=self.tmpdir,
            discovery_level=0,
            discovery_query="test",
            discovered_via="s2_search",
        )
        content = path.read_text(encoding="utf-8")
        self.assertIn("[No abstract available]", content)


# ---------------------------------------------------------------------------
# _process_papers end-to-end
# ---------------------------------------------------------------------------

class TestProcessPapersEndToEnd(unittest.TestCase):

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        self.output_dir = self.tmpdir / "papers"
        self.registry_path = self.tmpdir / "sources.json"

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_process_papers_end_to_end(self):
        raw_papers = [
            _make_s2_paper(
                paper_id="p1",
                title="Paper One",
                citation_count=100,
                year=2024,
                arxiv_id="2501.00001",
                doi="10.1/p1",
            ),
            _make_s2_paper(
                paper_id="p2",
                title="Paper Two",
                citation_count=200,
                year=2023,
                arxiv_id="2501.00002",
                doi="10.1/p2",
            ),
        ]

        fss._process_papers(
            raw_papers=raw_papers,
            output_dir=self.output_dir,
            registry_path=self.registry_path,
            min_citations=0,
            year_range=None,
            discovery_level=0,
            discovery_query="agentic AI",
            discovered_via="s2_search",
        )

        # Registry file was written and contains two entries
        self.assertTrue(self.registry_path.exists())
        registry = json.loads(self.registry_path.read_text(encoding="utf-8"))
        self.assertEqual(len(registry), 2)
        titles = {e["title"] for e in registry}
        self.assertIn("Paper One", titles)
        self.assertIn("Paper Two", titles)

        # Markdown files were created for each paper
        md_files = list(self.output_dir.glob("*.md"))
        self.assertEqual(len(md_files), 2)

    def test_process_papers_filters_applied(self):
        raw_papers = [
            _make_s2_paper(paper_id="low", title="Low Cites", citation_count=3),
            _make_s2_paper(paper_id="high", title="High Cites", citation_count=50),
        ]

        fss._process_papers(
            raw_papers=raw_papers,
            output_dir=self.output_dir,
            registry_path=self.registry_path,
            min_citations=10,
            year_range=None,
            discovery_level=0,
            discovery_query="test",
            discovered_via="s2_search",
        )

        registry = json.loads(self.registry_path.read_text(encoding="utf-8"))
        self.assertEqual(len(registry), 1)
        self.assertEqual(registry[0]["title"], "High Cites")

    def test_process_papers_deduplication(self):
        # Same paper ID in both raw inputs — should produce one registry entry
        raw_papers = [
            _make_s2_paper(paper_id="dup", arxiv_id="1111.11111", doi="10.1/dup"),
            _make_s2_paper(paper_id="dup", arxiv_id="1111.11111", doi="10.1/dup"),
        ]

        fss._process_papers(
            raw_papers=raw_papers,
            output_dir=self.output_dir,
            registry_path=self.registry_path,
            min_citations=0,
            year_range=None,
            discovery_level=0,
            discovery_query="dedup test",
            discovered_via="s2_search",
        )

        registry = json.loads(self.registry_path.read_text(encoding="utf-8"))
        self.assertEqual(len(registry), 1)

    def test_process_papers_incremental_merge(self):
        # First run: paper with no abstract
        raw_first = [_make_s2_paper(paper_id="inc1", arxiv_id="2222.22222", doi="")]
        raw_first[0]["abstract"] = None
        raw_first[0]["externalIds"] = {"ArXiv": "2222.22222"}

        fss._process_papers(
            raw_papers=raw_first,
            output_dir=self.output_dir,
            registry_path=self.registry_path,
            min_citations=0,
            year_range=None,
            discovery_level=0,
            discovery_query="first run",
            discovered_via="s2_search",
        )

        # Second run: same paper but now has abstract
        raw_second = [_make_s2_paper(
            paper_id="inc1",
            arxiv_id="2222.22222",
            doi="",
            abstract="Now has an abstract",
        )]
        raw_second[0]["externalIds"] = {"ArXiv": "2222.22222"}

        fss._process_papers(
            raw_papers=raw_second,
            output_dir=self.output_dir,
            registry_path=self.registry_path,
            min_citations=0,
            year_range=None,
            discovery_level=0,
            discovery_query="second run",
            discovered_via="s2_search",
        )

        registry = json.loads(self.registry_path.read_text(encoding="utf-8"))
        # Still one entry, but abstract was filled in
        self.assertEqual(len(registry), 1)
        self.assertEqual(registry[0]["abstract"], "Now has an abstract")

    def test_process_papers_empty_input(self):
        fss._process_papers(
            raw_papers=[],
            output_dir=self.output_dir,
            registry_path=self.registry_path,
            min_citations=0,
            year_range=None,
            discovery_level=0,
            discovery_query="empty",
            discovered_via="s2_search",
        )

        registry = json.loads(self.registry_path.read_text(encoding="utf-8"))
        self.assertEqual(registry, [])
        md_files = list(self.output_dir.glob("*.md")) if self.output_dir.exists() else []
        self.assertEqual(md_files, [])


if __name__ == "__main__":
    unittest.main()
