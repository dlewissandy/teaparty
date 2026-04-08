# TeaParty Management Team

Rules and conventions for management-team agent dispatches.

## Rules

- **Conceptual clarity** ALWAYS.
- **Agents are agents** -- autonomous, not scripted. No prescriptive prompts, no retry loops for tool use.
- **Agent output is never truncated.** Output rules are minimal -- no format constraints, length limits, or plain-text-only directives.
- **Workflows are advisory, not mandatory** -- agents follow them by choice, not enforcement.
- **Tests use `unittest.TestCase`** with `_make_*()` helpers, not pytest fixtures. No `conftest.py`.

## Codebase

All source code lives under `teaparty/`:

- `teaparty/cfa/` -- CfA protocol engine, actors, session, dispatch, state machine, gates
- `teaparty/proxy/` -- Human proxy system
- `teaparty/learning/` -- Hierarchical memory and learning
- `teaparty/bridge/` -- HTML dashboard + bridge server
- `teaparty/mcp/` -- MCP server
- `teaparty/runners/` -- LLM execution backends
- `teaparty/messaging/` -- Event bus, conversations, routing
- `teaparty/teams/` -- Multi-turn team coordination
- `teaparty/workspace/` -- Git worktree and job lifecycle
- `teaparty/config/` -- Runtime config loading

Config: `.teaparty/` (agents, workgroups, project settings)
Tests: `tests/`
