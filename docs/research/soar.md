# Soar Cognitive Architecture: Memory Systems Reference

This document is a self-contained explanation of the Soar cognitive architecture, focused on its memory systems. It is written for an engineer who has never used Soar. It covers the architecture's processing model, its distinct memory stores, its learning mechanisms, and the key equations.

---

## What Soar Is

Soar is a cognitive architecture developed by John E. Laird and colleagues at the University of Michigan. The project began in the 1980s with Allen Newell and Paul Rosenbloom; Laird has led its development since. The canonical reference is Laird (2012), *The Soar Cognitive Architecture* (MIT Press).

A cognitive architecture is a fixed computational substrate that specifies how an agent perceives, reasons, and acts. Soar's design claim is that intelligent behavior — across domains from games to robotics to natural language — emerges from a small set of memory systems and a single, unified decision cycle. The architecture does not prescribe what an agent knows; it prescribes how knowledge is stored, accessed, and learned.

Soar's central organizing principle is the **production rule**: an if-then rule that fires when its conditions match the current state of working memory and whose actions modify working memory. All reasoning in Soar is performed by production rules firing against working memory content. The architecture provides the cycle; the developer provides the rules.

---

## The Decision Cycle

Soar's processing is organized around a repeating **decision cycle**. Each cycle nominates, selects, and applies one operator — one unit of intentional action. The cycle has five phases:

### 1. Input

Sensory or environmental data enters working memory via an **input link** — a designated region of working memory connected to sensors or an environment interface. The architecture writes new WMEs (working memory elements, described below) reflecting current percepts.

### 2. Propose

Productions fire to **elaborate the current state** and **propose operators**. An operator is a named, structured object in working memory that represents a possible action or decision. A production proposes an operator by adding an **acceptable preference** for it to working memory. Multiple productions may propose multiple operators. The proposal phase runs until quiescence — no more productions can fire.

### 3. Select (Decide)

The **decision procedure** examines the set of proposed operators and their associated **preferences** and selects one. Preferences are explicit symbolic judgments about operators: acceptable, required, prohibited, better-than, worse-than, best, worst, or indifferent. The decision procedure applies these preferences in a fixed order:

1. If one operator is required and no others are required, select it.
2. Collect all acceptable operators.
3. Remove prohibited operators.
4. Remove rejected operators.
5. Eliminate operators dominated by better/worse comparisons.
6. Keep only best-marked operators if any exist.
7. Remove worst-marked operators.
8. Among mutually indifferent candidates, select at random; if none are indifferent to each other, an **impasse** occurs.

If the decision procedure cannot select a single operator — because no operators were proposed, because preferences conflict, or because multiple equally-preferred operators remain — a **tie**, **conflict**, **constraint-failure**, or **no-change impasse** is raised. Impasses are discussed below.

### 4. Apply

With an operator selected, productions that match the selected-operator pattern fire to **apply** it. Application productions modify working memory: they add new WMEs (called **o-supported** elements, which persist until explicitly removed) or modify state structure. This is where the agent's substantive work happens: updating beliefs, issuing commands, modifying data structures.

### 5. Output

Commands written to the **output link** — another designated working memory region — are transmitted to the environment (a motor system, an API, a simulator). The cycle then repeats.

---

## Impasses and Subgoals

An impasse is not an error. It is Soar's mechanism for invoking **deliberate problem-solving** when automatic processing fails. When an impasse occurs, Soar automatically creates a **substate** — a new state whose goal is to resolve the impasse. Within the substate, the full decision cycle runs recursively. The agent can propose and apply operators within the substate to reason about what the top-level agent should do.

Substates can nest: a substate may itself impasse and spawn a sub-substate. This creates a **stack of substates**, each working on a subproblem for the level above.

When a substate produces a **result** — a WME that connects to the superstate — the impasse is resolved and the substate is removed. The agent has determined what to do and returns to the main decision cycle.

There are four impasse types:

| Impasse | Trigger |
|---------|---------|
| No-change | No acceptable operators proposed, or selected operator fails to apply |
| Tie | Multiple operators remain after preferences; none is preferred over the others |
| Conflict | Contradictory preferences (A better than B and B better than A) |
| Constraint-failure | Multiple required operators, or require + prohibit on the same operator |

The impasse mechanism is what makes Soar's learning (chunking) possible — it is described in the Learning section below.

---

## Memory Systems

