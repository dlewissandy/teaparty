# Message Schema

A message carries seven pieces of information:

```
sender:       who sent it (human, proxy, office-manager, project-lead, ...)
conversation: which conversation it belongs to
timestamp:    when
type:         what kind (message, escalation, intervention, system)
content:      text
reply_to:     ID of the message this replies to (null if not a reply)
ack_status:   acknowledgment state of this message (see below)
```

The `type` field distinguishes messages that the system must handle differently. Escalations generate dashboard badges. Interventions trigger CfA reassessment by the lead. System messages carry state transitions and operational events. Normal messages are conversational turns.

## Acknowledgment State

"Awaiting human response" is tracked per-message, not per-conversation. A conversation can have multiple simultaneous outstanding questions (e.g., intent team and planning team both asking), so conversation-level state is insufficient.

`ack_status` tracks the grounding state of each message:

| Value | Meaning |
|-------|---------|
| `na` | Message does not request a reply (default) |
| `pending` | Question posted; awaiting human response |
| `acknowledged` | Human reply received |
| `cancelled` | Question withdrawn without resolution |

When `MessageBusInputProvider` posts a question, it inserts the message with `ack_status = 'pending'`. When a human reply arrives, the reply is inserted and the original question's `ack_status` is updated to `'acknowledged'` in the same transaction. The `reply_to` field on the human reply points at the question message ID.

The bridge queries `WHERE ack_status = 'pending'` to detect conversations needing human input. This is the structural signal for the `input_requested` WebSocket event — no content inspection required.

Each conversation is identified by what it represents: the office manager team, a project session ID, or a dispatch ID. Each has a stable ID tied to the thing it coordinates.
