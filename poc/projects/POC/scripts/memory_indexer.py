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
import hashlib
import json
import math
import os
import re
import sqlite3
import subprocess
import sys
import time
from datetime import date as date_type
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

    conn.executescript("""
        CREATE TABLE IF NOT EXISTS meta (
            key   TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS embedding_cache (
            hash       TEXT NOT NULL,
            provider   TEXT NOT NULL,
            model      TEXT NOT NULL,
            embedding  TEXT NOT NULL,
            updated_at INTEGER NOT NULL,
            PRIMARY KEY (hash, provider, model)
        );
    """)

    try:
        conn.execute("ALTER TABLE file_meta ADD COLUMN hash TEXT")
        conn.commit()
    except sqlite3.OperationalError:
        pass  # column already exists

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
            "SELECT mtime, size, hash FROM file_meta WHERE path = ?", (path,)
        ).fetchone()
        if row is None or (row[0] != fp[0] or row[1] != fp[1] or row[2] != fp[2]):
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
            "INSERT OR REPLACE INTO file_meta (path, mtime, size, hash) VALUES (?, ?, ?, ?)",
            (path, fp[0], fp[1], fp[2]),
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

def detect_provider() -> tuple[str, str]:
    """Detect which embedding provider would be used. Returns (provider, model)."""
    if os.environ.get("OPENAI_API_KEY", ""):
        return ("openai", "text-embedding-3-small")
    if os.environ.get("GOOGLE_API_KEY", "") or os.environ.get("GEMINI_API_KEY", ""):
        return ("gemini", "models/gemini-embedding-001")
    return ("none", "")


def try_embed(text: str, conn: sqlite3.Connection | None = None, provider: str = "", model: str = "") -> list[float] | None:
    """Try to embed text using OpenAI → Gemini → None. Uses embedding_cache if conn provided."""
    text_hash = hashlib.sha256(text.encode()).hexdigest()

    # Check cache first
    if conn and provider and model:
        row = conn.execute(
            "SELECT embedding FROM embedding_cache WHERE hash=? AND provider=? AND model=?",
            (text_hash, provider, model),
        ).fetchone()
        if row:
            try:
                return json.loads(row[0])
            except Exception:
                pass

    embedding = None
    actual_provider = ""
    actual_model = ""

    api_key = os.environ.get("OPENAI_API_KEY", "")
    if api_key:
        try:
            import openai  # type: ignore
            client = openai.OpenAI(api_key=api_key)
            m = "text-embedding-3-small"
            resp = client.embeddings.create(model=m, input=text)
            embedding = resp.data[0].embedding
            actual_provider = "openai"
            actual_model = m
        except Exception:
            pass

    if embedding is None:
        g_key = os.environ.get("GOOGLE_API_KEY", "") or os.environ.get("GEMINI_API_KEY", "")
        if g_key:
            try:
                import google.generativeai as genai  # type: ignore
                genai.configure(api_key=g_key)
                m = "models/gemini-embedding-001"
                result = genai.embed_content(model=m, content=text)
                embedding = result["embedding"]
                actual_provider = "gemini"
                actual_model = m
            except Exception:
                pass

    # Store in cache
    if embedding and conn and actual_provider and actual_model:
        try:
            conn.execute(
                "INSERT OR REPLACE INTO embedding_cache (hash, provider, model, embedding, updated_at) VALUES (?,?,?,?,?)",
                (text_hash, actual_provider, actual_model, json.dumps(embedding), int(time.time())),
            )
            conn.commit()
        except Exception:
            pass

    return embedding


def load_meta(conn: sqlite3.Connection) -> dict:
    """Load key-value metadata from the meta table."""
    rows = conn.execute("SELECT key, value FROM meta").fetchall()
    return {row[0]: row[1] for row in rows}


def save_meta(conn: sqlite3.Connection, provider: str, model: str) -> None:
    """Persist provider and model into the meta table."""
    for k, v in [("provider", provider), ("model", model)]:
        conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?,?)", (k, v))
    conn.commit()


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


