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

At the office manager level, the human always participates directly. This is their coordination layer — where they steer priorities, ask cross-cutting questions, and decide what gets worked on.

At the project level, the human chooses. They can sit in on a project session and participate directly (reviewing artifacts, answering questions, providing corrections), or they can let the proxy handle it. The proxy stands in when the human isn't present. When the human shows up, they take their own seat. This is how real teams work — you can send a delegate to a meeting, or you can attend yourself.

At the subteam level, the proxy almost always stands in. The human can't attend every subteam meeting. But they can drop in if they want to — nothing in the architecture prevents it.

---

## Direct Participation vs. Proxy

The distinction is simple. When the human is present at a level, they speak for themselves. When they're absent, the proxy speaks for them. There is no hybrid mode where both speak — that would create conflicting signals.

The transition is clean:

**Human arrives.** The proxy steps aside. Gate questions go to the human directly. The proxy observes (its memory records the interaction as a chunk) but does not generate predictions.

**Human leaves.** The proxy resumes. Gate questions go to the proxy, which generates predictions and either acts autonomously or escalates based on its confidence. The proxy now has fresh chunks from the human's direct participation — it saw what the human said, what they cared about, what they corrected. Its next predictions incorporate that.

**Human never shows up.** The proxy handles everything at that level, earning autonomy through accurate prediction as described in [act-r-proxy-memory.md](act-r-proxy-memory.md).

The current implementation only supports the "human never shows up at subteams" and "human always shows up at project level" patterns. Making the transition dynamic (human drops in mid-session, proxy steps aside) requires the approval gate to detect presence and switch modes. This is a detailed design concern.

---

## Learning Flows Across Levels

What the human does at one level reveals information useful at other levels. The ACT-R shared memory pool is the mechanism for this. All levels share a single `.proxy-memory.db` per human.

### Upward: Project Gates Inform the Office Manager

When the human corrects a plan at PLAN_ASSERT ("add a rollback strategy"), the proxy records a `gate_outcome` chunk. The next time the human asks the office manager "how's the POC project going?", the office manager retrieves that chunk and can report: "the planning phase completed — the plan was corrected to include a rollback strategy."

The office manager didn't attend the gate. But it has access to what happened through shared memory. It can synthesize a status report that reflects the human's actual concerns, not just raw state.

### Downward: Office Manager Steering Informs Gates

When the human tells the office manager "focus on security across all projects", the office manager records a `steering` chunk. The next time the proxy reviews a plan at PLAN_ASSERT, it retrieves that chunk and gives extra scrutiny to security aspects.

The proxy didn't hear the human say it. But the steering chunk surfaced through the shared pool because the structural context matched. The human's cross-cutting directive reached the gate decision without explicit forwarding.

### Lateral: Patterns in One Project Inform Another

When the human consistently corrects plans in the POC project for missing error handling, the proxy accumulates `gate_outcome` chunks with that pattern. If the joke-book project later produces a plan with similar gaps, the proxy retrieves those POC chunks (the structural filter matches on state, the semantic filter matches on content) and applies the learned pattern.

This lateral transfer is not guaranteed. It depends on whether the ACT-R retrieval's structural and semantic filters find the cross-project chunks relevant. Task-type filtering may exclude them. Whether lateral transfer helps or hurts is an empirical question for Phase 1 evaluation.

---

## The Office Manager's View of the Human

The office manager learns about the human differently than the proxy does.

The proxy learns gate behavior: what the human approves, what they correct, what they attend to in artifacts. Its chunks are structured around CfA states, outcomes, and prediction deltas. Its model is: "given this state and this artifact, what would the human say?"

The office manager learns coordination behavior: what the human asks about, what they prioritize, when they intervene, what context they volunteer. Its chunks are `inquiry`, `steering`, `action_request`, `context_injection`. Its model is: "what does the human care about right now, and what do they need to know?"

Both models describe the same human. They are complementary views.

