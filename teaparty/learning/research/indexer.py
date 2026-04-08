#!/usr/bin/env python3
"""SQLite FTS5 indexer and retriever for research paper corpora.

Indexes paper markdown files (with YAML frontmatter) into a full-text search
database. Supports BM25 retrieval with citation-count boost, source-type
weighting, and MMR re-ranking for diversity.

Usage:
    research_indexer.py --db <path> --init
    research_indexer.py --db <path> --source <papers_dir> --registry <sources.json>
    research_indexer.py --db <path> --query "..." [--top-k 10] [--section abstract|notes|relevance|full_text]
    research_indexer.py --db <path> --stats

Exits 0 always. Caller checks output.
"""
import argparse
import hashlib
import json
import math
import os
import re
import sqlite3
import sys
from datetime import date as date_type
from pathlib import Path


# ── Constants ────────────────────────────────────────────────────────────────

CHUNK_SIZE = 1600
CHUNK_OVERLAP = 320
FULLTEXT_CHUNK_SIZE = 2000
FULLTEXT_CHUNK_OVERLAP = 400

SOURCE_TYPE_WEIGHTS = {
    "peer-reviewed": 1.2,
    "preprint": 1.0,
    "informal": 0.8,
    "book": 1.1,
}

MMR_LAMBDA = 0.7


def _log(msg: str) -> None:
    print(f"[research_indexer] {msg}", file=sys.stderr)


# ── YAML Frontmatter Parsing ────────────────────────────────────────────────

def parse_frontmatter(text: str) -> tuple[dict, str]:
    """Parse YAML frontmatter from paper markdown.

    Returns (metadata_dict, body_text). If no frontmatter found, returns
    ({}, full_text).
    """
    text = text.lstrip()
    if not text.startswith("---"):
        return {}, text

    end = text.find("\n---", 3)
    if end == -1:
        return {}, text

    fm_text = text[3:end].strip()
    body = text[end + 4:].strip()

    metadata: dict = {}
    current_key = ""
    current_value = ""

    for line in fm_text.splitlines():
        # Handle list items (continuation of previous key)
        stripped = line.strip()
        if stripped.startswith("- ") and current_key:
            item = stripped[2:].strip().strip('"').strip("'")
            if current_key not in metadata:
                metadata[current_key] = []
            if isinstance(metadata[current_key], list):
                metadata[current_key].append(item)
            continue

        # Handle array-style values: key: ["a", "b"]
        if ":" in line:
            key, _, val = line.partition(":")
            k = key.strip()
            v = val.strip()

            if not k or not k.replace("_", "").isalnum():
                continue

            # JSON-style arrays
            if v.startswith("[") and v.endswith("]"):
                try:
                    metadata[k] = json.loads(v)
                    current_key = k
                    continue
                except json.JSONDecodeError:
                    pass

            # Quoted strings — keep as string (user explicitly quoted)
            was_quoted = len(v) >= 2 and v[0] == v[-1] and v[0] in ('"', "'")
            if was_quoted:
                v = v[1:-1]
                metadata[k] = v
            elif v.isdigit():
                metadata[k] = int(v)
            elif v.replace(".", "", 1).isdigit() and v.count(".") <= 1:
                metadata[k] = float(v)
            else:
                metadata[k] = v

            current_key = k
            current_value = v

    return metadata, body


def extract_sections(body: str) -> dict[str, str]:
    """Extract named sections from paper markdown body.

    Returns dict with keys like 'abstract', 'notes', 'relevance', 'full_text'.
    Section headers are ## Abstract, ## Notes, ## Relevance, ## Full Text.
    """
    sections: dict[str, str] = {}
    current_section = ""
    current_lines: list[str] = []

    for line in body.splitlines():
        header_match = re.match(r"^##\s+(.+)$", line)
        if header_match:
            if current_section and current_lines:
                sections[current_section] = "\n".join(current_lines).strip()
            current_section = header_match.group(1).strip().lower().replace(" ", "_")
            current_lines = []
        else:
            current_lines.append(line)

    if current_section and current_lines:
        sections[current_section] = "\n".join(current_lines).strip()

    return sections


