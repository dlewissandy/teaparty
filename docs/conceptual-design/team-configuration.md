# Team Configuration

The `.teaparty/` configuration tree is the source of truth for how agents are organized, who they report to, what skills they have access to, and which humans participate in their work. It defines the organizational structure that the runtime reads at dispatch time to determine rosters, skill availability, and MCP access.

This document describes the configuration model — the shape of the tree, the rules that govern it, and the separation between what is configured and what is computed at runtime.

## Two Scopes, One Structure

Configuration exists at two levels, each with identical internal structure:

**Management scope** — the top-level organizational configuration, rooted at `.teaparty/management/`. This is where the Office Manager's workgroup is defined, where projects are registered, and where organization-wide agents, skills, hooks, and settings live.

**Project scope** — per-project configuration, rooted at `{project}/.teaparty/project/`. This is where a Project Lead's workgroup is defined, where project-specific workgroups are registered, and where project-scoped agents, skills, and settings live.

Both scopes share the same directory layout:

```
{scope}/
  teaparty.yaml          # workgroup definition (lead, members, humans)
  agents/                 # agent definitions (.md files)
  skills/                 # skill definitions (directories with SKILL.md)
  workgroups/             # workgroup definitions (.yaml files)
  settings.yaml           # hooks, MCP servers, and other settings
```

The structural symmetry is deliberate. A project workgroup is configured the same way as the management workgroup — same fields, same semantics, same catalog conventions. The only difference is scope: management-level configuration applies across all projects; project-level configuration applies within a single project.

This means that learning to configure one level teaches you the other. There is no special syntax for management versus project configuration.

## The Workgroup Definition

Every workgroup — management, project, or regular — is defined by a YAML file with the same core fields:

- **name** and **description** — identity and the one-line summary that tells a parent lead when to dispatch here.
- **lead** — the agent responsible for the workgroup. The lead coordinates and dispatches; it is the only agent that communicates with agents in other workgroups (see [hierarchical-teams.md](hierarchical-teams.md)).
- **members** — the agents, workgroups, or projects the lead can dispatch to. Membership is the active roster — only members receive work.
- **humans** — the people who participate in this workgroup's decisions (see [Human Roles](#human-roles-decider-advisor-informed) below).

Management workgroups add `projects:` and `workgroups:` registration blocks. Project workgroups add a `workgroups:` registration block. Regular workgroups have neither — they are leaf teams that do work.

## Registration vs Membership

Knowing about something and being able to dispatch to it are separate concerns.

**Registration** is catalog entry. Registering a project means the management workgroup knows it exists — its name, path, and config file location. Registering a workgroup means the parent workgroup knows it exists and where its definition lives. Registration is a prerequisite for membership but does not imply it.

**Membership** is dispatch eligibility. A project listed under `members.projects` is one the Office Manager can dispatch to. A workgroup listed under `members.workgroups` is one the Project Lead can dispatch to. An agent listed under `members.agents` is one the lead can call on directly.

This separation exists because not everything that is known should be active. A project can be registered but paused, archived, or imported for reference only. A workgroup can be registered but not yet staffed. The catalog is the full inventory; membership is the working set.

```yaml
# Registration — the management workgroup knows these exist
projects:
  - name: TeaParty
    path: .
    config: .teaparty/project.yaml
  - name: pybayes
    path: /Users/primus/git/pybayes
    config: .teaparty/project.yaml

# Membership — the Office Manager dispatches to these
members:
  projects:
    - TeaParty
```

In this example, `pybayes` is registered (the system knows about it) but not a member (the Office Manager will not dispatch to it). The same pattern applies to workgroups within a project.

## Catalog Merging and Precedence

Agents, skills, hooks, and settings form an inherited catalog that flows from management scope down to project scope.

**Management-level catalog** is derived from the filesystem:

- Agents: everything in `.teaparty/management/agents/`
- Skills: everything in `.teaparty/management/skills/`
- Hooks and settings: `.teaparty/management/settings.yaml`

