# Hierarchical Agent Teams

TeaParty implements hierarchical agent teams using Claude Code's native team primitives. Each level of the work hierarchy (engagement, project, job) runs as an independent Claude Code team session. Levels are bridged by **liaison agents** -- lightweight teammates in the upper team whose sole function is to communicate with a separate lower team.

This architecture combats context rot: each team's context window is tightly scoped to its own work. Complexity is compressed at each level boundary into a task description (going down) and a result summary (going up).

See [ARCHITECTURE.md](ARCHITECTURE.md) for the full corporate hierarchy and [agent-dispatch.md](agent-dispatch.md) for dispatch mechanics.

---

## Mapping to the Work Hierarchy

TeaParty's three work-unit types map directly to team levels:

```
Engagement Team (uber team)
  org lead + external liaison(s) + internal liaison(s)
    |
    +-- Project Team (uber team)
    |     org lead + workgroup liaison(s)
    |       |
    |       +-- Job Team (sub-team)
    |       |     workgroup lead + workgroup agents
    |       |
    |       +-- Job Team (sub-team)
    |             workgroup lead + workgroup agents
    |
    +-- Job Team (sub-team, direct dispatch)
          workgroup lead + workgroup agents
```

Not every engagement spawns projects. Simple work can be dispatched directly as jobs. Similarly, not every project comes from an engagement -- the org lead can create projects from internal requests.

The key rule: **each team is a separate Claude Code team session with its own process tree and context window**. No team sees the internal reasoning of any other team.

---

## Team Composition

### Job Team

The atomic unit. A single workgroup's agents collaborating on a concrete task.

| Role | Agent | Source |
|------|-------|--------|
| Team lead | Workgroup lead | Workgroup's `is_lead=True` agent |
| Members | Workgroup agents | Workgroup's other agents |

The job team has no knowledge of any team above it. It receives a task description and produces artifacts. It uses native Claude Code team primitives internally (SendMessage, TaskCreate, shared task list). TeaParty models the team session as a `job` conversation.

### Project Team

Cross-workgroup coordination within a single organization.

| Role | Agent | Source |
|------|-------|--------|
| Team lead | Org lead | Organization's `is_lead=True` agent (Administration workgroup) |
| Liaisons | One per participating workgroup | Ephemeral, generated when project starts |

The org lead coordinates and synthesizes. Each liaison bridges to its workgroup's job team. The project team uses native Claude Code team primitives internally. TeaParty models the team session as a `project` conversation.

### Engagement Team

Cross-organization collaboration, or top-level internal work.

| Role | Agent | Source |
|------|-------|--------|
| Team lead | Target org lead | Target organization's org lead |
| Internal liaisons | One per internal workgroup or project | Ephemeral, generated when engagement work begins |
| External liaison(s) | One per external party | Ephemeral, bridges to source org's representative |

For **external engagements**, the external liaison communicates with the source organization's org lead through the engagement conversation. For **internal engagements**, there is no external liaison -- the human interacts through the engagement conversation directly, and the org lead dispatches work via internal liaisons.

The engagement team may create projects (spawning project teams) or dispatch jobs directly (spawning job teams), depending on whether the work is cross-workgroup or single-workgroup.

---

## The Liaison Agent

A liaison is a narrowly-scoped teammate in an upper-level team. It does not write code, make architectural decisions, or modify files. Its entire job is communication relay.

### Definition

Liaisons are **ephemeral agent definitions** -- they exist only in the Claude Code team session, not as persistent Agent records in the database. They are generated when a project or engagement team is assembled.

Each liaison definition includes:

| Field | Value |
|-------|-------|
| Name | `liaison-{workgroup-slug}` (internal) or `liaison-{org-slug}` (external) |
| Role | "Liaison to {workgroup/org name}" |
| Tools | `relay_to_subteam` (mandatory, always use) |
| Prompt | Narrow behavioral instructions (see below) |

### Spawn Prompt

```
You are a liaison agent bridging the {project/engagement} team to the
{workgroup name} workgroup. You do not write code or make architectural
decisions.

Your sole responsibility is communication relay:
1. Receive task assignments from the team lead
2. Use your relay_to_subteam tool to dispatch tasks and communicate
3. Report results, status updates, and questions back to the team lead

You MUST use the relay_to_subteam tool for ALL communication with your
sub-team. Do not attempt to do the work yourself.
```

### Lifecycle

1. **Created**: When the project/engagement team session starts. TeaParty generates the liaison definition and includes it in the `--agents` argument.
2. **Active**: Receives tasks from the team lead, relays to sub-team, relays results back.
3. **Destroyed**: When the project/engagement team session ends.

The liaison itself has no persistent state. All persistent state lives in the TeaParty models (Project, Job, Conversation, Message).

---

## The `relay_to_subteam` Tool

