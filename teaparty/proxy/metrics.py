"""ACT-R Phase 1 evaluation metrics for the human proxy.

Computes evaluation metrics from proxy_memory.db chunks:
1. Surprise calibration — surprise detection confirmed by human response
2. Retrieval relevance — inspectable retrieval sets with activation scores

Pre-583cccd8, this module also computed action_match_rate,
prior_calibration, and a go_no_go_assessment that depended on
categorical action comparisons.  The conversational-prompts migration
retired per-pass ACTION tokens — proxy responses are now free text
classified downstream via _classify_review, and the corresponding
chunk fields (prior_prediction, posterior_prediction) are no longer
populated.  Those metrics are removed; the calibration-stack revisit
in milestone-4 (#337) will define the replacement readiness criteria.

Theory: docs/systems/human-proxy/act-r/memory.md §Evaluation metrics
"""
from __future__ import annotations

import json
import math
import sqlite3
from dataclasses import dataclass, field

from teaparty.proxy.memory import (
    DECAY,
    NOISE_SCALE,
    RETRIEVAL_THRESHOLD,
    MemoryChunk,
    base_level_activation,
    get_interaction_counter,
    query_chunks,
    retrieve_chunks,
    retrieve_most_recent_n,
)


# ── Result types ─────────────────────────────────────────────────────────────

@dataclass
class SurpriseCalibrationResult:
    rate: float
    surprises: int
    confirmed: int


@dataclass
class RetrievalInspection:
    """One chunk's retrieval details for human review."""
    chunk_id: str
    state: str
    task_type: str
    outcome: str
    activation: float
    content_summary: str


@dataclass
class RetrievalRelevanceResult:
    """Retrieved memory set for a given context, ready for human inspection."""
    state: str
    task_type: str
    current_interaction: int
    retrievals: list[RetrievalInspection]
    total_candidates: int


# ── Metric functions ─────────────────────────────────────────────────────────

CONFIDENCE_SHIFT_THRESHOLD = 0.3


def surprise_calibration(conn: sqlite3.Connection) -> SurpriseCalibrationResult:
    """When surprise was detected, did the human respond?

    Surprise is detected when any of:
    - Confidence shifted > 0.3 (|posterior_confidence - prior_confidence|)
    - prediction_delta is non-empty (explicitly flagged by the proxy)
    - salient_percepts are populated (extracted from a shift)

    Confirmation means human_response is non-empty.

    The pre-583cccd8 design also counted "action changed
    (prior_prediction != posterior_prediction)" as a surprise signal, but
    the conversational-prompts migration retired categorical per-pass
    actions — proxy responses are now free text classified downstream
    from the final human/proxy answer via _classify_review.
    """
    rows = conn.execute(
        """SELECT prior_confidence, posterior_confidence,
                  prediction_delta, salient_percepts, human_response
           FROM proxy_chunks
           WHERE prior_confidence > 0 OR posterior_confidence > 0"""
    ).fetchall()

    surprises = 0
    confirmed = 0
    for r in rows:
        prior_conf = r[0] or 0.0
        posterior_conf = r[1] or 0.0
        delta_text = r[2] or ''
        percepts = r[3] or '[]'

        confidence_shifted = abs(posterior_conf - prior_conf) > CONFIDENCE_SHIFT_THRESHOLD
        has_delta = bool(delta_text)
        has_percepts = percepts not in ('[]', '')

        if confidence_shifted or has_delta or has_percepts:
            surprises += 1
            if r[4]:  # human_response non-empty
                confirmed += 1

    if surprises == 0:
        return SurpriseCalibrationResult(rate=0.0, surprises=0, confirmed=0)

    return SurpriseCalibrationResult(
        rate=confirmed / surprises,
        surprises=surprises,
        confirmed=confirmed,
    )


def retrieval_relevance(
    conn: sqlite3.Connection,
    *,
    state: str = '',
    task_type: str = '',
    current_interaction: int | None = None,
    tau: float = -0.5,
    d: float = DECAY,
) -> RetrievalRelevanceResult:
    """Inspect what chunks would be retrieved for a given context.

    Returns chunks that pass the activation threshold, sorted by activation
    score, with content summaries for human review. This supports the
    qualitative retrieval relevance assessment specified in the design.

    If current_interaction is not provided, reads it from the DB.
    """
    if current_interaction is None:
        row = conn.execute(
            "SELECT value FROM proxy_state WHERE key='interaction_counter'"
        ).fetchone()
        current_interaction = row[0] if row else 0

    candidates = query_chunks(conn, state=state, task_type=task_type)

    inspections: list[RetrievalInspection] = []
    for chunk in candidates:
        activation = base_level_activation(chunk.traces, current_interaction, d)
        if activation > tau:
            summary = chunk.content[:200] if chunk.content else ''
            inspections.append(RetrievalInspection(
                chunk_id=chunk.id,
                state=chunk.state,
                task_type=chunk.task_type,
                outcome=chunk.outcome,
                activation=activation,
                content_summary=summary,
            ))

    inspections.sort(key=lambda x: -x.activation)

    return RetrievalRelevanceResult(
        state=state,
        task_type=task_type,
        current_interaction=current_interaction,
        retrievals=inspections,
        total_candidates=len(candidates),
    )


