# Audit Context: Issue #254

## Issue Text

**Title:** Escalation badge bubbling through dashboard hierarchy

**Problem:** The dashboard UI design specifies that escalation badges propagate upward through the hierarchy: a task-level escalation appears as a badge on the job, which bubbles up to the workgroup, project, and management levels. The human sees attention indicators at every level without drilling down. The current TUI shows per-session status icons (needs_input indicator) but does not aggregate or propagate badges. Escalation counts do not bubble up from dispatches to sessions, or from sessions to projects.

**What needs to change:**
- Each dashboard level needs an escalation count that sums all unresolved escalations in its subtree
- Badge propagation: task escalations bubble to job, job to workgroup, workgroup to project, project to management
- Visual indicator (badge count) on each card showing pending attention items
- Heartbeat status (alive/stale/dead) per the design also needs visual indicators at each level

**References:**
- docs/proposals/dashboard-ui/references/heartbeats-and-badges.md
- docs/proposals/dashboard-ui/proposal.md — Key Behaviors section
- #253 — Hierarchical dashboard navigation (prerequisite, closed)

## Design Docs

### heartbeats-and-badges.md (verbatim)

Heartbeat Indicators: Active processes show a liveness indicator with three states:
| State | Threshold | Meaning |
|-------|-----------|---------|
| Alive | Stream-json event within the last 30 seconds | Agent is actively working |
| Stale | No event for 120 seconds | Agent has not reported recently (may be in extended thinking) |
| Dead | Process exit, or no event for 5 minutes | Agent process has ended or is unresponsive |

Extended thinking can produce gaps in stream-json output. A stale indicator during extended thinking is correct behavior.

Heartbeats appear on: sessions (management dashboard), tasks (job and workgroup dashboards).

Escalation Badges: Escalation badges appear on escalation list items across all dashboards. They are pointers into chats; clicking one opens the relevant job or task chat.

Escalations bubble up: a task escalation appears on the task dashboard, the job dashboard, the workgroup dashboard, the project dashboard, and the management dashboard. At each level, clicking it opens the same chat.

### proposal.md — Key Behaviors section

- Chat Windows — One chat per unit of work. Escalations, interventions, and status all flow through the same conversation.
- Heartbeats and Badges — Process liveness indicators (alive/stale/dead). Escalation badges bubble up through the hierarchy.
- Creating Things — "+ New" buttons open office manager chats pre-seeded with intent.
- Agent Configuration View — Read-only modal showing full agent config.

## Diff Summary

5 files changed, 522 insertions(+), 35 deletions(-)

- `projects/POC/orchestrator/tests/test_issue_253.py` — updated card count assertions (29 lines changed)
- `projects/POC/orchestrator/tests/test_issue_254.py` �� new test file (313 lines)
- `projects/POC/tui/navigation.py` — added ESCALATIONS card to management, project, job levels (3 lines)
- `projects/POC/tui/screens/dashboard_screen.py` — new helpers (_heartbeat_icon, _build_project_items, _build_escalation_items), updated refresh methods (146 lines changed)
- `projects/POC/tui/state_reader.py` — added needs_input/heartbeat_status to DispatchState, escalation_count to SessionState, _heartbeat_three_state function (66 lines)
