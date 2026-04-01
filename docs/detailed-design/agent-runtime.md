# Agent Runtime

## Design Choice: Claude Code CLI

All agent invocations go through `claude -p` — the Claude Code CLI in pipe mode. The CLI provides agent teams, tool use, permission modes, session persistence, and `stream-json` output as built-in capabilities. Using the CLI lets us move fast: we get multi-agent coordination, file system access, and tool orchestration without building any of it ourselves.

The tradeoff is clear. The CLI is not a stable API — it's a product interface that can change between releases. A production system would replace CLI invocations with direct Anthropic API calls, reimplementing team coordination, tool dispatch, and permission enforcement at the application layer. For a research POC, the CLI's capabilities far outweigh the coupling risk.

---

## Orchestrator Architecture

The agent runtime is the POC orchestrator (`projects/POC/orchestrator/`), which drives the CfA state machine through three phases:

```
Session.run()
  └─ Orchestrator.run()
       ├─ Start EscalationListener (Unix socket for AskQuestion MCP tool)
       ├─ Intent phase    → AgentRunner → ClaudeRunner → claude -p (with --mcp-config)
       │                    → ApprovalGate (INTENT_ASSERT)
       ├─ Planning phase  → Skill lookup (System 1 fast path)
       │                    ├─ Match found → write PLAN.md from skill, skip planning agent
       │                    └─ No match   → AgentRunner → ClaudeRunner → claude -p
       │                    → ApprovalGate (PLAN_ASSERT)
       └─ Execution phase → AgentRunner → ClaudeRunner → claude -p
                            → ApprovalGate (WORK_ASSERT)
       └─ Stop EscalationListener
```

The orchestrator starts an `EscalationListener` before the first phase. This creates a Unix domain socket and builds an MCP server config that is passed to every `ClaudeRunner` invocation via `--mcp-config`. Agents can call the `AskQuestion` MCP tool to ask questions mid-turn — the question routes through the proxy, and the answer returns as a tool result without the agent exiting.

