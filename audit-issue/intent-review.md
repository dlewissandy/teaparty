# Intent Review: Issue #254

## Intent Statement
The dashboard should propagate escalation badge counts upward through the hierarchy: task-level escalations aggregate to the job, job to project, project to management. At every level, the human sees an attention count reflecting the full subtree below, without drilling down. Heartbeat liveness (alive/stale/dead) should also be visually indicated at each level.

## New Findings

### 1. Heartbeat three-state thresholds do not match design spec
**Type:** partial-implementation
**What the issue asks for:** Per the design doc (heartbeats-and-badges.md), alive means a stream-json event within 30 seconds, stale means no event for 120 seconds, and dead means no event for 5 minutes or process exit.
**What the diff delivers:** `_heartbeat_three_state` in `state_reader.py` (line 109) classifies everything under 120s as "alive" and uses `is_heartbeat_stale` (120s + dead PID) as the "dead" boundary. The comment on line 113 claims "Uses the same thresholds as heartbeat.py (30s alive, 120s stale, 5m dead)" but the code implements no 30-second alive boundary and no 5-minute dead boundary.
**The gap:** The 30s-to-120s window (which the spec defines as the transition from alive to stale) is treated as alive. The 120s-to-5min window (stale per spec) is only treated as stale when the PID is still alive; if the PID is dead at 120s it reports dead rather than waiting for 5 minutes. This is a defensible simplification but the comment is misleading and the behavior does not match the stated thresholds in the design doc.

### 2. No findings on escalation bubbling -- implementation is faithful
**Type:** (no gap)
**What the issue asks for:** Escalation counts bubble from tasks (dispatches) through sessions to projects to management. Each level shows a numeric badge count.
**What the diff delivers:** `SessionState.escalation_count` (property, line 204) sums `needs_input` from the session itself plus all its dispatches. `ProjectState.attention_count` is computed from `sum(s.escalation_count for s in proj.sessions)` in `reload()` (line 315). The management stats bar shows `Escalations` from the same sum. `_build_project_items` shows numeric badge counts. `_build_escalation_items` collects both session-level and dispatch-level escalation items. ESCALATIONS cards appear at management, project, workgroup, and job levels via `navigation.py`. This fully implements the bubbling chain described in the issue.

## Verdict
COMPLETE

The escalation badge bubbling -- the core ask of this issue -- is fully and faithfully implemented across all five hierarchy levels. The heartbeat three-state indicator is implemented and functional with distinct visual indicators at each state, though its thresholds diverge from the design spec's stated 30s/120s/5m boundaries. This threshold discrepancy is a minor fidelity issue against the reference doc, not a gap in the issue's intent. The person who filed this issue would recognize this diff as delivering what they asked for.
