# Approval Gate and Human Proxy

Every question that needs a human decision follows one path:

1. **Statistical pre-filters** — cold start, staleness, content checks, exploration rate
2. **If stats say escalate** → skip the proxy agent, go straight to the human
3. **If stats pass** → invoke the **proxy agent** (a Claude session with file-read tools and learned patterns)
4. **Proxy agent generates text + confidence** — what it predicts the human would say
5. **If confident** → the agent's text IS the answer
6. **If not confident** → the same question goes to the human
7. **Both predicted text and actual text feed into learning**

This is implemented in `proxy_agent.py:consult_proxy()` — the single entry point for all proxy decisions. `ApprovalGate` (artifact review at ASSERT states) and `EscalationListener` (agent questions via AskQuestion MCP tool) both use it.

### Never-escalate states

TASK_ASSERT and TASK_ESCALATE are marked as **never-escalate**: the proxy still runs through the full path (statistical filters, agent invocation, confidence check) but if it's not confident, it goes with its best guess rather than bothering the human. If the proxy returned nothing, it defaults to approval. The human should never be interrupted for task-level review during execution — that would defeat the purpose of hierarchical delegation.

---

## Why Retrieval-Backed Question Answering Is the Priority

Park et al. (2024) built AI agents representing 1,052 real people from two-hour qualitative interviews. Those agents replicated individual survey responses with **85% accuracy** using LLM in-context reasoning over interview transcripts — no explicit ML model, no fine-tuning, just retrieval + reasoning.

This result is **motivating evidence** for the proxy's architecture, not a performance target for this system. The proxy accumulates conversational data about the human — differential corrections, question patterns, behavioral rituals, gate decisions — and uses retrieval to surface relevant history when answering a new question. By contextualizing retrieval by CfA phase, task type, project, and concern category, the proxy can achieve reasonable prediction accuracy at low cost — without fine-tuning, without a separate ML model, just scoped retrieval and LLM reasoning over accumulated interactions.

Measuring actual proxy accuracy on real escalations remains a critical validation gap.

This explains the priority ordering:

1. **Retrieval-backed prediction is the path to autonomy.** A proxy that predicts correctly most of the time handles most human involvement automatically. Each escalation produces a new differential that improves future predictions — the system can get better with use.

2. **The differential is the highest-value learning signal.** Salemi & Zamani (2024, Fermi) showed that misaligned responses — where the model predicted incorrectly — are more valuable for learning than correct predictions. Every proxy prediction that diverges from the human's actual answer tells the system exactly where its model is wrong.

---

## Proxy Maturity Levels

The approval gate's capabilities stack across three tiers:

**Tier 1 (Operational now):** Statistical filters + agent generative prediction. Cold start → escalate. Staleness → escalate. Confidence < threshold → escalate at ASSERT states. Confidence < threshold → use best guess at never-escalate states. This works without any learning system — the proxy can function immediately.

**Tier 2 (Design target, requires learning):** Retrieval-backed patterns from `.proxy-interactions.jsonl` and `proxy-patterns.md`. This requires learning extraction to build a signal history of differential corrections and question patterns. Tier 1 works standalone; Tier 2 improves accuracy.

**Tier 3 (Full vision, requires full learning system):** Scoped learning system feeds task-specific corrections into proxy context. Behavioral rituals, gap-detection questioning, and text derivative learning. Full accuracy improvement loop. This requires Tiers 1 and 2 plus the main learning system's integration.

The proxy architecture decouples Tier 1 from learning's completion — Tier 1 is operational now, and Tiers 2–3 improve it as learning integration advances.

---

## The Proxy Agent

`proxy_agent.py:consult_proxy()` is the single proxy invocation path:

1. **Proxy disabled?** → return empty result (experiment baseline)
2. **Elapsed-time guard**: TASK_ASSERT and WORK_ASSERT — if execution phase ran < 120 seconds, skip agent, escalate
3. **Load proxy model** and tier 1 patterns (`proxy-patterns.md`), tier 2 interactions (`.proxy-interactions.jsonl`)
4. **Statistical pre-filters** via `should_escalate()` — if stats say escalate, return empty result (no agent needed)
5. **Invoke proxy agent** via `run_proxy_agent()` — a Claude CLI session with file-read tools. The agent receives:
   - The gate question (e.g., "Do you recognize this as your idea?")
   - The artifact path and upstream context paths (INTENT.md, PLAN.md) — passed as file-read references, not pre-injected
   - Learned behavioral patterns from `proxy-patterns.md` (static, tier 1)
   - Similar past interactions from `.proxy-interactions.jsonl` (dynamic, tier 2)
   - Dialog history (for multi-turn conversations)