Soar has four distinct memory systems. Each stores a different kind of knowledge and operates by different rules.

### Working Memory

Working memory is Soar's central data structure. It holds **everything the agent currently knows**: the current state, proposed operators, preferences, perceptual input, memory retrieval results, and intermediate reasoning. All production rule matching happens against working memory. All production rule actions write to working memory. Working memory is the agent's entire cognitive context at any moment.

The primitive unit of working memory is the **working memory element (WME)**, an identifier-attribute-value triple:

```
(identifier ^attribute value)
```

Examples:
```
(S1 ^name my-state)
(S1 ^operator O1)
(O1 ^name move-north)
(B1 ^color red)
(B1 ^location room3)
```

The identifier is a symbolic label. The attribute is a slot name. The value is either a constant (a symbol or number) or another identifier, which allows WMEs to form linked structures. All WMEs with the same identifier belong to the same **object**. Objects link hierarchically through shared identifiers, forming a connected graph rooted at the top-level state.

**Support and removal.** A WME is maintained by one of two support types:

- **I-support (instantiation support)**: the WME exists as long as the production that created it continues to match. When the production's conditions no longer match working memory, the WME is automatically retracted.
- **O-support (operator support)**: the WME is created as a consequence of an operator application and persists until explicitly removed by another production. O-supported WMEs represent the agent's committed changes to the world.

WMEs without any support — because the production that created them retracted — are automatically garbage-collected, along with all WMEs that depended on them (unlinked elements vanish).

### Long-Term Procedural Memory (Production Memory)

Procedural memory stores **production rules** — the if-then rules that encode the agent's procedural knowledge. A production has the form:

```
production-name
  conditions (tests against working memory)
  -->
  actions (modifications to working memory)
```

A condition is a pattern that matches WMEs. For example:
```
(<state> ^operator <op> +)
(<op> ^name move-north)
(<state> ^location room3)
```

This condition matches any state where there is an acceptable operator named `move-north` and the current location is `room3`. Variables (written with angle brackets) unify across conditions — the same `<op>` must match in both condition lines.

Productions fire in **parallel**: every production whose conditions match working memory fires simultaneously each cycle. Soar does not have sequential programming flow; all knowledge in procedural memory acts at once on whatever the working memory presents.

Productions are categorized by what they do:
- **State elaboration**: add descriptive WMEs about the current state.
- **Operator proposal**: create an acceptable preference for a candidate operator.
- **Operator comparison**: add better/worse/indifferent preferences between operators.
- **Operator application**: apply the selected operator by modifying working memory.

### Semantic Memory (smem)

Semantic memory is a **long-term store of factual knowledge**. Unlike working memory — which is volatile and limited to the current context — semantic memory persists across the agent's lifetime and is accessed on demand.

**Data structure.** Semantic memory represents knowledge as **directed, connected subgraphs** of symbolic elements. Nodes are called **long-term identifiers (LTIs)**, labeled with the `@` prefix (e.g., `@5`, `@29`). Edges between LTIs are attribute-value pairs, just like WMEs. Unlike working memory's single connected graph, semantic memory can be disconnected — multiple disjoint subgraphs may coexist.

When an LTI is retrieved into working memory, the architecture creates a new short-term identifier in working memory that is linked to the LTI. The LTI itself remains in semantic memory; the working memory identifier is a temporary handle to it.

**Storage.** An agent stores knowledge in semantic memory by writing to the `smem.command.store` link in working memory. The architecture extracts the structure rooted at that point and adds it to semantic memory as a new LTI or augments an existing one.

**Retrieval.** An agent retrieves knowledge by writing a **cue** — a partial WME pattern — to the `smem.command.query` link. Semantic memory finds the LTI whose attributes best match the cue and reconstructs its augmentations in working memory. Matching follows three rules:
- Constant attribute-value pairs must match exactly.
- LTI-valued slots must match the specific LTI.
- Short-term identifier slots match any value (used to indicate "has this attribute" without specifying the value).

Among all LTIs that satisfy the cue, semantic memory returns the one with the highest activation.

**Base-level activation.** Semantic memory uses the **Petrov (2006) approximation** of the ACT-R base-level activation formula to rank LTIs. The approximation stores only the `k` most recent activation boosts (hardcoded to 10 in Soar) and computes:

