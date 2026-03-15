# Approval Gate and Human Proxy

Every question that needs a human decision follows ONE path:

1. **Ask the human through the proxy** — `consult_proxy()` in `proxy_agent.py`
2. **Classify the response** — `_classify_review()` via `classify_review.classify()` (Haiku)
3. **If terminal action** — record, return
4. **If dialog** — loop back to step 1

The proxy is a Claude agent with file-read tools.  It reads the artifact, considers learned behavioral patterns and past interactions, and generates a full text response — what it predicts the human would say.  If confident, its text IS the answer.  If not, the same question goes to the actual human.  The approval gate does not know or care which source produced the text.

---

## Why Retrieval-Backed Question Answering Is the Priority

Park et al. (2024) built AI agents representing 1,052 real people from two-hour qualitative interviews. Those agents replicated individual survey responses with **85% accuracy** using LLM in-context reasoning over interview transcripts — no explicit ML model, no fine-tuning, just retrieval + reasoning.

This result is the empirical basis for the proxy's architecture. The proxy accumulates conversational data about the human — differential corrections, question patterns, behavioral rituals, gate decisions — and uses retrieval to surface relevant history when answering a new question. By contextualizing retrieval by CfA phase, task type, project, and concern category, the proxy can achieve reasonable prediction accuracy at low cost — without fine-tuning, without a separate ML model, just scoped retrieval and LLM reasoning over accumulated interactions.

The differential is the highest-value learning signal. Salemi & Zamani (2024, Fermi) showed that misaligned responses — where the model predicted incorrectly — are more valuable for learning than correct predictions. Every proxy prediction that diverges from the human's actual answer tells the system exactly where its model is wrong.

---

## The Single Proxy Path: `consult_proxy()`

`proxy_agent.consult_proxy()` is the ONE entry point for all proxy decisions. Both `ApprovalGate` (artifact review at gates) and `EscalationListener` (agent questions via MCP AskQuestion) call it.

**Flow inside `consult_proxy()`:**

1. **Proxy disabled?** → return immediately (from_agent=False), caller asks human
2. **Elapsed-time guard:** At TASK_ASSERT and WORK_ASSERT, if < `MIN_EXECUTION_SECONDS` (120s) → return immediately
3. **Load proxy model** via `resolve_team_model_path()` + `load_model()`
4. **Load learned patterns** from `proxy-patterns.md` (tier 1)
5. **Retrieve similar interactions** from `.proxy-interactions.jsonl` (tier 2)
6. **Run statistical pre-filters** via `should_escalate()`:
   - Cold start (< 5 observations) → escalate
   - [CONFIRM:] markers → escalate
   - Content checks (length anomaly, principle violation, keyword match, concern patterns)
   - Tier 1 pattern match
   - Tier 2 retrieval correction rate
   - Confidence below threshold → escalate
   - Staleness guard (> 7 days) → escalate
   - Prediction drift → escalate
   - Exploration rate (15%) → escalate
7. **All checks pass** → invoke the proxy agent

**Proxy agent invocation** (`run_proxy_agent()`):

- Invokes `claude -p` with `--allowedTools Read,Glob,Grep,Bash`
- Prompt includes: question, artifact path, upstream context paths, learned patterns, past interactions, dialog history
- Agent reads files, reasons, generates text + self-assessed confidence (`CONFIDENCE: 0.85`)
- Returns `ProxyResult(text, confidence, from_agent=True)`

**Parameters:**

