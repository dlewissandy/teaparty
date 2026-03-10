# Reasoning Interface Framework
### A brief for technical conversation
*Draft — March 2026*

---

## A Note Before You Read

I'm sending this ahead of Tuesday because I want to use our time well and the question is specific enough to warrant some advance context.

I'm building a framework for representing, navigating, and rendering reasoning processes -- initially to support a clinical differential diagnosis tool, but the abstraction is broader than that. In thinking through the architecture I've landed on a structure that feels like it should have a clean categorical description, and the terminology I keep reaching for sounds a lot like things you've said in our conversations.

I'm not asking you to validate a product idea. I'm asking whether the formal structure I'm describing is a known thing, what that tells us about its properties, and whether the renderer interface I'm proposing is the right formalism.

The open questions are at the end. That's the part I most want your reaction to.

---

## The Problem

Reasoning entities — AI systems, human experts, historical figures, students learning — consider alternatives, weigh evidence, resolve uncertainty, and arrive at conclusions. That process is almost entirely invisible to the people who depend on or learn from the output.

Current UI libraries were built for deterministic systems. You know what's coming back, you design for it. Reasoning output is probabilistic, variable in structure, variable in confidence. No component system treats that as a first-class design constraint.

The result: users get conclusions with no visibility into how they were produced, how confident the reasoner was, what would change the outcome, or where the reasoning is weak.

In high-stakes professional contexts — clinical diagnosis, legal analysis, financial decisions, compliance review — this is an accountability problem. In educational contexts — teaching geometry, algebra, grammar, history, medicine — it's a pedagogical problem. The same framework addresses both.

**The scope is broader than AI.** A reasoning trace can represent:
- An AI system's inference chain
- A clinician's diagnostic process
- A historical leader's decision under uncertainty (Churchill weighing invasion options, inputs considered, paths rejected)
- A student's proof attempt compared against an expert's trace of the same problem
- A supervisor reviewing a trainee's reasoning step by step

The framework doesn't care what did the reasoning. It cares about representing the process faithfully so it can be navigated, understood, and learned from.

---

## The Core Question

*How do you represent any reasoning process — human or AI — as a formal structure that can be rendered, navigated, and interrogated — independent of the rendering technology?*

Specifically:

- A reasoning trace has typed nodes (inference, evidence, assumption, conclusion, uncertainty, rejected path) and directed edges (led-to, contradicts, supports, unresolved)
- The trace has a temporal dimension — steps occurred in sequence, confidence shifted over time, branches were taken or rejected
- A user needs to navigate that trace — step forward and back, inspect individual nodes, understand why a conclusion was reached
- The rendering should be swappable — the same reasoning model should be expressible as a React Flow graph, an SVG diagram, a linear timeline, a text outline, or a printed clinical report

**The question for a category theorist:**
Does this have a clean categorical description? What must be preserved for the renderer swap to be formally valid? Where does composition break down?

---

## Why This Is Not a Knowledge Graph

A knowledge graph encodes what is known about a domain — static, structural, relational.

A reasoning trace encodes a thinking process — dynamic, temporal, process-oriented.

A reasoning trace may *reference* a knowledge graph ("this node fired because of this domain relationship") but they are distinct structures. The knowledge graph is the territory. The reasoning trace is the journey through it.

---

## Prior Work This Builds On

### Petri Net Stepping Debugger
Built in direct collaboration. Full playback controls — step forward, step back, watch token counts change per transition, highlighted active paths.

The structural mapping to a reasoning debugger:
- Places → Reasoning states
- Transitions → Inference steps
- Tokens → Active reasoning paths / confidence distribution
- Firing sequence → Playback timeline

The visualization and interaction problem is already solved. The data layer is different.

### Bayesian Network Authoring Tool
Built visual authoring interface for a Bayesian Network — nodes, conditional dependencies, belief propagation. React Flow for diagram authoring.

Direct relevance: Bayesian Networks are models of uncertainty and conditional reasoning. Building an authoring tool for one means the representation of probabilistic reasoning in a navigable visual structure is already understood.

### Clinical Differential Diagnosis Assistant
In active development. Three-layer hybrid architecture:
- Layer 1: LLM extraction (free text → structured JSON)
- Layer 2: Deterministic rule engine (clinical logic, auditable, consistent)
- Layer 3: LLM synthesis (narrative, differential table, formulation)

The rule engine emits structured reasoning metadata — rules fired, gaps detected, branches active, confidence signals. This is the first validation context for the reasoning interface framework. The rendering components need to exist to build the clinical tool. The question is whether to build them as throwaway implementation or as the seed of something reusable and releasable.

---

## Proposed Architecture

