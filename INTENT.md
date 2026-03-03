<!-- INTENT VERSION: v0.1 | Updated: 2026-03-03T03:05:03Z | Change: approved -->
# INTENT.md

## Objective

current assumption: The human wants a conceptual explanation of how two systems interact: the **intent pipeline** (the dialog-driven process of capturing what a human actually wants, culminating in INTENT.md) and the **learning system** (MEMORY.md, a cross-project log of patterns, strategies, and hard-won insights from prior agent runs).

to be confirmed: Whether the explanation is for onboarding (understanding the system as a user), operational (understanding it to use it better), or architectural (understanding it to extend or improve it).

## What We Know

The intent system is the first stage of a pipeline. Its job is to produce a well-formed INTENT.md through dialog — surfacing assumptions, resolving contradictions, and narrowing the problem before any planning or implementation begins. It is explicitly non-implementing: no code, no design, no solutions.

The learning system (MEMORY.md) is a persistent, cross-project memory. It captures patterns that emerged from real work — how to parallelize phases, how to recover from failures, how to structure agent dispatch, how to sequence verification. It is appended to after each project, not before.

best guess: They work together as a feedback loop. INTENT.md is per-task and forward-looking (what should happen). MEMORY.md is cross-task and backward-looking (what has worked). When a new task begins, MEMORY.md is available as context — informing how the intent is shaped and how the downstream planning team approaches implementation. When a task ends, new learnings feed back into MEMORY.md, shaping future runs.

## Open Questions

- Why does the human want this explanation right now? (Onboarding? Debugging? Architectural curiosity?)
- Is the human a user of this system, a builder of it, or evaluating it from the outside?
- Is there a specific gap between the two systems they've noticed or are confused by?

## Constraints

None identified yet. Explanation scope is unbounded until intent is clearer.

## Revision History

- v0.1 [2026-03-01T00:00:00Z]: Initial hypothesis — user wants conceptual explanation of intent + learning system interaction.
