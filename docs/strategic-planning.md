# Assistive Strategic Planning Experience

Strategic planning is the bridge between intent and execution in TeaParty's four-pillar framework: it transforms an approved specification of purpose into a structured plan that organizes work across teams, sequences decisions, and maps the terrain execution will traverse. Intent engineering establishes what to want. Strategic planning establishes how to get there — the shape of the work, the decisions that must be made before execution begins, and the constraints that determine what can proceed in parallel and what must wait.

## Why This Exists

The plan-execute model used by most agent systems treats planning as either a formality or a monolith. In the formality version, the agent receives a task and immediately begins executing, with "planning" reduced to a mental note about what to do first. In the monolith version, the agent produces a detailed step-by-step breakdown that intermixes strategic decisions with tactical ones, making it impossible to revise the approach without also revising every implementation detail.

Both fail at scale. The formality version fails because the first architectural decision an agent makes constrains every subsequent decision, and agents that skip planning make those decisions implicitly — choosing a direction without recognizing they have chosen. The monolith version fails because correcting a strategic error requires re-planning tactical details that were never wrong.

Strategic planning and tactical planning use different information, produce different artifacts, operate at different time horizons, and require different decision authority. Collapsing them into a single step produces work that is internally coherent and externally wrong — every task gets done, the outcome misses the point. In the POC, this failure mode has manifested as dispatches that executed cleanly against decompositions that did not match the intent, requiring backtrack to replanning after substantial completed work.

Three principles govern the quality of all artifacts this system produces:

**Every sentence must earn its place.** If removing a sentence would not change the reader's ability to understand the plan, remove it.

**Would a reasonable person find this sufficient?** Read the plan as a team lead who was not in the room during intent gathering. If they cannot proceed without guessing at priorities, decision authority, or sequencing, the plan is incomplete.

**Bring solutions, not questions.** Never present a problem without researched alternatives and a recommendation.

**Would the human recognize the plan as a faithful operationalization of their intent?** The plan is not a reinterpretation of the intent. It is the intent made executable.

## What The System Produces

Through a synthesis loop between the planning team and the human (or their proxy), the system produces a strategic plan that captures:

**Work decomposition** — how the intent breaks into semi-independent work streams, and the rationale for that decomposition. The decomposition is driven by the problem's structure, not by the team's structure. The plan names relationships between streams explicitly: true parallel work, fan-out/fan-in patterns, and sequential gates.

**Decision authority mapping** — which decisions can be made autonomously by subteams, which require notification, and which require escalation. This is a specific mapping of specific decisions to specific tiers, derived from the intent's decision boundaries and each decision's reversibility and organizational impact. Unmapped decisions force agents to choose between guessing and blocking — the POC's most common source of execution-time escalation.

**Proof points** — the smallest possible validations that confirm the approach before full execution commitment. If a proof point fails, redirection is cheap. If it passes, subsequent work can proceed with more autonomy.

**Parallelization strategy** — which work streams can run concurrently and which must be sequenced. Fan-out/fan-in identifies independent streams that converge at a merge point. Sequential gates identify dependencies on verified output, not merely completed output. The plan encodes these constraints rather than leaving them to be rediscovered at runtime.

**Contingency triggers** — foreseeable divergences from the happy path and the planned response to each. For each foreseeable divergence, the plan specifies: what triggers it, who detects it, and what happens — retry, escalate, or backtrack to replanning.

**Session boundaries** — explicit criteria for when execution should pause. Complex work rarely completes in a single session. The plan identifies natural checkpoints where completed work can be verified and the remaining plan reassessed with fresh context.

**Tactical invariants** — the constraints that bound how subteams operate, established at the strategic level so that independently operating subteams produce composable and aligned work:

- *Quality criteria* — what standard the work must meet, operationalized per work stream. The strategic plan does not say "be comprehensive" — it defines what comprehensive means for this context.
- *Boundary conditions* — what is in scope, what is not, what constitutes a blocking problem versus an acceptable tradeoff.
- *Process invariants* — non-negotiable behaviors throughout execution. A coding team's invariants might be: all changes must pass existing tests before new tests are written, no dependency additions without stated rationale.
- *Completion criteria* — how each team knows it is done. Quality defines the standard; completion defines the scope.

The strategic plan follows the shape of the problem, not a fixed template. Some projects need extensive decision authority mapping and minimal parallelization strategy. Others are the reverse.

## How The Planning Conversation Works

### Cold Start (No Prior Context)

When the system has no history with this type of work, the planning phase begins with exploration, not artifact production. The project lead explores the solution space — reading the codebase, identifying structural dependencies, surfacing assumptions the intent did not address. Research liaisons dispatch to investigate open questions from the intent phase, technical feasibility, and prior art.

