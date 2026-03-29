# Message Schema

A message carries five pieces of information:

```
sender:       who sent it (human, proxy, office-manager, project-lead, ...)
conversation: which conversation it belongs to
timestamp:    when
type:         what kind (message, escalation, intervention, system)
content:      text
```

The `type` field distinguishes messages that the system must handle differently. Escalations generate dashboard badges. Interventions trigger CfA reassessment by the lead. System messages carry state transitions and operational events. Normal messages are conversational turns.

## Awaiting Input

"Awaiting human response" is tracked per-conversation via the `awaiting_input` flag on the `conversations` table. `MessageBusInputProvider` sets this flag when posting a question and clears it when a human response is received. The bridge queries `conversations WHERE awaiting_input = 1` to detect conversations needing human input — the structural signal for the `input_requested` WebSocket event, requiring no message content inspection.

Each conversation is identified by what it represents: the office manager team, a project session ID, or a dispatch ID. Each has a stable ID tied to the thing it coordinates.
