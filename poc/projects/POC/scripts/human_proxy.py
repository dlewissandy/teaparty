#!/usr/bin/env python3
"""Human Proxy — confidence-based approval gate for the CfA state machine.

Collapses human approval and agent auto-approval into a single mechanism
driven by a learned confidence threshold. At every human decision point the
proxy answers one question: can I speak for the human, or should I escalate?

There is no 'auto-approve' as a fundamentally different action. There is only
the proxy deciding whether it can speak for the human or not.

Usage:
    # Query — should we escalate or auto-approve?
    python3 human_proxy.py --decide --state PLAN_ASSERT --task-type my-project \\
        --model /path/to/.proxy-confidence.json

    # Record — human actually approved
    python3 human_proxy.py --record --state PLAN_ASSERT --task-type my-project \\
        --outcome approve --model /path/to/.proxy-confidence.json

    # Stats — show confidence summary
    python3 human_proxy.py --stats --model /path/to/.proxy-confidence.json

No external dependencies — uses stdlib only (json, os, datetime, dataclasses).
"""
import argparse
import json
import os
import random
import re
import sys
from dataclasses import dataclass, field, asdict
from datetime import date, timedelta


# ── Constants ──────────────────────────────────────────────────────────────────

# Minimum number of observations before the proxy will trust its own estimate.
COLD_START_THRESHOLD = 5

# Exploration rate: probability of escalating even when confidence is above
# threshold. Prevents the proxy from converging to "always auto-approve" and
# ensures ongoing calibration signal from the human.
EXPLORE_RATE = 0.15

# Staleness guard: force escalation if the last human observation is older
# than this many days. Confidence drifts — the human's preferences may have
# changed since the proxy last checked.
STALENESS_DAYS = 7

# EMA (exponential moving average) learning rate for recency decay.
# Higher = more weight on recent observations, faster forgetting of old ones.
EMA_ALPHA = 0.3

# Asymmetric regret weight: one correction applies this many EMA decay steps.
# This makes auto-approve harder to earn and easier to lose — because the cost
# of rubber-stamping bad work (false approve) is much higher than the cost of
# asking the human when they would have said yes (false escalate).
REGRET_WEIGHT = 3

# States where the proxy only needs to produce a binary approve/reject signal.
BINARY_STATES = frozenset([
    'INTENT_ASSERT',
    'PLAN_ASSERT',
    'TASK_ASSERT',
    'WORK_ASSERT',
])

# States where the proxy must generate a substantive response (clarify, correct,
# refine) rather than simply saying yes or no.
GENERATIVE_STATES = frozenset([
    'INTENT_ESCALATE',
    'PLANNING_ESCALATE',
    'TASK_ESCALATE',
])

# All valid outcomes that can be recorded after a human decision.
VALID_OUTCOMES = frozenset(['approve', 'correct', 'reject', 'withdraw', 'clarify'])

# Maximum number of text differentials to retain per (state, task_type) pair.
MAX_DIFFERENTIALS_PER_ENTRY = 20


# ── Content-awareness constants ─────────────────────────────────────────────

MAX_ARTIFACT_CHARS = 4000

# Phase 1 — length anomaly thresholds (relative to mean of historical artifact lengths).
ARTIFACT_LENGTH_RATIO_LOW  = 0.5   # < 50% of mean → escalate
ARTIFACT_LENGTH_RATIO_HIGH = 2.0   # > 200% of mean → escalate
MAX_ARTIFACT_LENGTHS_PER_ENTRY = 20  # same cap pattern as MAX_DIFFERENTIALS_PER_ENTRY

# Phase 2b — concern frequency threshold.
QUESTION_PATTERN_MIN_OCCURRENCES = 2  # concern must appear >= N times to trigger Phase 2b

# Phase 2a — principle violation detection threshold.
PRINCIPLE_VIOLATION_THRESHOLD = 0.5

# Fixed concern vocabulary
CONCERN_VOCABULARY = {
    "error_handling":        ["error", "exception", "failure", "fallback", "handle",
                              "handling", "catch", "retry", "fault"],
    "rollback":              ["rollback", "revert", "undo", "restore", "recovery",
                              "transaction"],
    "security":              ["auth", "authentication", "authorization", "permission",
                              "access", "token", "secret", "encrypt"],
    "idempotency":           ["idempotent", "idempotency", "duplicate", "replay"],
    "testing":               ["test", "tests", "spec", "coverage", "assert",
                              "verify", "validate"],
    "documentation":         ["docs", "documentation", "comment", "explain"],
    "sequencing":            ["order", "sequence", "step", "before", "after",
                              "dependency", "prerequisite"],
    "external_dependencies": ["external", "dependency", "database", "service",
                              "network", "connection"],
}


