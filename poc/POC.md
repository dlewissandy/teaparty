# Hierarchical Agent Teams POC

Hierarchical agent teams separate strategic coordination from tactical execution. A single flat team trying to do both — plan the project AND write every file — hits context limits and loses coherence as the conversation grows. By splitting into an uber team (strategy) and subteams (tactics), each process stays focused in its own context window. The uber lead never sees raw file content; subteam workers never see cross-team coordination. Context rot is structural, so the fix is structural.

This POC demonstrates two-level agent team coordination using Claude Code CLI. The uber team coordinates strategy; subteams execute tactics. Each level runs as a separate `claude -p` process with its own agent pool.

## Architecture

### Two-Level Hierarchy

```
uber team (one claude -p process)
├── lead        — delegates, never produces deliverables
└── liaisons    — bridge to subteams via relay.sh

subteams (separate claude -p processes, one per relay dispatch)
├── lead        — coordinates workers within the subteam
└── workers     — produce files
```

The specific teams (art, writing, editorial, research) are an implementation detail. The architecture is the two levels and the communication paths between them.

**Why liaisons?** Why not put subteam leads directly in the uber team?

1. **`--agents` is a flat pool.** Each `claude -p` process gets one `--agents` JSON defining its agent pool. The writing-lead needs access to markdown-writer and latex-writer; the art-lead needs svg-artist, graphviz-artist, and tikz-artist. These can't all be in the uber pool — the writing-lead would have no way to get its own workers. Subteams must be separate processes with separate pools.

2. **Someone must cross the process boundary.** The subteam runs as a separate `claude -p` process. Someone in the uber process needs to call `relay.sh` (via Bash) to spawn it, wait for completion, and return the result. That's the liaison — it lives in the uber team and bridges to the subteam process.

3. **Parallelism.** The project-lead dispatches multiple liaisons as background Tasks, so subteams run concurrently. If the lead called relay.sh directly, it would block on each subteam sequentially.

4. **Context isolation.** The liaison returns a JSON summary, not the full subteam conversation. The uber lead never sees raw file content or worker-level chatter — only results. This is the context rot prevention in action.

### Communication Paths

All intra-team communication uses Claude Code's built-in primitives (`CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1`):

- **Task** — the primary delegation mechanism. Leads spawn agents from the `--agents` pool. The spawned agent runs in its own context, does work, and results return through the Task tool. Can run in foreground (blocking) or background (parallel).
- **SendMessage** — direct messages between teammates within a process. Available for coordination but in practice the lead often uses Task for delegation since results return automatically.
- **Automatic inbox delivery** — messages queue and deliver between turns.

No bespoke messaging code. The POC relies entirely on Claude's native coordination primitives.

**Within a level** (intra-process): the lead delegates via Task, spawning agents from the `--agents` pool. Results return through the tool. Agents can also coordinate via SendMessage. All of this is built into Claude Code — the POC adds nothing.

**Between levels** (inter-process): liaison agents call `relay.sh` via the Bash tool. This is the only bespoke bridge. relay.sh spawns a new `claude -p` process for the subteam, waits for completion, and returns a JSON summary.

```
uber process                          subteam process
-----------                          ---------------
lead ──Task──> liaison
               liaison ──Bash(relay.sh)──> lead ──Task──> workers
                                           lead <──(result)── workers
               liaison <──(JSON result)──  lead
lead <──(result)── liaison
```

Subteams never communicate with each other. All cross-team coordination goes through the uber team.

### Process Model

Both levels run the same lifecycle via plan-execute.sh:

1. **Plan** — `claude -p --permission-mode plan` (built-in: agent explores, plans, calls ExitPlanMode)
2. **Approve** — human gate at uber level, auto-approve at subteam level
3. **Execute** — `claude -p --resume $SESSION_ID --permission-mode acceptEdits`

This uses Claude's native plan mode — no prompt engineering to get plan/execute behavior.

## Key Design Choices

### Use Built-In Features, Not Bespoke Code

The POC's value is proving that Claude Code's existing primitives are sufficient for hierarchical teams:

- **Agent teams** (`--agents` JSON, `--agent` lead, `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1`) — the CLI creates the team context automatically when given agent definitions and a lead agent. No agent needs to call TeamCreate.
- **Subagents** (`--agents` pool, Task tool) — leads spawn teammates from the defined pool via the Task tool. Teammates coordinate via SendMessage and shared inboxes.
- **Plan mode** (`--permission-mode plan`, ExitPlanMode, `--resume`) — plan/execute lifecycle
- **Tool restrictions** (`disallowedTools`) — structural role enforcement
- **Agent definitions** (`--agents` JSON with description, prompt, model, maxTurns) — static team composition

