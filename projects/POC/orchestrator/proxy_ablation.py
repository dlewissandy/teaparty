"""ACT-R Phase 1 ablation: multi-dimensional embeddings vs single blended embedding.

Compares retrieval quality under two scoring configurations:
- Configuration A (current): 5 independent embeddings per chunk, composite score
  averages cosine similarity across all dimensions (TOTAL_EMBEDDING_DIMENSIONS=5).
- Configuration B (ablation): 1 blended embedding per chunk from concatenated text,
  single cosine similarity.

The comparison uses leave-one-out retrieval: for each eligible chunk, retrieve from
the remaining chunks under both configurations and compare top-k overlap.

Go/no-go criterion (from act-r-proxy-memory.md): if single-embedding retrieval
achieves >= 95% of multi-dimensional retrieval's quality, the 5x embedding cost
is not justified. Since action match rate cannot be measured offline, retrieval
overlap at top-k is used as a proxy metric.

Theory: docs/detailed-design/act-r-proxy-memory.md
Sensorium: docs/detailed-design/act-r-proxy-sensorium.md
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field

from projects.POC.orchestrator.proxy_memory import (
    ACTIVATION_WEIGHT,
    DECAY,
    NOISE_SCALE,
    RETRIEVAL_THRESHOLD,
    SEMANTIC_WEIGHT,
    TOTAL_EMBEDDING_DIMENSIONS,
    MemoryChunk,
    base_level_activation,
    composite_score,
    cosine_similarity,
    normalize_activation,
    query_chunks,
    get_interaction_counter,
)

ABLATION_THRESHOLD = 0.95


# ── Blended text ────────────────────────────────────────────────────────────

def blended_text(chunk: MemoryChunk) -> str:
    """Concatenate available chunk fields into a single string for embedding.

    Uses all stored text fields that correspond to the 5 independent embedding
    dimensions: situation (state + task_type), content (proxy for artifact),
    stimulus (content also covers this), response (human_response), and
    salience (prediction_delta).

    Note: artifact_text and stimulus_text are not stored in the chunk — only
    their embeddings survive. The content field is the closest available proxy.
    """
    parts = []
    if chunk.state:
        parts.append(chunk.state)
    if chunk.task_type:
        parts.append(chunk.task_type)
    if chunk.content:
        parts.append(chunk.content)
    if chunk.human_response:
        parts.append(chunk.human_response)
    if chunk.prediction_delta:
        parts.append(chunk.prediction_delta)
    return ' '.join(parts)


# ── Single-embedding composite score ────────────────────────────────────────

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
    """
    from projects.POC.orchestrator.proxy_memory import logistic_noise

    b = base_level_activation(chunk.traces, current_interaction, d)
    b_norm = normalize_activation(b, b_min, b_max)

    sem = 0.0
    if chunk.embedding_blended and context_blended:
        try:
            sem = cosine_similarity(chunk.embedding_blended, context_blended)
        except ValueError:
            pass

    noise = logistic_noise(s)
    return activation_weight * b_norm + semantic_weight * sem + noise


# ── Retrieval under each configuration ──────────────────────────────────────

def _retrieve_multi_dim(
    candidates: list[MemoryChunk],
    context_embeddings: dict[str, list[float]],
    current_interaction: int,
    b_min: float,
    b_max: float,
    top_k: int,
) -> list[str]:
    """Retrieve top-k chunk IDs using multi-dimensional scoring (Config A)."""
    scored = []
    for chunk in candidates:
        score = composite_score(
            chunk, context_embeddings, current_interaction,
            b_min, b_max, s=0.0,  # no noise for deterministic comparison
        )
        scored.append((score, chunk.id))
    scored.sort(key=lambda x: -x[0])
    return [cid for _, cid in scored[:top_k]]


def _retrieve_single(
    candidates: list[MemoryChunk],
    context_blended: list[float],
    current_interaction: int,
    b_min: float,
    b_max: float,
    top_k: int,
) -> list[str]:
    """Retrieve top-k chunk IDs using single blended scoring (Config B)."""
    scored = []
    for chunk in candidates:
        score = single_composite_score(
            chunk, context_blended, current_interaction,
            b_min, b_max, s=0.0,  # no noise for deterministic comparison
        )
        scored.append((score, chunk.id))
    scored.sort(key=lambda x: -x[0])
    return [cid for _, cid in scored[:top_k]]


def _overlap_at_k(list_a: list[str], list_b: list[str]) -> float:
    """Fraction of items in list_a that also appear in list_b (set overlap)."""
    if not list_a:
        return 1.0  # vacuously true
    return len(set(list_a) & set(list_b)) / len(list_a)


# ── Result types ────────────────────────────────────────────────────────────

@dataclass
class AblationContextResult:
    """Ablation result for a single (state, task_type) context."""
    state: str
    task_type: str
    n_interactions: int
    mean_overlap: float
    divergent_chunks: list[str] = field(default_factory=list)


