# TeaParty Concepts

## Hierarchy

TeaParty organizes work through a corporate hierarchy:

- **Management team** — the top level. Has a human decider, a lead agent (office manager), workgroups, and registered projects.
- **Project** — a registered codebase with its own team. Has a lead agent (project manager), workgroups, and agents. Projects are where code lives.
- **Workgroup** — a department within a project or at the management level. Has a lead agent, member agents, and a focus area (e.g. Coding, Configuration).
- **Agent** — an autonomous worker with a defined role, tools, skills, and permissions. Agents belong to workgroups.

The management team coordinates across projects. Each project manages its own workgroups. Workgroups manage their agents.

## Work

Work flows through three levels:

- **Job** — a unit of work assigned to a single workgroup. A workgroup lead decomposes a job into tasks and assigns them to agents. Jobs run in isolated worktrees and merge back when complete.
- **Task** — a single agent's assignment within a job. The agent works autonomously, producing artifacts (code, docs, configs).
- **Dispatch** — sending work down the hierarchy. The office manager dispatches to project leads; project leads dispatch to workgroup leads; workgroup leads assign to agents.

Jobs follow the CfA (Call for Action) protocol: PROPOSE -> APPROVE -> execute -> COMPLETE/WITHDRAW. The human decider approves at gates.

## Configuration

Configuration is stored in two places:

- **`.claude/`** — agent definitions (`agents/`), skills (`skills/`), and settings that Claude Code discovers automatically. Each agent sees a scoped `.claude/` containing only its allowed skills.
- **`.teaparty/`** — team structure, workgroup definitions, project registration, and agent infrastructure (message buses, session state, pins).

Changes to configuration are routed through the Configuration Lead, who dispatches to specialists (agent-specialist, skills-specialist, systems-engineer, workgroup-specialist, project-specialist).

## Key Relationships

- An agent can belong to multiple workgroups
- A workgroup can exist at management level (cross-project) or within a project
- Projects are registered in `.teaparty/management/teaparty.yaml` and have their own `.teaparty/project/project.yaml`
- Skills are scoped per agent via the `skills:` allowlist in the agent definition
- Artifacts can be pinned to any scope (system, project, workgroup, agent) via `pins.yaml`
