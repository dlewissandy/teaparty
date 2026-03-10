# RIF Integration with the POC: A Structural Analysis
**March 2026** | Can the Reasoning Interface Framework integrate with the POC, and under what conditions?

---

## 0. What This Is

One question: can the Reasoning Interface Framework integrate with the POC, and under what conditions? Conditional yes. The structural fit is real, the extraction path is tractable, three schema gaps must be resolved before integration is valid rather than decorative. Those three gaps are named in Section 7.

---

## 1. The Structure of a ReasoningTrace

In a representative POC session, a writing subteam runs through: DRAFT → PLAN_ASSERT → PLAN → TASK → TASK_IN_PROGRESS → (B3 backtrack) → PLANNING_QUESTION → PLANNING_RESPONSE → DRAFT → PLAN_ASSERT → PLAN → TASK → COMPLETED_TASK → WORK_ASSERT → COMPLETED_WORK. At each state transition, `PlaybackStep.confidenceSnapshot` records the confidence distribution over active nodes. The confidence over the 'schema_is_stable' inference node at step 2 (pre-backtrack) is 0.8. At step 5 (post-B3), it has been replaced by a new inference node 'schema_changed_in_migration' at confidence 0.9, and a 'contradicts' edge connects them. This is not a static DAG: confidence values are step-indexed, not fixed properties of nodes.

**Formal observation:** A `ReasoningTrace` assigns a step-indexed measure over nodes — closer to a filtered probability space indexed by step than to a weighted DAG. At step k, only confidence values up to step k are known. The filtration is not reorderable: you cannot permute steps without changing the semantics. This has direct implications for diff and composition — a diff of two traces must align on step index, not just on node identity.

### Typed Edges

The B3 backtrack produces a 'contradicts' edge (source: 'schema_is_stable', target: 'schema_changed_in_migration'). The subsequent synthesis step produces a 'led-to' edge (source: 'schema_changed_in_migration', target: 'revised_task_assignment'). These are qualitatively different relationships. A 'contradicts' edge carries information about what was invalidated and why; a 'led-to' edge carries information about what followed from what. A weighted DAG with negative weights for 'contradicts' collapses this distinction. The RIF preserves it by design.

### The Category

Objects are `ReasoningTrace` values. Morphisms are step-index-preserving maps that respect edge type. Identity (map a trace to itself) and composition (chain two step-preserving maps) are both well-defined. The B1-B7 backtrack transitions are the clearest examples of trace morphisms in the POC: a backtrack takes the trace up to the backtrack point and produces a new sub-trace from the re-entry state. B3 maps the trace through step 4 to a new trace beginning at PLANNING_QUESTION.

### Limits and Colimits

A product of two traces requires a shared interface. The POC does not currently provide one — `dispatch.sh` returns an opaque prose summary. A pushout is the right operation for merging parent and child traces, but pushouts require a span.

### Parking: Monoidal Structure

Does the trace category have a monoidal structure — a tensor product of traces corresponding to parallel reasoning? Partial answer: the POC does support parallel subteam execution via `SendMessage`, so the structure exists at the system level. The formal path is enriched category theory — the trace category enriched over [0,1]-valued filtrations, with step-index as a functor from the ordinal category ω. Named gap: **step-indexed edge weights** — the current `ReasoningEdge.weight?: number` is a fixed scalar, making the enriched characterization incomplete because it cannot represent how relationship strength varies across steps. Path forward: add `stepWeights?: Record<number, number>` to `ReasoningEdge`; verify the resulting structure is a valid enriched category over filtered probability spaces.

---

## 2. The Renderer as Functor

### Test Against display_filter.py

`display_filter.py` is the POC's actual renderer. It is concrete, running code, and its behavior is precisely testable against the three functor conditions. The functor claim requires: (a) preservation of node types, (b) preservation of edge types, (c) preservation of step sequence.

