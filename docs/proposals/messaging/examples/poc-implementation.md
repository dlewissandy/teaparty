# POC Implementation Details

## Storage

SQLite. One table:

See [poc-schema.sql](poc-schema.sql) for the CREATE TABLE statement.

Total overhead: one integer ID, one indexed conversation lookup. Simple and efficient for a local POC.

## TUI

A chat panel in Textual alongside the existing dashboard. The dashboard becomes one view, the chat becomes another. Or they're side by side — layout is a UX question.

The chat panel polls `receive()` and renders messages as a conversation. The human types at the bottom, `send()` stores and delivers.

## Orchestrator Integration

Replace the FIFO IPC with message bus reads. Where the orchestrator currently blocks on `.input-response.fifo`, it instead polls the message bus for new messages in the session's conversation. The `input_provider` callback becomes a bus read.

This is mechanically identical to the FIFO read, but the source is the message bus instead of a named pipe.

## Office Manager

The office manager conversation is a `claude -p` session. The human's messages are delivered as prompts. The office manager's responses come back as stream-json and are stored as messages. Multi-turn uses `--resume`.

The office manager is a long-lived agent that maintains the conversation context across multiple sessions. It coordinates cross-project concerns.
