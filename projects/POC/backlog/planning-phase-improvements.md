# Planning Phase Improvements

## Problem

Plans are supposed to be the bridge between "what we want" (intent) and "the
work" (execution). After 20+ sessions, they're not doing that job. The plans
look thorough — Context sections, Critical Files tables, Verification
checklists — but they consistently produce execution failures that trace back
to planning gaps.

The scrollable prompt plan specified exact CSS (`max-height: calc(4 * 1.6 *
0.875rem)`) and exact line numbers, but execution went to the wrong codebase
entirely. A workflow that said "find where the truncation is applied and
replace it with a scrollable region" would have survived. The state hygiene
plan implemented `CLAUDE_CODE_TASK_LIST_ID` without validating it works, even
though the intent explicitly flagged it as a blocker. The pythonify plan
proposed a 7-wave parallel dependency graph without discovering that half the
Python already existed (and was broken), and without knowing that dispatch.sh
chokes on complex arguments and swaps plans when run in parallel.

The plans are implementation specs. They should be workflows.

## What a plan actually is

A plan is a bespoke skill designed for a specific intent. It tells the
execution team what to do, in what order, with what resources, at what
checkpoints — not how to implement each step. The execution team figures out
the how. The plan gives them a roadmap that survives contact with reality
because it describes activities and gates, not code.

A good plan-as-workflow:

- **Describes activities, not implementations.** "Find the truncation mechanism
  and replace it with a scrollable region" rather than "add `max-height:
  calc(...)` to line 4439." The execution team adapts the how when reality
  diverges; the what stays valid.

- **Front-loads prerequisites.** Open questions from the intent and unvalidated
  assumptions become the first steps, not footnotes. "Validate that
  `CLAUDE_CODE_TASK_LIST_ID` persists task lists. If it doesn't, stop — the
  approach changes."

- **Has binding checkpoints.** "Verify X before proceeding to Y" is a gate
  that blocks progress, not a suggestion in an appendix.

- **Specifies available resources and their constraints.** Which teams, tools,
  scripts, dispatch mechanisms the execution team can use — and what doesn't
  work. "Dispatch to the coding team; keep task descriptions to single-line
  plain text" rather than silently designing a workflow that dispatch.sh can't
  execute.

- **Maps every intent success criterion to a workflow step.** If a criterion
  isn't reachable through the workflow, either add a step or explicitly defer
  it with reasoning.

- **Resolves every intent open question.** For each one: resolved (decision
  and reasoning), validated (what was checked), deferred (why, and what
  execution must do), or escalated (sent to human). No open question passes
  through planning unaddressed.

The quality test: could you hand this workflow to a competent team with access
to the codebase and the intent document, and would they know what to do at
every step, in what order, with clear criteria for when to proceed and when to
stop?

## The team lead's role

The team lead is always a coordinator. In planning, their job is to ensure the
team produces a workflow that, when executed, would satisfy the intent. They
are the final quality hurdle — they review the proposed workflow against the
intent's success criteria, decision boundaries, and open questions before
asserting it's ready.

This is true across all three phases. The leads don't produce deliverables
themselves. They manage the workflow and assert when the team's deliverable
meets the bar:

- **Intent lead:** ensure the intent document meets its bar — someone who never
  spoke to the requester could produce work the requester would recognize as
  their own idea, well executed.
- **Plan lead:** ensure the workflow meets its bar — executing it would produce
  work satisfying the intent.
- **Execution lead:** ensure the work meets its bar — it satisfies the intent.

Right now the project-lead's prompt is ~1200 words, and roughly 90% is
messaging protocols, checkpoint JSON schemas, and dispatch mechanics. There's
almost nothing about how to evaluate whether a workflow is good.

## The three distinct artifacts

Intent, plan, and prompt are different things serving different purposes:

- **Intent** (INTENT.md) — what to achieve and why. The specification.
- **Plan** (plan.md) — a bespoke workflow for this specific intent. The skill.
- **Prompt** (agent config) — how the execution team operates. Behavioral
  instructions about execution discipline: follow the workflow, adapt when
  reality diverges, verify against success criteria, escalate when stuck.

The execution team receives the intent and plan as inputs. The prompt tells
them how to act. The plan is not the prompt — the plan is a reference document
the execution team follows while applying the operating discipline described
in their prompt.

## What needs to change

### A. The planning team needs a prescribed workflow

The intent and planning phases have prescribed workflows (per the CfA model),
but the project-lead's prompt describes messaging protocols, not a planning
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

The project-lead prompt should describe this workflow, not message routing.
The messaging protocols are infrastructure — they belong in the agent config
or a reference document, not in the planning guidance.

### B. Plan-as-skill format

Two options for standardizing the plan format:

**Option 1: Structured workflow document.** Define a plan.md format that
mirrors a skill structure — steps with objectives, gates, resource
assignments, and contingencies. Something like:

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

Option 2 is closer to how plans already work and lower friction. Option 1
makes the structure machine-checkable.

### C. Problem space exploration capabilities

The planning team needs the same historical session retrieval capability
proposed for the intent team — but used differently. The intent team searches
history to understand what the human wants. The planning team searches history
and the codebase to understand what's feasible, what exists, and what's been
tried.