6. **Agent returns** text (what the human would say) + confidence (0.0–1.0)

### Proxy Agent Context Injection

The proxy agent receives file-read tools and artifact paths relative to the session worktree. Paths are passed as task references, not pre-loaded into the prompt. This allows the agent to read current versions at decision time and gives it control over what context to consider.

Specifically:
- Artifact paths (INTENT.md, PLAN.md) are resolved relative to the session worktree root
- The agent has file-read tools and can fetch these at runtime
- Proxy patterns (`proxy-patterns.md`) and interactions (`.proxy-interactions.jsonl`) are loaded from the approval gate store (not from the main learning system — this is a design debt noted in learning-system.md)
- The proxy agent prompt includes references to these file paths; the agent uses Read/Grep tools to access content

The caller (`ApprovalGate._ask_human_through_proxy`) decides based on confidence:
- confidence >= `PROXY_AGENT_CONFIDENCE_THRESHOLD` (0.8) → agent's text is the answer
- confidence < threshold AND state in `_NEVER_ESCALATE_STATES` → agent's text is still the answer (or 'Approved.' if empty)
- confidence < threshold → escalate to the actual human

---

## ApprovalGate (ASSERT states)

`ApprovalGate.run()` in `actors.py`. Invoked by `engine.py` at states where all outgoing CfA transitions have actor `human` or `approval_gate`: INTENT_ASSERT, PLAN_ASSERT, TASK_ASSERT, TASK_ESCALATE, and WORK_ASSERT.

ONE loop. Every turn: ask the human through the proxy. Classify the response. If terminal, done. If dialog, loop.

**Gate questions** (`_GATE_QUESTIONS`):
- INTENT_ASSERT: "Do you recognize this as your idea, completely and accurately articulated?"
- PLAN_ASSERT: "Do you recognize this as a strategic plan to operationalize your idea well?"
- TASK_ASSERT: "Does this work look like your task, correctly executed?"
- WORK_ASSERT: "Do you recognize the deliverables and project files as your idea, completely and well implemented?"

**Decision flow:**

```
if state in NEVER_ESCALATE_STATES:
  if proxy_returned_text:
    use text as answer (even if low confidence)
  else:
    use 'Approved.' as answer
else:
  if confidence >= PROXY_AGENT_CONFIDENCE_THRESHOLD:
    use text as answer
  else:
    escalate to human
```

**Full loop:**

1. Call `_ask_human_through_proxy()` with the gate question
2. `consult_proxy()` runs the full path (stats → agent → confidence check → maybe human)
3. Classify the response via `_classify_review()` (Haiku LLM call). Valid actions derived from CfA state machine per state.
4. If `dialog` or `__fallback__` → generate contextual reply via `_generate_dialog_response()` (Haiku), append to dialog history, loop back to step 1
5. If dialog occurred and final action is `approve` → convert to `correct` with the dialog as feedback, so the agent gets another pass with the human's context
6. Record outcome via `_proxy_record()` + `_log_interaction()`, return

---

## Never-Escalate Tradeoff

The never-escalate states (TASK_ASSERT, TASK_ESCALATE) implement a deliberate architectural choice:

**Goal:** Uninterrupted execution. The human is not bothered with task-level review questions during execution — they approved the plan; the agents should execute it without interruption.

**Cost:** Silent learning gaps. When the proxy is not confident but escalation is suppressed, the human never sees the decision, so no differential is recorded. This silence means the learning system misses high-value signals — misaligned responses are the most valuable for learning (Salemi & Zamani).

**Consequence:** Proxy improvement at task level depends on escalations at ASSERT states (intent, plan, work), not task-level corrections. Task-level corrections are invisible to the learning system.

**Design question for future:** Can task-level learnings be extracted from agent self-assessment instead of human correction? This would preserve the uninterrupted execution goal while capturing learning signals.

---

## EscalationListener (AskQuestion MCP tool)

`EscalationListener._route_through_proxy()` in `escalation_listener.py`. Invoked when an agent calls the `AskQuestion` MCP tool during its turn. The agent is still running — the answer returns as a tool result in the same turn.

Uses the same `consult_proxy()` path as ApprovalGate.

---

## Statistical Pre-Filters

`should_escalate()` in `approval_gate.py`. Returns `ProxyDecision`. Decision rules in priority order:

