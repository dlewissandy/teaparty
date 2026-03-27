# Stream Extraction Patterns

The orchestrator doesn't try to understand everything in the stream. It looks for specific patterns based on event type.

## From `assistant` events (agent text)
- Statements about what was decided or concluded
- Plans and next steps
- Questions directed at the human

## From `user` events (human messages)
- Everything. Human input is always worth preserving.

## From `result` events
- Token usage for budget tracking
- Cost accumulation
- Turn count

## From `state_changed` events (CfA transitions)
- Phase transitions
- Backtracks and their reasons

## Extraction Philosophy

The extraction logic is simple pattern matching on event types, not deep semantic analysis. The goal is to capture the *outcomes* of conversation turns, not the reasoning that led to them.
