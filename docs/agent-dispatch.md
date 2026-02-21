# Agent Dispatch

How TeaParty routes messages to agents and how agent responses are produced.

TeaParty does not select speakers or orchestrate turn-taking. It dispatches user messages to Claude, which handles all coordination autonomously. Multi-agent collaboration uses Claude's native team sessions with streaming I/O.

---

## Routing Table

| Conversation kind | Trigger | Path | What happens |
|---|---|---|---|
| `job` + `@each` | User message | `_run_single_agent_responses` | Independent fan-out: one `claude -p` per agent, run sequentially |
| `job` + `@all`/`@team` | User message | `_run_team_response` | Persistent team session with all agents |
| `job` + `@name` | User message | `_run_single_agent_responses` | Single named agent only |
| `job` (default, multi-agent) | User message | `_run_team_response` | Persistent team session |
| `job` (default, single agent) | User message | `_run_single_agent_responses` | Single agent |
| `direct` | User message | `_run_single_agent_responses` | Single participating agent |
| `task` | User message | `_run_single_agent_responses` | Single agent with persistent Claude session |
| `engagement` | User message | `_run_single_agent_responses` | Single org lead agent |
| `project` | User message | `_run_team_response` | Persistent team session with workgroup leads |
| `admin` | User message | `build_admin_agent_reply` | Deterministic command handler (no LLM selection) |
| `activity` | Any | None | No auto-response |

**Priority**: `@each` is checked before `@all`/`@team`. If both appear, fan-out wins.

**Guard**: Only user messages trigger responses in job conversations. Agent messages are ignored to prevent re-triggering loops.

---

## Multi-Agent Team Sessions

When multiple agents need to collaborate (job conversations with 2+ agents), TeaParty uses **persistent team sessions** — long-lived `claude` processes with bidirectional `stream-json` I/O.

### Architecture

```
User message
    |
    v
_run_team_response()          # agent_runtime.py
    |
    v
get_or_create_session()       # team_registry.py — reuses existing or spawns new
    |
    v
TeamSession.start()           # team_session.py — spawns: claude --input-format stream-json
    |                                               --output-format stream-json --agents {...}
    v                                               --agent <lead-slug> --verbose
TeamSession.send_message()    # writes {"type": "user_message", "content": "..."} to stdin
    |
    v
process_team_events_sync()    # team_bridge.py — reads events from stdout, stores as Messages
    |
    v
Messages appear in chat       # Frontend picks them up via pollMessages()
```

### How streaming works

1. `TeamSession` reads `stream-json` events line-by-line from the `claude` process stdout
2. Events are parsed into `TeamEvent` objects and pushed to an `asyncio.Queue`
3. `team_bridge.py` drains the queue, converting each agent's text into a `Message` record
4. Each `Message` is committed to the database immediately via `commit_with_retry`
5. The frontend's existing polling (`pollMessages()`) picks up new messages incrementally

Messages appear one at a time as each agent contributes — not all at once after the process finishes.

### Session lifecycle

- **Created**: On the first message to a multi-agent job conversation
- **Reused**: Follow-up messages in the same conversation reuse the existing session (the `claude` process retains full context)
- **Stopped**: When the conversation is cancelled, or the server shuts down
- **Registry**: `team_registry.py` manages sessions in memory, keyed by `conversation_id`

### Lead agent designation

The agent with `is_lead=True` is designated as the lead via `--agent <slug>`. The lead's prompt includes a teammates roster so it knows who to delegate to via Claude's Task tool. All other agents receive the same files_context but not the teammate list.

### File access

Agents need disk access to use Claude's built-in Read/Write/Glob/Grep tools:

| Workgroup type | File source | Cleanup |
|---|---|---|
| Workspace-enabled | Git worktree (managed by workspace system) | Managed by workspace |
| Non-workspace | Virtual files materialized to a temp directory | `TeamSession.stop()` cleans up via `_materialized_dir` |

After each message exchange, changes to files on disk are synced back to the workgroup's virtual file store via `sync_directory_to_files`.

---

## Independent Fan-Out (`@each`)

Every agent gets the same conversation history + trigger and responds independently via separate `claude -p` invocations. No agent sees another's response. Uses `_run_single_agent_responses` with all candidates.

---

## Lead Agents

Every organizational level has an explicit lead agent (`is_lead=True`) that serves as the default responder and the top-level agent in multi-agent team sessions.

| Level | Lead agent name | Created when | Role |
|---|---|---|---|
| Home | `home-agent` | User first login | Creates orgs, manages partnerships |
| Organization | `org-lead` | Organization is created (lives in Administration workgroup) | Orchestrates engagements, projects; decomposes work to workgroups |
| Workgroup | `<workgroup-name>-lead` | Workgroup is created | Manages jobs, onboards agents |

Lead agents are configurable (personality, model, tools) but not removable or renamable. Selection uses `_select_lead()` which picks the `is_lead=True` agent, falling back to `candidates[0]`.

See [ARCHITECTURE.md](ARCHITECTURE.md) for the full hierarchy and how lead agents interact across levels.

