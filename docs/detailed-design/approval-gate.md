# Approval Gate and Human Proxy

Two entry points for human involvement in the CfA loop:

1. **ApprovalGate** (`actors.py`) — invoked at ASSERT states (INTENT_ASSERT, PLAN_ASSERT, WORK_ASSERT, TASK_ASSERT). Consults the statistical proxy model; if not confident, asks the human to review the artifact.

2. **EscalationListener** (`escalation_listener.py`) — invoked when agents call the AskQuestion MCP tool. Routes through the proxy; if not confident, surfaces the question to the human via the TUI.

The statistical proxy model (`approval_gate.py`) is shared by both paths. Issue [#139](https://github.com/dlewissandy/teaparty/issues/139) tracks replacing it with an actual Claude agent that reads artifacts and reasons about approval.

---

## Two Paths to the Human

### Path 1: Artifact Review (ASSERT states)

```
Agent produces artifact → AgentRunner._interpret_output → CfA transition to *_ASSERT
→ ApprovalGate.run():
    1. Check artifact_missing → escalate
    2. Check proxy_enabled → if disabled, escalate
    3. Check RESOLVE coverage (PLAN_ASSERT only)
    4. Consult proxy (_proxy_decide → should_escalate)
    5. If auto-approve → return approve
    6. If escalate → generate bridge text → dialog loop with human
       → classify response → record outcome → return action
```

The human sees the bridge text (an alignment validation question) and can approve, correct, withdraw, or ask follow-up questions. Dialog continues until the human gives a clear decision.

### Path 2: Agent Questions (AskQuestion MCP tool)

```
Agent calls AskQuestion(question) → MCP server (stdio) → Unix socket
→ EscalationListener._route_through_proxy():
    1. Load proxy model, call generate_response for a prediction
    2. If confident → return prediction (human never consulted)
    3. If not confident → ask human via input_provider (TUI)
    4. Record differential (prediction vs. human actual) via record_outcome
    5. Return human's answer → MCP server → agent
```

The agent gets the answer in the same turn as a tool result. It does not exit and re-enter — no file-based escalation, no stream-offset detection. The question appears in the TUI as the agent's actual question, not a generic label.

---

## Design Choices

**Dual-signal confidence (Laplace + EMA).** Confidence is the minimum of two signals. The Laplace estimate provides stability (converges slowly). The EMA provides recency weighting (recent corrections matter more). Taking the minimum ensures both signals agree before the proxy acts autonomously.

**Asymmetric regret weighting (REGRET_WEIGHT=3).** A false approval costs 3x more than a false escalation. Annoying the human with an extra question is reversible; letting bad work through is not.

**Exploration rate (15%).** Even when confident, the proxy escalates 15% of the time to continue gathering human signal.

**Per-team JSON persistence.** The proxy model is stored as `.proxy-confidence-{team}.json` — one file per team. Each team's proxy evolves independently.

---

## Decision Function

`should_escalate(model, state, task_type, artifact_path)` returns a `ProxyDecision`:

```python
class ProxyDecision:
    action: str             # 'auto-approve' | 'escalate'
    confidence: float       # 0.0–1.0
    reasoning: str          # explanation
    predicted_response: str # what proxy thinks human would say
```

### Decision Rules (in priority order)

1. **Cold start guard**: < 5 observations for this state-task pair → always escalate
2. **Content checks** (if artifact provided):
   - Length anomaly: artifact < 50% or > 200% of historical mean length
   - Keyword matching: artifact matches past correction patterns
   - Concern patterns: repeated question categories not addressed
   - `[CONFIRM:]` markers: unconditional escalation
3. **Confidence threshold**: Binary states (ASSERT) require 0.8; generative states require 0.95
4. **Staleness guard**: > 7 days since last human signal → escalate to recalibrate
5. **Exploration rate**: 15% probability of escalation even when confident

### Confidence Computation

Confidence is the minimum of two signals:
- **Laplace estimate**: `(approve_count + 1) / (total_count + 2)` — stable long-term
- **EMA** (alpha=0.3): Approval nudges up by 1 step; correction nudges down by `REGRET_WEIGHT=3` steps

---

## Learning from Outcomes

`record_outcome(model, state, task_type, outcome, ...)` records:
- Counter increments (approve, correct, reject, total)
- **Text differentials**: what the human changed (summary + reasoning), timestamped
- **Artifact lengths**: historical char counts (max 20 per entry)
- **Question patterns**: extracted questions with concern category and disposition (max 20 per entry)
- **Prediction**: the proxy's predicted response, stored alongside the human's actual response

Concern vocabulary covers 8 categories: error_handling, rollback, security, idempotency, testing, documentation, sequencing, external_dependencies.

Both paths record outcomes: ApprovalGate via `_proxy_record`, EscalationListener via `record_outcome` directly.

---

## Generative Prediction

`generate_response(model, state, task_type)` constructs a predicted human response from stored question patterns and text differentials. Returns `GenerativeResponse` (predicted action, text, confidence) or None if insufficient data.

Used by the EscalationListener to decide whether the proxy can answer an agent's question without consulting the human.

---

## Implementation Status

### Completed

**AskQuestion MCP tool ([#137](https://github.com/dlewissandy/teaparty/issues/137)).** File-based escalation (.intent-escalation.md, stream-offset detection, misplaced-file relocation) replaced with an MCP tool the agent calls directly. The `escalation_file` and `escalation_state` fields were removed from PhaseSpec. All agent prompts updated to use AskQuestion instead of writing escalation files.

**Alignment validation framing ([#102](https://github.com/dlewissandy/teaparty/issues/102)).** Bridge prompts frame each gate as an alignment validation question with upstream artifact context.

**Intake dialog Phase 1 ([#125](https://github.com/dlewissandy/teaparty/issues/125)).** Cold-start detection exposes the proxy's observation count to agents. Agent prompts default to exploration and engagement on cold start.

**Differential recording ([#138](https://github.com/dlewissandy/teaparty/issues/138)).** The EscalationListener records the differential (proxy prediction vs. human actual) via `record_outcome` when the proxy is not confident. The proxy always generates a prediction, even on cold start.

### Open

**Proxy must be an actual agent ([#139](https://github.com/dlewissandy/teaparty/issues/139)).** `should_escalate()` is a pure statistical heuristic — no LLM, no file reads, no artifact inspection. `generate_response()` constructs predictions from stored patterns, not by reading the artifact. The proxy cannot meaningfully review work it never looks at. This is the primary gap: the proxy must become a Claude agent session with tools (file read, dialog, decision) that actually reads and reasons about the artifact under review. The statistical model may inform the agent's prior, but it cannot be the whole decision.

**Retrieval-backed prediction.** `generate_response` constructs predictions from locally stored differentials and question patterns. The conceptual design describes prediction through scoped retrieval from the learning system.

**Intake dialog Phases 2–3.** Prediction-comparison loop, text derivative learning, ritual detection, graduated autonomy remain design targets.

**Text derivative learning.** The implementation stores differentials (what the human changed) but not the proxy's self-assessment of *why its model was wrong*. The conceptual design describes this reflection step as the primary learning signal.

**Behavioral rituals.** Detection of invariant practices tied to CfA states (e.g., human always asks for TLDR before reviewing a plan).

**Gap-detection questioning.** Three triggers for asking rather than predicting (no retrieval hits, contradictory retrieval, novel concerns). Depends on retrieval-backed prediction.
