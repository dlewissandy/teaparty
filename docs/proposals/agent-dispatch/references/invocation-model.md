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

TeaParty composes the `--agents` object for each agent at spawn time, the same way it composes the `.claude/skills/` directory. The roster defines exactly who the agent can communicate with via `Send`. An agent cannot `Send` to anyone not in its roster.

The `--agents` flag accepts a JSON object keyed by agent name. Current Claude Code documentation shows:

```json
{
  "coding-specialist": {
    "description": "Implements features and fixes bugs. Contact when you need code written, reviewed, or debugged.",
    "prompt": "You are a senior coding specialist..."
  }
}
```

**The `prompt` field conflict.** In native agent teams mode, the `prompt` field is the system prompt for the named agent. The prior design placed the recipient's `agent_id` in this field as a bus routing key, claiming it was "never used as a system prompt." Current documentation contradicts that claim: `prompt` is actively used as the agent's system prompt when native agent teams are enabled.

**Design decision: TeaParty maintains a session-scoped roster map.** The `agent_id` for bus routing is stored in a TeaParty-maintained session-scoped map keyed by agent name, independent of the `--agents` payload. The `--agents` entries carry `description` and, where appropriate, `prompt` as agent instructions — but `prompt` is not the routing key. The `Send` tool resolves the routing key by name lookup in this roster map, not by parsing the `--agents` payload. The `--agents` payload is constructed from the roster map at spawn time, but the two are separate structures.

Using `prompt` as the routing key instead depends on the field not being used as a system prompt — an assumption that breaks silently if Anthropic changes `--agents` semantics. Routing correctness cannot depend on an undocumented constraint about a field with conflicting semantics.

> **Implementation note.** The roster map (agent name → `agent_id`) is a first-class data structure maintained by TeaParty for the session's duration. It is the authoritative source for routing key resolution. The `--agents` payload at spawn time is derived from it, not the reverse.

### Entry Construction by Member Type

**Workgroup member (agent from catalog):**
- key: agent definition name from the workgroup YAML (e.g., `coding-specialist`)
- `description`: from the agent's description field in the workgroup YAML — what the agent does and when to contact it
- `agent_id` (in TeaParty roster map): `{project}/{workgroup}/{role}`, e.g., `my-backend/coding/specialist`

**Subteam lead (representing a whole workgroup):**
- key: the lead's agent definition name
- `description`: the workgroup's description — what the team does, not who the lead is. Example: "The coding team. Contact for feature implementation, bug fixes, and code review."
- `agent_id` (in TeaParty roster map): `{project}/{workgroup}/lead`

**Human participant:**
- key: participant name from the project config
- `description`: tiered by the participant's declared role on this team:
  - *Decider*: "The human decision-maker for this team. Contact for questions about scope, design, intent, or completeness. A response is required before proceeding."
  - *Advisor*: "Human advisor. Contact for guidance. Can proceed without a response if the advisor is unavailable."
  - *Inform*: "Human observer. Notify of significant events or decisions. No response expected."
- `agent_id` (in TeaParty roster map): the proxy routing key for this participant

**Requestor injection:**
When TeaParty spawns a worker or subteam in response to a `Send` call, it adds the caller's entry to the spawned agent's roster:
- key: caller's agent definition name
- `description`: "The agent that requested this task. Send questions or ask for clarification. Use Reply when your work is complete."
- `agent_id` (in TeaParty roster map): caller's `agent_id`

Every spawned agent gets a direct path back to whoever gave it the work. The worker can ask questions via `Send` and close the thread via `Reply`. Without this injection, the worker has no way to communicate upward.

## Context Boundaries

Every `claude -p` invocation starts cold — no visibility into any other agent's conversation history. A worker needs context to act effectively. The `Send` tool solves this by assembling the prior automatically before delivery.

The prior is the scratch file. The orchestrator maintains `{worktree}/.context/scratch.md` — a distilled snapshot of the job's decisions, human input, dead ends, and current state as of the spawning agent's last flush, under 200 lines and structured for progressive disclosure. See the [context budget proposal](../../context-budget/proposal.md) for the full scratch file design. What a worker at depth N receives is the invoking lead's view of job state — current from that lead's perspective, not necessarily from the top-level session lead's perspective. For a three-level chain, the worker's scratch reflects the workgroup lead's state at spawn time, which in turn reflects the session lead's state when the workgroup lead was spawned.

