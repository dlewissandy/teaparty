# ACT-R Declarative Memory

This document explains ACT-R's declarative memory system — the theory, the equations, and the parameter values — for an engineer who has never used ACT-R. It is self-contained: everything you need to understand the memory model is here.

For how this applies to the TeaParty proxy agent, see:
- [act-r-proxy-memory.md](act-r-proxy-memory.md) — motivation and migration plan
- [act-r-proxy-mapping.md](act-r-proxy-mapping.md) — chunks, traces, retrieval implementation
- [act-r-proxy-sensorium.md](act-r-proxy-sensorium.md) — two-pass prediction and learned attention

---

## What ACT-R Is

ACT-R (Adaptive Control of Thought — Rational) is a cognitive architecture developed by John Anderson at Carnegie Mellon University. It is a computational model of human cognition — not a metaphor or a framework, but a running system that reproduces human performance data across hundreds of experiments on memory, learning, and decision-making.

ACT-R's central claim about memory: **the probability of retrieving a memory reflects the statistical patterns of the environment.** Things you encountered recently and frequently are more likely to be relevant now. The memory system is rational — it forgets at the rate that makes its retrievals most useful given the actual patterns of the world.

Memory in ACT-R is organized as **chunks** — structured units of knowledge. Each chunk has an **activation level** that determines how accessible it is. High-activation chunks are retrieved quickly and reliably. Low-activation chunks are effectively forgotten — still stored, but below the retrieval threshold.

Activation is not a fixed property. It changes continuously based on two factors:

1. **Base-level activation** — how often and how recently this chunk has been accessed. This is the learning-and-forgetting component.
2. **Context sensitivity** — how related this chunk is to what you're currently thinking about. ACT-R uses symbolic spreading activation for this; we use vector embeddings (see the proxy mapping document for details).

---

## Base-Level Activation (B)

Base-level activation reflects how often and how recently a chunk has been accessed (Anderson & Lebiere, 1998, Chapter 4; equation simplified from ACT-R Tutorial Unit 4):

```
B = ln( sum over all accesses i:  t_i ^ (-d) )
```

Where:
- `t_i` is the number of **interactions** since the i-th access of this chunk (see "Interactions, Not Seconds" below)
- `d` is the **decay parameter**, standardly set to **0.5**
- `ln` is the natural logarithm
- The sum is over every time this chunk was accessed (created, retrieved, reinforced)

**How it works.** Each time a chunk is accessed, it gets a **trace**. Each trace decays as a power function of interactions elapsed: `t^(-0.5)`. The sum of all decaying traces, passed through a logarithm, gives the base-level activation.

### Interactions, Not Seconds

In the ACT-R literature, `t` is measured in seconds — laboratory experiments use wall-clock time. For agent systems, we measure `t` in **interactions**: decisions, dialog turns, observations. Each interaction advances the clock by 1.

This is a better fit than wall-clock time for three reasons:

1. **Between sessions, nothing happens.** If the agent handles 5 decisions on Monday and none until Thursday, wall-clock decay would erode Monday's memories over 3 idle days. Interaction-based decay doesn't advance — no interactions means no decay, which is correct because nothing happened to make the memories less relevant.

2. **Anderson & Schooler's empirical basis is event-based.** Their 1991 analysis measured word *occurrences* in newspaper headlines, child-directed speech, and email. The power-law pattern they found was in events (how many headlines ago did this word last appear?), not in seconds. The environment's statistical structure is event-based; so should the memory system's.

3. **Experience scales with activity, not calendar time.** An agent that handled 100 interactions over a busy week has far more trace accumulation than one that handled 5 over the same calendar period. The memory should reflect *experience*, not elapsed time.

### Worked Example

A chunk was accessed 3 times: 2 interactions ago, 10 interactions ago, and 50 interactions ago.

```
B = ln( 2^(-0.5) + 10^(-0.5) + 50^(-0.5) )
  = ln( 0.707 + 0.316 + 0.141 )
  = ln( 1.164 )
  = 0.152
```

Now the agent has another interaction (the chunk is accessed again, t=1):

```
B = ln( 1^(-0.5) + 3^(-0.5) + 11^(-0.5) + 51^(-0.5) )
  = ln( 1.000 + 0.577 + 0.302 + 0.140 )
  = ln( 2.019 )
  = 0.703
```

The activation jumped from 0.152 to 0.703 — the chunk went from moderately accessible to highly accessible, because it was just accessed.

### Key Properties

- Recent accesses contribute much more than old ones (power-law decay)
- Many accesses accumulate — a chunk accessed 50 times decays much slower than one accessed once
- The logarithm compresses the range — you need exponentially more accesses to get linear activation gains
- At `d = 0.5`, a single trace loses half its contribution when the interaction count quadruples
- Between sessions, the interaction counter doesn't advance — memories don't decay while the system is idle

