# Approval Gate and Human Proxy

Every question that needs a human decision follows the same pattern:

1. **Ask the proxy** (if enabled) — proxy generates a predicted answer
2. **If confident** — return the proxy's answer
3. **If not confident** — ask the human
4. **Record the differential** (proxy prediction vs. human actual) for learning
5. **Return the answer**

Two entry points feed into this pattern, but they use **different proxy functions** — this is a known gap ([#143](https://github.com/dlewissandy/teaparty/issues/143)).

---

## Why Retrieval-Backed Question Answering Is the Priority

Park et al. (2024) built AI agents representing 1,052 real people from two-hour qualitative interviews. Those agents replicated individual survey responses with **85% accuracy** using LLM in-context reasoning over interview transcripts — no explicit ML model, no fine-tuning, just retrieval + reasoning.

This result is the empirical basis for the proxy's architecture. The proxy accumulates conversational data about the human — differential corrections, question patterns, behavioral rituals, gate decisions — and uses retrieval to surface relevant history when answering a new question. At steady state (sufficient accumulated interactions), this approach should reach the same ~85% accuracy Park demonstrated: the proxy predicts what the human would say, and is right 85% of the time.

The 85% figure also explains the priority ordering:

1. **Retrieval-backed prediction is the path to autonomy.** A proxy that can answer 85% of questions correctly handles 85% of human involvement automatically. The remaining 15% escalates to the human, and each escalation produces a new differential that improves future predictions.

2. **The statistical heuristic is a stepping stone, not the destination.** `should_escalate()` uses keyword matching, length anomalies, and confidence counters — it can detect obvious signals but cannot reason about whether the human would approve a specific artifact. It reads the artifact for pattern matching (CONFIRM markers, correction keywords, concern vocabulary) but does not understand it. Issue [#139](https://github.com/dlewissandy/teaparty/issues/139) tracks replacing this with a Claude agent that reads and reasons.

3. **The differential is the highest-value learning signal.** Salemi & Zamani (2024, Fermi) showed that misaligned responses — where the model predicted incorrectly — are more valuable for learning than correct predictions. Every proxy prediction that diverges from the human's actual answer tells the system exactly where its model is wrong. This is why both entry points record the differential.

---

## Entry Point 1: ApprovalGate (artifact review)

`ApprovalGate.run()` in `actors.py`. Invoked by `engine.py` at states where all outgoing CfA transitions have actor `human` or `approval_gate`. Currently this means: INTENT_ASSERT, PLAN_ASSERT, and WORK_ASSERT.

The ESCALATE states (INTENT_ESCALATE, PLANNING_ESCALATE, TASK_ESCALATE) are also in `human_actor_states` but are **currently unreachable** — the only path to them was through escalation file detection in `_interpret_output()`, removed in #137. Agents now use AskQuestion for mid-turn questions.

TASK_ASSERT is **not** routed to ApprovalGate — its CfA actor is `execution_worker`.

**Flow:**

1. **Artifact missing?** → skip proxy, ask human directly
2. **Proxy disabled?** → skip proxy, ask human directly (experiment baseline)
3. **PLAN_ASSERT only:** cross-reference [RESOLVE] questions from INTENT.md against PLAN.md via `check_resolve_coverage()`. Unaddressed questions → reject back to planning agent.
4. **Consult proxy** via `_proxy_decide()` → calls `should_escalate()` from `approval_gate.py`
5. **Auto-approve** → record outcome via `_proxy_record()`, log interaction, return approve
6. **Escalate** → generate bridge text → enter dialog loop

**Dialog loop (step 6):**

- Generate bridge text via `_generate_bridge()` — LLM call (Haiku) via `generate_review_bridge.generate()`. Reads the artifact and upstream context (INTENT.md at PLAN_ASSERT; INTENT.md + PLAN.md at WORK_ASSERT). Falls back to a static string if LLM unavailable.
- Show bridge text to human via `input_provider` (TUI)
- Human responds
- Classify response via `_classify_review()` — LLM call (Haiku) via `classify_review.classify()`. Valid actions are derived from the CfA state machine per state, with `dialog` prepended for multi-turn conversation. `__fallback__` on classification failure.
- If `dialog` or `__fallback__` → generate contextual reply via `_generate_dialog_response()` (Haiku), append to dialog history, loop
- If clear action → record outcome via `_proxy_record()`, log interaction via `_log_interaction()`, return

**Elapsed-time guard:** At TASK_ASSERT and WORK_ASSERT, if the execution phase ran for less than `MIN_EXECUTION_SECONDS` (120s), the proxy always escalates.

**Recording:** `_proxy_record()` calls `record_outcome()` with outcome, differential summary, artifact length, extracted question patterns, and proxy prediction. `_log_interaction()` appends to `.proxy-interactions.jsonl` for tier 2 retrieval.

---

## Entry Point 2: EscalationListener (AskQuestion MCP tool)

`EscalationListener._route_through_proxy()` in `escalation_listener.py`. Invoked when an agent calls the `AskQuestion` MCP tool during its turn. The agent is still running — the answer returns as a tool result in the same turn.

**Flow:**

1. Load proxy model via `load_model()`
2. Call `generate_response()` for a prediction — returns `GenerativeResponse` (action, text, confidence) or None
3. **Confident** (confidence >= `model.generative_threshold`) → return prediction text directly
4. **Not confident** → ask human via `_ask_human()` → `input_provider` (TUI)
5. Record differential via `record_outcome()` — stores prediction alongside human answer
6. Return answer to agent as MCP tool result

**Key difference from ApprovalGate:** Uses `generate_response()` instead of `should_escalate()`. `generate_response()` requires cold start threshold passed, stored differentials or question patterns to exist, and confidence above threshold — but lacks the content checks, staleness guard, exploration rate, tier 1/tier 2 pattern checks, prediction drift detection, and elapsed-time guard that `should_escalate()` has. No interaction log is written. Issue [#143](https://github.com/dlewissandy/teaparty/issues/143) tracks unifying these paths.

---

## Proxy Decision Model

The proxy is a statistical heuristic in `approval_gate.py`. It reads artifacts for mechanical pattern matching (CONFIRM markers, keyword overlap with past corrections, concern vocabulary, length anomalies) but does not reason about content semantically. Issue [#139](https://github.com/dlewissandy/teaparty/issues/139) tracks replacing it with a Claude agent that reads and reasons — the step required to reach the 85% prediction accuracy Park et al. demonstrated.

### `should_escalate()` — used by ApprovalGate

Returns `ProxyDecision`. Decision rules in priority order:

1. **Cold start guard**: < 5 observations for this (state, task_type) pair → escalate
2. **[CONFIRM:] markers**: artifact contains unresolved `[CONFIRM:...]` markers → escalate unconditionally
3. **Content checks** (`_check_content()`), in sub-priority order:
   - Length anomaly: artifact < 50% or > 200% of historical mean character count
   - Principle violation (Phase 2a): past corrections with reasoning — if the artifact doesn't contain keywords from the human's stated standard, escalate
   - Keyword match (Phase 2a fallback): past corrections without reasoning — if correction summary keywords appear in the artifact, escalate (signal the artifact may repeat a past mistake)
   - Concern patterns (Phase 2b): concern categories from question history (e.g., error_handling, security) raised >= 2 times — if the artifact doesn't contain keywords from the concern vocabulary, escalate
4. **Tier 1 pattern match**: flat behavioral patterns from `proxy-patterns.md` — if the artifact doesn't address known correction patterns for this state (< 30% keyword coverage), escalate
5. **Tier 2 retrieval**: past interactions from `.proxy-interactions.jsonl` — if > 50% of last 5 similar interactions at this state resulted in corrections, escalate
6. **Confidence threshold**: confidence < threshold → escalate. Binary states (ASSERT) require 0.8; generative states require 0.95
7. **Staleness guard**: > 7 days since last human signal → escalate to recalibrate
8. **Prediction drift**: prediction accuracy below 50% (min 5 predictions) → escalate
9. **Exploration rate**: 15% random escalation even when confident
10. **Auto-approve**: all checks passed

`_proxy_decide()` in `actors.py` wraps this with an elapsed-time guard (< 120s at execution states → escalate) and loads tier 1 patterns from `proxy-patterns.md` and tier 2 interactions from `.proxy-interactions.jsonl`.

### `generate_response()` — used by EscalationListener

Constructs a predicted human response from stored question patterns and text differentials. Returns `GenerativeResponse` (action, text, confidence) or None. Returns None if: cold start (< 5 observations), no stored differentials or question patterns, or confidence below threshold. When it does return, it assembles text from the most recent question pattern (with reasoning) and the most recent differential.

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

## Implementation Status

| Area | Status | Issue |
|------|--------|-------|
| AskQuestion MCP tool replaces file-based escalation | Done (open) | [#137](https://github.com/dlewissandy/teaparty/issues/137) |
| Differential recording (proxy prediction vs. human actual) | Done | [#138](https://github.com/dlewissandy/teaparty/issues/138) |
| Alignment validation framing at gates | Done | [#102](https://github.com/dlewissandy/teaparty/issues/102) |
| Cold-start intake dialog (Phase 1) | Done | [#125](https://github.com/dlewissandy/teaparty/issues/125) |
| Retrieval-backed prediction (tier 1 patterns + tier 2 interactions) | Done | [#11](https://github.com/dlewissandy/teaparty/issues/11) |
| Unify proxy paths (should_escalate vs. generate_response) | Open | [#143](https://github.com/dlewissandy/teaparty/issues/143) |
| Proxy must be an actual agent (reads artifacts, reasons) | Open | [#139](https://github.com/dlewissandy/teaparty/issues/139) |
| Intake dialog Phases 2–3 (prediction-comparison, rituals) | Design target | [#125](https://github.com/dlewissandy/teaparty/issues/125) |
| Text derivative learning (proxy self-assessment) | Design target | |

### References

- Park, J. S. et al. (2024). Generative agent simulations of 1,000 people. *arXiv:2411.10109*. 85% accuracy from conversational data + LLM reasoning.
- Salemi, A. & Zamani, H. (2024). Few-shot personalization of LLMs with mis-aligned responses — Fermi. *arXiv:2406.18678*. Misaligned responses are the highest-value learning signal.