1. **Cold start guard**: < 5 observations for this (state, task_type) pair → escalate
2. **[CONFIRM:] markers**: artifact contains unresolved `[CONFIRM:...]` markers → escalate unconditionally
3. **Content checks** (`_check_content()`):
   - Length anomaly: artifact < 50% or > 200% of historical mean
   - Principle violation (Phase 2a): past corrections with reasoning — artifact doesn't contain keywords from the human's stated standard
   - Keyword match (Phase 2a fallback): correction summary keywords appear in the artifact
   - Concern patterns (Phase 2b): concern categories raised >= 2 times, artifact doesn't contain concern vocabulary
4. **Tier 1 pattern match**: `proxy-patterns.md` — artifact doesn't address known correction patterns (< 30% keyword coverage)
5. **Tier 2 retrieval**: `.proxy-interactions.jsonl` — > 50% of last 5 similar interactions resulted in corrections
6. **Confidence threshold**: confidence < threshold → escalate. ASSERT states require 0.8; generative states require 0.95
7. **Staleness guard**: > 7 days since last human signal → escalate
8. **Prediction drift**: prediction accuracy below 50% (min 5 predictions) → escalate
9. **Exploration rate**: 15% random escalation even when confident
10. **Auto-approve**: all checks passed → proxy agent runs

### Confidence Computation (Design Stage)

`compute_confidence()` = min(Laplace, EMA):
- **Laplace**: `(approve_count + 1) / (total_count + 2)`
- **EMA** (alpha=0.3): approval → +1 step; correction → -3 steps (asymmetric regret, REGRET_WEIGHT=3)

**Rationale for these choices:**

- **Laplace smoothing:** Chosen for bounded (0, 1) range and standard beta prior behavior. Prevents zero confidence from blocking all decisions.
- **min(Laplace, EMA):** Conservative blending — report the lower estimate to be cautious about confidence.
- **EMA alpha=0.3:** Exploratory choice; controls how quickly recent outcomes influence confidence. Not tuned to data.
- **REGRET_WEIGHT=3:** Asymmetric cost; corrections count three times as much as approvals. Reflects the intuition that the human's corrections are more informative than approvals. Not tuned to data.
- **Cold start behavior:** < 5 observations for a state/task pair always escalates, regardless of confidence. This prevents overfitting to early samples.

**Important:** These are exploratory constants, not literature-based or data-tuned. Tuning to real accuracy data is future work. This is not production-calibrated; validation experiments will guide refinement.

---

## Learning from Outcomes

`record_outcome()` records after every decision:

- Counter increments (approve, correct, reject, total)
- EMA update
- **Text differentials**: what the human changed, with the proxy's prediction as `predicted_response`
- **Artifact lengths**: historical char counts (max 20)
- **Question patterns**: extracted questions with concern category (max 20)
- **Prediction accuracy**: `prediction_correct_count` / `prediction_total_count`

Concern vocabulary: error_handling, rollback, security, idempotency, testing, documentation, sequencing, external_dependencies.

---

## Implementation Status

| Area | Status | Issue |
|------|--------|-------|
| AskQuestion MCP tool replaces file-based escalation | Done | [#137](https://github.com/dlewissandy/teaparty/issues/137) |
| Proxy is a real Claude agent with tools | Done | [#139](https://github.com/dlewissandy/teaparty/issues/139) |
| Differential recording (proxy prediction vs. human actual) | Done | [#138](https://github.com/dlewissandy/teaparty/issues/138) |
| Alignment validation questions at gates | Done | [#102](https://github.com/dlewissandy/teaparty/issues/102) |
| Cold-start intake dialog (Phase 1) | Done | [#125](https://github.com/dlewissandy/teaparty/issues/125) |
| Retrieval-backed prediction (tier 1 patterns + tier 2 interactions) | Done | [#11](https://github.com/dlewissandy/teaparty/issues/11) |
| Never-escalate for task-level gates (TASK_ASSERT, TASK_ESCALATE) | Done | [#139](https://github.com/dlewissandy/teaparty/issues/139) |
| Unified proxy path (consult_proxy for all entry points) | Done | [#143](https://github.com/dlewissandy/teaparty/issues/143) |
| Intake dialog Phases 2–3 (prediction-comparison, rituals) | Design target | [#125](https://github.com/dlewissandy/teaparty/issues/125) |
| Text derivative learning (proxy self-assessment) | Design target | |
| Proxy accuracy measurement on real escalations | Design target | |

### References

- Park, J. S. et al. (2024). Generative agent simulations of 1,000 people. *arXiv:2411.10109*. 85% accuracy from conversational data + LLM reasoning — motivating evidence for retrieval-backed prediction.
- Salemi, A. & Zamani, H. (2024). Few-shot personalization of LLMs with mis-aligned responses — Fermi. *arXiv:2406.18678*. Misaligned responses are the highest-value learning signal.
