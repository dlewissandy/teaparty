"""Tests for scripts/research/fetch_arxiv.py.

Run from the repo root:
    PYTHONPATH=. uv run pytest scripts/research/tests/test_fetch_arxiv.py -v
"""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
import urllib.error
from io import BytesIO
from pathlib import Path
from unittest.mock import MagicMock, patch

from teaparty.learning.research.fetch_arxiv import (
    _build_url,
    _clean_text,
    _load_registry,
    _make_registry_entry,
    _parse_entry,
    _parse_feed,
    _sanitize_arxiv_id,
    _save_registry,
    _write_paper_markdown,
    fetch_papers,
)
import xml.etree.ElementTree as ET

# ---------------------------------------------------------------------------
# Canned Atom XML used across multiple tests
# ---------------------------------------------------------------------------

CANNED_ATOM_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"
      xmlns:arxiv="http://arxiv.org/schemas/atom">
  <title>ArXiv Query</title>
  <opensearch:totalResults xmlns:opensearch="http://a9.com/-/spec/opensearch/1.1/">2</opensearch:totalResults>
  <entry>
    <id>http://arxiv.org/abs/2505.07087v1</id>
    <title>Test Paper One: A Study</title>
    <summary>This is the abstract of paper one. It has multiple   spaces and
newlines that should be cleaned.</summary>
    <published>2025-05-07T00:00:00Z</published>
    <updated>2025-05-08T00:00:00Z</updated>
    <author><name>Alice Smith</name></author>
    <author><name>Bob Jones</name></author>
    <category term="cs.AI"/>
    <category term="cs.CL"/>
    <link title="pdf" href="https://arxiv.org/pdf/2505.07087v1" rel="related" type="application/pdf"/>
    <arxiv:comment>10 pages, 3 figures</arxiv:comment>
  </entry>
  <entry>
    <id>http://arxiv.org/abs/2403.12345v2</id>
    <title>Test Paper Two</title>
    <summary>Abstract of paper two.</summary>
    <published>2024-03-15T00:00:00Z</published>
    <updated>2024-04-01T00:00:00Z</updated>
    <author><name>Carol Lee</name></author>
    <category term="cs.MA"/>
    <link title="pdf" href="https://arxiv.org/pdf/2403.12345v2" rel="related" type="application/pdf"/>
  </entry>
</feed>
"""

EMPTY_FEED_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"
      xmlns:arxiv="http://arxiv.org/schemas/atom">
  <title>ArXiv Query</title>
</feed>
"""

MALFORMED_XML = b"<feed><entry><id>broken</entry>"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_paper(
    arxiv_id: str = "2505.07087",
    source_id: str = "2505.07087v1",
    title: str = "Test Paper One: A Study",
    authors: list[str] | None = None,
    abstract: str = "This is the abstract of paper one. It has multiple spaces and newlines that should be cleaned.",
    published: str = "2025-05-07T00:00:00Z",
    updated: str = "2025-05-08T00:00:00Z",
    year: int = 2025,
    categories: list[str] | None = None,
    pdf_url: str = "https://arxiv.org/pdf/2505.07087v1",
    comment: str = "10 pages, 3 figures",
) -> dict:
    return {
        "arxiv_id": arxiv_id,
        "source_id": source_id,
        "title": title,
        "authors": authors if authors is not None else ["Alice Smith", "Bob Jones"],
        "abstract": abstract,
        "published": published,
        "updated": updated,
        "year": year,
        "categories": categories if categories is not None else ["cs.AI", "cs.CL"],
        "pdf_url": pdf_url,
        "comment": comment,
    }


# ---------------------------------------------------------------------------
# _build_url
# ---------------------------------------------------------------------------

