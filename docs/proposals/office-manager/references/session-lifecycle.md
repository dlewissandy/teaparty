# Session Lifecycle

The office manager's conversation is a `claude -p` session. Unlike single-turn agent invocations within CfA phases, the office manager conversation may be multi-turn. The runtime substrate is the same; the usage pattern differs.

## Invocation

A human sends a message via the dashboard chat. The bridge server receives the POST to `/api/conversations/om:{qualifier}`, writes the human message to the OM bus, and fires an async task that invokes `claude -p` with the office manager agent definition, tools, ACT-R memory, and a platform state summary. The TUI was retired in issue #305; the bridge is the invocation path (issue #328).

## Multi-Turn

The first invocation returns a session ID. Subsequent messages use `--resume <session_id>`. The office manager retains context across turns within a conversation. Operational concerns (context window limits, session persistence) belong in detailed design.

## Between Agent Sessions

The office manager is not persistent between agent sessions. Each invocation starts fresh from `claude -p` with an empty context window. ACT-R memory carries forward what the agent judged worth remembering. The message history (the human-visible conversation thread) persists indefinitely, but the agent's working context does not -- it is rebuilt from the prompt, memory retrieval, and platform state on each invocation.

This distinction matters: "conversation" in the messaging system refers to the persistent message thread. "Agent session" refers to the ephemeral `claude -p` context window. The office manager's message history survives across days; its agent context is rebuilt each time.
