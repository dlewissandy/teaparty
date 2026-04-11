# TeaParty Architecture

TeaParty is a platform where teams of humans and AI agents co-author files and collaborate in chat. A management hierarchy organizes all work: the management team coordinates across projects, project teams coordinate within a project, and workgroups execute the work.

---

## Corporate Hierarchy

The corporate hierarchy determines who can talk to whom, who manages whom, and where work gets assigned.

```
Management Team
  +-- Office Manager (team lead)
  +-- Human (decider)
  +-- Configuration Team (workgroup)
  |     +-- Configuration Lead
  |     +-- Agent Specialist, Skills Specialist, ...
  |
  +-- Project Team A
  |     +-- Project Lead (team lead)
  |     +-- Workgroup: Engineering
  |     |     +-- agents: implementer, reviewer, ...
  |     |     +-- jobs: "fix login bug", "add search", ...
  |     +-- Workgroup: Design
  |           +-- agents: designer, researcher, ...
  |
  +-- Project Team B
        +-- ...
```

### Management Team

The top-level organizational structure, defined in `~/.teaparty/teaparty.yaml`. The management team contains the office manager, the human, the configuration team, and references to all project teams.

- **Lead agent**: The Office Manager (OM). Coordinates across projects, dispatches work, synthesizes status, and transmits the human's intent through the hierarchy. See [office-manager](proposals/office-manager/proposal.md).
- **Human**: The decider. Interacts via chat with the OM, project leads, and the proxy. The Decider-Advisor-Informed (D-A-I) role model governs participation at every level. See [team-configuration](proposals/team-configuration/proposal.md).
- **Configuration Team**: A workgroup that creates and modifies agents, skills, hooks, and other Claude Code artifacts. See [configuration-team](proposals/configuration-team/proposal.md).

### Project Team

A project has its own repo (or subdirectory), its own `.teaparty/` configuration, and a project lead who coordinates workgroups within it. Projects are registered in `teaparty.yaml` with a `path:` entry.

- **Lead agent**: The Project Lead. Accepts jobs, decomposes them into tasks, dispatches tasks to workgroup agents, merges results. The project lead creates jobs in its own project's `.teaparty/jobs/` directory.
- **Workgroups**: Can be project-scoped (defined in `{project}/.teaparty/workgroups/`) or shared across projects via `ref:` references to org-level workgroups in `~/.teaparty/workgroups/`.
- **Configuration**: `{project}/.teaparty/project.yaml` defines the project team, its workgroups, skills, and norms. See [team-configuration](proposals/team-configuration/proposal.md).

### Workgroup

A leaf team of agents that executes work. A workgroup has a specific focus, a roster of specialist agents, and a skills catalog.

- **Lead agent**: The workgroup lead. Coordinates workgroup agents within jobs.
- **Agents**: Specialists with defined roles, tools, model selection, and skills. They do the actual work within tasks.
- **Terminal**: Workgroups do not contain subteams. They are the execution boundary.

### Partnerships

> Partnerships are a future platform design for cross-organization collaboration. They are not part of the current single-machine, single-user system.

---

## Work Hierarchy

Work flows down through three levels. Each level gets its own conversation on the message bus and its own workspace.

```
Office Manager                       -- cross-project coordination
  |
  +-- Project Lead                   -- cross-workgroup coordination
        |
        +-- Job (single project)     -- a unit of work, typically a GitHub issue
              |
              +-- Task (single agent) -- dispatched to a workgroup agent
              +-- Task
```

### Job

A top-level unit of work within a project, typically tied to a GitHub issue. The project lead accepts and coordinates jobs.

- **Created by**: The project lead, in response to OM dispatch or human request.
- **Workspace**: Each job gets its own git worktree at `{project}/.teaparty/jobs/job-{id}--{slug}/worktree/`. See [job-worktrees](proposals/job-worktrees/proposal.md).
- **Lifecycle**: `active -> complete | failed`

### Task

A sub-unit of work within a job, dispatched by the project lead to a specific workgroup agent. Leads routinely dispatch multiple tasks in parallel.

- **Created by**: The project lead, via `Send` to the target agent.
- **Workspace**: Each task gets its own git worktree branched from the job's worktree. Parallel tasks on a shared checkout corrupt each other -- task worktrees are unconditional.
- **Merge**: Completed task branches are merged back into the job branch by the project lead. The job branch is merged to the integration branch on job completion.

