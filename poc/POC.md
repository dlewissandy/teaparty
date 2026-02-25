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

The specific teams (art, writing, editorial) are an implementation detail. The architecture is the two levels and the communication paths between them.

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

### plan-execute.sh Works at Both Levels

Same script, same lifecycle. The only difference: `--auto-approve` at the subteam level (no human in the loop). One pattern, no special casing.

### Leaf Workers Have Restricted Tools

Workers (writers, artists, editors) have no Bash. They produce files and return results via Task. Leads have Bash only because liaisons need it for relay.sh. Tool restrictions via `disallowedTools`, not prompts.

### Stream Files Are Observable

`.plan-stream.jsonl` and `.exec-stream.jsonl` persist in each team's output directory. `stream_filter.py` shows conversations and decisions, suppresses internal machinery. The shared `CONVERSATION_LOG` unifies output across all levels, with subteam output indented via `--filter-prefix`.

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
| `run.sh` | Entry point. Sets env, builds agents JSON, calls plan-execute.sh. |
| `plan-execute.sh` | Lifecycle: plan → approve → execute. Works at both levels. |
| `relay.sh` | Inter-process bridge. Called by liaisons via Bash. Spawns subteam claude process. |
| `agents/*.json` | Static team definitions. One file per team level. |
| `stream_filter.py` | Filters stream-json to human-readable conversation output. |
| `status.sh` | Dashboard: processes, teams, stream activity, output files. |
| `shutdown.sh` | Graceful shutdown and team artifact cleanup. |

## Usage

```bash
./poc/run.sh "Create a handbook about dimensional travel"   # run
./poc/status.sh                                             # monitor
tail -f $(cat poc/output/.stream-file)                      # live stream
./poc/shutdown.sh                                           # stop
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

## Environment Variables

| Variable | Set by | Purpose |
|----------|--------|---------|
| `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1` | `run.sh` | Enables agent teams. Required for SendMessage, shared inboxes, and team coordination. Without this, agents are plain subagents that only report results back. |
| `CLAUDE_CODE_MAX_OUTPUT_TOKENS` | `run.sh` | Maximum output tokens per response. Defaults to 128000. SVG and LaTeX output can be verbose — the 32k default is too low for art agents. |
| `CONVERSATION_LOG` | `run.sh` | Shared log file path. All levels append filtered conversation output here. `run.sh` creates it and tails it for live terminal output. Subteam output is indented via `--filter-prefix`. |

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
10. Subteam lead finishes → `result/success` event → `extract_result.py` captures the JSON summary.
11. relay.sh returns the summary to the liaison → liaison returns to uber lead.
12. Uber lead synthesizes results, may dispatch more work, eventually exits.
13. `plan-execute.sh` reads the final `result/success` event and exits.

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