The liaison's single tool. It bridges two independent Claude Code team sessions through TeaParty's backend.

### Interface

```
relay_to_subteam:
  description: >
    Send a message to your sub-team. On first use, this creates a job
    in your workgroup, assembles the workgroup's agents into a team,
    and dispatches the message as the initial task. On subsequent uses,
    it sends a follow-up message to the existing team.
  parameters:
    message: str  # What to communicate to the sub-team
  returns:
    str  # Sub-team's response or current status
```

### Behavior

**First call (initialization):**
1. TeaParty creates a Job in the liaison's assigned workgroup, linked to the parent project/engagement.
2. TeaParty creates a job conversation with the workgroup's agents as participants.
3. TeaParty launches a Claude Code team session for the job (a new `claude` process with `--input-format stream-json`).
4. The liaison's message becomes the initial task prompt for the sub-team.
5. The tool returns a confirmation that the sub-team has been spawned and is working.

**Subsequent calls:**
1. TeaParty sends the message to the job conversation's team session (via `TeamSession.send_message()`).
2. The sub-team processes the message and produces responses.
3. The tool returns a summary of the sub-team's latest output.

### Async Completion Notification

Sub-teams may run for extended periods. Rather than blocking the liaison, the tool returns immediately after dispatch. When the sub-team completes or has a question:

1. TeaParty detects the event (job completion, question posted, team session idle).
2. TeaParty injects a notification into the project/engagement team session directed at the liaison.
3. The liaison picks up the notification and relays the result to the team lead.

This means the liaison alternates between two modes:
- **Active**: Receiving tasks from the team lead and dispatching them via the tool.
- **Waiting**: Idle until the sub-team produces output, at which point TeaParty wakes the liaison with a notification.

### External Liaison Variant

For engagement teams, the external liaison uses a variant of the tool that communicates through the engagement conversation rather than spawning a job team:

```
relay_to_partner:
  description: >
    Send a message to the partner organization's representative
    through the engagement conversation.
  parameters:
    message: str
  returns:
    str  # Partner's response or current status
```

The external liaison does not spawn processes. It reads from and writes to the engagement conversation, which the source org's representative can also access.

---

## Execution Flow

### Project Execution

```
1. Org lead creates a project (via create_project tool or human request)
      |
2. TeaParty backend:
   a. Creates Project record (status: pending)
   b. Creates project conversation (kind: "project")
   c. Generates liaison definitions for each workgroup in project.workgroup_ids
   d. Launches project team session (org lead + liaisons)
   e. Sets Project status to in_progress
      |
3. Org lead receives the project prompt in the team session
   a. Decomposes the work
   b. Assigns tasks to liaisons via native SendMessage / TaskCreate
      |
4. Each liaison:
   a. Receives task assignment
   b. Calls relay_to_subteam with the task description (first call spawns the job team)
   c. Reports "sub-team spawned, working on X" to org lead
      |
5. Sub-teams work independently:
   a. Workgroup lead coordinates workgroup agents
   b. Agents execute using native team primitives
   c. All work happens in the job's isolated workspace
      |
6. On sub-team completion:
   a. TeaParty notifies the liaison
   b. Liaison reads the result and relays to org lead
   c. Org lead synthesizes cross-workgroup results
      |
7. When all sub-teams complete:
   a. Org lead marks the project complete
   b. TeaParty shuts down the project team session
   c. If linked to an engagement, results flow up to the engagement level
```

### Engagement Execution

```
1. Engagement is proposed (external or internal)
      |
2. Negotiation phase:
   a. Org leads (or human + org lead) converse in engagement conversation
   b. No team session yet -- single-agent dispatch as today
      |
3. Engagement accepted, work begins:
   a. TeaParty launches engagement team session
   b. Target org lead is team lead
   c. Internal liaisons created for participating workgroups
   d. External liaison created for source org communication (if external)
      |
4. Target org lead decomposes the work:
   a. For cross-workgroup work: creates a project (spawns project team, which spawns job teams)
   b. For single-workgroup work: assigns directly to a workgroup liaison (spawns job team)
      |
5. Work proceeds hierarchically (engagement -> project -> job)
      |
6. Results flow back up:
   a. Job teams complete -> liaisons relay to project team
   b. Project teams complete -> liaisons relay to engagement team
   c. Org lead assembles deliverables
   d. External liaison communicates results to source org
      |
7. Engagement completed and reviewed
```

### Direct Job Dispatch (No Project)

For simple single-workgroup work, the org lead can skip the project level:

1. Org lead (in an engagement or internal context) calls `create_job` directly.
2. TeaParty creates the job and its team session.
3. The job team works independently.
4. On completion, results flow back to the org lead.

No liaison or project team is needed. This uses the existing single-level dispatch.

---

## Communication Protocol

### Within a Team (Native Claude Code)

