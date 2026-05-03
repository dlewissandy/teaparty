# Unified Agent Launch

**Status:** Implemented
**Implementation:** `launch()` in `teaparty/runners/launcher.py`

## Two launch tiers

TeaParty launches agents in two distinct tiers that share the same
`launch()` function but take different branches:

| Tier | Used by | cwd | Per-launch config | Worktree |
|------|---------|-----|-------------------|----------|
| **chat** | Management chat, OM, project leads, workgroup leads, and any agent dispatched through `teaparty/teams/session.py::AgentSession` | **The real repo** — teaparty for management agents, `<project>` for project leads, inherited from the dispatcher otherwise | Written to the session directory under `.teaparty/{scope}/sessions/{id}/` and passed to `claude` via `--settings`, `--mcp-config --strict-mcp-config`, `--setting-sources user`, `--agents <inline JSON>` | **None** — the real repo is never mutated |
| **job**  | CfA jobs/tasks (`teaparty/cfa/`), where the agent's turn mutates code | A detached git worktree at `{project}/.teaparty/jobs/job-{id}--{slug}/worktree/` (and per-task worktrees at `tasks/task-{id}--{slug}/worktree/` underneath) | Composed into the worktree's `.claude/` and `.mcp.json` by `compose_launch_worktree` | **Yes** — filesystem isolation for concurrent code mutations |

Chat-tier agents read, reason, and dispatch — they do not mutate code,
so a worktree per conversation is pure churn and produces two concrete
bugs: project leads run in the wrong repo, and per-session `.claude/`
composition is structurally incompatible with launching at the real
repo. The chat tier solves both by injecting per-launch config via CLI
flags pointing at files outside the cwd. CfA jobs continue to use
worktrees because their agents do mutate code.

**Chat-tier launch_cwd resolution.** When spawn_fn dispatches a member,
`teaparty.config.roster.resolve_launch_cwd()` walks the registry: if
the member is a project lead listed in `teaparty.yaml`, it returns
that project's path; otherwise it returns the dispatcher's cwd
(fallback: the teaparty repo root). Each `Session` records its
`launch_cwd` so nested dispatches (workgroup leads under project leads)
inherit the correct repo.

## What

TeaParty is a multi-agent system that uses its own `.teaparty/` folder to configure every aspect of agentic teams: roster, MCP access, skills, streaming, prompts. Those definitions are the source of truth for any interaction with agents while using the system. To facilitate research and rapid iteration, the designer uses a Claude Max account to avoid per-token costs. To stay within the Max SLA this means using `claude -p` (with `--resume` on warm restarts) rather than the Claude API.

The current state uses multiple different launch patterns, which complicates the ability to ensure that agents are using the correct `.teaparty/` configuration and compliance with the SLA. At present the designer is concerned that the code has diverged from his intent on both counts.

## Goal

The `.teaparty/` config fully determines how an agent is launched. Every agent is launched via the same function, no exceptions. Launch uses `claude -p` in compliance with the Max SLA.

## Why

Multiple launch codepaths make it impossible to verify two things that must be verifiable: that `.teaparty/` config is honored, and that every invocation complies with the Max SLA. With eight codepaths, a fix to one leaves seven unaudited. A single function is the only structure where correctness can be established once and trusted everywhere.

---

## The Invocation

Every launch produces a `claude -p` call of this shape:

```
claude -p \
  --agent {name} \
  --output-format stream-json \
  --verbose \
  --setting-sources user \
  --settings {path}              # .claude/settings.json (tool permissions, etc.)
  --agents {roster_json}         # if agent leads a workgroup or team
  --mcp-config {path}            # if agent has MCP tools
  --resume {session_id}          # if warm restart
  {message}
```

Always present: `--agent`, `--output-format stream-json`, `--verbose`, `--setting-sources user`, `--settings`. The rest are conditional on what `.teaparty/` config declares for that agent. Nothing else.

The process runs to completion, streams events, exits. One-shot with `--resume` for multi-turn continuity. No persistent processes, no NDJSON stdin, no warm caching.

## The Worktree

A session is a worktree. There is a 1:1 correspondence between sessions, worktrees, and Claude session IDs. Cold start creates both. `--resume` reuses both. CloseConversation cleans up both.

The repo checkout gives the worktree the project's files, including `.claude/CLAUDE.md`. The launcher composes additional files into the worktree:

| Worktree file | Source | Notes |
|---------------|--------|-------|
| `.claude/CLAUDE.md` | Already in the repo checkout | Not composed, not touched. Agent-specific instructions live in the agent definition. |
| `.claude/agents/{name}.md` | `{scope}/agents/{name}/agent.md` | Copied into worktree |
| `.claude/skills/{skill}/` | `{scope}/skills/{skill}/` | Filtered by agent frontmatter `skills:` allowlist. No `skills:` key means no skills. |
| `.claude/settings.json` | `{scope}/settings.yaml` merged with `{scope}/agents/{name}/settings.yaml` | Agent wins per-key; includes tool permissions |
| `.mcp.json` | Generated | Points to `http://localhost:{port}/mcp/{scope}/{agent}` |

---

## Directory Structure

### Two scopes, two tiers

Every project repo has `.teaparty/project/` — the project-level configuration. The teaparty repo additionally has `.teaparty/management/` — the cross-project management configuration. Within each scope there are two runtime tiers with separate on-disk layouts:

```
.teaparty/{scope}/
  agents/{name}/             # agent definitions (catalog)
    agent.md
    settings.yaml            # per-agent settings override (optional)
  skills/{name}/             # skill definitions (catalog)
  workgroups/{name}.yaml     # workgroup definitions (catalog)
  settings.yaml              # base settings for this scope
  sessions/                  # runtime: chat-tier sessions
    {session-id}/
      metadata.json          # session state (claude session id, agent name,
                             #   conversation map: request id → child session id)

{project}/.teaparty/jobs/    # runtime: job-tier worktrees
  jobs.json                  # job index (derived)
  job-{id}--{slug}/
    worktree/                # git worktree for the job
    job.json                 # job state
    tasks/
      tasks.json             # task index
      task-{id}--{slug}/
        worktree/            # per-task worktree (forked from job branch)
        task.json
```

Config (agents, skills, workgroups, settings) is separate from runtime. Config is checked into git. Sessions and jobs are ephemeral.

### Tier placement rule

- **Chat-tier sessions** (OM conversations, project-lead chat, configuration interactions) → `.teaparty/{scope}/sessions/{id}/`. No worktree — chat does not mutate code.
- **Job-tier worktrees** (CfA-driven work that mutates code) → `{project}/.teaparty/jobs/job-{id}--{slug}/worktree/`. Each dispatched task gets its own per-task worktree forked from the job branch.

Agent definitions may be shared (e.g., the auditor definition lives in `.teaparty/management/agents/`), but each session/job lives with the project the agent is working on.

### Agent definition resolution

The launcher resolves agent definitions by looking in the invocation scope first, then falling back to management scope. A project can override any management-level agent definition by providing its own version in `.teaparty/project/agents/`. The definition source is independent of placement.

### Job catalog

`jobs.json` indexes user-initiated work requests under `.teaparty/jobs/`. It is an index, not a container — the worktrees live in `job-{id}--{slug}/worktree/`, and the catalog points to them. Jobs go directly to the project lead.

---

## Team Hierarchy

Three things matter for each agent: who dispatches it, where its definition comes from, and where its session lives. These are independent.

### Dispatch chain

```
OM
├── project lead (one per project)
│   ├── workgroup leads
│   │   └── workgroup agents
│   └── configuration lead (project)
│       └── CRUD specialists
├── configuration lead (management)
│   └── project-specialist
└── proxy
```

`PROJECT_MANAGER` exists as a *conversation kind* in `ConversationType` — the human's dedicated chat thread with a project — but there is no intermediate project-manager *agent tier* between OM and project lead. Recursive multi-tier dispatch is tracked in the [recursive-dispatch proposal](../../proposals/recursive-dispatch/proposal.md).

### Where each agent works

| Agent | Repo | Session location |
|-------|------|-----------------|
| OM | teaparty | `.teaparty/management/sessions/` |
| Configuration lead (mgmt) | teaparty | `.teaparty/management/sessions/` |
| Project-specialist | teaparty | `.teaparty/management/sessions/` |
| Project lead | project | `{project}/.teaparty/project/sessions/` (chat) or `{project}/.teaparty/jobs/` (job tier) |
| Configuration lead (project) | project | `{project}/.teaparty/project/sessions/` |
| CRUD specialists (project) | project | `{project}/.teaparty/project/sessions/` |
| Workgroup agents | project | `{project}/.teaparty/jobs/.../tasks/` |
| Proxy | depends | session lives with the scope of the conversation |

### Roster derivation

