# Folder Structure

TeaParty's folder structure mirrors its organizational model. The top-level directory is the organization. Projects are separate git repositories. Memory files are scoped to the hierarchy level where the learning occurred.

## Organization at the Top

The root directory represents the organization:

```
teaparty/                               # the organization
├── .claude/
│   ├── agents/                         # agent role definitions
│   │   ├── architect.md
│   │   ├── backend-engineer.md
│   │   ├── code-reviewer.md
│   │   ├── cognitive-architect.md
│   │   ├── doc-writer.md
│   │   ├── frontend-engineer.md
│   │   ├── graphic-artist.md
│   │   ├── researcher.md
│   │   ├── social-architect.md
│   │   ├── test-engineer.md
│   │   └── ux-designer.md
│   ├── commands/                       # custom slash commands
│   ├── skills/                         # skill definitions
│   └── CLAUDE.md                       # project instructions
├── docs/                               # organization-level documentation
├── projects/                           # one git repo per project
├── teaparty_app/                       # the platform itself
└── pyproject.toml
```

The `.claude/agents/` directory defines agent roles available across the organization. Each role is a markdown file specifying the agent's description, prompt, model, tools, and permission mode. These roles are instantiated in team JSON files within individual projects.

## Projects as Separate Repositories

Each project in `projects/` is a separate git repository with its own history, branches, and deliverables:

```
projects/
├── MEMORY.md                           # global learnings (cross-project)
├── POC/                                # proof-of-concept (uses parent repo)
├── hierarchical-memory-paper/          # research paper
├── agentic-cfa-publication/            # research paper
├── reasoning-interface-framework/      # research project
└── ...
```

The root `.gitignore` excludes project contents by default (`projects/*`) since each project manages its own git history. The POC is the exception — it is explicitly tracked by the parent repository for dogfooding (see below).

## Project Internal Structure

Each project contains its own agents, orchestration configuration, and session history:

```
projects/POC/
├── agents/                             # team definitions
│   ├── uber-team.json                  # strategic coordination team
│   ├── coding-team.json                # coding subteam
│   ├── writing-team.json               # writing subteam
│   ├── art-team.json                   # art subteam
│   ├── research-team.json              # research subteam
│   ├── editorial-team.json             # editorial subteam
│   ├── intent-team.json                # intent gathering team
│   └── project-team.json              # project-level liaison team
├── orchestrator/                       # CfA engine, actors, session lifecycle
├── scripts/                            # CfA state machine, proxy model, learning
├── tui/                                # terminal UI dashboard
├── docs/                               # project-specific documentation
├── .sessions/                          # session history
│   └── <timestamp>/                    # one directory per session
│       ├── MEMORY.md                   # session-level learnings
│       └── <team>/                     # team-level state
│           └── MEMORY.md              # team-level learnings
├── .worktrees/                         # git worktrees for session isolation
├── cfa-state-machine.json              # state machine definition
└── MEMORY.md                           # project-level learnings
```

## Memory Hierarchy

Memory files are scoped to the hierarchy level where the learning occurred. The [promotion chain](learning-system.md) moves validated learnings upward:

```
projects/MEMORY.md                              # global scope
projects/<project>/MEMORY.md                    # project scope
projects/<project>/.sessions/<ts>/MEMORY.md     # session scope
projects/<project>/.sessions/<ts>/<team>/MEMORY.md  # team scope
```

Each scope level also has typed memory stores — `institutional.md` (always loaded) and task-based stores (fuzzy-retrieved). See [Learning System](learning-system.md) for the full design.

## Git Worktree Isolation

Each session and dispatch runs in an isolated git worktree. This provides:

- **Concurrent sessions** — multiple sessions can modify the codebase simultaneously without conflicts
- **Branch isolation** — each session's changes are on a separate branch until approved
- **Clean rollback** — if a session fails, its worktree is discarded with no impact on the main branch

Completed sessions merge their worktree back to the parent repository. See [POC Architecture](poc-architecture.md) for the full worktree lifecycle.

## Dogfooding

TeaParty uses itself. The POC project (`projects/POC/`) is tracked by the parent repository rather than having its own `.git`. A `.linked-repo` file signals this arrangement: session worktrees are created from the parent repo, allowing agents to modify the TeaParty codebase directly.

The uber team (`uber-team.json`) coordinates strategy — a project lead delegates to liaison agents, each bridging to a subteam. Subteams (`coding-team.json`, `writing-team.json`, etc.) execute tactical work. Each subteam runs as a separate Claude Code CLI process with its own agent pool and context window. Results flow back through the liaison to the uber team.

```
User Task
  └── Orchestrator
        ├── Intent Phase   → align on what to do
        ├── Planning Phase → uber team plans strategy
        ├── Approval Gate  → human proxy / human review
        └── Execution Phase
              └── uber team
                    ├── coding-liaison → coding-team (lead + workers)
                    ├── writing-liaison → writing-team (lead + workers)
                    ├── art-liaison → art-team (lead + workers)
                    └── ...
```

This is the intended production pattern: the organization defines agent roles at the top level, projects are separate repositories, and the platform orchestrates work across the hierarchy. TeaParty demonstrates this pattern by using it to develop itself.