# ── Data model ─────────────────────────────────────────────────────────────────

@dataclass
class ProxyDecision:
    """The proxy's verdict at a single decision point."""
    action: str              # 'auto-approve' | 'escalate'
    confidence: float        # 0.0–1.0
    reasoning: str           # why this decision was made
    predicted_response: str  # what the proxy thinks the human would say


@dataclass
class GenerativeResponse:
    """A predicted human response for generative states.

    When the proxy has sufficient confidence and differential history,
    it can predict what the human would say (e.g., a correction or
    clarification) rather than just saying 'approve' or 'escalate'.
    """
    action: str              # predicted human action (e.g. 'correct', 'clarify')
    text: str                # predicted response text
    confidence: float        # 0.0–1.0


@dataclass
class TextDifferential:
    """A record of what the human changed when they corrected/edited output."""
    outcome: str             # 'correct', 'reject', 'clarify'
    summary: str             # brief description of the change
    reasoning: str = ''      # NEW — why it needed to change
    timestamp: str = ''      # ISO date e.g. '2026-03-04'


@dataclass
class QuestionPattern:
    """A record of a question the human asked during a review session.

    Captures not just the question but the concern it probes and the reasoning
    behind it — so the proxy can generalize to new artifacts that don't address
    the same standard, even if the exact question was never asked before.
    """
    question: str     # verbatim or paraphrased question
    concern: str      # concern category extracted via CONCERN_VOCABULARY
    reasoning: str    # why the human asks this — the standard being checked
    disposition: str  # final disposition after this Q&A: 'approve'|'correct'|'reject'
    timestamp: str


@dataclass
class ConfidenceEntry:
    """Accumulated outcome history for one (state, task_type) pair."""
    state: str               # CfA state e.g. 'INTENT_ASSERT', 'PLAN_ASSERT'
    task_type: str           # derived from project slug or classification
    approve_count: int       # times human approved at this state+type
    correct_count: int       # times human corrected
    reject_count: int        # times human rejected/withdrew
    total_count: int         # total decisions observed
    last_updated: str        # ISO date e.g. '2026-03-04'
    differentials: list = field(default_factory=list)  # list of TextDifferential dicts
    ema_approval_rate: float = 0.5  # exponential moving average — recency-weighted approval rate
    artifact_lengths: list = field(default_factory=list)   # [int, ...] char counts of reviewed artifacts
    question_patterns: list = field(default_factory=list)  # [QuestionPattern dicts]


@dataclass
class ConfidenceModel:
    """The full confidence model over all (state, task_type) pairs."""
    entries: dict            # key: "<state>|<task_type>" → ConfidenceEntry dict
    global_threshold: float  # default threshold for binary decisions (0.8)
    generative_threshold: float  # threshold for generative responses (0.95)


# ── Entry key ──────────────────────────────────────────────────────────────────

def _entry_key(state: str, task_type: str) -> str:
    """Canonical dict key for a (state, task_type) pair."""
    return f"{state}|{task_type}"


# ── Factory ────────────────────────────────────────────────────────────────────

def make_model(
    global_threshold: float = 0.8,
    generative_threshold: float = 0.95,
) -> ConfidenceModel:
    """Create a fresh empty ConfidenceModel."""
    return ConfidenceModel(
        entries={},
        global_threshold=global_threshold,
        generative_threshold=generative_threshold,
    )


def _make_entry(state: str, task_type: str) -> ConfidenceEntry:
    """Create a new zero-count ConfidenceEntry for a previously unseen pair."""
    return ConfidenceEntry(
        state=state,
        task_type=task_type,
        approve_count=0,
        correct_count=0,
        reject_count=0,
        total_count=0,
        last_updated=date.today().isoformat(),
        differentials=[],
    )


# ── Content-awareness helpers ──────────────────────────────────────────────────

def _read_artifact(path: str) -> str:
    """Read artifact text up to MAX_ARTIFACT_CHARS. Returns '' on empty path or any error."""
    if not path:
        return ''
    try:
        with open(path) as f:
            return f.read(MAX_ARTIFACT_CHARS)
    except OSError:
        return ''


def _extract_tokens(text: str) -> set:
    """Lowercase, split on non-alpha chars, drop tokens shorter than 4 characters."""
    return {t for t in re.split(r'[^a-z]+', text.lower()) if len(t) >= 4}


