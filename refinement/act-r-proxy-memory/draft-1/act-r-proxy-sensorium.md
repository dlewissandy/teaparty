# Proxy Sensorium: Two-Pass Prediction and Learned Attention

The proxy agent doesn't just predict what the human will decide. It predicts what the human will **attend to** before deciding. This document describes how the proxy's sensorium works — what it senses, how it determines salience, and how it learns to focus on the percepts that matter.

For the memory model underlying this, see [act-r.md](act-r.md). For the chunk structure and retrieval, see [act-r-proxy-mapping.md](act-r-proxy-mapping.md). For the overall motivation, see [act-r-proxy-memory.md](act-r-proxy-memory.md).

---

## The Problem

At any gate moment, the proxy has access to a rich sensorium:

- The **artifact** under review (INTENT.md, PLAN.md, deliverables, .work-summary.md)
- The **upstream context** (the intent behind the plan, the plan behind the deliverable)
- The **session history** (prior gates, prior decisions, corrections, backtracks)
- The **agent stream** (what the agent team said and did while producing the work)
- The **CfA state** (where in the protocol)
- The **dispatch results** (which subteams ran, what they produced)
- The **temporal signals** (how long the phase took, how many turns the agent used)

This is a lot of percepts. If the proxy encodes all of them into every memory chunk, the chunks become high-dimensional blobs — everything is related to everything, nothing is specific, the fan is infinite, and associations lose meaning.

The human brain solves this with **attention**. The retina takes in millions of signals, but attention selects what gets processed deeply. The rest is sensed but not attended to. The proxy needs the same mechanism: a way to determine which percepts are salient at each interaction, and to encode only those into the memory chunk.

---

## Two-Pass Prediction

The proxy generates its prediction in two passes:

### Pass 1: Preconception (without the artifact)

The proxy receives the context — CfA state, task type, project, session history, retrieved memories from the ACT-R system — but **not** the artifact under review. It generates a prediction:

> "Based on what I know about this human, this task type, and this state, I predict the human will approve. This human typically approves plans for documentation tasks without detailed review. Confidence: 0.8."

This is the **prior**. It reveals what the proxy expects before inspecting the actual work. The prediction is based entirely on learned patterns — what this human has done in similar situations before.

### Pass 2: Inspection (with the artifact)

The proxy now receives the artifact (and any upstream context). It generates a revised prediction:

> "Having read the plan, I notice it has no rollback section for the database migration. This human has corrected plans with missing safety mechanisms before. I now predict the human will correct, asking for a rollback strategy. Confidence: 0.85."

This is the **posterior**. It reveals what the artifact changed about the prediction.

### The Delta

The difference between the two passes is the **salience signal**:

- **Prediction unchanged** → the artifact contained nothing surprising relative to the proxy's model. The human's response is predictable from context alone. The artifact's content is not salient — it confirmed expectations.
- **Prediction changed** → the artifact contained something the proxy didn't expect. The shift from prior to posterior identifies **what** in the artifact caused the change. Those features are the salient percepts — the things the human would attend to.

In the example above, the salience signal is: "missing rollback section in a database migration plan." The proxy didn't expect this from the context (documentation tasks usually don't need rollback plans, but this task involves a migration). The artifact revealed something the context alone couldn't predict.

This is **Bayesian surprise** applied to attention. The most informative percepts are the ones that change the prediction the most. The same principle that Allen AI's AutoDiscovery uses for guiding hypothesis exploration — but applied to what the proxy pays attention to, not what experiments to run.

**A note on signal quality.** The prior-posterior delta is an approximate salience signal, not a precise measurement. Temperature 0 does not guarantee deterministic LLM outputs — floating-point precision, GPU parallelism, and prompt structure differences between Pass 1 and Pass 2 introduce noise unrelated to the artifact's influence. The binary surprise trigger (action changed vs. didn't) is partly a robustness choice: it thresholds away small noise-driven variations that would contaminate a continuous delta measure.

---

## Why Both Passes Matter

The two passes serve different purposes, and both are essential:

**The prior (Pass 1) reveals the proxy's model.** If the proxy predicts "approve" before reading the artifact, that tells us what it has learned about this human in this context. A wrong prior means the proxy's model needs updating. A consistently accurate prior means the proxy understands this human's patterns well enough that artifact inspection is confirmatory, not discovery.

