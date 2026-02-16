# Next Speaker Selection

How TeaParty decides which agents respond in a conversation.

---

## Overview

TeaParty uses different response strategies based on conversation type:

| Conversation kind | Strategy |
|---|---|
| `job` | **Multi-agent team** — all agents passed to Claude via `--agents`, lead agent orchestrates delegation |
| `direct` | Single-agent `claude -p` with workflow-aware turn policy |
| `engagement` | Single-agent `claude -p` (coordinator agent) |
| `admin` | Single deterministic command handler (no selection) |
| `activity` | No auto-response |

---

## Job Conversations — Multi-Agent Teams

Job conversations invoke Claude's native multi-agent team feature. All workgroup agents participate in every response cycle.

### How it works

1. **All agents** in the workgroup (excluding admin) are gathered as candidates
2. **Agent definitions** are built via `build_agent_json()` for each candidate
3. The **first agent** (by creation order) is designated as the **lead** (`--agent <slug>`)
4. All agents are passed as `--agents '<json>'` to a single `claude -p` invocation
5. The lead agent's prompt includes a **team roster** listing other agents and their roles
6. Claude's agent runtime handles delegation — the lead uses the `Task` tool to involve other agents as needed

### Output parsing

The verbose JSON output from `claude -p --verbose --output-format json` is parsed to extract individual agent contributions:

1. **Event-based parsing** (`parse_team_output`) — walks the verbose event array looking for `Task` tool_use/tool_result pairs. Each tool_result is attributed to the sub-agent named in the corresponding tool_use.
2. **Text-based fallback** (`unpack_agent_text`) — if no Task events are found, splits the result text by agent name prefixes (`**Name**: ...`, `[Name]: ...`, `Name: ...`).
3. **Lead attribution fallback** — if neither strategy produces results, the full text is attributed to the lead agent.

Each extracted contribution becomes a separate `Message` in the conversation, with `sender_agent_id` set to the matched agent.

### Configuration

- **Max turns**: `max(3, 2 * len(candidates))` — enough for the lead to delegate to each agent
- **Timeout**: `max(120, 60 * len(candidates))` seconds
- **Tools**: agent mode does not restrict tools (lead needs `Task` for delegation)
- **Fallback**: on error, falls back to sequential single-agent responses

---

## Direct Conversations — Single Agent

Direct conversations use the workflow-aware turn policy (`determine_next_turns`) to select which agent responds, then invoke `claude -p` for each selected agent sequentially.

If only one agent participates in a direct conversation, it responds immediately without selection logic.

---

## Live Activity Tracking

An in-memory store (`_conversation_activity`) tracks what each agent is currently doing, exposed via `GET /conversations/{id}/activity`. Activity entries auto-expire after 120 seconds.

| Phase | Meaning |
|---|---|
| `composing` | Agent's reply is being generated |
| `composing` (detail: `team`) | Agent is part of a multi-agent team invocation |

---

## Implementation

- **Entry point**: `run_agent_auto_responses()` in `agent_runtime.py`
- **Job path**: `_run_job_team_response()` — multi-agent team via `--agents`
- **Direct/engagement path**: `_run_single_agent_responses()` — sequential `claude -p`
- **Team output parser**: `team_output_parser.py` — event and text parsing
- **Agent definitions**: `agent_definition.py` — `build_agent_json()` with optional team roster