def _mean_artifact_length(entry: ConfidenceEntry) -> float:
    """Mean of stored artifact character counts. Returns 0.0 if no history."""
    lengths = getattr(entry, 'artifact_lengths', [])
    return sum(lengths) / len(lengths) if lengths else 0.0


def _extract_concern(question: str) -> str:
    """Map a question string to the best-matching concern in CONCERN_VOCABULARY.

    Returns the concern name with the most keyword hits, or 'general' if no concern
    vocabulary keywords appear in the question.
    """
    tokens = _extract_tokens(question)
    best_concern, best_count = 'general', 0
    for concern, keywords in CONCERN_VOCABULARY.items():
        count = sum(1 for kw in keywords if kw in tokens)
        if count > best_count:
            best_concern, best_count = concern, count
    return best_concern


def _extract_question_patterns(dialog_text: str, disposition: str) -> list:
    """Extract QuestionPattern dicts from raw dialog text.

    Splits on question marks and newlines to find candidate questions.
    Maps each to a concern via CONCERN_VOCABULARY (skipping 'general').
    Extracts reasoning heuristically from sentences containing reasoning indicators.

    Returns a list of QuestionPattern dicts (via asdict). Returns [] if dialog is empty.
    """
    if not dialog_text.strip():
        return []

    patterns = []
    sentences = re.split(r'[?\n]+', dialog_text)
    for sent in sentences:
        sent = sent.strip()
        if not sent:
            continue
        concern = _extract_concern(sent)
        if concern == 'general':
            continue
        reasoning = ''
        lower = sent.lower()
        if any(ind in lower for ind in ['because', 'requires', 'must', 'should', 'need']):
            reasoning = sent
        patterns.append(asdict(QuestionPattern(
            question=sent[:200],
            concern=concern,
            reasoning=reasoning[:500],
            disposition=disposition,
            timestamp=date.today().isoformat(),
        )))
    return patterns


def _check_content(artifact_text: str, entry: ConfidenceEntry) -> tuple:
    """Run all Phase 1 + 2a + 2b content checks. Returns (fired: bool, reason: str).

    Checks run in priority order and stop at first match:
      Phase 1:  Length anomaly vs historical mean
      Phase 2a: Principle-based violation (reasoning field populated)
      Phase 2a: Keyword fallback (summary field only)
      Phase 2b: Concern pattern reasoning-based
      Phase 2b: Concern pattern keyword fallback

    Returns (False, '') if no check fires.
    """
    # Phase 1 — length anomaly
    mean_len = _mean_artifact_length(entry)
    if mean_len > 0:
        ratio = len(artifact_text) / mean_len
        if ratio < ARTIFACT_LENGTH_RATIO_LOW:
            return True, (
                f"Content novelty: length anomaly — artifact is unusually short "
                f"({len(artifact_text)} chars, {ratio:.0%} of historical mean {mean_len:.0f})"
            )
        if ratio > ARTIFACT_LENGTH_RATIO_HIGH:
            return True, (
                f"Content novelty: length anomaly — artifact is unusually long "
                f"({len(artifact_text)} chars, {ratio:.0%} of historical mean {mean_len:.0f})"
            )

    artifact_tokens = _extract_tokens(artifact_text)
    differentials = getattr(entry, 'differentials', [])

    # Phase 2a — reasoning-based (takes priority over keyword fallback)
    for d in differentials:
        reasoning = d.get('reasoning', '')
        if reasoning and d.get('outcome') in ('correct', 'reject'):
            principle_tokens = _extract_tokens(reasoning)
            if not principle_tokens:
                continue
            present = principle_tokens & artifact_tokens
            coverage = len(present) / len(principle_tokens)
            if coverage < PRINCIPLE_VIOLATION_THRESHOLD:
                return True, (
                    f"Content novelty: possible principle violation. "
                    f"The human's stated standard: '{reasoning}'. "
                    f"This artifact does not appear to satisfy it "
                    f"(only {coverage:.0%} of principle keywords present)."
                )

    # Phase 2a — keyword fallback (differentials without reasoning field)
    correction_tokens: set = set()
    for d in differentials:
        if not d.get('reasoning') and d.get('outcome') in ('correct', 'reject'):
            correction_tokens |= _extract_tokens(d.get('summary', ''))
    matched = correction_tokens & artifact_tokens
    if matched:
        sample = sorted(matched)[:3]
        return True, (
            f"Content novelty: artifact matches past correction patterns: {sample}"
        )

    # Phase 2b — question pattern checks
    question_patterns = getattr(entry, 'question_patterns', [])
    from collections import Counter
    concern_count: Counter = Counter()
    concern_reasoning: dict = {}
    for qp in question_patterns:
        c = qp.get('concern', '')
        if c and c != 'general':
            concern_count[c] += 1
            r = qp.get('reasoning', '')
            if r:
                concern_reasoning[c] = r

    for concern, count in concern_count.items():
        if count < QUESTION_PATTERN_MIN_OCCURRENCES:
            continue
        concern_kws = set(CONCERN_VOCABULARY.get(concern, []))
        if not concern_kws:
            continue
        if concern_kws & artifact_tokens:
            continue  # concern is addressed in artifact
        reasoning = concern_reasoning.get(concern, '')
        if reasoning:
            return True, (
                f"Content novelty: unaddressed concern '{concern}'. "
                f"The human consistently applies the standard: '{reasoning}'. "
                f"This artifact does not address it."
            )
        return True, (
            f"Content novelty: unaddressed concern '{concern}' "
            f"(raised {count} times in question history, no matching keywords in artifact)."
        )

    return False, ''


