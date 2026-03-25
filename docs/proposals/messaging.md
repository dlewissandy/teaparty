# Messaging

The human's primary interaction with agents is conversation. The messaging system is the pipe that carries those conversations. It needs to be simple enough to build for the POC and abstract enough that Slack, Teams, or any other chat app can replace it later.

---

## What It Is

A message bus. Messages go in, messages come out. Each message has a sender, a recipient (a conversation), a timestamp, and content. That's it.

The POC implementation is local: messages stored in SQLite, rendered in a Textual chat panel. The long-term implementation is "bring your own" — the same message abstractions backed by Slack, Teams, Discord, or whatever the organization uses. The bus is the abstraction layer. The POC chat UI and Slack are both adapters.

## What It Is Not

It is not the dashboard. The dashboard is an admin panel — project status, session state, dispatch monitoring. The dashboard stays. The chat is where work conversations happen. You glance at the dashboard to see the big picture. You talk in the chat.

It is not a log viewer. The TUI currently renders stream-json output as a scrolling log. The chat is a conversation, not a transcript. Agent output that constitutes a conversational turn becomes a message. Internal telemetry stays in the dashboard.

---

## Messages

A message:

```
sender:       who sent it (human, proxy, office-manager, project-lead, ...)
conversation: which conversation it belongs to
timestamp:    when
content:      text
```

That's the entire schema. No message types, no metadata fields, no threading. If we need those later, we add them. For now, messages are text in a conversation from a sender.

Conversations are identified by what they're about. A conversation with the office manager. A conversation within a project session. Each has a stable ID tied to the thing it represents (the office manager team, the session infra dir).

---

## Conversations

Three kinds, mapping to the hierarchy:

**Office manager conversation.** One per human. Always available. The human talks to the office manager about cross-project coordination. This conversation persists across sessions — the human can come back to it.

**Project session conversation.** One per active session. Gate questions, corrections, dialog, and steering within a project. When the session ends, the conversation closes. A new session gets a new conversation.

**Subteam conversation.** One per dispatch. The proxy participates on behalf of the human. The human can read these but typically doesn't write in them. If the human drops in, their messages go here.

The office manager conversation and project session conversations can be active simultaneously. The human might be talking to the office manager while a project session hits a gate.

---

## How Messages Flow

### Human → Agent

The human types in the chat. The message is stored and delivered to the agent's next `claude -p` invocation as part of the prompt. For multi-turn conversations (office manager, dialog at gates), the message goes via `--resume` to continue an existing session.

This replaces the FIFO IPC. Instead of writing to `.input-response.fifo`, the human's message goes through the message bus. The orchestrator reads from the bus instead of blocking on a FIFO.

### Agent → Human