**Project-level catalog** extends the management catalog with project-specific entries from `.teaparty/project/`. When a project-level entry shares a name with a management-level entry, the project-level entry takes precedence. This allows projects to override organization-wide defaults without modifying the management configuration.

Individual workgroups do not define their own catalogs. They are consumers — they select from the inherited catalog of their parent project (or management scope). This keeps the catalog authority at levels where it can be meaningfully governed and avoids fragmentation across dozens of leaf workgroups.

Skills deserve special mention: they are whitelisted per agent, not per workgroup. Each agent has its own list of skills it is permitted to invoke, selected from the catalog. A workgroup's `skills:` field, when present, is a catalog declaration for dispatch visibility — not an access control list.

## Human Roles: Decider-Advisor-Informed

Every workgroup declares its human participants using three roles:

**Decider** — exactly one, required. The decider has final decision authority at gates and can block or redirect work. The proxy system models the decider's preferences and predicts their decisions. Every workgroup must have a decider; there is no leaderless configuration.

**Advisors** — zero or more. Advisors can be consulted and can interject, but their input is advisory, not binding. Each advisor has a proxy that mediates contact. Advisors participate in discussions but do not make final calls.

**Informed** — zero or more. Informed participants receive notifications but do not participate in decisions and do not have proxies. When an agent decides someone should know about a result, it sends them a message directly.

```yaml
humans:
  decider: primus
  advisors:
    - alice
  inform:
    - xavier
```

Humans are participants, not members. They are never dispatched to, never appear in the `members:` block, and are never treated as agents. When an agent needs the decider's input, it escalates through the decider's proxy — a runtime-instantiated agent that mediates all human contact. See [human-proxies.md](human-proxies.md) for how proxies work.

## Configuration vs Runtime

The `.teaparty/` tree draws a hard line between what is configured and what is computed.

**Configuration** is checked into git. It is the organizational structure — workgroup definitions, agent definitions, skill definitions, human role assignments, registered projects, hooks, and settings. It changes through deliberate acts: a human editing YAML, or the Configuration Team writing files through MCP tools. Configuration is the same across all sessions and all worktrees that share the same branch.

**Runtime state** is ephemeral. Sessions, dispatch queues, heartbeats, proxy memory, dashboard stats, and worktree assignments are all computed at runtime and never committed. They live in locations that are explicitly gitignored (session directories, stats files, local overrides).

This separation matters because configuration is the contract that agents read at launch time. An agent dispatched to a workgroup reads the workgroup definition, resolves its skill catalog, and knows its roster — all from configuration. The runtime then tracks what happens during execution, but that tracking never feeds back into the configuration tree automatically. Changes to configuration require human intent.

| Configured (git) | Runtime (ephemeral) |
|-------------------|---------------------|
| Workgroup definitions | Active sessions |
| Agent definitions | Dispatch queues |
| Skill definitions | Heartbeats |
| Human role assignments | Proxy memory |
| Project registrations | Dashboard stats |
| Hooks and settings | Worktree assignments |
| Norms | Job artifacts |

## Scheduled Tasks

Scheduled tasks are skill invocations on a timer — a cron expression paired with a skill reference and arguments. They exist at two levels only:

- **Management level** — tasks defined in `teaparty.yaml`, executed by the Office Manager or a designated agent.
- **Project level** — tasks defined in `project.yaml`, executed within the project's context.

Regular workgroups do not have scheduled tasks. A workgroup that needs recurring work defines the skill at the project or management level and schedules it there. This keeps scheduling authority at levels where it can be meaningfully governed — a workgroup lead should not be able to create arbitrary cron jobs.

Every scheduled task must reference an existing skill. No raw prompts. The skill is the contract for what the task does, and it must exist before the task is created.

## Architectural Invariants

These are structural rules that the configuration model enforces. They are not conventions or best practices — they are constraints that the system depends on for correctness.