All intra-team communication uses Claude Code's native primitives:

| Primitive | Usage |
|-----------|-------|
| SendMessage | Direct messages between teammates |
| TaskCreate / TaskUpdate / TaskList | Shared task tracking |
| Broadcast | Team-wide announcements (used sparingly) |

These are the standard Claude Code team tools. No TeaParty-specific communication layer is needed within a single team level.

### Across Team Levels (Liaison Bridge)

Cross-level communication always passes through a liaison using `relay_to_subteam`. The liaison compresses context at the boundary:

**Downward (task assignment):**
```
Org lead -[SendMessage]-> Liaison -[relay_to_subteam]-> Sub-team lead
```
The liaison translates the org lead's high-level task into a scoped task description for the sub-team. The sub-team receives only what it needs -- no project-level planning discussions, no other workgroups' details.

**Upward (result delivery):**
```
Sub-team lead -[completes work]-> TeaParty notification -> Liaison -[SendMessage]-> Org lead
```
The liaison summarizes the sub-team's output for the org lead. The org lead sees the result, not the sub-team's internal deliberation.

**Bidirectional (question relay):**
```
Sub-team lead posts question -> TeaParty notifies liaison
Liaison -[SendMessage]-> Org lead: "Team X asks: ..."
Org lead -[SendMessage]-> Liaison: "Tell them: ..."
Liaison -[relay_to_subteam]-> Sub-team lead receives answer
```

Each hop compresses context. A four-hop relay (member -> sub-lead -> liaison -> uber-lead -> liaison -> sub-lead -> member) is acceptable for blocking questions. Tasks assigned to sub-teams should be scoped to minimize these cross-team round trips.

### TeaParty's Conversation/Message Layer

TeaParty's database models (Conversation, Message, SyncedMessage) are **abstractions over the Claude Code team state**:

- Each Claude Code team session maps to a TeaParty Conversation.
- Each agent message in a team session is persisted as a TeaParty Message.
- The `team_bridge.py` component converts Claude Code `TeamEvent`s to Message records.
- The frontend's polling/SSE picks up messages from the database, regardless of which team level produced them.

This means every message at every hierarchy level is visible in the UI, searchable, and persistent -- even though the underlying execution is distributed across independent Claude Code processes.

---

## Context Isolation

The primary benefit of hierarchical teams is scoped context windows. Each level sees only what it needs:

| Level | Context contains | Context does NOT contain |
|-------|-----------------|------------------------|
| Engagement team | Engagement scope, partner communication, project-level status summaries | Internal project deliberations, job-level details, workgroup internal discussions |
| Project team | Project scope, cross-workgroup coordination, job result summaries | Job-level agent discussions, workgroup internal file changes, engagement negotiation history |
| Job team | Job task description, workgroup files, workgroup workflows | Project-level coordination, other workgroups' work, engagement details, org-level discussions |

Context isolation is achieved structurally, not by filtering. Each team is a separate `claude` process that starts with a clean context window containing only its scope-appropriate information.

### Compaction at Boundaries

As conversations grow long within a team, Claude Code's automatic context compaction operates within that team's scope. Compaction at the job level loses job-level detail but preserves the task result. The liaison at the project level never had the job-level detail to begin with -- it only ever saw the compressed result. This is **hierarchical compaction**: each level compacts independently, and the compression cascades upward through liaison summaries.

---

## Workspace Isolation

Each team level has its own file access scope:

### Job Teams

Each job gets an isolated workspace:
- **Workspace-enabled workgroups**: A git worktree branched from the workgroup's main. The job's agents read/write within this worktree.
- **Non-workspace workgroups**: Virtual files materialized to a temp directory, scoped by `topic_id`.

Multiple jobs within a project work in separate worktrees/scopes. Completed jobs merge changes back.

### Project Teams

The project team has access to the project workspace (`organizations/<org>/projects/<project>/workspace/`). This contains shared coordination artifacts -- plans, status summaries, cross-workgroup documents. The project team does NOT have direct access to job workspaces.

### Engagement Teams

The engagement team has access to the engagement workspace. Contract-based visibility applies: the `deliverables/` directory is visible to both parties; `workspace/` is restricted to the target org.

### File Flow

```
Job workspace (isolated)
  --[job completes, merge]--> Workgroup shared files
                                --[liaison relays deliverables]--> Project workspace
                                                                    --[org lead assembles]--> Engagement deliverables
```

Files move upward through explicit actions (merge, copy, relay), never through shared access. This prevents clobbering and maintains isolation.

---

## Workgroup Team Configuration

Each workgroup has configurable parameters that govern how its job teams are spawned. These are set through a workgroup configuration screen.

