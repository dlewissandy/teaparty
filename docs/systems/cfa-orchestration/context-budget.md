# Context Budget

Detailed design for token tracking, compaction triggers, and scratch file
working memory.

Source files:

- `teaparty/util/context_budget.py` -- ContextBudget class, threshold logic
- `teaparty/util/scratch.py` -- ScratchModel and ScratchWriter

---

## ContextBudget class

`ContextBudget` tracks context window utilization from Claude Code's stream-json
`result` events.  The orchestrator feeds every parsed stream event via `update()`;
only `result` events with token usage are processed.

### Token accounting

Three counters are extracted from each result event:

- `input_tokens` -- direct input tokens
- `cache_creation_input_tokens` -- tokens used to create cache entries
- `cache_read_input_tokens` -- tokens read from cache

`used_tokens` sums all three.  `utilization` divides by `context_window`
(default 200,000 tokens) to produce a 0.0--1.0+ fraction.

Token counts may appear at the top level of the result event or nested under
a `usage` key; the code checks both locations.

### Thresholds

Two thresholds trigger orchestrator action at turn boundaries:

| Threshold | Default | Flag | Meaning |
|-----------|---------|------|---------|
| Warning | 70% | `should_warn` | Context pressure is building |
| Compaction | 78% | `should_compact` | Compaction must happen now |

Flags are latched: once a threshold is crossed, the flag stays True until the
caller explicitly clears it via `clear_warning()` or `clear_compact()`.
Crossing the compaction threshold implies the warning, so both flags are set.

### Compaction trigger

When `should_compact` is True at a turn boundary, the orchestrator injects a
`/compact` command into the agent's input.  `build_compact_prompt()` constructs
the command:

```
/compact focus on {task} -- current CfA state is {cfa_state}
After compaction, read {scratch_path} for preserved context.
```

The focus argument tells Claude's built-in `/compact` what to preserve.  The
optional `scratch_path` points the agent to the `.context/scratch.md` file
where the orchestrator has recorded important content that would otherwise be
lost to compaction.

---

## ScratchModel

`ScratchModel` is an in-memory model of extracted content for a job or task.
The orchestrator feeds stream events via `extract()` and the model is serialized
to `{worktree}/.context/scratch.md` at turn boundaries.

### Extraction categories

Currently implemented:

- **Human inputs:** extracted from `user` events.  Content blocks are normalized
  by `extract_text()`, which handles both plain strings and Claude Code's
  `[{"type": "text", "text": "..."}]` list format.
- **File modifications:** extracted from `tool_use` events where the tool name
  is `Write` or `Edit`.  The `file_path` from the input is recorded (deduplicated).
- **State changes:** recorded via `record_state_change(previous, new)`, called
  by the engine when processing `STATE_CHANGED` bus events (not stream events).
- **Dead ends:** recorded via `add_dead_end(description)` for failed approaches.

### Rendering

`render()` produces a markdown file capped at 200 lines with four sections:
Human Input, State Changes, Dead Ends, and Artifacts.  Each section gets an
equal budget (~47 lines).  Long human messages are truncated to 120 characters.
Sections include pointers to detail files (e.g. `.context/human-input.md`).

---

## ScratchWriter

`ScratchWriter` serializes the model to the `.context/` directory in a worktree.
The orchestrator is the sole writer; agents only read.

- `write_scratch(model)` -- atomic rewrite of `scratch.md` (temp file + `os.replace`).
- `append_human_input(text)` -- appends to `human-input.md` detail file.
- `append_dead_end(description)` -- appends to `dead-ends.md` detail file.
- `cleanup()` -- removes the entire `.context/` directory.

---

## Recently landed

- **Cost enforcement:** `_check_cost_budget` in `teaparty/cfa/engine.py:1649` publishes `COST_WARNING` at 80% and `COST_LIMIT` at 100%, pauses the job via `INPUT_REQUESTED`, asks the human whether to continue, and injects a wrap-up prompt on decline. Project-level enforcement runs alongside via `_check_project_cost_budget`.
- **Context-compaction enforcement:** `_check_context_budget` in `teaparty/cfa/engine.py:1599` injects `/compact` as a `_pending_intervention` when the threshold is crossed, so the next agent turn begins with a compaction pass.

## Design targets not yet implemented

- **Detail files for all sections:** `render()` references `.context/human-input.md`
  and `.context/dead-ends.md`, and `ScratchWriter` has `append_human_input()` and
  `append_dead_end()` methods.  However, state change and artifact detail files
  are not yet written -- only the scratch.md summary includes them.
- **Progressive disclosure:** The scratch file design calls for a tiered
  structure where scratch.md is a concise index with pointers to detail files,
  and detail files contain full content.  The rendering produces pointers but
  only human-input and dead-ends detail files are actually written.
- **Automatic dead-end detection:** Currently dead ends must be explicitly
  recorded via `add_dead_end()`.  Automatic detection from stream patterns
  (e.g. repeated tool failures, backtracking) is not implemented.
