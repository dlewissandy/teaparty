# Heartbeat Indicators and Escalation Badges

## Heartbeat Indicators

Active processes show a liveness indicator with three states:

| State | Threshold | Meaning |
|-------|-----------|---------|
| Alive | Stream-json event within the last 30 seconds | Agent is actively working |
| Stale | No event for 120 seconds | Agent has not reported recently (may be in extended thinking) |
| Dead | Process exit, or no event for 5 minutes | Agent process has ended or is unresponsive |

Extended thinking can produce gaps in stream-json output. A stale indicator during extended thinking is correct behavior: the agent is not producing output, and the user should see that state. The indicator will return to alive when the thinking completes and output resumes.

These thresholds are defaults. The existing `claude_runner.py` already uses similar values (30s heartbeat interval, 120s stale threshold, 300s kill threshold).

Heartbeats appear on: sessions (management dashboard), tasks (job and workgroup dashboards).

## Escalation Badges

Escalation badges appear on escalation list items across all dashboards. They are pointers into chats; clicking one opens the relevant job or task chat.

Escalations bubble up: a task escalation appears on the task dashboard, the job dashboard, the workgroup dashboard, the project dashboard, and the management dashboard. At each level, clicking it opens the same chat.
