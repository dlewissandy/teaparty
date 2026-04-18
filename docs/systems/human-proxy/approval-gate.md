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

**Tier 1 (Operational now):** Two-pass prediction + cold-start calibration via ACT-R memory depth. The proxy agent always runs. The memory-depth cold-start mechanism caps confidence at 0.5 when ACT-R memory depth falls below `MEMORY_DEPTH_THRESHOLD`; the threshold is currently set to `0` (see commit `4f9d16ea`, 2026-04-17). The mechanism is in place and will be re-tuned in the milestone-4 skill-graph rewrite ([#337](https://github.com/dlewissandy/teaparty/issues/337)). The per-gate confidence check (confidence < 0.8 → escalate at ASSERT states; use best guess at never-escalate states) runs unchanged.

**Tier 2 (Operational now):** Retrieval-backed patterns from `.proxy-interactions.jsonl` (legacy similar interactions) and `proxy-patterns.md` (flat behavioral patterns). These are loaded as context for the proxy agent's two-pass prediction. ACT-R memory chunks (Tier 3) supplement these with structured retrieval.

**Tier 3 (Operational now):** ACT-R memory retrieval feeds task-specific memories into proxy context. Memory chunks carry situation, stimulus, and outcome data, retrieved via two-stage ranking: activation filter (power-law decay) then composite scoring (normalized activation + multi-dimensional cosine similarity). Retrieved chunks are reinforced after the proxy agent consumes them (ACT-R Rule 2). Contradiction detection identifies conflicting memory pairs (same state/task_type, different outcome) and classifies them via a two-tier pipeline: heuristic triage (`classify_conflict()` in `proxy_memory.py`) then LLM-as-judge reclassification for ambiguous cases (`_classify_conflict_llm()` in `proxy_agent.py`). Conflict context is injected into the proxy prompt so the agent can reason about contradictions. Per-context prediction accuracy is tracked per (state, task_type) pair in `proxy_accuracy` table (`proxy_memory.py`), recording prior and posterior match rates. Behavioral rituals, gap-detection questioning, and text derivative learning remain design targets.

All three tiers are wired into `consult_proxy()`. The proxy architecture was designed to decouple tiers, but all three now contribute to every proxy invocation.

---

## The Proxy Agent

`proxy_agent.py:consult_proxy()` is the single proxy invocation path:

1. **Proxy disabled?** → return empty result (experiment baseline)
2. **Gather learning context**:
   - Tier 1: read flat behavioral patterns from `proxy-patterns.md`
   - Tier 2: retrieve similar past interactions from `.proxy-interactions.jsonl`
   - Tier 3: ACT-R memory retrieval via `_retrieve_actr_memories()` — two-stage retrieval: activation filter (power-law decay over retrieval traces), then composite ranking (normalized activation + multi-dimensional cosine similarity), scoped by state and task type
3. **Two-pass prediction** via `run_proxy_agent()` — a Claude CLI session with file-read tools:
   - **Pass 1 (prior)**: predict without seeing the artifact, using only memories and learned patterns
   - **Pass 2 (posterior)**: predict after reading the artifact + prior prediction
   - **Surprise detection**: if confidence shifted > 0.3 between passes, extract what in the artifact caused the shift (salient percepts + a one-sentence description). Pre-583cccd8, a separate action-change branch also triggered surprise; that was retired when prompts stopped emitting categorical ACTION tokens — categorical classification now happens downstream on the final response via `_classify_review`.
   - The agent receives: gate question, artifact/upstream context paths (file references, not pre-injected), ACT-R memory chunks, learned patterns, similar interactions, dialog history
4. **Reinforce ACT-R memories** — retrieved chunks get a retrieval trace after the agent has consumed them (ACT-R Rule 2: post-consumption reinforcement)
5. **Cold-start calibration** via `_calibrate_confidence()` — mechanism still in place; threshold currently `0` (see Tier 1 note above and commit `4f9d16ea`)
6. **Agent returns** text (what the human would say) + calibrated confidence (0.0–1.0)

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

**Gate bridge composition** (`_GATE_TEMPLATES` + `_generate_bridge`):

The gate sends a self-contained message to the reviewer — same discipline as the Send tool. Three slots, consistent across every gate:

1. `Decide: <decision>` — what decision is being requested (verb + object).
2. `Available:` — the files that may help, each with a one-line purpose.
3. The actor's own triggering message — what the agent wrote as they hit the gate. The gate does not fabricate a substitute.

Slots 1 and 2 come from `_GATE_TEMPLATES`; slot 3 comes from the previous actor's last assistant text, plumbed via `ActorResult.data['actor_message']`.

Per-gate decisions:
- INTENT_ASSERT: "Approve or revise the proposed intent."
- PLAN_ASSERT: "Approve or revise the proposed plan."
- TASK_ASSERT: "Accept or correct this sub-task output."
- TASK_ESCALATE: "Resolve the worker's escalation."
- WORK_ASSERT: "Approve or revise the overall deliverable."

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

The proxy agent's self-assessed confidence (from two-pass prediction) is the decision signal. `_calibrate_confidence()` applies six gates in order:

**Cold-start guard:** Checks the ACT-R memory store for experience diversity — the number of distinct (state, task_type) pairs. If memory depth is below `MEMORY_DEPTH_THRESHOLD`, confidence is capped at 0.5 regardless of the agent's self-assessment. The mechanism is operational but the threshold is currently set to `0` (effectively disabled on fresh projects). Commit `4f9d16ea` (2026-04-17) relaxed it because the old `3` threshold caused every fresh-project gate to escalate, forcing humans into rubber-stamping. With the improved conversational prompts, probe-or-paraphrase gate instructions, and classifier, the proxy's self-reported confidence is trustworthy enough to drive clear-cut gates from turn one; the other guards in this section still run. The threshold — and the whole calibration stack — is slated for re-tuning in the milestone-4 skill-graph rewrite ([#337](https://github.com/dlewissandy/teaparty/issues/337)).

**Genuine tension guard (#228):** If retrieved memories contain a genuine unresolved tension (`has_genuine_tension` from conflict classification), confidence is capped at 0.5 to force escalation. The proxy cannot resolve a genuine tension without human input.

**Staleness guard (#237):** If `proxy_accuracy.last_updated` for the current (state, task_type) is older than `STALENESS_DAYS` (7), confidence is capped at 0.5. Preferences drift; the model must not converge to an outdated snapshot.

**Exploration rate (#237):** With probability `EXPLORATION_RATE` (0.15), confidence is capped at 0.5 regardless of all other signals. This prevents convergence to "always auto-approve" and ensures the model continues to see human decisions for ongoing calibration.

**Accuracy-based autonomy (#226):** If per-context posterior accuracy is available (>= `ACCURACY_MIN_INTERACTIONS` (10) interactions), the proxy's track record gates the decision. If posterior accuracy is below `ACCURACY_AUTONOMY_THRESHOLD` (0.85), confidence is capped. Above threshold, the agent's self-assessed confidence passes through.

**Passthrough:** If none of the above gates fire, the agent's self-assessed confidence is returned unchanged.

**EMA tracking:** EMA is tracked separately as a system health monitor via `_proxy_record()` in `actors.py`. It does not influence the confidence returned by `consult_proxy()` — it is observational only. EMA uses alpha=0.3 with asymmetric regret (REGRET_WEIGHT=3: corrections count 3x as much as approvals).

**Threshold:** The caller (`ApprovalGate._ask_human_through_proxy`) compares the calibrated confidence against `PROXY_AGENT_CONFIDENCE_THRESHOLD` (0.8). Above threshold → agent's text is the answer. Below threshold at never-escalate states → agent's text is still the answer. Below threshold otherwise → escalate to human.

### CLI Monitoring Tool

`should_escalate()` in `teaparty/proxy/approval_gate.py` is available as a CLI tool (`--decide`) for monitoring and audit.

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
| Cold-start gating mechanism via ACT-R memory depth | Built; threshold relaxed to 0 (see `4f9d16ea`; slated for re-tune in [#337](https://github.com/dlewissandy/teaparty/issues/337)) | [#220](https://github.com/dlewissandy/teaparty/issues/220) |
| EMA decoupled from confidence scoring | Done | [#220](https://github.com/dlewissandy/teaparty/issues/220) |
| Post-consumption reinforcement of retrieved chunks | Done | [#219](https://github.com/dlewissandy/teaparty/issues/219) |
| Contradiction detection and resolution in proxy memory | Done | [#228](https://github.com/dlewissandy/teaparty/issues/228) |
| LLM-as-judge conflict classification (two-tier: heuristic then LLM) | Done | [#228](https://github.com/dlewissandy/teaparty/issues/228) |
| Asymmetric confidence decay (Hindsight, arXiv:2512.12818) | Done | [#228](https://github.com/dlewissandy/teaparty/issues/228) |
| Post-session proxy memory consolidation | Done | [#228](https://github.com/dlewissandy/teaparty/issues/228) |
| Per-context prediction accuracy tracking per (state, task_type) | Done | [#226](https://github.com/dlewissandy/teaparty/issues/226) |
| Proxy-learning integration (bidirectional feedback) | Done | [#198](https://github.com/dlewissandy/teaparty/issues/198) |
| Salience index separated from chunk embeddings | Done | [#227](https://github.com/dlewissandy/teaparty/issues/227) |
| Embedding wired into proxy pattern compaction | Done | [#214](https://github.com/dlewissandy/teaparty/issues/214) |
| ACT-R Phase 1 ablation harness (evaluation metrics) | Done | [#221](https://github.com/dlewissandy/teaparty/issues/221) |
| Ablation: multi-dim vs single blended embedding | Done | [#222](https://github.com/dlewissandy/teaparty/issues/222) |
| Ablation: activation decay vs simple recency | Done | [#223](https://github.com/dlewissandy/teaparty/issues/223) |
| Ablation: composite scoring vs activation-only and similarity-only | Done | [#225](https://github.com/dlewissandy/teaparty/issues/225) |
| Intake dialog Phases 2–3 (prediction-comparison, rituals) | Design target | [#125](https://github.com/dlewissandy/teaparty/issues/125) |
| Text derivative learning (proxy self-assessment) | Design target | |
| Proxy accuracy measurement on real escalations | Design target | |

### References

- Park, J. S. et al. (2024). Generative agent simulations of 1,000 people. *arXiv:2411.10109*. 85% accuracy from conversational data + LLM reasoning — motivating evidence for retrieval-backed prediction.
- Salemi, A. & Zamani, H. (2024). Few-shot personalization of LLMs with mis-aligned responses — Fermi. *arXiv:2406.18678*. Misaligned responses are the highest-value learning signal.
