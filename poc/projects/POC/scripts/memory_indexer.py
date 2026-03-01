#!/usr/bin/env python3
"""SQLite-backed memory indexer and retriever for the POC learning subsystem.

Chunks OBSERVATIONS.md, ESCALATION.md, and MEMORY.md into a SQLite FTS5 index.
At session start, retrieves relevant chunks for the current task description.

Usage:
    memory_indexer.py \
        --db <path/to/.memory.db> \
        --source <md_file> [--source <md_file> ...] \
        --task "<task description>" \
        --output <context_file_path> \
        [--top-k 5]

Exits 0 always. Caller checks whether --output is non-empty.
"""
import argparse
import os
import sqlite3
import subprocess
import sys
from pathlib import Path


# ── Chunking ─────────────────────────────────────────────────────────────────

def chunk_text(text: str, chunk_size: int = 1600, overlap: int = 320) -> list[tuple[str, int]]:
    """Character-based, structure-blind chunking.

    Returns list of (content, char_offset) pairs.
    """
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


# ── Fingerprinting ────────────────────────────────────────────────────────────

def file_fingerprint(path: str) -> tuple[float, int] | None:
    """Return (mtime, size) or None if file missing/empty."""
    p = Path(path)
    if not p.is_file():
        return None
    stat = p.stat()
    if stat.st_size == 0:
        return None
    return (stat.st_mtime, stat.st_size)


# ── Database setup ────────────────────────────────────────────────────────────

def open_db(db_path: str) -> sqlite3.Connection:
    """Open (or create) the SQLite database with the required schema."""
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS file_meta (
            path  TEXT PRIMARY KEY,
            mtime REAL NOT NULL,
            size  INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS chunks (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            source      TEXT NOT NULL,
            content     TEXT NOT NULL,
            char_offset INTEGER NOT NULL
        );
        CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
            content,
            source      UNINDEXED,
            chunk_id    UNINDEXED,
            tokenize    = 'porter ascii'
        );
    """)
    conn.commit()
    return conn


# ── Indexing ──────────────────────────────────────────────────────────────────

def needs_reindex(conn: sqlite3.Connection, source_paths: list[str]) -> list[str]:
    """Return list of source paths that need (re)indexing."""
    stale = []
    for path in source_paths:
        fp = file_fingerprint(path)
        if fp is None:
            # Missing or empty — remove any existing chunks for this source
            continue
        row = conn.execute(
            "SELECT mtime, size FROM file_meta WHERE path = ?", (path,)
        ).fetchone()
        if row is None or (row[0] != fp[0] or row[1] != fp[1]):
            stale.append(path)
    return stale


def index_file(conn: sqlite3.Connection, path: str) -> int:
    """Rechunk a file and insert into chunks + FTS. Returns chunk count."""
    text = Path(path).read_text(errors="replace")
    chunks = chunk_text(text)
    if not chunks:
        return 0

    # Remove existing chunks for this source
    old_ids = [
        row[0] for row in
        conn.execute("SELECT id FROM chunks WHERE source = ?", (path,)).fetchall()
    ]
    if old_ids:
        placeholders = ",".join("?" * len(old_ids))
        conn.execute(f"DELETE FROM chunks_fts WHERE chunk_id IN ({placeholders})", old_ids)
        conn.execute(f"DELETE FROM chunks WHERE id IN ({placeholders})", old_ids)

    # Insert new chunks
    for content, offset in chunks:
        cur = conn.execute(
            "INSERT INTO chunks (source, content, char_offset) VALUES (?, ?, ?)",
            (path, content, offset),
        )
        chunk_id = cur.lastrowid
        conn.execute(
            "INSERT INTO chunks_fts (content, source, chunk_id) VALUES (?, ?, ?)",
            (content, path, str(chunk_id)),
        )

    # Update fingerprint
    fp = file_fingerprint(path)
    if fp:
        conn.execute(
            "INSERT OR REPLACE INTO file_meta (path, mtime, size) VALUES (?, ?, ?)",
            (path, fp[0], fp[1]),
        )

    conn.commit()
    return len(chunks)


def refresh_index(conn: sqlite3.Connection, source_paths: list[str]) -> None:
    """Reindex any stale source files. Silently skips missing/empty files."""
    stale = needs_reindex(conn, source_paths)
    for path in stale:
        count = index_file(conn, path)
        print(f"[memory_indexer] Indexed {path} → {count} chunks", file=sys.stderr)


# ── Query construction ────────────────────────────────────────────────────────

QUERY_PROMPT = """Extract 5-8 key search terms from this task description for a memory retrieval query.
Focus on domain concepts, action types, and subject areas — not common words.
Return only the terms as a single space-separated line. No explanation, no punctuation.

