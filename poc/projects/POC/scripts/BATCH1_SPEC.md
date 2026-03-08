# Batch 1 Implementation Spec: Context-Aware Human Proxy (Phase 1, 2a, 2b)

**Target file:** `scripts/human_proxy.py`
**Working directory:** `/Users/darrell/git/teaparty/poc/projects/POC/.worktrees/session-20260307-155155/poc/projects/POC`

Read `scripts/human_proxy.py` first, then apply ALL changes below as a complete rewrite. Stdlib-only (no new external imports — `re` and `collections.Counter` are both stdlib).

---

## A. Add `import re` to the top-level imports block

Current imports: `argparse, json, os, random, sys, dataclasses, datetime`
Add `re` to that block.

---

## B. New constants (add after the existing constants block, before the data model section)

```python
# ── Content-awareness constants ─────────────────────────────────────────────

MAX_ARTIFACT_CHARS = 4000

# Phase 1 — length anomaly thresholds (relative to mean of historical artifact lengths).
# Rationale: 50%/200% bounds catch meaningfully short/long artifacts while tolerating
# natural variation. Tighter bounds would produce too many false positives.
ARTIFACT_LENGTH_RATIO_LOW  = 0.5   # < 50% of mean → escalate
ARTIFACT_LENGTH_RATIO_HIGH = 2.0   # > 200% of mean → escalate
MAX_ARTIFACT_LENGTHS_PER_ENTRY = 20  # same cap pattern as MAX_DIFFERENTIALS_PER_ENTRY

# Phase 2b — concern frequency threshold.
QUESTION_PATTERN_MIN_OCCURRENCES = 2  # concern must appear >= N times to trigger Phase 2b

# Phase 2a — principle violation detection threshold.
# When checking whether an artifact satisfies a human's stated reasoning principle:
# if fewer than 50% of the principle's keywords are present in the artifact,
# the proxy treats it as a potential violation.
# Rationale: 50% is permissive enough to avoid false positives from synonym variation,
# strict enough to catch artifacts that genuinely ignore the principle.
PRINCIPLE_VIOLATION_THRESHOLD = 0.5

# Fixed concern vocabulary — structured so new categories can be added by appending
# to this dict without touching any matching logic.
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
```

---

## C. Data model changes

### `TextDifferential` — add `reasoning` field with empty-string default

```python
@dataclass
class TextDifferential:
    outcome: str             # 'correct', 'reject', 'clarify'
    summary: str             # brief description of the change
    reasoning: str = ''      # NEW — why it needed to change: the standard or principle enforced
    timestamp: str = ''      # ISO date e.g. '2026-03-04'
```

Note: `timestamp` gains a default too (was positional — giving it a default avoids breakage when constructing with positional args that omit `reasoning`).

### New `QuestionPattern` dataclass — add immediately after `TextDifferential`

```python
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
```

### `ConfidenceEntry` — add two new backward-compat fields after `ema_approval_rate`

```python
artifact_lengths: list = field(default_factory=list)   # [int, ...] char counts of reviewed artifacts
question_patterns: list = field(default_factory=list)  # [QuestionPattern dicts]
```

---

## D. Backward-compat deserialization

There are two places that deserialize a raw dict into a `ConfidenceEntry` — one in `should_escalate()` and one in `record_outcome()`. Both follow this pattern:

```python
if 'differentials' not in raw:
    raw['differentials'] = []
if 'ema_approval_rate' not in raw:
    ...
entry = ConfidenceEntry(**raw)
```

In **BOTH** places, add these two lines alongside the existing backward-compat checks:

```python
if 'artifact_lengths' not in raw:
    raw['artifact_lengths'] = []
if 'question_patterns' not in raw:
    raw['question_patterns'] = []
```

Also in `record_outcome()`, there is an `else:` branch that copies a `ConfidenceEntry` object field-by-field. Add the two new fields to that copy:

```python
artifact_lengths=list(getattr(raw, 'artifact_lengths', [])),
question_patterns=list(getattr(raw, 'question_patterns', [])),
```

---

## E. New helper functions (add between the `_entry_key` section and `should_escalate`)

