# Session Lifecycle

The office manager's conversation is a `claude -p` session. Unlike single-turn agent invocations within CfA phases, the office manager conversation may be multi-turn. The runtime substrate is the same; the usage pattern differs.

## Invocation

A human presses a key in the TUI. The TUI invokes `claude -p` with the office manager's team agent definition, tools, ACT-R memory, and a platform state summary.

## Multi-Turn

The first invocation returns a session ID. Subsequent messages use `--resume <session_id>`. The office manager retains context across turns within a conversation. Operational concerns (context window limits, session persistence) belong in detailed design.

## Between Conversations

The office manager is not persistent between conversations. Each starts fresh from `claude -p`. ACT-R memory carries forward what the agent judged worth remembering. A fresh agent with persistent memory avoids unbounded state, context pressure, and drift.