Task: {task}"""


def build_retrieval_query(task_desc: str) -> str:
    """Call claude-haiku to extract search terms. Falls back to raw task on failure."""
    if not task_desc.strip():
        return ""
    prompt = QUERY_PROMPT.format(task=task_desc[:2000])
    try:
        result = subprocess.run(
            [
                "claude", "-p",
                "--model", "claude-haiku-4-5",
                "--max-turns", "1",
                "--output-format", "text",
            ],
            input=prompt,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return task_desc[:500]

    if result.returncode != 0 or not result.stdout.strip():
        return task_desc[:500]

    return result.stdout.strip()


# ── Retrieval ─────────────────────────────────────────────────────────────────

def retrieve_bm25(conn: sqlite3.Connection, query: str, top_k: int = 5) -> list[tuple[str, str, float]]:
    """FTS5 BM25 full-text search.

    Returns list of (source_path, content, rank) sorted best-first.
    rank is negative (FTS5 convention); more-negative = better match.
    """
    if not query.strip():
        return []

    # Build FTS5 match expression: quote each term, join with OR
    terms = [t.strip() for t in query.split() if t.strip()]
    if not terms:
        return []

    # Try exact phrase first, fall back to OR of individual terms
    try:
        rows = conn.execute(
            """
            SELECT source, content, rank
            FROM chunks_fts
            WHERE chunks_fts MATCH ?
            ORDER BY rank
            LIMIT ?
            """,
            (" OR ".join(terms), top_k * 3),
        ).fetchall()
    except sqlite3.OperationalError:
        # FTS syntax error — try simplified query
        try:
            rows = conn.execute(
                """
                SELECT source, content, rank
                FROM chunks_fts
                WHERE chunks_fts MATCH ?
                ORDER BY rank
                LIMIT ?
                """,
                (terms[0], top_k * 3),
            ).fetchall()
        except sqlite3.OperationalError:
            return []

    return [(row[0], row[1], row[2]) for row in rows[:top_k]]


# ── Embedding retrieval (optional) ────────────────────────────────────────────

def try_embed(text: str) -> list[float] | None:
    """Try to embed text using OpenAI → Gemini → None."""
    api_key = os.environ.get("OPENAI_API_KEY", "")
    if api_key:
        try:
            import openai  # type: ignore
            client = openai.OpenAI(api_key=api_key)
            resp = client.embeddings.create(
                model="text-embedding-3-small",
                input=text,
            )
            return resp.data[0].embedding
        except Exception:
            pass

    g_key = os.environ.get("GOOGLE_API_KEY", "") or os.environ.get("GEMINI_API_KEY", "")
    if g_key:
        try:
            import google.generativeai as genai  # type: ignore
            genai.configure(api_key=g_key)
            result = genai.embed_content(
                model="models/gemini-embedding-001",
                content=text,
            )
            return result["embedding"]
        except Exception:
            pass

    return None


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Cosine similarity between two equal-length vectors."""
    dot = sum(x * y for x, y in zip(a, b))
    mag_a = sum(x * x for x in a) ** 0.5
    mag_b = sum(x * x for x in b) ** 0.5
    if mag_a == 0 or mag_b == 0:
        return 0.0
    return dot / (mag_a * mag_b)


def ensure_embeddings_table(conn: sqlite3.Connection, dim: int) -> None:
    """Create chunk_embeddings table if missing (not using sqlite-vec, plain BLOB)."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS chunk_embeddings (
            chunk_id INTEGER PRIMARY KEY REFERENCES chunks(id),
            embedding TEXT NOT NULL
        )
    """)
    conn.commit()


