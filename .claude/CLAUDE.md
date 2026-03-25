# TeaParty

A research platform for durable, scalable agent coordination.

## Quick Start

```bash
uv sync
./teaparty.sh                                                    # TUI dashboard
uv run python -m projects.POC.orchestrator "Your task"           # CLI session
uv run pytest projects/POC/orchestrator/tests/ --tb=short -q     # tests
uv run mkdocs serve                                              # docs at localhost:8000
```

## Rules

- **Conceptual clarity** ALWAYS.
- **Agents are agents** -- autonomous, not scripted. No prescriptive prompts, no retry loops for tool use.
- **Agent output is never truncated.** Output rules are minimal -- no format constraints, length limits, or plain-text-only directives.
- **Workflows are advisory, not mandatory** -- agents follow them by choice, not enforcement.
- **Tests use `unittest.TestCase`** with `_make_*()` helpers, not pytest fixtures. No `conftest.py`.

## Codebase

The active code is the POC orchestrator at `projects/POC/orchestrator/`. Key files:

- `session.py` -- Session lifecycle, worktree creation, phase orchestration
- `engine.py` -- CfA state machine execution, approval gates
- `actors.py` -- Actor definitions (human, proxy, intent team, uber team)
- `claude_runner.py` -- Claude Code CLI integration, stream-json parsing
- `dispatch_cli.py` -- Hierarchical dispatch to subteams via worktrees
- `learnings.py` -- Post-session learning extraction
- `phase_config.py` -- Per-phase Claude Code configuration

TUI: `projects/POC/tui/`
Tests: `projects/POC/orchestrator/tests/`

## Docs

- [docs/overview.md](../docs/overview.md) -- Master conceptual model
- [docs/conceptual-design/cfa-state-machine.md](../docs/conceptual-design/cfa-state-machine.md) -- CfA protocol specification
- [docs/detailed-design/](../docs/detailed-design/index.md) -- Implementation status, gap analysis
- [docs/conceptual-design/learning-system.md](../docs/conceptual-design/learning-system.md) -- Hierarchical memory and learning
- [docs/conceptual-design/human-proxies.md](../docs/conceptual-design/human-proxies.md) -- Human proxy agents
- [docs/conceptual-design/hierarchical-teams.md](../docs/conceptual-design/hierarchical-teams.md) -- Hierarchical agent teams
- [docs/conceptual-design/intent-engineering.md](../docs/conceptual-design/intent-engineering.md) -- Intent capture dialog
