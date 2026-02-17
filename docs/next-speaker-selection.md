# Next Speaker Selection

How TeaParty decides which agents respond in a conversation.

---

## Design Principle

Job conversations have two fundamentally different multi-agent modes:

| Mode | Trigger | What happens | Agent isolation |
|---|---|---|---|
| **Multi-agent team** | `@all` / `@team` | One `claude` process with all agents via `--agents`; lead delegates autonomously via Task tool | Agents coordinate through Claude's built-in multi-agent mechanism |
| **Independent fan-out** | `@each` | One `claude -p` per agent, run sequentially | Complete isolation — no agent sees another's response |

There is no third mode.  There is no hand-rolled sequential orchestration, no round-robin, and no prompt-chaining where one agent's output is fed to the next.  When agents need to collaborate, Claude's multi-agent teams handle it — the lead decides how to involve teammates.

---

## Routing Table

| Conversation kind | Strategy |
|---|---|
| `job` + `@each` | Independent fan-out via `_run_single_agent_responses` with ALL candidates |
| `job` + `@all`/`@team` | Claude multi-agent team via `_run_job_team_response` |
| `job` + `@name` | Single named agent via `_run_single_agent_responses` |
| `job` (default) | Lead agent only (`is_lead=True`, fallback to first by creation order) via `_run_single_agent_responses` |
| `direct` | Single participating agent |
| `engagement` | Single coordinator agent |
| `admin` | Deterministic command handler (no LLM selection) |
| `activity` | No auto-response |

**Priority**: `@each` is checked before `@all`/`@team`.  If both appear in the same message, fan-out wins.

**Guard**: Only user messages trigger responses in job conversations.  Agent messages are ignored to prevent re-triggering loops.

---

## Multi-Agent Team (`@all` / `@team`)

All workgroup agents (excluding admin) collaborate via Claude's multi-agent teams feature:

1. Agents are gathered as candidates, ordered by creation date
2. The agent with `is_lead=True` is the **lead** (fallback: first by creation order); all others are **teammates**
3. All agents are passed to a **single** `claude` invocation via `--agents`
4. The lead delegates to teammates using Claude's built-in **Task tool**
5. Agents collaborate **autonomously** — TeaParty does not script their interaction
6. Output is parsed for per-agent attribution and each contribution becomes a separate Message

### Attribution

With `--output-format stream-json --verbose`, all inter-agent communication appears as structured Task tool_use/tool_result event pairs.  No text parsing is needed — the events are the source of truth.

| Strategy | Source | When it applies |
|---|---|---|
| **Event parsing** | `stream-json` Task tool_use/tool_result pairs | Lead delegated to subagents via Task tool |
| **Lead fallback** | Entire `result.text` | No Task delegation found; everything attributed to lead |

### Configuration

- **Max turns**: `max(6, 4 * len(candidates))` — enough for delegation + discussion
- **Timeout**: `max(180, 90 * len(candidates))` seconds
- **Lead**: gets a teammates roster in its agent definition
- **Fallback on error**: reverts to `_run_single_agent_responses` (each agent solo)

---

## Lead Agents

Every workgroup has an explicit lead agent (`is_lead=True`) that serves as the default responder and the top-level agent in multi-agent teams.

| Level | Lead agent name | Created when |
|---|---|---|
| Workgroup | `<workgroup-name>-lead` | Workgroup is created (or lazily on first listing) |
| Organization | `engagements-lead` | Organization is created (lives in Administration workgroup) |

Lead agents are **configurable** (personality, model, tools, etc.) but **not removable** or **renamable**. Their name tracks the workgroup name automatically on rename. Selection uses `_select_lead()` which picks the `is_lead=True` agent, falling back to `candidates[0]` for backward compatibility.

---

## Independent Fan-Out (`@each`)

Every agent gets the same conversation history + trigger and responds independently via separate `claude -p` invocations.  No agent sees another's response.  Uses `_run_single_agent_responses` with all candidates — the same function used for @mention and default routing, just with the full candidate list instead of one agent.

---

## Direct Conversations

Always route to the single participating agent.  No selection logic.

---

## Live Activity Tracking

An in-memory store (`_conversation_activity`) tracks what each agent is doing, exposed via `GET /conversations/{id}/activity`.  Entries auto-expire after 120 seconds.

| Phase | Detail | Meaning |
|---|---|---|
| `composing` | `thinking` | Single-agent response in progress |
| `composing` | `team` | Agent is part of a multi-agent team response |

---

## Implementation

| Component | File | Purpose |
|---|---|---|
| Entry point | `agent_runtime.py` : `run_agent_auto_responses()` | Routes to correct path |
| Multi-agent team | `agent_runtime.py` : `_run_job_team_response()` | Single `claude --agents` invocation |
| Fan-out / single | `agent_runtime.py` : `_run_single_agent_responses()` | Isolated per-agent invocations |
| Output parsing | `team_output_parser.py` | Extracts per-agent contributions |
| Agent definitions | `agent_definition.py` | Builds per-agent JSON with history |
| @-mention parsing | `agent_runtime.py` : `_is_each_invocation()`, `_is_team_invocation()`, `_resolve_mentioned_agent()` | Routing decisions |
