# TeaParty

A platform where teams of humans and AI agents co-author files and collaborate in chat.

## Quick Start

```bash
uv sync && cp .env.example .env
uv run uvicorn teaparty_app.main:app --reload
PYTHONPATH=. uv run pytest tests/ --tb=short -q
```

## Rules

- **Conceptual clarity** ALWAYS.
- **Frontend should be AS DELIGHTFUL AS POSSIBLE.** Vanilla JS, no framework, no build tools.
- **All LLM calls go through `llm_client.create_message()`** -- never call the Anthropic SDK directly.
- **Agents are agents** -- autonomous, not scripted. No prescriptive prompts, no retry loops for tool use.
- **Agent output is never truncated.** Output rules are minimal -- no format constraints, length limits, or plain-text-only directives.
- **Workflows are advisory, not mandatory** -- agents follow them by choice, not enforcement.
- **Tests use `unittest.TestCase`** with `_make_*()` helpers, not pytest fixtures. No `conftest.py`.
- **Mock LLM calls** by patching `teaparty_app.services.llm_client.create_message`.
- **DB migrations** use the lightweight pattern in `db.py`, not Alembic.

## Docs

- [ROADMAP.md](../../ROADMAP.md) -- Phased plan
- [TASKLIST.md](../../TASKLIST.md) -- Task breakdown
- [TOOL_GAPS.md](../../TOOL_GAPS.md) -- Agent tool capability gaps
- [docs/file-layout.md](../../docs/file-layout.md) -- Virtual file tree
- [docs/workflows.md](../../docs/workflows.md) -- Workflow system
- [docs/engagements.md](../../docs/engagements.md) -- Cross-org engagement model
- [docs/sandbox-design.md](../../docs/sandbox-design.md) -- Docker sandbox architecture
- [docs/next-speaker-selection.md](../../docs/next-speaker-selection.md) -- Turn-order selection