@dataclass
class EmbeddingAblationResult:
    """Full ablation comparison result."""
    overall_retrieval_overlap: float
    per_context: list[AblationContextResult]
    threshold_met: bool
    recommendation: str  # SIMPLIFY, KEEP_MULTI_DIM, or INSUFFICIENT


def apply_threshold(
    overall_overlap: float,
    threshold: float = ABLATION_THRESHOLD,
) -> EmbeddingAblationResult:
    """Apply the 95% threshold criterion to an overlap measurement."""
    met = overall_overlap >= threshold
    return EmbeddingAblationResult(
        overall_retrieval_overlap=overall_overlap,
        per_context=[],
        threshold_met=met,
        recommendation='SIMPLIFY' if met else 'KEEP_MULTI_DIM',
    )


# ── Main ablation runner ───────────────────────────────────────────────────

def run_embedding_ablation(
    conn: sqlite3.Connection,
    *,
    tau: float = RETRIEVAL_THRESHOLD,
    top_k: int = 10,
    d: float = DECAY,
) -> EmbeddingAblationResult:
    """Run the embedding ablation on all eligible chunks in the DB.

    For each eligible chunk (has human_response and posterior_prediction),
    uses leave-one-out: treats the chunk as the query, retrieves from
    remaining chunks under both configurations, and compares top-k overlap.

    Returns per-context breakdown and overall retrieval overlap.
    """
    current_interaction = get_interaction_counter(conn)
    all_chunks = query_chunks(conn)

    # Eligible chunks: human responded and posterior prediction exists
    eligible = [
        c for c in all_chunks
        if c.human_response and c.posterior_prediction
    ]

    if not eligible:
        return EmbeddingAblationResult(
            overall_retrieval_overlap=0.0,
            per_context=[],
            threshold_met=False,
            recommendation='INSUFFICIENT',
        )

    # Group by (state, task_type) for per-context breakdown
    context_groups: dict[tuple[str, str], list[MemoryChunk]] = {}
    for chunk in eligible:
        key = (chunk.state, chunk.task_type)
        context_groups.setdefault(key, []).append(chunk)

    per_context: list[AblationContextResult] = []
    all_overlaps: list[float] = []

    for (state, task_type), group_chunks in sorted(context_groups.items()):
        context_overlaps: list[float] = []
        divergent: list[str] = []

        for query_chunk in group_chunks:
            # Leave-one-out: exclude the query chunk from candidates
            candidates = [c for c in all_chunks if c.id != query_chunk.id]
            if not candidates:
                continue

            # Filter by activation threshold
            survivors = []
            for c in candidates:
                b = base_level_activation(c.traces, current_interaction, d)
                if b > tau:
                    survivors.append(c)
            if not survivors:
                continue

            # Compute activation range for normalization
            activations = [
                base_level_activation(c.traces, current_interaction, d)
                for c in survivors
            ]
            b_min = min(activations)
            b_max = max(activations)

            # Build context embeddings from the query chunk
            context_embeddings: dict[str, list[float]] = {}
            if query_chunk.embedding_situation:
                context_embeddings['situation'] = query_chunk.embedding_situation
            if query_chunk.embedding_artifact:
                context_embeddings['artifact'] = query_chunk.embedding_artifact
            if query_chunk.embedding_stimulus:
                context_embeddings['stimulus'] = query_chunk.embedding_stimulus
            if query_chunk.embedding_response:
                context_embeddings['response'] = query_chunk.embedding_response
            if query_chunk.embedding_salience:
                context_embeddings['salience'] = query_chunk.embedding_salience

            context_blended = query_chunk.embedding_blended or []

            # Retrieve under both configurations
            multi_dim_ids = _retrieve_multi_dim(
                survivors, context_embeddings, current_interaction,
                b_min, b_max, top_k,
            )
            single_ids = _retrieve_single(
                survivors, context_blended, current_interaction,
                b_min, b_max, top_k,
            )

            overlap = _overlap_at_k(multi_dim_ids, single_ids)
            context_overlaps.append(overlap)
            all_overlaps.append(overlap)

            if overlap < 1.0:
                divergent.append(query_chunk.id)

        mean_overlap = (
            sum(context_overlaps) / len(context_overlaps)
            if context_overlaps else 0.0
        )
        per_context.append(AblationContextResult(
            state=state,
            task_type=task_type,
            n_interactions=len(group_chunks),
            mean_overlap=mean_overlap,
            divergent_chunks=divergent,
        ))

    overall = (
        sum(all_overlaps) / len(all_overlaps)
        if all_overlaps else 0.0
    )
    threshold_met = overall >= ABLATION_THRESHOLD

    if threshold_met:
        recommendation = 'SIMPLIFY'
    else:
        recommendation = 'KEEP_MULTI_DIM'

    return EmbeddingAblationResult(
        overall_retrieval_overlap=overall,
        per_context=per_context,
        threshold_met=threshold_met,
        recommendation=recommendation,
    )