def retrieve_hybrid(
    conn: sqlite3.Connection,
    query: str,
    query_embedding: list[float],
    top_k: int = 5,
) -> list[tuple[str, str, float]]:
    """Hybrid retrieval: 0.7 × vector + 0.3 × BM25.

    Falls back to BM25-only if chunk_embeddings is missing or empty.
    """
    import json

    # BM25 results (get more candidates for re-ranking)
    bm25_results = retrieve_bm25(conn, query, top_k=top_k * 4)
    if not bm25_results:
        return []

    # Normalize BM25 ranks to [0,1]: rank is negative, more-negative = better
    ranks = [r[2] for r in bm25_results]
    min_rank, max_rank = min(ranks), max(ranks)
    rank_range = max_rank - min_rank if max_rank != min_rank else 1.0

    scored = []
    for source, content, rank in bm25_results:
        bm25_score = (max_rank - rank) / rank_range  # higher is better

        # Try to get chunk embedding
        row = conn.execute(
            "SELECT c.id, ce.embedding FROM chunks c "
            "LEFT JOIN chunk_embeddings ce ON c.id = ce.chunk_id "
            "WHERE c.source = ? AND c.content = ? LIMIT 1",
            (source, content),
        ).fetchone()

        vec_score = 0.0
        if row and row[1]:
            try:
                chunk_vec = json.loads(row[1])
                vec_score = max(0.0, cosine_similarity(query_embedding, chunk_vec))
            except Exception:
                pass

        final_score = 0.7 * vec_score + 0.3 * bm25_score
        scored.append((source, content, final_score))

    scored.sort(key=lambda x: x[2], reverse=True)
    return scored[:top_k]


# ── Formatting ────────────────────────────────────────────────────────────────

def format_chunks(results: list[tuple[str, str, float]]) -> str:
    """Format retrieved chunks as a markdown context block."""
    if not results:
        return ""

    parts = ["## Retrieved Memory Context\n"]
    for source_path, content, score in results:
        label = Path(source_path).name
        parts.append(f"### {label}\n\n{content.strip()}\n")

    return "\n".join(parts)


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(description="Memory indexer and retriever")
    parser.add_argument("--db", required=True, help="Path to SQLite database file")
    parser.add_argument("--source", action="append", default=[], dest="sources",
                        help="Source markdown file to index (repeatable)")
    parser.add_argument("--task", default="", help="Task description for query construction")
    parser.add_argument("--output", required=True, help="Path to write retrieved context")
    parser.add_argument("--top-k", type=int, default=5, dest="top_k",
                        help="Number of chunks to retrieve")
    args = parser.parse_args()

    output_path = Path(args.output)
    output_path.write_text("")  # ensure file exists (empty = no relevant memory)

    # Filter to existing, non-empty source files
    sources = [s for s in args.sources if Path(s).is_file() and Path(s).stat().st_size > 0]
    if not sources:
        print("[memory_indexer] No non-empty source files found, skipping.", file=sys.stderr)
        return 0

    # Open / create database
    try:
        conn = open_db(args.db)
    except Exception as e:
        print(f"[memory_indexer] Failed to open database: {e}", file=sys.stderr)
        return 0

    # Refresh stale indexes
    try:
        refresh_index(conn, sources)
    except Exception as e:
        print(f"[memory_indexer] Index refresh error: {e}", file=sys.stderr)

    # Check if there's anything indexed
    total = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
    if total == 0:
        print("[memory_indexer] No chunks in index, skipping retrieval.", file=sys.stderr)
        conn.close()
        return 0

    # Build retrieval query
    if not args.task.strip():
        print("[memory_indexer] No task description provided, skipping retrieval.", file=sys.stderr)
        conn.close()
        return 0

    query = build_retrieval_query(args.task)
    if not query.strip():
        conn.close()
        return 0

    print(f"[memory_indexer] Retrieval query: {query[:100]}", file=sys.stderr)

    # Try hybrid retrieval (embedding + BM25), fall back to BM25-only
    query_embedding = try_embed(query) if args.task else None
    if query_embedding:
        try:
            results = retrieve_hybrid(conn, query, query_embedding, top_k=args.top_k)
        except Exception:
            results = retrieve_bm25(conn, query, top_k=args.top_k)
    else:
        results = retrieve_bm25(conn, query, top_k=args.top_k)

    conn.close()

    if not results:
        print("[memory_indexer] No relevant chunks found.", file=sys.stderr)
        return 0

    formatted = format_chunks(results)
    if formatted.strip():
        output_path.write_text(formatted)
        print(f"[memory_indexer] Wrote {len(results)} chunks to {args.output}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
