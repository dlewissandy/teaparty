# Conversation Identity and Persistence

Each conversation pattern has a distinct stable identity tied to what it represents and how long it persists.

| Pattern | Identity | Persistence |
|---------|----------|-------------|
| Office manager | Session ID (like Claude Code) | Indefinite — survives across days/weeks |
| Job chat | Project + job ID | Lives with the job — open while active, read-only history when done |
| Task chat | Project + job + task ID | Lives with the task — same lifecycle |
| Proxy review | Decider ID | Indefinite — the ongoing calibration relationship |
| Liaison chat | Requester + target human | Session-scoped — closes when the question is resolved |

Escalation badges on dashboards are pointers into these chats, not separate conversations. Clicking an escalation badge opens the job or task chat scrolled to the proxy's message.
