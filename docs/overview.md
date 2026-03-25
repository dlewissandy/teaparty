# TeaParty Architecture

TeaParty is a platform where teams of humans and AI agents co-author files and collaborate in chat. A corporate hierarchy organizes all work, mirroring how real organizations operate: departments (workgroups) contain specialist agents, organizations coordinate across departments, and partnerships enable cross-organization collaboration.

---

## Corporate Hierarchy

The corporate hierarchy is the organizing structure for workers. It determines who can talk to whom, who manages whom, and where work gets assigned.

```
Home
  |
  +-- Organization A
  |     |
  |     +-- Workgroup: Engineering
  |     |     +-- agents: implementer, reviewer, ...
  |     |     +-- jobs: "fix login bug", "add search", ...
  |     |
  |     +-- Workgroup: Design
  |     |     +-- agents: designer, researcher, ...
  |     |     +-- jobs: "redesign dashboard", ...
  |     |
  |     +-- Workgroup: Administration (operations)
  |           +-- agents: org-lead
  |           +-- projects: "Q1 product launch" (cross-workgroup)
  |
  |     Partnerships: A -> B (can engage B)
  |
  +-- Organization B
        |
        +-- Workgroup: Consulting
              +-- agents: analyst, writer, ...
```

### Home

The top-level view for a human user. Home aggregates all organizations that a user owns or has been invited to participate in.

- **Lead agent**: The home agent. Can create new organizations, establish partnerships between them, and help onboard users.
- **Scope**: Cross-organization. The home agent sees all the user's organizations but does not see internal workgroup details.
- **One per user**: Each human user has their own Home.

### Organization

The top-level corporate structure. An organization has a name, a description, members, workgroups, and partnerships with other organizations.

- **Lead agent**: The org lead. Lives in the Administration workgroup (the designated operations workgroup). Can create projects, propose engagements to partnered organizations, onboard new workgroups, and coordinate cross-workgroup work.
- **Members**: Humans invited to the organization. Membership grants visibility into the org's structure and the ability to interact with the org lead.
- **Administration workgroup** (the designated `operations_workgroup` in the data model): Every organization has one. It is the operations hub -- the org lead lives here and handles incoming engagements, project coordination, and organizational management.

### Workgroup

The lower-level organizational unit. A workgroup is like a department -- it has a specific focus, a team of agents with relevant skills, and executes jobs assigned to it.

- **Lead agent**: The workgroup lead. Can create jobs, onboard new agents, and manage the workgroup's work queue.
- **Agents**: Specialist agents with defined roles, personalities, tools, and capabilities. They do the actual work within jobs.
- **Shared workspace**: A virtual file store with documents, workflows, and configuration that all agents in the workgroup can access.

### Partnerships

> **Note**: Partnerships are a platform design — they describe behavior planned for `teaparty_app/` and are not yet implemented.

Partnerships are directional trust links between organizations that enable cross-org collaboration.

- **Directional**: A partnership from Org A to Org B means A can propose engagements to B. It does **not** mean B can propose engagements to A.
- **Mutual**: Both directions must be established independently for mutual engagement capability.
- **Lifecycle**: `proposed -> accepted -> active -> revoked` (with `declined` branch from `proposed`)
- **No discovery required**: Once a partnership exists, either side (in the permitted direction) can propose engagements directly, without going through a public directory.

---

## Work Hierarchy

Work happens in three types of units. Each gets its own **agent team** (a Claude team session), its own **workspace**, and its own **conversation**.

```
Engagement (cross-org)          -- org leads collaborate
  |
  +-- Project (cross-workgroup) -- workgroup leads collaborate
  |     |
  |     +-- Job (single workgroup) -- workgroup agents execute
  |     +-- Job
  |
  +-- Job (direct dispatch)     -- sometimes no project is needed
```

### Job

The atomic unit of work. A job happens within a single workgroup and is executed by that workgroup's agents as an independent Claude Code team session.

