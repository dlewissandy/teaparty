# Hierarchical Agent Teams

Hierarchical agent teams are TeaParty's structural solution to context rot — the degradation of earlier instructions in long multi-step tasks, where the model begins optimizing for recent context at the expense of the original intent. This is the third pillar of TeaParty's four-pillar framework: where intent engineering establishes what to do and the learning system preserves what was learned, hierarchical teams ensure each agent works within a context bounded by what is relevant to its role.

The implementation uses Claude Code's native team primitives. Each level of the work hierarchy (engagement, project, job) runs as an independent Claude Code team session with its own context window. Levels are bridged by **liaison agents** — lightweight teammates in the upper team whose sole function is to communicate with a separate lower team, relaying tasks downward and results upward.

This architecture addresses context rot directly: each team's context window is tightly scoped to its own work. Complexity is compressed at each level boundary into a task description (going down) and a result summary (going up). An explicit process boundary — not a prompt instruction — enforces the separation.

See [ARCHITECTURE.md](ARCHITECTURE.md) for the full corporate hierarchy and [agent-dispatch.md](agent-dispatch.md) for dispatch mechanics.

---

## Mapping to the Work Hierarchy

TeaParty's three work-unit types map directly to team levels. The top level in each hierarchy is the **uber team** — the strategic coordinator responsible for decomposing work and synthesizing results, never for producing deliverables directly.

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

The job team has no knowledge of any team above it. It receives a task description and produces artifacts. TeaParty models the team session as a `job` conversation.

### Project Team

Cross-workgroup coordination within a single organization.

| Role | Agent | Source |
|------|-------|--------|
| Team lead | Org lead | Organization's `is_lead=True` agent (Administration workgroup) |
| Liaisons | One per participating workgroup | Ephemeral, generated when project starts |

The org lead coordinates and synthesizes. Each liaison bridges to its workgroup's job team. TeaParty models the team session as a `project` conversation.

### Engagement Team

Cross-organization collaboration, or top-level internal work.

| Role | Agent | Source |
|------|-------|--------|
| Team lead | Target org lead | Target organization's org lead |
| Internal liaisons | One per internal workgroup or project | Ephemeral, generated when engagement work begins |
| External liaison(s) | One per external party | Ephemeral, bridges to source org's representative |

For **external engagements**, the external liaison communicates with the source organization's org lead through the engagement conversation. For **internal engagements**, there is no external liaison -- the human interacts through the engagement conversation directly, and the org lead dispatches work via internal liaisons.

---

## The Liaison Agent

A liaison is a narrowly-scoped teammate in an upper-level team. It does not write code, make architectural decisions, or modify files. Its entire job is communication relay.

Liaisons are **ephemeral agent definitions** -- they exist only in the Claude Code team session, not as persistent Agent records in the database. They are generated when a project or engagement team is assembled, and destroyed when the team session ends. All persistent state lives in the TeaParty models (Project, Job, Conversation, Message).

Each liaison's prompt is narrow by design:

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

---

## The `relay_to_subteam` Tool

The liaison's single tool. It bridges two independent Claude Code team sessions through TeaParty's backend.

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

**First call** creates a Job in the liaison's assigned workgroup, launches a Claude Code team session for the job, and returns a confirmation that the sub-team is working. **Subsequent calls** send messages to the existing session and return the sub-team's latest output.

Sub-teams may run for extended periods. Rather than blocking the liaison, the tool returns immediately after dispatch. When the sub-team completes or has a question, TeaParty injects a notification into the parent team session directed at the liaison. The liaison picks up the notification and relays the result to the team lead.

For engagement teams, the external liaison uses a variant (`relay_to_partner`) that communicates through the engagement conversation rather than spawning a job team — bridging to the source org's representative without creating a new process.

---

## Communication Protocol

### Within a Team (Native Claude Code)

All intra-team communication uses Claude Code's native primitives: `SendMessage` for direct messages, `TaskCreate`/`TaskUpdate`/`TaskList` for shared task tracking. No TeaParty-specific layer is needed within a single team level.

### Across Team Levels (Liaison Bridge)

Cross-level communication always passes through a liaison using `relay_to_subteam`. The liaison compresses context at the boundary:

**Downward (task assignment):**
```
Org lead -[SendMessage]-> Liaison -[relay_to_subteam]-> Sub-team lead
```
The liaison translates the org lead's high-level task into a scoped task description. The sub-team receives only what it needs -- no project-level planning discussions, no other workgroups' details.

**Upward (result delivery):**
```
Sub-team lead -[completes work]-> TeaParty notification -> Liaison -[SendMessage]-> Org lead
```
The liaison summarizes the sub-team's output. The org lead sees the result, not the sub-team's internal deliberation.

Each hop compresses context. Tasks assigned to sub-teams should be scoped to minimize cross-team round trips.

TeaParty's database models (Conversation, Message) are abstractions over the Claude Code team state: each team session maps to a Conversation, each agent message is persisted as a Message. Every message at every hierarchy level is visible in the UI and persistent — even though the underlying execution is distributed across independent processes.

---

## Context Isolation

The primary benefit of hierarchical teams is scoped context windows. Each level sees only what it needs:

| Level | Context contains | Context does NOT contain |
|-------|-----------------|------------------------|
| Engagement team | Engagement scope, partner communication, project-level status summaries | Internal project deliberations, job-level details, workgroup internal discussions |
| Project team | Project scope, cross-workgroup coordination, job result summaries | Job-level agent discussions, workgroup internal file changes, engagement negotiation history |
| Job team | Job task description, workgroup files, workgroup workflows | Project-level coordination, other workgroups' work, engagement details, org-level discussions |

Context isolation is achieved structurally, not by filtering or prompt instruction. Each team is a separate `claude` process that starts with a clean context window. A process boundary is a hard guarantee; a prompt instruction is not.

As conversations grow long within a team, Claude Code's automatic context compaction operates within that team's scope. Compaction at the job level loses job-level detail but preserves the task result. The liaison at the project level never had the job-level detail to begin with — it only ever saw the compressed result. This is **hierarchical compaction**: each level compacts independently, and the compression cascades upward through liaison summaries.

---

## Workspace Isolation

Each job gets an isolated workspace: a git worktree branched from the workgroup's main (workspace-enabled workgroups) or virtual files materialized to a temp directory (non-workspace workgroups). Completed jobs merge changes back.

The project team has access to shared coordination artifacts (plans, status, cross-workgroup documents) but not to job workspaces — results flow up through liaisons. The engagement team has contract-based visibility: `deliverables/` is visible to both parties; `workspace/` is restricted to the target org.

Files move upward through explicit actions (merge, copy, relay), never through shared access.

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

Failure modes, resource limits, graceful shutdown, and implementation details are in [`projects/POC/docs/poc-architecture.md`](../projects/POC/docs/poc-architecture.md).
