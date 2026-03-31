[Agent Dispatch](../proposal.md) >

# Invocation Model

## Worktree Composition

Before spawning an agent, TeaParty creates a git worktree for the target project and composes its `.claude/skills/` directory from the central skill library.

`teaparty_home` is the TeaParty installation root (e.g. `~/.teaparty/` or the repo root for local development). The skill library lives at `teaparty_home/skills/` with subdirectories `common/` and `roles/{role}/`. Project skills live in the project's own `.claude/skills/`. Each entry in those directories is itself a directory (the `{name}/SKILL.md` layout), so composition uses directory-level symlinks, not glob expansion:

```bash
git worktree add /tmp/tp/agent-{id} HEAD
mkdir -p /tmp/tp/agent-{id}/.claude/skills

# Compose: common + role + project (project wins on name collision)
for skill in $TEAPARTY_HOME/skills/common/*/; do
    ln -s "$skill" /tmp/tp/agent-{id}/.claude/skills/
done
for skill in $TEAPARTY_HOME/skills/roles/{role}/*/; do
    ln -s "$skill" /tmp/tp/agent-{id}/.claude/skills/
done
for skill in $PROJECT/.claude/skills/*/; do
    ln -s "$skill" /tmp/tp/agent-{id}/.claude/skills/
done
```

Name collisions are resolved by composition order — project overrides role overrides common — following the same override semantics as the workgroup skills catalog. The orchestrator logs any collision at composition time, noting which skill was overridden and by which source.

The orchestrator writes any required `.claude/settings.json` (hooks, permissions) into the worktree before spawning.

## Agent Roster Composition

TeaParty composes the `--agents` list for each agent at spawn time, the same way it composes the `.claude/skills/` directory. The roster defines exactly who the agent can communicate with via `Send`. An agent cannot `Send` to anyone not in its roster.

Each roster entry uses the three fields required by the Claude CLI:

```json
{
  "name": "coding-specialist",
  "description": "Implements features and fixes bugs. Contact when you need code written, reviewed, or debugged.",
  "prompt": "my-backend/coding/specialist"
}
```

- **`name`** — the agent's name from the TeaParty agent catalog, or a human participant's name from the project config. Used by the LLM to address the member in a `Send` call.
- **`description`** — the routing guide. The LLM reads descriptions to decide who to `Send` to. This is the primary signal for routing decisions; there is no other mechanism. Descriptions must be specific enough for the lead to distinguish members and know when to contact each one.
- **`prompt`** — coopted by TeaParty for bus routing. It is never used as a system prompt. Contains the recipient's `agent_id` — the key the `Send` tool reads to route the message on the bus.

### Entry Construction by Member Type

**Workgroup member (agent from catalog):**
- `name`: agent definition name from the workgroup YAML (e.g., `coding-specialist`)
- `description`: from the agent's description field in the workgroup YAML — what the agent does and when to contact it
- `prompt`: the member's `agent_id` (`{project}/{workgroup}/{role}`, e.g., `my-backend/coding/specialist`)

**Subteam lead (representing a whole workgroup):**
- `name`: the lead's agent definition name
- `description`: the workgroup's description — what the team does, not who the lead is. Example: "The coding team. Contact for feature implementation, bug fixes, and code review."
- `prompt`: the lead's `agent_id` (`{project}/{workgroup}/lead`)

**Human participant:**
- `name`: participant name from the project config
- `description`: tiered by the participant's declared role on this team:
  - *Decider*: "The human decision-maker for this team. Contact for questions about scope, design, intent, or completeness. A response is required before proceeding."
  - *Advisor*: "Human advisor. Contact for guidance. Can proceed without a response if the advisor is unavailable."
  - *Inform*: "Human observer. Notify of significant events or decisions. No response expected."
- `prompt`: the proxy routing key for this participant — identifies the proxy conversation context that `Send` delivers to

**Requestor injection:**
When TeaParty spawns a worker or subteam in response to a `Send` call, it adds the caller's entry to the spawned agent's roster:
- `name`: caller's agent definition name
- `description`: "The agent that requested this task. Send questions or ask for clarification. Use Reply when your work is complete."
- `prompt`: caller's `agent_id`

This gives every spawned agent a direct path back to whoever gave it the work. The worker can ask questions via `Send` and close the thread via `Reply`. Without this injection, the worker would have no way to communicate upward.

## Context Boundaries

Every `claude -p` invocation starts cold — no visibility into any other agent's conversation history. A worker needs context to act effectively. The `Send` tool solves this by assembling the prior automatically before delivery.

**The prior is the scratch file.** The orchestrator maintains `{worktree}/.context/scratch.md` — a current snapshot of the job's decisions, human input, dead ends, and current state, under 200 lines and structured for progressive disclosure. See the [context budget proposal](../../context-budget/proposal.md) for the full scratch file design. The scratch file is the distilled picture of the job: what has been decided, what has been tried, where things stand. It is exactly what a newly spawned agent needs.

