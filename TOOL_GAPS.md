# Agent Tool Gap Analysis

## Current Regular Agent Tools (8)

| Tool | What it does | Assigned to (templates) |
|---|---|---|
| `list_files` | Lists all files/links in the workgroup | — |
| `add_file` | Creates a new file (owner only) | — |
| `edit_file` | Replaces entire file content (owner only) | — |
| `rename_file` | Moves/renames a file (owner only) | — |
| `delete_file` | Removes a file (owner only) | — |
| `summarize_topic` | Shows last 6 messages (120 chars each) | All templates |
| `list_open_followups` | Counts pending follow-up tasks | Coding (both), Debate (Moderator) |
| `suggest_next_step` | Canned advice based on keyword ("blocked", "decision", default) | Coding (Implementer), Debate (Affirmative, Negative) |

### Observations

- **Five of eight tools are file CRUD.** Agents that aren't assigned file tools have almost nothing beyond `summarize_topic`.
- **No tool reads a file.** An agent can list files but cannot inspect content. It must rely on whatever the LLM already has in context.
- **No tool searches messages.** `summarize_topic` shows the last 6 messages — there is no way to search older conversation history.
- **`suggest_next_step` is static.** It returns hard-coded strings. It doesn't read files, messages, or agent state.
- **`summarize_topic` is shallow.** 6 messages x 120 chars is 720 characters of context at most.

---

## Gap Analysis by Workgroup Type

### Coding

Agents: Implementer, Reviewer
Files: README.md, docs/architecture.md, backlog/todo.md

| Gap | Why it matters |
|---|---|
| **read_file** | The Reviewer cannot inspect a file to critique it. The Implementer cannot read `backlog/todo.md` to know what's next. Both agents are blind to file content unless it's pasted into chat. |
| **search_files** | No way to find which file mentions a term. With larger workgroups (10+ files), agents can't locate relevant content. |
| **append_to_file** | `edit_file` replaces the entire file. Appending a new backlog item or architecture note requires sending the full existing content back — fragile and wasteful. |
| **patch_file** (section edit) | Editing one section of `architecture.md` requires rewriting the whole file. Agents should be able to target a heading or line range. |
| **search_messages** | Looking up "what did we decide about the API schema?" is impossible once it scrolls past the 6-message `summarize_topic` window. |
| **create_checklist_item** / **toggle_checklist_item** | The backlog is a markdown file. There's no structured way to add, check off, or reorder items — agents must do raw markdown surgery via `edit_file`. |

### Debate

Agents: Affirmative, Negative, Moderator
Files: topic.md, arguments/pro.md, arguments/con.md, synthesis/verdict.md

| Gap | Why it matters |
|---|---|
| **read_file** | The Moderator cannot read `arguments/pro.md` and `arguments/con.md` to synthesize them into `synthesis/verdict.md`. Debaters can't review the opposing side's written arguments. |
| **deep_summarize** (full-conversation summary) | `summarize_topic` gives 6 messages. A debate can run dozens of rounds. The Moderator needs a comprehensive summary to write a fair synthesis. |
| **poll / vote** | No way to collect structured opinions from participants. The Moderator can ask "do you agree?" but can't tally responses. |
| **timer / round_control** | Debates need structure: "Round 1 opening statements", "Round 2 rebuttals". There's no mechanism to advance rounds or enforce time. |
| **tag_message** | Arguments should be taggable (e.g., "evidence", "rebuttal", "concession") so the Moderator can reference them. Currently all messages are flat and unstructured. |
| **compare_files** | Side-by-side comparison of pro vs. con arguments for synthesis. |

### Roleplay

Agents: Scene Director, Character Coach
Files: setting/world.md, characters/cast.md, sessions/session-001.md

| Gap | Why it matters |
|---|---|
| **read_file** | The Character Coach cannot read `characters/cast.md` to check consistency. The Scene Director cannot read `setting/world.md` for scene grounding. |
| **append_to_file** | Session logs grow over time. Appending new scene beats to `sessions/session-001.md` requires rewriting the entire file. |
| **random / dice_roll** | Tabletop-style randomness is fundamental to many roleplay formats. No tool generates random outcomes. |
| **search_messages** | "What did the innkeeper say in scene 3?" — players and agents need to recall past narrative moments. |
| **create_file_from_template** | Starting a new session file (`session-002.md`) from the session template structure. Currently requires manually crafting the content. |
| **pin_message / bookmark** | Key narrative moments (plot twists, character reveals) should be retrievable. Currently they vanish into the scroll. |

---

## Cross-Cutting Gaps (All Workgroup Types)

### Tier 1 — High impact, repeatedly needed

| Tool | Description | Rationale |
|---|---|---|
| **read_file** | Return the content of a specific file by path | The single biggest gap. Agents literally cannot see file content. Every workgroup type suffers. Without it, file tools are write-only. |
| **search_messages** | Search conversation history by keyword or date range | `summarize_topic` only covers the last 6 messages. Any workgroup that runs more than a few exchanges loses access to its own history. |
| **append_to_file** | Append content to an existing file without replacing it | Logs, backlogs, session notes, argument lists — all grow incrementally. Full-file replacement is error-prone. |

### Tier 2 — Significant value, moderate complexity

| Tool | Description | Rationale |
|---|---|---|
| **deep_summarize** | LLM-powered summary of an entire conversation or a specific range | The current `summarize_topic` is a mechanical snippet dump. A real summary tool should use the LLM to produce coherent synthesis. |
| **search_files** | Full-text search across all workgroup files | As file count grows, agents need to find relevant content without listing and reading every file. |
| **patch_file** | Edit a section of a file by heading, line range, or find-and-replace | Surgical edits are safer and more natural than full-file replacement. |
| **pin_message** | Mark a message as pinned/important for later retrieval | Decisions, action items, key narrative moments — these need to survive the scroll. |
| **mention_agent** | Explicitly request input from a specific agent | Currently agents respond based on relevance scoring alone. There's no way for one agent (or a user) to direct a question to a specific agent. |

### Tier 3 — Nice to have, workgroup-specific

| Tool | Description | Primary beneficiary |
|---|---|---|
| **poll / vote** | Collect structured responses from participants | Debate, general decision-making |
| **random / dice_roll** | Generate random numbers or roll dice | Roleplay |
| **timer / set_reminder** | Schedule a future message or enforce time bounds | Debate rounds, coding standups |
| **create_file_from_template** | Create a new file from a workgroup's own file patterns | Roleplay (new sessions), Coding (new docs) |
| **tag_message** | Label messages with categories | Debate (argument types), Coding (decision/action/question) |
| **compare_files** | Diff or side-by-side comparison of two files | Debate synthesis, Coding reviews |

---

## Summary

The current toolset is heavily biased toward file CRUD and lacks the **read** side entirely. Agents can create and modify files but cannot inspect them, search through messages, or perform any structured reasoning over workgroup content.

**Priority order for closing gaps:**
1. `read_file` — unblocks every workflow; without it, files are opaque to agents
2. `search_messages` — unblocks any conversation longer than a few exchanges
3. `append_to_file` — unblocks incremental workflows (logs, backlogs, session notes)
4. `deep_summarize` — unlocks meaningful synthesis (debate verdicts, project status)
5. `search_files` + `patch_file` — scales file management beyond small workgroups