class BuildUrlTests(unittest.TestCase):
    def test_build_url_basic(self) -> None:
        url = _build_url("agentic AI", start=0, max_results=20, sort_by="relevance")
        self.assertIn("export.arxiv.org/api/query", url)
        self.assertIn("search_query=", url)
        self.assertIn("agentic", url)
        self.assertIn("max_results=20", url)
        self.assertIn("start=0", url)
        self.assertIn("sortBy=relevance", url)
        self.assertIn("sortOrder=descending", url)

    def test_build_url_with_category(self) -> None:
        # Caller is responsible for prepending category prefix; _build_url just
        # encodes whatever query string it receives.
        query = "cat:cs.AI AND agentic AI"
        url = _build_url(query, start=10, max_results=50, sort_by="submittedDate")
        self.assertIn("cat%3Acs.AI", url)
        self.assertIn("start=10", url)
        self.assertIn("max_results=50", url)
        self.assertIn("sortBy=submittedDate", url)

    def test_build_url_pagination_params(self) -> None:
        url = _build_url("multi-agent", start=100, max_results=5, sort_by="lastUpdatedDate")
        self.assertIn("start=100", url)
        self.assertIn("max_results=5", url)


# ---------------------------------------------------------------------------
# _parse_feed
# ---------------------------------------------------------------------------

class ParseFeedTests(unittest.TestCase):
    def test_parse_feed_valid(self) -> None:
        papers = _parse_feed(CANNED_ATOM_XML)
        self.assertEqual(len(papers), 2)

        p1 = papers[0]
        self.assertEqual(p1["arxiv_id"], "2505.07087")
        self.assertEqual(p1["source_id"], "2505.07087v1")
        self.assertEqual(p1["title"], "Test Paper One: A Study")
        self.assertIn("Alice Smith", p1["authors"])
        self.assertIn("Bob Jones", p1["authors"])
        self.assertEqual(p1["year"], 2025)
        self.assertIn("cs.AI", p1["categories"])
        self.assertIn("cs.CL", p1["categories"])
        self.assertEqual(p1["pdf_url"], "https://arxiv.org/pdf/2505.07087v1")
        self.assertEqual(p1["comment"], "10 pages, 3 figures")

        p2 = papers[1]
        self.assertEqual(p2["arxiv_id"], "2403.12345")
        self.assertEqual(p2["authors"], ["Carol Lee"])
        self.assertEqual(p2["year"], 2024)

    def test_parse_feed_empty(self) -> None:
        papers = _parse_feed(EMPTY_FEED_XML)
        self.assertEqual(papers, [])

    def test_parse_feed_malformed(self) -> None:
        papers = _parse_feed(MALFORMED_XML)
        self.assertEqual(papers, [])


# ---------------------------------------------------------------------------
# _parse_entry
# ---------------------------------------------------------------------------

