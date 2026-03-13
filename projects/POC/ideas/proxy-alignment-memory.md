# Idea: Proxy alignment memory — a dedicated learning system for the human proxy

## The distinction

There are two fundamentally different kinds of memory in the orchestrator, and they are currently tangled:

**Institutional memory** is about the project. What the architecture looks like, what conventions the team uses, what constraints exist, what was tried before and why it failed. It answers: *what is true about this work?*

**Proxy alignment memory** is about the human. How they review, what they focus on, what language patterns signal approval vs. discomfort, when they intervene and when they let things go, what standards they apply implicitly that they've never written down. It answers: *what would this person say here?*

These are orthogonal. A proxy that knows everything about the project's architecture but nothing about the human's review habits will make confident decisions on the wrong axis. A proxy that perfectly mimics the human's tone but knows nothing about the domain will pattern-match on surface signals and miss substantive issues.

The current system conflates them. `proxy.md` is injected verbatim alongside `institutional.md`. The `.proxy-confidence.json` model stores statistical counts, text differentials, and conversation transcripts in a flat structure keyed by `(state, task_type)`. There is no retrieval — the model is loaded whole every time. There is no separation between "the human cares about error handling" (a stable trait) and "the human corrected the CLIN citation" (a one-time factual fix that happened to pass through the approval gate).

## What proxy alignment memory should be

### The signal source

Every human utterance at a CfA decision point is alignment data. Not just the action (approve/correct/reject) but the full texture of the interaction:

- **What they said** — the literal words, before classification strips them to an action.
- **What the proxy predicted** — what the proxy expected the human to say (currently tracked as `predicted_response` in `ProxyDecision` but not persisted after the decision).
- **The delta** — the gap between prediction and reality. This is the learning signal. A proxy that predicted "approve" and got "correct: add error handling" has learned something specific about this human's standards.
- **The context** — what artifact was being reviewed, at what CfA state, in what project, at what point in the session lifecycle. The same human may have different standards at intent review vs. work review.
- **The pattern over time** — a single correction is an event. The same correction recurring across sessions is a trait. The proxy needs to distinguish between these.

### Two tiers of proxy memory

**Tier 1: Flat injection (unconditional).** A compact set of durable behavioral patterns — the proxy equivalent of "this is who I am." Injected into every proxy decision, regardless of context. Examples:

- "Darrell consistently rejects plans that don't address error handling. This has occurred in 7 of 12 plan reviews."
- "At INTENT_ASSERT, Darrell approves when the scope is clearly bounded but corrects when the intent is open-ended. The correction pattern is to add explicit non-goals."
- "Darrell's approval language is terse ('looks good', 'ship it'). Extended responses always signal either a correction or a question. Interpret response length as a proxy for satisfaction."

These are distilled from many observations. They should be periodically re-derived (compacted) as new data accumulates, not appended indefinitely. The flat memory should be small enough to fit in a single context injection — a page or less.

**Tier 2: Fuzzy retrieval (context-dependent).** The full corpus of past interactions, indexed for retrieval by situation. When the proxy faces a decision, it retrieves the most relevant past interactions based on:

- CfA state (am I reviewing an intent, a plan, or work?)
- Domain/project type (is this a research paper, a coding task, an operations change?)
- Artifact content (does this artifact touch topics the human has corrected before?)
- Recency (recent interactions are more predictive than old ones)

This is the same retrieval architecture as `memory_indexer.py` — BM25 + optional embeddings, prominence-weighted, MMR-diversified — but the source corpus is proxy interaction history, not project learnings.

### The learning loop

Each decision point is a learning cycle:

```
1. Context arrives (artifact, state, project)
2. Proxy retrieves relevant past interactions (tier 2)
3. Proxy reads flat behavioral patterns (tier 1)
4. Proxy makes a prediction: action + predicted response text
5. Decision: auto-approve or escalate

If escalated:
6. Human responds
7. Response is classified into action + feedback
8. The (prediction, reality, delta, context) tuple is stored
9. If delta is significant, tier 1 patterns are candidates for update

If auto-approved:
6. The prediction is stored with outcome="auto-approved"
7. No immediate feedback — but if the session later fails or backtracks,
   the auto-approval can be retrospectively marked as a false positive
```

Step 9 is critical and currently missing. The proxy stores corrections but never re-derives its flat behavioral patterns from the accumulated history. The patterns in `proxy.md` are written once by `summarize_session.py` and then only appended to. There is no compaction, no contradiction resolution, and no mechanism for a pattern to be retired when the human's behavior changes.

### Prediction persistence

The proxy currently computes a `ProxyDecision` with a `predicted_response` field, but this prediction is not stored. It evaporates after the decision. This means:

- The proxy cannot measure its own prediction accuracy over time.
- There is no way to detect alignment drift (predictions getting worse).
- The learning signal from auto-approvals is lost entirely — the proxy never finds out whether its confident auto-approve was correct unless the session explicitly fails.

Every prediction should be persisted alongside the actual outcome. The prediction accuracy rate — across states, projects, and time — is the proxy's primary health metric.

### Retrospective learning from auto-approvals

The hardest learning problem is false positives: cases where the proxy auto-approved and the human would have corrected. These are invisible by design — the human never sees the artifact, so no correction signal arrives.

