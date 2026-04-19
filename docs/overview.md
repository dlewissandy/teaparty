# Organizational Model

TeaParty organizes work the way organizations do: a management team coordinates across projects, project teams coordinate within projects, and workgroups execute tasks. This page describes that shape — the *what* — and links into the [architecture](systems/index.md) that implements it.

## Why a hierarchy?

A single flat team — one agent planning a project and writing every file — eventually loses coherence. The twentieth revision of the plan buries the original intent. Cross-workgroup coordination crowds out the task at hand. File contents from one workstream dilute the context needed for another. This is *context rot*: not a prompting failure but a structural one. No instruction can prevent a context window from filling up, and once it does, the model's attention drifts toward whatever is most recent, not whatever is most important.

Summarization, truncation, and retrieval each trade one problem for another. The structural fix is to scope each agent's responsibility so its context window contains only what is relevant to its work, and to enforce that scope with a process boundary rather than a prompt instruction. Hierarchical teams are TeaParty's answer.

## Corporate hierarchy

Defined in `~/.teaparty/teaparty.yaml` and each project's `.teaparty/project.yaml`:

```
Management Team
  ├── Office Manager (team lead)
  ├── Human (decider)
  ├── Configuration Team (workgroup)
  │     ├── Configuration Lead
  │     └── Agent Specialist, Skills Specialist, …
  ├── Project Team A
  │     ├── Project Lead (team lead)
  │     ├── Workgroup: Engineering
  │     │     ├── agents: implementer, reviewer, …
  │     │     └── jobs: "fix login bug", "add search", …
  │     └── Workgroup: Design
  │           └── agents: designer, researcher, …
  └── Project Team B
        └── …
```

### Management team

The top-level structure. Contains the OM, the human, the configuration team, and references to all project teams.

- **Office Manager (OM)** — coordinates across projects, dispatches work, synthesizes status, carries the human's intent through the hierarchy.
- **Human** — the decider. Interacts via chat with the OM, project leads, and the proxy. The D-A-I role model (below) governs participation at every level.
- **Configuration Team** — a workgroup that creates and modifies agents, skills, hooks, and workgroups. Exposed to the OM through MCP tools.

### Project team

Each project has its own repository (or subdirectory), its own `.teaparty/` configuration, and a project lead. Projects are registered in `teaparty.yaml` with a `path:` entry.

- **Project Lead** — accepts jobs, decomposes them into tasks, dispatches tasks to workgroup agents, merges results. Creates jobs in its own project's `.teaparty/jobs/` directory.
- **Workgroups** — either project-scoped (in `{project}/.teaparty/workgroups/`) or shared across projects via `ref:` to org-level workgroups in `~/.teaparty/workgroups/`.

### Workgroup

A leaf team of agents that executes work. A workgroup has a specific focus, a roster of specialist agents, and a skills catalog.

- **Workgroup Lead** — coordinates workgroup agents within jobs.
- **Workgroup Agents** — specialists with defined roles, tools, model selection, and skills. They do the actual work.
- **Terminal** — workgroups do not contain subteams. They are the execution boundary.

See [reference/built-in-teams/](reference/built-in-teams/index.md) for the catalog of built-in workgroups (coding, research, writing, editorial, art, quality-control, analytics, and more).

## Work hierarchy

Work flows down through three levels. Each level gets its own [conversation on the message bus](systems/messaging/index.md) and its own [workspace](systems/workspace/index.md).

```
Office Manager                       ← cross-project coordination
  │
  └── Project Lead                   ← cross-workgroup coordination
        │
        └── Job (single project)     ← a unit of work, typically a GitHub issue
              │
              ├── Task (single agent) ← dispatched to a workgroup agent
              └── Task
```

### Job

A top-level unit of work within a project, typically tied to a GitHub issue.

- **Created by** the project lead, in response to OM dispatch or human request.
- **Workspace**: each job gets its own git worktree at `{project}/.teaparty/jobs/job-{id}--{slug}/worktree/`.
- **Lifecycle**: `active → complete | failed`.

### Task

A sub-unit of work within a job, dispatched by the project lead to a specific workgroup agent. Leads routinely dispatch multiple tasks in parallel.

- **Created by** the project lead, via `Send` to the target agent.
- **Workspace**: each task gets its own worktree branched from the job's worktree. Parallel tasks on a shared checkout would corrupt each other; task worktrees are unconditional.
- **Merge**: completed task branches are merged back into the job branch by the project lead. The job branch is merged to the integration branch on job completion.

### Cross-project coordination

Cross-project communication is always mediated by the office manager. Project-scoped agents have no direct bus routes to other projects. The OM holds cross-project context and translates between them.

## Context compression at boundaries

When an agent `Send`s a message to another agent, the sender composes what the recipient will see. This is where context compression happens: the sender decides what information the recipient needs, stripping away internal deliberation, coordination history, and irrelevant detail.