| Condition | What it requires | `display_filter.py` | Result |
|---|---|---|---|
| (a) Node type preservation | All node types represented | Discards all thinking-block nodes — 'rejected' and 'assumption' nodes that only appear in thinking output vanish | **FAILS** |
| (b) Edge type preservation | 'contradicts' ≠ 'led-to' | All inter-agent communication renders as `[sender] @recipient: content` — no edge type distinction | **FAILS** |
| (c) Step sequence preservation | Events in stream order | `SendMessage` events displayed in stream order | **PASSES** |

**Formal observation:** `display_filter.py` is a projection, not a functor. This is not a criticism — legibility requires lossy projection, and `display_filter.py` is well-suited to its purpose. The point is that "functor" now has a precise meaning: a renderer that passes all three conditions.

### What the Functor Condition Buys

Two renderers that both satisfy (a), (b), (c) are formally swappable — the same `ReasoningTrace` produces equivalent representations up to layout. A `ReactFlowRenderer` and a `ClinicalReportRenderer` can both be functors. `display_filter.py` cannot, and does not need to be.

### A Functor Renderer (Concrete)

A `ClinicalReportRenderer` that maps 'rejected'-type nodes to "path considered and excluded" entries, maps 'contradicts' edges to "superseded assumption" annotations, and maps step index to temporal position in the report timeline — satisfies all three conditions. The clinical supervisor sees the same inferential structure as the React Flow graph user, rendered for a printed record rather than an interactive display.

---

## 3. Extraction and the Uber/Subteam Boundary

### The Naturality Setup

Let F map CfA sessions to stream-JSON records. Let G map CfA sessions to `ReasoningTrace` values. Let η be the extraction family. The naturality square says: refine-then-extract = extract-then-update. Concretely: if we run a session, extract a trace, then run a refined version of the same session (with one new piece of evidence), the trace we extract from the refined session should be the same as the trace we'd get by taking the original trace and applying the update map for that evidence.

### Rule-Engine Case — Naturality Satisfied

In the clinical tool's Layer 2, the rule engine emits structured metadata at each state transition: rule ID, firing conditions, confidence value, branch status. This metadata is deterministic and append-only. Extracting a `ReasoningNode` from this output is a pure function of the metadata. If we refine the session (add a lab result that fires a new rule), the new extraction is structurally identical to updating the original trace with the new node — the naturality square closes. The extraction pass for deterministic rule metadata is a genuine natural transformation.

### LLM Thinking Block Case — Naturality Fails

In Layer 3 synthesis, the session lead's thinking block for a B3 backtrack contains: "I need to raise the schema issue to planning." Run the extraction twice on the same thinking block and get different node IDs, different claim phrasings, possibly different edge assignments — the LLM introduces non-determinism. The naturality square does not close. The extraction pass for LLM thinking blocks is at best a lax natural transformation — the square commutes only up to isomorphism, and only when the LLM happens to be consistent.

**Formal characterization:** The extraction pass is a lax natural transformation. The rule-engine case satisfies the laxness condition; the LLM case does not. This is not a categorical technicality — it means that LLM-extracted traces cannot be reliably composed or diffed without the `extractionMethod` field to mark which nodes are which.

Named gap: **extractionMethod field.** `ReasoningNode` has no field distinguishing deterministic from LLM-extracted nodes. Path forward: add `extractionMethod: 'deterministic' | 'llm_extracted'` to `ReasoningNode`; propagate from the `/extract-trace` skill.

### Where Composition Breaks Down — the dispatch.sh Boundary

After a writing subteam completes its dispatch, `dispatch.sh` writes `.result.json` containing: the final result text ("writing-subteam completed chapter 1"), total cost, number of turns, a prose summary. The uber team receives this and represents the entire subteam execution as a single inference-type node: "writing-subteam execution completed with backtrack_count=2."

The subteam's actual trace contains: 12 `PlaybackStep`s, 7 `ReasoningNode`s (including 2 'assumption' nodes that were contradicted), 5 `ReasoningEdge`s (including 1 'contradicts' edge from the B3 backtrack), and a confidence snapshot showing the confidence in the revised schema assumption at 0.9 at final step.

