# TeaParty Management Team

Rules and conventions for management-team agent dispatches.

## Rules

- **Conceptual clarity** ALWAYS.
- **Agents are agents** -- autonomous, not scripted. No prescriptive prompts, no retry loops for tool use.
- **Agent output is never truncated.** Output rules are minimal -- no format constraints, length limits, or plain-text-only directives.
- **Workflows are advisory, not mandatory** -- agents follow them by choice, not enforcement.
- **Tests use `unittest.TestCase`** with `_make_*()` helpers, not pytest fixtures. No `conftest.py`.

## Codebase

Key packages at repo root:

- `orchestrator/` -- CfA engine, actors, session lifecycle
- `bridge/` -- HTML dashboard + bridge server
- `scripts/` -- CfA state machine, proxy model, learning utilities
- `agents/` -- Team and workgroup definitions
- `cfa-state-machine.json` -- State machine definition

Dashboard: `bridge/` (HTML dashboard + bridge server)
Tests: `tests/`
