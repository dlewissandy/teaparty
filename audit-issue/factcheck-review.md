# Factcheck Review: Issue #254

## Scope
Design docs checked:
- `docs/proposals/dashboard-ui/references/heartbeats-and-badges.md` — heartbeat three-state spec, escalation badge bubbling spec
- `docs/proposals/dashboard-ui/proposal.md` — Key Behaviors section
- `docs/proposals/dashboard-ui/references/management-dashboard.md` — management-level cards and stats
- `docs/proposals/dashboard-ui/references/project-dashboard.md` — project-level cards
- `docs/proposals/dashboard-ui/references/job-dashboard.md` — job-level cards and stats
- `docs/proposals/dashboard-ui/references/task-dashboard.md` — task-level cards
- `docs/proposals/dashboard-ui/references/workgroup-dashboard.md` — workgroup-level cards

Changed files checked:
- `projects/POC/tui/state_reader.py` — DispatchState, SessionState, `_heartbeat_three_state`, `escalation_count`
- `projects/POC/tui/screens/dashboard_screen.py` — `_heartbeat_icon`, `_build_project_items`, `_build_escalation_items`, refresh methods
- `projects/POC/tui/navigation.py` — ESCALATIONS card definitions per level
- `projects/POC/orchestrator/tests/test_issue_254.py` — test file
- `projects/POC/orchestrator/tests/test_issue_253.py` — updated card count assertions

## New Findings

### 1. Task dashboard missing ESCALATIONS card
**Severity:** medium
**Code location:** `projects/POC/tui/navigation.py:211-215` (`_CARD_DEFS[DashboardLevel.TASK]`)
**Doc location:** `docs/proposals/dashboard-ui/references/task-dashboard.md:Content Cards`
**Doc says:** The task dashboard has three content cards: Escalations, Artifacts, and Todo List. The Escalations card shows "Pending escalations for this task" and opens the task's chat.
**Code does:** `_CARD_DEFS[DashboardLevel.TASK]` only defines two cards: `artifacts` and `todo_list`. No `escalations` card.
**Gap:** The task dashboard spec explicitly includes an Escalations card. The diff adds ESCALATIONS to management, project, and job levels but omits it from the task level. Since a task can itself be in an escalation state (needs_input), the spec expects that to be visible as an escalation item on the task dashboard.

### 2. Escalation badge click does not always open the relevant chat
**Severity:** medium
**Code location:** `projects/POC/tui/screens/dashboard_screen.py:592-601` (`action_card_click`, `escalations` branch)
**Doc location:** `docs/proposals/dashboard-ui/references/heartbeats-and-badges.md:Escalation Badges`
**Doc says:** "Escalations bubble up: a task escalation appears on the task dashboard, the job dashboard, the workgroup dashboard, the project dashboard, and the management dashboard. At each level, clicking it opens the same chat."
**Code does:** When clicking an escalation item that has a `dispatch` in its data, the code navigates to the task dashboard (`drill_down(DashboardLevel.TASK)`). When clicking an escalation without a dispatch, it opens a chat window. The spec says clicking an escalation at ANY level should open the relevant chat, not navigate to a different dashboard level.
**Gap:** Dispatch-level escalation clicks navigate to the task dashboard instead of opening the task's chat. The design doc says clicking an escalation is always a pointer into a chat, not a navigation action.

### 3. Heartbeat three-state uses heartbeat file mtime, not stream-json event age
**Severity:** medium
**Code location:** `projects/POC/tui/state_reader.py:109-139` (`_heartbeat_three_state`)
**Doc location:** `docs/proposals/dashboard-ui/references/heartbeats-and-badges.md:Heartbeat Indicators`
**Doc says:** The three states are defined by "Stream-json event" timing: alive = "within the last 30 seconds", stale = "No event for 120 seconds", dead = "no event for 5 minutes".
**Code does:** Uses `.heartbeat` file mtime as the time source, not stream-json event timestamps. The stale threshold checks `age > 120` on the heartbeat file mtime, and dead is determined by `is_heartbeat_stale` from heartbeat.py.
**Gap:** The spec explicitly defines thresholds relative to "stream-json event" timing. The heartbeat file mtime is a proxy (it gets updated when heartbeat writes occur), but the mapping is indirect. The stale-to-dead boundary is also unclear: the code delegates to `is_heartbeat_stale()` for the dead determination, but that function's threshold may not be 300 seconds. If `is_heartbeat_stale` uses a different threshold than 5 minutes, the dead state won't match the spec. This is an ambiguity -- the implementation may be correct if `is_heartbeat_stale` uses the 300s threshold, but the layering obscures verification.

## Verified Consistent

- **Escalation subtree aggregation:** `SessionState.escalation_count` correctly sums session-level `needs_input` (1 if true, 0 if false) plus all dispatch-level `needs_input` counts. This matches the spec requirement that "escalation counts bubble up from dispatches to sessions."
- **Project attention count includes dispatches:** `StateReader.reload()` computes `attention_count` as `sum(s.escalation_count for s in proj_sessions)`, which includes dispatch-level escalations via the `escalation_count` property. This matches the issue requirement.
- **ESCALATIONS card at management, project, workgroup, and job levels:** `navigation.py` defines an `escalations` CardDef at all four levels. The management, project, workgroup, and job dashboard reference docs all list an Escalations card.
- **Numeric badge count on project cards:** `_build_project_items` sums `escalation_count` across sessions and displays the total as a numeric count in the card detail text. This replaces the prior boolean indicator with a count, matching the issue requirement.
- **Heartbeat three-state exposed on both sessions and dispatches:** `DispatchState.heartbeat_status` and `SessionState.heartbeat_status` both carry the alive/stale/dead string. `_build_dispatch` and `_build_session` both call `_heartbeat_three_state`. This matches the spec that "Heartbeats appear on: sessions (management dashboard), tasks (job and workgroup dashboards)."
- **Heartbeat visual indicators are distinct per state:** `_heartbeat_icon` returns green filled circle for alive, yellow open circle for stale, and dim bullet for dead. Three visually distinct indicators.
- **Dispatch-level escalation detection:** `_build_dispatch` checks `cfa_state in HUMAN_ACTOR_STATES` and `.input-request.json` existence to set `needs_input`, using the same logic as session-level escalation detection.
- **Escalation items built for ESCALATIONS cards:** `_build_escalation_items` iterates sessions and their dispatches, creating clickable items for each escalation. Items include both session-level and dispatch-level escalations.
- **Job-level stats include escalation count:** `_refresh_job` displays `session.escalation_count` in the stats bar, matching the job-dashboard.md spec which lists "Escalations: Number of escalations in this job."

## Verdict
PARTIAL

Unmet spec requirements:
1. Task dashboard is missing its ESCALATIONS card (task-dashboard.md specifies it).
2. Escalation click behavior at management/project levels navigates to task dashboard for dispatch escalations instead of opening the chat, contradicting the spec that says clicking an escalation always opens the relevant chat.
3. Heartbeat three-state thresholds are indirectly implemented through heartbeat file mtime rather than stream-json event age; the dead threshold depends on `is_heartbeat_stale()` whose threshold is not verified to be 300 seconds in this diff.
