# Planning Phase Improvements

## Problem

After 20+ sessions, the plans look thorough but consistently produce execution
failures that trace back to planning gaps. The plans are implementation specs
when they should be workflows.

The scrollable prompt plan specified exact CSS (`max-height: calc(4 * 1.6 *
0.875rem)`) and exact line numbers. Execution went to the wrong codebase
entirely. A workflow that said "find where the truncation is applied and
replace it with a scrollable region" would have survived — because it
describes the activity, not the implementation.

The state hygiene plan implemented `CLAUDE_CODE_TASK_LIST_ID` without
validating it works, even though the intent explicitly flagged it as a blocker.
The plan treated a prerequisite like an implementation detail.

The pythonify plan proposed a 7-wave parallel dependency graph without
discovering that half the Python already existed (and was broken), and without
knowing that dispatch.sh chokes on complex arguments and swaps plans when run
in parallel. The plan designed a workflow for infrastructure it never checked.

The project-lead's prompt is ~1200 words. Roughly 90% is messaging protocols,
checkpoint JSON schemas, and dispatch mechanics. Almost nothing about how to
evaluate whether a workflow is good, how to decompose work, or how to
validate assumptions before committing to an approach.

## What a plan should be

A plan is a bespoke skill designed for a specific intent. It tells the
execution team what to do, in what order, with what resources, at what
checkpoints — not how to implement each step. The execution team figures out
the how. The plan survives contact with reality because it describes
activities and gates, not code.

The quality test: a competent team following this workflow would produce work
satisfying the intent without needing to re-read it.

The team lead's job in planning is the same as in every other phase:
coordination and quality. They ensure the team produces a workflow that, when
executed, would satisfy the intent. They are the final quality hurdle. They
don't produce deliverables — they manage the workflow and assert when the
deliverable meets the bar.

## What needs to change

### A. The planning team needs a prescribed workflow

The project-lead's prompt describes messaging protocols, not a planning
workflow. The planning team should follow explicit steps:

1. Read the intent — understand the what and why
2. Explore the problem space — codebase state, existing code, prior sessions,
   what's been tried before
3. Inventory available resources — teams, tools, dispatch mechanisms,
   permission modes, known limitations and friction points
4. Resolve intent open questions — using what was discovered in steps 2-3
5. Design the workflow — activities, dependencies, checkpoints, resource
   assignments, contingency triggers
6. Lead reviews against intent — does this workflow address every success
   criterion? Every open question? Every decision boundary?

The messaging protocols are infrastructure — they belong in the agent config
or a reference document, not in the planning guidance.

### B. Plans should be structured as skills

Two options:

**Option 1: Structured workflow document.** Define a plan.md format that
mirrors a skill structure — steps with objectives, gates, resource
assignments, and contingencies:

```
## Prerequisites
1. Validate [assumption]. If invalid, escalate — approach changes.
2. Resolve [open question from intent]. Decision: [...]

## Workflow
### Step 1: [Activity objective]
Resources: [team/tool]
Gate: [what must be true before proceeding]
Contingency: if [X], then [Y]

### Step 2: ...
```

**Option 2: Narrative workflow.** Keep plans as prose but enforce that every
plan includes: (a) resolved open questions, (b) prerequisite validations,
(c) sequenced activities with gates, (d) resource inventory with constraints,
(e) explicit mapping of intent success criteria to workflow steps. The format
is flexible; the content requirements are not.

Option 2 is lower friction. Option 1 makes the structure machine-checkable
and — critically — directly usable for procedural learning (see section G).

### C. Problem space exploration

The planning team needs to explore the codebase and session history — this is
the exploration work that was deliberately excluded from intent. The planner
needs ground truth to design a viable workflow.

Specifically:

- Search prior sessions for related work, corrective learnings, and dispatch
  friction patterns (the pythonify plan would have found existing Python
  orchestrator code; the parallel dispatch failure was a known friction point
  logged months earlier)
- Explore the codebase to validate intent assumptions (the scrollable prompt
  plan would have discovered the truncation mechanism before committing to
  an approach)
- Inventory what resources are actually available and what their constraints
  are (dispatch.sh argument limits, sub-agent permission boundaries, tool
  availability per permission mode)

### D. Intent open questions must be resolved

Every numbered open question from INTENT.md must be explicitly addressed in
the plan. For each one: resolved (decision and reasoning), validated (what was
checked and found), deferred (why, and what execution must do if it hits this),
or escalated (sent to human). No open question passes through planning
unaddressed.

