# Human Proxy Agents

## The Autonomy-Oversight Dilemma

Every autonomous agent faces a continuous choice: act or ask. Both carry risk.

Acting when the human wanted to be consulted causes wrong work, eroded trust, and violated values. Escalating when the agent could have handled it wastes the human's time and fails to deliver on the promise of autonomy. These failure modes are not symmetric — their relative costs vary by organization, individual, domain, and specific decision.

Pure autonomy misses human values. Constant human oversight defeats the purpose of automation. Neither extreme works. The human proxy exists to navigate the space between them.

## Least-Regret Escalation

The agent must choose the option with the least expected regret. This requires three capabilities:

**A model of the human's risk tolerance.** Learned by observing the human's reactions over time. When the agent acts autonomously and gets corrected, that indicates the escalation threshold was too low. When the agent escalates and the human responds with "you should have just done that," the threshold was too high. Both signals calibrate the model.

**A model of action cost.** Before choosing to act or ask, the agent estimates two properties of the decision: how reversible it is, and how much organizational impact it carries. High-reversibility, low-impact decisions default toward autonomy. Low-reversibility, high-impact decisions default toward escalation. What the organization considers "high-impact" is itself a learned property, not a universal constant.

**A default posture that shifts over time.** At cold start, with no observational history, the agent defaults to escalation. As it accumulates data, the threshold shifts toward autonomy in domains where the human has demonstrated consistent preferences. The agent earns autonomy through demonstrated alignment, not through configuration.

See [Intent Engineering — Least-Regret Escalation](intent-engineering.md#least-regret-escalation) for the full treatment.

## Proxy Learning

The human proxy learns from two distinct types of signal, mirroring the institutional/task-based split in [organizational learning](learning-system.md):

### Preferential Learning

The human's general traits — stable, broadly applicable, always loaded:

- Communication style (concise vs verbose, formal vs casual)
- Risk tolerance (general baseline)
- Values and priorities
- Trust levels per workgroup, per agent, per domain
- Delegation boundaries (what they approve vs what they trust agents to decide)

### Task-Based Learning

The human's domain-specific decision patterns — context-specific, retrieved on demand:

- Domain-specific consultation preferences ("for database changes, always consult before applying")
- Delegation scope by area ("for UI work, trust the design team — don't escalate unless it touches the nav")
- Triage heuristics ("severity first, then recency")

The preferential/task-based split matters because they have different storage and retrieval characteristics. Preferential learnings are compact and stable enough to load into every relevant session. Task-based learnings are numerous and domain-specific — they must be fuzzy-retrieved based on what the current task looks like.

## Content Awareness

The proxy model is not purely decision-based. It also monitors artifact properties to detect situations that warrant escalation:

**Artifact length anomalies.** Unusually short or long deliverables relative to historical norms for the task type may indicate truncation, scope creep, or misunderstanding.

**Concern vocabulary.** Certain patterns in agent output — hedging language, unresolved questions, qualification of confidence — signal that the agent itself is uncertain and the human should review.

**Question pattern learning.** The proxy tracks what kinds of questions the human asks during review and what concerns they raise. Over time, it learns to anticipate these concerns and either address them proactively or escalate preemptively.

## Cold Start to Warm Start

At cold start, with no observational history, the proxy defaults to escalation for every decision. The human is the sole decision-maker. As data accumulates:

1. **Cold start** (< 5 observations per decision type) — always escalate, collect data
2. **Calibrating** — approval rate emerges via exponential moving average, but confidence is low
3. **Warm start** — proxy pre-populates decisions based on learned patterns. For binary decisions (approve/reject), it uses the approval rate. For generative decisions (what should the correction be?), it predicts what the human would say.

The proxy never fully stops escalating. An exploration rate (currently 15%) ensures the model continues to see human decisions even in domains where it is confident. A staleness guard forces escalation if the proxy hasn't seen human feedback in 7+ days, preventing convergence to an outdated model.

Asymmetric regret weighting ensures that false approvals — rubber-stamping bad work — cost 3x more than false escalations. The system is deliberately conservative. Earning autonomy is slow; losing it is fast.

## Relationship to the Learning System

Proxy learning is one of the three learning types in the [learning system](learning-system.md). It sits at the intersection of the organizational hierarchy and the human:

- **Proxy preferential** memory is stored in `proxy.md` — always loaded, compact, human-readable
- **Proxy task-based** memory is stored in `proxy-tasks/` — chunked, embedded, fuzzy-retrieved

The escalation model is one of the highest-value things the memory system stores. It encodes not just what a person values but how much latitude they grant, and how that varies by domain and risk level. See [Learning System — Proxy Learning](learning-system.md#23-proxy-learning) for the full taxonomy.