None of that structure survives the `.result.json` boundary. There is no structure-preserving morphism from the subteam's `ReasoningTrace` to the uber's single-node representation — a morphism from a 12-step filtered probability space to a terminal object is not injective on morphisms. Composition at this boundary is formally invalid.

This is a design decision, not a bug. The uber team's context isolation is a feature — it prevents context rot by keeping the uber lead from drowning in subteam detail. Full compositional tracing and context isolation are in tension. The question is not "fix this" but "what is the minimum structure needed at the boundary to enable valid composition without breaking context isolation?"

Named gap: **mergeTraces() semantics.** No `mergeTraces()` function is defined. The pushout required for composing traces requires a span. Path forward: extend `.result.json` to carry (a) node counts by type, (b) list of edge types that appeared, (c) final-step confidence snapshot — the minimum structure for a trace morphism at the boundary. Then define `mergeTraces(parent, child, boundary)` where `boundary` is the structured `.result.json`.

### The Hybrid Extraction Strategy

The tractable path is: (1) deterministic parsing of CfA state transitions and tool calls from `.exec-stream.jsonl` → `PlaybackStep`s and inference/evidence nodes, `extractionMethod: 'deterministic'`; (2) optional LLM extraction of reasoning content from thinking blocks → additional nodes, `extractionMethod: 'llm_extracted'`; (3) merge with `extractionMethod` preserved per node.

Step 1 alone produces a faithful skeletal trace. Step 2 adds interpretive richness at the cost of faithfulness. The `extractionMethod` field makes this trade-off explicit rather than hidden.

---

## 4. Petri Nets, Bayes Nets, and the State Machine

### Petri Nets

The POC's prior Petri Net stepping debugger exploited a specific categorical property: Petri Net executions form a symmetric monoidal category (Meseguer and Montanari, 1990). Independent firings can be permuted without changing the outcome — the debugger can replay any valid firing sequence. A `ReasoningTrace` is not symmetric monoidal: step order is essential. Permuting the B3 backtrack (step 4) to step 2 changes the meaning of the trace — a different set of nodes were active at step 2, and the contradiction that triggers B3 hadn't been observed yet. The Petri Net structure was the right formalism for the debugger prior work. It is the wrong formalism for `ReasoningTrace`.

### Bayes Nets

`ConfidenceSignal.value` is a scalar in [0,1] with provenance metadata (source, basis). It is not a conditional probability distribution. You cannot run belief propagation over a `ReasoningTrace` — there is no joint distribution, no conditional independence structure. The Bayesian Network authoring tool was building a different object. The formal connection between `ConfidenceSignal` and probability theory runs through the Kleisli category of the Giry monad, but that connection requires upgrading `ConfidenceSignal.value` from a scalar to a `Distribution`. As currently specified, the trace is not a Bayes Net. Path forward: replace `ConfidenceSignal.value: number` with `ConfidenceSignal.distribution: Distribution` — then the trace becomes a valid object in the Kleisli category and belief propagation becomes well-defined.

### The State Machine Distinction

The CfA state machine is a labeled transition system (LTS) — a coalgebra specifying which transitions are *possible*. The stream-JSON from a specific POC session is one *trace* of that LTS — a specific execution path. The RIF's `ReasoningTrace` is a *decorated* trace: it adds why the B3 backtrack happened (the 'contradicts' edge from evidence E3 to inference N7), what the confidence was at each step (`confidenceSnapshot`), and which inference was revised (new node post-re-entry). The LTS is prescriptive; the `ReasoningTrace` is descriptive. A state machine is a coalgebra; a `ReasoningTrace` is a decorated path object in the trace category. These are formally distinct structures, and the distinction is the point of the RIF.

---

## 5. Integration Points

### CfA to RIF Mapping