**The posterior (Pass 2) is the actual decision.** This is what gets used at the gate — the prediction informed by both the proxy's model and the artifact under review.

**The delta reveals what matters.** The prior-to-posterior shift tells us which artifact features drove the prediction change. Over time, accumulated deltas build a map of what this human attends to: "at PLAN_ASSERT, this human notices missing safety mechanisms, doesn't notice formatting issues, always checks whether open questions from the intent were addressed." This is the learned attention model — built from data, not from configuration.

**The prior enables calibration.** By comparing the prior against the actual human response, we can assess how much the proxy needs the artifact vs. how much it can predict from context alone. A proxy whose prior is almost always right has deeply internalized the human's patterns. A proxy whose prior is frequently overturned by the artifact still needs the inspection step and shouldn't be trusted to auto-approve.

---

## Surprise: When to Extract Salient Percepts

Surprise extraction triggers when the prior and posterior meaningfully diverge:

- **Action changed** (e.g., approve -> correct): strong surprise. Extract a one-sentence description of what changed and a list of salient percept phrases (2 additional short-context LLM calls).
- **Confidence delta exceeds threshold** (e.g., |posterior_confidence - prior_confidence| > 0.3, same action): moderate surprise. Extract salient percepts but with a lighter-weight extraction (1 LLM call).
- **Neither**: no surprise. No additional calls. The chunk is still stored but with empty salience fields.

This replaces the purely binary surprise mechanism. The confidence threshold captures cases where the artifact was noteworthy — a confidence jump from 0.3 to 0.9 without changing the action is informative — without opening the door to noise from minor confidence fluctuations.

Most gates produce no surprise. This is the design working correctly: routine interactions reinforce the prior (making it more accurate), while surprising cases build the attention model (what to look for). Learned attention is intentionally built from the minority of interactions that produce surprise — you attend to what is unexpected, not to what is routine.

---

## How the Delta Feeds Into Memory

When the interaction completes (the human responds), the memory chunk is constructed with the delta as a first-class component:

```python
{
    "type": "gate_outcome",
    "state": "PLAN_ASSERT",
    "task_type": "data-migration",
    "outcome": "correct",

    # The two-pass results
    "prior_prediction": "approve",
    "prior_confidence": 0.8,
    "posterior_prediction": "correct",
    "posterior_confidence": 0.85,

    # The salience signal
    "prediction_delta": "Missing rollback section for database migration changed prediction from approve to correct",
    "salient_percepts": ["no rollback strategy", "database migration risk"],

    # The human's actual response
    "human_response": "Add a rollback strategy for the migration",
    "delta_from_posterior": "",  # posterior was correct

    # Embeddings — independent vectors per dimension
    "embedding_situation": [...],    # state + task type
    "embedding_artifact": [...],     # the artifact content
    "embedding_stimulus": [...],     # the question/observation
    "embedding_response": [...],     # the human's response
    "embedding_salience": [...],     # the prediction delta

    "traces": [142]
}
```

The **salience embedding** is a new dimension — it captures *what changed between the two passes*. At retrieval time, when the proxy encounters a new artifact with a similar gap (e.g., a deployment plan with no rollback), the salience embedding matches: "last time I saw something like this, the prediction shifted and the human corrected." The prior for the new interaction incorporates this — the proxy now *expects* a correction when it sees missing safety mechanisms.

---

## The Sensorium as Independent Embeddings

Each percept dimension gets its own embedding, not one blended vector:

| Dimension | What it captures | Example |
|-----------|-----------------|---------|
| **Situation** | Where in the process | PLAN_ASSERT, data-migration project |
| **Artifact** | What the agent is reviewing | The plan content — structure, gaps, specifics |
| **Stimulus** | What triggered the interaction | The gate question, the escalation, the observation |
| **Response** | What the human did | The correction text, the approval, the dismissal |
| **Salience** | What changed between prior and posterior | The prediction delta — the surprise |

Independent embeddings allow retrieval to match on each dimension separately. A new interaction can match on:
- Situation alone: "what happens at PLAN_ASSERT?" (high fan, weak signal)
- Situation + artifact: "what happens at PLAN_ASSERT when the plan has gaps?" (lower fan, stronger signal)
- Salience: "when has the proxy been surprised by missing safety mechanisms?" (specific, cross-cutting)