# ── Report ───────────────────────────────────────────────────────────────────

def generate_report(conn: sqlite3.Connection) -> dict:
    """Aggregate all metrics into a structured report with text summary."""
    sc = surprise_calibration(conn)
    rr = retrieval_relevance(conn)

    lines = [
        '# ACT-R Phase 1 Evaluation Report',
        '',
        '## Surprise Calibration',
        f'Rate: {sc.rate:.1%} ({sc.confirmed}/{sc.surprises} surprise events)',
        '',
        '## Retrieval Relevance',
        f'Chunks passing activation threshold: {len(rr.retrievals)}/{rr.total_candidates}',
    ]

    if rr.retrievals:
        lines.append('')
        for ri in rr.retrievals[:10]:
            lines.append(
                f'  [{ri.chunk_id[:8]}] {ri.state} | {ri.task_type} | '
                f'{ri.outcome} | activation={ri.activation:.3f}'
            )
            if ri.content_summary:
                lines.append(f'    {ri.content_summary[:120]}')

    text = '\n'.join(lines)

    return {
        'surprise_calibration': sc,
        'retrieval_relevance': rr,
        'text': text,
    }


# ── Ablation: ACT-R decay vs. simple recency (#223) ────────────────────────

ABLATION_THRESHOLD = 0.95


@dataclass
class AblationEpoch:
    epoch: str
    overlap: float
    actr_match_rate: float
    recency_match_rate: float


@dataclass
class AblationResult:
    actr_ids: list[str]
    recency_ids: list[str]
    overlap: float
    actr_match_rate: float
    recency_match_rate: float
    recency_sufficient: bool
    epoch_breakdown: list[dict]


def _chunk_action_match(chunks: list[MemoryChunk]) -> float:
    """Fraction of chunks where posterior_prediction == outcome (eligible only)."""
    eligible = [c for c in chunks
                if c.human_response and c.posterior_prediction]
    if not eligible:
        return 0.0
    matched = sum(1 for c in eligible if c.posterior_prediction == c.outcome)
    return matched / len(eligible)


def _set_overlap(a: list[str], b: list[str]) -> float:
    """Jaccard overlap between two ID lists."""
    if not a and not b:
        return 1.0
    sa, sb = set(a), set(b)
    union = sa | sb
    if not union:
        return 1.0
    return len(sa & sb) / len(union)


def _rerank_by_composite(
    chunks: list[MemoryChunk],
    context_embeddings: dict[str, list[float]],
    current_interaction: int,
    activation_weight: float,
    semantic_weight: float,
    d: float,
    s: float,
) -> list[MemoryChunk]:
    """Re-rank chunks by composite score with given weights."""
    from teaparty.proxy.memory import composite_score as _cs
    if not chunks:
        return []
    scored = [
        (_cs(c, context_embeddings, current_interaction,
             activation_weight=activation_weight,
             semantic_weight=semantic_weight, d=d, s=s), c)
        for c in chunks
    ]
    scored.sort(key=lambda x: -x[0])
    return [c for _, c in scored]


