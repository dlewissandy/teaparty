# ACT-R Declarative Memory: Reference

This document is a self-contained explanation of ACT-R declarative memory theory. It covers the equations, standard parameters, and empirical basis. For an engineer who has never used ACT-R, this is everything you need to understand how the system models memory.

---

## What ACT-R Is

ACT-R (Adaptive Control of Thought — Rational) is a cognitive architecture developed by John Anderson at Carnegie Mellon University. It is a computational model of human cognition: a running system that reproduces human performance data across hundreds of experiments on memory, learning, and decision-making.

ACT-R's central claim: **the probability of retrieving a memory reflects the statistical patterns of the environment.** Things you encountered recently and frequently are more likely to be relevant now. The memory system is rational—it forgets at the rate that makes retrievals most useful given the actual patterns of the world.

Memory in ACT-R is organized as **chunks**: structured units of knowledge. Each chunk has an **activation level** that determines how accessible it is. High-activation chunks are retrieved quickly and reliably. Low-activation chunks fall below the retrieval threshold and are effectively forgotten, though they remain stored in memory.

Activation is not fixed. It changes continuously based on two factors:

1. **Base-level activation** — how often and how recently this chunk has been accessed. This is the learning-and-forgetting component.
2. **Context sensitivity** — how related this chunk is to what you are currently thinking about. ACT-R uses symbolic spreading activation for this: chunks related to your current goals and focus receive a boost.

---

## Base-Level Activation (B)

Base-level activation reflects how often and how recently a chunk has been accessed.

```
B = ln( sum over all accesses i:  t_i ^ (-d) )
```

Where:
- `t_i` is the time elapsed since the i-th access (measured in seconds)
- `d` is the **decay parameter**, standardly set to **0.5**
- `ln` is the natural logarithm
- The sum is over every time this chunk was accessed (created, retrieved, reinforced)

**How it works.** Each time a chunk is accessed, it gets a **trace**. Each trace decays as a power function of time elapsed: `t^(-0.5)`. The sum of all decaying traces, passed through a logarithm, gives the base-level activation.

### Worked Example

A chunk was accessed 3 times: 2 seconds ago, 10 seconds ago, and 50 seconds ago.

```
B = ln( 2^(-0.5) + 10^(-0.5) + 50^(-0.5) )
  = ln( 0.707 + 0.316 + 0.141 )
  = ln( 1.164 )
  = 0.152
```

Now the chunk is accessed again (t=1 second):

```
B = ln( 1^(-0.5) + 3^(-0.5) + 11^(-0.5) + 51^(-0.5) )
  = ln( 1.000 + 0.577 + 0.302 + 0.140 )
  = ln( 2.019 )
  = 0.703
```

The activation jumped from 0.152 to 0.703. The chunk went from moderately accessible to highly accessible because it was just accessed.

### Key Properties

- Recent accesses contribute much more than old ones (power-law decay).
- Many accesses accumulate. A chunk accessed 50 times decays much slower than one accessed once.
- The logarithm compresses the range. You need exponentially more accesses to get linear activation gains.
- At `d = 0.5`, a single trace loses half its contribution when the time interval quadruples.
- The memory system "forgets" exponentially: useful for filtering out old, irrelevant information while preserving frequently-encountered knowledge.

### Why d = 0.5?

Anderson & Schooler (1991, "Reflections of the Environment in Memory," *Psychological Science* 2(6), 396-408) showed that environmental statistics follow power-law distributions matching human memory decay curves. They analyzed newspaper headlines, child-directed speech, and email archives. In all three domains, the probability that an item encountered in the past would be relevant now followed a power function: the rate at which information becomes obsolete in the real world.

The specific value d = 0.5 became the ACT-R standard through subsequent modeling work. It achieves a rational match between memory decay and environmental relevance. This is why the equations use power functions: the empirical basis is that relevance in the environment decays as a power law, and human memory does the same.

The memory system's decay rate matches the environment's relevance rate. Forgetting is not a bug. It is a rational response to the statistics of the world.

---

## Noise

Retrieval noise follows a logistic distribution.

```
noise ~ Logistic(0, s)
```