```
BLA = ln [ sum(i=1 to k) of t_i^(-d)
           + ((n - k) * (t_n^(1-d) - t_k^(1-d))) / ((1 - d) * (t_n - t_k)) ]
```

Where:
- `n` = total number of activation boosts this LTI has received
- `k` = number of recent boosts stored (10 by default)
- `t_i` = time elapsed since the i-th boost (measured in decision cycles)
- `t_n` = time elapsed since the first (oldest) boost
- `t_k` = time elapsed since the k-th (most recent stored) boost
- `d` = decay parameter (default: 0.5)

The first term sums the exact contribution of the `k` stored recent boosts. The second term approximates the contribution of the remaining `n - k` older boosts using a closed-form integral, treating them as uniformly distributed between `t_k` and `t_n`. This approximation avoids storing the full access history while preserving a close estimate of the exact sum.

Higher activation means the LTI has been stored or retrieved recently and frequently. When multiple LTIs equally satisfy a cue, the one with highest activation is returned — recency and frequency bias retrieval toward contextually relevant memories.

**Spreading activation.** When base-level activation mode is enabled, spreading activation can be added on top. Activation spreads from LTIs currently instantiated in working memory to neighboring LTIs in semantic memory, following the directed graph structure. Each source LTI spreads a value to its direct children; the spread attenuates multiplicatively with depth according to a `spreading-continue-probability` parameter (default: 0.9). So direct children receive 90% of the source's spread value; grandchildren receive 81% (0.9 × 0.9); and so on. The total activation of an LTI is:

```
total_activation = BLA + spreading_activation
```

Spreading activation allows the current context to bias retrieval. An LTI linked to concepts that are already active in working memory receives a boost proportional to the structural proximity, not just the historical access pattern.

### Episodic Memory (epmem)

Episodic memory is a **timestamped record of the agent's experience**. While semantic memory stores factual knowledge that the agent explicitly stores and retrieves, episodic memory automatically records what the agent's working memory looked like at each decision cycle.

**Encoding.** At a configurable interval (default: every decision cycle), the architecture automatically snapshots the **entire top-level state** of working memory and stores it as a new episode. Episodes are numbered sequentially starting at 1. The snapshot stores all WMEs accessible from the top-level state, with two exclusions: WMEs whose attributes are not constants, and WMEs on explicitly excluded links (such as `epmem` and `smem` themselves, to avoid storing potentially large memory system structures).

The agent does not decide what to remember. All experience is recorded automatically.

**Cue-based retrieval.** An agent retrieves an episode by writing a **cue** to the `epmem.command.query` link. The cue is a partial WME structure describing what the agent is looking for. Retrieval proceeds in two stages:

1. **Surface matching**: find all candidate episodes containing at least one leaf WME (a cue WME with no sub-structure) that appears in the episode. This is a fast prefilter.
2. **Graph matching**: for each candidate, verify that the cue structure can be **structurally unified** with the episode — that is, the identifiers in the cue can be consistently mapped to identifiers in the episode such that all cue WMEs are satisfied.

The system returns the episode that best satisfies the cue by the scoring function:

```
score = (balance) * cardinality + (1 - balance) * activation
```

Where:
- `cardinality` = number of cue WMEs matched in the episode, normalized by cue size
- `activation` = working memory activation of matched WMEs (if working memory activation is enabled)
- `balance` = a tunable parameter (default: 1.0, meaning pure cardinality matching)

The highest-scoring episode among structurally valid matches is returned. If multiple episodes score equally, the most recent is preferred.

**Temporal retrieval.** Once an episode has been retrieved, the agent can step forward or backward through time:

- `^epmem.command.next` retrieves the episode immediately after the last retrieved one.
- `^epmem.command.previous` retrieves the episode immediately before.
- `^epmem.command.retrieve <time>` retrieves the episode at a specific timestamp.

This allows the agent to replay a sequence of past experience, predict the consequences of actions by pattern-matching against historical sequences, or locate a specific memory by navigating temporally from a known anchor.

---

## Learning Mechanisms

### Chunking

Chunking is Soar's primary learning mechanism. When a subgoal resolves an impasse and produces results, Soar **automatically compiles the problem-solving that occurred in the subgoal into a new production rule** and adds it to procedural memory. This new rule is called a **chunk**.

The chunk captures the essential relationship between the superstate conditions that were relevant to the subgoal's reasoning and the results that were produced. In future situations where the same superstate conditions hold, the chunk fires immediately and produces the same results — without spawning a subgoal, without deliberate reasoning, without re-deriving the answer.

