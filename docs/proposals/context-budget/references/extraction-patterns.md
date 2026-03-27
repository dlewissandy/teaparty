# Stream Extraction Patterns

The orchestrator extracts content from the stream based on event type. Some categories are mechanically straightforward; one requires further design work.

## Mechanically Extractable

### From `user` events (human messages)
Everything. Human input is always preserved verbatim. No semantic analysis needed.

### From `result` events
Token usage for budget tracking, cost accumulation, turn count. These are numeric fields read directly from the event.

### From `state_changed` events (CfA transitions)
Phase transitions, backtracks and their reasons. These are structured data.

### From `tool_use` and `tool_result` events
File modifications (which files were written or edited during the turn). The orchestrator can track what changed without understanding why.

## Requires Design Work

### From `assistant` events (agent text)
- Statements about what was decided or concluded
- Plans and next steps
- Questions directed at the human

Identifying decisions and plans within free-form agent text is semantic analysis, not pattern matching. Event type tells you "this is agent text" but not which sentences contain decisions versus exploratory reasoning.

Three implementation paths are viable:

1. **LLM summarization pass.** After each turn, a secondary LLM call summarizes the turn's outcomes. This is what Claude Code's own `/compact` does. Effective but adds latency and cost per turn.

2. **Structured output convention.** Agents emit decisions in a parseable format: a specific tool call, a tagged block, or writing to a designated file. This is implementable as pattern matching on structured markers, not semantic content. The codebase already uses CfA state changes as structured markers.

3. **Post-turn file inspection.** Instead of extracting from the stream, the orchestrator checks what files the agent modified during the turn and indexes those changes. This sidesteps stream extraction entirely.

The choice between these paths is an open design decision that affects extraction quality, latency, and cost. The remaining extraction categories (human messages, state transitions, cost data, file changes) are implementable today as stream parser rules.