def ablation_actr_vs_recency(
    conn: sqlite3.Connection,
    *,
    state: str = '',
    task_type: str = '',
    context_embeddings: dict[str, list[float]] | None = None,
    tau: float = RETRIEVAL_THRESHOLD,
    d: float = DECAY,
    s: float = 0.0,
    epoch_boundary: int | None = None,
) -> AblationResult:
    """Compare ACT-R activation retrieval vs. most-recent-N on the same data.

    Config A (current): activation filter (B > tau) then composite scoring
    with tanh(B − τ) activation as a component.
    Config B (ablation): most-recent-N candidate selection, then composite
    scoring with activation_weight=0 (semantic similarity + noise only).

    When context_embeddings is empty (offline evaluation), semantic similarity
    is 0 for both configs — Config A reduces to activation-only ranking,
    Config B to recency-only ranking. When embeddings are provided (online
    evaluation), Config B uses semantic similarity to re-rank the recency
    candidates.
    """
    context_embeddings = context_embeddings or {}
    current = get_interaction_counter(conn)

    # Config A: ACT-R two-stage retrieval (activation filter + composite)
    actr_chunks = retrieve_chunks(
        conn,
        state=state,
        task_type=task_type,
        context_embeddings=context_embeddings,
        current_interaction=current,
        tau=tau,
        top_k=9999,
        d=d,
        s=s,
    )
    n = len(actr_chunks)

    # Config B: most-recent-N selection, then composite with activation_weight=0
    recency_candidates = retrieve_most_recent_n(
        conn, n=n, state=state, task_type=task_type,
    )
    recency_chunks = _rerank_by_composite(
        recency_candidates, context_embeddings, current,
        activation_weight=0.0, semantic_weight=1.0, d=d, s=s,
    )

    actr_ids = [c.id for c in actr_chunks]
    recency_ids = [c.id for c in recency_chunks]

    overlap = _set_overlap(actr_ids, recency_ids)
    actr_mr = _chunk_action_match(actr_chunks)
    recency_mr = _chunk_action_match(recency_chunks)
    recency_sufficient = (
        recency_mr >= ABLATION_THRESHOLD * actr_mr if actr_mr > 0
        else True
    )

    # Epoch breakdown
    all_chunks = query_chunks(conn, state=state, task_type=task_type)
    epoch_breakdown = _compute_epoch_breakdown(
        all_chunks, current, context_embeddings, tau, d, s,
        epoch_boundary,
    )

    return AblationResult(
        actr_ids=actr_ids,
        recency_ids=recency_ids,
        overlap=overlap,
        actr_match_rate=actr_mr,
        recency_match_rate=recency_mr,
        recency_sufficient=recency_sufficient,
        epoch_breakdown=epoch_breakdown,
    )


def _compute_epoch_breakdown(
    chunks: list[MemoryChunk],
    current: int,
    context_embeddings: dict[str, list[float]],
    tau: float,
    d: float,
    s: float,
    epoch_boundary: int | None,
) -> list[dict]:
    """Split chunks into early/late epochs and compare configs per epoch."""
    if not chunks:
        return []

    # Determine boundary: use provided or median of min(traces) (creation time)
    creation_times = [min(c.traces) for c in chunks if c.traces]
    if not creation_times:
        return []

    if epoch_boundary is None:
        creation_times_sorted = sorted(creation_times)
        mid = len(creation_times_sorted) // 2
        epoch_boundary = creation_times_sorted[mid]

    early = [c for c in chunks if c.traces and min(c.traces) < epoch_boundary]
    late = [c for c in chunks if c.traces and min(c.traces) >= epoch_boundary]

    result = []
    for label, group in [('early', early), ('late', late)]:
        if not group:
            continue

        # Config A: filter by activation threshold, rank by composite
        actr_survivors = []
        for c in group:
            b = base_level_activation(c.traces, current, d)
            if b > tau:
                actr_survivors.append(c)

        n_epoch = len(actr_survivors)

        # Config B: recency selection, re-rank with activation_weight=0
        recency_candidates = sorted(
            group, key=lambda c: max(c.traces) if c.traces else 0, reverse=True,
        )[:n_epoch]
        recency_group = _rerank_by_composite(
            recency_candidates, context_embeddings, current,
            activation_weight=0.0, semantic_weight=1.0, d=d, s=s,
        )

        actr_ids_e = [c.id for c in actr_survivors]
        recency_ids_e = [c.id for c in recency_group]

        result.append({
            'epoch': label,
            'overlap': _set_overlap(actr_ids_e, recency_ids_e),
            'actr_match_rate': _chunk_action_match(actr_survivors),
            'recency_match_rate': _chunk_action_match(recency_group),
            'actr_count': n_epoch,
            'recency_count': len(recency_group),
        })

    return result


# ── Reinforcement distribution (#223) ──────────────────────────────────────

@dataclass
class ReinforcementDistResult:
    total_chunks: int
    single_trace_count: int
    multi_trace_count: int
    single_trace_fraction: float
    mean_traces: float
    max_traces: int
    ablation_tautological: bool


def reinforcement_distribution(conn: sqlite3.Connection) -> ReinforcementDistResult:
    """Report trace count statistics across all chunks.

    When all chunks have exactly one trace, ACT-R activation reduces to a
    function of creation time, making the decay-vs-recency ablation tautological.
    """
    chunks = query_chunks(conn)
    if not chunks:
        return ReinforcementDistResult(
            total_chunks=0, single_trace_count=0, multi_trace_count=0,
            single_trace_fraction=0.0, mean_traces=0.0, max_traces=0,
            ablation_tautological=True,
        )

    trace_counts = [len(c.traces) for c in chunks]
    single = sum(1 for tc in trace_counts if tc <= 1)
    multi = len(trace_counts) - single
    total_traces = sum(trace_counts)

    return ReinforcementDistResult(
        total_chunks=len(chunks),
        single_trace_count=single,
        multi_trace_count=multi,
        single_trace_fraction=single / len(chunks),
        mean_traces=total_traces / len(chunks),
        max_traces=max(trace_counts),
        ablation_tautological=(multi == 0),
    )