### Cross-Project Coordination

Cross-project communication is always mediated by the office manager. Project-scoped agents have no direct bus routes to other projects. The OM holds cross-project context and translates between them. See [agent-dispatch routing](proposals/agent-dispatch/proposal.md).

---

## Conversation Kinds

Agent messages are routed by conversation kind on the message bus. See [messaging](proposals/messaging/proposal.md) and [agent-dispatch](proposals/agent-dispatch/proposal.md).

| Kind | Participants | Initiated by |
|------|-------------|-------------|
| Office manager | Human + OM | Human opens from Sessions card |
| Project session | Human + project lead + proxy | Job or gate event |
| Agent dispatch | Lead + worker agent | Lead via `Send` |
| Proxy review | Human + their own proxy | Human opens directly |
| Config lead | OM + configuration specialists | OM routes config request |

Multiple conversations can be active simultaneously. All persist on the message bus and can be resumed.

---

## Human Interaction Model

Humans interact with TeaParty through conversation, primarily via the dashboard chat blade.

### What Humans Can Do

| Action | How |
|--------|-----|
| Chat with the office manager | Open a conversation from the Sessions card |
| Participate in job/task conversations | Join the chat, talk alongside agents |
| Launch jobs directly | Request work through the OM or project lead |
| Review and calibrate the proxy | Open a proxy review session |
| Steer priorities | Memory-based steering via OM conversation |
| Intervene in active sessions | Type in a job/task chat (triggers INTERVENE) |
| Withdraw sessions | Dashboard Withdraw button (kill signal) |

### Two Kinds of Influence

**Memory-based steering** records durable preferences that influence all future work. "Focus on security." These propagate through the shared memory pool, surfacing in any agent's retrieval when context matches.

**Direct intervention** acts immediately on a specific session. The OM calls MCP tools: `WithdrawSession`, `PauseDispatch`, `ResumeDispatch`, `ReprioritizeDispatch`. See [office-manager](proposals/office-manager/proposal.md).

### D-A-I Role Model

Every team has exactly one decider. The decider has final authority at gates. Advisors can interject but their input is advisory. Informed members observe but cannot write. See [team-configuration](proposals/team-configuration/proposal.md).

---

## Agent Model

- **Agents are autonomous**, not scripted. They decide what to do based on conversation context, workflow state, and their own judgment. No prescriptive prompts or retry loops.
- **Agent output is never truncated.** Output rules are minimal -- no format constraints, length limits, or plain-text-only directives.
- **Workflows are advisory, not mandatory.** Agents follow them by choice, not enforcement.
- **Every agent is an independent process.** Each agent runs as a standalone `claude -p` invocation with `--resume` for multi-turn conversations. Agents communicate via the message bus using `Send` and `Reply`, not by holding teammates in context. See [agent-dispatch](proposals/agent-dispatch/proposal.md).
- **Lead agents coordinate.** The OM coordinates across projects. Project leads coordinate within a project. Workgroup leads coordinate within a workgroup. Leads decompose work, send requests to named roster members, and synthesize responses.
- **Bus routing enforces boundaries.** Routing policy derives from workgroup membership. Cross-team requests go through the project lead. Cross-project requests go through the OM.

### Agent Types

| Type | Scope | Role |
|------|-------|------|
| Office Manager | Management team | Cross-project coordination, human's primary agent |
| Project Manager | Management team | Project coordination (future, for multi-PM setups) |
| Project Lead | Project team | Decomposes jobs into tasks, dispatches to workgroup agents |
| Configuration Lead | Configuration workgroup | Routes config requests to specialists |
| CRUD Specialist | Configuration workgroup | Creates/modifies agents, skills, hooks, workgroups, projects |
| Workgroup Lead | Single workgroup | Coordinates workgroup agents within jobs |
| Workgroup Agent | Single workgroup | Executes tasks |
| Human Proxy | Cross-cutting | Handles escalations and gates autonomously; escalates when uncertain |

### Execution Model

Agents use the write-then-exit-then-resume pattern. A lead that sends parallel requests records outstanding threads in its conversation history before exiting. Workers call `Reply` when done. The lead is re-invoked when all threads close. State lives on the bus, not in process memory -- durability across restarts follows from that.

The `Send` tool flushes current state to a scratch file before posting, assembling a composite message with the task and current job context. The recipient gets a self-contained brief. See [agent-dispatch](proposals/agent-dispatch/proposal.md).

