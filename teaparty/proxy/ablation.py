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

import json
import logging
import sqlite3
from dataclasses import dataclass, field

from teaparty.proxy.memory import (
    ACTIVATION_WEIGHT,
    DECAY,
    NOISE_SCALE,
    RETRIEVAL_THRESHOLD,
    SEMANTIC_WEIGHT,
    TOTAL_EMBEDDING_DIMENSIONS,
    MemoryChunk,
    base_level_activation,
    blended_text_from_fields,
    composite_score,
    cosine_similarity,
    single_composite_score,
    query_chunks,
    get_interaction_counter,
    _embed_to_json,
)

_log = logging.getLogger('teaparty.proxy.ablation')

ABLATION_THRESHOLD = 0.95


# ── Blended text ────────────────────────────────────────────────────────────

def blended_text(chunk: MemoryChunk) -> str:
    """Concatenate available chunk fields into a single string for embedding.

    Delegates to blended_text_from_fields() which is the single source of
    truth for which fields contribute to the blended embedding.
    """
    return blended_text_from_fields(
        state=chunk.state,
        task_type=chunk.task_type,
        content=chunk.content,
        human_response=chunk.human_response,
        prediction_delta=chunk.prediction_delta,
    )


# ── Retrieval under each configuration ──────────────────────────────────────

def _retrieve_multi_dim(
    candidates: list[MemoryChunk],
    context_embeddings: dict[str, list[float]],
    current_interaction: int,
    top_k: int,
    tau: float = RETRIEVAL_THRESHOLD,
) -> list[str]:
    """Retrieve top-k chunk IDs using multi-dimensional scoring (Config A)."""
    scored = []
    for chunk in candidates:
        score = composite_score(
            chunk, context_embeddings, current_interaction,
            s=0.0, tau=tau,  # no noise for deterministic comparison
        )
        scored.append((score, chunk.id))
    scored.sort(key=lambda x: -x[0])
    return [cid for _, cid in scored[:top_k]]


def _retrieve_single(
    candidates: list[MemoryChunk],
    context_blended: list[float],
    current_interaction: int,
    top_k: int,
    tau: float = RETRIEVAL_THRESHOLD,
) -> list[str]:
    """Retrieve top-k chunk IDs using single blended scoring (Config B)."""
    scored = []
    for chunk in candidates:
        score = single_composite_score(
            chunk, context_blended, current_interaction,
            s=0.0, tau=tau,  # no noise for deterministic comparison
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
                top_k, tau=tau,
            )
            single_ids = _retrieve_single(
                survivors, context_blended, current_interaction,
                top_k, tau=tau,
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


# ── Populate blended embeddings ─────────────────────────────────────────────

def populate_blended_embeddings(conn: sqlite3.Connection) -> int:
    """Compute and store blended embeddings for chunks that lack them.

    Uses the same embedding infrastructure as record_interaction().
    Returns the number of chunks updated.
    """
    from teaparty.proxy.memory import _default_embed

    all_chunks = query_chunks(conn)
    missing = [c for c in all_chunks if c.embedding_blended is None]
    if not missing:
        return 0

    embed_fn = _default_embed(conn)
    updated = 0
    for chunk in missing:
        text = blended_text(chunk)
        if not text.strip():
            continue
        vec = embed_fn(text)
        if vec is None:
            continue
        conn.execute(
            'UPDATE proxy_chunks SET embedding_blended=? WHERE id=?',
            (_embed_to_json(vec), chunk.id),
        )
        updated += 1

    conn.commit()
    _log.info('Populated blended embeddings for %d/%d chunks', updated, len(missing))
    return updated


# ── Report generation ───────────────────────────────────────────────────────

def generate_ablation_report(result: EmbeddingAblationResult) -> str:
    """Generate a human-readable text report from ablation results."""
    lines = [
        '# Embedding Ablation: Multi-Dimensional vs Single Blended',
        '',
        '## Configuration',
        'A (current): 5 independent embeddings, cosine avg / 5',
        'B (ablation): 1 blended embedding, single cosine similarity',
        f'Threshold: {ABLATION_THRESHOLD:.0%} retrieval overlap',
        '',
        '## Overall Result',
        f'Retrieval overlap: {result.overall_retrieval_overlap:.1%}',
        f'Threshold met: {result.threshold_met}',
        f'Recommendation: **{result.recommendation}**',
    ]

    if result.per_context:
        lines.extend(['', '## Per-Context Breakdown'])
        for ctx in result.per_context:
            lines.append(
                f'  {ctx.state} x {ctx.task_type}: '
                f'{ctx.mean_overlap:.1%} overlap '
                f'({ctx.n_interactions} interactions, '
                f'{len(ctx.divergent_chunks)} divergent)'
            )

    lines.extend([
        '',
        '## Notes',
        '- Retrieval overlap is a proxy for action match rate (LLM cannot be re-run offline)',
        '- Noise disabled (s=0) for deterministic comparison',
        '- Blended text uses content field as proxy for artifact_text/stimulus_text',
    ])

    return '\n'.join(lines)
