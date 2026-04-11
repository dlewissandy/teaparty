# Office Manager and Dispatch Chain

The organizational design for how humans interact with the agent hierarchy. The office manager is the human's coordination partner -- a `claude -p` agent that lives at the management level and mediates between human intent and the dispatch chain that carries it out.

---

## The Office Manager

The office manager (OM) is a `claude -p` agent. Same substrate as every other agent: invoked via the CLI, stream-json output, tools for reading files and inspecting state. It is the lead of the management team.

The OM's job is coordination, not execution. It synthesizes status, dispatches work, transmits the human's intent through the hierarchy, and intervenes when the human directs it to. It does not write code, review artifacts, or approve gates.

The management team members include:

- **Project managers** -- one per registered project, each running in its own project repo.
- **Configuration lead (management)** -- routes configuration requests to CRUD specialists for management-scope artifacts.
- **Proxy** -- the human's autonomous representative at gates and escalations across all projects.

Communication between members happens via `Send` and `Reply` (see [messaging](messaging.md)).

---

## The Dispatch Chain

Each level in the hierarchy is an independent process with its own context window. Levels are bridged by communication, not shared context. This is the structural guarantee described in [hierarchical-teams](hierarchical-teams.md) -- no agent can see the internal reasoning of any other team, because no agent shares a process with any other team.

```
OM
+-- PM (one per project)
|   +-- project lead
|   |   +-- workgroup agents
|   +-- configuration lead (project)
|       +-- CRUD specialists
+-- configuration lead (management)
|   +-- project-specialist
+-- proxy
```

**Office manager** plans and coordinates across projects. Dispatches to PMs when work requires project-level coordination.

**Project manager (PM)** mediates between the OM and the project lead. Runs in the project repo. Coordinates two direct reports: the project lead (execution) and the project configuration lead (project-scope config changes). The PM exists for management-initiated coordination -- when the OM dispatches work that requires a project's attention.

**Project lead** owns execution within a project. Dispatches to workgroup agents. Receives work from the PM (management-initiated) or directly from the human (job-initiated).

**Workgroup agents** do the actual work. Scoped to their workgroup's files and tools.

---

## Four Entry Points

There are four ways a human initiates a conversation. Everything below these entry points is agents dispatching to other agents.

### OM chat

Human opens a free-form conversation with the office manager in the management chat blade. Open-ended, persistent across days or weeks. Topics include project status, cross-project steering, scheduling, workgroup management, and new project ideas.

### PM chat

Human opens a conversation with a specific project's PM in a project chat blade. Same conversational pattern as OM chat, but scoped to a single project. Useful when the human wants to coordinate within a project without going through the OM.

### Proxy 1:1

Human opens a conversation with their proxy on any screen. This is the direct calibration channel described in [human-proxies](human-proxies.md) -- the human inspects the proxy's model, corrects it, reinforces what matters. Available from any dashboard context.

### New job

Human launches a job directly to the project lead, bypassing the PM. This is the most common entry point for getting work done. The human describes the task, the project lead dispatches it to the appropriate workgroup.

---

## Authority Boundaries

Two kinds of authority must be distinguished. They are separate and must not be conflated.

**Team-lead authority** means controlling dispatch: who works on what, when work starts and stops, what gets prioritized. The OM exercises team-lead authority. So does every other team lead in the chain (PM, project lead, workgroup lead).

**Gate authority** means participating as a CfA role holder -- approving, rejecting, or requesting changes at gates within a session's state machine. The proxy exercises gate authority. See [cfa-state-machine](cfa-state-machine.md).

The OM never approves gates directly. It never participates in the CfA protocol as a role holder. When the human tells the OM "I'm worried about the database migration," the OM records that as a steering preference. Later, at a gate, the proxy retrieves that preference and gives the migration closer scrutiny. The influence is indirect -- through shared memory, not through direct gate participation.

This boundary is load-bearing. The proxy's autonomy model depends on being the sole gate decision-maker with accuracy tracking. If the OM could override gate decisions, the proxy's learning signal would be corrupted -- it could not distinguish its own errors from OM overrides.

---

## Memory and Steering

The OM and proxy share a memory database (`.proxy-memory.db`). Both read and write ACT-R chunks. Neither retains its context window between invocations -- the agent session is ephemeral, rebuilt from prompt and memory each time.

**Steering chunks** are recorded when the human expresses durable preferences in an OM conversation. "Focus on security." "We're switching to Postgres next quarter." These propagate indirectly through activation-based retrieval, surfacing in any agent's context when the retrieval cue matches.

**Gate outcome chunks** are recorded when the proxy processes a gate decision. The OM can retrieve these when the human asks "how are things going?" -- the OM reports what the proxy has observed.

Cross-session learning works because both agents share the same database and retrieval mechanics. What the human says in an OM conversation becomes context available at the next gate. What the proxy observes at a gate becomes context available in the next OM conversation. The message threads are separate; learning crosses between them through shared memory. See [learning-system](learning-system.md).

---

## Intervention

The OM can act immediately on specific sessions. These are team-lead actions, not CfA events -- they operate on the dispatch that contains a session, not on the session's internal state machine.

- **Withdraw session** -- kill a running session and clean up its resources.
- **Pause dispatch** -- suspend a dispatch so no new work starts.
- **Resume dispatch** -- restart a paused dispatch.
- **Reprioritize** -- change the priority of a dispatch.

The orchestrator exposes these as MCP tools that the OM calls during its turn, the same way any agent calls any tool. No new infrastructure beyond the tool definitions. See [agent-dispatch](agent-dispatch.md).

---

## Configuration Team

Each scope (management, project) has a configuration workgroup. The configuration lead routes requests to CRUD specialists, each responsible for a specific artifact type:

- **Agent specialist** -- creates and modifies agent definitions.
- **Skill specialist** -- creates and modifies skill definitions.
- **Workgroup specialist** -- creates and modifies workgroup definitions.
- **Hook specialist** -- creates and modifies hooks.
- **Project specialist** -- creates and modifies project registrations (management scope only).
- **Systems engineer** -- modifies settings, environment, and infrastructure config.

Configuration is accessed via chat blade, never via dispatch. The human (or the OM/PM on their behalf) opens a conversation with the configuration lead, describes what they want, and the lead routes the request. See [team-configuration](team-configuration.md).

The management configuration lead is a direct report of the OM. The project configuration lead is a direct report of the PM. Both follow the same pattern -- the difference is scope.

---

## Relationship to Other Conceptual Documents

- [agent-dispatch](agent-dispatch.md) -- routing, session lifecycle, stream processing.
- [hierarchical-teams](hierarchical-teams.md) -- process boundaries, context isolation, liaison pattern.
- [human-proxies](human-proxies.md) -- the proxy agent, gate authority, calibration.
- [cfa-state-machine](cfa-state-machine.md) -- the protocol that governs gates.
- [learning-system](learning-system.md) -- ACT-R memory, chunk types, activation dynamics.
- [messaging](messaging.md) -- Send/Reply, bus architecture, conversation identity.
- [team-configuration](team-configuration.md) -- configuration workgroups, CRUD specialists, D-A-I roles.