| Agent role | Roster source |
|------------|---------------|
| Office manager | `teaparty.yaml` → project leads from `members.projects`, management config lead from `members.workgroups`, proxy from `humans:` |
| Project lead | Project team config → workgroup leads, project config lead |
| Workgroup lead | Workgroup YAML `members.agents` |
| Leaf agent | No roster |

---

## Entry Points and Session Lifecycle

### Entry points

There are four ways a conversation is initiated. All communication goes through the bus.

- **OM chat.** Human interacts with the office manager in the management chat blade.
- **Project chat.** Human interacts with a project lead in a project chat blade (the `PROJECT_MANAGER` conversation kind).
- **Proxy 1:1.** Human interacts with the proxy on any screen.
- **New job.** Human launches a job, which goes directly to the project lead.

Everything below these entry points is agents dispatching to other agents via Send.

### Session lifecycle

- **Create/Resume:** The MCP Send handler checks the dispatching agent's `metadata.json` for open slot count (max 3). If a slot is available, it creates or resumes the target session and calls the launcher. The new conversation is recorded in the dispatching agent's conversation map.
- **Work:** The agent runs to completion, streams events, returns a response.
- **Follow-up or close:** The caller (the agent or human who initiated the conversation) decides whether to send another message or close. The target agent never unilaterally closes — it responds and waits.
- **Close:** CloseConversation removes the entry from the dispatching agent's conversation map (freeing a slot) and triggers worktree cleanup on the target session.
- **Withdraw:** Iterates the agent's conversation map, closes each open conversation, cleans up all child sessions.
- **Metrics:** After each turn, `ClaudeRunner` emits a `TURN_COMPLETE` telemetry event via `teaparty.telemetry.record_event` carrying cost, tokens, duration, and turn metadata. The events are queryable via the bridge's `/api/telemetry/*` endpoints. There is no separate `metrics.db`; see [Bridge telemetry](../bridge/telemetry.md).

The launcher is stateless — it does not cache, track, or persist anything between calls.

### Session health

Two failure modes the launcher must handle:

- **Poisoned session.** MCP server fails to start → `--resume` on that session silently fails forever. Detect via `system` events, return empty session ID so caller starts fresh.
- **Empty response.** Runner completes, no assistant text → session is dead. Return empty session ID.

---

## Max SLA Constraints

The launcher must enforce these constraints on every invocation:

- Invoke via the genuine `claude` binary only.
- Never extract OAuth tokens for direct HTTP use.
- Never instrument around Claude Code's built-in throttling.
- Per-agent concurrency limit of 3 (`MAX_CONVERSATIONS_PER_AGENT`). Each dispatching agent's worktree holds a conversation map (request ID → session ID) in `metadata.json`. A slot is occupied until the conversation is closed. A fourth `Send` is refused until a slot frees, which forces the agent to close conversations when done. The map also enables graceful shutdown on withdraw. This is the only concurrency backpressure in code today; a system-wide ceiling across all agents has been discussed but not implemented.
- Let the CLI set the pace, not the orchestrator.
- Keep system prompts stable across invocations for a given agent/task.
- Use session resumption (`--resume`) rather than reconstructing context from scratch.
- Single user only.

## Stream Processing

Every launch streams events to the bus in real time: deduplicate tool_use/tool_result by ID, classify by sender type, relay immediately. This is baseline for all agents, not an OM privilege.

---

## Behaviors preserved through the unification

The unified `launch()` function preserves these behaviors, all of which are now the baseline for every agent invocation:

- **Config-driven roster.** `teaparty.config.roster.resolve_launch_cwd` and the roster-derivation helpers build a roster JSON from the workgroup/project config for any agent that leads a team. No per-agent special cases.
- **Stream event processing.** `teaparty/teams/stream.py::_classify_event` and `_make_live_stream_relay` deduplicate `tool_use`/`tool_result` by ID, classify by sender, and relay immediately to the message bus. Baseline for all agents.
- **Poisoned session detection.** `detect_poisoned_session` in `teaparty/runners/launcher.py` scans stream events for MCP-server failures and returns an empty session ID so the caller starts fresh.
- **Empty response recovery.** `should_clear_session` in `teaparty/runners/launcher.py` clears the session ID when no assistant text was produced.
- **`--setting-sources user` on every invocation.** Required for Max OAuth authentication.
- **Environment isolation.** `ClaudeRunner._build_env` strips the environment to an allowlist; agents do not inherit orchestrator credentials.