The compilation process:

1. **Backtrace**: the system traces backward through all rules that fired in the substate, identifying which WMEs in the superstate those rules depended on.
2. **Identity tracking**: variables are assigned to elements, with elements that played the same role across multiple rule firings unified into the same variable.
3. **Constraint collection**: relational tests (e.g., `{ <x> < <y> }`) discovered during substate reasoning are preserved in the chunk's conditions.
4. **Rule formation**: conditions are assembled from backtraced superstate dependencies; actions are assembled from the substate results.

The resulting chunk is a normal production rule. It fires by pattern matching against working memory, just like hand-written rules. The agent gains new knowledge without any external supervision or reward signal.

**The key property**: once a chunk is learned, the agent never encounters the same impasse again in the same situation. The impasse prompted deliberate reasoning; the chunk converts that reasoning into automatic, reactive processing. Soar's knowledge compilation is **incremental** — the more impasses the agent encounters and resolves, the richer its procedural memory becomes, and the fewer impasses it encounters in the future.

This is fundamentally different from gradient-based learning: no weights are updated, no loss function is minimized. The agent either knows the answer (no impasse) or derives it in a subgoal (learns a chunk). There is no middle ground of "partially knowing" something.

### Reinforcement Learning

Soar supports **on-policy reinforcement learning** to tune numeric preferences on operators. The mechanism is called Soar-RL (Nason & Laird, 2004).

In Soar-RL, **RL rules** are productions that create **numeric-indifferent preferences** for operators. A numeric-indifferent preference contributes a Q-value-like signal to the decision procedure; the operator with the highest sum of numeric preferences is favored. RL rules have the standard production form, but their actions are constrained to creating numeric preferences of the form:

```
(<state> ^operator <op> = <value>)
```

The value is the learnable parameter — equivalent to Q(state, operator).

**Update rule (SARSA).** After each operator application, Soar updates the RL rules that contributed preferences to the selected operator. The update uses the SARSA(0) on-policy TD rule:

```
delta_t = alpha * [ r_{t+1} + gamma * Q(s_{t+1}, a_{t+1}) - Q(s_t, a_t) ]
```

Where:
- `alpha` = learning rate
- `gamma` = discount rate
- `r_{t+1}` = reward received at the next decision cycle (read from the `reward-link` in working memory)
- `Q(s_t, a_t)` = current Q-value of the selected operator (sum of all numeric-indifferent preferences for it)
- `Q(s_{t+1}, a_{t+1})` = Q-value of the operator selected in the next cycle

An off-policy Q-learning variant substitutes the maximum Q-value across available next-state operators instead of the chosen operator's value:

```
delta_t = alpha * [ r_{t+1} + gamma * max_{a} Q(s_{t+1}, a) - Q(s_t, a_t) ]
```

**Gap propagation.** When `n` non-RL operators intervene between RL operators (creating a gap in the sequence), the update discounts rewards across the gap:

```
delta_t = alpha * [ sum(i=t to t+n) gamma^(i-t) * r_i  +  gamma^(n+1) * Q(s_{t+n+1}, a_{t+n+1})  -  Q(s_t, a_t) ]
```

**Multiple contributing rules.** When multiple RL rules contribute numeric preferences for the same operator, the computed delta is divided equally among them. Each rule's value is updated by `delta_t / m` where `m` is the number of contributing rules.

---

## Impasse-Driven Learning

A critical structural property of Soar: **learning only occurs when the agent gets stuck**. Chunking fires when a subgoal produces results. Subgoals are created by impasses. If the agent never impasses — because it already has sufficient procedural knowledge — no new chunks are created.

This is not a limitation; it is a design choice with specific consequences:

- **Learning is triggered by ignorance, not by success.** The agent acquires knowledge precisely where its current knowledge is insufficient. It does not re-learn things it already knows.
- **Learned knowledge is complete, not approximate.** A chunk encodes the full derivation of a result from superstate conditions. It does not generalize statistically from examples; it compiles reasoning exactly. The chunk is correct by construction (assuming the subgoal reasoning was correct).
- **The agent converges.** As the agent encounters situations and resolves impasses, it accumulates chunks that cover those situations. Eventually, for a fixed environment, the agent reaches a state where it almost never impasses — almost all behavior is automatic. This convergence is observable and verifiable.
- **Novel situations still cause impasses.** A situation that differs from any previously encountered one will still trigger an impasse. The agent is not brittle in the sense of failing silently; impasses are explicit and handled by the subgoal mechanism.

