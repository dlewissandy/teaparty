# Folder Structure

This document describes the POC's actual directory layout on disk: where projects live, how memory is scoped, how worktrees isolate concurrent work, and how the dogfooding setup works.

---

## POC Directory Layout

```
projects/
├── MEMORY.md                           # global learnings (cross-project)
├── POC/                                # proof-of-concept (uses parent repo)
│   ├── agents/                         # team definitions
│   │   ├── uber-team.json              # strategic coordination team
│   │   ├── coding-team.json            # coding subteam
│   │   ├── writing-team.json           # writing subteam
│   │   ├── art-team.json               # art subteam
│   │   ├── research-team.json          # research subteam
│   │   ├── editorial-team.json         # editorial subteam
│   │   ├── intent-team.json            # intent gathering team
│   │   └── project-team.json           # project-level liaison team
│   ├── orchestrator/                   # CfA engine, actors, session lifecycle
│   ├── scripts/                        # CfA state machine, proxy model, learning
│   ├── tui/                            # terminal UI dashboard
│   ├── docs/                           # project-specific documentation
│   ├── .sessions/                      # session history
│   │   └── <timestamp>/                # one directory per session
│   │       ├── MEMORY.md               # session-level learnings
│   │       └── <team>/                 # team-level state
│   │           └── MEMORY.md           # team-level learnings
│   ├── .worktrees/                     # git worktrees for session isolation
│   ├── cfa-state-machine.json          # state machine definition
│   └── MEMORY.md                       # project-level learnings
├── hierarchical-memory-paper/          # research paper (separate git repo)
├── agentic-cfa-publication/            # research paper (separate git repo)
└── ...
```

Each project in `projects/` is a separate git repository with its own history, branches, and deliverables. The root `.gitignore` excludes project contents by default (`projects/*`) since each project manages its own git history. The POC is the exception — it is explicitly tracked by the parent repository for dogfooding (see below).

---

## Memory Hierarchy

Memory files are scoped to the hierarchy level where the learning occurred. The [promotion chain](learning-system.md) moves validated learnings upward:

```
projects/MEMORY.md                                          # global scope
projects/<project>/MEMORY.md                                # project scope
projects/<project>/.sessions/<ts>/MEMORY.md                 # session scope
projects/<project>/.sessions/<ts>/<team>/MEMORY.md          # team scope
projects/<project>/.sessions/<ts>/<team>/<dispatch>/MEMORY.md  # dispatch scope
```

Each scope level also has typed memory stores — `institutional.md` (always loaded) and task-based stores (fuzzy-retrieved). See [Learning System](learning-system.md) for the full design.

---

## Git Worktree Isolation

Each session and dispatch runs in an isolated git worktree. This provides:

- **Concurrent sessions** — multiple sessions can modify the codebase simultaneously without conflicts
- **Branch isolation** — each session's changes are on a separate branch until approved and merged
- **Clean rollback** — if a session fails, its worktree is discarded with no impact on the main branch

Completed sessions merge their worktree back into the parent branch.

---

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
                    ├── coding-liaison   → coding-team (lead + workers)
                    ├── writing-liaison  → writing-team (lead + workers)
                    ├── art-liaison      → art-team (lead + workers)
                    └── ...
```

---

For the platform's virtual file tree (workgroups, engagements, scoped files), see [File Layout](file-layout.md).