# ── Core logic ─────────────────────────────────────────────────────────────────

def is_generative_state(state: str) -> bool:
    """Return True for states that require the proxy to generate a response.

    Generative states (INTENT_ESCALATE, PLANNING_ESCALATE, TASK_ESCALATE) need
    the proxy to produce a clarifying answer, not just approve or reject.  A
    higher confidence threshold applies because generating the wrong content is
    worse than approving the wrong artifact.
    """
    return state in GENERATIVE_STATES


def compute_confidence(entry: ConfidenceEntry) -> float:
    """Compute approval confidence for a ConfidenceEntry.

    Uses the conservative minimum of two signals:
    - Laplace (add-1) smoothing: stable long-term estimate
    - EMA (exponential moving average): recency-weighted estimate

    min(laplace, ema) is a least-regret strategy: if EITHER long-term OR
    short-term signal is low, the proxy escalates. This prevents old approvals
    from masking recent corrections, and recent lucky streaks from masking
    a poor long-term record.

    Returns 0.0 when total_count is zero (no data at all).
    """
    if entry.total_count == 0:
        return 0.0
    # Laplace smoothing: (approve + 1) / (total + 2)
    laplace = (entry.approve_count + 1) / (entry.total_count + 2)
    # EMA: initialized from Laplace for backward compat with old entries
    ema = getattr(entry, 'ema_approval_rate', None)
    if ema is None:
        ema = laplace  # old entry without EMA — bootstrap from Laplace
    return min(laplace, ema)


