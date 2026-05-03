#!/usr/bin/env python3
"""Fetch academic papers from the Semantic Scholar Graph API.

Subcommands:
    search      -- keyword/phrase search
    references  -- papers cited by a given paper
    citations   -- papers that cite a given paper

Usage:
    python fetch_semantic_scholar.py search --query "agentic AI" \\
        --output papers/ --registry sources.json [options]

    python fetch_semantic_scholar.py references --paper-id ARXIV:2505.07087 \\
        --output papers/ --registry sources.json [options]

    python fetch_semantic_scholar.py citations --paper-id 10.1145/3442188.3445922 \\
        --output papers/ --registry sources.json [options]

Authentication:
    Set S2_API_KEY environment variable for authenticated access
    (higher rate limits).  Unauthenticated: ~100 req / 5 min.
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
from datetime import date
from pathlib import Path


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

S2_BASE_URL = "https://api.semanticscholar.org/graph/v1"
RATE_LIMIT_SECONDS = 3          # conservative: 100 req/5 min unauthenticated
MAX_SEARCH_LIMIT = 100          # S2 hard cap per page for search
MAX_GRAPH_LIMIT = 1000          # S2 hard cap per page for references/citations

# Backoff schedule (seconds) for HTTP 429 responses
BACKOFF_SCHEDULE = [5, 10, 20]

DEFAULT_FIELDS = (
    "title,abstract,year,authors,citationCount,referenceCount,"
    "venue,openAccessPdf,externalIds,tldr,s2FieldsOfStudy"
)


# ---------------------------------------------------------------------------
# Progress logging
# ---------------------------------------------------------------------------

def _log(msg: str) -> None:
    print(f"[fetch_s2] {msg}", file=sys.stderr)


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

def _api_key_header() -> dict[str, str]:
    key = os.environ.get("S2_API_KEY", "").strip()
    if key:
        return {"x-api-key": key}
    return {}


def _get_json(url: str) -> dict | None:
    """Fetch a URL, return parsed JSON, or None on error.

    Implements exponential backoff on HTTP 429.
    """
    headers = _api_key_header()
    req = urllib.request.Request(url, headers=headers)

    for attempt, backoff in enumerate([0] + BACKOFF_SCHEDULE):
        if backoff:
            _log(f"Rate-limited (429). Waiting {backoff}s before retry {attempt}...")
            time.sleep(backoff)
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code == 429:
                if attempt < len(BACKOFF_SCHEDULE):
                    continue  # will sleep on next iteration
                _log(f"ERROR: Still rate-limited after all retries for {url}.")
                return None
            _log(f"HTTP {exc.code} fetching {url}: {exc.reason}")
            return None
        except urllib.error.URLError as exc:
            _log(f"Network error fetching {url}: {exc}")
            return None
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            _log(f"Parse error for {url}: {exc}")
            return None
        except Exception as exc:
            _log(f"Unexpected error fetching {url}: {exc}")
            return None

    return None


# ---------------------------------------------------------------------------
# Paper ID normalization
# ---------------------------------------------------------------------------

def _normalize_paper_id(raw: str) -> str:
    """Normalise a user-supplied paper ID to the format S2 API accepts.

    Handles:
      - Plain S2 corpus integer ID  ("12345678")
      - Already-prefixed forms      ("ARXIV:2505.07087", "DOI:10.1145/...")
      - Bare arXiv IDs              ("2505.07087", "2505.07087v2")
      - DOIs                        ("10.1145/3442188.3445922")
    """
    raw = raw.strip()
    # Already has an explicit prefix
    if raw.upper().startswith("ARXIV:") or raw.upper().startswith("DOI:"):
        return raw

    # Pure integer → S2 corpus ID
    if re.fullmatch(r"\d+", raw):
        return raw

    # arXiv pattern: NNNN.NNNNN(vN)?
    if re.fullmatch(r"\d{4}\.\d{4,5}(?:v\d+)?", raw):
        return f"ARXIV:{raw}"

    # DOI pattern starts with "10."
    if raw.startswith("10."):
        return f"DOI:{raw}"

    # Fallback: pass through and let the API reject it
    return raw


# ---------------------------------------------------------------------------
# S2 API calls
# ---------------------------------------------------------------------------

def _search_papers(
    query: str,
    fields: str,
    limit: int,
    min_citations: int,
    year_range: str | None,
) -> list[dict]:
    """Call the S2 paper search endpoint; handle pagination."""
    results: list[dict] = []
    offset = 0

    while len(results) < limit:
        batch = min(MAX_SEARCH_LIMIT, limit - len(results))
        params: dict[str, str] = {
            "query": query,
            "fields": fields,
            "limit": str(batch),
            "offset": str(offset),
        }
        if min_citations:
            params["minCitationCount"] = str(min_citations)
        if year_range:
            params["publicationDateOrYear"] = year_range

        url = f"{S2_BASE_URL}/paper/search?" + urllib.parse.urlencode(params)
        _log(f"GET {url}")
        data = _get_json(url)
        if data is None:
            break

        batch_papers = data.get("data") or []
        if not batch_papers:
            break

        results.extend(batch_papers)
        offset += len(batch_papers)
        total = data.get("total", 0)

        if offset >= total or len(batch_papers) < batch:
            break

        if len(results) < limit:
            _log(f"Rate limit: waiting {RATE_LIMIT_SECONDS}s...")
            time.sleep(RATE_LIMIT_SECONDS)

    return results[:limit]


def _fetch_references(paper_id: str, fields: str, limit: int) -> list[dict]:
    """Fetch papers cited by `paper_id`."""
    results: list[dict] = []
    offset = 0

    while len(results) < limit:
        batch = min(MAX_GRAPH_LIMIT, limit - len(results))
        params = {
            "fields": fields,
            "limit": str(batch),
            "offset": str(offset),
        }
        url = (
            f"{S2_BASE_URL}/paper/{urllib.parse.quote(paper_id, safe='')}/references?"
            + urllib.parse.urlencode(params)
        )
        _log(f"GET {url}")
        data = _get_json(url)
        if data is None:
            break

        batch_items = data.get("data") or []
        if not batch_items:
            break

        # References are wrapped: [{"citedPaper": {...}}, ...]
        for item in batch_items:
            paper = item.get("citedPaper")
            if paper:
                results.append(paper)

        offset += len(batch_items)

        if len(batch_items) < batch:
            break

        if len(results) < limit:
            _log(f"Rate limit: waiting {RATE_LIMIT_SECONDS}s...")
            time.sleep(RATE_LIMIT_SECONDS)

    return results[:limit]


def _fetch_citations(paper_id: str, fields: str, limit: int) -> list[dict]:
    """Fetch papers that cite `paper_id`."""
    results: list[dict] = []
    offset = 0

    while len(results) < limit:
        batch = min(MAX_GRAPH_LIMIT, limit - len(results))
        params = {
            "fields": fields,
            "limit": str(batch),
            "offset": str(offset),
        }
        url = (
            f"{S2_BASE_URL}/paper/{urllib.parse.quote(paper_id, safe='')}/citations?"
            + urllib.parse.urlencode(params)
        )
        _log(f"GET {url}")
        data = _get_json(url)
        if data is None:
            break

        batch_items = data.get("data") or []
        if not batch_items:
            break

        # Citations are wrapped: [{"citingPaper": {...}}, ...]
        for item in batch_items:
            paper = item.get("citingPaper")
            if paper:
                results.append(paper)

        offset += len(batch_items)

        if len(batch_items) < batch:
            break

        if len(results) < limit:
            _log(f"Rate limit: waiting {RATE_LIMIT_SECONDS}s...")
            time.sleep(RATE_LIMIT_SECONDS)

    return results[:limit]


# ---------------------------------------------------------------------------
# Paper object parsing
# ---------------------------------------------------------------------------

def _clean_text(text: str | None) -> str:
    """Collapse internal whitespace; strip leading/trailing whitespace."""
    if not text:
        return ""
    return re.sub(r"\s+", " ", text).strip()


def _extract_paper(raw: dict) -> dict:
    """Normalise a raw S2 paper object into a flat dict."""
    external_ids = raw.get("externalIds") or {}
    arxiv_id = _clean_text(external_ids.get("ArXiv") or "")
    doi = _clean_text(external_ids.get("DOI") or "")
    s2_id = _clean_text(raw.get("paperId") or "")

    title = _clean_text(raw.get("title") or "")
    abstract = _clean_text(raw.get("abstract") or "")
    year = raw.get("year") or 0
    citation_count = raw.get("citationCount") or 0
    venue = _clean_text(raw.get("venue") or "")

    open_access = raw.get("openAccessPdf") or {}
    pdf_url = _clean_text(open_access.get("url") or "")

    # s2FieldsOfStudy: [{"category": "...", "source": "..."}, ...]
    s2_fields = raw.get("s2FieldsOfStudy") or []
    categories: list[str] = []
    seen_categories: set[str] = set()
    for f in s2_fields:
        cat = _clean_text(f.get("category") or "")
        if cat and cat not in seen_categories:
            categories.append(cat)
            seen_categories.add(cat)

    # tldr: {"model": "...", "text": "..."}
    tldr_obj = raw.get("tldr") or {}
    tldr = _clean_text(tldr_obj.get("text") or "")

    # authors: [{"name": "..."}, ...]
    authors_raw = raw.get("authors") or []
    authors: list[str] = [
        _clean_text(a.get("name") or "")
        for a in authors_raw
        if a.get("name")
    ]

    # Canonical ID: prefer arXiv → DOI → S2
    if arxiv_id:
        canonical_id = arxiv_id
    elif doi:
        canonical_id = doi
    else:
        canonical_id = s2_id

    # Source type: preprint if no venue or venue mentions arXiv
    venue_lower = venue.lower()
    if not venue or "arxiv" in venue_lower:
        source_type = "preprint"
    else:
        source_type = "peer-reviewed"

    return {
        "canonical_id": canonical_id,
        "s2_id": s2_id,
        "arxiv_id": arxiv_id,
        "doi": doi,
        "title": title,
        "authors": authors,
        "abstract": abstract,
        "year": int(year) if year else 0,
        "venue": venue,
        "citation_count": int(citation_count),
        "source_type": source_type,
        "pdf_url": pdf_url,
        "categories": categories,
        "tldr": tldr,
    }


# ---------------------------------------------------------------------------
# Filtering
# ---------------------------------------------------------------------------

def _apply_filters(
    papers: list[dict],
    min_citations: int,
    year_range: str | None,
) -> list[dict]:
    """Post-filter papers; S2 search accepts these server-side too, but
    references/citations endpoints do not, so we filter client-side."""
    filtered: list[dict] = []
    for p in papers:
        if p["citation_count"] < min_citations:
            continue
        if year_range and p["year"]:
            parts = year_range.split("-")
            try:
                year_min = int(parts[0])
                year_max = int(parts[1]) if len(parts) > 1 else 9999
            except (ValueError, IndexError):
                year_min, year_max = 0, 9999
            if not (year_min <= p["year"] <= year_max):
                continue
        filtered.append(p)
    return filtered


# ---------------------------------------------------------------------------
# Registry (sources.json)
# ---------------------------------------------------------------------------

def _load_registry(registry_path: Path) -> list[dict]:
    """Load existing registry list, or return empty list."""
    if not registry_path.exists():
        return []
    try:
        data = json.loads(registry_path.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            _log(
                f"WARNING: {registry_path} is not a JSON array; "
                "treating as empty."
            )
            return []
        return data
    except (json.JSONDecodeError, OSError) as exc:
        _log(f"WARNING: Could not read registry {registry_path}: {exc}. Treating as empty.")
        return []


def _save_registry(registry_path: Path, entries: list[dict]) -> None:
    """Atomically write the registry JSON file."""
    content = json.dumps(entries, indent=2, ensure_ascii=False)
    dir_path = registry_path.parent
    dir_path.mkdir(parents=True, exist_ok=True)
    tmp_path: str | None = None
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
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass


def _build_dedup_index(entries: list[dict]) -> dict[str, int]:
    """Return mapping of doi/arxiv_id/s2_id → list index for quick lookup."""
    index: dict[str, int] = {}
    for i, entry in enumerate(entries):
        for key in ("doi", "arxiv_id", "s2_id"):
            val = entry.get(key, "").strip()
            if val:
                index[val] = i
    return index


def _merge_into_registry(
    registry: list[dict],
    index: dict[str, int],
    new_entry: dict,
) -> bool:
    """Attempt to merge new_entry into an existing registry record.

    Returns True if a match was found (and potentially updated).
    Returns False if no match; caller should append.

    Update strategy: fill empty fields only; never overwrite non-empty.
    """
    match_idx: int | None = None
    for key in ("doi", "arxiv_id", "s2_id"):
        val = new_entry.get(key, "").strip()
        if val and val in index:
            match_idx = index[val]
            break

    if match_idx is None:
        return False

    existing = registry[match_idx]
    changed = False
    for field in (
        "s2_id", "arxiv_id", "doi", "title", "authors", "year",
        "venue", "source_type", "citation_count", "abstract",
        "pdf_url", "categories", "tldr",
    ):
        current = existing.get(field)
        incoming = new_entry.get(field)
        # Consider a field empty if it's falsy (None, "", 0, [])
        if not current and incoming:
            existing[field] = incoming
            changed = True

    if changed:
        _log(f"  [merge] Updated existing entry for {existing.get('id', '')}")

    # Always update index with any new IDs we just learned
    for key in ("doi", "arxiv_id", "s2_id"):
        val = existing.get(key, "").strip()
        if val and val not in index:
            index[val] = match_idx

    return True


# ---------------------------------------------------------------------------
# Markdown + registry entry construction
# ---------------------------------------------------------------------------

def _make_registry_entry(
    paper: dict,
    discovery_level: int,
    discovery_query: str,
    discovered_via: str,
) -> dict:
    today = date.today().isoformat()
    return {
        "id": paper["canonical_id"],
        "title": paper["title"],
        "authors": paper["authors"],
        "year": paper["year"],
        "venue": paper["venue"],
        "source_type": paper["source_type"],
        "citation_count": paper["citation_count"],
        "abstract": paper["abstract"],
        "pdf_url": paper["pdf_url"],
        "arxiv_id": paper["arxiv_id"],
        "doi": paper["doi"],
        "s2_id": paper["s2_id"],
        "categories": paper["categories"],
        "tldr": paper["tldr"],
        "fetched_at": today,
        "discovery_level": discovery_level,
        "discovery_query": discovery_query,
        "discovered_via": discovered_via,
    }


def _write_paper_markdown(
    paper: dict,
    output_dir: Path,
    discovery_level: int,
    discovery_query: str,
    discovered_via: str,
) -> Path:
    """Write a single paper as a markdown file. Returns the file path."""
    # Safe filename: canonical_id may contain slashes (DOIs) or colons
    safe_id = re.sub(r"[^\w.\-]", "-", paper["canonical_id"])
    filepath = output_dir / f"{safe_id}.md"
    today = date.today().isoformat()

    authors_yaml = json.dumps(paper["authors"])
    categories_yaml = json.dumps(paper["categories"])

    # Escape double-quotes for YAML double-quoted strings
    def _esc(s: str) -> str:
        return s.replace('"', '\\"')

    content = (
        f'---\n'
        f'paper_id: "{_esc(paper["canonical_id"])}"\n'
        f'source: semantic_scholar\n'
        f'source_id: "{_esc(paper["s2_id"])}"\n'
        f'doi: "{_esc(paper["doi"])}"\n'
        f's2_id: "{_esc(paper["s2_id"])}"\n'
        f'arxiv_id: "{_esc(paper["arxiv_id"])}"\n'
        f'title: "{_esc(paper["title"])}"\n'
        f'authors: {authors_yaml}\n'
        f'year: {paper["year"]}\n'
        f'venue: "{_esc(paper["venue"])}"\n'
        f'citation_count: {paper["citation_count"]}\n'
        f'source_type: "{paper["source_type"]}"\n'
        f'pdf_url: "{_esc(paper["pdf_url"])}"\n'
        f'categories: {categories_yaml}\n'
        f'fetched_at: "{today}"\n'
        f'discovery_level: {discovery_level}\n'
        f'discovery_query: "{_esc(discovery_query)}"\n'
        f'discovered_via: "{discovered_via}"\n'
        f'---\n'
        f'\n'
        f'## Abstract\n'
        f'\n'
        f'{paper["abstract"] or "[No abstract available]"}\n'
        f'\n'
    )

    if paper["tldr"]:
        content += (
            f'## TL;DR\n'
            f'\n'
            f'{paper["tldr"]}\n'
            f'\n'
        )

    content += (
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


# ---------------------------------------------------------------------------
# Core processing loop
# ---------------------------------------------------------------------------

def _process_papers(
    raw_papers: list[dict],
    output_dir: Path,
    registry_path: Path,
    min_citations: int,
    year_range: str | None,
    discovery_level: int,
    discovery_query: str,
    discovered_via: str,
) -> None:
    """Filter, dedup, write markdown, and update registry for a batch of raw S2 papers."""
    output_dir.mkdir(parents=True, exist_ok=True)

    registry = _load_registry(registry_path)
    index = _build_dedup_index(registry)
    _log(f"Registry has {len(registry)} existing paper(s).")

    papers = [_extract_paper(r) for r in raw_papers]
    papers = _apply_filters(papers, min_citations, year_range)
    _log(f"After filters: {len(papers)} paper(s) to process.")

    new_count = 0
    updated_count = 0

    for paper in papers:
        if not paper["canonical_id"]:
            _log("  [skip] Paper has no usable ID; skipping.")
            continue

        entry = _make_registry_entry(paper, discovery_level, discovery_query, discovered_via)

        # Check for duplicate
        is_existing = _merge_into_registry(registry, index, entry)

        if is_existing:
            updated_count += 1
            # Still write / overwrite markdown to reflect any merged data
        else:
            registry.append(entry)
            # Add new IDs to index
            for key in ("doi", "arxiv_id", "s2_id"):
                val = entry.get(key, "").strip()
                if val:
                    index[val] = len(registry) - 1
            new_count += 1

        try:
            md_path = _write_paper_markdown(
                paper, output_dir, discovery_level, discovery_query, discovered_via
            )
            _log(f"  Wrote {md_path}")
        except OSError as exc:
            _log(f"  ERROR writing markdown for {paper['canonical_id']}: {exc}")

    _save_registry(registry_path, registry)
    _log(
        f"Registry updated: {new_count} new, {updated_count} merged/updated "
        f"-> {registry_path}"
    )


# ---------------------------------------------------------------------------
# Subcommand handlers
# ---------------------------------------------------------------------------

def cmd_search(args: argparse.Namespace) -> None:
    _log(f'Searching for "{args.query}"...')
    raw = _search_papers(
        query=args.query,
        fields=args.fields,
        limit=args.limit,
        min_citations=args.min_citations,
        year_range=args.year_range,
    )
    _log(f"Found {len(raw)} result(s) from API.")
    _process_papers(
        raw_papers=raw,
        output_dir=Path(args.output),
        registry_path=Path(args.registry),
        min_citations=args.min_citations,
        year_range=args.year_range,
        discovery_level=args.discovery_level,
        discovery_query=args.query,
        discovered_via="s2_search",
    )


def cmd_references(args: argparse.Namespace) -> None:
    paper_id = _normalize_paper_id(args.paper_id)
    _log(f"Fetching references for {paper_id}...")
    raw = _fetch_references(paper_id=paper_id, fields=args.fields, limit=args.limit)
    _log(f"Found {len(raw)} reference(s) from API.")
    _process_papers(
        raw_papers=raw,
        output_dir=Path(args.output),
        registry_path=Path(args.registry),
        min_citations=args.min_citations,
        year_range=args.year_range,
        discovery_level=args.discovery_level,
        discovery_query=args.paper_id,
        discovered_via="s2_references",
    )


def cmd_citations(args: argparse.Namespace) -> None:
    paper_id = _normalize_paper_id(args.paper_id)
    _log(f"Fetching citations for {paper_id}...")
    raw = _fetch_citations(paper_id=paper_id, fields=args.fields, limit=args.limit)
    _log(f"Found {len(raw)} citing paper(s) from API.")
    _process_papers(
        raw_papers=raw,
        output_dir=Path(args.output),
        registry_path=Path(args.registry),
        min_citations=args.min_citations,
        year_range=args.year_range,
        discovery_level=args.discovery_level,
        discovery_query=args.paper_id,
        discovered_via="s2_citations",
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _add_shared_args(parser: argparse.ArgumentParser) -> None:
    """Add flags that are common to all subcommands."""
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
        "--fields",
        default=DEFAULT_FIELDS,
        metavar="FIELDS",
        help=(
            "Comma-separated Semantic Scholar fields to request "
            f"(default: {DEFAULT_FIELDS})"
        ),
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=50,
        metavar="N",
        help="Maximum number of results to fetch (default: 50)",
    )
    parser.add_argument(
        "--min-citations",
        type=int,
        default=0,
        dest="min_citations",
        metavar="N",
        help="Minimum citation count filter (default: 0)",
    )
    parser.add_argument(
        "--year-range",
        default=None,
        dest="year_range",
        metavar="YYYY-YYYY",
        help="Year range filter, e.g. 2023-2026 (default: no filter)",
    )
    parser.add_argument(
        "--discovery-level",
        type=int,
        default=0,
        dest="discovery_level",
        metavar="N",
        help="Discovery level tag (0=broad, 1-3=expansion; default: 0)",
    )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Fetch academic papers from the Semantic Scholar Graph API. "
            "Set S2_API_KEY env var for authenticated (higher rate limit) access."
        ),
    )
    subparsers = parser.add_subparsers(dest="subcommand", required=True)

    # --- search ---
    search_parser = subparsers.add_parser(
        "search",
        help="Search for papers by keyword/phrase",
    )
    search_parser.add_argument(
        "--query",
        required=True,
        metavar="TEXT",
        help="Search query string",
    )
    _add_shared_args(search_parser)

    # --- references ---
    refs_parser = subparsers.add_parser(
        "references",
        help="Fetch papers cited by a given paper (its reference list)",
    )
    refs_parser.add_argument(
        "--paper-id",
        required=True,
        dest="paper_id",
        metavar="ID",
        help=(
            "Paper ID: S2 corpus integer, DOI (10.xxxx/...), "
            "or arXiv ID (ARXIV:2505.07087 or bare 2505.07087)"
        ),
    )
    _add_shared_args(refs_parser)

    # --- citations ---
    cites_parser = subparsers.add_parser(
        "citations",
        help="Fetch papers that cite a given paper",
    )
    cites_parser.add_argument(
        "--paper-id",
        required=True,
        dest="paper_id",
        metavar="ID",
        help=(
            "Paper ID: S2 corpus integer, DOI (10.xxxx/...), "
            "or arXiv ID (ARXIV:2505.07087 or bare 2505.07087)"
        ),
    )
    _add_shared_args(cites_parser)

    return parser.parse_args()


def main() -> None:
    args = _parse_args()

    if args.limit < 1:
        _log("ERROR: --limit must be at least 1")
        sys.exit(1)

    if args.min_citations < 0:
        _log("ERROR: --min-citations must be >= 0")
        sys.exit(1)

    if args.discovery_level < 0:
        _log("ERROR: --discovery-level must be >= 0")
        sys.exit(1)

    dispatch = {
        "search": cmd_search,
        "references": cmd_references,
        "citations": cmd_citations,
    }
    dispatch[args.subcommand](args)


if __name__ == "__main__":
    main()