class ParseEntryTests(unittest.TestCase):
    """Test _parse_entry directly by constructing minimal ET.Element trees."""

    ATOM_NS = "http://www.w3.org/2005/Atom"
    ARXIV_NS = "http://arxiv.org/schemas/atom"

    def _make_entry_element(
        self,
        arxiv_id: str = "http://arxiv.org/abs/2505.07087v1",
        title: str = "A Test Paper",
        summary: str = "Abstract text.",
        published: str = "2025-05-07T00:00:00Z",
        updated: str = "2025-05-08T00:00:00Z",
        authors: list[str] | None = None,
        categories: list[str] | None = None,
        pdf_href: str = "https://arxiv.org/pdf/2505.07087v1",
        comment: str | None = None,
    ) -> ET.Element:
        ns = self.ATOM_NS
        arxiv_ns = self.ARXIV_NS

        entry = ET.Element(f"{{{ns}}}entry")

        id_el = ET.SubElement(entry, f"{{{ns}}}id")
        id_el.text = arxiv_id

        title_el = ET.SubElement(entry, f"{{{ns}}}title")
        title_el.text = title

        summary_el = ET.SubElement(entry, f"{{{ns}}}summary")
        summary_el.text = summary

        pub_el = ET.SubElement(entry, f"{{{ns}}}published")
        pub_el.text = published

        upd_el = ET.SubElement(entry, f"{{{ns}}}updated")
        upd_el.text = updated

        for author_name in (authors or ["Alice Smith"]):
            author_el = ET.SubElement(entry, f"{{{ns}}}author")
            name_el = ET.SubElement(author_el, f"{{{ns}}}name")
            name_el.text = author_name

        for cat in (categories or ["cs.AI"]):
            cat_el = ET.SubElement(entry, f"{{{ns}}}category")
            cat_el.set("term", cat)

        link_el = ET.SubElement(entry, f"{{{ns}}}link")
        link_el.set("title", "pdf")
        link_el.set("href", pdf_href)

        if comment is not None:
            comment_el = ET.SubElement(entry, f"{{{arxiv_ns}}}comment")
            comment_el.text = comment

        return entry

    def _ns_dict(self) -> dict:
        return {"a": self.ATOM_NS, "arxiv": self.ARXIV_NS}

    def test_parse_entry_extracts_fields(self) -> None:
        entry = self._make_entry_element(
            authors=["Alice Smith", "Bob Jones"],
            categories=["cs.AI", "cs.CL"],
            comment="10 pages",
        )
        paper = _parse_entry(entry, self._ns_dict())
        self.assertIsNotNone(paper)
        self.assertEqual(paper["arxiv_id"], "2505.07087")
        self.assertEqual(paper["source_id"], "2505.07087v1")
        self.assertEqual(paper["title"], "A Test Paper")
        self.assertEqual(paper["abstract"], "Abstract text.")
        self.assertEqual(paper["authors"], ["Alice Smith", "Bob Jones"])
        self.assertEqual(paper["published"], "2025-05-07T00:00:00Z")
        self.assertEqual(paper["updated"], "2025-05-08T00:00:00Z")
        self.assertEqual(paper["year"], 2025)
        self.assertEqual(paper["categories"], ["cs.AI", "cs.CL"])
        self.assertEqual(paper["pdf_url"], "https://arxiv.org/pdf/2505.07087v1")
        self.assertEqual(paper["comment"], "10 pages")

    def test_parse_entry_strips_version(self) -> None:
        entry = self._make_entry_element(arxiv_id="http://arxiv.org/abs/2505.07087v1")
        paper = _parse_entry(entry, self._ns_dict())
        self.assertEqual(paper["arxiv_id"], "2505.07087")
        self.assertEqual(paper["source_id"], "2505.07087v1")

    def test_parse_entry_strips_version_multidigit(self) -> None:
        entry = self._make_entry_element(arxiv_id="http://arxiv.org/abs/2403.12345v12")
        paper = _parse_entry(entry, self._ns_dict())
        self.assertEqual(paper["arxiv_id"], "2403.12345")
        self.assertEqual(paper["source_id"], "2403.12345v12")

    def test_parse_entry_returns_none_without_id(self) -> None:
        # Construct an entry element with no <id> child
        ns = self.ATOM_NS
        entry = ET.Element(f"{{{ns}}}entry")
        title_el = ET.SubElement(entry, f"{{{ns}}}title")
        title_el.text = "No ID Paper"
        result = _parse_entry(entry, self._ns_dict())
        self.assertIsNone(result)

    def test_parse_entry_no_comment(self) -> None:
        entry = self._make_entry_element(comment=None)
        paper = _parse_entry(entry, self._ns_dict())
        self.assertEqual(paper["comment"], "")


# ---------------------------------------------------------------------------
# _clean_text
# ---------------------------------------------------------------------------

