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
TOTAL_EMBEDDING_DIMENSIONS = 5  # All dimensions including salience (storage)

# Experience dimensions — used for composite scoring (issue #227)
EXPERIENCE_EMBEDDING_DIMENSIONS = 4
EXPERIENCE_DIMS = ('situation', 'artifact', 'stimulus', 'response')

# All embedding dimension names (including salience — used for storage)
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
    embedding_blended: list[float] | None = None


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
    embedding_salience TEXT,
    embedding_blended TEXT
);

CREATE TABLE IF NOT EXISTS proxy_state (
    key TEXT PRIMARY KEY,
    value INTEGER NOT NULL
);
INSERT OR IGNORE INTO proxy_state (key, value) VALUES ('interaction_counter', 0);

CREATE TABLE IF NOT EXISTS proxy_accuracy (
    state TEXT NOT NULL,
    task_type TEXT NOT NULL,
    prior_correct INTEGER DEFAULT 0,
    prior_total INTEGER DEFAULT 0,
    posterior_correct INTEGER DEFAULT 0,
    posterior_total INTEGER DEFAULT 0,
    last_updated TEXT,
    PRIMARY KEY (state, task_type)
);

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
    # Migration: add embedding_blended column for existing DBs (issue #222)
    try:
        conn.execute('ALTER TABLE proxy_chunks ADD COLUMN embedding_blended TEXT')
        conn.commit()
    except sqlite3.OperationalError:
        pass  # column already exists
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
            embedding_stimulus, embedding_response, embedding_salience,
            embedding_blended)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
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
            _embed_to_json(chunk.embedding_blended),
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
        embedding_blended=_json_to_embed(row['embedding_blended']),
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

    Cosine similarities are summed across the 4 experience dimensions
    (situation, artifact, stimulus, response) and divided by
    EXPERIENCE_EMBEDDING_DIMENSIONS (4).  Salience is excluded from
    composite scoring and retrieved independently (issue #227).
    """
    b = base_level_activation(chunk.traces, current_interaction, d)
    b_norm = normalize_activation(b, b_min, b_max)

    # Experience dimensions only — salience is retrieved separately (#227)
    dim_map = {
        'situation': chunk.embedding_situation,
        'artifact': chunk.embedding_artifact,
        'stimulus': chunk.embedding_stimulus,
        'response': chunk.embedding_response,
    }
    sim_sum = 0.0
    for dim, context_vec in context_embeddings.items():
        chunk_vec = dim_map.get(dim)
        if chunk_vec and context_vec:
            try:
                sim_sum += cosine_similarity(chunk_vec, context_vec)
            except ValueError:
                _log.debug('Skipping dim %s: vector length mismatch', dim)
    sem = sim_sum / EXPERIENCE_EMBEDDING_DIMENSIONS

    noise = logistic_noise(s)
    return activation_weight * b_norm + semantic_weight * sem + noise


def single_composite_score(
    chunk: MemoryChunk,
    context_blended: list[float],
    current_interaction: int,
    b_min: float,
    b_max: float,
    activation_weight: float = ACTIVATION_WEIGHT,
    semantic_weight: float = SEMANTIC_WEIGHT,
    d: float = DECAY,
    s: float = NOISE_SCALE,
) -> float:
    """Composite score using a single blended embedding instead of 5.

    Same structure as composite_score() but replaces the multi-dimensional
    cosine average with a single cosine similarity on blended embeddings.
    This is the Configuration B scoring function for the embedding ablation
    (issue #222).
    """
    b = base_level_activation(chunk.traces, current_interaction, d)
    b_norm = normalize_activation(b, b_min, b_max)

    sem = 0.0
    if chunk.embedding_blended and context_blended:
        try:
            sem = cosine_similarity(chunk.embedding_blended, context_blended)
        except ValueError:
            _log.debug('Skipping blended: vector length mismatch')

    noise = logistic_noise(s)
    return activation_weight * b_norm + semantic_weight * sem + noise


# ── Retrieval ────────────────────────────────────────────────────────────────

def retrieve_chunks(
    conn: sqlite3.Connection,
    *,
    state: str = '',
    task_type: str = '',
    context_embeddings: dict[str, list[float]] | None = None,
    context_blended: list[float] | None = None,
    scoring: str = 'multi_dim',
    current_interaction: int = 0,
    tau: float = RETRIEVAL_THRESHOLD,
    top_k: int = 10,
    d: float = DECAY,
    s: float = NOISE_SCALE,
    activation_weight: float = ACTIVATION_WEIGHT,
    semantic_weight: float = SEMANTIC_WEIGHT,
) -> list[MemoryChunk]:
    """Two-stage retrieval: activation filter, then composite ranking.

    scoring='multi_dim' (default): uses 5 independent embeddings via composite_score().
        Requires context_embeddings dict mapping dimension names to vectors.
    scoring='single': uses 1 blended embedding via single_composite_score().
        Requires context_blended vector. This is Configuration B for the
        embedding ablation (issue #222).
    """
    if scoring not in ('multi_dim', 'single'):
        raise ValueError(f"scoring must be 'multi_dim' or 'single', got {scoring!r}")

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
        if scoring == 'single':
            score = single_composite_score(
                chunk, context_blended or [], current_interaction,
                b_min, b_max,
                activation_weight=activation_weight,
                semantic_weight=semantic_weight,
                d=d, s=s,
            )
        else:
            score = composite_score(
                chunk, context_embeddings, current_interaction,
                b_min, b_max,
                activation_weight=activation_weight,
                semantic_weight=semantic_weight,
                d=d, s=s,
            )
        scored.append((score, chunk))
    scored.sort(key=lambda x: -x[0])
    return [chunk for _, chunk in scored[:top_k]]


def retrieve_most_recent_n(
    conn: sqlite3.Connection,
    n: int = 10,
    *,
    state: str = '',
    task_type: str = '',
) -> list[MemoryChunk]:
    """Most-recent-N retrieval: return N chunks ordered by latest trace.

    No activation computation, no embeddings, no threshold — pure recency.
    This is Configuration B for the ACT-R decay vs. recency ablation (#223).
    """
    candidates = query_chunks(conn, state=state, task_type=task_type)
    if not candidates:
        return []
    candidates.sort(key=lambda c: max(c.traces) if c.traces else 0, reverse=True)
    return candidates[:n]


def retrieve_salience(
    conn: sqlite3.Connection,
    *,
    context_embedding: list[float],
    current_interaction: int = 0,
    tau: float = RETRIEVAL_THRESHOLD,
    top_k: int = 5,
    d: float = DECAY,
) -> list[MemoryChunk]:
    """Retrieve chunks by salience embedding similarity.

    Independent retrieval path for the learned attention model (issue #227).
    Returns only chunks with non-null salience embeddings, ranked by
    cosine similarity between the chunk's salience embedding and the
    provided context embedding.  Activation filtering still applies.
    """
    rows = conn.execute(
        'SELECT * FROM proxy_chunks WHERE embedding_salience IS NOT NULL',
    ).fetchall()
    candidates = [_row_to_chunk(r) for r in rows]

    # Stage 1: filter by raw activation
    survivors: list[tuple[float, MemoryChunk]] = []
    for c in candidates:
        if not c.embedding_salience:
            continue
        b = base_level_activation(c.traces, current_interaction, d)
        if b > tau:
            survivors.append((b, c))

    if not survivors:
        return []

    # Stage 2: rank by cosine similarity to the salience query
    scored: list[tuple[float, MemoryChunk]] = []
    for _, chunk in survivors:
        try:
            sim = cosine_similarity(chunk.embedding_salience, context_embedding)  # type: ignore[arg-type]
        except ValueError:
            continue
        scored.append((sim, chunk))

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


# ── Ablation ──────────────────────────────────────────────────────────────────

ABLATION_CONFIGS = {
    'composite': {'activation_weight': 0.5, 'semantic_weight': 0.5},
    'activation_only': {'activation_weight': 1.0, 'semantic_weight': 0.0},
    'similarity_only': {'activation_weight': 0.0, 'semantic_weight': 1.0},
}


@dataclass
class AblationCheckpoint:
    """Results for one configuration at one checkpoint."""
    config: str
    checkpoint: int           # interaction count at evaluation
    matches: int              # retrieved outcomes matching held-out outcome
    total: int                # total held-out chunks evaluated
    match_rate: float         # matches / total (0.0 if total == 0)
    survivors_avg: float      # average chunks surviving activation filter


@dataclass
class AblationResult:
    """Full ablation results across configs and checkpoints."""
    checkpoints: dict[int, dict[str, AblationCheckpoint]]

    def summary(self) -> str:
        """Human-readable summary comparing configs at each checkpoint."""
        lines = ['## Scoring Ablation Results', '']
        for cp in sorted(self.checkpoints):
            lines.append(f'### After {cp} interactions')
            lines.append('| Config | Match Rate | Matches/Total | Avg Survivors |')
            lines.append('|--------|-----------|---------------|---------------|')
            for name in ('composite', 'activation_only', 'similarity_only'):
                r = self.checkpoints[cp].get(name)
                if r:
                    lines.append(
                        f'| {name} | {r.match_rate:.3f} | {r.matches}/{r.total} '
                        f'| {r.survivors_avg:.1f} |'
                    )
            lines.append('')
        return '\n'.join(lines)


def run_scoring_ablation(
    conn: sqlite3.Connection,
    *,
    checkpoints: list[int] | None = None,
    tau: float = RETRIEVAL_THRESHOLD,
    top_k: int = 10,
    d: float = DECAY,
) -> AblationResult:
    """Run the composite vs. activation-only vs. similarity-only ablation.

    Performs leave-one-out evaluation: for each chunk in chronological order,
    holds it out, retrieves from all prior chunks under each weight config,
    and checks whether the majority outcome among retrieved chunks matches
    the held-out chunk's actual outcome. This is a retrieval relevance
    proxy for action match rate (the true metric requires re-running the LLM).

    Evaluates at the specified checkpoints (interaction counts). If None,
    evaluates at all chunks. Noise is disabled (s=0.0) for determinism.

    Returns an AblationResult with per-config, per-checkpoint metrics.
    """
    all_chunks = query_chunks(conn)
    if not all_chunks:
        return AblationResult(checkpoints={})

    # Sort chronologically by first trace
    all_chunks.sort(key=lambda c: min(c.traces) if c.traces else 0)

    if checkpoints is None:
        checkpoints = [len(all_chunks)]

    result_checkpoints: dict[int, dict[str, AblationCheckpoint]] = {}

    for cp in checkpoints:
        eval_chunks = all_chunks[:cp]
        if len(eval_chunks) < 2:
            continue

        config_results: dict[str, AblationCheckpoint] = {}
        for config_name, weights in ABLATION_CONFIGS.items():
            matches = 0
            total = 0
            survivor_counts: list[int] = []

            for i, held_out in enumerate(eval_chunks):
                if i == 0:
                    continue  # need at least one prior chunk

                prior_chunks = eval_chunks[:i]
                held_out_interaction = min(held_out.traces) if held_out.traces else i

                # Build context embeddings from the held-out chunk's experience
                # dimensions only — salience is retrieved independently (#227)
                context_embeddings: dict[str, list[float]] = {}
                if held_out.embedding_situation:
                    context_embeddings['situation'] = held_out.embedding_situation
                if held_out.embedding_artifact:
                    context_embeddings['artifact'] = held_out.embedding_artifact
                if held_out.embedding_stimulus:
                    context_embeddings['stimulus'] = held_out.embedding_stimulus
                if held_out.embedding_response:
                    context_embeddings['response'] = held_out.embedding_response

                # Run retrieval on prior chunks only
                retrieved = _retrieve_from_chunks(
                    prior_chunks,
                    context_embeddings=context_embeddings,
                    current_interaction=held_out_interaction,
                    tau=tau,
                    top_k=top_k,
                    d=d,
                    **weights,
                )

                survivor_counts.append(len(retrieved))

                if not retrieved:
                    continue

                # Majority outcome among retrieved chunks
                outcome_counts: dict[str, int] = {}
                for rc in retrieved:
                    outcome_counts[rc.outcome] = outcome_counts.get(rc.outcome, 0) + 1
                majority_outcome = max(outcome_counts, key=outcome_counts.get)  # type: ignore[arg-type]

                total += 1
                if majority_outcome == held_out.outcome:
                    matches += 1

            match_rate = matches / total if total > 0 else 0.0
            survivors_avg = (
                sum(survivor_counts) / len(survivor_counts)
                if survivor_counts else 0.0
            )

            config_results[config_name] = AblationCheckpoint(
                config=config_name,
                checkpoint=cp,
                matches=matches,
                total=total,
                match_rate=match_rate,
                survivors_avg=survivors_avg,
            )

        result_checkpoints[cp] = config_results

    return AblationResult(checkpoints=result_checkpoints)


def _retrieve_from_chunks(
    chunks: list[MemoryChunk],
    *,
    context_embeddings: dict[str, list[float]] | None = None,
    current_interaction: int = 0,
    tau: float = RETRIEVAL_THRESHOLD,
    top_k: int = 10,
    d: float = DECAY,
    activation_weight: float = ACTIVATION_WEIGHT,
    semantic_weight: float = SEMANTIC_WEIGHT,
) -> list[MemoryChunk]:
    """Retrieve from an in-memory list of chunks (no DB query).

    Same two-stage logic as retrieve_chunks but operates on a provided
    list rather than querying the database. Used by the ablation harness
    to evaluate retrieval on a subset of chunks (leave-one-out).
    """
    context_embeddings = context_embeddings or {}

    survivors: list[tuple[float, MemoryChunk]] = []
    for c in chunks:
        b = base_level_activation(c.traces, current_interaction, d)
        if b > tau:
            survivors.append((b, c))

    if not survivors:
        return []

    activations = [b for b, _ in survivors]
    b_min = min(activations)
    b_max = max(activations)

    scored = []
    for _, chunk in survivors:
        score = composite_score(
            chunk, context_embeddings, current_interaction,
            b_min, b_max,
            activation_weight=activation_weight,
            semantic_weight=semantic_weight,
            d=d, s=0.0,
        )
        scored.append((score, chunk))
    scored.sort(key=lambda x: -x[0])
    return [chunk for _, chunk in scored[:top_k]]


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

    # Blended embedding: single embedding from concatenated text (issue #222)
    blended_str = blended_text_from_fields(
        state=state, task_type=task_type, content=content,
        human_response=human_response, prediction_delta=prediction_delta,
    )
    emb_blended = _embed(blended_str) if blended_str else None

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
            embedding_blended=emb_blended,
        )
        _store_chunk_no_commit(conn, chunk)
        _update_accuracy_no_commit(
            conn, state, task_type, outcome,
            prior_prediction, posterior_prediction,
        )
        conn.commit()
        return chunk
    except Exception:
        conn.rollback()
        raise


def _update_accuracy_no_commit(
    conn: sqlite3.Connection,
    state: str,
    task_type: str,
    outcome: str,
    prior_prediction: str,
    posterior_prediction: str,
) -> None:
    """Update per-context accuracy counts inside an existing transaction.

    Only counts predictions that are non-empty — empty predictions
    (cold start, agent failure) are excluded from totals.
    """
    has_prior = bool(prior_prediction)
    has_posterior = bool(posterior_prediction)
    if not has_prior and not has_posterior:
        return

    prior_correct_inc = int(has_prior and prior_prediction == outcome)
    prior_total_inc = int(has_prior)
    posterior_correct_inc = int(has_posterior and posterior_prediction == outcome)
    posterior_total_inc = int(has_posterior)

    conn.execute(
        """INSERT INTO proxy_accuracy (state, task_type,
               prior_correct, prior_total, posterior_correct, posterior_total,
               last_updated)
           VALUES (?, ?, ?, ?, ?, ?, datetime('now'))
           ON CONFLICT(state, task_type) DO UPDATE SET
               prior_correct = prior_correct + excluded.prior_correct,
               prior_total = prior_total + excluded.prior_total,
               posterior_correct = posterior_correct + excluded.posterior_correct,
               posterior_total = posterior_total + excluded.posterior_total,
               last_updated = excluded.last_updated""",
        (state, task_type,
         prior_correct_inc, prior_total_inc,
         posterior_correct_inc, posterior_total_inc),
    )


def get_accuracy(
    conn: sqlite3.Connection,
    *,
    state: str,
    task_type: str,
) -> dict[str, Any] | None:
    """Query prediction accuracy for a specific (state, task_type) context.

    Returns a dict with prior_correct, prior_total, posterior_correct,
    posterior_total, last_updated — or None if no data exists.
    """
    row = conn.execute(
        """SELECT prior_correct, prior_total, posterior_correct, posterior_total,
                  last_updated
           FROM proxy_accuracy WHERE state = ? AND task_type = ?""",
        (state, task_type),
    ).fetchone()
    if not row:
        return None
    return {
        'prior_correct': row[0],
        'prior_total': row[1],
        'posterior_correct': row[2],
        'posterior_total': row[3],
        'last_updated': row[4],
    }


def blended_text_from_fields(
    state: str = '',
    task_type: str = '',
    content: str = '',
    human_response: str = '',
    prediction_delta: str = '',
) -> str:
    """Concatenate available text fields into a single string for blended embedding.

    This is the single source of truth for which fields contribute to the
    blended embedding. Used by record_interaction() and proxy_ablation.blended_text().

    Note: artifact_text and stimulus_text are not stored in the chunk — only
    their per-dimension embeddings survive. The content field is the closest
    available proxy.
    """
    parts = []
    if state:
        parts.append(state)
    if task_type:
        parts.append(task_type)
    if content:
        parts.append(content)
    if human_response:
        parts.append(human_response)
    if prediction_delta:
        parts.append(prediction_delta)
    return ' '.join(parts)


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
    chunks: list[MemoryChunk],
    token_budget: int = 5000,
    salience_chunks: list[MemoryChunk] | None = None,
    salience_token_budget: int = 2000,
) -> str:
    """Serialize retrieved chunks to Markdown for the proxy's LLM prompt.

    Experience chunks and salience chunks are rendered as separate sections
    (issue #227).  Approximate token budget: ~4 chars per token.
    """
    parts: list[str] = []

    # Experience section
    if chunks:
        parts.append(_serialize_section(
            chunks,
            '## Your relevant experience with this human',
            token_budget,
        ))

    # Salience section (independent attention retrieval, issue #227)
    if salience_chunks:
        parts.append(_serialize_section(
            salience_chunks,
            '## What has surprised you in similar situations',
            salience_token_budget,
        ))

    return '\n\n'.join(parts)


def _serialize_section(
    chunks: list[MemoryChunk], heading: str, token_budget: int,
) -> str:
    """Serialize a list of chunks under a heading within a token budget."""
    char_budget = token_budget * 4
    parts = [heading]
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


# ── Contradiction detection (issue #228) ────────────────────────────────────


@dataclass
class ConflictClassification:
    """Result of classifying a conflicting memory pair."""
    chunk_a_id: str
    chunk_b_id: str
    cause: str      # preference_drift, context_sensitivity, genuine_tension, retrieval_noise
    action: str     # human-readable recommended action
    newer_id: str = ''  # which chunk is newer (for preference_drift)


# Recency gap threshold: if the newest trace of one chunk is this many
# interactions older than the other, classify as preference_drift.
_RECENCY_GAP_THRESHOLD = 8

# Confidence threshold for genuine_tension: both chunks must have
# posterior_confidence above this to qualify.
_TENSION_CONFIDENCE_THRESHOLD = 0.75

# Maximum age (in interactions) for a chunk to be considered "recent".
_RECENT_WINDOW = 10


def find_conflicting_pairs(
    chunks: list[MemoryChunk],
) -> list[tuple[MemoryChunk, MemoryChunk]]:
    """Identify candidate conflicting pairs from retrieved chunks.

    A pair is a candidate conflict when both chunks share the same
    (state, task_type) but have different outcomes.  This is a cheap
    heuristic pre-filter — no LLM call required.

    The chunk list is NOT modified (read-only).
    """
    pairs: list[tuple[MemoryChunk, MemoryChunk]] = []
    for i in range(len(chunks)):
        for j in range(i + 1, len(chunks)):
            a, b = chunks[i], chunks[j]
            if a.state == b.state and a.task_type == b.task_type and a.outcome != b.outcome:
                pairs.append((a, b))
    return pairs


def classify_conflict(
    chunk_a: MemoryChunk,
    chunk_b: MemoryChunk,
    current_interaction: int = 0,
) -> ConflictClassification:
    """Classify a conflicting pair by cause.

    Uses heuristic signals from chunk metadata — no LLM call.

    Classification rules (applied in order):
    1. Retrieval noise: if chunks have no traces (shouldn't happen), noise.
    2. Preference drift: large recency gap + same context domain.
    3. Genuine tension: both recent + both high confidence.
    4. Default: context_sensitivity (preserve both — safest default).
    """
    a_newest = max(chunk_a.traces) if chunk_a.traces else 0
    b_newest = max(chunk_b.traces) if chunk_b.traces else 0
    recency_gap = abs(a_newest - b_newest)

    # Determine which is newer
    if a_newest >= b_newest:
        newer, older = chunk_a, chunk_b
        newer_newest, older_newest = a_newest, b_newest
    else:
        newer, older = chunk_b, chunk_a
        newer_newest, older_newest = b_newest, a_newest

    # Rule 1: retrieval noise — no traces at all
    if not chunk_a.traces or not chunk_b.traces:
        return ConflictClassification(
            chunk_a_id=chunk_a.id, chunk_b_id=chunk_b.id,
            cause='retrieval_noise',
            action='Discard the weaker match; insufficient trace data.',
        )

    # Rule 2: preference drift — large recency gap
    if recency_gap >= _RECENCY_GAP_THRESHOLD:
        return ConflictClassification(
            chunk_a_id=chunk_a.id, chunk_b_id=chunk_b.id,
            cause='preference_drift',
            action=f'Prefer newer memory ({newer.id}); schedule older for demotion.',
            newer_id=newer.id,
        )

    # Rule 3: genuine tension — both recent, both high confidence
    a_recent = (current_interaction - a_newest) <= _RECENT_WINDOW
    b_recent = (current_interaction - b_newest) <= _RECENT_WINDOW
    a_confident = chunk_a.posterior_confidence >= _TENSION_CONFIDENCE_THRESHOLD
    b_confident = chunk_b.posterior_confidence >= _TENSION_CONFIDENCE_THRESHOLD
    if a_recent and b_recent and a_confident and b_confident:
        return ConflictClassification(
            chunk_a_id=chunk_a.id, chunk_b_id=chunk_b.id,
            cause='genuine_tension',
            action='Escalate to human — unresolved tension in preferences.',
        )

    # Default: context_sensitivity — preserve both with scope annotations
    return ConflictClassification(
        chunk_a_id=chunk_a.id, chunk_b_id=chunk_b.id,
        cause='context_sensitivity',
        action='Preserve both memories with scope annotations; use both in reasoning.',
    )


def format_conflict_context(
    classifications: list[ConflictClassification],
    *,
    llm_fallback_count: int = 0,
) -> str:
    """Render conflict classifications as prompt text for the proxy agent.

    Returns empty string when no conflicts exist (zero overhead fast path).
    When llm_fallback_count > 0, appends a note that some classifications
    used heuristic-only mode due to LLM failures (#238).
    """
    if not classifications:
        return ''

    lines = ['## Memory Conflicts Detected', '']
    for i, cls in enumerate(classifications, 1):
        lines.append(f'**Conflict {i}:** {cls.cause.replace("_", " ")}')
        lines.append(f'  Chunks: {cls.chunk_a_id[:8]} vs {cls.chunk_b_id[:8]}')
        lines.append(f'  Recommended action: {cls.action}')
        lines.append('')

    if llm_fallback_count > 0:
        lines.append(
            f'**Note:** {llm_fallback_count} conflict(s) classified by heuristic only '
            f'(LLM classifier unavailable).'
        )
        lines.append('')

    return '\n'.join(lines)


def has_genuine_tension(
    classifications: list[ConflictClassification],
) -> bool:
    """Return True if any classification is genuine_tension.

    Used by _calibrate_confidence() to cap confidence and force escalation.
    """
    return any(c.cause == 'genuine_tension' for c in classifications)


# ── Asymmetric confidence decay (Hindsight, arXiv:2512.12818) ────────────────

# Step size for confidence updates. Supporting = +α, weakening = -α,
# contradicting = -2α. Value chosen to be meaningful over ~10-20
# interactions but not so large that a single event dominates.
CONFIDENCE_ALPHA = 0.05


def apply_confidence_decay(
    confidence: float,
    evidence_type: str,
    alpha: float = CONFIDENCE_ALPHA,
) -> float:
    """Apply asymmetric confidence decay following Hindsight.

    Args:
        confidence: current confidence value in [0.0, 1.0]
        evidence_type: one of 'supporting', 'weakening', 'contradicting'
        alpha: step size (default CONFIDENCE_ALPHA)

    Returns:
        Updated confidence, clamped to [0.0, 1.0].

    The asymmetry: contradicting evidence reduces confidence by 2α,
    while supporting evidence increases by only α. This is consistent
    with the proxy's existing 3x correction asymmetry (EMA) and
    regret theory: false beliefs are more costly than missed reinforcements.
    """
    if evidence_type == 'supporting':
        return min(1.0, confidence + alpha)
    elif evidence_type == 'weakening':
        return max(0.0, confidence - alpha)
    elif evidence_type == 'contradicting':
        return max(0.0, confidence - 2 * alpha)
    else:
        return confidence


def consolidate_proxy_entries(
    chunks: list[MemoryChunk],
    current_interaction: int = 0,
) -> list[MemoryChunk]:
    """Apply ADD/UPDATE/DELETE/SKIP taxonomy to proxy ACT-R chunks.

    Post-session consolidation pass — separate from compact_entries().

    For each conflicting pair:
    - preference_drift → DELETE older (keep newer only)
    - context_sensitivity → keep both (ADD semantics)
    - genuine_tension → keep both (will be escalated at retrieval time)
    - retrieval_noise → keep both (let activation decay handle it)

    Non-conflicting entries are returned unchanged.
    """
    pairs = find_conflicting_pairs(chunks)
    if not pairs:
        return list(chunks)

    # Collect IDs to delete
    delete_ids: set[str] = set()
    for a, b in pairs:
        cls = classify_conflict(a, b, current_interaction=current_interaction)
        if cls.cause == 'preference_drift':
            # Delete the older chunk
            a_newest = max(a.traces) if a.traces else 0
            b_newest = max(b.traces) if b.traces else 0
            older_id = a.id if a_newest < b_newest else b.id
            delete_ids.add(older_id)

    return [c for c in chunks if c.id not in delete_ids]


# ── Proxy.md consolidation (issue #228 Stage 2) ─────────────────────────────

# Mem0 decision taxonomy
CONSOLIDATION_ADD = 'ADD'           # no conflict — keep new entry
CONSOLIDATION_UPDATE = 'UPDATE'     # complement existing — merge
CONSOLIDATION_DELETE = 'DELETE'     # new supersedes old — remove old
CONSOLIDATION_SKIP = 'SKIP'        # already represented — discard new


def _tokenize_content(text: str) -> set[str]:
    """Extract word tokens from text for similarity comparison."""
    import re as _re
    return set(_re.findall(r'[a-z0-9]+', text.lower()))


def _jaccard_similarity(a: set[str], b: set[str]) -> float:
    """Jaccard similarity between two token sets."""
    if not a and not b:
        return 1.0
    union = a | b
    if not union:
        return 0.0
    return len(a & b) / len(union)


def consolidate_proxy_file(
    entries: list,
    *,
    similarity_threshold: float = 0.4,
    classifier: Any = None,
) -> tuple[list, list[dict]]:
    """Consolidate proxy.md MemoryEntry objects using ADD/UPDATE/DELETE/SKIP.

    Stage 2 of issue #228: post-session write-time consolidation.

    1. Cluster entries by content similarity (O-Mem pattern).
    2. Within each cluster, identify conflicts:
       - If classifier is provided, use it (LLM-as-judge).
       - Otherwise, use heuristic: within a cluster, entries with
         substantially different content (low Jaccard despite being
         in the same cluster via embedding/topic) are conflict candidates.
    3. Apply taxonomy:
       - SKIP: entries whose content is already covered by another
       - DELETE: older entries superseded by newer ones (preference drift)
       - UPDATE: entries that complement each other (merge content)
       - ADD: entries with no conflict

    Args:
        entries: list of MemoryEntry objects from proxy.md
        similarity_threshold: Jaccard threshold for clustering (default 0.4,
            lower than compact_memory's 0.8 because we want to find
            topically related entries, not near-duplicates)
        classifier: optional callable(entry_a, entry_b) -> str returning
            one of ADD/UPDATE/DELETE/SKIP. When None, uses heuristic.

    Returns:
        (consolidated_entries, decisions) where decisions is a list of
        dicts recording each consolidation decision for auditability.
    """
    if len(entries) <= 1:
        return list(entries), []

    # Step 1: Tokenize all entries
    tokens = [_tokenize_content(e.content) for e in entries]
    n = len(entries)

    # Step 2: Single-linkage clustering by Jaccard similarity
    cluster_id = list(range(n))

    def _find(i: int) -> int:
        while cluster_id[i] != i:
            cluster_id[i] = cluster_id[cluster_id[i]]
            i = cluster_id[i]
        return i

    def _union(i: int, j: int) -> None:
        ri, rj = _find(i), _find(j)
        if ri != rj:
            cluster_id[ri] = rj

    for i in range(n):
        for j in range(i + 1, n):
            if _jaccard_similarity(tokens[i], tokens[j]) >= similarity_threshold:
                _union(i, j)

    # Group entries by cluster
    clusters: dict[int, list[int]] = {}
    for i in range(n):
        root = _find(i)
        clusters.setdefault(root, []).append(i)

    # Step 3: Within each multi-entry cluster, apply consolidation
    keep_indices: set[int] = set()
    decisions: list[dict] = []

    for root, members in clusters.items():
        if len(members) == 1:
            keep_indices.add(members[0])
            continue

        # Sort by created_at (newer last) for recency ordering
        members.sort(key=lambda i: entries[i].created_at)

        if classifier:
            # LLM-based classification
            for i_idx in range(len(members)):
                for j_idx in range(i_idx + 1, len(members)):
                    ei, ej = entries[members[i_idx]], entries[members[j_idx]]
                    decision = classifier(ei, ej)
                    decisions.append({
                        'entry_a': ei.id, 'entry_b': ej.id,
                        'decision': decision,
                    })
                    if decision == CONSOLIDATION_DELETE:
                        # DELETE the older (i < j, so i is older)
                        pass  # handled below
                    elif decision == CONSOLIDATION_SKIP:
                        # SKIP the newer (it's already represented)
                        pass
            # For LLM path, collect which to keep based on decisions
            deleted = set()
            skipped = set()
            for d in decisions:
                if d['decision'] == CONSOLIDATION_DELETE:
                    deleted.add(d['entry_a'])
                elif d['decision'] == CONSOLIDATION_SKIP:
                    skipped.add(d['entry_b'])
            for idx in members:
                if entries[idx].id not in deleted and entries[idx].id not in skipped:
                    keep_indices.add(idx)
        else:
            # Heuristic classification: within a cluster, use recency
            # to resolve conflicts. Keep the newest entry in each cluster
            # and any entries that are sufficiently different from each other.
            #
            # Default to context_sensitivity: preserve all entries unless
            # they are near-duplicates (high Jaccard, handled by standard
            # compaction) or clearly superseded (same topic, newer exists).
            #
            # Conservative: keep all members. The clustering itself is the
            # signal — entries that land in the same cluster are related.
            # Without an LLM, we can't reliably determine if they conflict
            # or complement each other. Err on the side of preservation.
            for idx in members:
                keep_indices.add(idx)
            decisions.append({
                'cluster': [entries[m].id for m in members],
                'decision': 'PRESERVE_ALL',
                'reason': 'Heuristic mode: cannot reliably classify without LLM',
            })

    return [entries[i] for i in sorted(keep_indices)], decisions


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
