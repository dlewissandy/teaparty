# TeaParty - CLAUDE.md

## What This Is

TeaParty is a platform where multidisciplinary teams of humans and AI agents co-author files and collaborate in chat. It has workgroups, organizations, engagements, workflows, and a tool system for agents.

## Quick Start

```bash
uv sync                                              # Install dependencies
cp .env.example .env                                 # Configure environment
uv run uvicorn teaparty_app.main:app --reload        # Run the app (localhost:8000)
PYTHONPATH=. uv run pytest tests/ --tb=short -q      # Run all tests
PYTHONPATH=. uv run pytest tests/test_workflows.py -v # Run single test file
```

## Architecture

**Backend:** FastAPI monolith with SQLModel/SQLite (WAL mode), served by uvicorn.

**Frontend:** Vanilla JS single-page app (`web/app.js`, `web/styles.css`, `web/index.html`). No framework, no build tools.   AS DELIGHTFUL AS POSSIBLE.

**Agent Runtime:** Agents respond to messages via `claude -p` subprocess calls. The runtime in `agent_runtime.py` determines who speaks (via `turn_policy.py`), builds prompts (via `prompt_builder.py`), invokes Claude CLI (via `claude_runner.py`), and tracks activity.

**LLM Client:** `llm_client.py` abstracts Anthropic SDK + LiteLLM. All LLM calls go through `llm_client.create_message()` -- never call the SDK directly. Model resolution via `resolve_model(purpose, explicit)` where purpose is `"reply"`, `"cheap"`, or `"admin"`.

**Admin Workspace:** Package at `services/admin_workspace/` with submodules for bootstrap, parsing, tools, SDK integration, and global tools.

## Project Structure

```
teaparty_app/
  main.py              # FastAPI app factory, router mounting, static files
  config.py            # Pydantic Settings (TEAPARTY_ env prefix, .env file)
  models.py            # SQLModel table definitions
  schemas.py           # Pydantic request/response schemas
  db.py                # Engine setup, init_db(), lightweight migrations, seeds
  deps.py              # FastAPI dependency injection (session, current user)
  routers/             # API route handlers
    auth.py, workgroups.py, conversations.py, agents.py, tools.py,
    tasks.py, engagements.py, workspace.py, organizations.py, system.py
  services/            # Business logic layer
    agent_runtime.py   # Agent auto-response, follow-ups, activity tracking
    agent_tools.py     # Tool schemas and dispatch for agent-facing tools
    admin_workspace/   # Admin agent: bootstrap, parsing, tools, SDK integration
    llm_client.py      # Anthropic + LiteLLM abstraction
    claude_runner.py   # Async subprocess wrapper for `claude -p`
    prompt_builder.py  # System prompt and user message construction
    turn_policy.py     # Workflow-driven turn management (who speaks next)
    tools.py           # Tool registry, file operations
    claude_code.py     # Multi-turn coding assistant with file tools
    agent_learning.py  # Learning signal extraction, state updates
    activity.py        # Activity feed and event tracking
    permissions.py     # Permission checks
    llm_usage.py       # LLM usage tracking
    custom_tool_executor.py  # Custom tool execution
    engagement_sync.py # Engagement message sync
    workgroup_templates.py   # Template application
    workspace_manager.py     # Workspace file management
  seeds/               # Template YAML files and seed runner
    templates/         # coding.yaml, dialectic.yaml, roleplay.yaml
web/                   # Frontend SPA
  index.html, app.js, styles.css
tests/                 # All tests (28 files, ~6700 lines)
docs/                  # Design documents
  file-layout.md, workflows.md, engagements.md,
  sandbox-design.md, next-speaker-selection.md
```