---

## Live Activity Tracking

An in-memory store (`_conversation_activity`) tracks what each agent is doing, exposed via `GET /conversations/{id}/activity`. Entries auto-expire after 120 seconds.

| Phase | Detail | Meaning |
|---|---|---|
| `composing` | `thinking` | Single-agent response in progress |
| `composing` | `team session` | Agent is part of a persistent team session |

---

## Hierarchical Team Dispatch

Projects and engagements create hierarchical teams -- multiple independent Claude Code team sessions connected by liaison agents. See [hierarchical-teams.md](hierarchical-teams.md) for the full design.

### Project Team Dispatch

When a project starts, TeaParty creates a project team session:

```
Project created (status: pending)
    |
    v
Generate agent definitions:
  - org-lead (team lead, from Administration workgroup)
  - liaison-{workgroup} (one per workgroup in project.workgroup_ids)
    |
    v
Launch team session (claude --input-format stream-json --agents {...})
    |
    v
Send project prompt as initial message
    |
    v
Project status -> in_progress
```

The project team uses native Claude Code team primitives internally (SendMessage, TaskCreate). The org lead assigns tasks to liaisons, who relay to sub-teams via `relay_to_subteam`.

### Liaison-to-SubTeam Dispatch

When a liaison calls `relay_to_subteam` for the first time:

```
relay_to_subteam(message="...")
    |
    v
Create Job record (linked to project, in liaison's workgroup)
    |
    v
Create job conversation (kind: "job")
    |
    v
Generate agent definitions for workgroup agents
    |
    v
Launch job team session (separate claude process)
    |
    v
Send liaison's message as initial task prompt
    |
    v
Return confirmation to liaison
```

Subsequent calls send messages to the existing job team session via `TeamSession.send_message()`.

### Async Notification Bridge

Sub-teams may run for extended periods. When a sub-team produces notable output (completion, question, stall), TeaParty bridges the notification to the parent team:

1. `team_bridge.py` detects the event in the sub-team's event stream.
2. TeaParty injects a message into the parent team session, addressed to the relevant liaison.
3. The liaison picks up the notification and relays to the team lead.

This bridges the async gap between independent Claude Code processes without the liaison needing to poll.

### Engagement Team Dispatch

Engagement dispatch is two-phase:

1. **Negotiation phase**: Single-agent dispatch (existing behavior). The engagement conversation uses `_run_single_agent_responses` with the org lead.
2. **Work phase** (after acceptance): A team session is created with the org lead + internal liaisons + external liaison(s). Dispatches the same way as project teams.

### Team Parameter Inheritance

Job team sessions inherit configuration from multiple levels:

```
Workgroup defaults  <--  Project overrides  <--  Job overrides
```

| Parameter | Source |
|-----------|--------|
| `model` | Workgroup config, overridden by Project.model if set |
| `permission_mode` | Workgroup config (default: `acceptEdits`), overridden by Project.permission_mode |
| `max_turns` | Workgroup config, overridden by Project.max_turns |
| `max_cost_usd` | Workgroup config, overridden by Project.max_cost_usd |
| `max_time_seconds` | Workgroup config, overridden by Project.max_time_seconds |

---

## Feedback Routing

The feedback bubble-up model (see [ARCHITECTURE.md](ARCHITECTURE.md)) flows through the hierarchical team structure:

1. A job agent posts a feedback request in the **job conversation**.
2. TeaParty notifies the liaison in the parent team session.
3. The liaison relays to the org lead in the **project** or **engagement conversation**.
4. The org lead notifies the human (via org-level DM or the engagement conversation).
5. The human responds. The response routes back down: org lead -> liaison (`relay_to_subteam`) -> job team.

Each hop uses the existing dispatch routing for its conversation kind. The liaison bridge handles the cross-team hops transparently.

---

## Implementation

| Component | File | Purpose |
|---|---|---|
| Entry point | `agent_runtime.py` : `run_agent_auto_responses()` | Routes to correct path |
| Team sessions | `agent_runtime.py` : `_run_team_response()` | Persistent `claude` process via team session |
| Fan-out / single | `agent_runtime.py` : `_run_single_agent_responses()` | Isolated per-agent invocations |
| Session management | `team_session.py` : `TeamSession` | Bidirectional `stream-json` I/O with `claude` process |
| Session registry | `team_registry.py` | In-memory registry of active sessions per conversation |
| Event bridge | `team_bridge.py` | Converts `TeamEvent`s to `Message` records in the database |
| Agent definitions | `agent_definition.py` | Builds per-agent JSON for `--agents` (including liaison definitions) |
| Routing helpers | `agent_runtime.py` : `_is_each_invocation()`, `_is_team_invocation()`, `_resolve_mentioned_agent()` | Routing decisions |
| Liaison tool | *(new)* `relay_to_subteam` | Creates jobs, spawns sub-team sessions, bridges messages |
| Notification bridge | *(new)* async injector | Pushes sub-team events into parent team sessions |
| Project lifecycle | *(new)* project team manager | Orchestrates project team creation, monitoring, shutdown |