Before entering cold-start planning, the orchestrator queries the skill library for matching skills ([#97](https://github.com/dlewissandy/teaparty/issues/97)). When a skill matches, the skill template is written directly as `PLAN.md` and CfA advances to `PLAN_ASSERT`, bypassing the planning agent entirely. The human reviews the skill-as-plan at the approval gate. If corrected, the system falls back to the cold-start planning path (System 2).

Each phase invokes an **AgentRunner** (which wraps `ClaudeRunner`) to run a Claude agent team, then routes to the **ApprovalGate** at assertion states for proxy review.

---

## CLI Invocation

`ClaudeRunner` (`claude_runner.py`) builds and executes the subprocess command:

```bash
claude -p \
  --output-format stream-json \
  --verbose \
  --setting-sources user \
  --permission-mode acceptEdits \
  --agents '<team-definition-JSON>' \
  --agent intent-lead \
  --settings /tmp/settings-overlay.json \
  --add-dir /path/to/session/worktree \
  --add-dir /path/to/project/dir \
  --mcp-config /tmp/mcp-config.json
```

Key parameters:
- **`--agents`** — team definition JSON (read from `agents/*.json`, with placeholder substitution for `__POC_DIR__` and `__SESSION_DIR__`)
- **`--agent`** — which agent to start with (the team lead)
- **`--permission-mode`** — per-phase permission level (`acceptEdits`, `plan`, `default`)
- **`--settings`** — overlay for allowed/disallowed tools
- **`--add-dir`** — directories visible to the agent (session worktree, project dir)
- **`--output-format stream-json`** — real-time JSONL event stream
- **`--mcp-config`** — MCP server configuration (provides the `AskQuestion` tool to agents)

The prompt is passed via stdin. Agent output streams as JSONL to `.{phase}-stream.jsonl` files. A stall watchdog kills the process if no output arrives within the configured timeout (default 1800 seconds).

Environment variables injected into every invocation:
- `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1`
- `CLAUDE_CODE_MAX_OUTPUT_TOKENS=128000`
- `POC_PROJECT`, `POC_PROJECT_DIR`, `POC_SESSION_DIR`, `POC_SESSION_WORKTREE`

---

## Agent Definitions

Agent teams are defined in JSON files (`agents/*.json`). Each agent specifies:

| Field | Purpose |
|-------|---------|
| `description` | When to use this agent (shown to other agents) |
| `prompt` | Full behavior instructions |
| `model` | `sonnet`, `opus`, or `haiku` |
| `maxTurns` | Turn limit before force-completion |
| `disallowedTools` | Tools this agent cannot use |

Teams are structured by phase:
- **Intent**: `intent-team.json` — intent lead + research liaison
- **Planning/Execution**: `uber-team.json` — project lead + one liaison per subteam (art, writing, editorial, research, coding)
- **Subteams**: `coding-team.json`, `writing-team.json`, `art-team.json`, `research-team.json`, `editorial-team.json`

---

## Hierarchical Dispatch

During execution, the project lead delegates tasks to subteams through liaison agents. Each liaison dispatches to its subteam by invoking `dispatch_cli.py` via the Bash tool:

```bash
python3 -m projects.POC.orchestrator.dispatch_cli \
  --team art \
  --task "Design the cover art"
```

Each dispatch:
1. Creates an isolated **dispatch worktree** (child branch of the session branch)
2. Initializes **child CfA state** linked to the parent via `make_child_state()` (carries parent_id, team_id, depth)
3. Runs a **child orchestrator** with the subteam's agent file and lead, skipping intent (intent is inherited from parent)
4. **Auto-approves** all review gates — `_NoInputProvider` returns `'approve'` for every request. No human interaction at the dispatch level.
5. On failure, **retries** up to `max_dispatch_retries` (default 5) unless the failure is an escalation (which surfaces to the parent)
6. On success, generates a commit message (LLM call via Haiku) and **squash-merges** results back into the parent session worktree
7. Writes a `MEMORY.md` in the dispatch infra dir for the learning rollup chain
8. Cleans up the dispatch worktree
9. Returns JSON status with fields: `status` (completed/failed), `exit_reason` (completed, plan_escalation, work_escalation, failed), `terminal_state` (final CfA state), `backtrack_count`

### Dispatch Result Schema

The dispatch function returns a JSON object with the following fields:

| Field | Type | Description |
|-------|------|-------------|
| `status` | string | `completed` or `failed` |
| `exit_reason` | string | `completed`, `plan_escalation`, `work_escalation`, `failed`, or `retry_limit_exceeded` |
| `terminal_state` | object | Final CfA state (phase, state, actor, history, backtrack_count, etc.) |
| `backtrack_count` | int | Total cross-phase backtracks during the dispatch |
| `team` | string | Team slug that was dispatched |
| `timestamp` | string | ISO timestamp of dispatch completion |

The calling agent parses this JSON to determine whether to continue execution or escalate to the parent.

### Process Isolation and Intent Scope

Process boundaries provide context isolation by design — each subteam runs in its own `claude -p` process with its own context window. This ensures subteams don't pollute the parent's working memory and can focus on their narrow task without distraction.

Child CfA skips intent gathering (inherited from parent). This is a policy choice to avoid redundant dialogue, justified by the assumption that intent is monotonic — if task X is part of project P, and project P is part of intent I, then task X is part of intent I. Future work could consider intent re-validation at narrower scope for tasks that specialize the parent's intent.

**Issue [#144](https://github.com/dlewissandy/teaparty/issues/144)** tracks replacing this subprocess-based dispatch with an `AskTeam` MCP tool — the same pattern as `AskQuestion`. Liaisons would call `AskTeam(team, task)` instead of invoking `dispatch_cli.py` via Bash. The orchestrator would manage the full subteam lifecycle (worktree, child CfA, merge, learning rollup) behind the tool call. The isolation benefit is real and will be preserved in the MCP version.

---

## Event Bus and Observability

The orchestrator publishes events to an `EventBus` (`events.py`), which serves as the pub-sub backbone for observability. The bridge dashboard and logging systems subscribe to these events.

Major event types:
- `LOG` — text output (agent steps, orchestrator decisions)
- `INPUT_REQUEST` — question asked to human
- `ACTOR_START` — agent or approval gate invocation begins
- `ACTOR_DONE` — agent or approval gate completes
- `STATE_TRANSITION` — CfA state change
- `APPROVAL_REQUIRED` — human review requested
- `ESCALATION` — decision escalated to human

The EventBus is created in the main orchestrator entry point and flows through `Session` → `Orchestrator` → individual actors. It survives across all phases and is the mechanism that the bridge dashboard uses to display real-time progress.

This is infrastructure detail, not core to understanding CfA or agent runtime, but important for observability and debugging.

---

## Phase Configuration

Phase configuration is loaded by `phase_config.py:PhaseConfig.load()`; validation happens at orchestrator startup. The configuration file (`phase-config.json`) maps phases to agent files, leads, permission modes, artifact paths, and approval states:

| Phase | Agent File | Lead | Permission Mode | Artifact | Approval State |
|-------|-----------|------|-----------------|----------|----------------|
| Intent | `intent-team.json` | `intent-lead` | `acceptEdits` | `INTENT.md` | `INTENT_ASSERT` |
| Planning | `uber-team.json` | `project-lead` | `acceptEdits` | `PLAN.md` | `PLAN_ASSERT` |
| Execution | `uber-team.json` | `project-lead` | `acceptEdits` | `.work-summary.md` | `WORK_ASSERT` |

Each phase configures a `settings_overlay` controlling which tools are allowed. Intent phase allows Write, Edit, WebFetch, WebSearch. Execution phase additionally allows SendMessage, Bash, Task, TaskOutput.

Subteam overrides are configured in the `teams` section — each team specifies its agent file, lead, and optional planning permission mode (subteams use `plan` mode for tactical planning).

---

## Session Lifecycle

The `Session` class (`session.py`) manages the full workflow:

1. Classify task → derive project slug
2. Ensure project directory and git repo exist
3. Create session worktree (isolated branch from main)
4. Copy context files (`--intent-file`, `--plan-file`) if provided
5. Retrieve memory context (institutional memory, proxy preferences, fuzzy retrieval)
6. Run orchestrator (CfA state loop)
7. Commit deliverables
8. Squash-merge session into main
9. Extract learnings (10 scopes in parallel)
10. Clean up session worktree

Sessions can be resumed (`Session.resume_from_disk()`) by reloading CfA state, extracting Claude session IDs from stream JSONL files, and reconstructing actor data from the worktree.

---

## Key Files

| File | Purpose |
|------|---------|
| `orchestrator/__main__.py` | CLI entry point |
| `orchestrator/session.py` | Session lifecycle |
| `orchestrator/engine.py` | CfA state machine loop |
| `orchestrator/actors.py` | AgentRunner + ApprovalGate |
| `orchestrator/claude_runner.py` | `claude -p` subprocess wrapper |
| `orchestrator/dispatch_cli.py` | Subteam dispatch entry point |
| `orchestrator/mcp_server.py` | AskQuestion MCP server (stdio) |
| `orchestrator/escalation_listener.py` | Unix socket bridge for AskQuestion → proxy → human |
| `orchestrator/phase_config.py` | Phase and team configuration loader |
| `orchestrator/procedural_learning.py` | Skill candidate archival and crystallization |
| `orchestrator/skill_lookup.py` | System 1 skill matching (threshold-based retrieval, default threshold=0.15) |
| `phase-config.json` | Phase/team/permission configuration |
| `agents/*.json` | Agent team definitions |