---

## Workspace Model

Session = worktree. Every session gets a git worktree. Every job gets a worktree. Every task gets a worktree. The 1:1:1 correspondence between session, worktree, and branch is unconditional.

```
{project}/.teaparty/
  jobs/
    jobs.json
    job-{id}--{slug}/
      worktree/          -- job's git worktree
      job.json           -- job state
      tasks/
        task-{id}--{slug}/
          worktree/      -- task's git worktree (branched from job)
          task.json      -- task state
```

Jobs are project-scoped. A pybayes job lives in the pybayes repo, not in the TeaParty repo. Cleanup is hierarchical -- removing a job directory removes everything it owns. See [job-worktrees](proposals/job-worktrees/proposal.md).

---

## Technology Stack

| Layer | Technology |
|-------|-----------|
| Agent runtime | Claude Code CLI (`claude -p` with `--resume`) |
| Package | `teaparty/` (Python, installed via `uv sync`) |
| Message bus | `teaparty/messaging/` -- event bus, conversations, routing, IPC |
| CfA engine | `teaparty/cfa/` -- protocol engine, actors, session, dispatch, state machine, gates |
| Proxy | `teaparty/proxy/` -- human proxy system |
| Learning | `teaparty/learning/` -- hierarchical memory (episodic, procedural, research) |
| Teams | `teaparty/teams/` -- multi-turn team coordination (OM, project lead/manager) |
| Runners | `teaparty/runners/` -- LLM execution backends (Claude CLI, Ollama, deterministic) |
| MCP server | `teaparty/mcp/` -- config CRUD, escalation, messaging, intervention tools |
| Workspace | `teaparty/workspace/` -- git worktree and job lifecycle |
| Dashboard | `teaparty/bridge/` -- HTML dashboard + bridge server (localhost:8081) |
| Config | `.teaparty/` -- agents, workgroups, projects, management settings |
| Tests | `unittest.TestCase` with `_make_*()` helpers |

---

## Further Reading

### Conceptual Design
- [CfA State Machine](conceptual-design/cfa-state-machine.md) -- Three-phase Conversation for Action protocol
- [Intent Engineering](conceptual-design/intent-engineering.md) -- AI-assisted intent capture dialog
- [Strategic Planning](conceptual-design/strategic-planning.md) -- Bridge from intent to execution
- [Human Proxies](conceptual-design/human-proxies.md) -- Learned proxy agents that stand in for humans
- [Learning System](conceptual-design/learning-system.md) -- Hierarchical memory, scoped retrieval, promotion chain
- [Hierarchical Teams](conceptual-design/hierarchical-teams.md) -- Hierarchical agent team architecture
- [Agent Dispatch](conceptual-design/agent-dispatch.md) -- Message routing and team sessions

### Proposals (Milestone 3)
- [Milestone 3: Human Interaction Layer](proposals/milestone-3.md) -- Humans as team members at every level
- [Office Manager](proposals/office-manager/proposal.md) -- Human's coordination partner, cross-project gateway
- [Messaging](proposals/messaging/proposal.md) -- Message bus design, conversation persistence
- [Agent Dispatch](proposals/agent-dispatch/proposal.md) -- Single-agent invocations, bus-mediated communication, routing
- [Team Configuration](proposals/team-configuration/proposal.md) -- File-based configuration tree, D-A-I roles
- [Configuration Team](proposals/configuration-team/proposal.md) -- Workgroup for creating Claude Code artifacts
- [Chat Experience](proposals/chat-experience/proposal.md) -- Four human interaction patterns
- [Job Worktrees](proposals/job-worktrees/proposal.md) -- Hierarchical, project-scoped worktree layout
- [CfA Extensions](proposals/cfa-extensions/proposal.md) -- INTERVENE and WITHDRAW events
- [Proxy Review](proposals/proxy-review/proposal.md) -- Direct proxy calibration channel
- [Context Budget](proposals/context-budget/proposal.md) -- Stream-based context management
- [Dashboard UI](proposals/dashboard-ui/proposal.md) -- Hierarchical dashboard with drill-down navigation

### Detailed Design
- [Detailed Design](detailed-design/index.md) -- Implementation status, gap analysis, data models

### Reference
- [Folder Structure](reference/folder-structure.md) -- Directory layout on disk
- [UX Design](reference/UX.md) -- User experience philosophy
- [Research Directions](reference/research-directions.md) -- Active open questions
