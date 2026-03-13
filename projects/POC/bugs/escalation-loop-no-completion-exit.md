# BUG: Agent stuck in infinite escalation loop — no way for human to signal completion

**Discovered:** 2026-03-12, session 20260312-221105 (hierarchical-memory-paper)
**Severity:** High — requires manual process kill to recover
**Component:** CfA state machine design, `scripts/classify_review.py`, `orchestrator/actors.py`

## Observed behaviour

An agent completed its work but then entered a permission-blocked loop (trying to read files outside the worktree sandbox). It escalated to the human via `TASK_ESCALATE`. The human responded "The work is complete. You do not need to read the files again." The agent ignored this and continued looping.

The cycle repeated: the agent re-read the same files, hit the same permission wall, escalated again, received the same human instruction, and continued. The session had to be killed manually after multiple cycles.

## Why the human's instruction was ignored

The `TASK_ESCALATE` state has three valid actions:

```python
"TASK_ESCALATE": ["dialog", "clarify", "withdraw"]
```

There is no "approve", "complete", or "done" action at escalation states. When the human says "the work is complete," `classify_review.py` classifies this as `clarify` — the human is providing an answer to the agent's question. The clarification is fed back to the agent as context, and the agent transitions to `TASK_RESPONSE` → `TASK_IN_PROGRESS`, where it resumes the same blocked work.

The human has no way to say "stop working, the task is done" at an escalation point. The only exit that preserves work would require the agent to voluntarily reach `COMPLETED_WORK` on its own — but since it's stuck in a permission loop, it never does.

## The full loop

```
TASK_IN_PROGRESS → agent tries to read file outside sandbox
                 → permission denied
                 → agent escalates (writes .task-escalation.md)
                 → TASK_ESCALATE
                 → human says "work is complete"
                 → classified as "clarify"
                 → TASK_RESPONSE → TASK_IN_PROGRESS
                 → agent tries to read the same file again
                 → (repeat)
```

## Two distinct problems

1. **No completion exit from escalation states.** The CfA state machine provides no edge from `TASK_ESCALATE` (or `INTENT_ESCALATE` / `PLANNING_ESCALATE`) that leads toward `COMPLETED_WORK`. The human can only clarify (continue), dialog (ask more), or withdraw (abandon). "The work is done" has no valid classification.

2. **Agent does not learn from repeated permission denials.** The agent receives "Claude requested permissions to read from..." as a tool result, re-reads the worktree copy instead, then tries the blocked path again on the next turn. There is no mechanism for the agent to recognise that a path is persistently inaccessible and stop attempting it.

## Impact

The session's work was completed successfully — 928 insertions across 3 files — but the session could not terminate normally. It required manual process kill and manual squash-merge, bypassing the orchestrator's post-completion steps (learning extraction, state persistence, clean shutdown).
