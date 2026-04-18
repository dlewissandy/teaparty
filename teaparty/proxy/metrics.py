"""ACT-R Phase 1 evaluation metrics for the human proxy.

Computes four metrics from proxy_memory.db chunks:
1. Action match rate — posterior_prediction vs outcome (escalated gates only)
2. Prior calibration — prior vs posterior prediction agreement
3. Surprise calibration — surprise detection confirmed by human response
4. Retrieval relevance — inspectable retrieval sets with activation scores
Plus go/no-go assessment and reporting.

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
class ActionMatchResult:
    rate: float
    eligible: int
    matched: int


@dataclass
class PriorCalibrationResult:
    rate: float
    eligible: int
    agreed: int


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


@dataclass
class GoNoGoResult:
    total_eligible: int
    distinct_task_types: int
    distinct_states: int
    coverage_matrix: dict[tuple[str, str], int]
    action_match_rate: float
    sample_sufficient: bool
    coverage_met: bool
    verdict: str  # GO, NO_GO, INVESTIGATE, INSUFFICIENT


# ── Metric functions ─────────────────────────────────────────────────────────

CONFIDENCE_SHIFT_THRESHOLD = 0.3


def action_match_rate(conn: sqlite3.Connection) -> ActionMatchResult:
    """Fraction of escalated gates where posterior_prediction == outcome.

    Eligible population: chunks where human_response is non-empty (the human
    actually responded) AND posterior_prediction is non-empty (two-pass ran).
    """
    rows = conn.execute(
        """SELECT posterior_prediction, outcome FROM proxy_chunks
           WHERE human_response != '' AND posterior_prediction != ''"""
    ).fetchall()

    if not rows:
        return ActionMatchResult(rate=0.0, eligible=0, matched=0)

    matched = sum(1 for r in rows if r[0] == r[1])
    return ActionMatchResult(
        rate=matched / len(rows),
        eligible=len(rows),
        matched=matched,
    )


def prior_calibration(conn: sqlite3.Connection) -> PriorCalibrationResult:
    """Fraction of chunks where prior_prediction == posterior_prediction.

    Eligible population: chunks where both prior and posterior are non-empty.
    """
    rows = conn.execute(
        """SELECT prior_prediction, posterior_prediction FROM proxy_chunks
           WHERE prior_prediction != '' AND posterior_prediction != ''"""
    ).fetchall()

    if not rows:
        return PriorCalibrationResult(rate=0.0, eligible=0, agreed=0)

    agreed = sum(1 for r in rows if r[0] == r[1])
    return PriorCalibrationResult(
        rate=agreed / len(rows),
        eligible=len(rows),
        agreed=agreed,
    )


def surprise_calibration(conn: sqlite3.Connection) -> SurpriseCalibrationResult:
    """When surprise was detected, did the human respond?

    Surprise is detected when:
    - The action changed (prior_prediction != posterior_prediction), OR
    - Confidence shifted > 0.3 (|posterior_confidence - prior_confidence| > 0.3), OR
    - prediction_delta is non-empty (explicitly flagged by the proxy)

    Confirmation means human_response is non-empty.
    """
    rows = conn.execute(
        """SELECT prior_prediction, posterior_prediction,
                  prior_confidence, posterior_confidence,
                  prediction_delta, salient_percepts, human_response
           FROM proxy_chunks
           WHERE prior_prediction != '' AND posterior_prediction != ''"""
    ).fetchall()

    surprises = 0
    confirmed = 0
    for r in rows:
        prior_action = r[0]
        posterior_action = r[1]
        prior_conf = r[2] or 0.0
        posterior_conf = r[3] or 0.0
        delta_text = r[4] or ''
        percepts = r[5] or '[]'

        action_changed = prior_action != posterior_action
        confidence_shifted = abs(posterior_conf - prior_conf) > CONFIDENCE_SHIFT_THRESHOLD
        has_delta = bool(delta_text)
        has_percepts = percepts not in ('[]', '')

        if action_changed or confidence_shifted or has_delta or has_percepts:
            surprises += 1
            if r[6]:  # human_response non-empty
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


def go_no_go_assessment(conn: sqlite3.Connection) -> GoNoGoResult:
    """Evaluate Phase 2 transition criteria.

    Criteria from act-r-proxy-memory.md:
    - Minimum sample: 50 gate interactions with human responses
    - Spanning: >= 3 task types and >= 4 CfA states
    - Action match rate >= 70% → GO
    - Action match rate 60-70% → INVESTIGATE
    - Action match rate < 60% → NO_GO
    - Insufficient data → INSUFFICIENT
    """
    # Build coverage matrix from eligible chunks (human responded + posterior exists)
    rows = conn.execute(
        """SELECT state, task_type, posterior_prediction, outcome
           FROM proxy_chunks
           WHERE human_response != '' AND posterior_prediction != ''"""
    ).fetchall()

    coverage: dict[tuple[str, str], int] = {}
    matched = 0
    for r in rows:
        key = (r[0], r[1])
        coverage[key] = coverage.get(key, 0) + 1
        if r[2] == r[3]:
            matched += 1

    total = len(rows)
    distinct_states = len({k[0] for k in coverage})
    distinct_task_types = len({k[1] for k in coverage})

    sample_sufficient = total >= 50
    coverage_met = distinct_task_types >= 3 and distinct_states >= 4

    match_rate = matched / total if total > 0 else 0.0

    if not sample_sufficient or not coverage_met:
        verdict = 'INSUFFICIENT'
    elif match_rate >= 0.7:
        verdict = 'GO'
    elif match_rate >= 0.6:
        verdict = 'INVESTIGATE'
    else:
        verdict = 'NO_GO'

    return GoNoGoResult(
        total_eligible=total,
        distinct_task_types=distinct_task_types,
        distinct_states=distinct_states,
        coverage_matrix=coverage,
        action_match_rate=match_rate,
        sample_sufficient=sample_sufficient,
        coverage_met=coverage_met,
        verdict=verdict,
    )


# ── Report ───────────────────────────────────────────────────────────────────

def generate_report(conn: sqlite3.Connection) -> dict:
    """Aggregate all metrics into a structured report with text summary."""
    am = action_match_rate(conn)
    pc = prior_calibration(conn)
    sc = surprise_calibration(conn)
    rr = retrieval_relevance(conn)
    gng = go_no_go_assessment(conn)

    lines = [
        '# ACT-R Phase 1 Evaluation Report',
        '',
        '## Action Match Rate',
        f'Rate: {am.rate:.1%} ({am.matched}/{am.eligible} eligible gates)',
        '',
        '## Prior Calibration',
        f'Rate: {pc.rate:.1%} ({pc.agreed}/{pc.eligible} eligible chunks)',
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

    lines.extend([
        '',
        '## Go/No-Go Assessment',
        f'Total eligible: {gng.total_eligible}',
        f'Task types: {gng.distinct_task_types} (need >= 3)',
        f'CfA states: {gng.distinct_states} (need >= 4)',
        f'Sample sufficient: {gng.sample_sufficient} (need >= 50)',
        f'Coverage met: {gng.coverage_met}',
        f'Action match rate: {gng.action_match_rate:.1%}',
        f'Verdict: **{gng.verdict}**',
    ])

    if gng.coverage_matrix:
        lines.append('')
        lines.append('### Coverage Matrix')
        for (state, tt), count in sorted(gng.coverage_matrix.items()):
            lines.append(f'  {state} × {tt}: {count}')

    text = '\n'.join(lines)

    return {
        'action_match': am,
        'prior_calibration': pc,
        'surprise_calibration': sc,
        'retrieval_relevance': rr,
        'go_no_go': gng,
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