## Code Conventions
- **Conceptual Clarity** ALWAYS!  
- **IDs:** UUID strings via `new_id()` factory
- **Timestamps:** `utc_now()` returning timezone-aware datetime
- **Database:** SQLite with WAL mode; `commit_with_retry()` for busy handling
- **Imports:** Most service files use `from __future__ import annotations`
- **Migrations:** Lightweight migration pattern in `db.py` (`_run_lightweight_migrations`)
- **Config:** Pydantic Settings with `TEAPARTY_` env prefix; loads from `.env`
- **Dependencies:** Managed with `uv` (see `pyproject.toml` and `uv.lock`)
- **SERVER_SIDE_TOOLS:** Set that excludes `web_search` from `_select_tool()` by design
- **`web_search`** is server-side (`web_search_20250305`) -- handled by Anthropic API internally

## Testing Conventions

- **Framework:** pytest as the runner, but tests use `unittest.TestCase` classes
- **No pytest fixtures.** Helper functions like `_make_agent()`, `_make_conversation()`, `_make_message()` create test objects
- **No conftest.py.** This is intentional -- do not introduce one
- **Database:** In-memory SQLite (`sqlite:///:memory:`) for test isolation
- **LLM mocking:** Always patch `teaparty_app.services.llm_client.create_message`
- **Mock responses:** Use `MagicMock` matching Anthropic SDK shape (`content=[MagicMock(text="...")]`, `usage=MagicMock(input_tokens=N, output_tokens=N)`)
- **Test models:** Constructed directly: `Agent(id="a1", workgroup_id="wg-1", ...)`
- **Async tests:** Use `unittest.IsolatedAsyncioTestCase` with `AsyncMock`
- **Session mocking:** `MagicMock()` for the session, with `.exec()`, `.get()`, `.add()` mocked

## Design Philosophy

- **Agents should be agents** -- autonomous, not scripted with prescriptive prompts or retry loops
- **Don't over-engineer:** No `MANDATORY`/`CRITICAL` prompt instructions, no retry loops for tool use
- **Agent output should not be truncated** -- preserve full responses
- **Output rules should be minimal** -- no format constraints, length rules, or plain-text-only directives
- **Workflows are advisory, not mandatory** -- agents follow them by choice, not enforcement

## Key Design Documents

- `ROADMAP.md` -- Phased plan (Foundation Hardening through Governance)
- `TASKLIST.md` -- Detailed task breakdown with acceptance criteria
- `TOOL_GAPS.md` -- Identified gaps in agent tool capabilities
- `docs/file-layout.md` -- Virtual file tree design
- `docs/workflows.md` -- Workflow system specification
- `docs/engagements.md` -- Cross-organization engagement model
- `docs/sandbox-design.md` -- Docker sandbox architecture
- `docs/next-speaker-selection.md` -- Agent turn-order selection algorithm
- `docs/SocialArchitecture.md` -- Social interaction design (maintained by social-architect)
- `docs/CognitiveArchitecture.md` -- Cognition and learning design (maintained by cognitive-architect)
- `docs/research/INDEX.md` -- Research library catalog (maintained by researcher)

## Agent Team

| Agent | Model | Edits | Scope |
|-------|-------|-------|-------|
| `backend-engineer` | sonnet | `teaparty_app/` | FastAPI routes, services, models, DB, LLM client |
| `frontend-engineer` | sonnet | `web/` | Vanilla JS SPA, DOM, API calls, polling |
| `test-engineer` | sonnet | `tests/` | Pytest tests, coverage, test debugging |
| `ux-designer` | sonnet | `web/` | Layout, interactions, accessibility, polish |
| `graphic-artist` | sonnet | `web/` | SVG icons, illustrations, logos, CSS graphics |
| `doc-writer` | haiku | `docs/`, `*.md` | Documentation, README, ROADMAP, docstrings |
| `code-reviewer` | opus | read-only | Code quality, security, conventions |
| `architect` | opus | read-only | Design decisions, roadmap alignment, trade-offs |
| `social-architect` | opus | `docs/` | Social interaction design, communication patterns, group dynamics |
| `cognitive-architect` | opus | `docs/` | Cognition, learning systems, memory architecture, preference modeling |
| `researcher` | sonnet | `docs/research/` | Peer-reviewed literature, research library, evidence-based design |

File ownership enforced by `.claude/hooks/enforce-ownership.sh` (PreToolUse hook on Edit/Write).
