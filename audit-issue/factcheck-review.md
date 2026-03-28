# Factcheck Review: Issue #255

## Scope

Design docs checked:
- `docs/proposals/dashboard-ui/references/creating-things.md` -- spec table of pre-seeded messages per card type
- `docs/proposals/dashboard-ui/proposal.md` -- Key Behaviors section ("Creating Things")
- `docs/proposals/configuration-team/proposal.md` -- Request Triage section (routing rules)

Changed files checked:
- `projects/POC/tui/screens/dashboard_screen.py` -- `pre_seeded_message()`, `action_card_new()`, `open_chat_window()`
- `projects/POC/tui/screens/chat.py` -- `ChatScreen(pre_seed=...)`, auto-send on mount
- `projects/POC/tui/chat_main.py` -- `--pre-seed` CLI arg, `ChatApp(pre_seed=...)`
- `projects/POC/tui/navigation.py` -- `CardDef.new_button` flags (pre-existing, verified)
- `projects/POC/orchestrator/tests/test_issue_255.py` -- 22 tests

## New Findings

### 1. Projects card bypasses office manager, contradicting spec
**Severity:** medium
**Code location:** `dashboard_screen.py:_NON_PRESEED_CARDS` (line 104) and `action_card_new` (line 580)
**Doc location:** `creating-things.md:spec table`
**Doc says:** Projects card opens an office manager chat pre-seeded with "I would like to create a new project". The spec preamble states: "Every dashboard card that represents configurable resources has a '+ New' button. Clicking it opens an office manager chat pre-seeded with the human's intent."
**Code does:** Projects is in `_NON_PRESEED_CARDS`, so `action_card_new('projects')` routes to `NewProjectScreen` -- a dedicated form screen, not an office manager conversation.
**Gap:** The spec explicitly lists a pre-seeded message for Projects. The code routes to a different screen entirely, bypassing the office manager conversation model. If the intent is to keep the existing `NewProjectScreen`, the design doc should be updated to reflect that exception.

### 2. Sessions card interpretation is ambiguous but defensible
**Severity:** medium
**Code location:** `dashboard_screen.py:_NON_PRESEED_CARDS` (line 104) and `action_card_new` (line 578)
**Doc location:** `creating-things.md:spec table`
**Doc says:** Sessions card has `(blank -- new conversation)` as the pre-seeded message.
**Code does:** Sessions is in `_NON_PRESEED_CARDS`, routing to `action_new_session()` which pushes `LaunchScreen`.
**Gap:** The spec says the button "opens an office manager chat" with a blank pre-seed. The code opens a `LaunchScreen` instead. The parenthetical "(blank -- new conversation)" is ambiguous -- it could mean "open a new session" (which `LaunchScreen` does) or "open an office manager chat with no pre-seed" (which is what the preamble implies). If the intent is `LaunchScreen`, the doc should clarify this as an exception to the office-manager pattern.

## Verified Consistent

- **Management-level generic messages:** All six card types (agents, skills, hooks, scheduled_tasks, workgroups, jobs) produce messages matching the spec table exactly.
- **Project-scoped messages:** When `nav.project_slug` is set and level is `PROJECT`, messages include the project name using the spec's phrasing (e.g., "I would like to add a new agent to the {project} project").
- **Workgroup-scoped messages:** When `nav.workgroup_id` is set and level is `WORKGROUP`, agents and skills use workgroup-specific templates matching the spec (e.g., "...for the {workgroup} workgroup").
- **Scoping fallback:** Workgroup-level cards without workgroup-specific templates fall back to project-scoped messages, then to generic. This is consistent with the spec's intent of providing the most specific context available.
- **Office manager conversation routing:** `action_card_new` routes non-session/non-project cards to `open_chat_window(app, conversation='om:new', pre_seed=msg)`, which opens an office manager conversation. The `'om'` prefix maps to `ConversationType.OFFICE_MANAGER` in `ChatScreen._ensure_conversation`.
- **Pre-seed auto-send:** `ChatScreen.on_mount` sends the pre-seed message into the selected conversation via `self._model.send_message()` and clears it to prevent re-sending. This implements "pre-seeded with the human's intent" from the spec.
- **CLI plumbing:** `--pre-seed` flows through `chat_main.py` argparse to `ChatApp(pre_seed=...)` to `ChatScreen(pre_seed=...)`. The chain is complete.
- **Card new_button flags:** All card types listed in the spec table have `new_button=True` in `navigation.py` at the appropriate dashboard levels.
- **Workgroup-level cards with new_button:** Management (sessions, projects, workgroups, agents, skills, scheduled_tasks, hooks), Project (sessions, jobs, workgroups, agents, skills, scheduled_tasks, hooks), and Workgroup (sessions, agents, skills) levels all have appropriate `new_button` flags.

## Verdict

PARTIAL

The core implementation -- pre-seeded messages, office manager routing, CLI plumbing, and auto-send -- is correct and consistent with the design docs. Two card types (Projects and Sessions) deviate from the spec's stated model of "every card opens an office manager chat." The Projects deviation is clearly a gap (the spec lists a specific pre-seeded message that the code ignores). The Sessions deviation is ambiguous. Both should either be aligned with the spec or the spec should be updated to document these as intentional exceptions.