# ── Temporal decay ────────────────────────────────────────────────────────────

HALF_LIFE_DAYS = 30.0


def infer_date_from_path(source_path: str):
    """Extract date from path like .../memory/YYYY-MM-DD.md. Returns date or None (evergreen)."""
    m = re.search(r'(\d{4}-\d{2}-\d{2})', source_path)
    if m:
        try:
            return date_type.fromisoformat(m.group(1))
        except ValueError:
            pass
    return None


def apply_temporal_decay(
    results: list[tuple[str, str, float]],
    today=None,
) -> list[tuple[str, str, float]]:
    """Apply exponential decay to scores. Evergreen sources (no date in path) are exempt."""
    if today is None:
        today = date_type.today()
    lambda_d = math.log(2) / HALF_LIFE_DAYS
    decayed = []
    for source, content, score in results:
        d = infer_date_from_path(source)
        if d is not None:
            age_days = max(0, (today - d).days)
            score = score * math.exp(-lambda_d * age_days)
        decayed.append((source, content, score))
    return decayed


# ── MMR diversification ───────────────────────────────────────────────────────

def mmr_rerank(
    results: list[tuple[str, str, float]],
    top_k: int = 5,
    lambda_mmr: float = 0.7,
) -> list[tuple[str, str, float]]:
    """Maximal Marginal Relevance re-ranking using Jaccard similarity on tokenized text."""
    if len(results) <= 1:
        return results[:top_k]

    def tokenize(text: str) -> set:
        return set(re.findall(r'[a-z0-9_]+', text.lower()))

    def jaccard(a: set, b: set) -> float:
        union = a | b
        if not union:
            return 0.0
        return len(a & b) / len(union)

    scores = [r[2] for r in results]
    max_s = max(scores) if scores else 1.0
    min_s = min(scores) if scores else 0.0
    rng = max_s - min_s if max_s != min_s else 1.0
    normalized = [(r[2] - min_s) / rng for r in results]

    tokens = [tokenize(r[1]) for r in results]
    selected = []
    selected_idx = []
    remaining = list(range(len(results)))

    while remaining and len(selected) < top_k:
        if not selected_idx:
            best = max(remaining, key=lambda i: normalized[i])
        else:
            def mmr_score(i):
                rel = normalized[i]
                max_sim = max(jaccard(tokens[i], tokens[j]) for j in selected_idx)
                return lambda_mmr * rel - (1 - lambda_mmr) * max_sim
            best = max(remaining, key=mmr_score)
        selected.append(results[best])
        selected_idx.append(best)
        remaining.remove(best)

    return selected


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

    # Detect provider and handle full reindex if provider changed
    try:
        stored_meta = load_meta(conn)
        cur_provider, cur_model = detect_provider()
        provider_changed = (
            stored_meta.get("provider", "") != cur_provider or
            stored_meta.get("model", "") != cur_model
        )
        if provider_changed and stored_meta:
            print(
                f"[memory_indexer] Provider changed ({stored_meta.get('provider', '')} → {cur_provider}), full reindex.",
                file=sys.stderr,
            )
            conn.execute("DELETE FROM chunk_embeddings")
            conn.execute("DELETE FROM embedding_cache")
            conn.commit()
            for path in sources:
                fp = file_fingerprint(path)
                if fp:
                    index_file(conn, path)
        else:
            refresh_index(conn, sources)

        save_meta(conn, cur_provider, cur_model)
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
    query_embedding = try_embed(query, conn=conn) if args.task else None
    if query_embedding:
        try:
            results = retrieve_hybrid(conn, query, query_embedding, top_k=args.top_k * 4)
        except Exception:
            results = retrieve_bm25(conn, query, top_k=args.top_k * 4)
    else:
        results = retrieve_bm25(conn, query, top_k=args.top_k * 4)

    # Apply temporal decay, sort, then MMR
    results = apply_temporal_decay(results)
    results.sort(key=lambda x: x[2], reverse=True)
    results = mmr_rerank(results, top_k=args.top_k)

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