# ── Chunking ────────────────────────────────────────────────────────────────

def chunk_text(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[tuple[str, int]]:
    """Character-based chunking. Returns list of (content, char_offset)."""
    if not text.strip():
        return []
    step = chunk_size - overlap
    if step <= 0:
        step = chunk_size
    results = []
    offset = 0
    while offset < len(text):
        chunk = text[offset:offset + chunk_size]
        if chunk.strip():
            results.append((chunk, offset))
        offset += step
    return results


def chunk_paper(metadata: dict, sections: dict[str, str]) -> list[tuple[str, str, int]]:
    """Chunk a paper into section-tagged pieces.

    Returns list of (content, section_tag, char_offset).

    Strategy:
    - Abstract is always one chunk (tagged 'abstract')
    - Notes and relevance are chunked at standard size, tagged by section
    - Full text is chunked at larger size, tagged 'full_text'
    """
    results: list[tuple[str, str, int]] = []
    offset_base = 0

    # Abstract: one chunk
    abstract = sections.get("abstract", "")
    if abstract.strip():
        results.append((abstract.strip(), "abstract", 0))

    # Notes section
    notes = sections.get("notes", "")
    if notes.strip() and notes.strip() != "[To be filled during deep reading]":
        for content, offset in chunk_text(notes, CHUNK_SIZE, CHUNK_OVERLAP):
            results.append((content, "notes", offset))

    # Relevance section
    relevance = sections.get("relevance", "")
    if relevance.strip() and relevance.strip() != "[To be filled: alignment, differences, extensions]":
        for content, offset in chunk_text(relevance, CHUNK_SIZE, CHUNK_OVERLAP):
            results.append((content, "relevance", offset))

    # Full text (from PDF extraction)
    full_text = sections.get("full_text", "")
    if full_text.strip():
        for content, offset in chunk_text(full_text, FULLTEXT_CHUNK_SIZE, FULLTEXT_CHUNK_OVERLAP):
            results.append((content, "full_text", offset))

    # TL;DR as a chunk if present in metadata
    tldr = metadata.get("tldr", "")
    if isinstance(tldr, str) and tldr.strip():
        results.append((tldr.strip(), "tldr", 0))

    return results


# ── Fingerprinting ──────────────────────────────────────────────────────────

def file_fingerprint(path: str) -> tuple[float, int, str] | None:
    """Return (mtime, size, sha256_hex) or None if file missing/empty."""
    p = Path(path)
    if not p.is_file():
        return None
    stat = p.stat()
    if stat.st_size == 0:
        return None
    content = p.read_bytes()
    sha256 = hashlib.sha256(content).hexdigest()
    return (stat.st_mtime, stat.st_size, sha256)


# ── Database ────────────────────────────────────────────────────────────────

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS papers (
    id              TEXT PRIMARY KEY,
    title           TEXT NOT NULL,
    authors         TEXT,
    year            INTEGER,
    venue           TEXT,
    source_type     TEXT,
    citation_count  INTEGER DEFAULT 0,
    abstract        TEXT,
    notes           TEXT,
    relevance_notes TEXT,
    pdf_url         TEXT,
    arxiv_id        TEXT,
    doi             TEXT,
    s2_id           TEXT,
    fetched_at      TEXT,
    level           INTEGER DEFAULT 0,
    source_file     TEXT
);

CREATE TABLE IF NOT EXISTS chunks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    paper_id    TEXT NOT NULL REFERENCES papers(id),
    content     TEXT NOT NULL,
    char_offset INTEGER NOT NULL,
    section     TEXT
);

CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
    content,
    paper_id    UNINDEXED,
    chunk_id    UNINDEXED,
    section     UNINDEXED,
    tokenize    = 'porter ascii'
);