def should_escalate(
    model: ConfidenceModel,
    state: str,
    task_type: str,
    artifact_path: str = '',
) -> ProxyDecision:
    """Decide whether to auto-approve or escalate to the human.

    Decision rules:
    1. Cold start (< COLD_START_THRESHOLD samples) — always escalate.
    2. Choose threshold based on whether the state is generative or binary.
    3. If confidence >= threshold → auto-approve; otherwise → escalate.
    """
    key = _entry_key(state, task_type)
    raw = model.entries.get(key)

    if raw is None:
        entry = _make_entry(state, task_type)
    elif isinstance(raw, dict):
        # Backward compat: old entries may lack newer fields
        if 'differentials' not in raw:
            raw['differentials'] = []
        if 'ema_approval_rate' not in raw:
            ac = raw.get('approve_count', 0)
            tc = raw.get('total_count', 0)
            raw['ema_approval_rate'] = (ac + 1) / (tc + 2) if tc > 0 else 0.5
        if 'artifact_lengths' not in raw:
            raw['artifact_lengths'] = []
        if 'question_patterns' not in raw:
            raw['question_patterns'] = []
        entry = ConfidenceEntry(**raw)
    else:
        entry = raw

    # Cold start guard
    if entry.total_count < COLD_START_THRESHOLD:
        return ProxyDecision(
            action='escalate',
            confidence=0.0,
            reasoning=(
                f"Cold start: only {entry.total_count} observation(s) for "
                f"({state}, {task_type}); need at least {COLD_START_THRESHOLD}."
            ),
            predicted_response="unknown — insufficient history",
        )

    confidence = compute_confidence(entry)

    # Content check (Phase 1 / 2a / 2b) — fires regardless of confidence level.
    if artifact_path:
        artifact_text = _read_artifact(artifact_path)
        if artifact_text:
            fired, reason = _check_content(artifact_text, entry)
            if fired:
                return ProxyDecision(
                    action='escalate',
                    confidence=confidence,
                    reasoning=reason,
                    predicted_response="human review required (content signal)",
                )

    threshold = (
        model.generative_threshold
        if is_generative_state(state)
        else model.global_threshold
    )
    threshold_label = "generative" if is_generative_state(state) else "binary"

    if confidence < threshold:
        return ProxyDecision(
            action='escalate',
            confidence=confidence,
            reasoning=(
                f"Confidence {confidence:.3f} < {threshold_label} threshold "
                f"{threshold:.2f} for ({state}, {task_type}). "
                f"Approved {entry.approve_count}/{entry.total_count} times, "
                f"corrected {entry.correct_count}, rejected {entry.reject_count}."
            ),
            predicted_response="human review required",
        )

    # Staleness guard: force escalation if we haven't heard from the human
    # in too long. Confidence drifts — preferences may have changed.
    try:
        last = date.fromisoformat(entry.last_updated)
        stale = (date.today() - last).days > STALENESS_DAYS
    except (ValueError, TypeError):
        stale = True  # unparseable date → treat as stale

    if stale:
        return ProxyDecision(
            action='escalate',
            confidence=confidence,
            reasoning=(
                f"Stale: last human observation was {entry.last_updated} "
                f"(>{STALENESS_DAYS} days ago). Escalating to recalibrate."
            ),
            predicted_response="human review required (staleness)",
        )

    # Exploration: even when confident, occasionally escalate to get fresh
    # signal. Without this, the proxy converges to auto-approve and never
    # learns about new failure modes.
    if random.random() < EXPLORE_RATE:
        return ProxyDecision(
            action='escalate',
            confidence=confidence,
            reasoning=(
                f"Exploration: randomly escalating ({EXPLORE_RATE:.0%} rate) "
                f"despite confidence {confidence:.3f} >= {threshold:.2f}. "
                f"This ensures ongoing human calibration."
            ),
            predicted_response="human review required (exploration)",
        )

    return ProxyDecision(
        action='auto-approve',
        confidence=confidence,
        reasoning=(
            f"Confidence {confidence:.3f} >= {threshold_label} threshold "
            f"{threshold:.2f} for ({state}, {task_type}). "
            f"Approved {entry.approve_count}/{entry.total_count} times."
        ),
        predicted_response="approve",
    )


