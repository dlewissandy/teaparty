# Approval Gate and Human Proxy

Every question that needs a human decision follows the same path:

1. **Ask the proxy** (if enabled) — proxy generates a predicted answer
2. **If confident** — return the proxy's answer, done
3. **If not confident** — ask the human
4. **Record the differential** (proxy prediction vs. human actual) for learning
5. **Return the answer**

Two entry points feed into this path:

- **ASSERT states** (INTENT_ASSERT, PLAN_ASSERT, WORK_ASSERT, TASK_ASSERT) — the `ApprovalGate` in `actors.py`, invoked by the engine when the CfA state machine reaches an approval gate. The question is "do you approve this artifact?"

- **Agent questions** — agents call the `AskQuestion` MCP tool. The `EscalationListener` in `escalation_listener.py` receives the question via Unix socket and routes it through the same proxy path. The question is whatever the agent asked.

---

## ApprovalGate (ASSERT states)

`ApprovalGate.run()` in `actors.py`:

1. If artifact is missing → skip proxy, ask human
2. If proxy disabled → skip proxy, ask human
3. At PLAN_ASSERT: check that all [RESOLVE] questions from INTENT.md are assigned to workflow steps in PLAN.md. If not → reject back to planning agent.
4. Consult proxy via `_proxy_decide()` → calls `should_escalate()` from `approval_gate.py`
5. If auto-approve → record outcome, return approve
6. If escalate → generate bridge text → dialog loop with human → classify response → record outcome → return action

The dialog loop lets the human ask follow-up questions before deciding. The proxy generates contextual replies. The loop ends when the human gives a clear action (approve, correct, withdraw, backtrack).

### Elapsed-time guard

At TASK_ASSERT and WORK_ASSERT, if the execution phase ran for less than 120 seconds, the proxy always escalates. A plan that completes in under 2 minutes relative to any non-trivial plan is suspicious.

---

## EscalationListener (agent questions via AskQuestion MCP tool)

`EscalationListener._route_through_proxy()` in `escalation_listener.py`:

1. Load proxy model, call `generate_response()` for a prediction (always, even on cold start)
2. If confident (confidence >= generative_threshold) → return prediction directly
3. If not confident → ask human via `input_provider` (TUI)
4. Record differential via `record_outcome()` — stores the proxy's prediction alongside the human's actual answer
5. Return the answer to the agent as the MCP tool result

The agent gets the answer in the same turn. It does not exit and re-enter.

---

## Proxy Decision Model

The proxy is currently a statistical heuristic in `approval_gate.py` — not an LLM agent. It does not read artifacts. Issue [#139](https://github.com/dlewissandy/teaparty/issues/139) tracks replacing it with a Claude agent that inspects the work.

### `should_escalate()` — used by ApprovalGate

Returns `ProxyDecision` (action, confidence, reasoning, predicted_response). Decision rules in priority order:

1. **Cold start**: < 5 observations → escalate
2. **Content checks**: artifact length anomaly, keyword match against past corrections, concern patterns, `[CONFIRM:]` markers
3. **Confidence threshold**: ASSERT states require 0.8; generative states require 0.95
4. **Staleness guard**: > 7 days since last human signal → escalate
5. **Exploration rate**: 15% random escalation even when confident

### `generate_response()` — used by EscalationListener

Constructs a predicted human response from stored question patterns and text differentials. Returns `GenerativeResponse` (action, text, confidence) or None if insufficient data or confidence too low.

### Confidence computation

Confidence = min(Laplace, EMA):
- **Laplace**: `(approve_count + 1) / (total_count + 2)`
- **EMA** (alpha=0.3): approval nudges up by 1; correction nudges down by 3 (asymmetric regret)

---

## Learning from Outcomes

`record_outcome()` records after every human decision:

- Counter increments (approve, correct, reject, total)
- **Text differentials**: what the human changed (summary + reasoning), timestamped, with the proxy's prediction
- **Artifact lengths**: historical char counts (max 20)
- **Question patterns**: extracted questions with concern category and disposition (max 20)

Both paths record outcomes: ApprovalGate via `_proxy_record()`, EscalationListener via `record_outcome()` directly.

---

## Implementation Status

| Area | Status | Issue |
|------|--------|-------|
| AskQuestion MCP tool replaces file-based escalation | Done | [#137](https://github.com/dlewissandy/teaparty/issues/137) |
| Differential recording (proxy prediction vs. human actual) | Done | [#138](https://github.com/dlewissandy/teaparty/issues/138) |
| Alignment validation framing at gates | Done | [#102](https://github.com/dlewissandy/teaparty/issues/102) |
| Cold-start intake dialog (Phase 1) | Done | [#125](https://github.com/dlewissandy/teaparty/issues/125) |
| Proxy must be an actual agent (reads artifacts, reasons) | Open | [#139](https://github.com/dlewissandy/teaparty/issues/139) |
| Intake dialog Phases 2–3 (prediction-comparison, rituals) | Design target | [#125](https://github.com/dlewissandy/teaparty/issues/125) |
| Retrieval-backed prediction | Design target | |
| Text derivative learning (proxy self-assessment) | Design target | |
