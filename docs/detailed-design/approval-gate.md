# Approval Gate and Human Proxy

Every question that needs a human decision follows one path:

1. **Gather context** — ACT-R memory retrieval, learned patterns, similar past interactions
2. **Two-pass prediction** — prior (without artifact) then posterior (with artifact)
3. **Cold-start calibration** — cap confidence if ACT-R memory depth is shallow
4. **Proxy agent generates text + confidence** — what it predicts the human would say
5. **If confident** → the agent's text IS the answer
6. **If not confident** → the same question goes to the human
7. **Both predicted text and actual text feed into learning** (ACT-R memory chunks)

The proxy agent always runs. Statistics never gate whether the agent is consulted — they are tracked for monitoring only. Confidence calibration happens post-hoc, after the agent has responded.

This is implemented in `proxy_agent.py:consult_proxy()` — the single entry point for all proxy decisions. `ApprovalGate` (artifact review at ASSERT states) and `EscalationListener` (agent questions via AskQuestion MCP tool) both use it.

### Never-escalate states

TASK_ASSERT and TASK_ESCALATE are marked as **never-escalate**: the proxy runs through the full path (context gathering, two-pass prediction, confidence calibration) but if it's not confident, it goes with its best guess rather than bothering the human. If the proxy returned nothing, it defaults to approval. The human should never be interrupted for task-level review during execution — that would defeat the purpose of hierarchical delegation.

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

**Tier 1 (Operational now):** Two-pass prediction + cold-start calibration via ACT-R memory depth. The proxy agent always runs. If ACT-R memory depth is below `MEMORY_DEPTH_THRESHOLD` (3 distinct state/task-type pairs), confidence is capped at 0.5 so the caller knows the proxy lacks experience breadth. Confidence < threshold → escalate at ASSERT states; use best guess at never-escalate states.

**Tier 2 (Operational now):** Retrieval-backed patterns from `.proxy-interactions.jsonl` (legacy similar interactions) and `proxy-patterns.md` (flat behavioral patterns). These are loaded as context for the proxy agent's two-pass prediction. ACT-R memory chunks (Tier 3) supplement these with structured retrieval.

**Tier 3 (Operational now):** ACT-R memory retrieval feeds task-specific memories into proxy context. Memory chunks carry situation, stimulus, and outcome data, retrieved via hybrid BM25 + vector search. Retrieved chunks are reinforced after the proxy agent consumes them (ACT-R Rule 2). Behavioral rituals, gap-detection questioning, and text derivative learning remain design targets.

All three tiers are wired into `consult_proxy()`. The proxy architecture was designed to decouple tiers, but all three now contribute to every proxy invocation.

---

## The Proxy Agent

`proxy_agent.py:consult_proxy()` is the single proxy invocation path:

1. **Proxy disabled?** → return empty result (experiment baseline)
2. **Elapsed-time guard**: TASK_ASSERT and WORK_ASSERT — if execution phase ran < `MIN_EXECUTION_SECONDS`, skip agent, escalate
3. **Gather learning context**:
   - Tier 1: read flat behavioral patterns from `proxy-patterns.md`
   - Tier 2: retrieve similar past interactions from `.proxy-interactions.jsonl`
   - Tier 3: ACT-R memory retrieval via `_retrieve_actr_memories()` — hybrid BM25 + vector search over structured memory chunks, scoped by state and task type
4. **Two-pass prediction** via `run_proxy_agent()` — a Claude CLI session with file-read tools:
   - **Pass 1 (prior)**: predict without seeing the artifact, using only memories and learned patterns
   - **Pass 2 (posterior)**: predict after reading the artifact + prior prediction
   - **Surprise detection**: if the action changed or confidence shifted > 0.3 between passes, extract what in the artifact caused the shift (salient percepts)
   - The agent receives: gate question, artifact/upstream context paths (file references, not pre-injected), ACT-R memory chunks, learned patterns, similar interactions, dialog history
5. **Reinforce ACT-R memories** — retrieved chunks get a retrieval trace after the agent has consumed them (ACT-R Rule 2: post-consumption reinforcement)
6. **Cold-start calibration** via `_calibrate_confidence()` — if ACT-R memory depth (distinct state/task-type pairs) is below `MEMORY_DEPTH_THRESHOLD` (3), cap confidence at 0.5
7. **Agent returns** text (what the human would say) + calibrated confidence (0.0–1.0)

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
2. `consult_proxy()` runs the full path (context gathering → two-pass prediction → calibration → maybe human)
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

## Confidence and Cold-Start Gating

The proxy agent's self-assessed confidence (from two-pass prediction) is the decision signal. The system calibrates this based on ACT-R memory depth:

**Cold-start guard:** `_calibrate_confidence()` checks the ACT-R memory store for experience diversity — the number of distinct (state, task_type) pairs. If memory depth is below `MEMORY_DEPTH_THRESHOLD` (3), confidence is capped at 0.5 regardless of the agent's self-assessment. A proxy with diverse memories across multiple states and task types has demonstrated understanding; one with shallow or missing memory has not.

**EMA tracking:** EMA is tracked separately as a system health monitor via `_proxy_record()` in `actors.py`. It does not influence the confidence returned by `consult_proxy()` — it is observational only. EMA uses alpha=0.3 with asymmetric regret (REGRET_WEIGHT=3: corrections count 3x as much as approvals).

**Threshold:** The caller (`ApprovalGate._ask_human_through_proxy`) compares the calibrated confidence against `PROXY_AGENT_CONFIDENCE_THRESHOLD` (0.8). Above threshold → agent's text is the answer. Below threshold at never-escalate states → agent's text is still the answer. Below threshold otherwise → escalate to human.

### Legacy Statistical Pre-Filters

`should_escalate()` in `scripts/approval_gate.py` implements a 10-step statistical pre-filter pipeline (cold start, staleness, content checks, exploration rate, etc.). This function is not called by the orchestrator — the proxy agent always runs. `should_escalate()` is available as a CLI tool (`--decide`) and may be reintegrated as a monitoring or audit signal in the future, but it does not gate proxy invocation.

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
| Two-pass prediction (prior/posterior) | Done | [#179](https://github.com/dlewissandy/teaparty/issues/179) |
| ACT-R memory retrieval in proxy flow | Done | [#179](https://github.com/dlewissandy/teaparty/issues/179) |
| Cold-start gating via ACT-R memory depth | Done | [#220](https://github.com/dlewissandy/teaparty/issues/220) |
| EMA decoupled from confidence scoring | Done | [#220](https://github.com/dlewissandy/teaparty/issues/220) |
| Post-consumption reinforcement of retrieved chunks | Done | [#219](https://github.com/dlewissandy/teaparty/issues/219) |
| Intake dialog Phases 2–3 (prediction-comparison, rituals) | Design target | [#125](https://github.com/dlewissandy/teaparty/issues/125) |
| Text derivative learning (proxy self-assessment) | Design target | |
| Proxy accuracy measurement on real escalations | Design target | |

### References

- Park, J. S. et al. (2024). Generative agent simulations of 1,000 people. *arXiv:2411.10109*. 85% accuracy from conversational data + LLM reasoning — motivating evidence for retrieval-backed prediction.
- Salemi, A. & Zamani, H. (2024). Few-shot personalization of LLMs with mis-aligned responses — Fermi. *arXiv:2406.18678*. Misaligned responses are the highest-value learning signal.
