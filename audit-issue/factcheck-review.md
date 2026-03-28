# Factcheck Review: Issue #254 (Round 2)

## Prior Finding Evaluation

### Finding 1: Task dashboard missing ESCALATIONS card
**Status: RESOLVED**

The task dashboard now defines three cards matching the spec (Escalations, Artifacts, Todo List):
```
DashboardLevel.TASK: [
    CardDef('escalations', 'ESCALATIONS'),
    CardDef('artifacts', 'ARTIFACTS'),
    CardDef('todo_list', 'TODO LIST'),
]
```
(`navigation.py` lines 211-216)

The `_refresh_task` method populates the escalations card with the dispatch's own escalation state (`dashboard_screen.py` lines 512-522). Test coverage exists in `TestEscalationsCardAtAllLevels.test_task_has_escalations_card`.

### Finding 2: Escalation badge click should open chat, not navigate to dashboard
**Status: PARTIALLY RESOLVED**

The `action_card_click` handler for `escalations` now opens a chat window instead of navigating to a dashboard (`dashboard_screen.py` lines 604-608):
```python
elif card_name == 'escalations':
    sid = data.get('session_id', '')
    conv = f'session:{sid}' if sid else ''
    open_chat_window(self.app, conversation=conv)
```

This correctly opens a chat at management and project levels, where `_build_escalation_items` includes `session_id` in the data dict for both session-level and dispatch-level escalation items (lines 149, 165).

**Remaining gap at job level:** In `_refresh_job`, dispatch-level escalation items (`dashboard_screen.py` lines 427-438) use `data={'dispatch': d}` without `session_id`. When clicked, `sid` resolves to `''` and `open_chat_window` opens a generic chat with no conversation context. The session-level escalation item at job level (lines 439-445) does include `session_id` and works correctly. Only dispatch-level escalation items at the job level are missing `session_id`.

### Prior Finding 3: Heartbeat three-state uses heartbeat file mtime, not stream-json event age
**Status: UNCHANGED (still open)**

No changes to `_heartbeat_three_state` in this round. The implementation still uses heartbeat file mtime as the time source rather than stream-json event timestamps. The alive/stale boundary at 120s and the delegation to `is_heartbeat_stale()` for the dead boundary remain the same.

## Summary

| Finding | Status | Severity |
|---------|--------|----------|
| F1: Task dashboard missing ESCALATIONS card | **Resolved** | -- |
| F2: Escalation click opens chat not dashboard | **Partially resolved** | Low -- job-level dispatch escalations open generic chat (missing `session_id` in data dict at `dashboard_screen.py` line 434) |
| F3: Heartbeat thresholds use file mtime not stream-json age | Unchanged | Low -- indirect proxy, not spec-literal |

## Verdict
PARTIAL -- F1 is fully resolved, F2 is substantively fixed but has a remaining edge case at job level, F3 is unchanged.