- **Agent team**: A Claude Code team session with the workgroup's agents, led by the workgroup lead. The job team has no knowledge of any team above it -- it receives a scoped task description and produces artifacts.
- **Workspace**: Each job gets its own isolated workspace (a worktree or copy branched from the workgroup's shared files). This is critical when multiple jobs within a project or engagement modify the same files -- isolation prevents clobbering. Completed jobs merge their changes back.
- **Linkage**: Jobs carry an optional `engagement_id` and `project_id` to trace back to the engagement or project that spawned them.
- **Created by**: A liaison agent (when dispatching from a project), org lead (direct dispatch), or a human participant. Liaisons create jobs via the `relay_to_subteam` tool.
- **Lifecycle**: `in_progress -> completed | cancelled`
- **Conversation**: A chat where the agents discuss, plan, and execute. Humans can participate. The conversation is backed by a persistent Claude Code team session.
- **Configuration**: Team parameters (model, permission mode, max turns, cost/time limits) are inherited from the workgroup defaults, optionally overridden by the parent project.

### Project

Cross-workgroup collaboration within a single organization. A project runs as a **hierarchical agent team**: the project-level team (org lead + liaison agents) coordinates independent job-level teams (workgroup agents) in each participating workgroup. See [hierarchical-teams.md](conceptual-design/hierarchical-teams.md).

- **Agent team**: A Claude Code team session with the org lead as team lead and one **liaison agent** per participating workgroup. Liaisons are ephemeral -- they exist only in the team session, not as persistent Agent records. Each liaison's sole tool (`relay_to_subteam`) spawns and communicates with its workgroup's job team.
- **Workspace**: A shared project workspace for coordination artifacts (plans, status, cross-workgroup documents). The project team does not have direct access to job workspaces -- results flow up through liaisons.
- **Created by**: The org lead, typically when decomposing an engagement or fulfilling an internal request.
- **Lifecycle**: `pending -> in_progress -> completed | cancelled`
- **Conversation**: A project conversation (kind: `project`) backed by the project team session. The org lead coordinates and synthesizes; liaisons relay to/from sub-teams.
- **Context isolation**: The project team's context window contains only project-level coordination. Job-level detail is compressed at the liaison boundary into task descriptions (going down) and result summaries (going up).

### Engagement

Cross-organization work between two partnered organizations, or top-level internal work. An engagement is the highest level of the hierarchical team structure.

> **Note**: The current `teaparty_app/` implementation scopes engagements to workgroups (`source_workgroup_id` / `target_workgroup_id`). Org-level scoping as described here is a planned platform design, not yet implemented.

- **Agent team**: When work begins, a Claude Code team session with the target org lead as team lead, **internal liaisons** (one per participating workgroup or project), and **external liaison(s)** (for cross-org engagements, bridging to the source org's representative). During the negotiation phase, no team session is needed -- single-agent dispatch handles the conversation.
- **Workspace**: Contract-based visibility -- `deliverables/` is visible to both parties; `workspace/` is restricted to the target org.
- **Created by**: The source org's lead proposes, the target org's lead accepts. Or a human member creates an internal engagement.
- **Lifecycle and feedback model**: The engagement lifecycle includes states from proposed through reviewed, with cycle prevention via engagement chains and feedback bubble-up through the agent hierarchy.
- **Conversation**: A shared conversation where both org leads (or human + org lead) negotiate terms and track progress. Once work begins, the engagement team session coordinates projects and direct-dispatch jobs.
- **Internal engagements**: A human member creates an engagement directly -- they describe what they need, and the org lead handles it the same way as external work.



---

## Conversation Kinds

Agent messages are routed by conversation kind; the full routing model is in [Agent Dispatch](conceptual-design/agent-dispatch.md).

---

## Human Interaction Model

Humans interact with TeaParty primarily through agents, not by managing agents directly.

### What Humans Can Do

| Action | Allowed? | How |
|--------|----------|-----|
| Participate in job conversations | Yes | Join the job's chat, talk alongside agents |
| Participate in project conversations | Yes | Join the project's chat with workgroup leads |
| Participate in engagement conversations | Yes | Join the engagement's chat with org leads |
| DM the organization lead | Yes | Direct message to the org lead agent |
| Create internal engagements | Yes | Request work through the org lead |

### What Humans Cannot Do

| Action | Why Not |
|--------|---------|
| DM workgroup members directly | No side-tasks. Work goes through the workgroup lead. |
| DM workgroup leads directly | No side-jobs. Work goes through the org lead or through a project/job conversation. |
| Assign work directly to agents | The lead agent decides how to decompose and assign work. |

When agents need human input, feedback requests flow up the hierarchy and responses flow back down.

---

## Agent Model

- **Agents are autonomous**, not scripted. They decide what to do based on conversation context, workflow state, and their own judgment. No prescriptive prompts or retry loops.
- **Agent output is never truncated.** Output rules are minimal -- no format constraints, length limits, or plain-text-only directives.
- **Workflows are advisory, not mandatory.** Agents follow them by choice, not enforcement.
- **Lead agents coordinate.** Every workgroup has a lead agent; every organization has an org lead. Lead agents manage work decomposition, progress tracking, and cross-boundary communication.
- **Agent teams use Claude Code CLI.** Multi-agent collaboration happens through persistent team sessions with bidirectional `stream-json` I/O. See [agent-dispatch.md](conceptual-design/agent-dispatch.md).
- **Liaison agents bridge hierarchy levels.** Projects and engagements create hierarchical teams where each level runs as an independent Claude Code team session. Liaison agents are ephemeral teammates in the upper team whose sole function is to communicate with a lower team via the `relay_to_subteam` tool. They do not write code or make decisions -- they relay tasks downward and results upward, compressing context at each boundary. See [hierarchical-teams.md](conceptual-design/hierarchical-teams.md).

### Agent Types

| Type | Persistent? | Scope | Role |
|------|-------------|-------|------|
| Workgroup agent | Yes (Agent record) | Single workgroup | Executes work within jobs |
| Workgroup lead | Yes (Agent record, `is_lead=True`) | Single workgroup | Coordinates workgroup agents, leads job teams |
| Org lead | Yes (Agent record, `is_lead=True`) | Organization (Administration workgroup) | Orchestrates projects/engagements, leads project/engagement teams |
| Liaison | No (ephemeral definition) | Project or engagement team | Bridges upper team to a lower team via `relay_to_subteam` |
| Home agent | Yes (Agent record) | User-level | Creates orgs, manages partnerships |

---

## Workspace and Filestore Model

TeaParty has two coexisting file systems:

1. **Virtual files** (JSON column in the database): Documents, workflows, configuration, agent learnings. These are what agents read as prompt context. Managed through file-ops tools.
2. **Git repositories** (workspace-enabled workgroups): Source code and artifacts that benefit from version history and branch isolation. Each job gets a branch; completed jobs merge to main. See [sandbox-design.md](proposals/sandbox-design.md) for the future sandbox architecture.

Each job creates a branch (or worktree) from the workgroup's shared files and merges back on completion. This model applies whether the workgroup uses virtual files or a git repository — jobs are isolated; merging is explicit. See [hierarchical-teams.md](conceptual-design/hierarchical-teams.md) for the full workspace isolation model.

The virtual file tree reflects the full corporate hierarchy. See [file-layout.md](reference/file-layout.md).

---

## Technology Stack

| Layer | Technology |
|-------|-----------|
| Backend | FastAPI + SQLModel + SQLite |
| Frontend | Vanilla JS, no framework, no build tools |
| Auth | Google ID token verification + app bearer token |
| Agent runtime | Claude Code CLI (team sessions via `stream-json`) |
| LLM calls | All through `llm_client.create_message()` -- never call the Anthropic SDK directly |
| Tests | `unittest.TestCase` with `_make_*()` helpers, not pytest fixtures |
| DB migrations | Lightweight pattern in `db.py`, not Alembic |

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

### Proposals
- [Office Manager](proposals/office-manager.md) -- Human-initiated conversation, cross-project coordination
- [Human Participation](proposals/human-participation.md) -- Seats at every table
- [Messaging](proposals/messaging.md) -- Message bus design
- [Sandbox Design](proposals/sandbox-design.md) -- Docker containers and git integration
- [Cognitive Architecture](proposals/cognitive-architecture.md) -- Agent learning and memory

### Detailed Design
- [Detailed Design](detailed-design/index.md) -- Implementation status, gap analysis, data models

### Reference
- [File Layout](reference/file-layout.md) -- Virtual file tree structure
- [Folder Structure](reference/folder-structure.md) -- POC directory layout on disk
- [UX Design](reference/UX.md) -- User experience philosophy
- [Research Directions](reference/research-directions.md) -- Active open questions
- [Autodiscovery](reference/autodiscovery.md) -- Autonomous code review system
- [POC Implementation Reference](../projects/POC/docs/poc-architecture.md) -- CLI flags, env vars, stream-JSON format
- [README](../README.md) -- Project overview