Agent output from `claude -p --output-format stream-json` is parsed. Conversational content (the agent's text response, questions, status updates) becomes messages in the conversation. Internal events (tool calls, stream metadata) stay in the dashboard.

The event parser already distinguishes content from telemetry. The split is: if it's something you'd show in a chat bubble, it's a message. If it's something you'd show in a monitoring panel, it's a dashboard event.

### Agent → Agent

Agents talk to each other via MCP tools (AskQuestion, AskTeam) and dispatch. These are not chat messages. They flow through the existing infrastructure. The messaging system is for human-agent conversation, not agent-agent coordination.

---

## Adapter Interface

The adapter is the boundary between the message bus and whatever renders the conversation.

```
send(conversation_id, sender, content) → message_id
receive(conversation_id, since_timestamp) → list[message]
conversations() → list[conversation_id]
```

Three methods. The POC adapter stores messages in SQLite and the Textual chat panel calls `receive()` on a poll. A Slack adapter posts to a channel and receives via webhook. A Teams adapter uses the Graph API. The agents don't know or care which adapter is active.

The adapter does not transform content. It delivers text. If Slack wants rich formatting, the adapter can add it, but the message bus deals in plain text.

---

## POC Implementation

**Storage.** SQLite. One table.

```sql
CREATE TABLE messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation TEXT NOT NULL,
    sender TEXT NOT NULL,
    content TEXT NOT NULL,
    timestamp REAL NOT NULL
);
CREATE INDEX idx_messages_conv ON messages(conversation, timestamp);
```

**TUI.** A chat panel in Textual alongside the existing dashboard. The dashboard becomes one view, the chat becomes another. Or they're side by side — layout is a UX question. The chat panel polls `receive()` and renders messages as a conversation. The human types at the bottom, `send()` stores and delivers.

**Orchestrator integration.** Replace the FIFO IPC with message bus reads. Where the orchestrator currently blocks on `.input-response.fifo`, it instead polls the message bus for new messages in the session's conversation. The `input_provider` callback becomes a bus read.

**Office manager.** The office manager conversation is a `claude -p` session. The human's messages are delivered as prompts. The office manager's responses come back as stream-json and are stored as messages. Multi-turn uses `--resume`.

---

## Migration from FIFO IPC

The current IPC (`ipc.py`) uses:
- `.input-request.json` — orchestrator writes what it needs
- `.input-response.fifo` — TUI writes the human's answer, orchestrator blocks reading

The migration:
1. Orchestrator writes a message to the conversation instead of `.input-request.json`
2. TUI shows it in the chat instead of as a modal input widget
3. Human responds in the chat instead of the input widget
4. Orchestrator reads from the conversation instead of the FIFO

The semantics are identical. The mechanism changes from blocking FIFO to polled message bus. The FIFO IPC can be removed once the migration is complete.

---

## What This Enables

Once messages flow through a bus with an adapter interface:

- **Slack/Teams integration** is an adapter swap. The agent's messages post to a channel. The human's replies come back via webhook. No changes to the orchestrator or agents.
- **Mobile access.** If the adapter is Slack, the human can respond to gates from their phone.
- **Audit trail.** Every human-agent interaction is a stored message. Searchable, exportable, reviewable.
- **Async human participation.** The human doesn't need to be watching the TUI when a gate fires. The message waits in the conversation. The human responds when they can. The orchestrator's timeout behavior may need adjustment, but the messaging layer supports it naturally.

---

## Compliance

Anthropic's terms draw a hard line between consumer subscription use (OAuth, Free/Pro/Max plans) and API key use (Console, Bedrock, Vertex). This affects the messaging system directly.

**What the terms say:**

- OAuth tokens from Free/Pro/Max accounts are for Claude Code and Claude.ai only. Using them in any other product, tool, or service is a violation of the Consumer Terms.
- "Automated or non-human means, whether through a bot, script, or otherwise" are prohibited except when accessed via API key.
- Developers building products or services must use API key authentication through Claude Console or a supported cloud provider.
- Pro and Max plan usage limits "assume ordinary, individual usage."

**What this means for TeaParty:**

The POC running locally for single-user development is ordinary individual usage. The current `claude -p` invocations under a subscription plan are fine for personal research and development.

The moment TeaParty routes messages through Slack, Teams, or any external adapter, it becomes a product or service built on Claude. A Slack bot that invokes `claude -p` on behalf of a user is automated non-human access. This requires API key authentication under the Commercial Terms, not subscription OAuth.

The multi-session orchestrator (concurrent `claude -p` for subteams, dispatch parallelism) may also exceed "ordinary, individual usage" at scale. API keys are the safe path for any deployment beyond single-user local development.

**Implications for the adapter architecture:**

| Deployment | Auth Required | Terms |
|---|---|---|
| Local POC (single user, TUI) | OAuth or API key | Consumer Terms |
| Multi-project orchestration at scale | API key recommended | Commercial Terms |
| Slack/Teams/external adapter | API key required | Commercial Terms |
| Mobile access via external app | API key required | Commercial Terms |

The adapter interface is auth-agnostic — it doesn't care how `claude -p` authenticates. But the deployment documentation must specify that any non-local adapter requires API key authentication. The POC adapter (local SQLite + Textual) works under either auth method. External adapters require Commercial Terms.

This is not a design constraint — the architecture doesn't change. It is a deployment constraint that must be documented and enforced at the configuration level, not the code level.

Sources: [Anthropic Legal and Compliance](https://code.claude.com/docs/en/legal-and-compliance), [Anthropic Terms of Service](https://www.anthropic.com/terms), [Anthropic Usage Policy](https://www.anthropic.com/news/usage-policy-update).

---

## Open Questions

1. **Polling vs. push in the POC.** The TUI polls for new messages. The orchestrator polls for human responses. What polling interval balances responsiveness with resource use? The FIFO was instant (blocking read). Polling adds latency.

2. **Message ordering guarantees.** SQLite autoincrement gives total order within a conversation. Is that sufficient, or do we need vector clocks for the multi-adapter future?

3. **Conversation lifecycle.** When does a project session conversation close? On session completion? On withdrawal? What about conversations for sessions that crash?

4. **Rich content.** Agents produce markdown, code blocks, file references. The message bus carries plain text. Should the adapter handle rendering, or should messages carry a format hint?
