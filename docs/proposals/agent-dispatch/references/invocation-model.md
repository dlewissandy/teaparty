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

## AskTeam Tool

`AskTeam` is a TeaParty MCP tool available to agents with bus-posting access. It initiates a new conversation with a recipient agent.

```
AskTeam(role: str, message: str) -> context_id: str
```

`role` is the recipient's role name, scoped to the caller's own workgroup. If the same role name exists in another workgroup in the project, it is not a candidate — matching is confined to the workgroup the calling agent belongs to. `message` is the initial request.

The execution model is write-then-exit. `AskTeam` posts the message to the bus, records the returned `context_id` into the conversation history before the turn ends, and then the agent process exits. The `context_id` is not a live in-memory reference; it is a durable record of the outstanding request. TeaParty re-invokes the caller when a response arrives.

If the caller has no routing access to the specified role, `AskTeam` raises a `RoutingError` before posting. The message is never written to the bus; the caller handles the error in the same turn.

**`AskTeam` is for initiating new conversations only.** Responding within an existing conversation uses the `ReplyTo` tool.

## ReplyTo Tool

`ReplyTo` is the mechanism for posting a response on an existing conversation context. Workers use it to reply to a lead's `AskTeam` request; leads use it for follow-up messages within an open conversation.

```
ReplyTo(context_id: str, message: str) -> None
```

`context_id` is the conversation context to post on. The bus validates that the caller has access to this context ID before accepting the message. Posting to a context ID the caller did not participate in raises `RoutingError`. After calling `ReplyTo`, the agent's turn ends and the process exits.

The distinction between `AskTeam` and `ReplyTo` is creation vs. continuation. `AskTeam` creates a new conversation and returns the context ID. `ReplyTo` posts onto an existing one. A recipient agent receives the context ID in its conversation history when TeaParty spawns it; that context ID is what it passes to `ReplyTo` when answering.

## Bus Context Record

The bus context record is the load-bearing data structure for re-invocation, fan-in, and authorization. All fields are stored in the durable bus store:

| Field | Type | Description |
|---|---|---|
| `context_id` | string | Stable identifier for this conversation context |
| `initiator_agent_id` | string | Agent that created the context via `AskTeam` |
| `recipient_agent_id` | string | Agent the context was addressed to |
| `session_id` | string | Claude Code session ID for the recipient's conversation thread |
| `status` | enum | `open` or `closed` |
| `pending_count` | int | Number of outstanding sub-contexts not yet closed (for fan-in) |
| `participant_set` | set\<agent_id\> | Agents authorized to post to this context via `ReplyTo` |

`pending_count` is decremented atomically by TeaParty each time a sub-context closes. The lead is re-invoked only when `pending_count` reaches zero. This makes fan-in correctness a platform responsibility, tracked in the bus record, not in agent narration.

`participant_set` is initialized with `{initiator_agent_id, recipient_agent_id}`. The routing table governs who can be added. `ReplyTo` authorization checks both the routing table and the participant set.

`session_id` is captured from the recipient's first invocation (`--output-format json` returns `session_id` in its output). TeaParty stores it here so subsequent re-invocations can use `--resume $session_id`.

## Parallel Dispatch and Fan-In

A lead can post multiple parallel `AskTeam` requests before exiting. Each call returns a `context_id`. Before its turn ends, the lead records all outstanding context IDs in the conversation history — for example: "Posted requests to coding-worker (ctx-A), qa-reviewer (ctx-B), doc-writer (ctx-C). Waiting for all three."

Fan-in correctness is maintained by the bus, not by the lead. When TeaParty creates a sub-context for each parallel `AskTeam` call, it increments the `pending_count` in the parent context's bus record. When a sub-context closes (the worker sends a terminal response), TeaParty atomically decrements `pending_count`. The lead is re-invoked only when `pending_count` reaches zero.

