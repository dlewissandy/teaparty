# Adapter Interface

The adapter is the boundary between the message bus and whatever renders the conversation.

## Three-Method Contract

```
send(conversation_id, sender, type, content) -> message_id
receive(conversation_id, since_timestamp) -> list[message]
conversations() -> list[conversation_id]
```

## Implementation Notes

The POC adapter stores messages in SQLite and the Textual chat panel calls `receive()` on a poll. A Slack adapter posts to a channel and receives via webhook. A Teams adapter uses the Graph API. The agents do not know or care which adapter is active.

The adapter does not transform message content: no summarization, filtering, or semantic alteration. It may add presentation formatting for the target platform (Slack markdown, emoji reactions, card layouts). The distinction is between content and rendering. The message bus deals in plain text; the adapter is responsible for how that text appears.