Each agent runs in its own worktree. The scratch file at `{worktree}/.context/scratch.md` is that agent's own file — there is no shared scratch file across agents. A worker's scratch file is seeded from the lead's state at spawn time (the lead's current scratch contents are included in the composite message the worker receives). The worker may update its own scratch file during its turn to track sub-task state. When the worker calls `Send` for a mid-task clarification, the orchestrator flushes the worker's scratch file — which reflects the lead's state at spawn time plus whatever the worker has recorded since. The lead, when re-invoked in the worker's sub-conversation, receives its own job state back as context.

Before posting, the orchestrator flushes. When `Send` is called, the orchestrator intercepts the tool call and writes the current state to the scratch file before the message is assembled. The scratch file is normally updated at turn boundaries and compaction thresholds, but a `Send` call may happen mid-turn. The flush ensures the scratch file reflects everything up to and including the turn containing the `Send`. Without this flush, the worker could receive a scratch file missing the most recent decisions.

**The composite message structure:**

```
## Task
[the agent's message]

## Context
[scratch file contents — decisions, human input, dead ends, current state as of the spawning agent's flush]
```

The Task section is what to do. The Context section is the job state from the spawning lead's perspective, structured for progressive disclosure: one-line summaries with pointers to detail files in `.context/`. The recipient reads the Task, consults the Context if needed, and follows pointers only when it needs the full rationale.

`Reply` does not inject context. A reply is a response within an established conversation; the context is already in the thread.

**Context budget constraint.** The maximum tokens in a newly spawned worker's injected context (scratch file contents plus task message) is the primary constraint Agent Dispatch places on the Context Budget proposal. That ceiling must be specified by the Context Budget proposal before dispatch feasibility can be fully evaluated. The 200-line scratch file cap is the current working bound; the token equivalent depends on content density and must be empirically characterized.

## Send Tool

`Send` is a TeaParty MCP tool for communicating with a member of the agent's roster. It opens a new conversation thread with that member, or continues an existing thread when the caller supplies an explicit context ID.

```
Send(member: str, message: str, context_id: str = None) -> None
```

`member` is the name key of a roster entry in the agent's `--agents` object. The tool resolves the `agent_id` from TeaParty's roster map (not from the `--agents` payload directly). If no matching entry exists, `Send` raises `UnknownMemberError`. For normal sends (without `context_id`), if the bus dispatcher has no routing entry for `(caller_agent_id, recipient_agent_id)`, `Send` raises `RoutingError`.

**Default behavior:** `Send` generates a new UUID4 and creates a new context. Two calls to `Send` targeting the same roster member produce two distinct context IDs and two independent threads. This is correct for parallel dispatch: the lead sends three tasks, gets three context IDs, waits for all three.

**Explicit context targeting:** when `context_id` is supplied, `Send` posts to that existing context rather than creating a new one. This is how a lead continues a multi-turn exchange with the same worker — the caller holds the context ID from the prior `Send` and passes it on the continuation call. No automatic lookup by `(caller, recipient)` pair occurs; the caller is responsible for tracking context IDs when it wants continuity.

