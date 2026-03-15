# Approval Gate and Human Proxy

The approval gate (`projects/POC/scripts/approval_gate.py`) implements the confidence-based proxy decision model described in [human-proxies.md](../human-proxies.md). It is integrated with the orchestrator — `ApprovalGate` in `actors.py` wraps the approval gate and is invoked by `engine.py` at ASSERT and ESCALATE states.

---

## Design Choices

**Dual-signal confidence (Laplace + EMA).** Confidence is the minimum of two signals rather than one. The Laplace estimate provides stability (it converges slowly, preventing premature confidence from a few positive signals). The EMA provides recency weighting (recent corrections matter more than old ones). Taking the minimum ensures both signals must agree before the proxy acts autonomously — a least-regret strategy.

**Asymmetric regret weighting (REGRET_WEIGHT=3).** A false approval (proxy approves work the human would have corrected) costs 3x more than a false escalation (proxy asks the human unnecessarily). This is a deliberate bias toward caution: annoying the human with an extra question is reversible; letting bad work through is not. The weight is configurable but 3x reflects the observation that correction is more expensive than confirmation.

**Exploration rate (15%).** Even when the proxy is confident, it escalates 15% of the time. This prevents the proxy from becoming permanently overconfident in a stable regime — it continues to gather human signal even for state-task pairs it thinks it understands. The tradeoff is a floor on human interruption: the proxy can never achieve fully autonomous operation.

**Per-team JSON persistence.** The proxy model is stored as `.proxy-confidence-{team}.json` — one file per team, persisted in the session infrastructure directory. This aligns with the worktree isolation model and avoids shared database dependencies. Each team's proxy evolves independently.

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

---

## Decision Rules (in priority order)

1. **Cold start guard**: < 5 observations for this state-task pair → always escalate
2. **Content checks** (if artifact provided):
   - Length anomaly: artifact < 50% or > 200% of historical mean length
   - Keyword matching: artifact matches past correction patterns
   - Concern patterns: repeated question categories not addressed
   - `[CONFIRM:]` markers: unconditional escalation
3. **Confidence threshold**: Binary states (ASSERT) require 0.8; generative states (ESCALATE) require 0.95
4. **Staleness guard**: > 7 days since last human signal → escalate to recalibrate
5. **Exploration rate**: 15% probability of escalation even when confident

---

## Confidence Computation

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

Concern vocabulary covers 8 categories: error_handling, rollback, security, idempotency, testing, documentation, sequencing, external_dependencies.

---

## Generative Prediction

`generate_response(model, state, task_type)` constructs a predicted human response from stored question patterns and text differentials. Returns `GenerativeResponse` (predicted action, text, confidence) or None if insufficient data.

---

## Gaps Against Conceptual Design

**Alignment validation framing.** The bridge prompts currently summarize the artifact from the agent's perspective ("I've drafted a plan...") rather than asking the proxy/human to validate alignment. The conceptual design describes each gate as an alignment validation question: "Do you recognize this as your idea?" at INTENT_ASSERT, "Do you recognize this as a strategic plan to operationalize your idea?" at PLAN_ASSERT, "Do you recognize the deliverables as your idea, well implemented?" at WORK_ASSERT. The prompts should also inject the upstream artifacts as context (INTENT.md at PLAN_ASSERT; INTENT.md + PLAN.md at WORK_ASSERT) so the proxy can compare across the full chain. Issue [#102](https://github.com/dlewissandy/teaparty/issues/102) tracks this.

**Intake dialog.** Phase 1 of the intake dialog is implemented ([#125](https://github.com/dlewissandy/teaparty/issues/125)): cold-start detection exposes the proxy's observation count to agents, agent prompts default to exploration and engagement on cold start, and escalation bridge text is framed as "the agent wants to discuss" rather than "agent escalated." Phases 2–3 (prediction-comparison loop, text derivative learning, ritual detection, graduated autonomy) remain design targets.

**Retrieval-backed prediction.** `generate_response` constructs predictions from locally stored differentials and question patterns. The conceptual design describes prediction through scoped retrieval from the learning system. Depends on the learning pipeline (issues [#73–#80](https://github.com/dlewissandy/teaparty/issues/73), [#115](https://github.com/dlewissandy/teaparty/issues/115)).

**Text derivative learning.** The current implementation stores differentials (what the human changed) but not the proxy's self-assessment of *why its model was wrong*. The conceptual design describes this reflection step as the primary learning signal.

**Behavioral rituals.** Detection of invariant practices tied to CfA states (e.g., human always asks for TLDR before reviewing a plan). Part of [#125](https://github.com/dlewissandy/teaparty/issues/125) scope.

**Gap-detection questioning.** Three triggers for asking rather than predicting (no retrieval hits, contradictory retrieval, novel concerns). Depends on retrieval-backed prediction.