Before producing `PLAN.md`, the [human proxy](human-proxies.md#understand-first-act-second) runs an intake dialog that shares what the team found and checks its understanding with the human: "Here's what I'm seeing in the codebase. Here's what's harder than it looks. Here are two viable approaches — which direction feels right?" On cold start, the proxy has no predictions about the human's planning preferences, so every directional question goes to the human. The human's answers inform the decomposition and become the first data points for the proxy's model of how this human thinks about planning.

The project lead proposes rather than asks — it presents a decomposition, explains the rationale, identifies the assumptions it rests on. But the proposal is informed by the intake conversation, not a one-shot guess. The intake dialog has already resolved the ambiguities that would otherwise surface as backtrack-triggering surprises during execution.

### Warm Start (Accumulated Skills)

Over time, the [learning system](learning-system.md) observes which plans led to successful execution and which required mid-course correction. Plans that worked are generalized into Claude Code skills — parameterized workflows that capture the shape of successful work for a category of tasks. These skills accumulate at the project or organization level.

A skill is a materialized generalization of plans that worked. When multiple cold-start sessions for "write a research paper" converge on the same decomposition — survey, argue, draft, edit, typeset — the system extracts that pattern into a reusable skill with parameters for the parts that vary (topic, audience, depth) and invariants for the parts that do not (sequencing, review gates, fan-out/fan-in structure). The planning team can adopt, adapt, or override a skill with stated rationale.

In warm-start mode, both the intake dialog and the planning conversation compress. The proxy predicts the human's planning preferences from prior sessions — "Based on our past work, I'm assuming you'd want parallel dispatch here with a sync gate before integration" — and only asks about genuinely novel aspects. The planning conversation shifts from "how should we decompose this work?" to "here is how we have successfully decomposed similar work before — does this apply, and what needs to change?" Corrections to proxy predictions or to skill-seeded plans refine the proxy's model and the skill's content, converging over successive applications toward the organization's actual best practice.

### The First-Move Problem

The first-move problem is this: the earliest decisions in a project — how to decompose the work, what architecture to use, what abstractions to commit to — are made when the team knows the least, yet they constrain every decision that follows. Later decisions are made with more information but less freedom. The result is that the decisions with the highest downstream impact are made at the moment of lowest confidence.

This asymmetry is why strategic planning cannot be skipped or rushed. The cost of a first-move error is not the error itself — it is every subsequent decision that assumed the error was correct, compounding through execution until correcting the original mistake requires unwinding work that was internally sound but built on a flawed foundation.

The planning conversation identifies high-leverage decision points and resolves them before execution begins. The reversibility test determines their treatment: if a decision can be corrected cheaply after execution begins, it can be made autonomously. If correcting it requires redoing substantial downstream work, it demands strategic treatment — research, deliberation, and human confirmation.

### Relationship to Tactical Planning

Strategic planning produces the shape of work and the invariants that constrain it. Tactical planning — which happens during execution, when subteams receive specific assignments — determines how to accomplish the assigned work within the framework the strategic plan established. The same CfA state machine governs both levels; the difference is in what the plan contains, not how it is negotiated.

A strategic plan for writing a research paper might be: survey the literature, construct the argument, draft sections in parallel, edit for coherence, typeset. The strategic plan also establishes the invariants — the literature survey must cover three research traditions, include work from the last five years, and provide at least two sources per claimed finding. The research team develops a tactical plan for how to achieve those criteria: which databases to search, what keywords to use, how to evaluate sources. Those decisions belong at the tactical level because they depend on the specific task — but they operate within constraints the strategic plan has already defined.

The uber lead produces strategic plans. It never produces deliverables and never makes tactical decisions. Subteam leads produce tactical plans within the scope of their assignments, exercising the decision authority the strategic plan has granted them, operating within the invariants it has defined.

## Plan Revision Discipline

Revise the strategic plan when new information invalidates an assumption — a constraint discovered, a proof point failed, a scope change from the human. Do not revise when execution is merely harder than expected or when tactical details need filling in. The test: does this change what the plan was predicting, or how the plan is being carried out? The former requires revision and re-confirmation with the human. The latter is expected tactical improvisation within the decision authority the plan already granted.

When execution reveals the plan itself was wrong, the CfA state machine backtracks to the planning phase. When planning reveals the intent was wrong, it backtracks further to intent. These are expensive but necessary — the alternative is continuing to execute against a falsified plan.

## The Human's Role in Planning

The human's primary contribution to planning is institutional knowledge — the operating priorities, conventions, and practices of their organization that no amount of research or reasoning can derive from first principles. The system can decompose work, identify dependencies, and map decision authority. It cannot know that this organization always ships documentation before code, that the VP of Engineering reviews anything touching the payment pipeline, or that the last time someone parallelized across three teams without a sync point the project slipped by a month.

Every edit a human makes to a plan is a learning opportunity. When a human reorders work streams, they are teaching the system about organizational dependencies not visible in the problem structure. When they add a review gate, they are encoding a risk tolerance the system had not modeled. When they change decision authority from escalate to autonomous, they are extending trust in a specific domain. These corrections are direct evidence of the gap between the system's model of the organization and how it actually operates — among the highest-value signals the [learning system](learning-system.md) captures.

The [human proxy](human-proxies.md) stands at the approval gate between planning and execution. In cold-start mode, it escalates all plans — maximizing the learning opportunity. As institutional knowledge accumulates, the proxy develops confidence to approve plans for familiar task categories, reserving human attention for novel work where the system's model is most likely to be wrong.

## Success Criteria

The governing metric is plan fidelity: the degree to which execution proceeds without requiring strategic plan revision. Observable indicators:

- Reduction in cross-phase backtracks from execution to planning over time
- Reduction in unmapped decision escalations during execution
- Increase in subteam autonomy within planned decision authority
- Decrease in time from approved intent to approved plan for familiar task categories
- Increase in plan reuse across similar projects

A plan that produces zero backtracks but low-quality deliverables has optimized for the wrong metric. A plan that requires three revisions but converges on excellent output has a planning problem worth solving, not a planning failure to accept.

## Open Questions

When the request is purely tactical — a single well-scoped task that does not require decomposition, sequencing, or cross-team coordination — the strategic planning layer adds overhead without value. The system must detect when this is the case and flatten: skip strategic planning entirely, dispatch directly to a subteam, and let the subteam's tactical planning handle it. The open question is how to make this detection reliable. Misclassifying a strategic task as tactical produces the first-move errors this document describes. Misclassifying a tactical task as strategic wastes time planning work that a single team could just do. The cost of getting it wrong is asymmetric: under-planning is more expensive than over-planning, but over-planning erodes trust in the system's judgment.
