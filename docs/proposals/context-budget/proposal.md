[Milestone 3: Human Interaction Layer](../milestone-3.md) >

# Context Budget Management

Agents working on long tasks can lose important context when their conversation window fills up. Context budget management ensures that decisions, human input, and dead ends are preserved in files so that agents can continue working effectively after compaction.

---

## Problem

Many agents run concurrently, each with its own context window. Without management, agents hit their context limits and lose important information during auto-compaction.

## Key Observation

The orchestrator already parses stream-json output from every agent. It sees text responses, tool calls, tool results, decisions, human messages, escalation resolutions. It also sees `result` events with full token usage after every turn.

If it extracts important content from the stream into files as it flows by, the conversation becomes expendable. Agents can compact aggressively without losing anything that matters -- the important content is in files, not in conversation history.

---

## Architecture

```
Agent (claude -p)
  | stream-json
Orchestrator (watches stream)
  | extracts
Scratch files (worktree)
  ^ reads on demand
Agent (after compaction)
```

### Stream Monitoring

The orchestrator already parses stream-json. From `result` events it can compute context utilization:

```
used = input_tokens + cache_creation_input_tokens + cache_read_input_tokens
capacity = modelUsage.{model}.contextWindow
utilization = used / capacity
```

This measures input context pressure, which is what Claude Code's `used_percentage` metric tracks. Output tokens also consume the context window but are not included in `used_percentage`. The formula replicates the metric the orchestrator can observe from stream-json.

### Content Extraction

As the stream flows, the orchestrator identifies and extracts content from specific event types. See [extraction-patterns.md](references/extraction-patterns.md) for the breakdown, including which categories are mechanically extractable and which require further design work.

A single scratch file per job/task (`{worktree}/.context/scratch.md`) serves as an index with pointers -- the same progressive disclosure pattern used elsewhere in the system. It must stay under 200 lines. An example appears in [scratch-file.md](examples/scratch-file.md).

After compaction, the agent reads this file first. One-line summaries point to detail files; the agent follows pointers only when it needs the full rationale. Detail files live in a structured directory described in [context-directory.md](examples/context-directory.md).

Only the scratch file is required reading after compaction. Everything else is on demand.

### Compaction Triggers

Compaction fires at turn boundaries: when the current turn completes, the orchestrator injects `/compact` as the next prompt via `--resume`, with a focus argument that directs the agent's attention to its current task. After compaction, the orchestrator also includes a pointer to the scratch file so the agent knows where to find its preserved context. Threshold levels and actions are in [compaction-thresholds.md](references/compaction-thresholds.md).

### After Compaction

Old tool results, early instructions, and detailed reasoning are gone from the context window. But:

- The current task description is in the agent's prompt (always reloaded)
- Decisions and human input are in scratch files (agent reads on demand)
- Artifacts are in the worktree (agent reads on demand)
- Dead ends are documented (agent reads to avoid repetition)
- Current state is in a file (agent knows where it is in the workflow)

Work continues from files rather than from conversation memory. Post-compaction effectiveness is strongest for artifact-heavy work where decisions are reflected in code and documents. Decisions that exist only in conversation ("I plan to use approach X" where X is not yet implemented) are the risk area -- the evaluation criteria below include task completion rate to measure this empirically.

---

## Scratch File Lifecycle

Scratch files live in `{worktree}/.context/` for the duration of the job or task.

- **`scratch.md` is rewritten** (not appended) each time the orchestrator updates it. It is always a current snapshot, not a growing log. This is how it stays under 200 lines. The orchestrator maintains an in-memory model of the current state and serializes it to the scratch file format. If the orchestrator crashes, the `.context/` directory can be scanned on restart to rebuild the index from detail files on disk. The reconstructed index may be slightly stale (missing entries accumulated between the last serialization and the crash), but the detail files themselves are written as they arrive and are complete.
- **Detail files are appended** as new content arrives (human input accumulates, dead ends accumulate). These can grow, but the agent only reads them on demand.
- **All `.context/` files are deleted** when the job completes. The job's session log (stream JSONL) is the permanent record.

These files are not committed to git. They are working memory for the duration of the job.

---

## Cost Budget

The `result` events include `total_cost_usd` and per-model cost breakdowns. The orchestrator tracks cumulative cost per job and per project. See [cost-budget.md](references/cost-budget.md) for budget enforcement rules and escalation behavior.

Cost budgets are enforced mechanically by the orchestrator (warns at 80%, pauses at 100%). They are configuration values, not advisory norms. See [cost-budget.md](references/cost-budget.md) for the distinction.

---

## Why Not ACT-R for Scratch Files

ACT-R's activation-based retrieval is designed for long-term memory across many sessions. It is valuable for cross-session learning.

Scratch files are short-term working memory for a single job. They are small (a few hundred lines total), task-scoped, and read in full. The agent reads the index, decides which pointers to follow based on relevance to its current task, and reads the detail files it needs. This is a table-of-contents lookup, not a memory search. ACT-R's activation decay, spreading activation, and partial matching are unnecessary here.

- **ACT-R** for proxy long-term memory, office manager steering memory, cross-session learning
- **Scratch files** for job/task working memory, context budget management, compaction safety net

---

## Progressive Disclosure Integration

This connects to the progressive disclosure model in [../team-configuration/proposal.md](../team-configuration/proposal.md). The hierarchy:

1. **Agent prompt** -- always loaded, minimal (role, current task, phase)
2. **Scratch files** -- loaded on demand after compaction, or when the agent needs to recall a decision
3. **Worktree artifacts** -- loaded when the agent needs to read or modify work products
4. **Team configuration YAML** -- loaded when the agent needs to understand team structure
5. **`.claude/` artifacts** -- loaded when the agent needs skill content or agent definitions

See [progressive-disclosure-levels.md](references/progressive-disclosure-levels.md) for the full hierarchy definition.

Each level is loaded only when needed. The agent's prompt is lean. Everything else is a Read away.

---

## Resolved: Multi-agent Coordination

When multiple agents share a worktree (team members on a workgroup), they share scratch files. The orchestrator is the sole writer of scratch files; agents only read them. Since the orchestrator serializes writes (atomic write via temp file and rename), there is no concurrency problem.

---

## Evaluation Criteria

| Metric | What it measures |
|--------|-----------------|
| Post-compaction task completion rate | Agents after compaction complete tasks at the same rate as agents without compaction |
| Scratch file coverage | Key decisions and human inputs appear in the scratch file (spot-check) |
| Context utilization at compaction | How close to the threshold agents get before compaction fires |
| Cost tracking accuracy | Tracked cost matches actual API charges |
