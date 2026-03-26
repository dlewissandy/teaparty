# Human Participation: Seats at Every Table

Humans are team members, not external observers. They participate at every level of the hierarchy, from cross-project coordination with the office manager down to individual subteam dispatches. The system learns from their participation at each level, and what it learns at one level informs how it works at others.

This document describes the human participation model for a single human. Multi-human teams (multiple deciders, advisors, domain experts) are a future extension that builds on these foundations.

---

## The Human's Seats

The human occupies a position at each level of the team hierarchy. At some levels they participate directly. At others, the proxy stands in for them. The human can move between levels at will.

```
Office Manager Team
├── Human (direct participant)
├── Office Manager (team lead)
│
├── Project: POC
│   ├── Human (direct participant OR proxy)
│   ├── Project Lead
│   │
│   ├── Subteam: Coding
│   │   ├── Proxy (stands in for human)
│   │   └── Coding agents
│   │
│   └── Subteam: Writing
│       ├── Proxy (stands in for human)
│       └── Writing agents
│
└── Project: Joke-book
    ├── Proxy (stands in for human)
    ├── Project Lead
    └── ...
```

The proxy is a single logical entity per human. It has one memory, one interaction counter, one personality model. The multiple seats in the diagram are roles, not instances. When a coding subteam gate and a writing subteam gate arrive at the same time, the proxy processes them sequentially through a FIFO queue. It is instantiated per-level as needed, but all instantiations share the same memory database.

At the office manager level, the human always participates directly. This is their coordination layer, where they steer priorities, ask cross-cutting questions, and decide what gets worked on.

At the project level, the human chooses. They can sit in on a project session and participate directly (reviewing artifacts, answering questions, providing corrections), or they can let the proxy handle it. When the human shows up, they take their own seat. When they leave, the proxy resumes. This is how real teams work: you can send a delegate to a meeting, or you can attend yourself.

At the subteam level, the proxy almost always stands in. The human can't attend every subteam meeting. But they can drop in if they want to.

---

## Direct Participation vs. Proxy

When the human is present at a level, they speak for themselves. When they're absent, the proxy speaks for them. There is no hybrid mode where both speak, as that would create conflicting signals. (The proxy's accumulated memory remains available for retrieval by other agents; this is memory, not active participation.)

The transition works like this:

**Human arrives.** The proxy steps aside. Gate questions go to the human directly. The proxy observes but does not generate predictions. What gets recorded is an *observation chunk*: the context (CfA state, task type, artifact summary), what the human said, and what they decided. This is a simpler schema than the full two-pass prediction chunk. It has no prior/posterior fields and no surprise delta, because the proxy wasn't predicting. But it captures the ground truth of what the human cared about and how they responded, which is exactly what the proxy needs for future predictions. The detailed schema for observation chunks is a design-level concern.

**Human leaves.** The proxy resumes. Gate questions go to the proxy, which generates predictions and either acts autonomously or escalates based on its confidence. The proxy now has fresh observation chunks from the human's direct participation. It saw what the human said, what they cared about, what they corrected. Its next predictions incorporate that.

**Human never shows up.** The proxy handles everything at that level, earning autonomy through accurate prediction as described in [proxy-memory-motivation.md](../detailed-design/proxy-memory-motivation.md).

The current implementation only supports the "human never shows up at subteams" and "human always shows up at project level" patterns. Making the transition dynamic (human drops in mid-session, proxy steps aside) is a Phase 2 capability that requires the approval gate to detect presence and switch modes.

---

## Learning Flows Across Levels

What the human does at one level reveals information useful at other levels. The ACT-R shared memory pool is the mechanism for this.

Currently, memory databases are per-project per-team. Each project maintains its own `.proxy-memory.db` (or `.proxy-memory-{team}.db` for named teams). This means the cross-level flows described below work within a project today. Cross-project flows (upward to the office manager, lateral between projects) require either a shared memory pool or a federation layer across per-project databases. Whether to unify into a single shared pool or federate across project databases is an architectural decision that has not yet been made.

### Upward: Project Gates Inform the Office Manager

When the human corrects a plan at PLAN_ASSERT ("add a rollback strategy"), the proxy records a `gate_outcome` chunk. The next time the human asks the office manager "how's the POC project going?", the office manager retrieves that chunk and can report: "the planning phase completed, and the plan was corrected to include a rollback strategy."

