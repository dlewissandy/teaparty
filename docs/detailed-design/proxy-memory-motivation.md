# ACT-R Memory Model for the Human Proxy

This document describes the proxy agent's memory architecture: an activation-based memory system derived from ACT-R that models what the human would retrieve and attend to, combined with EMA as a system health monitor.

For the theory and equations, see [act-r.md](act-r.md).
For the concrete proxy mapping, see [proxy-chunks-and-retrieval.md](proxy-chunks-and-retrieval.md).
For the two-pass prediction model and learned attention, see [proxy-prediction-and-attention.md](proxy-prediction-and-attention.md).

---

## The Proxy's Job

The proxy's job is not to approve or reject. It is to **proxy the behavior of the human** — ask the questions the human would ask, probe the reasoning the human would probe, raise the concerns the human would raise, and reach a decision only after the kind of dialog the human would have conducted. Approval or rejection is the final act of a rich conversation, not a binary gate.

This requires modeling what the human would retrieve and attend to in a given context. The LLM then reasons over those retrieved memories to generate contextually appropriate questions and concerns. ACT-R models memory accessibility, not thinking. What the proxy retrieves shapes what the LLM reasons about. This selection mechanism is how past interactions influence current behavior.

The dimensions that matter for retrieval are: which memories activate above the retrieval threshold; what their content describes; how the current situation connects to them through semantic similarity and structural match.

## Two Systems, Two Roles

**ACT-R activation memory** models memory accessibility. It stores memories of past interactions (the questions the human asked, the concerns they raised, the reasoning they applied, the corrections they made) and surfaces the memories most relevant to the current context. The LLM then uses these retrieved memories as raw material to simulate the human's conversational behavior. This is the core of the proxy's cognitive capability.

**EMA** monitors system health. It tracks approval rates per (state, task_type) over time, not to decide whether to approve but to detect trends. When approval rate drops from 0.8 to 0.4 over 10 sessions, the planning agent is producing worse plans and the proxy is catching it. EMA is a diagnostic signal about how well the upstream agents are performing, not a decision mechanism for the proxy.

The current system conflates these roles. EMA drives the approve/escalate decision. The new design separates them: ACT-R memory drives the proxy's behavior (what questions to ask, what to attend to, what the human would say). EMA observes the outcomes and reports on system health.

## What Changes in the Current Model

The current model uses EMA as a decision gate: confidence above threshold yields auto-approval, below yields escalation. This fails for several reasons.

It skips inspection. A high EMA means the proxy auto-approves without reading the artifact. The human would have read it, probed the details, challenged assumptions, verified completeness, even when ultimately approving. Quality requires artifact inspection. EMA skips inspection entirely. Two-pass prediction ensures inspection through explicit prior-posterior comparison.

It has no context sensitivity. The same EMA applies whether the human is reviewing a security plan or a documentation update. The proxy cannot ask different questions for different artifacts.

It cannot distinguish habitual from episodic patterns. A human's stable preference ("always asks about rollback plans") is invisible to a scalar, as is their recent shift ("rejected the last two migration plans").

It has no connection to discovery mode. The proxy's between-session reviews produce richer interactions than a scalar can represent. See [autodiscovery.md](../reference/autodiscovery.md) for details.

ACT-R activation memory solves these problems. EMA stays, reframed as monitoring.

Note: the new design does permit autonomous proxy action (without escalation to the human) when the proxy has demonstrably inspected the artifact via two-pass prediction and its predictions consistently match the human's patterns. This is earned through consistent inspection, not inferred from a scalar. See [proxy-prediction-and-attention.md](proxy-prediction-and-attention.md) for how this differs from EMA-based auto-approval.

---

## The Approach

Replace the scalar confidence model with **activation-weighted embedding retrieval**.

**Base-level activation** from ACT-R handles forgetting — frequently reinforced memories stay active; one-off events fade. See [research/act-r.md](../research/act-r.md) for the theory and equations, [act-r.md](act-r.md) for our parameter choices.

**Vector embeddings** handle context sensitivity, replacing ACT-R's symbolic spreading activation with semantic overlap in embedding space. See [act-r.md](act-r.md) §Context Sensitivity via Embeddings.

**Structural filtering** handles the relational structure. The chunk is a tuple (state, outcome, task_type, ...) where field ordering matters. SQL queries on structural fields narrow the candidate set; semantic ranking orders within the filtered set. See [proxy-chunks-and-retrieval.md](proxy-chunks-and-retrieval.md) for the chunk schema.

**Interaction-based time** replaces wall-clock seconds. See [act-r.md](act-r.md) §Interactions, Not Seconds.

---

## What Changes, What Stays

**Changes:**
- EMA role: from decision gate (approve/escalate) to system health monitor (are upstream agents improving?)
- Memory: from scalar per state-task pair to chunk-based activation memory (`proxy_memory.db`)
- Decision process: from threshold check to simulated dialog (proxy asks the questions the human would ask, then decides)
- `consult_proxy()`: from confidence lookup to retrieval plus LLM reasoning over past interactions
- Persona distillation: stable preferences discovered through episodic interactions are distilled post-session and written as Claude Code memory files (`~/.claude/projects/<project>/memory/`), bridging the proxy's ACT-R store and the always-loaded context available to all Claude Code sessions

**Stays:**
- `.proxy-confidence.json` — still tracks EMA per state-task pair, now as a monitoring signal
- The proxy agent prompt structure (receives context, generates prediction)
- The proxy agent's tools (file read, dialog)
- The delta-based learning signal (prediction vs. reality)
- The intake dialog flow
- The discovery mode concept and discussion lifecycle

---

## References

For vanilla ACT-R theory and foundational citations (Anderson & Lebiere 1998, Anderson & Schooler 1991, ACT-R Tutorial Unit 4), see [research/act-r.md](../research/act-r.md).

**Park, J.S., et al.** (2023). Generative Agents: Interactive Simulacra of Human Behavior. *UIST '23*. — Weighted combination of recency, importance, and relevance with min-max normalization. Direct precedent for hybrid retrieval scoring.

**Honda, Y., Fujita, Y., Zempo, K., & Fukushima, S.** (2025). Human-Like Remembering and Forgetting in LLM Agents: An ACT-R-Inspired Memory Architecture. In *Proceedings of the 13th International Conference on Human-Agent Interaction* (HAI '25), pp. 229-237. ACM. DOI: 10.1145/3765766.3765803 — ACT-R base-level activation plus cosine similarity for LLM agent memory retrieval. Best Paper Award, HAI 2025.