When the human tells the office manager "I'm worried about the database migration," the office manager records a `steering` chunk. The proxy retrieves it at the next database-related gate and gives the migration plan closer scrutiny. The office manager learned a priority; the proxy turned it into gate behavior. Neither agent had to be told to coordinate. The shared memory pool handled it.

When the human corrects a plan at PLAN_ASSERT with "this needs better error handling," the proxy records a `gate_outcome` chunk with a correction delta. The office manager retrieves it when the human asks "how are things going?" and reports: "the plan was corrected for error handling — this is a pattern I've seen you flag before." The proxy learned a gate pattern; the office manager used it for status reporting.

---

## What the Human Experiences

From the human's perspective, the system remembers what they care about regardless of which level they said it at.

They tell the office manager they're concerned about security. Later, at a project gate, the proxy asks about the security implications of the plan — not because it was told to, but because the steering chunk surfaced in retrieval. The human corrects a plan for missing tests. Later, the office manager mentions that test coverage has been a recurring concern across projects — not because it was programmed to track this, but because the correction chunks accumulated.

The human doesn't manage two separate systems. They talk to whoever is in front of them, and the system propagates what it learned.

This works because the shared memory pool uses activation-based retrieval, not explicit routing. A chunk's relevance is determined by its structural match (state, task type) and semantic similarity (embedding), not by which agent created it. Cross-level learning is an emergent property of shared memory with good retrieval, not an engineered pipeline.

---

## Cold Start

On first use, there is no memory at any level. The proxy has no chunks and escalates everything to the human. The office manager has no chunks and starts every conversation from scratch.

The human's first interactions seed the memory. A few steering directives to the office manager, a few gate corrections at the project level, and the system has enough to start connecting dots. The cold start is brief because every interaction produces chunks, and chunks at one level immediately influence behavior at other levels through the shared pool.

The cold start experience should feel like onboarding a new team member who is sharp but knows nothing about you yet. By the end of the first session, they have a rough picture. By the third, they're anticipating your concerns.

---

## Boundaries

Some cross-level learning is valuable. Some is noise. The system needs to distinguish.

The structural filters in ACT-R retrieval provide the first boundary. Chunks have a `state` and `task_type`. A chunk from PLAN_ASSERT in the POC project is unlikely to surface at INTENT_ASSERT in an unrelated project unless the semantic similarity is strong. The structural filter keeps retrieval focused.

The semantic filters provide the second boundary. A correction about "missing rollback strategy" in one project should surface when another project's plan is missing a rollback strategy. A correction about "wrong database driver" should not surface when reviewing a documentation plan. The embeddings handle this naturally — semantically similar artifacts retrieve semantically similar chunks.

What the boundaries don't handle well is priority decay. The human told the office manager to focus on security three weeks ago. Is that still a priority? ACT-R's activation decay handles this by default — chunks that aren't reinforced lose activation over time. But broad steering directives may need a "pinned" activation floor so they don't decay before the human explicitly revokes them. This is a memory system tuning question, not a participation model question, but the participation model creates the need.

---

## Open Questions

1. **Dynamic presence detection.** How does the approval gate know the human is "present" at a level and should be addressed directly rather than through the proxy? Currently, the human's presence is implicit in whether the TUI is showing that session.

2. **Proxy observation during direct participation.** When the human participates directly, the proxy should observe and learn. But the proxy is a `claude -p` invocation — it's not running as a background process watching the conversation. The proxy's learning from direct participation may need to happen retrospectively (process the transcript after the session) rather than in real-time.

3. **Conversation history across levels.** When the human drops from the office manager conversation into a project session and back, is there context continuity? Or are these separate conversations with shared memory as the only bridge? Separate conversations with shared memory is simpler and probably sufficient.

4. **Subteam drop-in mechanics.** The human "dropping in" to a subteam mid-dispatch would require interrupting the subteam's autonomous execution. The dispatch layer doesn't currently support mid-flight interruption by humans. Whether this is needed or whether the human can just review the subteam's output at WORK_ASSERT is an open question.