The only bespoke code is the inter-process bridge (relay.sh) and the lifecycle orchestration (plan-execute.sh). Everything else is Claude Code doing what Claude Code does.

### Teams Are Static

Agent definitions live in JSON files. The CLI creates the team from `--agents` + `--agent` + the env var. TeamCreate/TeamDelete are in every agent's `disallowedTools` — agents cannot create or destroy teams at runtime. The lead spawns teammates via Task from the pre-defined pool.

### Agents Are Agents

Minimal, non-prescriptive prompts. No retry loops, format constraints, or output rules. Agents decide how to organize their work. Behavior is shaped by tool availability (disallowedTools), not by prompt engineering.

### relay.sh Is the Only Bridge

The only custom inter-process communication. Everything else uses Claude's built-in inbox/messaging. relay.sh is intentionally thin: spawn a claude process, wait, return JSON.

**Parallelism lives at the lead level, not the liaison level.** The lead dispatches multiple liaisons as background Tasks (`run_in_background: true`). Each liaison calls relay.sh as a foreground Bash command — blocking until the subteam completes, then returning the JSON result through the Task tool. Parallelism comes from multiple concurrent Tasks, not from background Bash within a single liaison.

relay.sh also writes `.result.json` to the dispatch output directory and uses a `.running` sentinel file. This makes results discoverable even if an agent uses a suboptimal dispatch pattern (e.g., background Bash + polling instead of foreground Bash). When `.running` disappears and `.result.json` exists, the result is ready.

### plan-execute.sh Works at Both Levels

Same script, same lifecycle. The only difference: `--auto-approve` at the subteam level (no human in the loop). One pattern, no special casing.

### Leaf Workers Have Restricted Tools

Workers (writers, artists, editors) have no Bash. They produce files and return results via Task. Leads have Bash only because liaisons need it for relay.sh. Tool restrictions via `disallowedTools`, not prompts.

### Stream Files Are Observable

`.plan-stream.jsonl` and `.exec-stream.jsonl` persist in each team's output directory. `stream_filter.py` shows conversations and decisions, suppresses internal machinery. The shared `CONVERSATION_LOG` unifies output across all levels, with subteam output indented via `--filter-prefix`.

## Memory Hierarchy

Work is organized by project. Each project has its own namespace and memory. The project is determined from the task description via LLM-based intent classification (or explicit `--project` override). Within a project, each run gets a timestamped session directory. Within a session, each team dispatch gets its own timestamped subdirectory.

### Directory Layout

```
poc/output/
  MEMORY.md                                    # global learnings (project-agnostic)
  projects/
    multidimensional-travellers-handbook/
      MEMORY.md                                # project learnings (across sessions)
      20260226-143052/                         # uber session
        MEMORY.md                              # session learnings (team-agnostic)
        .conversation                          # unified conversation log
        .plan-stream.jsonl                     # uber plan stream
        .exec-stream.jsonl                     # uber exec stream
        art/
          MEMORY.md                            # team learnings (across dispatches)
          20260226-143055/                     # dispatch session 1
            MEMORY.md                          # dispatch learnings
            *.svg, *.dot
          20260226-144200/                     # dispatch session 2
            MEMORY.md
            *.svg
        writing/
          MEMORY.md                            # team learnings
          20260226-143100/
            MEMORY.md
            *.md, *.tex
        editorial/
          MEMORY.md                            # team learnings
          20260226-145000/
            MEMORY.md
            *.md
        research/
          MEMORY.md                            # team learnings
          20260226-143052/
            .result.json              # relay.sh result (persistent)
            .running                  # sentinel (exists while relay.sh runs)
            MEMORY.md
            *.md
    dark-energy-research/
      MEMORY.md
      ...
```

### Project Classification

When `run.sh` is called without `--project`, it calls `scripts/classify_task.py` to derive a project slug from the task description. The classifier:

1. Lists existing project directories under `output/projects/`
2. Calls claude-haiku with the task description and the existing project names
3. Returns an existing project slug if the task belongs to one, or a new slug if not