The office manager didn't attend the gate. But it has access to what happened through shared memory. It can synthesize a status report that reflects the human's actual concerns, not just raw state. This flow requires the cross-project memory unification described above.

### Downward: Office Manager Steering Informs Gates

When the human tells the office manager "focus on security across all projects", the office manager records a `steering` chunk. The next time the proxy reviews a plan at PLAN_ASSERT, it retrieves that chunk and gives extra scrutiny to security aspects.

The proxy didn't hear the human say it. But the steering chunk surfaced through the shared pool because the structural context matched. The human's cross-cutting directive reached the gate decision without explicit forwarding. Again, this depends on the cross-project memory architecture being in place.

### Lateral: Patterns in One Project Inform Another

When the human consistently corrects plans in the POC project for missing error handling, the proxy accumulates `gate_outcome` chunks with that pattern. If the joke-book project later produces a plan with similar gaps, the proxy retrieves those POC chunks (the structural filter matches on state, the semantic filter matches on content) and applies the learned pattern.

Lateral transfer cannot happen today. Per-project databases prevent it. Making it work requires the architectural decision on shared vs. federated memory. Even once the plumbing exists, whether lateral transfer helps or hurts is an empirical question. If the projects are similar (two backend services), corrections probably generalize. If they are dissimilar (a compiler and a joke book), cross-project retrieval is noise injection. Phase 1 evaluation should test this, and the default should probably be off until the evidence says otherwise.

---

## The Office Manager's View of the Human

The office manager learns about the human differently than the proxy does.

The proxy learns gate behavior: what the human approves, what they correct, what they attend to in artifacts. Its chunks are structured around CfA states, outcomes, and prediction deltas. Its model is "given this state and this artifact, what would the human say?"

The office manager learns coordination behavior: what the human asks about, what they prioritize, when they intervene. Its chunk types would include `inquiry`, `steering`, `action_request`, and `context_injection`. These chunk types do not exist in the current codebase. The office manager layer is not yet implemented, and its memory model is a separate design effort. It would share the same ACT-R retrieval mechanics as the proxy but use a different chunk schema optimized for coordination behavior. The shared memory pool concept requires schema coexistence, not schema identity: retrieval filters by chunk type, so proxy chunks and office manager chunks do not compete. Expanding the shared pool to accommodate office manager chunk types is a detailed design requirement.

The office manager's model is "what does the human care about right now, and what do they need to know?" Both models describe the same human from complementary angles.

Here is what the cross-level flow looks like in practice. The human tells the office manager "I'm worried about the database migration." The office manager records a `steering` chunk. The proxy retrieves it at the next database-related gate and gives the migration plan closer scrutiny. The office manager learned a priority; the proxy turned it into gate behavior. The shared memory pool handled the coordination without either agent being told to talk to the other.

The reverse flow works too. The human corrects a plan at PLAN_ASSERT with "this needs better error handling." The proxy records a `gate_outcome` chunk with a correction delta. The office manager retrieves it when the human asks "how are things going?" and can report that error handling has been a recurring concern.

---

## What the Human Experiences

From the human's perspective, the system remembers what they care about regardless of which level they said it at.

Say the human tells the office manager they're concerned about security. A week later, at a project gate, the proxy asks pointed questions about the security implications of the plan. The human didn't repeat their concern. The steering chunk surfaced in retrieval because the semantic match was strong. Or: the human corrects three plans for missing tests. The next time they check in with the office manager and ask how things are going, the office manager mentions that test coverage has been a recurring theme. Nobody programmed that report. The correction chunks accumulated and the office manager's retrieval picked them up.

The human talks to whoever is in front of them, and the system propagates what it learned.

This works because the shared memory pool uses activation-based retrieval, not explicit routing. A chunk's relevance is determined by structural match (state, task type) and semantic similarity (embedding), not by which agent created it. Cross-level learning is an emergent property of shared memory with good retrieval, not an engineered pipeline.

---

## Cold Start

On first use, there is no memory at any level. The proxy has no chunks and escalates everything to the human. The office manager has no chunks and starts every conversation from scratch.

