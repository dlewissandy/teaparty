# Intent Review: Issue #254

## Step 1: Intent

Issue #254 asks for escalation badge bubbling through the dashboard hierarchy. Each dashboard level needs an escalation count summing all unresolved escalations in its subtree. Badges propagate from task up through job/workgroup/project/management. Visual badge counts appear on each card, and heartbeat status (alive/stale/dead) needs visual indicators at each level.

## Step 2: Diff walk

### `projects/POC/tui/state_reader.py`
- `DispatchState` gains `needs_input` and `heartbeat_status` fields. `_build_dispatch` populates both by checking CFA state against `HUMAN_ACTOR_STATES` and calling `_heartbeat_three_state`. Serves the intent: task-level escalation detection and heartbeat indicators.
- `SessionState` gains `escalation_count` property that sums its own `needs_input` plus all dispatch `needs_input` counts. Gains `heartbeat_status` field populated via `_heartbeat_three_state`. Serves the intent: subtree aggregation.
- `ProjectState.attention_count` now uses `sum(s.escalation_count ...)` which includes dispatch-level escalations. Serves the intent: project-level badge aggregation.
- `_heartbeat_three_state` function implements the three-state (alive/stale/dead) indicator. Serves the intent.

### `projects/POC/tui/navigation.py`
- ESCALATIONS card added to management, project, job, and task levels (workgroup already had it). Serves the intent: escalation visibility at every dashboard level.

### `projects/POC/tui/screens/dashboard_screen.py`
- `_heartbeat_icon` maps alive/stale/dead to distinct colored Unicode symbols. Serves the intent.
- `_build_project_items` shows numeric escalation badge count. Serves the intent: numeric badge, not boolean.
- `_build_escalation_items` collects all escalation items (session + dispatch level) across a subtree. Serves the intent.
- `_refresh_management`, `_refresh_project`, `_refresh_job`, `_refresh_task` all populate ESCALATIONS cards and show escalation counts in stats bars. Serves the intent.
- Heartbeat indicators appear on active sessions and dispatches. Serves the intent.
- Escalation click handler opens chat via `open_chat_window` rather than navigating to a dashboard. Serves the spec.

### `projects/POC/orchestrator/tests/test_issue_254.py`
- 313 lines of tests covering: DispatchState.needs_input, SessionState.escalation_count subtree aggregation, ESCALATIONS card presence at all five levels, project card numeric badge, heartbeat status fields, heartbeat icon distinctness, _build_escalation_items behavior, StateReader._build_dispatch escalation detection. Tests use `unittest.TestCase` with `_make_*()` helpers per project conventions.

### `projects/POC/orchestrator/tests/test_issue_253.py`
- Card count assertions updated to reflect additional ESCALATIONS cards.

## Step 3: Prior findings evaluation

### Finding 1: Task dashboard missing ESCALATIONS card
**RESOLVED.** `navigation.py` lines 211-215 define three cards for TASK level: escalations, artifacts, todo_list. The `_refresh_task` method populates the escalations card with the task's own escalation state. Test `test_task_has_escalations_card` confirms it.

### Finding 2: Escalation badge click should open chat, not navigate to dashboard
**RESOLVED.** The `action_card_click` handler for `escalations` (lines 604-608) calls `open_chat_window(self.app, conversation=conv)` for all escalation clicks at every level. Dispatch-level escalation items carry `session_id` in their data dict, enabling the chat to open to the correct conversation. This matches the spec: "clicking one opens the relevant job or task chat."

### New findings
None. The implementation covers all four requirements from the issue:
1. Subtree escalation counts at each level -- via `escalation_count` property and stats bars.
2. Badge propagation from task to management -- via `_build_escalation_items` and ESCALATIONS cards at all five levels.
3. Visual numeric badge on project cards -- via `_build_project_items`.
4. Heartbeat three-state visual indicators -- via `_heartbeat_three_state` + `_heartbeat_icon`.

The workgroup level has the card defined but data is pending issue #251 (documented prerequisite) -- not a gap in #254's scope.

## Step 4: Recognition test

The person who filed this issue would recognize this diff as a complete implementation. All four stated requirements are addressed with both code and tests. The escalation counts propagate through the hierarchy, numeric badges appear on cards, heartbeat three-state indicators are present, and clicking an escalation opens the chat.

**Verdict: PASS -- both prior findings resolved, no new findings.**
