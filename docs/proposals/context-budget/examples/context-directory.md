# Example Context Directory Structure

Detail files live alongside the scratch file in a structured layout:

```
{worktree}/.context/
├── scratch.md              ← the index (under 200 lines)
├── human-input.md          ← full text of human messages
├── dead-ends.md            ← what was tried and failed
└── tasks/
    └── t2-status.md        ← per-task working state
```

## File Purposes

- **scratch.md** — the only file the agent must read after compaction; contains pointers to all other files
- **human-input.md** — accumulated human messages and decisions; grows as the job progresses
- **dead-ends.md** — failed approaches and why they didn't work; prevents re-exploration
- **tasks/*.md** — per-task working state; allows agent to understand where each task stands

All `.context/` files are deleted when the job completes. The job's session log (stream JSONL) is the permanent record.
