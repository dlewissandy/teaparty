# Message Schema

A message carries four pieces of information:

```
sender:       who or what produced it (see sender vocabulary below)
conversation: which conversation it belongs to
timestamp:    when
content:      text
```

`sender` encodes both identity and content kind. The chat UI routes on sender to apply stream filters and render appropriately.

## Sender Vocabulary

| Sender | What it carries |
|--------|----------------|
| `human` | Human input — responses, interventions |
| `office-manager` | OM conversational text response |
| `proxy` | Proxy conversational text response |
| `<agent-role>` | Any agent's conversational text (e.g. `project-lead`) |
| `thinking` | Extended reasoning block from an agent turn |
| `tool_use` | Tool invocation — name and input |
| `tool_result` | Tool return value |
| `system` | Session init, CfA state transitions, operational events |

Escalations and interventions are carried as `human` and `proxy` messages respectively; the `awaiting_input` flag on the conversation (not the message) is the structural signal for escalation state. System messages carry state transitions and operational events.

## Awaiting Input

"Awaiting human response" is tracked per-conversation via the `awaiting_input` flag on the `conversations` table. `MessageBusInputProvider` sets this flag when posting a question and clears it when a human response is received. The bridge queries `conversations WHERE awaiting_input = 1` to detect conversations needing human input — the structural signal for the `input_requested` WebSocket event, requiring no message content inspection.

Each conversation is identified by what it represents: the office manager team, a project session ID, or a dispatch ID. Each has a stable ID tied to the thing it coordinates.