Two partial solutions:

1. **Session outcome feedback.** If a session that was auto-approved at PLAN_ASSERT later backtracks from execution to planning, the auto-approval was probably wrong. The proxy can retrospectively downweight its confidence for that (state, context) pattern.

2. **Exploration rate (already implemented).** The 15% random escalation rate in `approval_gate.py` occasionally forces human review even when the proxy is confident. This provides ground truth for calibration. But the results of these exploration escalations are not currently distinguished from normal escalations — the proxy doesn't know which decisions were exploration-triggered and therefore doesn't use them as calibration signal.

### The LoRA analogy

The two-tier structure mirrors the distinction between base model weights and fine-tuning:

- **Tier 1 (flat patterns)** is the "base behavior" — a compact, stable representation of the human's tendencies. Like base weights, it changes infrequently and through a deliberate process.
- **Tier 2 (interaction history)** is the "training data" — the raw observations that accumulate continuously. Like LoRA adapters, specific retrievals modify the base behavior for particular contexts without changing the underlying representation.

The compaction step — periodically re-deriving tier 1 from tier 2 — is the analogue of merging LoRA weights back into the base. It should happen at natural boundaries: end of session, end of project phase, or when prediction accuracy drops below a threshold.

Whether actual LoRA fine-tuning of a small model could serve as the proxy is an open research question. The appeal is that a fine-tuned model would generalize to novel situations rather than relying on keyword matching and statistical thresholds. The risk is that it would generalize incorrectly — overfitting to surface patterns rather than learning the human's actual decision criteria. The current statistical approach is interpretable and auditable; a fine-tuned model would be neither.

A more tractable middle ground: use the accumulated interaction history to generate a structured prompt that captures the human's decision criteria in natural language, and use that prompt (plus retrieved examples) to condition a standard LLM call at decision time. This is effectively in-context learning rather than weight modification — and it's what tier 1 + tier 2 retrieval already enables if the content is rich enough.

## What changes

### New data store: proxy interaction log

A structured store (JSONL or SQLite) of every proxy decision point:

```
- timestamp
- session_id, project_slug
- cfa_state
- artifact_path, artifact_hash, artifact_length
- proxy_prediction: {action, response_text, confidence, reasoning}
- actual_outcome: {action, response_text} (null if auto-approved)
- delta: {prediction_correct: bool, action_match: bool, substantive_gap: text}
- exploration_triggered: bool
- retrospective_correction: {corrected_at, reason} (filled in later if session backtracks)
```

### New retrieval path for proxy decisions

When the proxy faces a decision, it retrieves from two sources:

1. **Flat patterns** — `proxy-patterns.md` (replaces current `proxy.md` for proxy-specific content; `proxy.md` continues to exist for session observations injected into agent context).
2. **Similar past interactions** — query the interaction log by state, project type, and artifact content. Return the most relevant past (prediction, outcome, delta) tuples as few-shot examples for the proxy's decision.

### New compaction step: pattern derivation

At session end (or on a schedule), re-derive tier 1 patterns from the accumulated interaction log:

1. Group interactions by (state, project_type).
2. Identify recurring deltas — corrections that appear across multiple sessions.
3. Extract the principle behind each recurring correction (using an LLM call against the delta history).
4. Compare derived principles against existing tier 1 patterns.
5. Update: add new patterns, strengthen confirmed ones, retire patterns that no longer match observed behavior.

### Prediction accuracy tracking

A simple metric: for each (state, project_type) pair, what fraction of proxy predictions matched the actual human response? Tracked as a rolling window (last 20 interactions) alongside the existing confidence score. When prediction accuracy drops below a threshold, the proxy should:

1. Increase escalation rate (reduce auto-approvals).
2. Flag the (state, project_type) pair for pattern re-derivation.
3. Log the drift for the human's awareness.

## What this is not

- Not a replacement for the confidence model. The statistical confidence mechanism (`approval_gate.py`) remains the gatekeeper. Proxy alignment memory makes the proxy's predictions better; the confidence model decides whether to trust them.
- Not a user profile or preference store. It does not track UI preferences, notification settings, or workflow configuration. It tracks decision-making behavior at CfA review points only.
- Not autonomous. The proxy never acts on alignment memory without the confidence gate's permission. Better alignment memory means the proxy can earn higher confidence faster and maintain it longer — but it still must earn it.

## Relationship to existing components

| Component | Current role | Role with proxy alignment memory |
|---|---|---|
| `approval_gate.py` | Confidence gating + content checks | Unchanged — still the gatekeeper |
| `human_proxy.py` | Extended content checks + conversation storage | Becomes the retrieval interface for proxy decisions |
| `proxy.md` | Flat observation dump from session extraction | Continues as agent-facing context; proxy-specific patterns move to `proxy-patterns.md` |
| `institutional.md` | Project knowledge | Unchanged — orthogonal to proxy memory |
| `memory_indexer.py` | Fuzzy retrieval for agent context | Extended or forked for proxy interaction log retrieval |
| `summarize_session.py` | Post-session extraction | Adds proxy interaction log population + pattern re-derivation trigger |
| `.proxy-confidence.json` | Statistical model | Adds prediction accuracy tracking per (state, project_type) |
