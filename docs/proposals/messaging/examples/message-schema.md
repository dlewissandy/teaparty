# Message Schema

A message carries four pieces of information:

```
sender:       who sent it (human, proxy, office-manager, project-lead, ...)
conversation: which conversation it belongs to
timestamp:    when
content:      text
```

That's the entire schema. No message types, no metadata fields, no threading. If we need those later, we add them. For now, messages are text in a conversation from a sender.

Each conversation is identified by what it represents: the office manager team, a project session ID, or a dispatch ID. Each has a stable ID tied to the thing it coordinates.