| CfA concept | RIF concept | Notes |
|---|---|---|
| State transition event in `.exec-stream.jsonl` | `PlaybackStep` | step index = event sequence number in stream |
| B1-B7 backtrack transitions | 'contradicts' edges | source = pre-backtrack inference node; target = new node post-re-entry |
| RESPONSE state synthesis output | 'led-to' edges from synthesis inputs to new DRAFT/PROPOSAL | synthesis funnel enforces this ordering |
| `backtrack_count` in `.cfa-state.json` | natural confidence signal for session complexity | readable without parsing thinking blocks |
| Tool call results (`Write`, `Bash`, `Read`) | evidence nodes, `extractionMethod: 'deterministic'` | faithful |
| Thinking block content | inference/assumption nodes, `extractionMethod: 'llm_extracted'` | not faithful |
| `.result.json` prose summary | single inference node at uber level | composition-invalid without structured boundary |

### The Synthesis Funnel as a Structural Guarantee

Every B1-B7 backtrack re-enters at a RESPONSE state (`INTENT_RESPONSE` or `PLANNING_RESPONSE`) or QUESTION state. The synthesis funnel then produces a new DRAFT or PROPOSAL before any assertion is made. This means in the POC: every 'contradicts' edge in the `ReasoningTrace` is structurally followed by a synthesis step that produces a 'led-to' edge from the new evidence to the revised assertion. This is a POC-specific invariant that the general RIF does not guarantee but can exploit — a clinical supervisor auditing the trace can verify that every contradiction was formally processed before a new claim was asserted.

### /extract-trace Skill

Reads `.exec-stream.jsonl` for a given dispatch. Extracts CfA state transitions and backtrack events deterministically. Emits `ReasoningTrace` JSON with `extractionMethod: 'deterministic'` on all state-transition-sourced nodes. Does not parse thinking blocks in default mode. Optional `--include-thinking` flag invokes LLM extraction on thinking blocks and merges results with `extractionMethod: 'llm_extracted'`. Faithful extraction from stream structure, not from LLM prose reconstruction.

### /replay-trace Skill

Loads a persisted trace, drives the `ReasoningDebugger` component. Concrete user interactions:

The clinical supervisor steps backward through the B3 backtrack to see what confidence signal (`backtrack_count` increment plus tool call result) triggered the escalation to planning. The student navigates to step 4 of the expert trace (the B3 backtrack decision point) and compares the expert's `confidenceSnapshot` against their own at the same step index — the expert's confidence in 'schema_is_stable' was already dropping at step 3; the student's was still 0.9. The accountability auditor inspects all 'contradicts' edges in a completed session trace to verify that every plan revision was preceded by a documented contradiction event — the synthesis funnel guarantee makes this audit linear in the number of backtracks, not requiring a full trace search.

The interactive debugger is the strongest single argument for RIF integration: it turns `.exec-stream.jsonl` from an infrastructure artifact into a navigable reasoning record.

### MCP Exposure

An MCP tool exposing a `ReasoningTrace` is valid iff its serialization preserves node identity, edge type, and step index. The current `.result.json` preserves none of these. An MCP tool wrapping `.result.json` is NOT a valid `ReasoningTrace` exposure. An MCP tool wrapping the full `ReasoningTrace` JSON from `/extract-trace` is valid.

### Memory System Interaction

Corrective memory entries (30-day TTL, M4 trigger, promotes to global at n_r ≥ 1) and 'contradicts' trace edges are complementary. A corrective entry captures the durable abstracted lesson: "verify database schema before planning when migrations are active." A 'contradicts' edge in a specific trace captures the full provenance: at step 4 of session-20260308-140440, inference node N7 ('schema_is_stable', confidence 0.8) was contradicted by evidence node E3 ('schema_migration_log shows change', confidence 1.0), triggering B3 backtrack. The corrective entry prevents recurrence. The trace edge makes the specific instance navigable. Neither substitutes for the other.

---

## 6. The Interpretability Problem