Contrast this with systems that learn after every interaction: they learn continuously regardless of whether they needed to, and their knowledge generalizes probabilistically. Soar's learning is sparse, triggered, and exact.

---

## Key Properties and Trade-offs

**What Soar does well:**

- **Impasse-driven learning (chunking)** is architecturally guaranteed: once a subgoal resolves a situation, the agent never deliberates over the same situation again. Procedural knowledge accumulates monotonically.
- **Transparent decision-making**: because all decisions are made by production rules firing against symbolic working memory, the agent's reasoning is inspectable. Every WME and every rule that fired is available for debugging and analysis.
- **Unified architecture**: working memory, procedural memory, semantic memory, and episodic memory interact through a single currency (WMEs and production rules). There is no impedance mismatch between memory systems.
- **Graceful decomposition**: the impasse/subgoal mechanism provides a principled way to handle situations that exceed the agent's current knowledge. Complex problem-solving is just nested decision cycles.

**What Soar struggles with:**

- **Learning from success without impasses**: if the agent selects the right operator and applies it successfully, no impasse occurs and no chunk is learned. Soar does not improve on paths it already knows. Reinforcement learning partially addresses this for preference refinement, but chunking — the primary learning mechanism — is blind to successful trials.
- **Gradual preference adjustment**: chunking is binary (a chunk fires or it does not). Fine-grained preference learning — where the agent should increasingly prefer one operator over another based on accumulated evidence — requires reinforcement learning or explicit comparison productions, not chunking.
- **Scale of the rule base**: in large domains, the number of productions can become very large, and the cost of matching all productions against working memory every cycle grows. Soar uses the Rete algorithm for efficient incremental matching, but the fundamental cost scales with the number and complexity of rules.
- **Knowledge acquisition bottleneck**: the developer must write the initial set of productions that enable the agent to attempt tasks at all. If the agent has no productions that propose operators for a situation, it will impasse immediately and may not have enough knowledge in the subgoal to resolve it. The bootstrap problem is real.

---

## References

**Laird, J. E.** (2012). *The Soar Cognitive Architecture*. MIT Press. — The definitive reference. Covers the decision cycle, all memory systems, chunking, and reinforcement learning in full. The primary source for this document.

**Laird, J. E.** (2022). "Introduction to the Soar Cognitive Architecture." arXiv:2205.03854. https://arxiv.org/abs/2205.03854 — Accessible survey of the architecture with current descriptions of all memory systems.

**Nason, S., & Laird, J. E.** (2005). Soar-RL: Integrating reinforcement learning with Soar. *Cognitive Systems Research*, 6(1), 51-59. https://doi.org/10.1016/j.cogsys.2004.09.004 — Original paper on the Soar reinforcement learning mechanism, Q-value storage in production rules, and the SARSA update.

**Nuxoll, A. M., & Laird, J. E.** (2007). Extending cognitive architecture with episodic memory. *AAAI 2007*. https://aaaipress.org/Papers/AAAI/2007/AAAI07-247.pdf — Original paper introducing episodic memory (epmem) into Soar: encoding, cue-based retrieval, and temporal navigation.

**Laird, J. E., Congdon, C. B., Assanie, M., Derbinsky, N., & Tinkerhess, M.** (2012). The Soar User's Manual. University of Michigan. https://soar.eecs.umich.edu — Official manual covering all four memory systems and learning mechanisms with implementation details.

**Soar Reference Manual — Semantic Memory.** University of Michigan Soar Group. https://soar.eecs.umich.edu/soar_manual/06_SemanticMemory/ — Primary source for the base-level activation formula (Petrov approximation), spreading activation parameters, and cue retrieval semantics.

**Soar Reference Manual — Episodic Memory.** University of Michigan Soar Group. https://soar.eecs.umich.edu/soar_manual/07_EpisodicMemory/ — Primary source for episodic encoding, graph-matching retrieval, and the episode scoring formula.

**Soar Reference Manual — Reinforcement Learning.** University of Michigan Soar Group. https://soar.eecs.umich.edu/soar_manual/05_ReinforcementLearning/ — Primary source for the SARSA and Q-learning update equations in Soar-RL, including gap propagation and multi-rule delta division.