CREATE TABLE IF NOT EXISTS file_meta (
    path    TEXT PRIMARY KEY,
    mtime   REAL NOT NULL,
    size    INTEGER NOT NULL,
    hash    TEXT
);
"""


def open_db(db_path: str) -> sqlite3.Connection:
    """Open (or create) the research database."""
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA_SQL)
    conn.commit()
    return conn


def init_db(db_path: str) -> None:
    """Initialize an empty research database."""
    conn = open_db(db_path)
    conn.close()
    _log(f"Initialized database: {db_path}")


# ── Indexing ────────────────────────────────────────────────────────────────

def needs_reindex(conn: sqlite3.Connection, paper_paths: list[str]) -> list[str]:
    """Return list of paper paths that need (re)indexing."""
    stale = []
    for path in paper_paths:
        fp = file_fingerprint(path)
        if fp is None:
            continue
        row = conn.execute(
            "SELECT mtime, size, hash FROM file_meta WHERE path = ?", (path,)
        ).fetchone()
        if row is None or (row[0] != fp[0] or row[1] != fp[1] or row[2] != fp[2]):
            stale.append(path)
    return stale


def index_paper_file(conn: sqlite3.Connection, path: str, registry: list[dict] | None = None) -> int:
    """Index a single paper markdown file. Returns chunk count."""
    text = Path(path).read_text(errors="replace")
    metadata, body = parse_frontmatter(text)
    sections = extract_sections(body)

    if not metadata.get("paper_id") and not metadata.get("title"):
        _log(f"Skipping {path}: no paper_id or title in frontmatter")
        return 0

    paper_id = str(metadata.get("paper_id", metadata.get("id", Path(path).stem)))
    title = str(metadata.get("title", ""))
    authors = metadata.get("authors", [])
    if isinstance(authors, str):
        authors = [authors]

    # Upsert paper record
    conn.execute("""
        INSERT OR REPLACE INTO papers
            (id, title, authors, year, venue, source_type, citation_count,
             abstract, notes, relevance_notes, pdf_url, arxiv_id, doi, s2_id,
             fetched_at, level, source_file)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        paper_id,
        title,
        json.dumps(authors) if authors else "[]",
        metadata.get("year"),
        str(metadata.get("venue", "")),
        str(metadata.get("source_type", "preprint")),
        int(metadata.get("citation_count", 0)),
        sections.get("abstract", ""),
        sections.get("notes", ""),
        sections.get("relevance", ""),
        str(metadata.get("pdf_url", "")),
        str(metadata.get("arxiv_id", "")),
        str(metadata.get("doi", "")),
        str(metadata.get("s2_id", "")),
        str(metadata.get("fetched_at", "")),
        int(metadata.get("discovery_level", 0)),
        path,
    ))

    # Remove existing chunks for this paper
    old_ids = [
        row[0] for row in
        conn.execute("SELECT id FROM chunks WHERE paper_id = ?", (paper_id,)).fetchall()
    ]
    if old_ids:
        placeholders = ",".join("?" * len(old_ids))
        conn.execute(f"DELETE FROM chunks_fts WHERE chunk_id IN ({placeholders})", old_ids)
        conn.execute(f"DELETE FROM chunks WHERE id IN ({placeholders})", old_ids)

    # Chunk and insert
    chunks = chunk_paper(metadata, sections)
    for content, section, offset in chunks:
        cur = conn.execute(
            "INSERT INTO chunks (paper_id, content, char_offset, section) VALUES (?, ?, ?, ?)",
            (paper_id, content, offset, section),
        )
        chunk_id = cur.lastrowid
        conn.execute(
            "INSERT INTO chunks_fts (content, paper_id, chunk_id, section) VALUES (?, ?, ?, ?)",
            (content, paper_id, str(chunk_id), section),
        )

    # Update file fingerprint
    fp = file_fingerprint(path)
    if fp:
        conn.execute(
            "INSERT OR REPLACE INTO file_meta (path, mtime, size, hash) VALUES (?, ?, ?, ?)",
            (path, fp[0], fp[1], fp[2]),
        )

    conn.commit()
    return len(chunks)


