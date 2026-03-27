[Milestone 3: Human Interaction Layer](../milestone-3.md) >

# Context Budget Management

Agents working on long tasks can lose important context when their conversation window fills up. Context budget management ensures that decisions, human input, and dead ends are preserved in files so that agents can continue working effectively after compaction.

---

## The Problem

The multi-level conversation model (office manager + project sessions + subteam dispatches) means many agents running concurrently, each with its own context window. Without management, agents hit their context limits and lose important information during auto-compaction.

## The Insight

The orchestrator is already parsing stream-json output from every agent. It sees everything: text responses, tool calls, tool results, decisions, human messages, escalation resolutions. It also sees `result` events with full token usage after every turn.

If the orchestrator extracts important content from the stream into files as it flows by, then the conversation becomes expendable. The agent can compact aggressively — or be compacted by the orchestrator — without losing anything that matters. The important stuff is in files, not in conversation history.

---

## Architecture

```
Agent (claude -p)
  ↓ stream-json
Orchestrator (watches stream)
  ↓ extracts
Scratch files (worktree)
  ↑ reads on demand
Agent (after compaction)
```

### Stream Monitoring

The orchestrator already parses stream-json. From `result` events it can compute context utilization:

```
used = input_tokens + cache_creation_input_tokens + cache_read_input_tokens
capacity = modelUsage.{model}.contextWindow
utilization = used / capacity
```

This gives real-time visibility into every agent's context state.

### Content Extraction

As the stream flows, the orchestrator identifies and extracts important content from specific event types. See [extraction-patterns.md](references/extraction-patterns.md) for the complete breakdown.

The orchestrator maintains a single scratch file per job/task: `{worktree}/.context/scratch.md`. This file is an **index with pointers** — the same progressive disclosure pattern used everywhere in the system. It must stay under 200 lines. See [scratch-file.md](examples/scratch-file.md) for an example.

The scratch file is what the agent reads after compaction. It's a map — one-line summaries with pointers to detail files. If the agent needs the full rationale for a decision, it reads the referenced file. If the one-line summary is enough, it moves on.

Detail files live in a structured directory. See [context-directory.md](examples/context-directory.md) for the directory structure.

The scratch file is the only file the agent must read after compaction. Everything else is on demand.

### Compaction Triggers

The orchestrator triggers compaction when context utilization exceeds a threshold. See [compaction-thresholds.md](references/compaction-thresholds.md) for the detailed threshold table and actions.

### After Compaction

The agent's conversation is summarized. Old tool results, early instructions, and detailed reasoning are gone. But:

- The current task description is in the agent's prompt (always reloaded)
- Decisions and human input are in scratch files (agent reads on demand)
- Artifacts are in the worktree (agent reads on demand)
- Dead ends are documented (agent reads to avoid repetition)
- Current state is in a file (agent knows where it is in the workflow)

The agent continues working as if nothing happened. It reads what it needs from files instead of remembering the conversation.

---

## Scratch File Lifecycle

Scratch files live in `{worktree}/.context/` for the duration of the job or task.

- **`scratch.md` is rewritten** (not appended) each time the orchestrator updates it. It's always a current snapshot, not a growing log. This is how it stays under 200 lines.
- **Detail files are appended** as new content arrives (human input accumulates, dead ends accumulate). These can grow, but the agent only reads them on demand — they don't burn context unless referenced.
- **All `.context/` files are deleted** when the job completes. The job's session log (stream JSONL) is the permanent record.

These files are not committed to git. They are working memory for the duration of the job.

---

## Cost Budget

The `result` events include `total_cost_usd` and per-model cost breakdowns. The orchestrator tracks cumulative cost per job and per project. See [cost-budget.md](references/cost-budget.md) for budget enforcement rules and escalation behavior.

---

## Why Not ACT-R for Scratch Files

ACT-R's activation-based retrieval is designed for long-term memory across many sessions — the proxy's accumulated knowledge of what the human cares about. It's valuable for cross-session learning.

Scratch files are short-term working memory for a single job. They're small (a few hundred lines total), task-scoped, and read in full. There's no retrieval problem to solve — the agent just reads the file. ACT-R's activation decay, spreading activation, and partial matching are overkill for "read the decisions file."

The right model:
- **ACT-R** — proxy long-term memory, office manager steering memory, cross-session learning
- **Scratch files** — job/task working memory, context budget management, compaction safety net

---

## Progressive Disclosure Integration

This connects to the progressive disclosure model in [../team-configuration/proposal.md](../team-configuration/proposal.md). The hierarchy:

1. **Agent prompt** — always loaded, minimal (role, current task, phase)
2. **Scratch files** — loaded on demand after compaction, or when the agent needs to recall a decision
3. **Worktree artifacts** — loaded when the agent needs to read or modify work products
4. **Team configuration YAML** — loaded when the agent needs to understand team structure
5. **`.claude/` artifacts** — loaded when the agent needs skill content or agent definitions

See [progressive-disclosure-levels.md](references/progressive-disclosure-levels.md) for the full hierarchy definition.

Each level is loaded only when needed. The agent's prompt is lean. Everything else is a Read away.

---

## Relationship to Other Proposals

- [../team-configuration/proposal.md](../team-configuration/proposal.md) — progressive disclosure configuration tree; scratch files are the job-level addition
- [../chat-experience/proposal.md](../chat-experience/proposal.md) — chat windows show stream content; the orchestrator watches the same stream
- [../dashboard-ui/proposal.md](../dashboard-ui/proposal.md) — stats (tokens, cost) on job/task dashboards come from the orchestrator's stream monitoring

---

## Resolved: Multi-agent Coordination

When multiple agents share a worktree (team members on a workgroup), they share scratch files. Agents working on the same job or task share the same `.context/` scratch files because they share the same worktree. This centralizes state and prevents divergent context across team members.