**Before posting, the orchestrator flushes.** When `Send` is called, the orchestrator intercepts the tool call and writes the current state to the scratch file before the message is assembled. This is critical: the scratch file is normally updated at turn boundaries and compaction thresholds, but a `Send` call may happen mid-turn. The flush ensures the scratch file reflects everything that has happened up to and including the turn containing the `Send` — not just what was known at the last scheduled update. Without this flush, the worker could receive a scratch file that is missing the most recent decisions.

**The composite message structure:**

```
## Task
[the agent's message]

## Context
[scratch file contents — current snapshot of job state, decisions, human input, dead ends]
```

Task section is what to do. Context section is the current state of the job, structured for progressive disclosure: one-line summaries with pointers to detail files in `.context/`. The recipient reads the Task, consults the Context if needed, and follows pointers only when it needs the full rationale. The recipient does not need to read everything — only what is relevant to its work.

`Reply` does not inject context. A reply is a response within an established conversation; the context is already in the thread.

## Send Tool

`Send` is a TeaParty MCP tool for communicating with a member of the agent's roster. It opens a new conversation thread or continues an existing open thread with that member.

```
Send(member: str, message: str) -> None
```

`member` is the `name` field of a roster entry in the agent's `--agents` list. The tool resolves the `agent_id` from the `prompt` field of the matching entry. If no matching entry exists, `Send` raises `UnknownMemberError` — the agent cannot contact anyone not in its roster. If the bus dispatcher has no routing entry for `(caller_agent_id, recipient_agent_id)`, `Send` raises `RoutingError`.

