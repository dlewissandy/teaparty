# Human Proxy

The Human Proxy is an agent that stands in for the human in conversations with agent teams. It participates in intake dialog, planning, execution, and escalation, predicting what the human would say and acting on their behalf when it has enough evidence to do so. Autonomy is earned, not configured: a proxy whose predictions consistently match the human's actual responses gradually handles more decisions on its own; a proxy whose model is shallow or stale defers back to the human. The [approval-gate](approval-gate.md) is one downstream consequence of this capability, not its defining purpose.

## Why it exists

The human cannot be in every conversation, but their intent must be represented in every conversation. An agent team running without the human present has three options: halt at every decision (blocking the human's attention), guess (producing wrong work), or act on some encoded stand-in for the human's preferences. The proxy is that stand-in: a learned model of how this specific human thinks about this specific kind of work.

Two failure modes bracket the design:

- **Rubber-stamp.** A proxy that approves everything degrades into a confirmation machine. Agents get the illusion of review without the reality; misaligned work ships silently because nothing pushed back.
- **Drift.** A proxy that never escalates stops seeing human decisions, and preferences are not static. The model converges to an outdated snapshot and quietly diverges from what the human would actually say today.

Both are invisible to casual inspection. The proxy's job is to stay calibrated: escalate when it does not know, act when it does, and keep its confidence honest about which case it is in. Every decision is also a data point about whether the proxy's confidence was warranted; that is the calibration challenge.

## How it works

**Three-tier prediction path.** Every proxy decision draws on three sources of learned context, in order of specificity:

1. **Flat patterns** — behavioral patterns extracted from prior sessions (`proxy-patterns.md`). Always loaded.
2. **Interaction history** — similar past (state, task) interactions retrieved from `.proxy-interactions.jsonl`.
3. **ACT-R memory retrieval** — structured memory chunks (situation, stimulus, outcome) ranked by a two-stage process: activation filter (power-law decay over retrieval traces) then composite scoring (normalized activation + multi-dimensional cosine similarity). See [act-r overview](act-r/overview.md).

All three feed into the proxy agent's context before it reasons about the decision. See [approval-gate](approval-gate.md) for the full invocation path.

**Two-pass prediction.** The proxy generates two predictions per decision. The *prior* is produced without seeing the artifact — drawing only on memories and learned patterns. The *posterior* is produced after reading the artifact and the prior. When the action or confidence shifts substantially between passes, what in the artifact caused the shift becomes a salient percept that feeds back into learning. The posterior is the decision; the delta is a signal.

**Asymmetric regret.** The costs of false approval and false escalation are not symmetric. Approving work the human would have rejected is expensive: misaligned artifacts propagate, trust erodes, and the human may not catch the drift for several turns. Escalating work the human would have approved is cheaper: a moment of attention, then forward motion. The system weights corrections 3x more heavily than approvals when tracking proxy health, and the confidence calibration is biased toward escalation when signals conflict. This follows the Hindsight approach to asymmetric confidence decay (arXiv:2512.12818).

**Confidence decay and guards.** Raw self-assessed confidence from the two-pass prediction passes through a series of guards in [approval-gate](approval-gate.md): a genuine-tension guard caps confidence when retrieved memories contain unresolved contradictions; a staleness guard forces escalation if the (state, task_type) has not seen human feedback in 7+ days; an exploration rate forces escalation on 15% of high-confidence decisions to keep calibration signal flowing; per-context accuracy tracking gates autonomy against the proxy's demonstrated track record. A memory-depth cold-start guard also exists (capping confidence until the proxy has accumulated experience across multiple distinct (state, task_type) pairs), but its threshold is currently relaxed to 0 on fresh projects — the improved conversational prompts make self-reported confidence trustworthy enough to drive clear-cut gates from turn one, and the other guards still run unchanged. The full calibration stack is slated for revisit in the milestone-4 skill-graph rewrite.

**Presence tracking.** The proxy respects the [D-A-I role assignment](../../overview.md#d-a-i-role-model) from the team configuration. When the human is present at a level (Decider), the proxy may hand off to them directly rather than predicting. When the human is not present or is Informed, the proxy acts. Routing is dynamic; presence is checked at gate time, not at session start.

**Bidirectional feedback with Learning.** The proxy and the [learning](../learning/index.md) system are two sides of the same loop. Proxy memory chunks are stored in the same ACT-R store that other learning types query. Corrections the human makes in direct dashboard conversation update the same model the proxy consults at every gate; there is no separate "chat proxy" and "gate proxy". Contradiction detection in proxy memory feeds post-session consolidation that prunes preference-drift losers and preserves genuine tensions for future escalation.

## Status

**Operational:**

- Three-tier prediction path wired into every proxy invocation ([approval-gate](approval-gate.md))
- ACT-R memory with two-stage retrieval, post-consumption reinforcement, and multi-dimensional embeddings
- Cold-start gating mechanism via ACT-R memory depth — built; threshold currently `0`, slated for re-tune in the milestone-4 skill-graph rewrite
- Contradiction detection with two-tier classification (heuristic + LLM-as-judge)
- Per-context prediction accuracy tracking per (state, task_type)
- Asymmetric confidence decay per Hindsight (arXiv:2512.12818)
- Proxy review blade in the bridge dashboard (self-review mode)
- Differential recording — proxy prediction vs. human actual — as the primary learning signal

**Still designed:**

- Intake dialog phases 2–3 (prediction-comparison dialog, behavioral rituals) — phase 1 lands questions at gates; phases 2–3 extend this to the pre-artifact intake conversation
- Text derivative learning — the proxy's reflection on its own prediction errors, stored for future retrieval
- Behavioral rituals — invariant practices tied to CfA states (e.g. always requesting a TLDR before plan review), detected from recurring behavior and executed preemptively

**Unmeasured:**

- Actual proxy accuracy on real escalations. Park et al. (2024) demonstrated 85% accuracy from conversational data + LLM reasoning in a comparable retrieval-backed setup; whether this proxy achieves similar accuracy on this human's decisions has not been measured. The mechanisms are in place to measure it; the measurement itself is outstanding.

## Deeper topics

- [approval-gate](approval-gate.md) — proxy decision model, consult_proxy invocation path, confidence calibration gates, never-escalate tradeoffs
- [act-r overview](act-r/overview.md) — how ACT-R declarative memory is adapted for gate decisions
- [act-r mapping](act-r/mapping.md) — chunks, traces, retrieval implementation
- [act-r memory](act-r/memory.md) — ACT-R memory store implementation
- [act-r sensorium](act-r/sensorium.md) — two-pass prediction and learned attention

**Related research:** [act-r research](../../research/act-r.md), [proxy-prediction](../../research/proxy-prediction-and-active-learning.md)

**Case study evidence:** [learnings](../../case-study/learnings.md), [artifacts/proxy-interactions.jsonl](../../case-study/artifacts/proxy-interactions.jsonl), [artifacts/proxy-patterns.md](../../case-study/artifacts/proxy-patterns.md)

**Tight coupling:** [learning](../learning/index.md) — the proxy's memory is the learning system's memory; corrections in either direction update the same model.