The **intersection** of high scores across dimensions produces specific, selective associations. A chunk that scores high on situation AND artifact AND salience is a strong, specific association. A chunk that scores high on only one dimension is a weak, general one.

---

## Learned Attention Over Time

The accumulated salience deltas build a model of what this human attends to. After 20 interactions at PLAN_ASSERT:

- The proxy notices that "missing safety mechanisms" appears in the salience delta 8 times, always followed by correction
- "Formatting issues" never appears in any salience delta — the prior and posterior never diverge on formatting
- "Open questions from intent not addressed" appears 4 times, always followed by correction

The proxy learns: at PLAN_ASSERT, attend to safety mechanisms and intent coverage. Don't attend to formatting. This is the learned attention model — not configured, not tagged, but emergent from the accumulated prior-posterior deltas.

Because learned attention is built from surprising interactions (a minority of gates), it accumulates gradually. This is by design: a human who reviews 100 plans and is surprised by 15 of them has learned attention from those 15 cases, not from the 85 routine approvals. The routine approvals reinforce the prior (making it more accurate); the surprises build the attention model (what to look for). The rate of attention learning depends on the surprise rate, which means the model learns faster in domains where the proxy's initial predictions are poor and slower where they are already good.

The next time the proxy reaches PLAN_ASSERT, its **Pass 1 prior** already reflects this learned attention: "I should look for safety mechanisms and intent coverage." The prior becomes more specific over time because the proxy has learned what to expect. When the prior is specific enough, the posterior rarely diverges — and the proxy has earned the right to act autonomously because it has demonstrated that it attends to what the human would attend to, inspects the artifact through two-pass prediction, and finds nothing unexpected.

This is fundamentally different from the auto-approval that the root document criticizes. EMA-based auto-approval skips inspection entirely — it never reads the artifact, never asks questions, just checks a scalar and waves things through. Two-pass auto-approval completes the full inspection: the proxy runs both passes, examines the artifact, confirms that its model of the human's attention patterns predicts approval, and the posterior agrees. The dialog happened inside the proxy's reasoning. The proxy earned its autonomy by demonstrating understanding, not by accumulating a high scalar.

---

## Implementation

The two-pass prediction requires two LLM calls per gate interaction:

### Pass 1: Prior
```
Prompt: You are the human proxy. Based on your memories of this human
and the current context (state, task type, session history), predict
what the human would say. You have NOT seen the artifact yet.

Context: {retrieved memories}, {CfA state}, {task type}, {session history}

Generate: prediction, confidence, reasoning
```

### Pass 2: Posterior
```
Prompt: You are the human proxy. You previously predicted: {prior}.
Now read the artifact and revise your prediction.

Context: {same as Pass 1} + {artifact content} + {upstream context}

Generate: revised prediction, confidence, what changed and why
```

### Cost

Two LLM calls instead of one. At every gate where the proxy runs. This is a real cost increase — roughly 2x the proxy's current LLM spend. Embedding costs add up to 5 API calls per chunk creation, plus retrieval-time embedding of the current context. These embedding costs are small relative to LLM generation calls but should be tracked in the cost budget.

It is worth it. If the proxy is standing in for the human on important decisions, understanding *what it's looking at and why* is not a luxury. It is the mechanism by which the proxy earns trust: not "I got the right answer" but "I got the right answer because I was looking at the right things."

A proxy that auto-approves because its prior says "this human always approves docs tasks" is a rubber stamp. A proxy that auto-approves because its prior correctly anticipated the artifact would have no issues — and the posterior confirmed it — has demonstrated understanding.

---

## Relationship to Other Documents

- **[act-r.md](act-r.md)** — the base-level activation equation that governs how memory chunks decay and are retrieved
- **[act-r-proxy-mapping.md](act-r-proxy-mapping.md)** — the chunk structure and retrieval mechanism that this document extends with salience embeddings
- **[act-r-proxy-memory.md](act-r-proxy-memory.md)** — the overall motivation for replacing EMA/Laplace with activation-based memory
- **[autodiscovery.md](../autodiscovery.md)** — the discovery mode where the proxy reviews the codebase between sessions, using the same memory and attention model
- **[human-proxies.md](../human-proxies.md)** — the conceptual design for the proxy agent, which this document extends with a concrete attention mechanism
