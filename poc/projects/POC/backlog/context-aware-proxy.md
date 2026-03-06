# Context-Aware Human Proxy

## Problem

The human proxy makes approval/escalation decisions using only statistical
confidence over historical outcomes. It knows that PLAN_ASSERT for task-type
"my-project" was approved 18 out of 20 times. It does not know what the plan
*says*. It cannot distinguish a routine plan from one that proposes deleting
the database.

This means the proxy overfits to the *frequency* of approval rather than
the *substance* of what it is approving. A human who approves 20 simple
plans in a row does not thereby authorize all future plans sight-unseen.

## Desired Behavior

The proxy should be able to read the artifact under review (intent, plan,
work output, escalation file) and factor its content into the
approve/escalate decision. It should NOT be able to modify artifacts.

Read-only access means the proxy can:
- Read INTENT.md at INTENT_ASSERT
- Read plan.md at PLAN_ASSERT
- Read .work-summary.md and the exec stream at WORK_ASSERT
- Read .task-escalation.md / .plan-escalation.md at ESCALATE states
- Read the confidence model (already does this)
- Read differentials from past corrections (already does this)

It cannot:
- Write to any artifact file
- Modify the confidence model outside of `record_outcome()`
- Execute commands or tools

## Current Information Flow

```
proxy_decide()
  -> human_proxy.py --decide --state PLAN_ASSERT --task-type my-project --model .proxy.json
  <- "auto-approve" | "escalate"
```

The proxy receives: state name, task type slug, model path. Nothing about
what is actually being reviewed.

Meanwhile, the classify_review and dialog_response systems already receive
artifact paths and summaries -- the proxy is the only actor in the review
loop that is content-blind.

## Design Direction

### Phase 1: Pass artifact paths to the proxy

Add `--artifact <path>` to `proxy_decide()`. The proxy reads the file and
uses a lightweight content signal alongside the statistical confidence.

The content signal is NOT an LLM call. It is structural:
- Is the artifact unusually short or long compared to past artifacts?
- Does it contain keywords from past correction differentials?
- Does it differ substantially from the last approved artifact at this
  state+task_type? (simple diff heuristic)

If any structural signal fires, the proxy treats it as a novelty flag and
escalates regardless of confidence -- similar to how the staleness guard
forces escalation when the date is too old.

### Phase 2: Differential-aware content matching

The proxy already stores text differentials (summaries of what the human
changed on past corrections). In Phase 2, it matches the current artifact
against differential patterns:

- If the human previously corrected "always check error codes" and the
  current work output contains no error handling, the proxy can predict
  that the human will correct again and escalate proactively.
- This is keyword/pattern matching against the differential history, not
  an LLM call.

### Phase 3: LLM-assisted content review (optional, future)

If the statistical + structural signals are insufficient, the proxy could
make a cheap LLM call (haiku) to evaluate the artifact against the
differential history. This is the most expensive option and should be gated
behind a confidence band: only invoke when confidence is in the ambiguous
range (e.g., 0.7-0.85 for binary states).

## Interface Changes

### human_proxy.py

```python
def should_escalate(
    model: ConfidenceModel,
    state: str,
    task_type: str,
    artifact_path: str = '',       # NEW — path to the artifact under review
) -> ProxyDecision:
```

The artifact_path is optional for backward compat. When provided, the proxy
reads the file (up to MAX_ARTIFACT_CHARS, e.g., 4000) and runs structural
checks before the confidence threshold check.

Decision flow becomes:

1. Cold start guard (unchanged)
2. Compute confidence (unchanged)
3. **Content novelty check** (NEW) -- if artifact is structurally novel,
   escalate with "Content novelty" reasoning
4. Confidence threshold check (unchanged)
5. Staleness guard (unchanged)
6. Exploration floor (unchanged)
7. Auto-approve

### CLI

```bash
python3 human_proxy.py --decide \
  --state PLAN_ASSERT \
  --task-type my-project \
  --model .proxy.json \
  --artifact /path/to/plan.md       # NEW
```

### Shell orchestration

In `proxy_decide()` (intent.sh and plan-execute.sh), pass the artifact path:

```bash
proxy_decide() {
  local state="$1"
  local artifact="${2:-}"                                # NEW
  local task_type="${POC_PROJECT:-default}"
  python3 "$SCRIPT_DIR/scripts/human_proxy.py" \
    --decide --state "$state" --task-type "$task_type" \
    --model "$PROXY_MODEL" \
    ${artifact:+--artifact "$artifact"} \                # NEW
    2>/dev/null || echo "escalate"
}
```

Call sites:

| State | Artifact path |
|-------|--------------|
| INTENT_ASSERT | `$CWD/INTENT.md` |
| PLAN_ASSERT | `$STREAM_DIR/plan.md` |
| WORK_ASSERT | `$STREAM_DIR/.work-summary.md` |
| INTENT_ESCALATE | `$CWD/.intent-escalation.md` |
| PLANNING_ESCALATE | `$STREAM_DIR/.plan-escalation.md` |
| TASK_ESCALATE | `$STREAM_DIR/.task-escalation.md` |

## Testing

- Existing tests pass unchanged (artifact_path defaults to empty string)
- New tests verify:
  - Novelty detection: artifact with correction-differential keywords triggers escalation
  - Length anomaly: unusually short artifact triggers escalation
  - No file: missing artifact_path degrades gracefully to stats-only
  - Unreadable file: OSError degrades gracefully to stats-only
  - Content check does not fire during cold start (cold start takes priority)
  - Content check does not fire when confidence is already below threshold

## Non-Goals

- The proxy does not generate corrections or rewrites
- The proxy does not call an LLM in Phase 1 or Phase 2
- The proxy does not modify artifacts
- The proxy does not replace the human -- it predicts what the human would do
