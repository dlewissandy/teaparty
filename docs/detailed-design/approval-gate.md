# Approval Gate and Human Proxy

Every question that needs a human decision follows the same pattern:

1. **Ask the proxy** (if enabled) — proxy generates a predicted answer
2. **If confident** — return the proxy's answer
3. **If not confident** — ask the human
4. **Record the differential** (proxy prediction vs. human actual) for learning
5. **Return the answer**

Two entry points feed into this pattern, but they use **different proxy functions** — this is a known gap ([#143](https://github.com/dlewissandy/teaparty/issues/143)).

---

## Entry Point 1: ApprovalGate (ASSERT states)

`ApprovalGate.run()` in `actors.py`. Invoked by `engine.py` when the CfA state machine reaches INTENT_ASSERT, PLAN_ASSERT, WORK_ASSERT, or TASK_ASSERT. The agent has already exited.

**Flow:**

1. **Artifact missing?** → skip proxy, ask human directly
2. **Proxy disabled?** → skip proxy, ask human directly (experiment baseline)
3. **PLAN_ASSERT only:** cross-reference [RESOLVE] questions from INTENT.md against PLAN.md via `check_resolve_coverage()`. Unaddressed questions → reject back to planning agent.
4. **Consult proxy** via `_proxy_decide()` → calls `should_escalate()` from `approval_gate.py`
5. **Auto-approve** → record outcome via `_proxy_record()`, log interaction, return approve
6. **Escalate** → generate bridge text via `_generate_bridge()` (calls `generate_review_bridge.generate()` — an LLM call that reads the artifact and upstream context files) → enter dialog loop

**Dialog loop (step 6):**

- Show bridge text to human via `input_provider` (TUI)
- Human responds
- Classify response via `_classify_review()` (calls `classify_review.classify()` — an LLM call with intent/plan summaries and dialog history)
- If classified as `dialog` or `__fallback__` → generate contextual reply via `_generate_dialog_response()` (another LLM call), append to dialog history, loop again
- If classified as a clear action (approve, correct, withdraw, backtrack) → record outcome via `_proxy_record()`, log interaction, return

**Elapsed-time guard:** At TASK_ASSERT and WORK_ASSERT, if the execution phase ran for less than `MIN_EXECUTION_SECONDS` (120s), the proxy always escalates regardless of confidence.

**Recording:** `_proxy_record()` calls `record_outcome()` with the outcome, differential summary (human feedback text), artifact length, extracted question patterns, and the proxy's prediction. Also appends to `.proxy-interactions.jsonl` via `_log_interaction()` for tier 2 retrieval.

---

## Entry Point 2: EscalationListener (AskQuestion MCP tool)

`EscalationListener._route_through_proxy()` in `escalation_listener.py`. Invoked when an agent calls the `AskQuestion` MCP tool during its turn. The agent is still running.

**Flow:**

1. Load proxy model via `load_model()`
2. Call `generate_response()` for a prediction — returns `GenerativeResponse` (action, text, confidence) or None
3. **Confident** (confidence >= `model.generative_threshold`) → return prediction text directly
4. **Not confident** → ask human via `_ask_human()` → `input_provider` (TUI)
5. Record differential via `record_outcome()` — stores prediction alongside human answer
6. Return human answer to agent as MCP tool result

**Key difference from ApprovalGate:** Uses `generate_response()` instead of `should_escalate()`. `generate_response()` only checks cold start threshold and confidence — it lacks the content checks, staleness guard, exploration rate, tier 1/tier 2 pattern checks, prediction drift detection, and elapsed-time guard that `should_escalate()` has. Issue [#143](https://github.com/dlewissandy/teaparty/issues/143) tracks unifying these paths.

---

## Proxy Decision Model

The proxy is a statistical heuristic in `approval_gate.py`. It does not read artifacts or reason about their content. Issue [#139](https://github.com/dlewissandy/teaparty/issues/139) tracks replacing it with an actual Claude agent.

### `should_escalate()` — used by ApprovalGate

Returns `ProxyDecision`. Decision rules in priority order:

1. **Cold start guard**: < 5 observations for this (state, task_type) pair → escalate
2. **[CONFIRM:] markers**: artifact contains unresolved `[CONFIRM:...]` markers → escalate unconditionally
3. **Content checks** (`_check_content()`), in sub-priority order:
   - Length anomaly: artifact < 50% or > 200% of historical mean character count
   - Principle violation (Phase 2a): past corrections with reasoning — if the artifact doesn't contain keywords from the human's stated standard, escalate
   - Keyword match (Phase 2a fallback): past corrections without reasoning — if correction summary keywords appear in the artifact, escalate (signal the artifact may repeat a past mistake)
   - Concern patterns (Phase 2b): concern categories from question history (e.g., error_handling, security) raised >= 2 times — if the artifact doesn't contain keywords from the concern vocabulary, escalate
4. **Tier 1 pattern match**: flat behavioral patterns from `proxy-patterns.md` — if the artifact doesn't address known correction patterns for this state, escalate
5. **Tier 2 retrieval**: past interactions from `.proxy-interactions.jsonl` — if > 50% of recent similar interactions at this state resulted in corrections, escalate
6. **Confidence threshold**: confidence < threshold → escalate. Binary states (ASSERT) require 0.8; generative states require 0.95
7. **Staleness guard**: > 7 days since last human signal → escalate to recalibrate
8. **Prediction drift**: if prediction accuracy has dropped below threshold → escalate
9. **Exploration rate**: 15% random escalation even when confident
10. **Auto-approve**: all checks passed

`_proxy_decide()` in `actors.py` wraps this with an elapsed-time guard (< 120s at execution states → escalate) and loads tier 1 patterns from `proxy-patterns.md` and tier 2 interactions from `.proxy-interactions.jsonl`.

### `generate_response()` — used by EscalationListener

Constructs a predicted human response from stored question patterns and text differentials. Returns `GenerativeResponse` (action, text, confidence) or None. Only checks cold start threshold and confidence — none of the content checks, pattern matching, or guards from `should_escalate()`.

### Confidence computation

`compute_confidence()` returns the minimum of two signals:
- **Laplace estimate**: `(approve_count + 1) / (total_count + 2)` — stable long-term
- **EMA** (alpha=0.3): approval nudges up by 1 step; correction nudges down by 3 steps (asymmetric regret)

### Design choices

- **Dual-signal confidence (Laplace + EMA)**: Taking the minimum ensures both signals agree before auto-approving — least-regret strategy.
- **Asymmetric regret (REGRET_WEIGHT=3)**: A false approval costs 3x more than a false escalation. Bias toward caution.
- **Exploration rate (15%)**: Prevents permanent overconfidence. Floor on human interruption.
- **Per-team JSON persistence**: `.proxy-confidence-{team}.json` — one file per team, each evolving independently.

---

## Learning from Outcomes

`record_outcome()` records after every human decision:

- Counter increments (approve, correct, reject, total)
- EMA update (approval → +1 step; correction → -3 steps)
- **Text differentials**: summary of what the human changed, reasoning, timestamped, with the proxy's prediction stored as `predicted_response`
- **Artifact lengths**: historical char counts (max 20 per entry)
- **Question patterns**: extracted questions with concern category and disposition (max 20 per entry)
- **Prediction accuracy tracking**: `prediction_correct_count` / `prediction_total_count`

Concern vocabulary: error_handling, rollback, security, idempotency, testing, documentation, sequencing, external_dependencies.

Both paths record outcomes: ApprovalGate via `_proxy_record()` → `record_outcome()` + `_log_interaction()`, EscalationListener via `record_outcome()` directly (no interaction log — another [#143](https://github.com/dlewissandy/teaparty/issues/143) gap).

---

## Bridge Text and Classification

**Bridge generation** (`_generate_bridge()`): LLM call (Haiku) via `generate_review_bridge.generate()`. Reads the artifact under review and upstream context (INTENT.md at PLAN_ASSERT; INTENT.md + PLAN.md at WORK_ASSERT). Frames the review as an alignment validation question. Falls back to a static string if the LLM is unavailable.

**Response classification** (`_classify_review()`): LLM call (Haiku) via `classify_review.classify()`. Takes the human's response, dialog history, and summaries of INTENT.md and PLAN.md. Returns (action, feedback). Valid actions are derived from the CfA state machine per state — each ASSERT/ESCALATE state has its own set of valid transitions (e.g., INTENT_ASSERT allows approve, correct, withdraw; WORK_ASSERT allows approve, correct, withdraw, revise-plan, refine-intent). `dialog` is prepended to all review states for multi-turn conversation. `__fallback__` is returned on classification failure (LLM timeout, empty response, exception).

**Dialog response** (`_generate_dialog_response()`): LLM call (Haiku) via `generate_dialog_response.generate()`. Generates a contextual reply when the human asks a question or says something that isn't a clear decision. Reads the artifact, execution stream, task description, and dialog history.

---

## Implementation Status

| Area | Status | Issue |
|------|--------|-------|
| AskQuestion MCP tool replaces file-based escalation | Done | [#137](https://github.com/dlewissandy/teaparty/issues/137) |
| Differential recording (proxy prediction vs. human actual) | Done | [#138](https://github.com/dlewissandy/teaparty/issues/138) |
| Alignment validation framing at gates | Done | [#102](https://github.com/dlewissandy/teaparty/issues/102) |
| Cold-start intake dialog (Phase 1) | Done | [#125](https://github.com/dlewissandy/teaparty/issues/125) |
| Unify proxy paths (should_escalate vs. generate_response) | Open | [#143](https://github.com/dlewissandy/teaparty/issues/143) |
| Proxy must be an actual agent (reads artifacts, reasons) | Open | [#139](https://github.com/dlewissandy/teaparty/issues/139) |
| Intake dialog Phases 2–3 (prediction-comparison, rituals) | Design target | [#125](https://github.com/dlewissandy/teaparty/issues/125) |
| Retrieval-backed prediction | Design target | |
| Text derivative learning (proxy self-assessment) | Design target | |
