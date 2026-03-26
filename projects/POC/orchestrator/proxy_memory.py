"""ACT-R activation-based memory for the human proxy agent.

Stores interaction memories as chunks with independent embedding dimensions.
Retrieval uses two stages: activation filtering (base-level activation > tau),
then composite scoring (normalized activation + multi-dimensional cosine
similarity + logistic noise).

Theory: docs/detailed-design/act-r.md
Chunk schema: docs/detailed-design/act-r-proxy-mapping.md
Two-pass prediction: docs/detailed-design/act-r-proxy-sensorium.md
"""
from __future__ import annotations

import json
import logging
import math
import os
import random
import sqlite3
import uuid
from dataclasses import dataclass, field
from typing import Any

_log = logging.getLogger('orchestrator.proxy_memory')

# ACT-R parameters (from act-r.md §Standard Parameter Values)
DECAY = 0.5
NOISE_SCALE = 0.25
RETRIEVAL_THRESHOLD = -0.5
ACTIVATION_WEIGHT = 0.5
SEMANTIC_WEIGHT = 0.5
TOTAL_EMBEDDING_DIMENSIONS = 5

# Embedding dimension names
EMBEDDING_DIMS = ('situation', 'artifact', 'stimulus', 'response', 'salience')


@dataclass
class MemoryChunk:
    id: str
    type: str                           # gate_outcome, dialog_turn, discovery_response
    state: str                          # CfA state or DISCOVERY_{lens}
    task_type: str                      # project slug
    outcome: str                        # approve, correct, dismiss, promote, discuss
    lens: str = ''                      # discovery lens (empty for gate mode)
    prior_prediction: str = ''
    prior_confidence: float = 0.0
    posterior_prediction: str = ''
    posterior_confidence: float = 0.0
    prediction_delta: str = ''          # what changed between passes
    salient_percepts: list[str] = field(default_factory=list)
    human_response: str = ''
    delta: str = ''                     # proxy error vs human response
    content: str = ''                   # full text of the interaction
    traces: list[int] = field(default_factory=list)
    embedding_model: str = ''
    embedding_situation: list[float] | None = None
    embedding_artifact: list[float] | None = None
    embedding_stimulus: list[float] | None = None
    embedding_response: list[float] | None = None
    embedding_salience: list[float] | None = None


# ── Database ─────────────────────────────────────────────────────────────────

_SCHEMA = """
CREATE TABLE IF NOT EXISTS proxy_chunks (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL,
    state TEXT NOT NULL,
    task_type TEXT DEFAULT '',
    outcome TEXT NOT NULL,
    lens TEXT DEFAULT '',
    prior_prediction TEXT DEFAULT '',
    prior_confidence REAL DEFAULT 0,
    posterior_prediction TEXT DEFAULT '',
    posterior_confidence REAL DEFAULT 0,
    prediction_delta TEXT DEFAULT '',
    salient_percepts TEXT DEFAULT '[]',
    human_response TEXT DEFAULT '',
    delta TEXT DEFAULT '',
    content TEXT NOT NULL,
    traces TEXT NOT NULL,
    embedding_model TEXT DEFAULT '',
    embedding_situation TEXT,
    embedding_artifact TEXT,
    embedding_stimulus TEXT,
    embedding_response TEXT,
    embedding_salience TEXT
);

CREATE TABLE IF NOT EXISTS proxy_state (
    key TEXT PRIMARY KEY,
    value INTEGER NOT NULL
);
INSERT OR IGNORE INTO proxy_state (key, value) VALUES ('interaction_counter', 0);

CREATE TABLE IF NOT EXISTS embedding_cache (
    hash TEXT NOT NULL,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    embedding TEXT NOT NULL,
    updated_at INTEGER,
    PRIMARY KEY (hash, provider, model)
);
"""


