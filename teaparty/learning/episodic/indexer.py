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


def _parse_frontmatter_simple(text: str) -> dict:
    """Parse simple key: value YAML frontmatter lines into a dict.

    Handles only flat key: value pairs. Strips surrounding quotes from values
    so that serialized fields like `last_reinforced: '2026-03-03'` are stored
    as bare strings (e.g. '2026-03-03') not quoted strings ("'2026-03-03'").

    Returns empty dict if no recognisable key: value lines are found.
    """
    result: dict = {}
    for line in text.strip().splitlines():
        if ':' not in line:
            continue
        key, _, val = line.partition(':')
        k = key.strip()
        v = val.strip()
        # Strip surrounding single or double quotes
        if len(v) >= 2 and v[0] == v[-1] and v[0] in ("'", '"'):
            v = v[1:-1]
        if k and k.isidentifier():
            result[k] = v
    return result


def chunk_by_entries(text: str, chunk_size: int = 1600, overlap: int = 320) -> list[tuple[str, dict, int]]:
    """Entry-aware chunking: splits on YAML frontmatter '---' boundaries.

    For structured MEMORY.md files, each entry (frontmatter + content block)
    becomes one chunk with its YAML metadata extracted as a dict.

    Falls back to character-based chunking for plain markdown files that
    have no '---' frontmatter delimiters.

    Returns list of (content, metadata_dict, char_offset) triples.
    metadata_dict is empty for plain-text fallback chunks.
    """
    if not text.strip():
        return []

    # splitlines(keepends=True) preserves '\n' so char offsets are correct
    lines = text.splitlines(keepends=True)

    # Find indices of lines that are exactly '---' (allow trailing whitespace)
    sep_indices = [i for i, l in enumerate(lines) if l.rstrip() == '---']

    # Need at least one open+close delimiter pair to attempt structured parsing
    if len(sep_indices) < 2:
        return [(c, {}, o) for c, o in chunk_text(text, chunk_size, overlap)]

    results = []
    i = 0
    while i + 1 < len(sep_indices):
        open_idx = sep_indices[i]
        close_idx = sep_indices[i + 1]

        fm_lines = lines[open_idx + 1:close_idx]
        fm_text = ''.join(fm_lines)
        metadata = _parse_frontmatter_simple(fm_text)

        if not metadata:
            # Not valid frontmatter — advance by 1 and retry
            i += 1
            continue

        # Content: from after closing '---' up to next opening '---' or EOF
        content_start = close_idx + 1
        if i + 2 < len(sep_indices):
            content_end = sep_indices[i + 2]
        else:
            content_end = len(lines)

        content_lines = lines[content_start:content_end]
        # Strip trailing blank lines between entries
        while content_lines and not content_lines[-1].strip():
            content_lines.pop()

        content = ''.join(content_lines).rstrip()

        # Full entry text (frontmatter + content)
        entry_text = ''.join(lines[open_idx:content_end]).rstrip()

        # Char offset of the opening '---' line
        char_offset = sum(len(l) for l in lines[:open_idx])

        if entry_text.strip():
            results.append((entry_text, metadata, char_offset))

        # Advance by 2: skip this open/close pair
        i += 2

    if not results:
        # No valid entries found — fall back to character chunking
        return [(c, {}, o) for c, o in chunk_text(text, chunk_size, overlap)]

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

    try:
        conn.execute("ALTER TABLE chunks ADD COLUMN metadata TEXT")
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
    """Rechunk a file and insert into chunks + FTS. Returns chunk count.

    Uses entry-aware chunking (chunk_by_entries) for structured MEMORY.md files.
    Falls back to character-based chunking for plain markdown.
    Stores YAML metadata as JSON in the chunks.metadata column.
    """
    text = Path(path).read_text(errors="replace")
    entry_chunks = chunk_by_entries(text)
    if not entry_chunks:
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

    # Insert new chunks (content, metadata_dict, offset triples)
    for content, metadata, offset in entry_chunks:
        meta_json = json.dumps(metadata) if metadata else None
        cur = conn.execute(
            "INSERT INTO chunks (source, content, char_offset, metadata) VALUES (?, ?, ?, ?)",
            (path, content, offset, meta_json),
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
    return len(entry_chunks)


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

HALF_LIFE_DAYS = 90.0
DECAY_FLOOR = 0.1


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
    """Apply exponential decay to scores. Evergreen sources (no date in path) are exempt.

    DEPRECATED: use apply_prominence_weights() which reads YAML frontmatter and
    removes the evergreen exemption. Retained for backward compatibility.
    """
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


def compute_prominence(metadata: dict, source_path: str = '', today=None) -> float:
    """Compute entry prominence from YAML frontmatter metadata.

    Prominence = importance × recency_decay × (1 + reinforcement_count)

    importance          : float in [0,1]; default 0.5 for legacy/plain entries
    recency_decay       : max(DECAY_FLOOR, exp(-ln(2)/HALF_LIFE_DAYS × age_days))
                          age derived from last_reinforced (frontmatter)
                          → source path date → 30-day default
    reinforcement_count : int; default 0

    Retired entries return 0.0.
    The decay floor ensures old-but-important entries remain discoverable.

    Entries with no date anywhere default to 30-day age — NO evergreen exemption.
    """
    if today is None:
        today = date_type.today()

    if metadata.get('status') == 'retired':
        return 0.0

    importance = float(metadata.get('importance', 0.5))
    importance = max(0.0, min(1.0, importance))

    reinforcement_count = int(metadata.get('reinforcement_count', 0))

    # Determine age: frontmatter last_reinforced > source path date > 30-day default
    age_days: int | None = None

    lr = metadata.get('last_reinforced', '')
    if lr:
        try:
            entry_date = date_type.fromisoformat(str(lr)[:10])
            age_days = max(0, (today - entry_date).days)
        except (ValueError, TypeError):
            pass

    if age_days is None and source_path:
        path_date = infer_date_from_path(source_path)
        if path_date is not None:
            age_days = max(0, (today - path_date).days)

    if age_days is None:
        # No date available — assume 30 days old (no evergreen exemption)
        age_days = 30

    lambda_d = math.log(2) / HALF_LIFE_DAYS
    recency_decay = max(DECAY_FLOOR, math.exp(-lambda_d * age_days))

    return importance * recency_decay * (1 + reinforcement_count)


def apply_prominence_weights(
    results: list[tuple[str, str, float]],
    conn: sqlite3.Connection,
    today=None,
) -> list[tuple[str, str, float]]:
    """Re-weight retrieval results by entry prominence from stored YAML metadata.

    Replaces apply_temporal_decay(). Algorithm:
      1. Normalize raw scores to [0,1] (handles both negative BM25 and [0,1] hybrid).
      2. Look up stored metadata JSON for each chunk.
      3. Compute prominence from metadata + source path.
      4. Final score = normalized_score × prominence.
      5. Retired entries (prominence == 0) are excluded from output.

    Returns (source, content, weighted_score) tuples; caller should sort.
    """
    if not results:
        return results

    # Normalize scores to [0, 1] — required because BM25 returns negative ranks
    raw_scores = [r[2] for r in results]
    min_s, max_s = min(raw_scores), max(raw_scores)
    tied = (max_s == min_s)

    out = []
    for source, content, score in results:
        normalized = 1.0 if tied else (score - min_s) / (max_s - min_s)

        # Look up stored metadata for this chunk
        row = conn.execute(
            "SELECT metadata FROM chunks WHERE source = ? AND content = ? LIMIT 1",
            (source, content),
        ).fetchone()
        metadata: dict = {}
        if row and row[0]:
            try:
                metadata = json.loads(row[0])
            except Exception:
                pass

        # Retired entries are excluded entirely
        if metadata.get('status') == 'retired':
            continue

        prominence = compute_prominence(metadata, source, today)
        out.append((source, content, normalized * prominence))

    return out


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
    tied = (max_s == min_s)
    normalized = [1.0 if tied else (r[2] - min_s) / (max_s - min_s) for r in results]

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

def format_chunks(results: list[tuple[str, str, float]], max_chars: int = 0) -> str:
    """Format retrieved chunks as a markdown context block.

    Clearly frames content as historical learnings to prevent agents
    from confusing past-session artifacts with current task instructions.

    Args:
        results: List of (source_path, content, score) tuples.
        max_chars: Maximum characters in the output. 0 means no limit.
            When set, chunks are added in order until the budget is exhausted.
    """
    if not results:
        return ""

    header = (
        "## Historical Learnings (from previous sessions)\n\n"
        "> These are patterns and lessons extracted from past work sessions.\n"
        "> They are background knowledge only — NOT instructions for your current task.\n"
        "> Use them to inform your approach where relevant, but your actual task is defined separately.\n"
    )

    if max_chars > 0 and len(header) >= max_chars:
        return header[:max_chars]

    parts = [header]
    current_len = len(header)

    for source_path, content, score in results:
        label = Path(source_path).name
        chunk_str = f"\n### {label}\n\n{content.strip()}\n"
        if max_chars > 0 and current_len + len(chunk_str) > max_chars:
            break
        parts.append(chunk_str)
        current_len += len(chunk_str)

    return "".join(parts)


# ── Main ──────────────────────────────────────────────────────────────────────

# -- Learning type classification ---------------------------------------------

def classify_learning_type(source_path: str) -> str:
    """Classify source path to learning type: 'institutional', 'task', or 'proxy'.

    Classification is by file/directory name pattern:
      - institutional.md          → 'institutional'
      - tasks/ (any file within)  → 'task'
      - proxy.md                  → 'proxy'
      - proxy-tasks/ (any file)   → 'proxy'
      - anything else             → 'task' (safe default)
    """
    p = Path(source_path)
    name = p.name.lower()
    parts = [part.lower() for part in p.parts]

    if name == 'institutional.md':
        return 'institutional'
    if name == 'proxy.md':
        return 'proxy'
    if 'proxy-tasks' in parts:
        return 'proxy'
    if 'tasks' in parts:
        return 'task'
    return 'task'


# -- Scope weighting ----------------------------------------------------------

SCOPE_MULTIPLIERS = {
    'team': 1.5,
    'project': 1.2,
    'global': 1.0,
}


def classify_scope(source_path: str, base_project_dir: str) -> str:
    """Classify source scope: 'team' (.sessions/ path), 'project', or 'global'."""
    if not base_project_dir:
        return 'global'
    try:
        p = Path(source_path).resolve()
        base = Path(base_project_dir).resolve()
        rel = p.relative_to(base)
        if '.sessions' in rel.parts:
            return 'team'
        return 'project'
    except ValueError:
        return 'global'


def apply_scope_multipliers(
    results: list[tuple[str, str, float]],
    base_project_dir: str,
) -> list[tuple[str, str, float]]:
    """Multiply scores by scope-level weight: team x1.5, project x1.2, global x1.0."""
    if not base_project_dir:
        return results
    return [
        (source, content, score * SCOPE_MULTIPLIERS.get(classify_scope(source, base_project_dir), 1.0))
        for source, content, score in results
    ]


def retrieve(
    task: str,
    db_path: str,
    source_paths: list[str],
    top_k: int = 5,
    scope_base_dir: str = '',
    ids_output_path: str = '',
    learning_type: str | None = None,
    max_chars: int = 0,
) -> str:
    """Importable retrieval entry point for the memory system.

    Indexes source files (if changed), retrieves relevant chunks for the task,
    applies prominence weighting and scope multipliers, and returns formatted
    context as a string.  Returns empty string if no relevant memory is found.

    Args:
        task: Task description used to construct the retrieval query.
        db_path: Path to the SQLite FTS5 database file.
        source_paths: Markdown files (or directories of .md files) to index.
        top_k: Number of chunks to return after MMR reranking.
        scope_base_dir: Project base directory for scope-level score multipliers.
        ids_output_path: If provided, write retrieved entry IDs (one per line)
            to this path for reinforcement tracking at session end.
        learning_type: Filter results to a specific learning type
            ('institutional', 'task', 'proxy'). None (default) returns all types.
        max_chars: Maximum characters in the returned string. 0 (default)
            means no limit. Used for per-type budget allocation.
    """
    # Expand directories to contained .md files and filter to non-empty
    sources = []
    for s in source_paths:
        p = Path(s)
        if p.is_dir():
            for f in sorted(p.glob('*.md')):
                if f.is_file() and f.stat().st_size > 0:
                    sources.append(str(f))
        elif p.is_file() and p.stat().st_size > 0:
            sources.append(str(s))
    if not sources:
        return ''

    try:
        conn = open_db(db_path)
    except Exception:
        return ''

    try:
        # Refresh index for changed source files
        refresh_index(conn, sources)

        # Check if anything is indexed
        total = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
        if total == 0:
            return ''

        if not task.strip():
            return ''

        query = build_retrieval_query(task)
        if not query.strip():
            return ''

        # Hybrid retrieval (embedding + BM25) with BM25 fallback
        query_embedding = try_embed(query, conn=conn)
        if query_embedding:
            try:
                results = retrieve_hybrid(conn, query, query_embedding, top_k=top_k * 4)
            except Exception:
                results = retrieve_bm25(conn, query, top_k=top_k * 4)
        else:
            results = retrieve_bm25(conn, query, top_k=top_k * 4)

        # Filter by learning type if specified
        if learning_type is not None:
            results = [
                (source, content, score)
                for source, content, score in results
                if classify_learning_type(source) == learning_type
            ]

        # Apply prominence weighting and scope multipliers
        results = apply_prominence_weights(results, conn)
        if scope_base_dir:
            results = apply_scope_multipliers(results, scope_base_dir)
        results.sort(key=lambda x: x[2], reverse=True)
        results = mmr_rerank(results, top_k=top_k)

        if not results:
            return ''

        # Write retrieved entry IDs to sidecar file for reinforcement tracking
        if ids_output_path:
            entry_ids = []
            for source, content, _score in results:
                row = conn.execute(
                    "SELECT metadata FROM chunks WHERE source = ? AND content = ? LIMIT 1",
                    (source, content),
                ).fetchone()
                if row and row[0]:
                    try:
                        meta = json.loads(row[0])
                        eid = meta.get('id', '')
                        if eid:
                            entry_ids.append(eid)
                    except Exception:
                        pass
            if entry_ids:
                Path(ids_output_path).write_text('\n'.join(entry_ids) + '\n')

        return format_chunks(results, max_chars=max_chars)
    finally:
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Memory indexer and retriever")
    parser.add_argument("--db", required=True, help="Path to SQLite database file")
    parser.add_argument("--source", action="append", default=[], dest="sources",
                        help="Source markdown file to index (repeatable)")
    parser.add_argument("--task", default="", help="Task description for query construction")
    parser.add_argument("--output", required=True, help="Path to write retrieved context")
    parser.add_argument("--top-k", type=int, default=5, dest="top_k",
                        help="Number of chunks to retrieve")
    parser.add_argument("--retrieved-ids", default="", dest="retrieved_ids",
                        help="Path to write retrieved entry IDs for reinforcement tracking")
    parser.add_argument("--scope-base-dir", default="", dest="scope_base_dir",
                        help="Project base directory for scope-level score multiplier (team > project > global)")
    args = parser.parse_args()

    output_path = Path(args.output)
    output_path.write_text("")  # ensure file exists (empty = no relevant memory)

    # Filter to existing, non-empty source files; expand directory paths to contained .md files
    sources = []
    for s in args.sources:
        p = Path(s)
        if p.is_dir():
            for f in sorted(p.glob('*.md')):
                if f.is_file() and f.stat().st_size > 0:
                    sources.append(str(f))
        elif p.is_file() and p.stat().st_size > 0:
            sources.append(s)
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

    # Apply prominence weighting (replaces apply_temporal_decay — removes evergreen exemption)
    results = apply_prominence_weights(results, conn)

    if args.scope_base_dir:
        results = apply_scope_multipliers(results, args.scope_base_dir)
    results.sort(key=lambda x: x[2], reverse=True)
    results = mmr_rerank(results, top_k=args.top_k)

    # Phase 5: Write retrieved entry IDs to sidecar file for reinforcement tracking
    if args.retrieved_ids and results:
        entry_ids = []
        for source, content, _score in results:
            row = conn.execute(
                "SELECT metadata FROM chunks WHERE source = ? AND content = ? LIMIT 1",
                (source, content),
            ).fetchone()
            if row and row[0]:
                try:
                    meta = json.loads(row[0])
                    eid = meta.get('id', '')
                    if eid:
                        entry_ids.append(eid)
                except Exception:
                    pass
        if entry_ids:
            Path(args.retrieved_ids).write_text('\n'.join(entry_ids) + '\n')
            print(f"[memory_indexer] Wrote {len(entry_ids)} retrieved IDs to {args.retrieved_ids}",
                  file=sys.stderr)

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
