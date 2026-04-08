# Claude Code Agent Team

This project has a configured team of 8 specialized agents and file-ownership guardrails to prevent conflicts when agents work in parallel.

## Quick Start

```bash
# Restart Claude Code to pick up settings (required after first setup)
claude

# List available agents
/agents

# Delegate to a specific agent
> Review the agent_runtime.py file for security issues
  → routes to code-reviewer

> Add a new /api/organizations/:id/members endpoint
  → routes to backend-engineer

> The conversation list needs a loading spinner
  → routes to ux-designer
```

## The Team

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

## File Ownership Enforcement

A `PreToolUse` hook (`.claude/hooks/enforce-ownership.sh`) runs on every `Edit` and `Write` call. It checks the target file path against the agent's allowed directories and blocks out-of-scope edits with a feedback message.

Example: if `test-engineer` tries to edit `teaparty_app/models.py`, the hook blocks it:
```
BLOCKED: test-engineer can only edit files under tests/. You tried to edit: teaparty_app/models.py
```

The agent receives this feedback and can adjust (e.g., describe the needed change for `backend-engineer` to make).

## Agent Teams (Experimental)

Agent teams allow multiple Claude Code sessions to coordinate with shared task lists and messaging. This is enabled in `.claude/settings.local.json`:

```json
{
  "env": {
    "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS": "1"
  }
}
```

To use agent teams, ask Claude to form a team:
```
> Create a team to implement user authentication.
  Spawn a backend-engineer for the API, a frontend-engineer
  for the login UI, and a test-engineer for coverage.
```

Claude will create tasks, spawn teammates, assign work, and coordinate results.

## Worktrees

Worktrees are created automatically by hierarchical dispatch (`teaparty/cfa/session.py`, `teaparty/workspace/job_store.py`). Each dispatched agent session gets its own worktree and branch for full isolation.

## Typical Workflows

### Single-Agent Delegation

Just describe the task. Claude routes it to the right agent:

```
> Write tests for the engagement sync service
> Make the file browser support drag-and-drop reordering
> Document the admin workspace tool system
```

### Multi-Agent Team

Ask Claude to coordinate a team effort:

```
> I need to add a notifications system. Have the architect design it,
  then the backend-engineer implement the API, the frontend-engineer
  build the UI, and the test-engineer write tests.
```

### Code Review Workflow

```
> Have the code-reviewer check all changes on this branch
> Ask the architect if this refactor aligns with the Phase 0 roadmap
```

## File Layout

```
.claude/
  settings.local.json          # Permissions + agent teams env flag
  hooks/
    enforce-ownership.sh       # PreToolUse hook for file boundaries
  agents/
    architect.md               # System architect (read-only, opus)
    backend-engineer.md        # Python/FastAPI (sonnet)
    code-reviewer.md           # Quality & security (read-only, opus)
    doc-writer.md              # Documentation (haiku)
    frontend-engineer.md       # JS/CSS/HTML (sonnet)
    graphic-artist.md          # SVG & visual assets (sonnet)
    test-engineer.md           # Pytest (sonnet)
    ux-designer.md             # UI/UX design (sonnet)
```