This means "revise chapter 1 of the handbook to reflect dark energy research" routes to the handbook project (not a new project), while "research dark energy" might create a separate project if no handbook project exists yet.

Override with `--project <slug>` for explicit control.

### Automated Learning Extraction

Learning is structural, not prompt-dependent. When a session ends, `scripts/summarize_session.py` reads the exec stream, calls claude-haiku to extract durable learnings, and appends them to MEMORY.md. No agent prompt mentions memory — agents don't need to cooperate for learning to happen.

The `--scope` parameter controls what kind of learnings are extracted at each level:

| Scope | Focus | Excludes |
|-------|-------|----------|
| `team` | Tool usage, coordination within the team | Domain content |
| `team-rollup` | Patterns across dispatches for one team | One-off issues |
| `session` | Cross-team coordination, delegation strategies | Team-internal details |
| `project` | Project-specific workflow patterns, domain knowledge | Generic process insights |
| `global` | Cross-project process insights only | ALL domain knowledge |

### Promotion Chain

Each level filters more aggressively. Team-specific knowledge stays at team level. Project-specific knowledge stays at project level.

```
dispatch session ends (relay.sh)
  └─> summarize_session.py --scope team
      └─> <session>/<team>/<dispatch>/MEMORY.md

uber session ends (run.sh) — 4 promotion steps:

  1. promote_learnings.sh --scope team
     └─> for each team: aggregate dispatch MEMORY.md files
     └─> summarize_session.py --scope team-rollup
         └─> <session>/<team>/MEMORY.md

  2. promote_learnings.sh --scope session
     └─> reads team MEMORY.md files + uber exec stream
     └─> summarize_session.py --scope session (team-agnostic filter)
         └─> <session>/MEMORY.md

  3. promote_learnings.sh --scope project
     └─> reads session MEMORY.md
     └─> summarize_session.py --scope project
         └─> projects/<project>/MEMORY.md

  4. promote_learnings.sh --scope global
     └─> reads project MEMORY.md
     └─> summarize_session.py --scope global (project-agnostic filter)
         └─> output/MEMORY.md
```

The team→session step filters for team-agnostic learnings only. The project→global step filters for project-agnostic insights only. Domain knowledge stays at the project level. Team-specific patterns stay at the team level.

### Session Isolation

Each `run.sh` invocation creates a new timestamped session directory under the project. Each `relay.sh` dispatch creates a new timestamped subdirectory under its team. Sessions and dispatches never clobber each other.

Shared files (append-only by convention):
- `output/MEMORY.md` — global learnings across all projects
- `output/projects/<slug>/MEMORY.md` — project learnings across all sessions

### File Access Permissions

Claude Code restricts file tool access (Read, Glob, Grep, Write) to the CWD tree by default. The POC uses `--cwd` to set the working directory (write target) and `--add-dir` to grant read access to broader directory trees.

| Level | CWD (write target) | --add-dir (read access) |
|-------|-------------------|------------------------|
| Uber | `$POC_SESSION_DIR` (session dir) | `$POC_PROJECT_DIR` (project dir — includes past sessions + project MEMORY.md) |
| Subteam | `$OUTPUT_DIR` (dispatch dir) | `$POC_SESSION_DIR` (session dir — includes all team/dispatch dirs + session MEMORY.md) |

This means:
- **Writes stay local**: output files go to the dispatch/session directory, preventing scattering.
- **Reads are broad**: agents can read output from sibling dispatches, other teams, and memory files.
- A writing subteam dispatched a second time can read the outline from its first dispatch.
- An editorial subteam can read writing and art output for review.
- The uber lead can read project MEMORY.md and past session output.

## Stream-JSON Parsing

`claude -p --output-format stream-json` emits one JSON object per line. Each event has a `type` field and optionally a `subtype`. Here's what matters for observing agent behavior.

### Event Types

| Type | Subtype | What it is | Key fields |
|------|---------|------------|------------|
| `system` | `init` | Process startup. One per `claude -p` invocation. | `session_id`, `agents` (pool), `tools`, `model` |
| `system` | `task_started` | A Task subagent was spawned. | `tool_use_id`, `description`, `task_type` |
| `system` | `task_progress` | Heartbeat while a background Task runs. High volume. | `tool_use_id`, `last_tool_name`, `usage` |
| `system` | `task_notification` | A background Task finished. | `tool_use_id`, `status`, `summary`, `usage` |
| `assistant` | — | The agent's turn. Contains content blocks (see below). | `message.content[]`, `session_id`, `parent_tool_use_id` |
| `user` | — | Tool results returning to the agent. | `message.content[]` (array of `tool_result` objects) |
| `result` | `success` | Process complete. Final output + cost. | `result`, `total_cost_usd`, `num_turns`, `usage` |
| `rate_limit_event` | — | API rate limit hit. | `rate_limit_info` |