```python
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
    Maps each to a concern via CONCERN_VOCABULARY (skipping 'general' — no clear concern).
    Extracts reasoning heuristically: sentences containing reasoning indicators
    ('because', 'requires', 'must', 'should', 'need') near a concern keyword are
    treated as reasoning statements.

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
            continue  # skip sentences with no recognized concern vocabulary
        reasoning = ''
        lower = sent.lower()
        if any(ind in lower for ind in ['because', 'requires', 'must', 'should', 'need']):
            reasoning = sent  # sentence itself is the reasoning statement
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
      Phase 2a: Principle-based violation (reasoning field populated) — priority over keyword fallback
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
                concern_reasoning[c] = r  # keep most recent reasoning for this concern

    for concern, count in concern_count.items():
        if count < QUESTION_PATTERN_MIN_OCCURRENCES:
            continue
        concern_kws = set(CONCERN_VOCABULARY.get(concern, []))
        if not concern_kws:
            continue
        if concern_kws & artifact_tokens:
            continue  # concern is addressed in artifact
        # Concern not addressed — escalate
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
```

---

## F. Updated `should_escalate()` signature and decision flow

Change signature to add `artifact_path: str = ''` parameter.

The full decision flow must be (insert content check as step 3):
1. Cold start guard (unchanged)
2. `compute_confidence()` (unchanged)
3. **Content check [NEW]** — after compute_confidence, before confidence threshold:
   ```python
       # Content check (Phase 1 / 2a / 2b) — fires regardless of confidence level.
       # Content standards are co-equal inputs, not a filter on top of statistics.
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
   ```
4. Confidence threshold check (unchanged)
5. Staleness guard (unchanged)
6. Exploration floor (unchanged)
7. Auto-approve (unchanged)

---

## G. Updated `record_outcome()` signature and body

New signature — add these parameters with defaults:
- `differential_reasoning: str = ''` — why the correction was needed
- `artifact_length: int = 0` — char count of artifact reviewed
- `question_patterns: list = None` — QuestionPattern dicts from this review

Update `TextDifferential` creation to include `reasoning=differential_reasoning[:500]`.

After the differentials block, add artifact_length and question_patterns tracking:

```python
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
```

Include both new fields in the final `ConfidenceEntry(...)` constructor:
```python
    updated_entry = ConfidenceEntry(
        ...existing fields...,
        artifact_lengths=artifact_lengths,
        question_patterns=stored_patterns,
    )
```

---

## H. Updated `generate_response()`

In the `isinstance(raw, dict)` branch, add backfill for `artifact_lengths` and `question_patterns`.

Update early-exit: `if not entry.differentials and not getattr(entry, 'question_patterns', []): return None`

Build text_parts:
1. Check `question_patterns` for entries with both `reasoning` and `question`. Use most recent one to prepend: `"Based on past reviews, the human would likely ask: '{question}' — checking whether {reasoning}"`
2. Check `entry.differentials`: if latest has `reasoning`, append `"The human would likely correct this to address: {reasoning}"`. Elif has `summary`, append that.
3. If `text_parts` is empty, return None.
4. Return `GenerativeResponse` with `text='\n'.join(text_parts)`.

Add docstring note: Interface note — reasoning-grounded predicted questions are prepended to GenerativeResponse.text when question_patterns with reasoning exist. No new fields are added to GenerativeResponse.

---

## I. CLI additions

After the existing `--diff` argument, add:
- `--artifact` (default empty string, path to artifact under review, for --decide)
- `--artifact-length` (type int, default 0, char count of artifact, for --record)
- `--reason` (default empty string, why correction was needed, for --record)
- `--questions` (default empty string, raw dialog text for pattern extraction, for --record)

Update `_cmd_decide()`: pass `artifact_path=getattr(args, 'artifact', '') or ''` to `should_escalate`.

Update `_cmd_record()`:
- Read `diff_reasoning = getattr(args, 'reason', '') or ''`
- Read `artifact_len = getattr(args, 'artifact_length', 0) or 0`
- Read `raw_questions = getattr(args, 'questions', '') or ''`
- Extract `qps = _extract_question_patterns(raw_questions, args.outcome) if raw_questions else None`
- Pass `differential_reasoning=diff_reasoning, artifact_length=artifact_len, question_patterns=qps or None` to `record_outcome`
- Print `qp_count` in status message if > 0.

---

## Constraints

- Stdlib only. No new external imports beyond `re`.
- Proxy is read-only w.r.t. artifacts — no writes from `should_escalate()`.
- All new params have defaults (backward-compatible).
- `import re` at top level.
- `from collections import Counter` inside `_check_content()` is acceptable.

## Verification

After writing the file, run:
```
python3 -m py_compile scripts/human_proxy.py
```
from the working directory. Report: file path written, syntax validity, line count.
