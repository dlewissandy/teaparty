"""ACT-R Phase 1 evaluation metrics for the human proxy.

Computes four metrics from proxy_memory.db chunks:
1. Action match rate — posterior_prediction vs outcome (escalated gates only)
2. Prior calibration — prior vs posterior prediction agreement
3. Surprise calibration — surprise detection confirmed by human response
4. Go/no-go assessment — sample coverage and Phase 2 transition verdict

Theory: docs/detailed-design/act-r-proxy-memory.md §Evaluation metrics
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass


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

    Surprise is detected when prediction_delta is non-empty OR salient_percepts
    contains entries. Confirmation means human_response is non-empty.
    """
    rows = conn.execute(
        """SELECT prediction_delta, salient_percepts, human_response
           FROM proxy_chunks"""
    ).fetchall()

    surprises = 0
    confirmed = 0
    for r in rows:
        delta = r[0] or ''
        percepts = r[1] or '[]'
        has_surprise = bool(delta) or (percepts not in ('[]', ''))

        if has_surprise:
            surprises += 1
            if r[2]:  # human_response non-empty
                confirmed += 1

    if surprises == 0:
        return SurpriseCalibrationResult(rate=0.0, surprises=0, confirmed=0)

    return SurpriseCalibrationResult(
        rate=confirmed / surprises,
        surprises=surprises,
        confirmed=confirmed,
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
        '## Go/No-Go Assessment',
        f'Total eligible: {gng.total_eligible}',
        f'Task types: {gng.distinct_task_types} (need >= 3)',
        f'CfA states: {gng.distinct_states} (need >= 4)',
        f'Sample sufficient: {gng.sample_sufficient} (need >= 50)',
        f'Coverage met: {gng.coverage_met}',
        f'Action match rate: {gng.action_match_rate:.1%}',
        f'Verdict: **{gng.verdict}**',
    ]

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
        'go_no_go': gng,
        'text': text,
    }