**Directed sends and escalation.** When `context_id` is supplied for escalation (posting to a context the caller did not open), both the routing table check and the participant-set check are bypassed. Authorization rests on structural position in the conversation hierarchy alone. For escalation to the job-level context, `member` is the roster name of the session lead (for routing key resolution), and `context_id` is the injected job-level context ID. The two fields serve different purposes: `member` names the intended recipient; `context_id` directs delivery to an existing thread. When both are present for escalation, the routing table is not consulted — the conversation hierarchy position is the authorization. The full escalation model is in [Escalation Routing](conversation-model.md#escalation-routing).

Before assembling the message, the orchestrator flushes the current job state to `{worktree}/.context/scratch.md`. The tool then constructs the composite message (Task + Context envelope as described in [Context Boundaries](#context-boundaries)) and posts it to the bus.

The execution model is write-then-exit. After `Send` completes, the agent's turn ends and the process exits. TeaParty re-invokes the caller when a response arrives on the open context.

`Send` is for initiation, continuation, and escalation. Closing a thread uses `Reply`.

## Reply Tool

`Reply` is the mechanism for responding to whoever opened the current conversation thread and closing it.

```
Reply(message: str) -> None
```

Every agent knows its parent context — the conversation it was spawned into. TeaParty injects the parent `context_id` at spawn time, in the agent's initial conversation history. `Reply` reads the parent context ID from the *current conversation thread*, not from the spawn-time injection. When an agent is re-invoked via `--resume` to answer a clarification in a sub-context, the current conversation thread is that clarification context, and `Reply` targets it — not the agent's original spawn-time parent. The spawn-time injection is the context ID for the agent's own task thread; re-invocation into a different thread presents a different context ID as the current thread.

Calling `Reply` closes the thread: the agent's turn ends, the process exits, and TeaParty marks the context as closed. The `pending_count` in the parent's bus context record is decremented atomically. If the parent is waiting on multiple sub-contexts (fan-out), it is re-invoked only when all counts reach zero.

`Reply` does not construct a context envelope — the context is already established from when the thread was opened.

An agent that finishes its work calls `Reply` with the result. An agent that answers a question calls `Reply` with the answer. Both are the same call: "I'm done with this thread."

The `Send`/`Reply` distinction: `Send` is outbound initiation — the agent chooses a roster member and delivers a message with context. `Reply` is inbound response — the agent answers whoever spawned it and closes the thread.

## Multi-Turn Clarification vs. Fan-In Re-Invocation

These are distinct re-invocation triggers with different lifecycle consequences.

Fan-in re-invocation: the lead exits after calling `Send` (write-then-exit). When all workers call `Reply`, `pending_count` reaches zero and TeaParty re-invokes the lead in the parent context to synthesize results.

Mid-task clarification: a worker calls `Send` targeting the lead (via requestor injection), opening a new clarification context. The lead is re-invoked in that clarification context — not the parent context — to answer the question. The fan-in `pending_count` is unchanged. When the lead calls `Reply` in the clarification context, that clarification thread closes; its own `pending_count` record is what gets decremented, not the task thread's. The worker's task thread remains open. The full `pending_count` lifecycle is in [Fan-In vs. Mid-Task Clarification](conversation-model.md#fan-in-vs-mid-task-clarification).

TeaParty serializes re-invocations of the same lead agent via a per-agent-id re-invocation lock. The lock is held by the bus event listener from the time it issues `--resume` until the process exits. If a clarification re-invocation and a fan-in re-invocation arrive near-simultaneously, the second queues until the first completes. The heartbeat dead-threshold (>300 seconds) bounds how long any queued re-invocation can wait before the open context is marked abandoned and a synthetic error is delivered.

## Bus Context Record

Re-invocation, fan-in, and authorization all read from the bus context record. All fields are stored in the durable bus store:

| Field | Type | Description |
|---|---|---|
| `context_id` | string | Stable identifier for this conversation context |
| `initiator_agent_id` | string | Agent that opened the context via `Send` |
| `recipient_agent_id` | string | Agent the context was addressed to |
| `session_id` | string | Claude Code session ID for the recipient's conversation thread |
| `status` | enum | `open` or `closed` |
| `pending_count` | int | Number of outstanding sub-contexts not yet closed (for fan-in) |
| `participant_set` | set\<agent_id\> | Agents authorized to post to this context via normal `Send` |

**`pending_count` lifecycle.** The parent context record is created when the lead's first turn opens (at session start, `pending_count = 0`). Each `Send` call that creates a sub-context requires a two-record atomic write: the new sub-context record and the `pending_count` increment in the parent record must both succeed or both fail. A crash between the two writes would leave an orphaned sub-context with no corresponding increment — the fan-in counter would be permanently wrong. The Messaging proposal must provide a two-record atomicity mechanism (SQLite transaction, multi-key CAS, or equivalent) to satisfy this requirement. Fan-in fires when `pending_count` reaches zero after at least one decrement. A lead that sends three parallel `Send` calls leaves the parent record with `pending_count = 3`; each worker `Reply` decrements it; the third `Reply` triggers re-invocation.

`pending_count` is decremented atomically by the MCP server's `Reply` handler. The MCP tool layer creates and updates records; the bus dispatcher reads them to authorize posts. The two roles are partitioned: the dispatcher is read-only for authorization.

**`participant_set` and authorization.** `participant_set` is initialized with `{initiator_agent_id, recipient_agent_id}` and frozen at context creation. Normal `Send` calls check both the routing table and the participant set. The participant-set check is defense-in-depth: the routing table confirms the sender can reach the recipient in general, while the participant set confirms the sender belongs in this particular conversation thread. These are different predicates. For agents posting directly through `Send`, the two checks never diverge. The participant-set check catches the case where an agent bypasses `Send` and writes directly to the bus transport — the routing table confirms the sender/recipient pair is valid, but the participant set confirms the sender is authorized for this specific thread. Directed sends that supply an explicit context ID for escalation bypass the participant-set check entirely; authorization is by conversation hierarchy position.

`session_id` is captured from the recipient's first invocation (`--output-format json` returns `session_id` in its output). TeaParty stores it here so subsequent re-invocations can use `--resume $session_id`.

## Parallel Dispatch and Fan-In

A lead can post multiple parallel `Send` calls before exiting. Each call opens a thread with a different roster member.

Fan-in correctness is maintained by the bus, not by the lead. When TeaParty creates a sub-context for each `Send` call, it increments `pending_count` in the parent context's bus record atomically with the sub-context write. When a sub-context closes (the worker calls `Reply`), TeaParty atomically decrements `pending_count`. The lead is re-invoked only when `pending_count` reaches zero.

The lead records outstanding context IDs in its conversation history before exiting — for example: "Sent tasks to coding-specialist (ctx-A), qa-reviewer (ctx-B), doc-writer (ctx-C). Waiting for all three to Reply." This narration is advisory: it gives a human reviewer a clear picture of what was in flight. The `pending_count` mechanism fires re-invocation correctly whether or not the lead narrated the context IDs. The platform does not depend on agent self-reporting to track completions.

Atomic `pending_count` management eliminates the double-resume race: two near-simultaneous replies cannot trigger two `--resume` invocations, because only the decrement that brings the count to zero fires re-invocation, and that decrement is atomic in the bus store.

## Skill Scope Suppression

```bash
claude -p \
  --output-format json \
  --bare \
  --settings "{...agent-specific MCP config...}" \
  --agent {agent-name} \
  --agents '{...composed roster entries...}' \
  "$TASK"
```

`--bare` suppresses auto-discovery of hooks, skills, plugins, MCP servers, auto memory, and CLAUDE.md, so the agent sees exactly the composed worktree set and nothing from `~/.claude/`. The CLI reference describes `--bare` as the recommended mode for programmatic invocations.

`--setting-sources project` is a different flag that controls which settings files are loaded (user, project, or local scope). It does not govern skill directory scanning and must not be used as a substitute for `--bare`.

`--output-format json` is required so TeaParty can capture the `session_id` field from the output. That session ID is stored in the bus conversation context record. When a response arrives for a given context ID, TeaParty retrieves the corresponding session ID and re-invokes the caller with `--resume $SESSION_ID`. `--resume` reuses the original session ID — it does not generate a new one unless `--fork-session` is explicitly passed. Using `--fork-session` in the re-invocation path would create a new session ID, breaking the stable-ID invariant that multi-turn conversations depend on.

`--agents` receives the composed roster as an inline JSON object. TeaParty constructs this object at spawn time from the workgroup membership, requestor injection, and any human participants, as described in [Agent Roster Composition](#agent-roster-composition). The `agent_id` for bus routing is stored in TeaParty's roster map, not in the `--agents` payload.

**Session ID and re-invocation decision rule.** First invocation: TeaParty does not pre-assign a session ID. The session ID is captured from the first invocation's stream output — the `system/init` event's `session_id` field, extracted by `_maybe_extract_session_id` in `claude_runner.py`. Re-invocation: TeaParty uses `--resume $SESSION_ID` with the captured ID. `--session-id` (pre-assigning a UUID at dispatch time rather than capturing it from output) is a documented CLI flag, but the current TeaParty orchestrator does not use it — and there is no confirmed behavior for combining `--session-id` with `--resume`. Treat `--session-id` as a capability that may be used in the new bus dispatcher implementation, but verify the flag's behavior under `--resume` before relying on it.

## MCP Scoping

Each invocation receives its MCP configuration via `--settings` inline JSON. The MCP server is always the TeaParty MCP server, but the tools surface varies by role:

- Config team agents: AddProject, CreateProject, CreateAgent, CreateSkill, etc.
- Coding agents: code tools only; no config tools
- Research agents: research tools only; no config or code tools

`disallowedTools` in the agent definition provides the denylist. The `--settings` override narrows further at invocation time if needed. The merge behavior of inline `--settings` with the agent definition's settings is not documented in the current public Claude Code docs — specifically, whether `disallowedTools` entries accumulate or replace when both sources specify them. This must be empirically validated before relying on accumulation semantics.

Agents that should not initiate communication have `Send` in their `disallowedTools`. An agent with only `Reply` available can do its work and report back but cannot open new threads.

## Worktree Reuse

For multi-turn conversations, the same worktree is reused. The agent is re-invoked via `--resume $SESSION_ID` with the updated conversation history appended to the local conversation state before re-invocation.

**Injection schema.** The JSONL injection schema is not a documented public API. Observed structure from live session history files:

```json
{
  "parentUuid": "<uuid-of-prior-entry or null>",
  "isSidechain": true,
  "userType": "external",
  "cwd": "<working directory>",
  "sessionId": "<session UUID>",
  "version": "<claude-code version>",
  "type": "user",
  "message": {
    "role": "user",
    "content": "..."
  },
  "uuid": "<this entry's UUID>",
  "timestamp": "<ISO 8601 with milliseconds>"
}
```

Fields observed as present on every entry: `uuid`, `parentUuid` (null on first entry), `timestamp`, `type`, `message`, `sessionId`, `cwd`. Injected bus messages are written as `type: "user"` entries so the model sees them as incoming input. The linked-list structure is `uuid` → `parentUuid`. This schema is reverse-engineered from the TeaParty project's own session history files. It is not a stable API contract — if Claude Code changes this format, the re-invocation path requires updating, but the bus records (session IDs, context IDs, pending state) remain intact and recovery is repairable.

**Path note.** All observable session files in this project's `~/.claude/projects/` directory follow the path `<session-uuid>/subagents/<agent-id>.jsonl`. The flat path format (`<session-uuid>.jsonl`) constructed by `office_manager.py` and `proxy_review.py` matches no current on-disk session file — those code paths appear stale relative to how Claude Code now writes session history. Whether `claude -p` (non-subagent) invocations also write to the `subagents/` subdirectory, or use a different path entirely, has not been verified against a live standalone `claude -p` session. The entire injection path must be verified by running a `claude -p` invocation and observing the resulting session file location before the bus dispatcher's injection logic is built.

The worktree is not rebuilt each turn, only per conversation context. Cleanup happens when the conversation closes — when the recipient calls `Reply`, marking the context closed and triggering worktree removal after the closing message is delivered.

If an agent crashes before calling `Reply`, the conversation is abandoned. TeaParty detects abandonment via the heartbeat mechanism (`orchestrator/heartbeat.py`): the orchestrator wrapper touches the `.heartbeat` file every 30 seconds on behalf of each running `claude -p` process. A context ID whose recipient worktree heartbeat has not been updated within the stale threshold (30–300 seconds) or dead threshold (>300 seconds) is marked abandoned, the worktree is cleaned up, and the caller receives a synthetic error response on the context ID. The synthetic error response triggers the same `pending_count` decrement as a normal `Reply` — the bus event listener's abandonment handler writes it directly, using the same atomic path as the `Reply` MCP handler. The caller is re-invoked with the error response as if it were a normal reply. Agent-to-agent invocations go through the same orchestrator wrapper (`claude_runner.py`) as dispatch invocations, so the heartbeat convention applies.

## Routing Table Recovery After Restart

The routing table is ephemeral — held in memory by the bus event listener, not persisted between sessions. The bus context records are durable. After a restart, the bus contains open context records for in-flight conversations, but the routing table is empty.

Recovery requires rebuilding the routing table from bus state before re-invoking any waiting callers. The recovery procedure: on restart, TeaParty reads all open bus context records. For each record, the `initiator_agent_id` and `recipient_agent_id` fields are present. TeaParty re-derives the routing entries for these pairs from the session's configuration YAML (the same derivation that runs at session start) and repopulates the routing table. Callers with open contexts are then re-invoked in dependency order.

Dependency ordering normally follows a topological sort over the `(initiator_agent_id, recipient_agent_id)` DAG in the open bus records — workers before leads, since leads wait on workers. However, mid-task clarification creates a cycle: if a restart occurs while a clarification thread is open, the bus records contain both `(lead, worker)` (the task thread) and `(worker, lead)` (the clarification thread) as active edges. Topological sort is undefined on a cyclic graph. On cycle detection, TeaParty identifies all agents involved in the cycle as a clarification-in-progress: it re-invokes them simultaneously with their current bus record state, rather than attempting to sequence them. Both the task thread and the clarification thread are re-opened concurrently; the per-agent re-invocation lock ensures that if the same agent appears in both threads, its re-invocations are serialized. This resolves the ambiguity without requiring topological ordering over the cycle.

This recovery path depends on the `agent_id` derivation algorithm (#348), which is not yet implemented. Until that algorithm exists, the recovery procedure cannot be executed. The durability claim is contingent on both the durable bus store and the derivation algorithm being in place.

If configuration has changed between crash and restart such that a previously valid routing pair is no longer derivable, the context is marked abandoned and a synthetic error is delivered to the caller. The durability guarantee covers clean restarts where configuration is unchanged; it does not cover configuration changes made during a crash window.