| Parameter | Purpose |
|-----------|---------|
| `question` | The gate question or agent's question |
| `state` | CfA state (INTENT_ASSERT, PLAN_ASSERT, etc.) |
| `project_slug` | Project identifier for model lookup |
| `artifact_path` | Path to artifact under review |
| `session_worktree` | Worktree root (agent's cwd for file reads) |
| `infra_dir` | Infrastructure dir (INTENT.md, PLAN.md locations) |
| `proxy_model_path` | Path to `.proxy-confidence.json` |
| `team` | Team name for per-team model resolution |
| `phase_start_time` | For elapsed-time guard |
| `proxy_enabled` | False to skip agent (experiment baseline) |
| `dialog_history` | Prior dialog turns for multi-turn context |

---

## Entry Point 1: ApprovalGate (artifact review)

`ApprovalGate.run()` in `actors.py`. Invoked by `engine.py` at INTENT_ASSERT, PLAN_ASSERT, and WORK_ASSERT.

TASK_ASSERT is **not** routed to ApprovalGate — its CfA actor is `execution_worker`.

**The loop:**

```
while True:
    response = ask_human_through_proxy(question, dialog_history)
    action = classify(response)
    if terminal: record, return
    dialog_history += response
```

`_ask_human_through_proxy()` calls `consult_proxy()`.  If the proxy is confident, its text is the response.  If not, the human is asked via `input_provider` (TUI).

**Classification:** `_classify_review()` calls `classify_review.classify()` (Haiku). Valid actions derived from the CfA state machine per state, with `dialog` prepended. `__fallback__` on classification failure.

**Recording:** `_proxy_record()` calls `record_outcome()` with outcome, differential summary, artifact length, extracted question patterns, and proxy prediction. `_log_interaction()` appends to `.proxy-interactions.jsonl` for tier 2 retrieval.

---

## Entry Point 2: EscalationListener (AskQuestion MCP tool)

`EscalationListener._route_through_proxy()` in `escalation_listener.py`. Invoked when an agent calls the `AskQuestion` MCP tool during its turn.

**Flow:**

1. Call `consult_proxy()` — same path as ApprovalGate, same guards, same agent
2. **Confident** → return proxy answer directly
3. **Not confident** → ask human via `_ask_human()` → `input_provider` (TUI)
4. Record differential via `record_outcome()`
5. Return answer to agent as MCP tool result

Same `consult_proxy()`, same statistical pre-filters, same agent invocation.

---

## Confidence Computation

`compute_confidence()` returns the minimum of two signals:
- **Laplace estimate**: `(approve_count + 1) / (total_count + 2)` — stable long-term
- **EMA** (alpha=0.3): approval nudges up by 1 step; correction nudges down by 3 steps (asymmetric regret)

### Design choices

- **Dual-signal confidence (Laplace + EMA)**: Taking the minimum ensures both signals agree — least-regret strategy.
- **Asymmetric regret (REGRET_WEIGHT=3)**: A false approval costs 3x more than a false escalation.
- **Exploration rate (15%)**: Prevents permanent overconfidence.
- **Per-team JSON persistence**: `.proxy-confidence-{team}.json` — one file per team.

---

## Learning from Outcomes

`record_outcome()` records after every human decision:

- Counter increments (approve, correct, reject, total)
- EMA update (approval → +1 step; correction → -3 steps)
- **Text differentials**: summary of what the human changed, reasoning, timestamped, with the proxy's prediction stored as `predicted_response`
- **Artifact lengths**: historical char counts (max 20 per entry)
- **Question patterns**: extracted questions with concern category and disposition (max 20 per entry)
- **Prediction accuracy tracking**: `prediction_correct_count` / `prediction_total_count`

Both entry points record outcomes through `record_outcome()`.

---

## Implementation Status

| Area | Status | Issue |
|------|--------|-------|
| Proxy is a Claude agent (reads artifacts, reasons, dialog) | Done | [#139](https://github.com/dlewissandy/teaparty/issues/139) |
| Unified proxy path (one `consult_proxy` for all decisions) | Done | [#139](https://github.com/dlewissandy/teaparty/issues/139) |
| AskQuestion MCP tool replaces file-based escalation | Done | [#137](https://github.com/dlewissandy/teaparty/issues/137) |
| Differential recording (proxy prediction vs. human actual) | Done | [#138](https://github.com/dlewissandy/teaparty/issues/138) |
| Alignment validation framing at gates | Done | [#102](https://github.com/dlewissandy/teaparty/issues/102) |
| Cold-start intake dialog (Phase 1) | Done | [#125](https://github.com/dlewissandy/teaparty/issues/125) |
| Retrieval-backed prediction (tier 1 patterns + tier 2 interactions) | Done | [#11](https://github.com/dlewissandy/teaparty/issues/11) |
| Intake dialog Phases 2–3 (prediction-comparison, rituals) | Design target | [#125](https://github.com/dlewissandy/teaparty/issues/125) |
| Text derivative learning (proxy self-assessment) | Design target | |

### References

- Park, J. S. et al. (2024). Generative agent simulations of 1,000 people. *arXiv:2411.10109*. 85% accuracy from conversational data + LLM reasoning.
- Salemi, A. & Zamani, H. (2024). Few-shot personalization of LLMs with mis-aligned responses — Fermi. *arXiv:2406.18678*. Misaligned responses are the highest-value learning signal.