class CleanTextTests(unittest.TestCase):
    def test_clean_text_collapses_spaces(self) -> None:
        self.assertEqual(_clean_text("hello   world"), "hello world")

    def test_clean_text_collapses_newlines(self) -> None:
        self.assertEqual(_clean_text("hello\nworld"), "hello world")

    def test_clean_text_strips_edges(self) -> None:
        self.assertEqual(_clean_text("  hello world  "), "hello world")

    def test_clean_text_mixed_whitespace(self) -> None:
        result = _clean_text("  multiple   spaces\nand\nnewlines  ")
        self.assertEqual(result, "multiple spaces and newlines")

    def test_clean_text_empty_string(self) -> None:
        self.assertEqual(_clean_text(""), "")

    def test_clean_text_none(self) -> None:
        self.assertEqual(_clean_text(None), "")

    def test_clean_text_no_change_needed(self) -> None:
        self.assertEqual(_clean_text("already clean"), "already clean")


# ---------------------------------------------------------------------------
# _sanitize_arxiv_id
# ---------------------------------------------------------------------------

class SanitizeArxivIdTests(unittest.TestCase):
    def test_sanitize_replaces_slash(self) -> None:
        self.assertEqual(_sanitize_arxiv_id("hep-th/0404001"), "hep-th-0404001")

    def test_sanitize_no_slash(self) -> None:
        self.assertEqual(_sanitize_arxiv_id("2505.07087"), "2505.07087")

    def test_sanitize_multiple_slashes(self) -> None:
        self.assertEqual(_sanitize_arxiv_id("a/b/c"), "a-b-c")

    def test_sanitize_empty_string(self) -> None:
        self.assertEqual(_sanitize_arxiv_id(""), "")


# ---------------------------------------------------------------------------
# _load_registry
# ---------------------------------------------------------------------------

class LoadRegistryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_dir = tempfile.mkdtemp()

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_load_registry_missing_file(self) -> None:
        path = Path(self.tmp_dir) / "does_not_exist.json"
        entries, ids = _load_registry(path)
        self.assertEqual(entries, [])
        self.assertEqual(ids, set())

    def test_load_registry_valid(self) -> None:
        data = [
            {"arxiv_id": "2505.07087", "id": "2505.07087", "title": "Paper One"},
            {"arxiv_id": "2403.12345", "id": "2403.12345", "title": "Paper Two"},
        ]
        path = Path(self.tmp_dir) / "registry.json"
        path.write_text(json.dumps(data), encoding="utf-8")

        entries, ids = _load_registry(path)
        self.assertEqual(len(entries), 2)
        self.assertIn("2505.07087", ids)
        self.assertIn("2403.12345", ids)

    def test_load_registry_uses_id_fallback(self) -> None:
        # Entry has only "id", not "arxiv_id"
        data = [{"id": "1234.56789", "title": "Old Style Entry"}]
        path = Path(self.tmp_dir) / "registry.json"
        path.write_text(json.dumps(data), encoding="utf-8")

        entries, ids = _load_registry(path)
        self.assertIn("1234.56789", ids)

    def test_load_registry_non_array_returns_empty(self) -> None:
        path = Path(self.tmp_dir) / "registry.json"
        path.write_text(json.dumps({"not": "an array"}), encoding="utf-8")

        entries, ids = _load_registry(path)
        self.assertEqual(entries, [])
        self.assertEqual(ids, set())

    def test_load_registry_malformed_json_returns_empty(self) -> None:
        path = Path(self.tmp_dir) / "registry.json"
        path.write_text("{ this is not valid JSON ]", encoding="utf-8")

        entries, ids = _load_registry(path)
        self.assertEqual(entries, [])
        self.assertEqual(ids, set())


# ---------------------------------------------------------------------------
# _save_registry
# ---------------------------------------------------------------------------

class SaveRegistryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_dir = tempfile.mkdtemp()

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_save_registry_creates_file(self) -> None:
        path = Path(self.tmp_dir) / "registry.json"
        entries = [{"arxiv_id": "2505.07087", "title": "A Paper"}]

        _save_registry(path, entries)

        self.assertTrue(path.exists())
        loaded = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0]["arxiv_id"], "2505.07087")

    def test_save_registry_creates_parent_dirs(self) -> None:
        path = Path(self.tmp_dir) / "subdir" / "nested" / "registry.json"
        entries = [{"arxiv_id": "1111.22222", "title": "Nested Paper"}]

        _save_registry(path, entries)

        self.assertTrue(path.exists())

    def test_save_registry_overwrites_existing(self) -> None:
        path = Path(self.tmp_dir) / "registry.json"
        path.write_text(json.dumps([{"arxiv_id": "old"}]), encoding="utf-8")

        new_entries = [{"arxiv_id": "new_1"}, {"arxiv_id": "new_2"}]
        _save_registry(path, new_entries)

        loaded = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(len(loaded), 2)
        self.assertEqual(loaded[0]["arxiv_id"], "new_1")

    def test_save_registry_roundtrip(self) -> None:
        path = Path(self.tmp_dir) / "registry.json"
        paper = _make_paper()
        entry = _make_registry_entry(paper, "agentic AI")

        _save_registry(path, [entry])

        entries, ids = _load_registry(path)
        self.assertEqual(len(entries), 1)
        self.assertIn("2505.07087", ids)


# ---------------------------------------------------------------------------
# _make_registry_entry
# ---------------------------------------------------------------------------

class MakeRegistryEntryTests(unittest.TestCase):
    def test_make_registry_entry_fields(self) -> None:
        paper = _make_paper()
        entry = _make_registry_entry(paper, "agentic AI")

        self.assertEqual(entry["id"], "2505.07087")
        self.assertEqual(entry["arxiv_id"], "2505.07087")
        self.assertEqual(entry["title"], "Test Paper One: A Study")
        self.assertEqual(entry["authors"], ["Alice Smith", "Bob Jones"])
        self.assertEqual(entry["year"], 2025)
        self.assertEqual(entry["venue"], "arXiv preprint")
        self.assertEqual(entry["source_type"], "preprint")
        self.assertEqual(entry["citation_count"], 0)
        self.assertEqual(entry["pdf_url"], "https://arxiv.org/pdf/2505.07087v1")
        self.assertEqual(entry["categories"], ["cs.AI", "cs.CL"])
        self.assertEqual(entry["doi"], "")
        self.assertEqual(entry["s2_id"], "")
        self.assertEqual(entry["tldr"], "")
        self.assertEqual(entry["discovery_level"], 0)
        self.assertEqual(entry["discovery_query"], "agentic AI")
        self.assertEqual(entry["discovered_via"], "arxiv_search")

    def test_make_registry_entry_has_fetched_at(self) -> None:
        paper = _make_paper()
        entry = _make_registry_entry(paper, "query")
        # fetched_at should be a non-empty ISO date string
        self.assertTrue(entry["fetched_at"])
        self.assertRegex(entry["fetched_at"], r"\d{4}-\d{2}-\d{2}")

    def test_make_registry_entry_query_preserved(self) -> None:
        paper = _make_paper()
        entry = _make_registry_entry(paper, "multi-agent systems")
        self.assertEqual(entry["discovery_query"], "multi-agent systems")


# ---------------------------------------------------------------------------
# _write_paper_markdown
# ---------------------------------------------------------------------------

class WritePaperMarkdownTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_dir = tempfile.mkdtemp()
        self.output_dir = Path(self.tmp_dir) / "papers"
        self.output_dir.mkdir()

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_write_paper_markdown_creates_file(self) -> None:
        paper = _make_paper()
        path = _write_paper_markdown(paper, self.output_dir, "agentic AI")

        self.assertTrue(path.exists())
        self.assertEqual(path.name, "2505.07087.md")

    def test_write_paper_markdown_yaml_frontmatter(self) -> None:
        paper = _make_paper()
        path = _write_paper_markdown(paper, self.output_dir, "agentic AI")
        content = path.read_text(encoding="utf-8")

        self.assertTrue(content.startswith("---\n"))
        self.assertIn('paper_id: "2505.07087"', content)
        self.assertIn('source: arxiv', content)
        self.assertIn('source_id: "2505.07087v1"', content)
        self.assertIn('title: "Test Paper One: A Study"', content)
        self.assertIn('"Alice Smith"', content)
        self.assertIn('"Bob Jones"', content)
        self.assertIn('year: 2025', content)
        self.assertIn('venue: "arXiv preprint"', content)
        self.assertIn('citation_count: 0', content)
        self.assertIn('source_type: "preprint"', content)
        self.assertIn('pdf_url: "https://arxiv.org/pdf/2505.07087v1"', content)
        self.assertIn('"cs.AI"', content)
        self.assertIn('discovery_level: 0', content)
        self.assertIn('discovery_query: "agentic AI"', content)
        self.assertIn('discovered_via: "arxiv_search"', content)

    def test_write_paper_markdown_has_abstract_section(self) -> None:
        paper = _make_paper()
        path = _write_paper_markdown(paper, self.output_dir, "agentic AI")
        content = path.read_text(encoding="utf-8")

        self.assertIn("## Abstract", content)
        self.assertIn(paper["abstract"], content)

    def test_write_paper_markdown_has_notes_and_relevance_sections(self) -> None:
        paper = _make_paper()
        path = _write_paper_markdown(paper, self.output_dir, "test query")
        content = path.read_text(encoding="utf-8")

        self.assertIn("## Notes", content)
        self.assertIn("## Relevance", content)

    def test_write_paper_markdown_sanitizes_slash_in_id(self) -> None:
        paper = _make_paper(arxiv_id="hep-th/0404001", source_id="hep-th/0404001v1")
        path = _write_paper_markdown(paper, self.output_dir, "query")
        # Filename should have slash replaced with dash
        self.assertEqual(path.name, "hep-th-0404001.md")
        self.assertTrue(path.exists())

    def test_write_paper_markdown_escapes_quotes_in_title(self) -> None:
        paper = _make_paper(title='Paper with "quotes" in title')
        path = _write_paper_markdown(paper, self.output_dir, "query")
        content = path.read_text(encoding="utf-8")
        # The title value in YAML should have quotes escaped
        self.assertIn('\\"quotes\\"', content)


# ---------------------------------------------------------------------------
# fetch_papers -- integration / pipeline tests
# ---------------------------------------------------------------------------

class FetchPapersTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_dir = tempfile.mkdtemp()
        self.output_dir = Path(self.tmp_dir) / "papers"
        self.registry_path = Path(self.tmp_dir) / "registry.json"

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def _mock_urlopen(self, xml_bytes: bytes):
        """Return a context manager mock that yields a readable response."""
        mock_resp = MagicMock()
        mock_resp.read.return_value = xml_bytes
        mock_resp.__enter__ = lambda s: mock_resp
        mock_resp.__exit__ = MagicMock(return_value=False)
        return mock_resp

    @patch("teaparty.learning.research.fetch_arxiv.time.sleep")
    @patch("teaparty.learning.research.fetch_arxiv.urllib.request.urlopen")
    def test_fetch_papers_end_to_end(self, mock_urlopen, mock_sleep) -> None:
        mock_urlopen.return_value = self._mock_urlopen(CANNED_ATOM_XML)

        fetch_papers(
            query="agentic AI",
            max_results=10,
            output_dir=self.output_dir,
            registry_path=self.registry_path,
            category=None,
            sort_by="relevance",
            start_offset=0,
        )

        # Both paper markdown files should have been written
        self.assertTrue((self.output_dir / "2505.07087.md").exists())
        self.assertTrue((self.output_dir / "2403.12345.md").exists())

        # Registry should be created with both entries
        self.assertTrue(self.registry_path.exists())
        entries, ids = _load_registry(self.registry_path)
        self.assertEqual(len(entries), 2)
        self.assertIn("2505.07087", ids)
        self.assertIn("2403.12345", ids)

    @patch("teaparty.learning.research.fetch_arxiv.time.sleep")
    @patch("teaparty.learning.research.fetch_arxiv.urllib.request.urlopen")
    def test_fetch_papers_dedup(self, mock_urlopen, mock_sleep) -> None:
        # Pre-populate registry with one of the two papers
        existing = [{"arxiv_id": "2505.07087", "id": "2505.07087", "title": "Already here"}]
        self.registry_path.write_text(json.dumps(existing), encoding="utf-8")

        mock_urlopen.return_value = self._mock_urlopen(CANNED_ATOM_XML)

        fetch_papers(
            query="agentic AI",
            max_results=10,
            output_dir=self.output_dir,
            registry_path=self.registry_path,
            category=None,
            sort_by="relevance",
            start_offset=0,
        )

        # Only the new paper should be written
        self.assertFalse((self.output_dir / "2505.07087.md").exists())
        self.assertTrue((self.output_dir / "2403.12345.md").exists())

        # Registry should now have both entries (original + 1 new)
        entries, ids = _load_registry(self.registry_path)
        self.assertEqual(len(entries), 2)
        self.assertIn("2505.07087", ids)
        self.assertIn("2403.12345", ids)

    @patch("teaparty.learning.research.fetch_arxiv.time.sleep")
    @patch("teaparty.learning.research.fetch_arxiv.urllib.request.urlopen")
    def test_fetch_papers_category_prepended_to_query(self, mock_urlopen, mock_sleep) -> None:
        mock_urlopen.return_value = self._mock_urlopen(CANNED_ATOM_XML)

        fetch_papers(
            query="multi-agent",
            max_results=10,
            output_dir=self.output_dir,
            registry_path=self.registry_path,
            category="cs.AI",
            sort_by="relevance",
            start_offset=0,
        )

        # The URL passed to urlopen should contain the category prefix
        call_args = mock_urlopen.call_args
        url_used = call_args[0][0]
        self.assertIn("cat%3Acs.AI", url_used)
        self.assertIn("multi-agent", url_used)

    @patch("teaparty.learning.research.fetch_arxiv.time.sleep")
    @patch("teaparty.learning.research.fetch_arxiv.urllib.request.urlopen")
    def test_fetch_papers_network_error_stops_gracefully(self, mock_urlopen, mock_sleep) -> None:
        mock_urlopen.side_effect = urllib.error.URLError("connection refused")

        # Should not raise; just log and return without writing anything
        fetch_papers(
            query="test",
            max_results=5,
            output_dir=self.output_dir,
            registry_path=self.registry_path,
            category=None,
            sort_by="relevance",
            start_offset=0,
        )

        # No markdown files should have been created
        md_files = list(self.output_dir.glob("*.md")) if self.output_dir.exists() else []
        self.assertEqual(md_files, [])
        # Registry should not have been created
        self.assertFalse(self.registry_path.exists())

    @patch("teaparty.learning.research.fetch_arxiv.time.sleep")
    @patch("teaparty.learning.research.fetch_arxiv.urllib.request.urlopen")
    def test_fetch_papers_all_already_in_registry(self, mock_urlopen, mock_sleep) -> None:
        # Pre-populate registry with BOTH papers
        existing = [
            {"arxiv_id": "2505.07087", "id": "2505.07087", "title": "Paper One"},
            {"arxiv_id": "2403.12345", "id": "2403.12345", "title": "Paper Two"},
        ]
        self.registry_path.write_text(json.dumps(existing), encoding="utf-8")

        mock_urlopen.return_value = self._mock_urlopen(CANNED_ATOM_XML)

        fetch_papers(
            query="agentic AI",
            max_results=10,
            output_dir=self.output_dir,
            registry_path=self.registry_path,
            category=None,
            sort_by="relevance",
            start_offset=0,
        )

        # No new markdown files should be written
        md_files = list(self.output_dir.glob("*.md")) if self.output_dir.exists() else []
        self.assertEqual(md_files, [])

        # Registry should still have exactly 2 entries (not duplicated)
        entries, _ = _load_registry(self.registry_path)
        self.assertEqual(len(entries), 2)


if __name__ == "__main__":
    unittest.main()
