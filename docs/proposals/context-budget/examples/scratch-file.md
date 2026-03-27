# Example Scratch File

A scratch file is a concise index that points to detailed information stored elsewhere in the `.context/` directory.

```markdown
# Job: Implement ACT-R memory retrieval
Phase: WORK (2 of 4 tasks complete)
Updated: 2026-03-27 14:32

## Decisions
- Retrieval threshold set to 0.3 for same-level, 0.5 for cross-level
  → see PLAN.md §Retrieval-Parameters for rationale
- Decay parameter d=0.5 (slow decay) per human guidance
  → see .context/human-input.md #3

## Human Input
3 interactions recorded → .context/human-input.md

## Dead Ends
- Tried cosine similarity without structural filter — too noisy
  → see .context/dead-ends.md #1

## Artifacts
- INTENT.md (complete)
- PLAN.md (complete)
- retrieval.py (in progress)
- test_retrieval.py (in progress)

## Current Task
Add activation decay calculation — coding-agent-2
  → see .context/tasks/t2-status.md
```

## Key Properties

- **Under 200 lines** — stays within context window
- **Rewritten, not appended** — always a current snapshot
- **Pointers to detail** — summaries with links to full content
- **One-line per item** — fast to scan after compaction

The agent reads this file first after compaction. It's a map. If the one-line summary is enough, the agent moves on. If more detail is needed, the agent reads the referenced file.