### Communication flows through leads only

Agents within a workgroup communicate only through their lead. An agent in the Coding workgroup cannot directly message an agent in the Research workgroup. Cross-workgroup communication goes up through the Coding lead, across to the Project Lead, and down through the Research lead. This is the structural guarantee that makes context isolation work — see [hierarchical-teams.md](hierarchical-teams.md).

### Humans are not members

Humans participate through proxies, not as roster entries. The `humans:` block declares participation roles; the `members:` block declares dispatch targets. These are disjoint. A lead dispatches to agents and workgroups, never to humans. Human contact always goes through the proxy escalation path.

### Skills are per-agent, not per-workgroup

The skill catalog is defined at the management or project level. Individual agents select from this catalog via their `skills:` allowlist. A workgroup does not grant or restrict skill access — each agent's definition controls what it can invoke. This means two agents in the same workgroup can have different skill sets, and moving an agent between workgroups does not change its skill access.

### Configuration authority does not cross project boundaries

A project's configuration workgroup can modify that project's workgroups and agents. It cannot reach into another project's `.teaparty/` directory. The management configuration workgroup can modify management-level configuration and project registration, but not project-internal configuration. Each scope is sovereign over its own tree.

### Configuration workgroups sit outside the dispatch hierarchy

The Configuration workgroup is registered in the catalog but is not a member of the dispatch roster. The Office Manager does not dispatch to it; the Project Lead does not dispatch to it. It is reached exclusively through the dashboard's chat blade — the user navigates to a config screen and starts a conversation with the appropriate config lead. This keeps configuration changes intentional and human-initiated, never triggered by agent-to-agent dispatch.

## The Configuration Team

Configuration changes that go beyond toggling a membership flag or editing a structured field are handled by a specialist workgroup — the Configuration Team. This team exists at both management and project levels, with specialists scoped to their domain.

The team's purpose is to absorb the mechanical complexity of creating and modifying configuration artifacts. A human says "I need an agent that reviews pull requests" in conversation; the Configuration Team's Agent Specialist designs the definition, selects the right model and tools, writes the prompt, and creates the file. The human reviews the result and iterates.

### Two modes of configuration change

**Direct edit** — for structured data with well-defined fields. Workgroup membership, agent metadata, hook selections, skill allowlists. The dashboard renders these as editable fields, pickers, and toggles. No conversation needed, no specialist involved.

**Chat in context** — for changes that require judgment, generation, or explanation. Creating a new agent from scratch. Writing or revising the prose body of an agent definition. Modifying a `NORMS.md`. Discussing a change with the config lead before committing it. The context is determined by the screen the user is on; the level determines which config lead is on the other end.

This split reflects a real difference in the nature of the work. Adding an agent to a workgroup roster is a mechanical operation with exactly one correct action. Designing that agent's prompt is a creative act that benefits from dialogue. The configuration model supports both without forcing everything through conversation.

### MCP tools as the write path

Configuration specialists do not write files directly. Every configuration write goes through an MCP tool — `CreateAgent`, `EditWorkgroup`, `CreateSkill`, and so on. The tool validates required fields, enforces schema constraints, and returns a structured result. This means:

- An agent calling `CreateAgent` cannot produce a malformed definition — the tool rejects it.
- Specialists have Read, Glob, Grep, and Bash for information gathering, but no Write access to configuration paths.
- Each specialist receives only the tools for its domain. An Agent Specialist cannot call `CreateSkill`.

See [agent-dispatch.md](agent-dispatch.md) for how the dispatch system reads these configuration files at launch time.

## Relationship to Other Documents

- [hierarchical-teams.md](hierarchical-teams.md) — the team structure that configuration defines
- [agent-dispatch.md](agent-dispatch.md) — how configuration is read at dispatch time to derive rosters and skills
- [human-proxies.md](human-proxies.md) — how the `humans:` block translates to runtime proxy agents
