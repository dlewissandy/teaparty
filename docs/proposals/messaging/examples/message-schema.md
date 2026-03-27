# Message Schema

A message carries five pieces of information:

```
sender:       who sent it (human, proxy, office-manager, project-lead, ...)
conversation: which conversation it belongs to
timestamp:    when
type:         what kind (message, escalation, intervention, system)
content:      text
```

The `type` field distinguishes messages that the system must handle differently. Escalations generate dashboard badges and await human response. Interventions trigger CfA reassessment by the lead. System messages carry state transitions and operational events. Normal messages are conversational turns.

Each conversation is identified by what it represents: the office manager team, a project session ID, or a dispatch ID. Each has a stable ID tied to the thing it coordinates.