def open_proxy_db(db_path: str) -> sqlite3.Connection:
    """Open (or create) the proxy memory database."""
    os.makedirs(os.path.dirname(db_path) or '.', exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA journal_mode=WAL')
    conn.executescript(_SCHEMA)
    return conn


# ── Interaction counter ──────────────────────────────────────────────────────

def get_interaction_counter(conn: sqlite3.Connection) -> int:
    row = conn.execute(
        "SELECT value FROM proxy_state WHERE key='interaction_counter'"
    ).fetchone()
    return row[0] if row else 0


def _increment_counter_no_commit(conn: sqlite3.Connection) -> int:
    """Increment the interaction counter without committing (for use in transactions)."""
    conn.execute(
        "UPDATE proxy_state SET value = value + 1 WHERE key='interaction_counter'"
    )
    row = conn.execute(
        "SELECT value FROM proxy_state WHERE key='interaction_counter'"
    ).fetchone()
    return row[0]


def increment_interaction_counter(conn: sqlite3.Connection) -> int:
    conn.execute('BEGIN IMMEDIATE')
    try:
        result = _increment_counter_no_commit(conn)
        conn.commit()
        return result
    except Exception:
        conn.rollback()
        raise


# ── Chunk CRUD ───────────────────────────────────────────────────────────────

def _store_chunk_no_commit(conn: sqlite3.Connection, chunk: MemoryChunk) -> None:
    """Insert/replace a chunk without committing (for use in transactions)."""
    conn.execute(
        """INSERT OR REPLACE INTO proxy_chunks
           (id, type, state, task_type, outcome, lens,
            prior_prediction, prior_confidence,
            posterior_prediction, posterior_confidence,
            prediction_delta, salient_percepts,
            human_response, delta, content, traces,
            embedding_model,
            embedding_situation, embedding_artifact,
            embedding_stimulus, embedding_response, embedding_salience)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            chunk.id, chunk.type, chunk.state, chunk.task_type,
            chunk.outcome, chunk.lens,
            chunk.prior_prediction, chunk.prior_confidence,
            chunk.posterior_prediction, chunk.posterior_confidence,
            chunk.prediction_delta, json.dumps(chunk.salient_percepts),
            chunk.human_response, chunk.delta, chunk.content,
            json.dumps(chunk.traces), chunk.embedding_model,
            _embed_to_json(chunk.embedding_situation),
            _embed_to_json(chunk.embedding_artifact),
            _embed_to_json(chunk.embedding_stimulus),
            _embed_to_json(chunk.embedding_response),
            _embed_to_json(chunk.embedding_salience),
        ),
    )


def store_chunk(conn: sqlite3.Connection, chunk: MemoryChunk) -> None:
    _store_chunk_no_commit(conn, chunk)
    conn.commit()


def get_chunk(conn: sqlite3.Connection, chunk_id: str) -> MemoryChunk | None:
    row = conn.execute(
        'SELECT * FROM proxy_chunks WHERE id=?', (chunk_id,),
    ).fetchone()
    if not row:
        return None
    return _row_to_chunk(row)


def _add_trace_no_commit(conn: sqlite3.Connection, chunk_id: str, interaction: int) -> None:
    """Add a trace to a chunk without committing (for use in transactions)."""
    row = conn.execute(
        'SELECT traces FROM proxy_chunks WHERE id=?', (chunk_id,),
    ).fetchone()
    if not row:
        return
    traces = json.loads(row[0])
    traces.append(interaction)
    conn.execute(
        'UPDATE proxy_chunks SET traces=? WHERE id=?',
        (json.dumps(traces), chunk_id),
    )


def add_trace(conn: sqlite3.Connection, chunk_id: str, interaction: int) -> None:
    _add_trace_no_commit(conn, chunk_id, interaction)
    conn.commit()


def query_chunks(
    conn: sqlite3.Connection, *, state: str = '', task_type: str = '',
) -> list[MemoryChunk]:
    clauses = []
    params: list[str] = []
    if state:
        clauses.append('state = ?')
        params.append(state)
    if task_type:
        clauses.append('task_type = ?')
        params.append(task_type)
    where = (' WHERE ' + ' AND '.join(clauses)) if clauses else ''
    rows = conn.execute(f'SELECT * FROM proxy_chunks{where}', params).fetchall()
    return [_row_to_chunk(r) for r in rows]


def _row_to_chunk(row: sqlite3.Row) -> MemoryChunk:
    return MemoryChunk(
        id=row['id'], type=row['type'], state=row['state'],
        task_type=row['task_type'], outcome=row['outcome'], lens=row['lens'],
        prior_prediction=row['prior_prediction'],
        prior_confidence=row['prior_confidence'],
        posterior_prediction=row['posterior_prediction'],
        posterior_confidence=row['posterior_confidence'],
        prediction_delta=row['prediction_delta'],
        salient_percepts=json.loads(row['salient_percepts']) if row['salient_percepts'] else [],
        human_response=row['human_response'], delta=row['delta'],
        content=row['content'],
        traces=json.loads(row['traces']) if row['traces'] else [],
        embedding_model=row['embedding_model'],
        embedding_situation=_json_to_embed(row['embedding_situation']),
        embedding_artifact=_json_to_embed(row['embedding_artifact']),
        embedding_stimulus=_json_to_embed(row['embedding_stimulus']),
        embedding_response=_json_to_embed(row['embedding_response']),
        embedding_salience=_json_to_embed(row['embedding_salience']),
    )


def _embed_to_json(vec: list[float] | None) -> str | None:
    return json.dumps(vec) if vec is not None else None


def _json_to_embed(s: str | None) -> list[float] | None:
    if s is None:
        return None
    try:
        return json.loads(s)
    except (json.JSONDecodeError, TypeError):
        return None


# ── ACT-R activation ─────────────────────────────────────────────────────────

def base_level_activation(
    traces: list[int], current_interaction: int, d: float = DECAY,
) -> float:
    """Compute B = ln(sum t_i^(-d)) for a chunk's trace history."""
    total = 0.0
    for trace in traces:
        age = max(current_interaction - trace, 1)
        total += age ** (-d)
    if total <= 0:
        return -float('inf')
    return math.log(total)


def normalize_activation(b: float, b_min: float, b_max: float) -> float:
    """Normalize base-level activation to [0, 1] via min-max scaling."""
    if b_max == b_min:
        return 0.5
    return max(0.0, min(1.0, (b - b_min) / (b_max - b_min)))


def logistic_noise(s: float = NOISE_SCALE) -> float:
    """Sample from Logistic(0, s)."""
    p = random.random()
    # Clamp to avoid log(0) or log(inf)
    p = max(1e-10, min(1 - 1e-10, p))
    return s * math.log(p / (1 - p))


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Cosine similarity between two equal-length vectors."""
    if len(a) != len(b):
        raise ValueError(
            f'Vector length mismatch: {len(a)} vs {len(b)}. '
            f'Chunks may have been embedded by different models.'
        )
    if not a:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    mag_a = sum(x * x for x in a) ** 0.5
    mag_b = sum(x * x for x in b) ** 0.5
    if mag_a == 0 or mag_b == 0:
        return 0.0
    return dot / (mag_a * mag_b)


def composite_score(
    chunk: MemoryChunk,
    context_embeddings: dict[str, list[float]],
    current_interaction: int,
    b_min: float,
    b_max: float,
    activation_weight: float = ACTIVATION_WEIGHT,
    semantic_weight: float = SEMANTIC_WEIGHT,
    d: float = DECAY,
    s: float = NOISE_SCALE,
) -> float:
    """Composite ranking score: normalized ACT-R activation +
    multi-dimensional semantic similarity + noise.

    Cosine similarities are summed across matched dimensions and divided
    by TOTAL_EMBEDDING_DIMENSIONS (5), rewarding breadth of matching.
    """
    b = base_level_activation(chunk.traces, current_interaction, d)
    b_norm = normalize_activation(b, b_min, b_max)

    dim_map = {
        'situation': chunk.embedding_situation,
        'artifact': chunk.embedding_artifact,
        'stimulus': chunk.embedding_stimulus,
        'response': chunk.embedding_response,
        'salience': chunk.embedding_salience,
    }
    sim_sum = 0.0
    for dim, context_vec in context_embeddings.items():
        chunk_vec = dim_map.get(dim)
        if chunk_vec and context_vec:
            try:
                sim_sum += cosine_similarity(chunk_vec, context_vec)
            except ValueError:
                _log.debug('Skipping dim %s: vector length mismatch', dim)
    sem = sim_sum / TOTAL_EMBEDDING_DIMENSIONS

    noise = logistic_noise(s)
    return activation_weight * b_norm + semantic_weight * sem + noise


# ── Retrieval ────────────────────────────────────────────────────────────────

def retrieve_chunks(
    conn: sqlite3.Connection,
    *,
    state: str = '',
    task_type: str = '',
    context_embeddings: dict[str, list[float]] | None = None,
    current_interaction: int = 0,
    tau: float = RETRIEVAL_THRESHOLD,
    top_k: int = 10,
    d: float = DECAY,
    s: float = NOISE_SCALE,
) -> list[MemoryChunk]:
    """Two-stage retrieval: activation filter, then composite ranking."""
    candidates = query_chunks(conn, state=state, task_type=task_type)
    context_embeddings = context_embeddings or {}

    # Stage 1: filter by raw activation
    survivors: list[tuple[float, MemoryChunk]] = []
    for c in candidates:
        b = base_level_activation(c.traces, current_interaction, d)
        if b > tau:
            survivors.append((b, c))

    if not survivors:
        return []

    # Compute activation range for normalization
    activations = [b for b, _ in survivors]
    b_min = min(activations)
    b_max = max(activations)

    # Stage 2: composite scoring
    scored = []
    for _, chunk in survivors:
        score = composite_score(
            chunk, context_embeddings, current_interaction,
            b_min, b_max, d=d, s=s,
        )
        scored.append((score, chunk))
    scored.sort(key=lambda x: -x[0])
    return [chunk for _, chunk in scored[:top_k]]


def reinforce_retrieved(
    conn: sqlite3.Connection,
    chunks: list[MemoryChunk],
    current_interaction: int,
) -> None:
    """ACT-R Rule 2: reinforce chunks that were retrieved for a task.

    Called after retrieve_chunks() returns, before the DB connection
    closes. The retrieval itself is the reinforcement signal —
    correctness feedback flows through the chunk's outcome field,
    not through trace frequency.
    """
    for chunk in chunks:
        add_trace(conn, chunk.id, current_interaction)


# ── Recording ────────────────────────────────────────────────────────────────

def record_interaction(
    conn: sqlite3.Connection,
    *,
    chunk_id: str | None = None,
    interaction_type: str,
    state: str,
    task_type: str,
    outcome: str,
    content: str,
    delta: str = '',
    lens: str = '',
    prior_prediction: str = '',
    prior_confidence: float = 0.0,
    posterior_prediction: str = '',
    posterior_confidence: float = 0.0,
    prediction_delta: str = '',
    salient_percepts: list[str] | None = None,
    human_response: str = '',
    situation_text: str = '',
    artifact_text: str = '',
    stimulus_text: str = '',
    embed_fn: Any = None,
) -> MemoryChunk:
    """Record an interaction as a memory chunk.

    If chunk_id matches an existing chunk, adds a trace (reinforcement).
    Otherwise creates a new chunk with independent per-dimension embeddings.
    """
    # Compute embeddings BEFORE the transaction — _default_embed routes to
    # try_embed which calls conn.commit() on the embedding_cache table,
    # so embedding calls must not happen inside our BEGIN IMMEDIATE block.
    _embed = embed_fn or _default_embed(conn)

    provider, model = '', ''
    try:
        from projects.POC.scripts.memory_indexer import detect_provider
        provider, model = detect_provider()
    except Exception:
        pass
    embedding_model = f'{provider}/{model}' if provider else ''

    emb_situation = _embed(situation_text or f'{state} {task_type}') if situation_text or state else None
    emb_artifact = _embed(artifact_text) if artifact_text else None
    emb_stimulus = _embed(stimulus_text) if stimulus_text else None
    emb_response = _embed(human_response) if human_response else None
    emb_salience = _embed(prediction_delta) if prediction_delta else None

    conn.execute('BEGIN IMMEDIATE')
    try:
        current = _increment_counter_no_commit(conn)

        if chunk_id:
            existing = get_chunk(conn, chunk_id)
            if existing:
                _add_trace_no_commit(conn, chunk_id, current)
                conn.commit()
                return get_chunk(conn, chunk_id)  # type: ignore[return-value]

        chunk = MemoryChunk(
            id=str(uuid.uuid4()),
            type=interaction_type,
            state=state,
            task_type=task_type,
            outcome=outcome,
            lens=lens,
            prior_prediction=prior_prediction,
            prior_confidence=prior_confidence,
            posterior_prediction=posterior_prediction,
            posterior_confidence=posterior_confidence,
            prediction_delta=prediction_delta,
            salient_percepts=salient_percepts or [],
            human_response=human_response,
            delta=delta,
            content=content,
            traces=[current],
            embedding_model=embedding_model,
            embedding_situation=emb_situation,
            embedding_artifact=emb_artifact,
            embedding_stimulus=emb_stimulus,
            embedding_response=emb_response,
            embedding_salience=emb_salience,
        )
        _store_chunk_no_commit(conn, chunk)
        conn.commit()
        return chunk
    except Exception:
        conn.rollback()
        raise


def _default_embed(conn: sqlite3.Connection):
    """Return an embed function that uses memory_indexer.try_embed with caching."""
    try:
        from projects.POC.scripts.memory_indexer import try_embed, detect_provider
        provider, model = detect_provider()

        def _embed(text: str) -> list[float] | None:
            return try_embed(text, conn=conn, provider=provider, model=model)
        return _embed
    except Exception:
        _log.warning('memory_indexer unavailable, embeddings disabled', exc_info=True)
        return lambda text: None


# ── Serialization ────────────────────────────────────────────────────────────

def serialize_chunks_for_prompt(
    chunks: list[MemoryChunk], token_budget: int = 5000,
) -> str:
    """Serialize retrieved chunks to Markdown for the proxy's LLM prompt.

    Approximate token budget: ~4 chars per token. Chunks are serialized in
    order (highest-scoring first) until the budget is exhausted.
    """
    if not chunks:
        return ''

    char_budget = token_budget * 4
    parts = ['--- RETRIEVED MEMORIES ---']
    used = len(parts[0])

    for chunk in chunks:
        lines = [f'### Memory {chunk.id[:8]}']
        lines.append(f'**Context:** {chunk.state} | {chunk.task_type} | outcome={chunk.outcome}')
        if chunk.prior_prediction:
            lines.append(
                f'**Prior:** {chunk.prior_prediction} '
                f'(confidence {chunk.prior_confidence:.2f})'
            )
        if chunk.posterior_prediction:
            lines.append(
                f'**Posterior:** {chunk.posterior_prediction} '
                f'(confidence {chunk.posterior_confidence:.2f})'
            )
        if chunk.prediction_delta:
            lines.append(f'**Delta:** {chunk.prediction_delta}')
        if chunk.human_response:
            lines.append(f'**Human said:** {chunk.human_response}')
        if chunk.delta:
            lines.append(f'**Proxy error:** {chunk.delta}')
        lines.append('')  # blank line between chunks

        block = '\n'.join(lines)
        if used + len(block) > char_budget:
            break
        parts.append(block)
        used += len(block)

    return '\n'.join(parts)


# ── DB path resolution ───────────────────────────────────────────────────────

def resolve_memory_db_path(proxy_model_path: str, team: str = '') -> str:
    """Resolve the proxy memory DB path, following the same convention as
    resolve_team_model_path for .proxy-confidence.json."""
    project_dir = os.path.dirname(proxy_model_path)
    if team:
        return os.path.join(project_dir, f'.proxy-memory-{team}.db')
    return os.path.join(project_dir, '.proxy-memory.db')


def memory_depth(conn: sqlite3.Connection) -> int:
    """Count distinct (state, task_type) pairs in the memory store.

    Used as the cold-start guard: a proxy with chunks spanning multiple
    states and task types has broader experience than one with many chunks
    all from the same context.  Returns 0 for an empty store.
    """
    row = conn.execute(
        'SELECT COUNT(DISTINCT state || \':\' || task_type) FROM proxy_chunks'
    ).fetchone()
    return row[0] if row else 0