def record_outcome(
    model: ConfidenceModel,
    state: str,
    task_type: str,
    outcome: str,
    differential_summary: str = '',
    differential_reasoning: str = '',
    artifact_length: int = 0,
    question_patterns: list = None,
) -> ConfidenceModel:
    """Record a human decision outcome and return the updated model.

    outcome must be one of: 'approve', 'correct', 'reject', 'withdraw', 'clarify'.

    differential_summary (optional): a brief description of what the human changed.
    Per spec Section 9.2, text differentials capture the substance of human
    corrections so the proxy can learn patterns beyond binary approve/reject.

    Returns a new ConfidenceModel with the updated entry (the original is not
    mutated).
    """
    if outcome not in VALID_OUTCOMES:
        raise ValueError(
            f"Invalid outcome {outcome!r}. Must be one of: "
            + ", ".join(sorted(VALID_OUTCOMES))
        )

    key = _entry_key(state, task_type)
    raw = model.entries.get(key)

    if raw is None:
        entry = _make_entry(state, task_type)
    elif isinstance(raw, dict):
        # Backward compat: old entries may lack newer fields
        if 'differentials' not in raw:
            raw['differentials'] = []
        if 'ema_approval_rate' not in raw:
            # Bootstrap EMA from existing Laplace rate
            ac = raw.get('approve_count', 0)
            tc = raw.get('total_count', 0)
            raw['ema_approval_rate'] = (ac + 1) / (tc + 2) if tc > 0 else 0.5
        if 'artifact_lengths' not in raw:
            raw['artifact_lengths'] = []
        if 'question_patterns' not in raw:
            raw['question_patterns'] = []
        entry = ConfidenceEntry(**raw)
    else:
        # Already a ConfidenceEntry — copy it to avoid mutation
        entry = ConfidenceEntry(
            state=raw.state,
            task_type=raw.task_type,
            approve_count=raw.approve_count,
            correct_count=raw.correct_count,
            reject_count=raw.reject_count,
            total_count=raw.total_count,
            last_updated=raw.last_updated,
            differentials=list(getattr(raw, 'differentials', [])),
            ema_approval_rate=getattr(raw, 'ema_approval_rate', 0.5),
            artifact_lengths=list(getattr(raw, 'artifact_lengths', [])),
            question_patterns=list(getattr(raw, 'question_patterns', [])),
        )

    # Update counters
    approve_count = entry.approve_count
    correct_count = entry.correct_count
    reject_count = entry.reject_count
    total_count = entry.total_count + 1

    if outcome == 'approve':
        approve_count += 1
    elif outcome == 'correct':
        correct_count += 1
    elif outcome in ('reject', 'withdraw'):
        reject_count += 1
    # 'clarify' only increments total_count (non-approval signal)

    # Update EMA with asymmetric regret weighting.
    # Approvals nudge the EMA up by one step.
    # Corrections/rejections nudge it down by REGRET_WEIGHT steps — because
    # false-approve (rubber-stamping bad work) costs much more than
    # false-escalate (asking the human when they would have said yes).
    ema = entry.ema_approval_rate
    if outcome == 'approve':
        ema = EMA_ALPHA * 1.0 + (1 - EMA_ALPHA) * ema
    elif outcome in ('correct', 'reject', 'withdraw'):
        for _ in range(REGRET_WEIGHT):
            ema = EMA_ALPHA * 0.0 + (1 - EMA_ALPHA) * ema
    # 'clarify' is neutral — no EMA update (asking a question is not approval or rejection)

    # Append text differential if provided (for non-approve outcomes)
    differentials = list(entry.differentials)
    if differential_summary and outcome != 'approve':
        diff_entry = asdict(TextDifferential(
            outcome=outcome,
            summary=differential_summary[:500],
            reasoning=differential_reasoning[:500],
            timestamp=date.today().isoformat(),
        ))
        differentials.append(diff_entry)
        # Retain only the most recent MAX_DIFFERENTIALS_PER_ENTRY
        if len(differentials) > MAX_DIFFERENTIALS_PER_ENTRY:
            differentials = differentials[-MAX_DIFFERENTIALS_PER_ENTRY:]

    # Track artifact length for Phase 1 length-anomaly detection
    artifact_lengths = list(entry.artifact_lengths) if hasattr(entry, 'artifact_lengths') else []
    if artifact_length > 0:
        artifact_lengths.append(artifact_length)
        if len(artifact_lengths) > MAX_ARTIFACT_LENGTHS_PER_ENTRY:
            artifact_lengths = artifact_lengths[-MAX_ARTIFACT_LENGTHS_PER_ENTRY:]

    # Track question patterns for Phase 2b concern-pattern detection
    stored_patterns = list(entry.question_patterns) if hasattr(entry, 'question_patterns') else []
    if question_patterns:
        stored_patterns.extend(question_patterns)
        if len(stored_patterns) > MAX_DIFFERENTIALS_PER_ENTRY:
            stored_patterns = stored_patterns[-MAX_DIFFERENTIALS_PER_ENTRY:]

    updated_entry = ConfidenceEntry(
        state=state,
        task_type=task_type,
        approve_count=approve_count,
        correct_count=correct_count,
        reject_count=reject_count,
        total_count=total_count,
        last_updated=date.today().isoformat(),
        differentials=differentials,
        ema_approval_rate=ema,
        artifact_lengths=artifact_lengths,
        question_patterns=stored_patterns,
    )

    new_entries = dict(model.entries)
    new_entries[key] = asdict(updated_entry)

    return ConfidenceModel(
        entries=new_entries,
        global_threshold=model.global_threshold,
        generative_threshold=model.generative_threshold,
    )