The human's first interactions seed the memory. A few steering directives to the office manager, a few gate corrections at the project level, and the system has enough to start connecting dots. By the end of the first session, the proxy has a rough picture. By the third, it's anticipating concerns.

---

## Earned Autonomy

The proxy can act autonomously, without escalating to the human, when its predictions consistently match what the human would have decided. This replaces EMA-based auto-approval with something more grounded.

The distinction from EMA matters. EMA measured approval rates detached from artifact content. A high EMA meant the proxy auto-approved without reading the artifact, skipping exactly the inspection that makes human review valuable. The new criterion requires that the proxy has actually inspected the artifact via two-pass prediction and that its content-grounded predictions match the human's actual decisions over a recent window. The difference is not "scalar vs. non-scalar." It is "content-blind vs. content-inspecting." The autonomy threshold is still a measure, but it measures prediction accuracy after forced inspection, not approval frequency.

What "consistently match" means in concrete terms (lookback window size, match rate threshold, how to weight recency) is a Phase 1 design question. The concept is that autonomy is earned through demonstrated prediction accuracy on real artifacts, not inferred from a running average of outcomes.

---

## Boundaries

Some cross-level learning is valuable. Some is noise.

The structural filters in ACT-R retrieval provide the first boundary. Chunks have a `state` and `task_type`. A chunk from PLAN_ASSERT in the POC project is unlikely to surface at INTENT_ASSERT in an unrelated project unless the semantic similarity is strong. The structural filter keeps retrieval focused.

The semantic filters provide the second boundary. A correction about "missing rollback strategy" in one project should surface when another project's plan is missing a rollback strategy. A correction about "wrong database driver" should not surface when reviewing a documentation plan. The embeddings provide semantic distance as a boundary. Chunks about database drivers score low similarity against documentation plans. But the retrieval threshold must be calibrated to make this boundary effective, and that calibration is Phase 1 work.

One thing the boundaries don't handle well: cross-level retrieval errors may be invisible because LLM output looks plausible. The proxy retrieves a chunk from a different context, the LLM weaves it into a coherent-sounding response, and nobody notices the reasoning was based on an irrelevant memory. Phase 1 spot-checks should specifically look for plausible-but-wrong cross-level retrievals.

Priority decay is another open boundary question. The human told the office manager to focus on security three weeks ago. Is that still a priority? ACT-R's activation decay handles this by default, since chunks that aren't reinforced lose activation over time. But broad steering directives may need a "pinned" activation floor so they don't decay before the human explicitly revokes them. This is a memory system tuning question, not a participation model question, but the participation model creates the need.

---

## Open Questions

1. **Dynamic presence detection.** How does the approval gate know the human is "present" at a level and should be addressed directly rather than through the proxy? Currently, the human's presence is implicit in whether the TUI is showing that session.

2. **Proxy observation during direct participation.** When the human participates directly, the proxy should observe and learn. But the proxy is a `claude -p` invocation, not a background process watching the conversation. The proxy's learning from direct participation may need to happen retrospectively (process the transcript after the session) rather than in real-time.

3. **Conversation history across levels.** When the human drops from the office manager conversation into a project session and back, is there context continuity? Or are these separate conversations with shared memory as the only bridge? Separate conversations with shared memory is simpler and probably sufficient.

4. **Subteam drop-in mechanics.** The human "dropping in" to a subteam mid-dispatch would require interrupting the subteam's autonomous execution. The dispatch layer doesn't currently support mid-flight interruption by humans. Whether this is needed or whether the human can just review the subteam's output at WORK_ASSERT is an open question.

5. **Explicit model correction.** Can the human directly down-weight or prune proxy patterns that have been over-learned, rather than waiting for activation decay? The `proxy-patterns.md` flat file (already used as tier-1 context in `consult_proxy()`) is a partial answer, since the human can edit it directly. But richer model correction (marking specific memories as stale, telling the proxy "stop over-indexing on X") is unaddressed.

6. **Cross-project memory architecture.** The upward, downward, and lateral learning flows described in this document depend on memory being shared across projects. The current per-project per-team database scoping prevents this. Whether to build a single shared pool, a federation layer, or project-scoped pools with explicit cross-project queries is an architectural decision that blocks the full participation model.
