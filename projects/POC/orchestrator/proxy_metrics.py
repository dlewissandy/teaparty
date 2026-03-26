"""ACT-R Phase 1 evaluation metrics for the human proxy.

Computes four metrics from proxy_memory.db chunks:
1. Action match rate — posterior_prediction vs outcome (escalated gates only)
2. Prior calibration — prior vs posterior prediction agreement
3. Surprise calibration — surprise detection confirmed by human response
4. Retrieval relevance — inspectable retrieval sets with activation scores
Plus go/no-go assessment and reporting.

Theory: docs/detailed-design/act-r-proxy-memory.md §Evaluation metrics
"""
from __future__ import annotations

import json
import math
import sqlite3
from dataclasses import dataclass, field

from projects.POC.orchestrator.proxy_memory import (
    DECAY,
    MemoryChunk,
    base_level_activation,
    query_chunks,
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