- **Downward**, a lead agent translates high-level coordination into a scoped task description. The recipient sees the task, not the planning discussion that produced it.
- **Upward**, the result is the recipient's turn-end output. There is no agent-facing `Reply` tool. The reply contains the outcome, not the recipient's reasoning.

Each hop compresses. The OM sees project-level status summaries, not job-level agent discussions. The project lead sees workgroup results, not internal file churn. The workgroup agent sees its task, not cross-workgroup coordination.

| Level | Context contains | Context does NOT contain |
|---|---|---|
| Office Manager | Cross-project coordination, human preferences, steering | Internal project work, workgroup details |
| Project Lead | Project scope, workgroup dispatch, task results | Management coordination, other projects |
| Workgroup agent | Task description, workgroup files | Project-level coordination, other workgroups' work |

## Scoping creates a blindness, and Learning fixes it

Context isolation solves rot but creates its own problem: a scoped agent cannot see the organizational knowledge — values, conventions, norms — that should inform its work. This is the gap the [Learning & Memory system](systems/learning/index.md) exists to bridge. Institutional learnings are injected into each agent's context at the appropriate scope; task learnings from prior work are fuzzy-retrieved. Neither mechanism works without the other: scoping without retrieval creates drift, retrieval without scoping creates rot.

## How work flows

### Conversation kinds

Agent messages are routed by conversation kind on the [message bus](systems/messaging/index.md):

| Kind | Participants | Initiated by |
|---|---|---|
| Office manager | Human + OM | Human opens from Sessions card |
| Project session | Human + project lead + proxy | Job or gate event |
| Agent dispatch | Lead + worker agent | Lead via `Send` |
| Proxy review | Human + their own proxy | Human opens directly |
| Config lead | OM + configuration specialists | OM routes config request |

Multiple conversations can be active simultaneously. All persist on the bus and can be resumed.

### Agent model

- **Agents are autonomous**, not scripted. They decide what to do based on conversation context, workflow state, and their own judgment. No prescriptive prompts or retry loops.
- **Agent output is never truncated.** Output rules are minimal: no format constraints, length limits, or plain-text-only directives.
- **Workflows are advisory, not mandatory.** Agents follow them by choice, not enforcement.
- **Every agent is an independent process.** Each runs as a standalone `claude -p` invocation with `--resume` for multi-turn conversations. Agents communicate via the message bus using `Send` (the recipient's turn-end output is the reply), not by holding teammates in context.
- **Lead agents coordinate.** The OM across projects, project leads within a project, workgroup leads within a workgroup. Leads decompose work, send requests to named roster members, and synthesize responses.
- **Bus routing enforces boundaries.** Routing policy derives from workgroup membership. Cross-team requests go through the project lead. Cross-project requests go through the OM.

### Execution model

Agents use the write-then-exit-then-resume pattern. A lead that dispatches parallel requests records outstanding threads in its conversation history before exiting. The recipient subprocess's output when its turn completes is, by convention, the reply to the opening Send. The lead is re-invoked when all threads close. State lives on the bus rather than in process memory; durability across restarts follows from that.

The `Send` tool flushes current state to a scratch file before posting, assembling a composite message with the task and current job context. The recipient gets a self-contained brief.

## Humans in the loop

### D-A-I role model

Every team has exactly one **Decider**. The decider has final authority at gates. **Advisors** can interject but their input is advisory. **Informed** members observe but cannot write. See [reference/team-configuration](reference/team-configuration.md) for how D-A-I roles are assigned.

### Two kinds of influence

**Memory-based steering** records durable preferences that influence all future work ("Focus on security"). These propagate through the shared memory pool and surface in any agent's retrieval when context matches.

**Direct intervention** acts immediately on a specific session. The OM calls MCP tools: `WithdrawSession`, `PauseDispatch`, `ResumeDispatch`, `ReprioritizeDispatch`.

### Human Proxy

The [Human Proxy](systems/human-proxy/index.md) is a learned agent that stands in for the human at gates and escalations, earning autonomy through demonstrated alignment. The proxy operates at each level of the hierarchy, differentiated by D-A-I role: the decider at the project level may be a different human than the decider at the workgroup level.

## When the hierarchy flattens

Not every task needs the full structure. Simple work dispatched by the OM may go directly to a single agent. Multiple sequential tasks from one workgroup need only the project lead dispatching them one at a time. The overhead of hierarchical dispatch is justified by the context isolation it provides; for work that fits in a single context window, skip it.

## Further reading

- [Architecture](systems/index.md) — the six systems that implement this model.
- [Case Study](case-study/index.md) — end-to-end demonstration: a four-sentence prompt to a 55,000-word manuscript.
- [Folder Structure](reference/folder-structure.md) — directory layout on disk.
- [Team Configuration](reference/team-configuration.md) — the `.teaparty/` config tree, catalog merging, D-A-I roles.
