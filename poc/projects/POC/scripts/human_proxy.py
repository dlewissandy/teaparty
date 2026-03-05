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
import sys
from dataclasses import dataclass, field, asdict
from datetime import date


# ── Constants ──────────────────────────────────────────────────────────────────

# Minimum number of observations before the proxy will trust its own estimate.
COLD_START_THRESHOLD = 5

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
    """A record of what the human changed when they corrected/edited output.

    Per spec Section 9.2: the proxy learns not just from binary approve/reject
    but from the substance of human corrections — what patterns of change indicate
    a correction the proxy should learn to predict.
    """
    outcome: str             # 'correct', 'reject', 'clarify'
    summary: str             # brief description of the change
    timestamp: str           # ISO date e.g. '2026-03-04'


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

    Uses Laplace (add-1) smoothing so the estimate shrinks toward 0.5 when the
    sample count is small and converges to the true rate as data accumulates.

    Returns 0.0 when total_count is zero (no data at all).
    """
    if entry.total_count == 0:
        return 0.0
    # Laplace smoothing: (approve + 1) / (total + 2)
    return (entry.approve_count + 1) / (entry.total_count + 2)


def should_escalate(
    model: ConfidenceModel,
    state: str,
    task_type: str,
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
    threshold = (
        model.generative_threshold
        if is_generative_state(state)
        else model.global_threshold
    )
    threshold_label = "generative" if is_generative_state(state) else "binary"

    if confidence >= threshold:
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
    else:
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


def record_outcome(
    model: ConfidenceModel,
    state: str,
    task_type: str,
    outcome: str,
    differential_summary: str = '',
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
        # Backward compat: old entries may lack 'differentials'
        if 'differentials' not in raw:
            raw['differentials'] = []
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

    # Append text differential if provided (for non-approve outcomes)
    differentials = list(entry.differentials)
    if differential_summary and outcome != 'approve':
        diff_entry = asdict(TextDifferential(
            outcome=outcome,
            summary=differential_summary[:500],  # Cap length
            timestamp=date.today().isoformat(),
        ))
        differentials.append(diff_entry)
        # Retain only the most recent MAX_DIFFERENTIALS_PER_ENTRY
        if len(differentials) > MAX_DIFFERENTIALS_PER_ENTRY:
            differentials = differentials[-MAX_DIFFERENTIALS_PER_ENTRY:]

    updated_entry = ConfidenceEntry(
        state=state,
        task_type=task_type,
        approve_count=approve_count,
        correct_count=correct_count,
        reject_count=reject_count,
        total_count=total_count,
        last_updated=date.today().isoformat(),
        differentials=differentials,
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
        entry = ConfidenceEntry(**raw)
    else:
        entry = raw

    # Need sufficient history AND differentials to generate
    if entry.total_count < COLD_START_THRESHOLD:
        return None
    if not entry.differentials:
        return None

    confidence = compute_confidence(entry)
    threshold = (
        model.generative_threshold
        if is_generative_state(state)
        else model.global_threshold
    )

    if confidence < threshold:
        return None

    # Find the most recent differential as the predicted response
    latest = entry.differentials[-1]
    return GenerativeResponse(
        action=latest['outcome'],
        text=latest['summary'],
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
    decision = should_escalate(model, args.state, args.task_type)
    print(decision.action)
    print(f"confidence: {_fmt_confidence(decision.confidence)}", file=sys.stderr)
    print(f"reasoning:  {decision.reasoning}", file=sys.stderr)
    print(f"predicted:  {decision.predicted_response}", file=sys.stderr)


def _cmd_record(args) -> None:
    """Handle --record: update model file with new outcome."""
    model = load_model(args.model)
    diff_summary = getattr(args, 'diff', '') or ''
    updated = record_outcome(
        model, args.state, args.task_type, args.outcome,
        differential_summary=diff_summary,
    )
    save_model(updated, args.model)
    key = _entry_key(args.state, args.task_type)
    raw = updated.entries.get(key, {})
    total = raw.get('total_count', 0)
    approved = raw.get('approve_count', 0)
    diff_count = len(raw.get('differentials', []))
    msg = (
        f"Recorded outcome={args.outcome!r} for ({args.state}, {args.task_type}). "
        f"Total={total}, approved={approved}."
    )
    if diff_summary:
        msg += f" Differentials: {diff_count}."
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
