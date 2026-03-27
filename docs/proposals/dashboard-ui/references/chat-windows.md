# Chat Windows

Chat windows are separate from the dashboard — they are not embedded in dashboard views.

## One Chat Per Unit of Work

Every job has one chat. Every task has one chat. There is no separate escalation window or intervention window. Everything flows through the same conversation.

## Stream Filtering

The chat carries the full stream-json output from the Claude session. The human can filter what's visible by stream type:

| Filter | Default | What it shows |
|--------|---------|--------------|
| **agent** | ON | Agent's conversational text responses |
| **human** | ON | Human messages (responses, interventions) |
| **thinking** | OFF | Extended reasoning blocks |
| **tools** | OFF | Tool invocations — Read, Write, Bash, etc. |
| **results** | OFF | Tool return values |
| **system** | OFF | Session init, task events |
| **state** | OFF | CfA state transitions |
| **cost** | OFF | Turn stats: tokens, cost, duration |
| **log** | OFF | Diagnostic messages |

The human can enable any combination to control how much detail they see — from conversation-only to full agent activity.

## Escalations

An escalation is a message from the proxy in the job or task chat. If the chat window is open, the message appears inline. If not, the dashboard shows an escalation badge; clicking the badge opens the chat.

## Interventions

The human types in the chat at any time. If the proxy asked a question, the response resolves the escalation. If nobody asked, the message is an INTERVENE — an unsolicited course correction.

## Office Manager Sessions

Office manager chats are long-lived and resumable. The same stream filtering applies. The office manager's internal activity (tool use, queries to project leads) is in the stream, hidden by default.