def index_directory(conn: sqlite3.Connection, papers_dir: str, registry_path: str = "") -> int:
    """Index all paper .md files in a directory. Returns total chunk count."""
    papers_path = Path(papers_dir)
    if not papers_path.is_dir():
        _log(f"Papers directory not found: {papers_dir}")
        return 0

    # Load registry for cross-reference
    registry = []
    if registry_path and Path(registry_path).is_file():
        try:
            registry = json.loads(Path(registry_path).read_text())
        except (json.JSONDecodeError, OSError):
            pass

    paper_files = sorted(papers_path.glob("*.md"))
    if not paper_files:
        _log(f"No .md files found in {papers_dir}")
        return 0

    # Check which files need reindexing
    stale = needs_reindex(conn, [str(f) for f in paper_files])
    if not stale:
        _log("All papers up to date, no reindexing needed.")
        return 0

    total_chunks = 0
    for path in stale:
        count = index_paper_file(conn, path, registry)
        if count > 0:
            _log(f"Indexed {Path(path).name} -> {count} chunks")
        total_chunks += count

    _log(f"Indexed {len(stale)} papers, {total_chunks} total chunks")
    return total_chunks


# ── Retrieval ───────────────────────────────────────────────────────────────

def retrieve_bm25(
    conn: sqlite3.Connection,
    query: str,
    top_k: int = 10,
    section_filter: str = "",
) -> list[dict]:
    """FTS5 BM25 full-text search.

    Returns list of dicts with keys: paper_id, content, section, rank, citation_count, source_type.
    """
    if not query.strip():
        return []

    terms = [t.strip() for t in query.split() if t.strip()]
    if not terms:
        return []

    # Build FTS5 match expression
    match_expr = " OR ".join(terms)

    try:
        if section_filter:
            rows = conn.execute("""
                SELECT cf.paper_id, cf.content, cf.section, cf.rank,
                       COALESCE(p.citation_count, 0), COALESCE(p.source_type, 'preprint')
                FROM chunks_fts cf
                LEFT JOIN papers p ON cf.paper_id = p.id
                WHERE chunks_fts MATCH ? AND cf.section = ?
                ORDER BY cf.rank
                LIMIT ?
            """, (match_expr, section_filter, top_k * 4)).fetchall()
        else:
            rows = conn.execute("""
                SELECT cf.paper_id, cf.content, cf.section, cf.rank,
                       COALESCE(p.citation_count, 0), COALESCE(p.source_type, 'preprint')
                FROM chunks_fts cf
                LEFT JOIN papers p ON cf.paper_id = p.id
                WHERE chunks_fts MATCH ?
                ORDER BY cf.rank
                LIMIT ?
            """, (match_expr, top_k * 4)).fetchall()
    except sqlite3.OperationalError:
        # FTS syntax error — try first term only
        try:
            rows = conn.execute("""
                SELECT cf.paper_id, cf.content, cf.section, cf.rank,
                       COALESCE(p.citation_count, 0), COALESCE(p.source_type, 'preprint')
                FROM chunks_fts cf
                LEFT JOIN papers p ON cf.paper_id = p.id
                WHERE chunks_fts MATCH ?
                ORDER BY cf.rank
                LIMIT ?
            """, (terms[0], top_k * 4)).fetchall()
        except sqlite3.OperationalError:
            return []

    results = []
    for paper_id, content, section, rank, citation_count, source_type in rows:
        results.append({
            "paper_id": paper_id,
            "content": content,
            "section": section or "",
            "rank": rank,
            "citation_count": citation_count,
            "source_type": source_type or "preprint",
        })

    return results


