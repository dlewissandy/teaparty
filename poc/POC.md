# Hierarchical Agent Teams POC

A proof-of-concept for two-level agent team coordination using Claude Code CLI. The uber team coordinates strategy; subteams execute tactics. Each level runs as a separate `claude -p` process with its own agent pool.

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

### Communication Paths

All intra-team communication uses Claude Code's built-in agent teams feature (`CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1`). This provides:

- **SendMessage** — direct messages between teammates within a process
- **Task** — spawn teammates from the `--agents` pool
- **Automatic inbox delivery** — messages queue and deliver between turns

No bespoke messaging code. The POC relies entirely on Claude's native team coordination primitives.

**Within a level** (intra-process): agents communicate via SendMessage. The lead delegates to workers, workers report back. Workers can also message each other directly. All of this is built into Claude Code — the POC adds nothing.

**Between levels** (inter-process): liaison agents call `relay.sh` via the Bash tool. This is the only bespoke bridge. relay.sh spawns a new `claude -p` process for the subteam, waits for completion, and returns a JSON summary. The liaison then relays the result back to the uber lead via SendMessage.

```
uber process                          subteam process
-----------                          ---------------
lead ──SendMessage──> liaison
                      liaison ──Bash(relay.sh)──> lead ──SendMessage──> workers
                                                  lead <──SendMessage── workers
                      liaison <──(JSON result)──  lead
lead <──SendMessage── liaison
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

- **Agent teams** (`--agents` JSON, SendMessage, Task) — intra-team coordination
- **Plan mode** (`--permission-mode plan`, ExitPlanMode, `--resume`) — plan/execute lifecycle
- **Tool restrictions** (`disallowedTools`) — structural role enforcement
- **Agent definitions** (`--agents` JSON with description, prompt, model, maxTurns) — static team composition

The only bespoke code is the inter-process bridge (relay.sh) and the lifecycle orchestration (plan-execute.sh). Everything else is Claude Code doing what Claude Code does.

### Teams Are Static

Agent definitions live in JSON files. TeamCreate/TeamDelete are in every agent's disallowedTools. Teams are known at startup — agents cannot invent new ones at runtime.

### Agents Are Agents

Minimal, non-prescriptive prompts. No retry loops, format constraints, or output rules. Agents decide how to organize their work. Behavior is shaped by tool availability (disallowedTools), not by prompt engineering.

### relay.sh Is the Only Bridge

The only custom inter-process communication. Everything else uses Claude's built-in inbox/messaging. relay.sh is intentionally thin: spawn a claude process, wait, return JSON.

### plan-execute.sh Works at Both Levels

Same script, same lifecycle. The only difference: `--auto-approve` at the subteam level (no human in the loop). One pattern, no special casing.

### Leaf Workers Have Restricted Tools

Workers (writers, artists, editors) have no Bash. They produce files and communicate via SendMessage. Leads have Bash only because liaisons need it for relay.sh. Tool restrictions via `disallowedTools`, not prompts.

### Stream Files Are Observable

`.plan-stream.jsonl` and `.exec-stream.jsonl` persist in each team's output directory. `stream_filter.py` shows conversations and decisions, suppresses internal machinery. `tail -f` works live.

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

## Constraints

- Two levels only (uber + subteams). No recursive hierarchies.
- Static teams. No dynamic team creation.
- No human approval at subteam level (auto-approve always).
- Subteams never communicate with each other (only through uber team).
- No bespoke intra-team messaging (use Claude's built-in agent teams).
- No prompt engineering for structural behavior (use tool restrictions and plan mode).