### Assistant Content Blocks

Each `assistant` event contains `message.content[]` — an array of typed blocks:

| Block type | What it is | Key fields |
|------------|------------|------------|
| `thinking` | Internal chain-of-thought. Not shown to users. | `text` |
| `text` | Agent's visible output — narration, reasoning, summaries. | `text` |
| `tool_use` | Agent calling a tool. The interesting part. | `name`, `input`, `id` |

### Tool Use Events Worth Watching

| Tool name | What it means | Input fields |
|-----------|---------------|--------------|
| `Task` | Lead dispatching to a subagent. | `subagent_type`, `name`, `description`, `prompt`, `run_in_background` |
| `SendMessage` | Direct message between teammates. | `type` (message/broadcast/shutdown_request), `recipient`, `content`, `summary` |
| `Bash` | Shell command. Only relay.sh calls cross process boundaries. | `command` |
| `Write` | File creation. | `file_path`, `content` |

### Tool Results (User Events)

Tool results come back as `user` events with `message.content[]` containing objects with:
- `tool_use_id` — matches the `id` from the `tool_use` block
- `content` — array of `{type: "text", text: "..."}` blocks
- `is_error` — boolean, true if the tool call failed

### Identifying the Sender

Events don't have an `agent_name` field. To identify who's speaking:

1. **Lead**: the `session_id` from the first `system/init` event.
2. **Subagents**: `parent_tool_use_id` on the event matches the `id` of the Task `tool_use` that spawned them. Track the mapping `tool_use_id → agent name` from Task dispatches.
3. **Fallback**: `session_id[:8]` as a short hash.

### Stream Completion and Stop Reasons

The `stop_reason` field on assistant messages tells you what happened and what to do next:

| `stop_reason` | Meaning | Action |
|---------------|---------|--------|
| `end_turn` | Claude finished naturally. The accompanying text IS the result. | Relay the result up. Task complete. |
| `tool_use` | Claude is calling a tool. Mid-loop. | Execute the tool, return the result, continue. |
| `max_tokens` | Response truncated at token limit. | Consider continuing or increasing `max_tokens`. |
| `null` | Intermediate event, not a stopping point. | Ignore — not the end of the stream. |

In the CLI's `--output-format stream-json` coalesced format, the completion signal is the `type: result` event with `subtype: success`. This is the CLI-level equivalent of `stop_reason: end_turn`. When this event appears, the stream is done and the last assistant text content is the final result.