def score_results(results: list[dict]) -> list[dict]:
    """Apply citation-count boost and source-type weighting to BM25 results.

    Scoring: normalized_bm25 * log2(citation_count + 2) * source_type_weight
    """
    if not results:
        return results

    # Normalize BM25 ranks to [0, 1] (rank is negative, more-negative = better)
    ranks = [r["rank"] for r in results]
    min_rank, max_rank = min(ranks), max(ranks)
    rank_range = max_rank - min_rank if max_rank != min_rank else 1.0

    for r in results:
        bm25_norm = (max_rank - r["rank"]) / rank_range

        # Citation-count boost: log2(count + 2) — gentle boost for cited papers
        cite_boost = math.log2(r["citation_count"] + 2)

        # Source-type weight
        type_weight = SOURCE_TYPE_WEIGHTS.get(r["source_type"], 1.0)

        r["score"] = bm25_norm * cite_boost * type_weight

    results.sort(key=lambda r: r["score"], reverse=True)
    return results


def mmr_rerank(results: list[dict], top_k: int = 10) -> list[dict]:
    """Maximal Marginal Relevance re-ranking using Jaccard similarity."""
    if len(results) <= 1:
        return results[:top_k]

    def tokenize(text: str) -> set:
        return set(re.findall(r'[a-z0-9_]+', text.lower()))

    def jaccard(a: set, b: set) -> float:
        union = a | b
        if not union:
            return 0.0
        return len(a & b) / len(union)

    scores = [r.get("score", 0.0) for r in results]
    max_s = max(scores) if scores else 1.0
    min_s = min(scores) if scores else 0.0
    rng = max_s - min_s if max_s != min_s else 1.0
    normalized = [(s - min_s) / rng for s in scores]

    tokens = [tokenize(r["content"]) for r in results]
    selected: list[dict] = []
    selected_idx: list[int] = []
    remaining = list(range(len(results)))

    while remaining and len(selected) < top_k:
        if not selected_idx:
            best = max(remaining, key=lambda i: normalized[i])
        else:
            def mmr_score(i):
                rel = normalized[i]
                max_sim = max(jaccard(tokens[i], tokens[j]) for j in selected_idx)
                return MMR_LAMBDA * rel - (1 - MMR_LAMBDA) * max_sim
            best = max(remaining, key=mmr_score)
        selected.append(results[best])
        selected_idx.append(best)
        remaining.remove(best)

    return selected


def retrieve(
    conn: sqlite3.Connection,
    query: str,
    top_k: int = 10,
    section_filter: str = "",
) -> list[dict]:
    """Full retrieval pipeline: BM25 → citation boost → source-type weight → MMR."""
    results = retrieve_bm25(conn, query, top_k=top_k, section_filter=section_filter)
    if not results:
        return []

    results = score_results(results)
    results = mmr_rerank(results, top_k=top_k)
    return results


# ── Formatting ──────────────────────────────────────────────────────────────

def format_results(results: list[dict], conn: sqlite3.Connection) -> str:
    """Format retrieval results as markdown."""
    if not results:
        return ""

    parts = ["## Research Index Results\n"]

    # Group by paper for cleaner output
    seen_papers: dict[str, list[dict]] = {}
    for r in results:
        pid = r["paper_id"]
        if pid not in seen_papers:
            seen_papers[pid] = []
        seen_papers[pid].append(r)

    for paper_id, chunks in seen_papers.items():
        # Get paper metadata
        row = conn.execute(
            "SELECT title, authors, year, venue, citation_count, source_type FROM papers WHERE id = ?",
            (paper_id,),
        ).fetchone()

        if row:
            title, authors_json, year, venue, cite_count, source_type = row
            authors = ""
            try:
                author_list = json.loads(authors_json) if authors_json else []
                if author_list:
                    authors = ", ".join(author_list[:3])
                    if len(author_list) > 3:
                        authors += " et al."
            except (json.JSONDecodeError, TypeError):
                pass

            header = f"### {title}"
            if authors and year:
                header += f" ({authors}, {year})"
            elif year:
                header += f" ({year})"
            parts.append(header)

            if venue:
                parts.append(f"*{venue}* | Citations: {cite_count} | Type: {source_type}")
            parts.append("")
        else:
            parts.append(f"### {paper_id}")
            parts.append("")

        for chunk in chunks:
            section = chunk.get("section", "")
            score = chunk.get("score", 0.0)
            if section:
                parts.append(f"**[{section}]** (score: {score:.3f})")
            parts.append(chunk["content"].strip())
            parts.append("")

    return "\n".join(parts)