def generate_response(
    model: ConfidenceModel,
    state: str,
    task_type: str,
) -> 'GenerativeResponse | None':
    """Generate a predicted human response based on differential history.

    For generative states (INTENT_ESCALATE, PLANNING_ESCALATE, TASK_ESCALATE),
    the proxy can predict what the human would say based on patterns in past
    corrections. Returns None if confidence is too low or insufficient data.

    This is the foundation for future auto-correction without human involvement.
    Currently returns the most recent differential as the predicted response.
    """
    key = _entry_key(state, task_type)
    raw = model.entries.get(key)

    if raw is None:
        return None

    if isinstance(raw, dict):
        if 'differentials' not in raw:
            raw['differentials'] = []
        if 'artifact_lengths' not in raw:
            raw['artifact_lengths'] = []
        if 'question_patterns' not in raw:
            raw['question_patterns'] = []
        entry = ConfidenceEntry(**raw)
    else:
        entry = raw

    # Need sufficient history AND differentials or question_patterns to generate
    if entry.total_count < COLD_START_THRESHOLD:
        return None
    if not entry.differentials and not getattr(entry, 'question_patterns', []):
        return None

    confidence = compute_confidence(entry)
    threshold = (
        model.generative_threshold
        if is_generative_state(state)
        else model.global_threshold
    )

    if confidence < threshold:
        return None

    text_parts = []

    # Prepend from question_patterns — most recent with both reasoning and question
    qps = getattr(entry, 'question_patterns', [])
    for qp in reversed(qps):
        q = qp.get('question', '') if isinstance(qp, dict) else ''
        r = qp.get('reasoning', '') if isinstance(qp, dict) else ''
        if q and r:
            text_parts.append(
                f"Based on past reviews, the human would likely ask: '{q}' — checking whether {r}"
            )
            break

    # Append from differentials — most recent
    if entry.differentials:
        latest = entry.differentials[-1]
        r = latest.get('reasoning', '') if isinstance(latest, dict) else ''
        s = latest.get('summary', '') if isinstance(latest, dict) else ''
        if r:
            text_parts.append(f"The human would likely correct this to address: {r}")
        elif s:
            text_parts.append(s)

    if not text_parts:
        return None

    return GenerativeResponse(
        action=entry.differentials[-1].get('outcome', 'correct') if entry.differentials else 'correct',
        text='\n'.join(text_parts),
        confidence=confidence,
    )


# ── Persistence ────────────────────────────────────────────────────────────────

def save_model(model: ConfidenceModel, path: str) -> None:
    """Serialize a ConfidenceModel to JSON at path.

    Creates parent directories if they do not exist.
    """
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    payload = {
        'global_threshold': model.global_threshold,
        'generative_threshold': model.generative_threshold,
        'entries': model.entries,
    }
    with open(path, 'w') as f:
        json.dump(payload, f, indent=2)


def load_model(path: str) -> ConfidenceModel:
    """Load a ConfidenceModel from JSON at path.

    Returns an empty model if the file does not exist or cannot be parsed.
    """
    if not os.path.isfile(path):
        return make_model()
    try:
        with open(path) as f:
            payload = json.load(f)
    except (json.JSONDecodeError, OSError):
        return make_model()

    return ConfidenceModel(
        entries=payload.get('entries', {}),
        global_threshold=float(payload.get('global_threshold', 0.8)),
        generative_threshold=float(payload.get('generative_threshold', 0.95)),
    )


# ── Team scoping ──────────────────────────────────────────────────────────────

def resolve_team_model_path(base_path: str, team: str) -> str:
    """Resolve a per-team model file path from a base path.

    resolve_team_model_path('/path/.proxy-confidence.json', 'coding')
    → '/path/.proxy-confidence-coding.json'
    """
    if not team:
        return base_path
    root, ext = os.path.splitext(base_path)
    return f"{root}-{team}{ext}"


# ── CLI helpers ────────────────────────────────────────────────────────────────

def _fmt_confidence(c: float) -> str:
    return f"{c:.3f}" if c > 0.0 else "0.000 (no data)"


def _cmd_decide(args) -> None:
    """Handle --decide: print action to stdout, details to stderr."""
    model = load_model(args.model)
    decision = should_escalate(model, args.state, args.task_type,
                               artifact_path=getattr(args, 'artifact', '') or '')
    print(decision.action)
    print(f"confidence: {_fmt_confidence(decision.confidence)}", file=sys.stderr)
    print(f"reasoning:  {decision.reasoning}", file=sys.stderr)
    print(f"predicted:  {decision.predicted_response}", file=sys.stderr)


def _cmd_record(args) -> None:
    """Handle --record: update model file with new outcome."""
    model = load_model(args.model)
    diff_summary = getattr(args, 'diff', '') or ''
    diff_reasoning = getattr(args, 'reason', '') or ''
    artifact_len = getattr(args, 'artifact_length', 0) or 0
    raw_questions = getattr(args, 'questions', '') or ''
    qps = _extract_question_patterns(raw_questions, args.outcome) if raw_questions else None
    updated = record_outcome(
        model, args.state, args.task_type, args.outcome,
        differential_summary=diff_summary,
        differential_reasoning=diff_reasoning,
        artifact_length=artifact_len,
        question_patterns=qps or None,
    )
    save_model(updated, args.model)
    key = _entry_key(args.state, args.task_type)
    raw = updated.entries.get(key, {})
    total = raw.get('total_count', 0)
    approved = raw.get('approve_count', 0)
    diff_count = len(raw.get('differentials', []))
    qp_count = len(qps) if qps else 0
    msg = (
        f"Recorded outcome={args.outcome!r} for ({args.state}, {args.task_type}). "
        f"Total={total}, approved={approved}."
    )
    if diff_summary:
        msg += f" Differentials: {diff_count}."
    if qp_count > 0:
        msg += f" Question patterns: {qp_count}."
    print(msg, file=sys.stderr)


