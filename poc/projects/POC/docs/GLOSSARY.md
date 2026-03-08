# POC Glossary

## CfA (Confidence-for-Action)

A three-phase state machine that governs session lifecycle:

1. **INTENT** -- Autonomous intent gathering with human review. Produces INTENT.md.
2. **PLAN** -- Agent plans work in read-only mode, exits plan mode for review.
3. **EXECUTE** -- Agent produces deliverables with write access.

Each phase has a human review gate. Backtracking is supported: execution can loop back to planning (exit code 3) or intent (exit code 2).

## Stage (Domain Stage)

A project-level work phase (stage 1, stage 2, ...) that organizes multi-session work into sequential chunks. Distinct from CfA phases, which are per-session.

- `.current-stage` -- file tracking which domain stage is active
- `detect_stage.py` -- determines the current stage
- `retire_stage.py` -- marks a stage as complete

## Dispatch

The act of creating an isolated subteam worktree, running plan-execute in agent-mode, and merging results back to the session branch. Handled by `dispatch.sh`.

- A dispatch creates a `dispatch/<team>/<timestamp>` branch
- Subteam agents work in the dispatch worktree with restricted visibility
- Results are squash-merged back to the session branch on completion

## Approval Gate

A learned confidence model (`scripts/approval_gate.py`) that predicts whether a human would approve a given plan or result. Used to auto-route decisions when confidence is high, and escalate to the human when confidence is low.

- `proxy_decide()` -- shell function that queries the approval gate
- `proxy_record()` -- shell function that records the human's actual decision for learning

## Message Broker

`message_broker.py` -- an async message routing system for multi-agent communication. Manages per-agent mailboxes, routes SendMessage calls between agents, and handles termination detection.

Not the orchestrator. The session orchestrator is `run.sh`.

## Stream-JSON

Claude Code's `--output-format stream-json` emits one JSON event per line (JSONL). The `stream/` directory contains processors for this format:

- `display_filter.py` -- human-facing display of inter-agent communication
- `intent_display.py` -- display filter for intent-gathering conversations
- `session_logger.py` -- audit log writer
- `extract_result.py` -- extracts the final result text

## UI (Terminal UI)

`ui.sh` -- shared shell library providing terminal formatting, session logging, human prompts, CfA review loops, and failure handling. Sourced by all main scripts.

## Worktree Model

Git worktrees provide isolation between concurrent processes:

```
main                              # consolidated deliverables
 \
  session/<timestamp>             # uber team session
   \         \
    \         dispatch/<team>/<ts> # subteam dispatch
     \
      dispatch/<team>/<ts>        # another subteam dispatch
```

Each level can only write to its own worktree, reads the parent via `--add-dir`.