### Two Distinct Layers

**Layer 1 — Reasoning Model**
Pure TypeScript. No rendering concerns. Framework agnostic.

The data structures, state machines, and algorithms that represent and traverse reasoning processes.

```typescript
type ReasoningStepType =
  | 'inference'
  | 'evidence'
  | 'assumption'
  | 'conclusion'
  | 'uncertainty'
  | 'rejected'

interface ConfidenceSignal {
  value: number        // 0–1, source-agnostic
  source: 'rule_engine' | 'model_self_report' | 'retrieval_score' | 'human'
  basis: string        // human-readable explanation
}

interface ReasoningNode {
  id: string
  type: ReasoningStepType
  claim: string
  confidence: ConfidenceSignal
  evidence: Evidence[]
  alternatives: string[]   // ids of rejected or unconsidered paths
  stepIndex: number        // position in playback sequence
  metadata: Record<string, unknown>
}

interface ReasoningEdge {
  id: string
  source: string
  target: string
  type: 'led-to' | 'contradicts' | 'supports' | 'unresolved'
  weight?: number
}

interface PlaybackStep {
  stepIndex: number
  activeNodeIds: string[]
  activeEdgeIds: string[]
  confidenceSnapshot: Record<string, number>  // nodeId → confidence at this step
  annotation?: string
}

interface ReasoningTrace {
  id: string
  nodes: ReasoningNode[]
  edges: ReasoningEdge[]
  steps: PlaybackStep[]
  outcome: ReasoningOutcome
  metadata: Record<string, unknown>
}
```

**Layer 2 — Rendering**
Takes a ReasoningTrace as input. Renders to target. Swappable.

```typescript
interface ReasoningRenderer<TOutput> {
  render(trace: ReasoningTrace, options: RenderOptions): TOutput
}

// Implementations:
// ReactFlowRenderer     → React Flow graph component
// SVGRenderer           → standalone SVG, no framework dependency
// TimelineRenderer      → linear step-by-step view
// OutlineRenderer       → collapsible text hierarchy
// PrintRenderer         → static output for clinical records / reports
```

The renderer is a structure-preserving mapping from ReasoningTrace to output representation. What must be preserved: node identity, edge relationships, step sequence, confidence values. What may vary: visual layout, interaction model, level of detail.

---

## The Retrospective Reasoning Debugger

The flagship component. The concept that gives the library its identity.

**What it is:**
A navigable record of a reasoning process that already happened. Not a flowchart of possible paths — a specific trace of what actually occurred, made inspectable after the fact.

**Interaction model:**
- Graph view showing full reasoning trace
- Playback controls — play, pause, step forward, step back, jump to step N
- Active path highlighted at each step
- Node detail panel — claim, evidence, confidence, alternatives not taken
- Confidence timeline — separate view showing confidence distribution shift across steps
- Annotation layer — human marks nodes as agreed / disputed / needs evidence
- Diff view — compare two traces for the same input (e.g. before and after new information)

**Node types and visual treatment:**

| Type | Meaning | Visual signal |
|------|---------|---------------|
| inference | conclusion drawn from evidence | standard node |
| evidence | input data supporting a claim | distinct shape |
| assumption | premise taken without full evidence | dashed border |
| conclusion | terminal node, final position | highlighted |
| uncertainty | explicit unknown or unresolved signal | warning indicator |
| rejected | path considered and not taken | muted, accessible on demand |

**Why this matters beyond any single domain:**

Every context where reasoning produces consequential outcomes has the same need — to make that reasoning visible, navigable, and trustworthy.

Professional accountability: legal reasoning, financial analysis, medical triage, compliance review, supervisor reviewing a trainee's decision process, regulator auditing an automated decision.

Education: a student's proof trace through a geometry problem compared step by step against an expert's trace of the same problem. A history lesson built around Churchill's decision process — inputs considered, paths rejected, conclusion reached under uncertainty. Grammar instruction showing exactly which rules fired and why. Algebra showing each inference step rather than just the answer.

The diff view — two traces of the same problem, different reasoners — is a new kind of teaching tool that doesn't exist yet.

---

## The Broader Component Taxonomy

*(Appendix — product context, not needed for the formal questions)*

The debugger is the flagship component of a broader library. Listed here for completeness but not central to Tuesday's conversation.

**Input primitives**
- TriStateField (Present / Absent / Unknown)
- ConfidenceInput (structured uncertainty expression)
- StructuredQuestionCard (mini-form card, rule-driven, bypasses LLM)

