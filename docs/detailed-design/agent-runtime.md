# Agent Runtime

## Design Choice: Claude Code CLI

All agent invocations go through `claude -p` — the Claude Code CLI in pipe mode. This is a deliberate design choice. The CLI provides agent teams, tool use, permission modes, session persistence, and `stream-json` output as built-in capabilities. Using the CLI lets us move fast: we get multi-agent coordination, file system access, and tool orchestration without building any of it ourselves.

The tradeoff is clear. The CLI is not a stable API — it's a product interface that can change between releases. A production system would replace CLI invocations with direct Anthropic API calls, reimplementing team coordination, tool dispatch, and permission enforcement at the application layer. For a research POC, the CLI's capabilities far outweigh the coupling risk.

---

## Orchestrator Architecture

The agent runtime is the POC orchestrator (`projects/POC/orchestrator/`), which drives the CfA state machine through three phases:

```
Session.run()
  └─ Orchestrator.run() — CfA state loop
       ├─ Intent phase    → AgentRunner → ClaudeRunner → claude -p
       │                    → ApprovalGate (INTENT_ASSERT)
       ├─ Planning phase  → AgentRunner → ClaudeRunner → claude -p
       │                    → ApprovalGate (PLAN_ASSERT)
       └─ Execution phase → AgentRunner → ClaudeRunner → claude -p
                            → ApprovalGate (WORK_ASSERT)
```

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
  --add-dir /path/to/project/dir
```

Key parameters:
- **`--agents`** — team definition JSON (read from `agents/*.json`, with placeholder substitution for `__POC_DIR__` and `__SESSION_DIR__`)
- **`--agent`** — which agent to start with (the team lead)
- **`--permission-mode`** — per-phase permission level (`acceptEdits`, `plan`, `default`)
- **`--settings`** — overlay for allowed/disallowed tools
- **`--add-dir`** — directories visible to the agent (session worktree, project dir)
- **`--output-format stream-json`** — real-time JSONL event stream

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
- **Planning/Execution**: `uber-team.json` — project lead + one liaison per subteam
- **Subteams**: `coding-team.json`, `writing-team.json`, `art-team.json`, etc.

---

## Hierarchical Dispatch

Liaisons invoke `dispatch_cli.py` via Bash to create child orchestrators in isolated subprocesses:

```bash
python3 -m projects.POC.orchestrator.dispatch_cli \
  --team art \
  --task "Design the cover art"
```

Each dispatch:
1. Creates an isolated **dispatch worktree** (child branch of session branch)
2. Initializes **child CfA state** linked to parent
3. Runs a **child orchestrator** with the subteam's agent file and lead
4. **Auto-approves** all review gates (no human interaction at dispatch level)
5. **Squash-merges** results back into the parent session worktree
6. Returns JSON status (`completed`, `failed`, `plan_escalation`, `work_escalation`)

Process boundaries provide context isolation by design — each subteam runs in its own `claude -p` process with its own context window.

---

## Phase Configuration

`phase-config.json` maps phases to agent files, leads, permission modes, artifact paths, and approval states:

| Phase | Agent File | Lead | Permission Mode | Artifact |
|-------|-----------|------|-----------------|----------|
| Intent | `intent-team.json` | `intent-lead` | `acceptEdits` | `INTENT.md` |
| Planning | `uber-team.json` | `project-lead` | `acceptEdits` | `PLAN.md` |
| Execution | `uber-team.json` | `project-lead` | `acceptEdits` | `.work-summary.md` |

Each phase also configures a `settings_overlay` controlling which tools are allowed (e.g., intent phase disables Bash; execution phase enables it).

---

## Session Lifecycle

The `Session` class (`session.py`) manages the full workflow:

1. Classify task → derive project slug
2. Create session worktree (isolated branch from main)
3. Copy context files (`--intent-file`, `--plan-file`) if provided
4. Retrieve memory context from prior sessions
5. Run orchestrator (CfA state loop)
6. Commit and merge results back to main
7. Extract learnings for proxy model training

Sessions can be resumed (`--resume SESSION_ID`) by reloading CfA state and extracting Claude session IDs from stream JSONL files.

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
| `orchestrator/phase_config.py` | Phase and team configuration loader |
| `phase-config.json` | Phase/team/permission configuration |
| `agents/*.json` | Agent team definitions |