def _cmd_generate(args) -> None:
    """Handle --generate: predict what the human would say, or 'escalate' if can't."""
    model = load_model(args.model)
    response = generate_response(model, args.state, args.task_type)
    if response is None:
        print("escalate")
        print("generation: insufficient data or confidence", file=sys.stderr)
    else:
        print(response.text)
        print(f"action: {response.action}", file=sys.stderr)
        print(f"confidence: {response.confidence:.3f}", file=sys.stderr)


def _cmd_stats(args) -> None:
    """Handle --stats: print a confidence summary table."""
    model = load_model(args.model)
    if not model.entries:
        print("(no entries in model)", file=sys.stderr)
        return

    header = f"{'STATE':<22} {'TASK_TYPE':<24} {'CONF':>6} {'APPROVED':>8} {'TOTAL':>6} {'DIFFS':>5} {'LAST_UPDATED'}"
    print(header)
    print('-' * len(header))

    for key, raw in sorted(model.entries.items()):
        if isinstance(raw, dict):
            # Backward compat: old entries may lack 'differentials'
            if 'differentials' not in raw:
                raw['differentials'] = []
            entry = ConfidenceEntry(**raw)
        else:
            entry = raw
        conf = compute_confidence(entry)
        threshold = (
            model.generative_threshold
            if is_generative_state(entry.state)
            else model.global_threshold
        )
        diff_count = len(entry.differentials)
        marker = "*" if conf >= threshold and entry.total_count >= COLD_START_THRESHOLD else " "
        print(
            f"{entry.state:<22} {entry.task_type:<24} {conf:>6.3f} "
            f"{entry.approve_count:>8} {entry.total_count:>6} {diff_count:>5}  "
            f"{entry.last_updated} {marker}"
        )
    print()
    print(f"global_threshold={model.global_threshold}  "
          f"generative_threshold={model.generative_threshold}  "
          f"(* = would auto-approve)")


# ── CLI entry point ────────────────────────────────────────────────────────────

if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description="Human Proxy — confidence-based CfA approval gate"
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--decide', action='store_true',
                      help="Query: should we escalate or auto-approve?")
    mode.add_argument('--record', action='store_true',
                      help="Record a human decision outcome")
    mode.add_argument('--generate', action='store_true',
                      help="Generate a predicted human response (or 'escalate' if can't)")
    mode.add_argument('--stats', action='store_true',
                      help="Print confidence summary for all state+task_type pairs")

    parser.add_argument('--state', help="CfA state (e.g. PLAN_ASSERT)")
    parser.add_argument('--task-type', help="Task type / project slug")
    parser.add_argument('--outcome',
                        choices=sorted(VALID_OUTCOMES),
                        help="Observed human outcome (for --record)")
    parser.add_argument('--diff', default='',
                        help="Text differential summary — what the human changed "
                             "(for --record, per spec Section 9.2)")
    parser.add_argument('--artifact', default='',
                        help="Path to artifact under review (for --decide)")
    parser.add_argument('--artifact-length', type=int, default=0,
                        help="Char count of artifact reviewed (for --record)")
    parser.add_argument('--reason', default='',
                        help="Why correction was needed (for --record)")
    parser.add_argument('--questions', default='',
                        help="Raw dialog text for pattern extraction (for --record)")
    parser.add_argument('--model', required=True,
                        help="Path to the JSON confidence model file")
    parser.add_argument('--team',
                        help="Team slug — scopes model to per-team file "
                             "(e.g. --team coding resolves model.json → model-coding.json)")

    args = parser.parse_args()

    # Resolve per-team model path
    if args.team:
        base, ext = os.path.splitext(args.model)
        args.model = f"{base}-{args.team}{ext}"

    if args.decide:
        if not args.state or not args.task_type:
            parser.error("--decide requires --state and --task-type")
        _cmd_decide(args)

    elif args.record:
        if not args.state or not args.task_type or not args.outcome:
            parser.error("--record requires --state, --task-type, and --outcome")
        _cmd_record(args)

    elif args.generate:
        if not args.state or not args.task_type:
            parser.error("--generate requires --state and --task-type")
        _cmd_generate(args)

    elif args.stats:
        _cmd_stats(args)