**Inference display**
- ComparisonMatrix (ranked hypotheses or candidates with justification and missing signal)
- SignalDisplay (confidence value + source + basis, not just a number)
- InformationGapAlert (severity-tiered missing or unresolved signal indicator)
- ContextualInsight (triggered explanatory sidebar, domain-neutral teaching point)

**Reasoning display**
- ReasoningTrace (the debugger)
- EvidenceChain (linear path from evidence to conclusion)
- AlternativePaths (rejected branches, accessible on demand)

**Agentic flow**
- AgentProgressIndicator (what step, what's been decided, what's pending)
- ToolCallLog (what external calls were made, what they returned)
- DecisionCheckpoint (human-in-the-loop confirmation moment)

**Feedback and correction**
- NodeAnnotation (agree / dispute / needs evidence at the node level)
- CorrectionCapture (structured pushback that feeds back as signal)

---

## Open Questions — What I'm Bringing to Tuesday

These are the questions I actually need help with. The product and architecture context above is background. This is the conversation.

**1. Is this just a weighted DAG with a probability measure?**
A ReasoningTrace has nodes, directed edges, a temporal ordering, and confidence values that shift over time. That sounds like it might reduce to a weighted directed acyclic graph with a probability measure and a temporal ordering. If so -- is that a known categorical structure? Does it have a name? And what does that tell us about its properties -- composition, factoring, equivalence?

**2. What category does a ReasoningTrace live in?**
More precisely -- is there a clean categorical description of the structure? What are the objects, what are the morphisms?

**3. Is the renderer interface a functor?**
The renderer is intended to be a structure-preserving mapping from ReasoningTrace to output representation -- React Flow graph, SVG, timeline, text outline, printed report. What must be preserved for that mapping to be formally valid? Is functor the right word or is there a more precise formalism?

**4. Is the extraction pass a natural transformation?**
Taking LLM prose output and producing a structured ReasoningTrace feels like mapping between two different representations of the same underlying reasoning. Is natural transformation the right description? Is there a more precise one?

**5. Where does composition break down?**
Can two ReasoningTraces be safely merged -- for instance, combining a rule engine trace with an LLM reasoning trace for the same case? Can a trace be factored into sub-traces? What are the conditions under which composition is valid?

**6. The Petri Net and Bayes Net connection**
In retrospect -- what categorical structures were we actually building in those projects? Does the ReasoningTrace generalize them, specialize them, or is it orthogonal?

**7. The state machine question**
A reviewer might say "this is just a state machine, that's been done." The counter I'm reaching for: a state machine is prescriptive (models possible states and valid transitions), a reasoning trace is descriptive (records what actually happened including uncertainty and confidence distribution). Is that distinction categorically precise? Is there a better way to say it?

**8. Extracting a ReasoningTrace from LLM thinking output**
This may be the hardest practical problem in the whole system and it has two parts I'd want your reaction to.

*The formal part:* If a ReasoningTrace has a clean categorical description, does that description give us any purchase on the extraction problem? If we know the structure we're trying to produce, does that constrain how we should go about producing it? Can the target structure guide the extraction?

*The practical part:* LLM thinking output is unstructured prose -- narrative, sometimes circular, sometimes self-contradicting. It wasn't emitted with a schema in mind. Current approaches all have problems:

- Prompt the model to emit structured JSON directly -- degrades reasoning quality, the model thinks differently when constrained to a schema
- Post-process with a second LLM call -- more reliable but the second model is interpreting the first model's thinking, introducing another layer of potential distortion
- Fine-tune a model specifically for trace extraction -- expensive, requires training data that doesn't exist yet
- Hybrid -- deterministic parsing for identifiable patterns combined with LLM extraction for the rest -- probably the most pragmatic but still fragile

*The deeper problem:* LLM thinking output may not be faithful to the actual computation. A model can produce a plausible-sounding reasoning trace that doesn't reflect how the output was actually generated. You can extract a trace. You can't guarantee it's the real trace. This is the interpretability problem showing up at the application layer.

Is there a categorical way to characterize the relationship between the expressed trace and the underlying computation? And does that characterization suggest anything about how seriously to take the extracted trace as a representation of actual reasoning?

---

## What This Is Not

- Not a knowledge graph library
- Not a general diagramming tool
- Not a chat component library
- Not another MUI or shadcn
- Not a visualization library for static data

It is a framework for representing, navigating, and rendering any reasoning process — with the retrospective debugger as the primary interface paradigm. The reasoning entity may be an AI system, a human expert, a historical figure, or a student. The framework doesn't care. It represents the process.

---

*Built on prior work in Petri Net stepping debuggers, Bayesian Network authoring tools, and a clinical differential diagnosis system. Applicable to AI accountability, professional decision support, and instructional design. Validated against real clinical complexity before general release.*