Multiple sessions show open questions that became dead letters — silently
decided during execution or just worked around. The state hygiene
`CLAUDE_CODE_TASK_LIST_ID` question, the scrollable prompt truncation-mechanism
question, the orphan recovery resume-entrypoint question. Planning is where
these get answered — that's the whole point.

### E. Contingency logic

Current plans assume the happy path. When execution hits a surprise, there's
no guidance — the execution team either silently adapts (often wrong) or
stalls.

Plans should include contingency triggers for foreseeable divergences:

- "If step 3 reveals the truncation is JS-based not CSS-based, adjust step 4
  to remove the JS truncation first."
- "If dispatch.sh fails with this task complexity, write the task to a file
  in the worktree and pass the path instead."
- "If the existing Python implementation is incomplete or broken, escalate —
  this changes from greenfield to repair work."

This is how a good skill handles branching — it anticipates common failure
modes and routes around them.

### F. Session scoping

Multiple sessions show work that couldn't finish — the pythonify 7-wave plan,
the state hygiene sequential principles where later steps were dispatched
before earlier ones completed. Alignment analyses repeatedly ask: "Clarify
whether partial progress constitutes done."

Two options:

**Option 1: Hard session boundaries.** The plan specifies "this session
completes steps 1-4. Steps 5-7 are a separate session." Success criteria
beyond the boundary are explicitly deferred.

**Option 2: Checkpoint-based.** The plan specifies ordered steps with
checkpoints. After each checkpoint, the execution lead evaluates whether to
continue or pause. The plan includes criteria for the pause decision (time
elapsed, complexity discovered, scope growth).

Option 2 is more adaptive. The pythonify session's escalation at the 69-gap
discovery was a good checkpoint — the problem was that no checkpoint was
planned, so it happened ad hoc.

### G. Procedural learning: plans become skills

If plans are bespoke skills, then plans that work become candidates for
reusable skills. The lifecycle:

1. The planning team writes a bespoke workflow for a specific intent.
2. The execution team follows it and produces work.
3. Alignment analysis confirms the workflow led to satisfactory results.
4. Over time, similar plans accumulate — multiple coding tasks produce
   similar workflows, multiple bug-fix tasks produce similar workflows.
5. Procedural learning (done periodically, not per-session) identifies
   recurring patterns across successful plans and generalizes them into
   reusable Claude skills — parameterized versions of what the planning
   team keeps writing by hand.

Once reusable skills exist, the planning phase changes. Before designing a
workflow from scratch, the planner checks whether an existing skill covers
this class of task. If one does, the plan becomes: "Use the [bug-fix-workflow]
skill with these parameters." If none fits, the planner writes a bespoke
workflow — and that workflow becomes a data point for future skill extraction.

This only works if plans are already structured as skills. If plans are prose
implementation specs (what we have now), there's no clean path from "plan that
worked" to "reusable skill." If plans are workflows with activities, gates,
resource assignments, and contingencies — the same structure a skill uses —
then generalization is just parameterization. The bespoke plan becomes a
reusable template by replacing the specifics with parameters.

Plans that look like skills today become skills tomorrow.

### H. Alignment analysis across phases

Currently alignment compares intent vs. execution. Many failures trace to
planning — the plan didn't resolve an open question, didn't validate
assumptions, designed an infeasible dispatch structure. Alignment should also
compare:

- **Plan vs. intent:** Did the plan address every success criterion, open
  question, and decision boundary?
- **Plan vs. execution:** Was the workflow followed? Where did execution
  diverge, and was the divergence justified?

This gives signal on whether the planning team is doing its job, not just
whether the execution team produced the right output.

### I. Fix plan approval (bug)

`phase-config.json` sets `artifact: null` for the planning phase. This means
`AgentRunner._interpret_output()` always returns `auto-approve`, bypassing
`PLAN_ASSERT` entirely. Plans never go through human review in the Python
orchestrator. This needs to be fixed regardless of any other changes.

## What this is not

This is not a redesign of the CfA state machine or the dispatch architecture.
The planning team's job stays the same: translate intent into actionable work.
These improvements are about giving it a real workflow to follow, clearer
standards for what "actionable" means, and a plan format that pays dividends
through procedural learning.

## Relationship to other backlog items

**intent-team-improvements.md** — The structured open question tracking
proposed there feeds directly into planning's obligation to resolve each one.
Historical session retrieval benefits both teams but for different purposes.

**intent-team-composition.md** — The retrieval specialist proposed there could
serve the planning team's problem space exploration needs. Cross-phase
specialist persistence is relevant.

**mcp-tools-for-cfa-infrastructure.md** — Dispatch constraints and tool
availability are things the planning team needs to understand. If dispatch
becomes an MCP tool, its constraints should be discoverable by the planner.
