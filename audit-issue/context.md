# Audit Context: Issue #255

## Issue Text

**Title:** New-item buttons opening pre-seeded office manager conversations

**Problem:** The dashboard UI design specifies New buttons on various cards (agents, skills, hooks, workgroups, scheduled tasks) that open office manager conversations pre-seeded with the human's intent. For example, clicking New Agent opens an office manager chat with context like "I would like to create a new agent." Creation flows through conversation, not forms.

No implementation exists. The current TUI has a New Session action that opens a launch screen with a text input, but it does not route through the office manager or pre-seed conversations.

**What needs to change:**
- Dashboard cards that support creation need New buttons
- Clicking the button opens an office manager conversation with a pre-seeded message describing the intent
- The office manager routes the request to the appropriate specialist (Configuration Team for agents/skills/hooks, direct dispatch for sessions)

**References:**
- `docs/proposals/dashboard-ui/references/creating-things.md` — Creation flows through conversation
- `docs/proposals/dashboard-ui/proposal.md` — Key Behaviors section
- `docs/proposals/configuration-team/proposal.md` — How Requests Flow
- #201 — Office manager agent
- #253 — Hierarchical dashboard navigation

## Design Docs

### creating-things.md (spec table)

Every dashboard card that represents configurable resources has a "+ New" button. Clicking it opens an office manager chat pre-seeded with the human's intent:

| Card | Pre-seeded message |
|------|--------------------|
| Sessions | (blank — new conversation) |
| Projects | "I would like to create a new project" |
| Agents | "I would like to create a new agent" / "...add a new agent to the POC project" |
| Skills | "I would like to create a new skill" / "...for the Coding workgroup" |
| Scheduled Tasks | "I would like to create a new scheduled task" / "...for the POC Project project" |
| Hooks | "I would like to create a new hook" |
| Jobs | "I would like to create a new job in the POC Project project" |
| Workgroups (management) | "I would like to create a new shared workgroup" |
| Workgroups (project) | "I would like to create a new workgroup in the POC Project project" |

The office manager handles creation through conversation.

### dashboard-ui/proposal.md — Key Behaviors

- **Creating Things** — "+ New" buttons open office manager chats pre-seeded with intent. Creation flows through conversation, not forms.

### configuration-team/proposal.md — Request Triage

Simple requests: office manager routes directly to the appropriate specialist (skills -> Skill Architect, hooks -> Systems Engineer, agents -> Agent Designer). Complex requests: office manager dispatches to Configuration Lead.

## Diff Summary

4 files changed, 347 insertions(+), 6 deletions(-)

- `projects/POC/orchestrator/tests/test_issue_255.py` (new, 263 lines) — 22 tests
- `projects/POC/tui/chat_main.py` — +12/-2: `--pre-seed` CLI arg, `ChatApp(pre_seed=...)`, pass to `ChatScreen`
- `projects/POC/tui/screens/chat.py` — +9/-1: `ChatScreen(pre_seed=...)`, auto-send on mount
- `projects/POC/tui/screens/dashboard_screen.py` — +69/-3: `pre_seeded_message()`, updated `action_card_new()`, updated `open_chat_window(pre_seed=...)`
