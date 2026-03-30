# Folder Structure

This document describes TeaParty's directory layout on disk: where packages live, how memory is scoped, how worktrees isolate concurrent work, and how the dogfooding setup works.

---

## Repo Layout

```
teaparty/                               # repo root
├── orchestrator/                       # CfA engine, actors, session lifecycle
│   ├── engine.py                       # CfA state machine execution
│   ├── session.py                      # session lifecycle
│   ├── actors.py                       # actor definitions
│   ├── phase-config.json               # per-phase Claude Code config
│   └── ...
├── bridge/                             # HTML dashboard + bridge server
│   ├── server.py                       # aiohttp bridge server
│   └── ...
├── scripts/                            # CfA state machine, proxy model, learning
│   ├── cfa_state.py                    # state machine operations
│   ├── approval_gate.py                # confidence-based proxy model
│   └── ...
├── agents/                             # team and workgroup definitions
│   ├── uber-team.json
│   ├── coding-team.json
│   └── ...
├── hooks/                              # Claude Code hook scripts
├── tests/                              # all tests (flat, no sub-packages)
├── cfa-state-machine.json              # state machine definition
├── teaparty.sh                         # launcher script
└── ...
```

Projects are discovered from the registry (`~/.teaparty/teaparty.yaml`) — they can live anywhere on disk and are not co-located with the TeaParty codebase. Each project has its own `.teaparty/` config directory and `.sessions/` directory for session history.

---

## Memory Hierarchy

Memory files are scoped to the hierarchy level where the learning occurred. The [promotion chain](../conceptual-design/learning-system.md) moves validated learnings upward:

```
~/.teaparty/MEMORY.md                                          # global scope
<project>/.sessions/MEMORY.md                                  # project scope
<project>/.sessions/<ts>/MEMORY.md                             # session scope
<project>/.sessions/<ts>/<team>/MEMORY.md                      # team scope
<project>/.sessions/<ts>/<team>/<dispatch>/MEMORY.md           # dispatch scope
```

Each scope level also has typed memory stores — `institutional.md` (always loaded) and task-based stores (fuzzy-retrieved). See [Learning System](../conceptual-design/learning-system.md) for the full design.

---

## Git Worktree Isolation

Each session and dispatch runs in an isolated git worktree. This provides:

- **Concurrent sessions** — multiple sessions can modify the codebase simultaneously without conflicts
- **Branch isolation** — each session's changes are on a separate branch until approved and merged
- **Clean rollback** — if a session fails, its worktree is discarded with no impact on the main branch

Completed sessions merge their worktree back into the parent branch.

---

## Dogfooding

TeaParty uses itself. The TeaParty repo is registered in `~/.teaparty/teaparty.yaml` as its own managed project. Session worktrees are created from the repo, allowing agents to modify the TeaParty codebase directly.

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