Specifically, the planning team needs to:

- Search prior sessions for related work, corrective learnings, and dispatch
  friction patterns (the pythonify session would have found existing Python
  orchestrator code)
- Explore the codebase to validate intent assumptions (the scrollable prompt
  plan would have discovered the truncation mechanism before committing to CSS)
- Review dispatch/tool constraints from memory (the parallel dispatch failure
  was a known friction point logged months earlier)

This is the exploration work that was explicitly excluded from intent. It
belongs in planning because the planner needs ground truth to design a viable
workflow.

### D. Contingency logic in plans

Current plans have no contingency handling. When execution hits a surprise,
there's no guidance — the execution team either silently adapts (often wrong)
or stalls.

Plans should include contingency triggers for foreseeable divergences:

- "If step 3 reveals the truncation is JS-based, not CSS-based, adjust step 4
  to remove the JS truncation first."
- "If dispatch.sh fails with this task complexity, write the task to a file in
  the worktree and pass the path instead."
- "If the existing Python implementation is incomplete or broken, escalate —
  this changes from greenfield to repair work."

This is how a good skill handles branching — it anticipates the common failure
modes and routes around them rather than assuming the happy path.

### E. Session scoping

Multiple sessions show work that couldn't finish — the pythonify 7-wave plan,
the state hygiene sequential principles where Principle 3 was dispatched
before Principle 4 was complete. Alignment analyses repeatedly ask: "Clarify
whether partial progress constitutes 'done.'"

The plan should scope what's achievable in one session and define natural
pause points. Two options:

**Option 1: Hard session boundaries.** The plan specifies "this session will
complete steps 1-4. Steps 5-7 are a separate session." Intent success criteria
that fall beyond the boundary are explicitly deferred.

**Option 2: Checkpoint-based.** The plan specifies ordered steps with
checkpoints. After each checkpoint, the execution lead evaluates whether to
continue or pause. The plan includes criteria for the pause decision (time
elapsed, complexity discovered, scope growth).

Option 2 is more adaptive. The pythonify session's escalation at the 69-gap
discovery was actually a good checkpoint — the problem was that no checkpoint
was planned, so it happened ad hoc.

### F. Alignment analysis across phases

Currently alignment compares intent vs. execution output. Many failures trace
to planning — the plan didn't resolve an open question, didn't validate
assumptions, designed an infeasible dispatch structure. Alignment should also
compare:

- **Plan vs. intent:** Did the plan address every success criterion, open
  question, and decision boundary?
- **Plan vs. execution:** Was the workflow followed? Where did execution
  diverge, and was the divergence justified?

This gives signal on whether the planning team is doing its job, not just
whether the execution team produced the right output.

### G. Procedural learning: plans become skills

If plans are bespoke skills, then plans that work become candidates for
reusable skills. This is the natural lifecycle:

1. The planning team writes a bespoke workflow for a specific intent.
2. The execution team follows it and produces work.
3. Alignment analysis confirms the workflow led to satisfactory results.
4. Over time, similar plans accumulate — multiple coding tasks produce
   similar workflows, multiple writing tasks produce similar workflows,
   multiple bug-fix tasks produce similar workflows.
5. Procedural learning (done periodically, not per-session) identifies
   recurring patterns across successful plans and generalizes them into
   reusable Claude skills — parameterized versions of what the planning
   team keeps writing by hand.

Once reusable skills exist, the planning phase changes. Before designing a
workflow from scratch, the planner checks whether an existing skill covers
this class of task. If it does, the plan becomes: "Use the [bug-fix-workflow]
skill with these parameters: [scope], [target files], [verification criteria]."
If no skill fits, the planner writes a bespoke workflow as before — and that
workflow becomes a data point for future skill extraction.

This only works if plans are already structured as skills. If plans are prose
implementation specs (what we have now), there's no clean path from "plan that
worked" to "reusable skill." If plans are workflows with activities, gates,
resource assignments, and contingencies — the same structure a skill uses —
then generalization is just parameterization. Replace the specific file paths
and task details with parameters, and the bespoke plan becomes a reusable
template.

The practical consequence: the plan-as-skill format isn't just a conceptual
improvement. It's a prerequisite for procedural learning to produce reusable
skills. Plans that look like skills today become skills tomorrow.

### H. Fix plan approval (bug)

`phase-config.json` sets `artifact: null` for the planning phase. This means
`AgentRunner._interpret_output()` always returns `auto-approve`, bypassing
`PLAN_ASSERT` entirely. Plans never go through human review in the Python
orchestrator. This is a bug that must be fixed regardless of any other changes.

## Relationship to Other Backlog Items

**intent-team-improvements.md** — The structured open question tracking
proposed there feeds directly into planning's obligation to resolve each one.
Historical session retrieval benefits both teams but for different purposes.

**intent-team-composition.md** — The retrieval specialist proposed there could
serve the planning team's problem space exploration needs. Cross-phase
specialist persistence is relevant here.

**mcp-tools-for-cfa-infrastructure.md** — Dispatch constraints and tool
availability are things the planning team needs to understand. If dispatch
becomes an MCP tool, its constraints should be discoverable by the planner.