**relay.sh uses this signal**: as soon as `plan-execute.sh` returns (meaning the subteam's stream emitted its result event), relay.sh immediately writes `.result.json` and echoes the result to stdout — before any post-processing (learning extraction runs asynchronously in the background). This ensures the result is available to the parent team as quickly as possible.

### What stream_filter.py Shows

The filter reads stream-json from stdin and outputs `[sender] @recipient: body` lines:

- **Task dispatch**: `[lead] @writing-liaison: Write chapter 1 — ...`
- **SendMessage**: `[art-liaison] @project-lead: Art assets complete`
- **Relay call**: `[writing-liaison] @writing-team: Write the introduction`
- **Errors**: `[lead] !! Bash: command failed`
- **Done**: `--- done ---` with final result text

Everything else (thinking, text narration, Glob, Read, Grep, TodoWrite, task_progress) is suppressed.

## File Layout

| File | Purpose |
|------|---------|
| `run.sh` | Entry point. Classifies project, sets env, builds agents JSON, creates session dir, calls plan-execute.sh. |
| `plan-execute.sh` | Lifecycle: plan → approve → execute. Works at both levels. |
| `relay.sh` | Inter-process bridge. Called by liaisons via Bash. Spawns subteam claude process with per-dispatch session dirs. Returns result immediately on stream completion; learning extraction runs async. |
| `agents/*.json` | Static team definitions. One file per team level. |
| `stream_filter.py` | Filters stream-json to human-readable conversation output. |
| `status.sh` | Dashboard: processes, teams, stream activity, output files. Project-aware. |
| `shutdown.sh` | Graceful shutdown and team artifact cleanup. |
| `scripts/classify_task.py` | LLM-based project classification. Maps task descriptions to project slugs. |
| `scripts/summarize_session.py` | Extracts durable learnings from stream files via claude-haiku. Scope-aware (team/session/project/global). |
| `scripts/promote_learnings.sh` | Promotes learnings upward: session→project or project→global (via `--scope`). |
| `output/MEMORY.md` | Global learnings. Persists across all projects. Only cross-project insights. |
| `output/projects/<slug>/` | Project directory. One per classified project. |
| `output/projects/<slug>/MEMORY.md` | Project learnings. Persists across sessions within this project. |
| `output/projects/<slug>/<session>/` | Session directory (timestamped YYYYMMDD-HHMMSS). One per run. |
| `output/projects/<slug>/<session>/MEMORY.md` | Session-level learnings. |
| `output/projects/<slug>/<session>/<team>/<dispatch>/` | Dispatch directory (timestamped). One per relay.sh call. |
| `output/projects/<slug>/<session>/<team>/<dispatch>/.result.json` | Relay result JSON. Written by relay.sh on completion. Discoverable fallback when stdout isn't captured. |
| `output/projects/<slug>/<session>/<team>/<dispatch>/.running` | Sentinel file. Exists while relay.sh is running. Removed on completion or abnormal exit (via trap). |
| `output/projects/<slug>/<session>/<team>/MEMORY.md` | Team-level learnings. Aggregated from dispatch MEMORYs via `promote_learnings.sh --scope team`. |
| `output/projects/<slug>/<session>/<team>/<dispatch>/MEMORY.md` | Dispatch-level learnings. |

## Usage

```bash
# Run (project auto-classified from task description)
./poc/run.sh "Create a handbook about dimensional travel"

# Run with explicit project
./poc/run.sh --project dimensional-travel-handbook "Add chapter on dark energy"

# Monitor and stop
./poc/status.sh
./poc/shutdown.sh

# Browse output
ls poc/output/projects/                                               # list projects
cat poc/output/MEMORY.md                                              # global learnings
cat poc/output/projects/dimensional-travel-handbook/MEMORY.md          # project learnings
cat poc/output/projects/dimensional-travel-handbook/20260226-143052/MEMORY.md  # session learnings
```

## CLI Flags

Every `claude -p` invocation uses these flags. They are the mechanism — no bespoke code replicates what they provide.

| Flag | Purpose |
|------|---------|
| `-p` | Pipe mode. Non-interactive, reads task from stdin, exits when done. |
| `--output-format stream-json` | Streams structured JSON events (tool calls, messages, results) to stdout. Consumed by `stream_filter.py` for human-readable output. |
| `--agents '<JSON>'` | Defines the agent pool for this process. Each agent has `description`, `prompt`, `model`, `maxTurns`, `disallowedTools`. Agents are spawned via the Task tool. |
| `--agent <name>` | Runs claude as the named agent from the `--agents` pool. Combined with `--agents` and the env var, this creates the team context automatically — no TeamCreate needed. |
| `--permission-mode plan` | Plan phase. Agent explores and plans in read-only mode, calls ExitPlanMode when ready. |
| `--permission-mode acceptEdits` | Execute phase. Agent can write files and run tools without prompting. |
| `--resume <session-id>` | Resumes a previous session. Used to continue from plan phase into execute phase with full context preserved. |
| `--max-turns <n>` | Caps the number of agentic turns. Prevents runaway processes. |
| `--verbose` | Includes additional detail in stream-json output. |
| `--settings <file>` | Points to a settings file (used at uber level to pre-approve relay.sh). |
| `--setting-sources user` | Ignores project-level `.claude/agents/` discovery. Isolates the POC from any agents defined in the repo. |
| `--add-dir <dir>` | Grants tool access to directories outside CWD. Used by subteams to read session-wide output (sibling dispatches, other teams, memory files) and by uber level to read project-wide output. |

## Environment Variables

| Variable | Set by | Purpose |
|----------|--------|---------|
| `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1` | `run.sh` | Enables agent teams. Required for SendMessage, shared inboxes, and team coordination. Without this, agents are plain subagents that only report results back. |
| `CLAUDE_CODE_MAX_OUTPUT_TOKENS` | `run.sh` | Maximum output tokens per response. Defaults to 128000. SVG and LaTeX output can be verbose — the 32k default is too low for art agents. |
| `CONVERSATION_LOG` | `run.sh` | Shared log file path. All levels append filtered conversation output here. Lives in the session directory. `run.sh` tails it for live terminal output. Subteam output is indented via `--filter-prefix`. |
| `POC_OUTPUT_DIR` | `run.sh` | Root output directory (`poc/output/`). Contains global MEMORY.md and projects directory. |
| `POC_PROJECT` | `run.sh` | Project slug (kebab-case). Derived from task via `classify_task.py` or `--project` override. |
| `POC_PROJECT_DIR` | `run.sh` | Project directory (`poc/output/projects/<slug>/`). Contains project MEMORY.md and session directories. |
| `POC_SESSION_DIR` | `run.sh` | Current session directory (`poc/output/projects/<slug>/YYYYMMDD-HHMMSS/`). Each run gets a unique timestamped directory. Propagated to subteams via settings file. |

## Agent/Team Lifecycle

### Startup

1. `run.sh` sets environment, builds `--agents` JSON from `agents/uber-team.json`, creates `CONVERSATION_LOG`.
2. `plan-execute.sh` starts `claude -p --agents ... --agent project-lead --permission-mode plan`. The CLI creates the team context from the agent definitions — no TeamCreate call needed.
3. The lead plans, calls ExitPlanMode. The session ID is extracted from the `system/init` event.
4. Human approves (or `--auto-approve` at subteam level).
5. `claude -p --resume $SESSION_ID --permission-mode acceptEdits` starts execution with full plan context.

### Delegation

6. The lead spawns liaisons via Task from the `--agents` pool. Liaisons run as subagents — each in its own context window.
7. Liaisons call `relay.sh` via Bash, which starts a new `claude -p` process for the subteam (step 2 again, recursively).
8. Subteam leads spawn workers via Task. Workers produce files and return results.

### Completion

9. Workers finish → results return to subteam lead.
10. Subteam lead finishes → stream emits `result/success` event (the `stop_reason: end_turn` signal). The last assistant text IS the result.
11. `extract_result.py` captures the result text. relay.sh immediately writes `.result.json`, clears `.running`, and returns the JSON summary — before learning extraction (which runs async).
12. Liaison receives the summary → returns to uber lead via Task tool.
13. Uber lead synthesizes results, may dispatch more work, eventually exits.
14. `plan-execute.sh` reads the final `result/success` event and exits.

### Failure Modes

- **Subteam error**: relay.sh returns an error JSON. The liaison reports failure. The lead can re-dispatch or fall back to a `general-purpose` subagent.
- **Token limit**: `CLAUDE_CODE_MAX_OUTPUT_TOKENS` too low. Agent gets an API error. Set to 128k.
- **Max turns exhausted**: agent stops mid-work. Increase `--max-turns` or simplify the task.
- **Rate limiting**: `rate_limit_event` in the stream. Claude retries automatically.
- **Hung process**: a background Task agent waiting on something that will never come. Use `shutdown.sh` to kill the process tree.

## Observed Behavior

From test runs, the lead autonomously:

- **Dispatches multiple Task agents in parallel** using `run_in_background: true` for concurrent liaison work.
- **Falls back gracefully** — if a relay.sh call fails or an art subteam errors, the lead re-dispatches or delegates to a `general-purpose` subagent directly.
- **Sequences dependent work** — writing first, then art, then editorial review — without being prompted to do so.

The stream-json output contains `task_progress` events while background agents work. These are high-volume and suppressed by `stream_filter.py`. The observable events are Task dispatches, relay.sh calls, SendMessage, and errors.

## Constraints

- Two levels only (uber + subteams). No recursive hierarchies.
- Static teams. No dynamic team creation.
- No human approval at subteam level (auto-approve always).
- Subteams never communicate with each other (only through uber team).
- No bespoke intra-team messaging (use Claude's built-in agent teams).
- No prompt engineering for structural behavior (use tool restrictions and plan mode).
- Learning extraction is automated (post-session scripts), not prompt-dependent. Agents don't need to write MEMORY.md — the summarizer extracts learnings from their conversation streams.
- Learning extraction calls claude-haiku, adding a small cost per session (~$0.01).
- Project classification calls claude-haiku once per run (~$0.001). Override with `--project` to skip classification.
- Project→global promotion is strictly filtered — only cross-project process insights propagate. Domain knowledge stays at the project level.