### Why d = 0.5?

Anderson & Schooler (1991, "Reflections of the environment in memory," *Psychological Science* 2(6), 396-408) showed that this value isn't arbitrary — it matches the statistical structure of the real world. They analyzed newspaper headlines, child-directed speech, and email archives. In all three domains, the probability that an item encountered in the past would be relevant now followed a power function with an exponent near 0.5. Crucially, their analysis was event-based — they measured relevance as a function of how many *events* ago something last appeared, not how many seconds. This is why interaction-based `t` is the natural unit: the empirical basis for `d = 0.5` was always about event intervals, not clock intervals.

The memory system's decay rate matches the environment's relevance rate. Forgetting is not a bug — it is a rational response to the statistics of the world.

---

## Noise

Retrieval noise follows a logistic distribution (Anderson & Lebiere, 1998, Chapter 4):

```
noise ~ Logistic(0, s)
```

Where `s` is the **noise parameter**, standardly set to **0.25**. This adds randomness to retrieval — sometimes you remember something unexpected, sometimes you fail to retrieve something you should. The noise ensures the system doesn't become deterministic, which would prevent exploration of its own memory.

For implementation: sample from a logistic distribution with location 0 and scale `s`. In Python: `random.random()` transformed via `s * log(p / (1 - p))` where p is uniform on (0, 1).

---

## Retrieval

A chunk is retrieved if its activation exceeds the **retrieval threshold** τ (Anderson & Lebiere, 1998, Chapter 4):

```
Retrieved if A > tau
```

The standard value is `tau = -0.5`. Chunks with activation below this threshold are effectively forgotten — they exist in memory but cannot be accessed.

The **probability of retrieval** follows a soft threshold (Anderson & Lebiere, 1998, eq. 4.4):

```
P(retrieve) = 1 / (1 + exp(-(A - tau) / s))
```

This is a logistic function centered at the threshold. Chunks well above threshold are almost certainly retrieved. Chunks well below are almost certainly not. Chunks near the threshold are retrieved probabilistically — sometimes yes, sometimes no.

**Retrieval latency** also follows from activation:

```
latency = F * exp(-f * A)
```

Where `F` and `f` are scaling parameters (standardly `F = 1.0`, `f = 1.0`). High-activation chunks are retrieved faster. This isn't directly relevant to agent implementations but explains why the model predicts human reaction times so accurately.

---

## Standard Parameter Values

| Parameter | Symbol | Standard Value | Role |
|-----------|--------|---------------|------|
| Decay | d | 0.5 | Power-law decay exponent for traces |
| Noise | s | 0.25 | Scale of retrieval noise (logistic) |
| Retrieval threshold | tau | -0.5 | Minimum activation for retrieval |
| Latency factor | F | 1.0 | Scales retrieval time (not needed for agents) |
| Latency exponent | f | 1.0 | Scales retrieval time (not needed for agents) |

These values are empirically validated across hundreds of ACT-R models.

---

## Emergent Behaviors

The remarkable thing about the base-level activation equation is how much behavior emerges from one formula:

**Stable preferences** (frequently reinforced) — a chunk accessed across 20 sessions has 20+ overlapping traces. Even as each individual trace decays, the sum stays high. The preference "sticks" because it keeps being reinforced.

**Drifting interests** (recently clustered) — a chunk accessed 5 times this week but never before has a burst of recent traces. High activation now, but if the accesses stop, the cluster decays as a unit. The interest "drifts" with context.

**One-off events** (single trace) — a chunk created once and never accessed again has a single decaying trace. It fades quickly. The event is "forgotten" unless something brings it back.

**Context-triggered recall** — a chunk that dropped below threshold (effectively forgotten) can be reactivated if accessed again. The old traces still contribute (albeit weakly); a new access adds a fresh trace that pushes activation above threshold. This is the "oh, I remember that!" phenomenon.

No tagging, no type system, no separate decay parameters. One equation, many behaviors.

---

## References

**Anderson, J. R., & Lebiere, C.** (1998). *The Atomic Components of Thought.* Lawrence Erlbaum Associates. — The definitive ACT-R reference. Complete derivation of the activation equations, retrieval dynamics, and parameter values. Chapter 4 covers declarative memory in full.

**Anderson, J. R., & Schooler, L. J.** (1991). Reflections of the environment in memory. *Psychological Science*, 2(6), 396-408. — Empirical basis for the power-law decay parameter (d = 0.5). Demonstrates that human forgetting curves match the statistical structure of real-world information relevance. Read this first for intuition about why the math works.

**ACT-R Tutorial, Unit 4: Activation of Chunks and Base-Level Learning.** Carnegie Mellon University. http://act-r.psy.cmu.edu/wordpress/wp-content/themes/ACT-R/tutorials/unit4.htm — Step-by-step tutorial with worked examples and code. The best starting point for implementation.
