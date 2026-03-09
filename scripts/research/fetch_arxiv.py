#!/usr/bin/env python3
"""Fetch academic papers from the arXiv REST API and write structured records.

Usage:
    python fetch_arxiv.py --query "agentic AI" --max-results 20 \\
        --output papers/ --registry sources.json \\
        [--category cs.AI] [--sort-by relevance|lastUpdatedDate|submittedDate] \\
        [--start 0]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import date
from pathlib import Path


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ARXIV_API_URL = "http://export.arxiv.org/api/query"
ATOM_NS = "http://www.w3.org/2005/Atom"
ARXIV_NS = "http://arxiv.org/schemas/atom"
PAGE_SIZE = 100  # arXiv recommends <= 100 per request
RATE_LIMIT_SECONDS = 3  # arXiv policy: be polite

VALID_SORT_BY = {"relevance", "lastUpdatedDate", "submittedDate"}


# ---------------------------------------------------------------------------
# Progress logging
# ---------------------------------------------------------------------------

def _log(msg: str) -> None:
    print(f"[fetch_arxiv] {msg}", file=sys.stderr)


# ---------------------------------------------------------------------------
# arXiv API
# ---------------------------------------------------------------------------

def _build_url(query: str, start: int, max_results: int, sort_by: str) -> str:
    params = {
        "search_query": query,
        "start": str(start),
        "max_results": str(max_results),
        "sortBy": sort_by,
        "sortOrder": "descending",
    }
    return ARXIV_API_URL + "?" + urllib.parse.urlencode(params)


def _fetch_page(url: str) -> bytes | None:
    try:
        with urllib.request.urlopen(url, timeout=30) as resp:
            return resp.read()
    except urllib.error.URLError as exc:
        _log(f"Network error fetching {url}: {exc}")
        return None
    except Exception as exc:
        _log(f"Unexpected error fetching {url}: {exc}")
        return None


def _parse_feed(xml_bytes: bytes) -> list[dict]:
    """Parse Atom XML from arXiv API and return a list of paper dicts."""
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as exc:
        _log(f"Malformed XML: {exc}")
        return []

    ns = {"a": ATOM_NS, "arxiv": ARXIV_NS}
    papers: list[dict] = []

    for entry in root.findall("a:entry", ns):
        paper = _parse_entry(entry, ns)
        if paper:
            papers.append(paper)

    return papers


def _parse_entry(entry: ET.Element, ns: dict) -> dict | None:
    """Extract structured data from a single Atom <entry> element."""
    # --- ID ---
    id_el = entry.find("a:id", ns)
    if id_el is None or not id_el.text:
        return None
    raw_id = id_el.text.strip()
    # raw_id looks like: http://arxiv.org/abs/2505.07087v1
    arxiv_id_with_version = raw_id.replace("http://arxiv.org/abs/", "").strip()
    # Strip version suffix for canonical ID (e.g. "2505.07087v1" -> "2505.07087")
    arxiv_id = re.sub(r"v\d+$", "", arxiv_id_with_version)

    # --- Title ---
    title_el = entry.find("a:title", ns)
    title = _clean_text(title_el.text if title_el is not None else "")

    # --- Authors ---
    authors: list[str] = []
    for author_el in entry.findall("a:author", ns):
        name_el = author_el.find("a:name", ns)
        if name_el is not None and name_el.text:
            authors.append(name_el.text.strip())

    # --- Abstract ---
    summary_el = entry.find("a:summary", ns)
    abstract = _clean_text(summary_el.text if summary_el is not None else "")

    # --- Dates ---
    pub_el = entry.find("a:published", ns)
    upd_el = entry.find("a:updated", ns)
    published = (pub_el.text or "").strip() if pub_el is not None else ""
    updated = (upd_el.text or "").strip() if upd_el is not None else ""

    # Derive year from published date (ISO 8601: "2025-05-07T00:00:00Z")
    year = 0
    if published:
        try:
            year = int(published[:4])
        except ValueError:
            pass

    # --- Categories ---
    categories: list[str] = []
    for cat_el in entry.findall("a:category", ns):
        term = cat_el.get("term", "")
        if term:
            categories.append(term)

    # --- PDF URL ---
    pdf_url = ""
    for link_el in entry.findall("a:link", ns):
        if link_el.get("title") == "pdf":
            pdf_url = link_el.get("href", "")
            break

    # --- Optional comment ---
    comment_el = entry.find("arxiv:comment", ns)
    comment = _clean_text(comment_el.text if comment_el is not None else "")

    return {
        "arxiv_id": arxiv_id,
        "source_id": arxiv_id_with_version,
        "title": title,
        "authors": authors,
        "abstract": abstract,
        "published": published,
        "updated": updated,
        "year": year,
        "categories": categories,
        "pdf_url": pdf_url,
        "comment": comment,
    }


def _clean_text(text: str | None) -> str:
    """Collapse internal whitespace/newlines; strip leading/trailing whitespace."""
    if not text:
        return ""
    return re.sub(r"\s+", " ", text).strip()


# ---------------------------------------------------------------------------
# File writing
# ---------------------------------------------------------------------------

def _sanitize_arxiv_id(arxiv_id: str) -> str:
    """Replace `/` with `-` so the ID is safe as a filename component."""
    return arxiv_id.replace("/", "-")


def _write_paper_markdown(paper: dict, output_dir: Path, query: str) -> Path:
    """Write a single paper as a markdown file. Returns the file path."""
    sanitized_id = _sanitize_arxiv_id(paper["arxiv_id"])
    filepath = output_dir / f"{sanitized_id}.md"
    today = date.today().isoformat()

    authors_yaml = json.dumps(paper["authors"])
    categories_yaml = json.dumps(paper["categories"])

    # Escape double-quotes so values are safe inside YAML double-quoted strings.
    arxiv_id = paper["arxiv_id"]
    source_id = paper["source_id"]
    title_escaped = paper["title"].replace('"', '\\"')
    pdf_url = paper["pdf_url"]
    query_escaped = query.replace('"', '\\"')
    abstract = paper["abstract"]
    year = paper["year"]

    content = (
        f'---\n'
        f'paper_id: "{arxiv_id}"\n'
        f'source: arxiv\n'
        f'source_id: "{source_id}"\n'
        f'doi: ""\n'
        f's2_id: ""\n'
        f'title: "{title_escaped}"\n'
        f'authors: {authors_yaml}\n'
        f'year: {year}\n'
        f'venue: "arXiv preprint"\n'
        f'citation_count: 0\n'
        f'source_type: "preprint"\n'
        f'pdf_url: "{pdf_url}"\n'
        f'categories: {categories_yaml}\n'
        f'fetched_at: "{today}"\n'
        f'discovery_level: 0\n'
        f'discovery_query: "{query_escaped}"\n'
        f'discovered_via: "arxiv_search"\n'
        f'---\n'
        f'\n'
        f'## Abstract\n'
        f'\n'
        f'{abstract}\n'
        f'\n'
        f'## Notes\n'
        f'\n'
        f'[To be filled during deep reading]\n'
        f'\n'
        f'## Relevance\n'
        f'\n'
        f'[To be filled: alignment, differences, extensions]\n'
    )

    filepath.write_text(content, encoding="utf-8")
    return filepath


def _make_registry_entry(paper: dict, query: str) -> dict:
    """Build the sources.json record for a paper."""
    today = date.today().isoformat()
    return {
        "id": paper["arxiv_id"],
        "title": paper["title"],
        "authors": paper["authors"],
        "year": paper["year"],
        "venue": "arXiv preprint",
        "source_type": "preprint",
        "citation_count": 0,
        "abstract": paper["abstract"],
        "pdf_url": paper["pdf_url"],
        "arxiv_id": paper["arxiv_id"],
        "doi": "",
        "s2_id": "",
        "categories": paper["categories"],
        "tldr": "",
        "fetched_at": today,
        "discovery_level": 0,
        "discovery_query": query,
        "discovered_via": "arxiv_search",
    }


# ---------------------------------------------------------------------------
# Registry (sources.json)
# ---------------------------------------------------------------------------

def _load_registry(registry_path: Path) -> tuple[list[dict], set[str]]:
    """Load existing registry; return (entries, set_of_arxiv_ids)."""
    if not registry_path.exists():
        return [], set()
    try:
        data = json.loads(registry_path.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            _log(f"WARNING: {registry_path} does not contain a JSON array; treating as empty.")
            return [], set()
        existing_ids = {entry.get("arxiv_id", entry.get("id", "")) for entry in data}
        return data, existing_ids
    except (json.JSONDecodeError, OSError) as exc:
        _log(f"WARNING: Could not read registry {registry_path}: {exc}. Treating as empty.")
        return [], set()


def _save_registry(registry_path: Path, entries: list[dict]) -> None:
    """Atomically write the registry JSON file."""
    content = json.dumps(entries, indent=2, ensure_ascii=False)
    dir_path = registry_path.parent
    dir_path.mkdir(parents=True, exist_ok=True)
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=dir_path,
            suffix=".tmp",
            delete=False,
        ) as tmp:
            tmp.write(content)
            tmp_path = tmp.name
        os.replace(tmp_path, str(registry_path))
    except OSError as exc:
        _log(f"ERROR: Could not write registry {registry_path}: {exc}")
        # Clean up temp file if possible
        try:
            os.unlink(tmp_path)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Main fetch loop
# ---------------------------------------------------------------------------

def fetch_papers(
    query: str,
    max_results: int,
    output_dir: Path,
    registry_path: Path,
    category: str | None,
    sort_by: str,
    start_offset: int,
) -> None:
    # Ensure output directory exists
    output_dir.mkdir(parents=True, exist_ok=True)

    # Load existing registry for deduplication
    registry_entries, existing_ids = _load_registry(registry_path)
    _log(f"Registry has {len(existing_ids)} existing paper(s).")

    # Build search query with optional category prefix
    effective_query = query
    if category:
        effective_query = f"cat:{category} AND {query}"

    new_entries: list[dict] = []
    total_fetched = 0
    current_start = start_offset
    page_number = 0

    while total_fetched < max_results:
        page_number += 1
        batch_size = min(PAGE_SIZE, max_results - total_fetched)

        _log(f"Fetching page {page_number} (start={current_start}, size={batch_size})...")
        url = _build_url(effective_query, current_start, batch_size, sort_by)

        xml_bytes = _fetch_page(url)
        if xml_bytes is None:
            _log("Skipping page due to fetch error.")
            break

        papers = _parse_feed(xml_bytes)
        if not papers:
            _log("No results on this page; stopping.")
            break

        _log(f"Found {len(papers)} result(s) on page {page_number}.")

        for paper in papers:
            arxiv_id = paper["arxiv_id"]
            if arxiv_id in existing_ids:
                _log(f"  [skip] {arxiv_id} already in registry.")
                continue

            # Write markdown file
            try:
                md_path = _write_paper_markdown(paper, output_dir, query)
                _log(f"  Wrote {md_path}")
            except OSError as exc:
                _log(f"  ERROR writing markdown for {arxiv_id}: {exc}")
                continue

            # Collect registry entry
            entry = _make_registry_entry(paper, query)
            new_entries.append(entry)
            existing_ids.add(arxiv_id)

        total_fetched += len(papers)
        current_start += len(papers)

        # If we got fewer results than requested, we've exhausted the feed
        if len(papers) < batch_size:
            _log("Reached end of result set.")
            break

        # Rate limiting between paginated requests
        if total_fetched < max_results:
            _log(f"Rate limit: waiting {RATE_LIMIT_SECONDS}s before next request...")
            time.sleep(RATE_LIMIT_SECONDS)

    # Persist updated registry
    if new_entries:
        updated_registry = registry_entries + new_entries
        _save_registry(registry_path, updated_registry)
        _log(f"Registry updated: added {len(new_entries)} new paper(s) to {registry_path}")
    else:
        _log("No new papers to add to registry.")

    _log(f"Done. Total pages fetched: {page_number}.")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fetch academic papers from the arXiv REST API.",
    )
    parser.add_argument(
        "--query",
        required=True,
        help="arXiv search query (supports field prefixes: ti:, abs:, au:, cat:, all:)",
    )
    parser.add_argument(
        "--max-results",
        type=int,
        default=20,
        metavar="N",
        help="Maximum number of papers to fetch (default: 20)",
    )
    parser.add_argument(
        "--output",
        required=True,
        metavar="DIR",
        help="Directory for paper markdown files",
    )
    parser.add_argument(
        "--registry",
        required=True,
        metavar="FILE",
        help="Path to sources.json registry file",
    )
    parser.add_argument(
        "--category",
        default=None,
        metavar="CAT",
        help="Filter to arXiv category (e.g. cs.AI)",
    )
    parser.add_argument(
        "--sort-by",
        default="relevance",
        choices=sorted(VALID_SORT_BY),
        metavar="ORDER",
        help=(
            "Sort order: relevance, lastUpdatedDate, submittedDate "
            "(default: relevance)"
        ),
    )
    parser.add_argument(
        "--start",
        type=int,
        default=0,
        metavar="OFFSET",
        help="Pagination offset (default: 0)",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()

    if args.sort_by not in VALID_SORT_BY:
        _log(f"ERROR: --sort-by must be one of {sorted(VALID_SORT_BY)}")
        sys.exit(1)

    if args.max_results < 1:
        _log("ERROR: --max-results must be at least 1")
        sys.exit(1)

    if args.start < 0:
        _log("ERROR: --start must be >= 0")
        sys.exit(1)

    fetch_papers(
        query=args.query,
        max_results=args.max_results,
        output_dir=Path(args.output),
        registry_path=Path(args.registry),
        category=args.category,
        sort_by=args.sort_by,
        start_offset=args.start,
    )


if __name__ == "__main__":
    main()