The LLM thinking-block problem is not unique to the POC. It is the application-layer manifestation of a fundamental interpretability question: does a model's expressed reasoning reflect its actual computation?

**Categorical framing:** The expressed trace (what appears in thinking blocks) and the underlying computation (the forward pass that produced the output) are related by a map that is not injective. Multiple underlying computations can produce the same expressed trace. The expressed trace is a projection from a higher-dimensional space. There is no categorical inverse — you cannot reconstruct the underlying computation from the expressed trace.

**What this means practically:** For the rule-engine and CfA state-transition layers, this problem does not arise — the deterministic metadata IS the computation, not a report of it. The faithfulness problem is confined to LLM synthesis content. The hybrid extraction strategy (Section 3) contains the problem: `extractionMethod: 'llm_extracted'` marks the nodes where faithfulness cannot be guaranteed, leaving the deterministic skeleton uncontaminated.

**Reverse Differential Categories:** Treating each node's confidence as a function of incoming edge weights and applying a chain-rule-style backward pass — sensitivity analysis on the confidence DAG — is computable today with the current schema, provided `ConfidenceSignal.value` is a scalar. This is Approach 1. Approach 2 — attention attribution on the LLM layer — is a different question requiring model internals. The RDC framing is correct as a long-term direction but not immediately applicable: the chain rule requires smooth functions over well-defined domains, and `ConfidenceSignal.value` as an opaque scalar from `model_self_report` does not satisfy this. Path forward: (1) upgrade `ConfidenceSignal` to carry a probability distribution, (2) define smooth interpolation between distributions, (3) specify an optimization target, (4) apply RDC machinery.

---

## 7. Verdict

The structural fit is real. The 25-state CfA machine produces the right kind of object for a `ReasoningTrace`: typed events, step-ordered, confidence-signaled, backtrack-provenanced. The synthesis funnel is a stronger structural guarantee than the general RIF requires — every 'contradicts' edge is followed by a synthesis step, making contradiction-audit linear rather than requiring full search. The interactive debugger is immediately realizable from `.exec-stream.jsonl` via the `/extract-trace` skill. The diff view is immediately realizable from the git branch model.

Integration is conditionally valid. Three schema gaps must be resolved first. Without all three, integration produces a trace that looks like a `ReasoningTrace` but does not support renderer swappability, valid composition, or calibrated trust — the formal properties that justify the framework.

### The Three Integration Prerequisites

**1. step-indexed edge weights** (`ReasoningEdge.stepWeights?: Record<number, number>` absent from RIF schema). The current `weight?: number` is a fixed scalar. A 'contradicts' edge from step 4 that is resolved by step 7 cannot be represented — the edge weight at step 4 is different from the edge weight at step 7, but the schema has one slot. Without this, the trace cannot represent the evolution of relationship strength across playback, and the enriched categorical characterization remains incomplete. Resolution: add `stepWeights?: Record<number, number>` to `ReasoningEdge`.

**2. mergeTraces() semantics** (no pushout-compatible boundary at `dispatch.sh`). Composing a subteam's `ReasoningTrace` into the uber team's trace requires a span — a shared structured boundary. `dispatch.sh` currently returns prose. The uber team cannot form a valid trace morphism. Resolution: extend `.result.json` to carry (a) node counts by type, (b) edge type list, (c) final-step confidence snapshot; define `mergeTraces(parent, child, boundary)`.

**3. extractionMethod field** (`ReasoningNode.extractionMethod` absent from RIF schema). The extraction pass produces nodes from two sources with different reliability: deterministic CfA state events (faithful) and LLM thinking-block interpretation (not faithful). Without this field, downstream consumers cannot distinguish structurally grounded nodes from interpretively reconstructed ones, and lax naturality silently contaminates the trace. Resolution: add `extractionMethod: 'deterministic' | 'llm_extracted'` to `ReasoningNode`.

All three changes are additive. No breaking schema changes. All directly testable against existing `.exec-stream.jsonl` data.