| Parameter | Default | Description |
|-----------|---------|-------------|
| `permission_mode` | `acceptEdits` | Claude Code permission mode for job team sessions |
| `model` | `claude-sonnet-4-6` | Default model for job team agents |
| `max_turns` | `30` | Maximum agent turns per job team session |
| `max_cost_usd` | `null` (unlimited) | Cost cap per job team session |
| `max_time_seconds` | `null` (unlimited) | Time limit per job team session |

These defaults can be overridden per-project (the Project record carries its own `model`, `max_turns`, `permission_mode`, etc.) or per-job if needed.

The configuration hierarchy:
```
Workgroup defaults  <--  Project overrides  <--  Job overrides
```

If a project specifies `model: claude-opus-4-6`, all job teams spawned from that project use Opus unless the job itself overrides. If neither project nor job specifies, the workgroup default applies.

---

## Failure Handling

### Sub-Team Stall

If a job team hasn't produced output within a configurable timeout (`max_time_seconds`):

1. TeaParty detects the stall.
2. TeaParty notifies the liaison: "Sub-team has stalled after N minutes."
3. The liaison reports to the team lead.
4. The team lead can: retry the task, reassign it, simplify the scope, or escalate.

### Liaison Failure

If a liaison becomes unresponsive (no activity within a timeout):

1. The org lead detects non-responsiveness (no replies to SendMessage).
2. The org lead can request a new liaison be spawned (via a tool or by asking TeaParty).
3. The replacement liaison picks up the sub-team's current state from the Job record and team session.
4. Sub-team continues running throughout -- it doesn't depend on the liaison being alive.

### Resource Limits

Resource limits are enforced at each level independently:

- **Job level**: `max_turns`, `max_cost_usd`, `max_time_seconds` from workgroup/project/job config.
- **Project level**: Project-level limits govern the project team session itself (the coordination overhead). These are typically more generous since coordination is lightweight.
- **Engagement level**: Engagement-level limits (if configured) govern the engagement team session.

When a limit is hit, the team session is stopped and TeaParty notifies the next level up.

### Graceful Shutdown

When a project or engagement completes:

1. The team lead marks it complete.
2. TeaParty sends shutdown requests to all liaisons.
3. Each liaison sends a shutdown to its sub-team (if still running).
4. All team sessions are cleaned up.
5. Worktrees are merged or preserved as configured.

---

## When to Use Hierarchical Teams

This architecture is justified when:
- The work decomposes into 2+ semi-independent workstreams.
- Each workstream is complex enough to benefit from its own multi-agent team.
- The total expected work would cause context rot in a single flat team.

For simpler work:
- **Single workgroup, single job**: Direct dispatch. No project team, no liaisons.
- **Single workgroup, multiple sequential jobs**: The org lead dispatches jobs one at a time. No project team needed.
- **Cross-workgroup but simple**: A project team with liaisons, but each job team may be a single agent rather than a full team.

The overhead of the liaison layer is justified by the context isolation it provides. For work that fits in a single context window, skip it.

---

## Implementation Notes

### Existing Infrastructure Reused

| Component | Already exists | Used for |
|-----------|---------------|----------|
| `TeamSession` | Yes | Manages each team-level Claude process |
| `team_registry.py` | Yes | Tracks active sessions per conversation |
| `team_bridge.py` | Yes | Converts events to Messages at every level |
| `agent_definition.py` | Yes | Builds agent JSON for `--agents` (extended for liaisons) |
| `_run_team_response()` | Yes | Entry point for team dispatch (used at every level) |
| `Project` model | Yes | Stores project config including team parameters |
| `Job` model | Yes | Stores job config and links to parent project/engagement |

### New Components Needed

| Component | Purpose |
|-----------|---------|
| Liaison agent definition generator | Builds ephemeral liaison definitions from workgroup metadata |
| `relay_to_subteam` tool implementation | Creates jobs, spawns sub-team sessions, bridges messages |
| `relay_to_partner` tool implementation | Bridges engagement conversation for external liaisons |
| Async notification injector | Pushes sub-team events into parent team sessions |
| Workgroup team config UI | Configuration screen for team parameters per workgroup |
| Project team lifecycle manager | Orchestrates project team creation, monitoring, and shutdown |

### Process Tree

A project with three workgroups produces this process tree:

```
TeaParty backend (FastAPI)
  |
  +-- Project team session (claude --input-format stream-json ...)
  |     Agents: org-lead, liaison-engineering, liaison-design, liaison-qa
  |
  +-- Job team session: Engineering (claude --input-format stream-json ...)
  |     Agents: engineering-lead, implementer, reviewer
  |
  +-- Job team session: Design (claude --input-format stream-json ...)
  |     Agents: design-lead, designer, researcher
  |
  +-- Job team session: QA (claude --input-format stream-json ...)
        Agents: qa-lead, tester
```

Four independent processes. Each has its own context window. The project team session coordinates the other three through liaison agents and the `relay_to_subteam` tool.
