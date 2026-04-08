# TeaParty

A research platform for durable, scalable agent coordination.

## Quick Start

```bash
uv sync
./teaparty.sh                                                    # HTML dashboard (bridge server, localhost:8081)
uv run python -m teaparty "Your task"                            # CLI session
uv run pytest tests/ --tb=short -q                               # tests
uv run mkdocs serve                                              # docs at localhost:8000
```

## Rules

- **Conceptual clarity** ALWAYS.
- **Agents are agents** -- autonomous, not scripted. No prescriptive prompts, no retry loops for tool use.
- **Agent output is never truncated.** Output rules are minimal -- no format constraints, length limits, or plain-text-only directives.
- **Workflows are advisory, not mandatory** -- agents follow them by choice, not enforcement.
- **Tests use `unittest.TestCase`** with `_make_*()` helpers, not pytest fixtures. No `conftest.py`.

## Codebase

All source code lives under `teaparty/`:

- `teaparty/cfa/` -- CfA protocol engine, actors, session, dispatch, state machine, gates
- `teaparty/proxy/` -- Human proxy system (independent of CfA)
- `teaparty/learning/` -- Hierarchical memory and learning (independent of CfA)
  - `episodic/` -- Session entries, indexing, compaction, reinforcement
  - `procedural/` -- Skill and pattern acquisition
  - `research/` -- PDF extraction, arXiv, Semantic Scholar
- `teaparty/bridge/` -- HTML dashboard + bridge server
  - `state/` -- State reader/writer, heartbeat, dashboard stats, navigation
- `teaparty/mcp/` -- MCP server (config CRUD, escalation, messaging, intervention)
- `teaparty/runners/` -- LLM execution backends (Claude CLI, Ollama, deterministic)
- `teaparty/messaging/` -- Event bus, conversations, routing, IPC
- `teaparty/teams/` -- Multi-turn team coordination (office manager, project lead/manager)
- `teaparty/workspace/` -- Git worktree and job lifecycle
- `teaparty/config/` -- Runtime config loading
- `teaparty/scheduling/` -- Cron execution
- `teaparty/scripts/` -- LLM-powered utility scripts
- `teaparty/util/` -- Shared utilities

Config: `.teaparty/` (agents, workgroups, project settings)
Tests: `tests/`

## Docs

- [docs/overview.md](../docs/overview.md) -- Master conceptual model
- [docs/conceptual-design/cfa-state-machine.md](../docs/conceptual-design/cfa-state-machine.md) -- CfA protocol specification
- [docs/detailed-design/](../docs/detailed-design/index.md) -- Implementation status, gap analysis
- [docs/conceptual-design/learning-system.md](../docs/conceptual-design/learning-system.md) -- Hierarchical memory and learning
- [docs/conceptual-design/human-proxies.md](../docs/conceptual-design/human-proxies.md) -- Human proxy agents
- [docs/conceptual-design/hierarchical-teams.md](../docs/conceptual-design/hierarchical-teams.md) -- Hierarchical agent teams
- [docs/conceptual-design/intent-engineering.md](../docs/conceptual-design/intent-engineering.md) -- Intent capture dialog
