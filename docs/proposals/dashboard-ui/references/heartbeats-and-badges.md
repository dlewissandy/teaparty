# Heartbeat Indicators and Escalation Badges

## Heartbeat Indicators

Active processes show a liveness indicator with three states:

| State | Threshold | Meaning |
|-------|-----------|---------|
| Alive | Heartbeat mtime within the last 30 seconds | Agent is actively working |
| Stale | Heartbeat mtime older than 30 seconds | Agent has not reported recently (may be in extended thinking) |
| Dead | Process exit, or heartbeat mtime older than 5 minutes | Agent process has ended or is unresponsive |

The heartbeat file (`heartbeat.py`) is touched every 30 seconds (`BEAT_INTERVAL`) by `claude_runner.py`. Extended thinking can produce gaps in heartbeat touches. A stale indicator during extended thinking is correct behavior: the agent is not producing output, and the user should see that state. The indicator will return to alive when the thinking completes and heartbeat touches resume.

These thresholds align with `claude_runner.py` constants: `BEAT_INTERVAL = 30`, `STALE_THRESHOLD = 120`.

Heartbeats appear on: sessions (management dashboard), tasks (job and workgroup dashboards).

## Escalation Badges

Escalation badges appear on escalation list items across all dashboards. They are pointers into chats; clicking one opens the relevant job or task chat.

Escalations bubble up: a task escalation appears on the task dashboard, the job dashboard, the workgroup dashboard, the project dashboard, and the management dashboard. At each level, clicking it opens the same chat.