Where `s` is the **noise parameter**. The ACT-R default is NIL (disabled). When enabled in tutorial models, values typically range from 0.2 to 0.5.

Noise makes retrieval stochastic. Even identical activation levels produce variable retrieval outcomes on repeated trials, matching human behavior where people sometimes remember and sometimes forget the same information.

---

## Retrieval

A chunk is retrieved if its base-level activation exceeds the **retrieval threshold** tau.

```
Retrieved if B > tau
```

The ACT-R default for the retrieval threshold is 0 (zero). In tutorial models where it is explicitly set, values range from 0 to -2, depending on the specific model and task.

The **probability of retrieval** follows a soft threshold. From Anderson & Lebiere (1998):

```
P(retrieve) = 1 / (1 + exp(-(B - tau) / s))
```

This is a logistic function centered at the threshold. Chunks well above the threshold are almost certainly retrieved. Chunks well below are almost certainly not. Chunks near the threshold are retrieved probabilistically. This soft-threshold behavior matches human data: memory is not all-or-nothing but probabilistic, especially near the boundary of what you can recall.

**Retrieval latency** also follows from activation.

```
latency = F * exp(-f * B)
```

Where `F` and `f` are scaling parameters (standardly `F = 1.0`, `f = 1.0`). High-activation chunks are retrieved faster. This equation explains why the model predicts human reaction times so accurately: more familiar, practiced information is retrieved both more reliably and more quickly.

---

## Standard Parameter Values

| Parameter | Symbol | Default Value | Role | Source |
|-----------|--------|---------------|------|--------|
| Decay | d | 0.5 | Power-law decay exponent for traces | ACT-R standard (Anderson & Schooler, 1991) |
| Noise | s | NIL (disabled) | Scale of retrieval noise (logistic) | ACT-R default; tutorials use 0.2–0.5 when enabled |
| Retrieval threshold | tau | 0 | Minimum activation for retrieval | ACT-R default; tutorials use 0 to -2 |
| Latency factor | F | 1.0 | Scales retrieval time | ACT-R standard |
| Latency exponent | f | 1.0 | Scales retrieval time | ACT-R standard |

The decay parameter d = 0.5 is empirically validated across hundreds of ACT-R models. All other parameters are set by the modeler depending on the task and data to be fit.

---

## Emergent Behaviors

The remarkable thing about the base-level activation equation is how much behavior emerges from one formula.

**Stable preferences** (frequently reinforced) emerge when a chunk is accessed across many sessions, giving many overlapping traces. Even as each individual trace decays, the sum stays high. The preference "sticks" because it keeps being reinforced.

**Drifting interests** (recently clustered) appear when a chunk is accessed several times in a short period but never before. A burst of recent traces gives high activation now, but if the accesses stop, the cluster decays as a unit. The interest "drifts" with the recency of access patterns.

**One-off events** (single trace) fade quickly. A chunk created once and never accessed again has a single decaying trace. Without reinforcement, the event "fades" over time.

**Context-triggered recall** occurs when a chunk that dropped below threshold is accessed again. The old traces still contribute, albeit weakly. A new access adds a fresh trace that pushes activation above threshold. This produces the "oh, I remember that!" phenomenon where familiar context suddenly makes a forgotten memory accessible again.

One equation, many behaviors.

---

## References

**Anderson, J. R., & Lebiere, C.** (1998). *The Atomic Components of Thought.* Lawrence Erlbaum Associates. — The definitive ACT-R reference. Complete derivation of the activation equations, retrieval dynamics, and parameter values. Chapter 4 covers declarative memory in full.

**Anderson, J. R., & Schooler, L. J.** (1991). Reflections of the environment in memory. *Psychological Science*, 2(6), 396-408. — Empirical basis for the power-law decay parameter. Demonstrates that human forgetting curves match the statistical structure of real-world information relevance. The foundational paper explaining why ACT-R's equations work.

**ACT-R Tutorial, Unit 4: Activation of Chunks and Base-Level Learning.** Carnegie Mellon University. http://act-r.psy.cmu.edu/wordpress/wp-content/themes/ACT-R/tutorials/unit4.htm — Step-by-step tutorial with worked examples and implementation guidance. The best starting point for implementation.