This removes the race condition that would arise from having the lead check its own pending set from conversation history: two near-simultaneous responses arriving concurrently could trigger two `--resume` invocations, both reading the same "still waiting" state and both exiting without synthesizing. Atomic `pending_count` management in the bus record eliminates this; only one re-invocation fires — the one triggered by the last response closing — and it fires when the count is known to be zero.

There is no barrier primitive visible to the lead. The lead posts, records its intent, and exits. TeaParty handles the rest.

## Skill Scope Suppression

```bash
claude -p \
  --output-format json \
  --bare \
  --settings "{...agent-specific MCP config...}" \
  --agent {agent-name} \
  "$TASK"
```

`--bare` is the correct flag for scripted `claude -p` calls. It suppresses auto-discovery of hooks, skills, plugins, MCP servers, auto memory, and CLAUDE.md, so the agent sees exactly the composed worktree set and nothing from `~/.claude/`. The headless documentation identifies `--bare` as the recommended mode for programmatic invocations and notes it will become the default for `-p` in a future release.

`--setting-sources project` is a different flag that controls which settings files are loaded (user, project, or local scope). It does not govern skill directory scanning and must not be used as a substitute for `--bare`.

`--output-format json` is required so TeaParty can capture the `session_id` field from the output. That session ID is stored in the bus conversation context record. When a response arrives for a given context ID, TeaParty retrieves the corresponding session ID and re-invokes the caller with `--resume $SESSION_ID`. `--resume` reuses the original session ID — it does not generate a new one unless `--fork-session` is explicitly passed. `--fork-session` must not appear in the re-invocation path; it would create a new session ID and break the stable-ID invariant that multi-turn conversations depend on.

TeaParty can also set session IDs explicitly via `--session-id <uuid>`, assigning the ID at dispatch time rather than capturing it from the first invocation's output. Either approach is valid; the bus context record stores whichever ID was used.

## MCP Scoping

Each invocation receives its MCP configuration via `--settings` inline JSON. The MCP server is always the TeaParty MCP server, but the tools surface varies by role:

- Config team agents: AddProject, CreateProject, CreateAgent, CreateSkill, etc.
- Coding agents: code tools only; no config tools
- Research agents: research tools only; no config or code tools

`disallowedTools` in the agent definition provides the denylist. The `--settings` override narrows further at invocation time if needed. An inline `--settings` JSON merges with the agent definition's settings; `disallowedTools` entries accumulate rather than replace.

## Worktree Reuse

For multi-turn conversations, the same worktree is reused. The agent is re-invoked via `--resume $SESSION_ID` with the updated conversation history appended to the local conversation state before re-invocation.

Conversation history lives at `~/.claude/projects/<encoded-cwd>/<session-id>.jsonl` (JSONL format, confirmed by the Agent SDK sessions documentation and the TeaParty codebase). TeaParty appends the incoming bus message to this file, then calls `--resume`. This is an integration against a Claude Code internal file — there is no documented public interface for external injection into session files. The file location and JSONL format are confirmed, but external writes are not an endorsed API contract. This is a known integration point that may need revision if Claude Code changes its internal session file format.

The worktree is not rebuilt each turn, only per conversation context. Cleanup happens when the conversation closes. A conversation closes when the recipient sends a terminal response — a bus message with `status: closed` on the context ID. The caller reads the closed status on re-invocation and does not post further to that context. TeaParty removes the worktree after the closing message is delivered.

If an agent crashes before sending a terminal response, the conversation is abandoned. TeaParty detects abandonment via the heartbeat mechanism (`orchestrator/heartbeat.py`): the orchestrator wrapper touches the `.heartbeat` file every 30 seconds on behalf of each running `claude -p` process. A context ID whose recipient worktree heartbeat has not been updated within the stale threshold (30–300 seconds) or dead threshold (>300 seconds) is marked abandoned, the worktree is cleaned up, and the caller receives a synthetic error response on the context ID. The synthetic error response carries `status: closed` so that any fan-in pending-count decrement fires correctly. Agent-to-agent invocations go through the same orchestrator wrapper (`claude_runner.py`) as dispatch invocations, so the heartbeat convention applies.