Before assembling the message, the orchestrator flushes the current job state to `{worktree}/.context/scratch.md`. The tool then constructs the composite message (Task + Context envelope as described in [Context Boundaries](#context-boundaries)) and posts it to the bus.

Thread continuity: if an open `context_id` already exists for the `(caller_agent_id, recipient_agent_id)` pair, `Send` posts to that context rather than creating a new one. This allows a lead to have an ongoing multi-turn exchange with a worker using the same tool — no separate "continue" primitive is needed. If no open context exists, `Send` creates a new one.

The execution model is write-then-exit. After `Send` completes, the agent's turn ends and the process exits. TeaParty re-invokes the caller when a response arrives on the open context.

`Send` is for initiation and continuation. Closing a thread uses `Reply`.

## Reply Tool

`Reply` is the mechanism for responding to whoever opened the current conversation thread and closing it.

```
Reply(message: str) -> None
```

Every agent knows its parent context — the conversation it was spawned into. TeaParty injects the parent `context_id` at spawn time, in the agent's initial conversation history. `Reply` reads this injected context ID and posts the message to it.

Calling `Reply` closes the thread: the agent's turn ends, the process exits, and TeaParty marks the context as closed. The `pending_count` in the parent's bus context record is decremented atomically. If the parent is waiting on multiple sub-contexts (fan-out), it is re-invoked only when all counts reach zero.

`Reply` does not construct a context envelope. It is a terminal response, not initiation — the recipient already has the context it needs from when the thread was opened.

An agent completes its work and calls `Reply` with the result. An agent that was asked a question calls `Reply` with the answer. An agent that escalated and received a resolution calls `Reply` to close the escalation thread.

The distinction between `Send` and `Reply`:
- `Send` is outbound initiation — the agent chooses a roster member and delivers a message with context
- `Reply` is inbound response — the agent answers whoever spawned it and closes the thread

An agent that only needs to do work and report back only ever uses `Reply`. An agent that coordinates a team uses `Send` to delegate and `Reply` to report its own results upward.

## Bus Context Record

The bus context record is the load-bearing data structure for re-invocation, fan-in, and authorization. All fields are stored in the durable bus store:

| Field | Type | Description |
|---|---|---|
| `context_id` | string | Stable identifier for this conversation context |
| `initiator_agent_id` | string | Agent that opened the context via `Send` |
| `recipient_agent_id` | string | Agent the context was addressed to |
| `session_id` | string | Claude Code session ID for the recipient's conversation thread |
| `status` | enum | `open` or `closed` |
| `pending_count` | int | Number of outstanding sub-contexts not yet closed (for fan-in) |
| `participant_set` | set\<agent_id\> | Agents authorized to post to this context |

`pending_count` is decremented atomically by TeaParty each time a sub-context closes via `Reply`. The initiator is re-invoked only when `pending_count` reaches zero. This makes fan-in correctness a platform responsibility, tracked in the bus record, not in agent narration.

`participant_set` is initialized with `{initiator_agent_id, recipient_agent_id}`. `Send` and `Reply` authorization checks both the routing table and the participant set.

`session_id` is captured from the recipient's first invocation (`--output-format json` returns `session_id` in its output). TeaParty stores it here so subsequent re-invocations can use `--resume $session_id`.

## Parallel Dispatch and Fan-In

A lead can post multiple parallel `Send` calls before exiting. Each call opens a thread with a different roster member. Before its turn ends, the lead records all outstanding context IDs in the conversation history — for example: "Sent tasks to coding-specialist (ctx-A), qa-reviewer (ctx-B), doc-writer (ctx-C). Waiting for all three to Reply."

Fan-in correctness is maintained by the bus, not by the lead. When TeaParty creates a sub-context for each `Send` call, it increments the `pending_count` in the parent context's bus record. When a sub-context closes (the worker calls `Reply`), TeaParty atomically decrements `pending_count`. The lead is re-invoked only when `pending_count` reaches zero.

This removes the race condition that would arise from having the lead check its own pending set from conversation history: two near-simultaneous replies arriving concurrently could trigger two `--resume` invocations, both reading the same "still waiting" state and both exiting without synthesizing. Atomic `pending_count` management in the bus record eliminates this; only one re-invocation fires — the one triggered by the last reply closing — and it fires when the count is known to be zero.

There is no barrier primitive visible to the lead. The lead sends, records its intent, and exits. TeaParty handles the rest.

## Skill Scope Suppression

```bash
claude -p \
  --output-format json \
  --bare \
  --settings "{...agent-specific MCP config...}" \
  --agent {agent-name} \
  --agents '[{...composed roster entries...}]' \
  "$TASK"
```

`--bare` suppresses auto-discovery of hooks, skills, plugins, MCP servers, auto memory, and CLAUDE.md, so the agent sees exactly the composed worktree set and nothing from `~/.claude/`. The headless documentation identifies `--bare` as the recommended mode for programmatic invocations and notes it will become the default for `-p` in a future release.

`--setting-sources project` is a different flag that controls which settings files are loaded (user, project, or local scope). It does not govern skill directory scanning and must not be used as a substitute for `--bare`.

`--output-format json` is required so TeaParty can capture the `session_id` field from the output. That session ID is stored in the bus conversation context record. When a response arrives for a given context ID, TeaParty retrieves the corresponding session ID and re-invokes the caller with `--resume $SESSION_ID`. `--resume` reuses the original session ID — it does not generate a new one unless `--fork-session` is explicitly passed. `--fork-session` must not appear in the re-invocation path; it would create a new session ID and break the stable-ID invariant that multi-turn conversations depend on.

`--agents` receives the composed roster as an inline JSON array. TeaParty constructs this array at spawn time from the workgroup membership, requestor injection, and any human participants, as described in [Agent Roster Composition](#agent-roster-composition). The `prompt` field of each entry carries the recipient's `agent_id` for bus routing — it is not used by Claude as a system prompt.

TeaParty can also set session IDs explicitly via `--session-id <uuid>`, assigning the ID at dispatch time rather than capturing it from the first invocation's output. Either approach is valid; the bus context record stores whichever ID was used.

## MCP Scoping

Each invocation receives its MCP configuration via `--settings` inline JSON. The MCP server is always the TeaParty MCP server, but the tools surface varies by role:

- Config team agents: AddProject, CreateProject, CreateAgent, CreateSkill, etc.
- Coding agents: code tools only; no config tools
- Research agents: research tools only; no config or code tools

`disallowedTools` in the agent definition provides the denylist. The `--settings` override narrows further at invocation time if needed. An inline `--settings` JSON merges with the agent definition's settings; `disallowedTools` entries accumulate rather than replace.

Agents that should not initiate communication have `Send` in their `disallowedTools`. An agent with only `Reply` available can do its work and report back but cannot open new threads. This is the right configuration for leaf workers that receive a task, execute it, and return a result.

## Worktree Reuse

For multi-turn conversations, the same worktree is reused. The agent is re-invoked via `--resume $SESSION_ID` with the updated conversation history appended to the local conversation state before re-invocation.

Conversation history lives at `~/.claude/projects/<encoded-cwd>/<session-id>.jsonl` (JSONL format, confirmed by the Agent SDK sessions documentation and the TeaParty codebase). TeaParty appends the incoming bus message to this file, then calls `--resume`. This is an integration against a Claude Code internal file — there is no documented public interface for external injection into session files. The file location and JSONL format are confirmed, but external writes are not an endorsed API contract. This is a known integration point that may need revision if Claude Code changes its internal session file format.

The worktree is not rebuilt each turn, only per conversation context. Cleanup happens when the conversation closes. A conversation closes when the recipient calls `Reply` — posting a terminal response and marking the context closed. TeaParty removes the worktree after the closing message is delivered.

If an agent crashes before calling `Reply`, the conversation is abandoned. TeaParty detects abandonment via the heartbeat mechanism (`orchestrator/heartbeat.py`): the orchestrator wrapper touches the `.heartbeat` file every 30 seconds on behalf of each running `claude -p` process. A context ID whose recipient worktree heartbeat has not been updated within the stale threshold (30–300 seconds) or dead threshold (>300 seconds) is marked abandoned, the worktree is cleaned up, and the caller receives a synthetic error response on the context ID. The synthetic error response is treated as a closed thread so that any fan-in `pending_count` decrement fires correctly. Agent-to-agent invocations go through the same orchestrator wrapper (`claude_runner.py`) as dispatch invocations, so the heartbeat convention applies.
