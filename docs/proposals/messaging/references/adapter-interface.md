# Adapter Interface

The adapter is the boundary between the message bus and whatever renders the conversation.

## Three-Method Contract

```
send(conversation_id, sender, content) → message_id
receive(conversation_id, since_timestamp) → list[message]
conversations() → list[conversation_id]
```

## Implementation Notes

The POC adapter stores messages in SQLite and the Textual chat panel calls `receive()` on a poll. A Slack adapter posts to a channel and receives via webhook. A Teams adapter uses the Graph API. The agents don't know or care which adapter is active.

The adapter does not transform content. It delivers text. If Slack wants rich formatting, the adapter can add it, but the message bus deals in plain text.