# ── Stats ───────────────────────────────────────────────────────────────────

def print_stats(conn: sqlite3.Connection) -> None:
    """Print corpus statistics."""
    total_papers = conn.execute("SELECT COUNT(*) FROM papers").fetchone()[0]
    total_chunks = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]

    print(f"\n=== Research Corpus Statistics ===\n")
    print(f"Total papers: {total_papers}")
    print(f"Total chunks: {total_chunks}")

    if total_papers == 0:
        return

    # By discovery level
    print(f"\nBy discovery level:")
    for row in conn.execute(
        "SELECT level, COUNT(*) FROM papers GROUP BY level ORDER BY level"
    ).fetchall():
        print(f"  Level {row[0]}: {row[1]} papers")

    # By source type
    print(f"\nBy source type:")
    for row in conn.execute(
        "SELECT source_type, COUNT(*) FROM papers GROUP BY source_type ORDER BY COUNT(*) DESC"
    ).fetchall():
        print(f"  {row[0] or 'unknown'}: {row[1]} papers")

    # By venue (top 10)
    print(f"\nTop venues:")
    for row in conn.execute(
        "SELECT venue, COUNT(*) FROM papers WHERE venue != '' GROUP BY venue ORDER BY COUNT(*) DESC LIMIT 10"
    ).fetchall():
        print(f"  {row[0]}: {row[1]} papers")

    # Chunks by section
    print(f"\nChunks by section:")
    for row in conn.execute(
        "SELECT section, COUNT(*) FROM chunks GROUP BY section ORDER BY COUNT(*) DESC"
    ).fetchall():
        print(f"  {row[0] or 'untagged'}: {row[1]} chunks")

    # Citation count distribution
    print(f"\nCitation count distribution:")
    for label, lo, hi in [
        ("0", 0, 0), ("1-10", 1, 10), ("11-50", 11, 50),
        ("51-200", 51, 200), ("201+", 201, 999999),
    ]:
        count = conn.execute(
            "SELECT COUNT(*) FROM papers WHERE citation_count BETWEEN ? AND ?",
            (lo, hi),
        ).fetchone()[0]
        if count > 0:
            print(f"  {label} citations: {count} papers")

    print()


# ── Main ────────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(description="Research paper indexer and retriever")
    parser.add_argument("--db", required=True, help="Path to SQLite database file")
    parser.add_argument("--init", action="store_true", help="Initialize empty database")
    parser.add_argument("--source", default="", help="Papers directory to index")
    parser.add_argument("--registry", default="", help="Path to sources.json")
    parser.add_argument("--query", default="", help="Search query")
    parser.add_argument("--top-k", type=int, default=10, dest="top_k", help="Results to return")
    parser.add_argument("--section", default="", help="Filter by section: abstract, notes, relevance, full_text")
    parser.add_argument("--stats", action="store_true", help="Print corpus statistics")
    parser.add_argument("--output", default="", help="Write results to file (default: stdout)")
    args = parser.parse_args()

    if args.init:
        os.makedirs(os.path.dirname(args.db) or ".", exist_ok=True)
        init_db(args.db)
        return 0

    try:
        conn = open_db(args.db)
    except Exception as e:
        _log(f"Failed to open database: {e}")
        return 0

    # Index mode
    if args.source:
        count = index_directory(conn, args.source, args.registry)
        _log(f"Indexing complete: {count} chunks")

    # Stats mode
    if args.stats:
        print_stats(conn)

    # Query mode
    if args.query:
        results = retrieve(
            conn, args.query,
            top_k=args.top_k,
            section_filter=args.section,
        )

        if results:
            formatted = format_results(results, conn)
            if args.output:
                Path(args.output).write_text(formatted)
                _log(f"Wrote {len(results)} results to {args.output}")
            else:
                print(formatted)
        else:
            _log("No results found.")

    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
