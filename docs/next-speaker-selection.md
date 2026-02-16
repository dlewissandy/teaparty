# Next Speaker Selection

How TeaParty decides which agent speaks next in a conversation.

---

## Overview

When a message is posted (by a user or agent), the system decides which agent should respond — and whether anyone should respond at all. The pipeline has three layers:

1. **LLM intent probing** — Each candidate agent gets an LLM call asking "do you have something distinct to say?" and returns an urgency score
2. **Threshold filtering** — Only agents whose urgency exceeds their personal `response_threshold` are eligible
3. **Heuristic fallback** — If LLM probing fails, a fast keyword/relevance scorer picks instead

After one agent responds, the system loops and asks "does anyone else want to respond?" — enabling natural multi-agent conversation chains.

---

## Entry Point

`run_agent_auto_responses()` in `agent_runtime.py` is called from a background task whenever a message is posted.

```
run_agent_auto_responses(session, conversation, trigger) -> list[Message]
```

It first gathers candidate agents based on conversation type:

| Conversation kind | Candidates |
|---|---|
| `direct` | Only the agent(s) that are conversation participants |
| `job` | All non-admin agents in the team |
| `admin` | Only the admin agent (single response, no chaining) |
| `engagement` | Only the coordinator agent on the operations team (see [engagements.md](engagements.md)) |
| `activity` | None (no auto-response) |

Admin conversations are handled as a special case — a single `build_admin_agent_reply()` call — and return immediately. Everything below applies to `job` and `direct` conversations.

---

## The Chain Loop

The system supports multiple agents responding in sequence. The loop runs up to `max_chain` iterations:

```python
max_chain = 1 if len(candidates) == 1 else min(settings.agent_chain_max, 2 * len(candidates))
```

Each iteration:

1. **Block the last speaker** — If the previous message was from an agent and there are multiple candidates, that agent is blocked from responding again immediately
2. **Select a responder** — Call `_select_responder()` to pick the next agent
3. **Break if nobody selected** — The chain ends naturally when no agent wants to speak
4. **Generate reply** — Call `build_agent_reply()` with the selected agent's intent
5. **Record thoughts** — Store the agent's intent and urgency as an `AgentLearningEvent`
6. **Apply learning** — Run short-term learning signals on the response
7. **Schedule follow-up** — If the reply warrants a follow-up task, schedule one
8. **Update chain state** — The new message becomes the trigger for the next iteration

### Thread anchoring

If the original trigger was from a user, all agent replies point their `response_to_message_id` at that user message (flat structure). If the trigger was from another agent, replies chain to each other.

### Chain awareness

All chains are open — there is no progressive dampening. Later chain steps tell the agent who has already spoken so it avoids repetition, but do not raise the bar:

> Chain step: 3. Already responded: Alice, Bob. Don't repeat what they said.

Chains end naturally when no agent's urgency exceeds its `response_threshold`, or when the hard cap (`max_chain`) is reached.

---

## `_select_responder()`

The core dispatcher. Decision branches in order:

### 1. Direct conversation shortcut

If the conversation is `direct` and there's only one eligible agent, skip probing entirely and return that agent immediately. There's no decision to make.

### 2. LLM intent probing

Call `_gather_agent_intents()` to probe every non-blocked candidate. This returns a list sorted by urgency descending. Then filter to agents where:

- `intent` is not null (agent declared they have something to say)
- `urgency >= agent.response_threshold` (default 0.55)

If any pass: return the highest-urgency agent.

### 3. Forced response for human triggers

If no agent passed the threshold but the trigger was from a human user, force the highest-urgency agent to respond anyway. Users always get a reply.

### 4. Natural pause for agent triggers

If no agent passed the threshold and the trigger was from another agent, return `None`. The chain ends — this is the natural pause mechanism that prevents agents from chattering endlessly.

### 5. Heuristic fallback

If the LLM probing throws an exception, fall back to `_heuristic_select_responder()`.

---

## LLM Intent Probing

`_gather_agent_intents()` iterates through each candidate and calls `_probe_agent_intent()`, which makes an Anthropic API call.

### The prompt

**System prompt** — Gives the agent its identity:

```
You are {name}. Role: {role}. Personality: {personality}.
Disposition: {voice_hint}. Confidence: {confidence}.

Decide whether you have a specific, distinct contribution to this conversation.
Return JSON only.
```

The disposition voice hint is derived from the agent's learned biases (e.g., "decisive stance, proactive initiative, engaged social tone, moderate detail").

**User prompt** — Provides context and asks for a decision:

```
Job: {conversation.topic}
Kind: {conversation.kind}
Trigger from: {human | agent:id}
Trigger: {first 400 chars of message}

{chain context if chain_step > 0}
{workflow hint if _workflow_state.md exists}

Recent messages:
{last 10 messages, up to 2000 chars}

Return strict JSON:
{"intent": "<one sentence: your specific point, or null>", "urgency": <0.0 to 1.0>}

Rules:
- 0: nothing to add, would just agree or paraphrase
- 0.3-0.5: tangentially related comment
- 0.6-0.8: relevant perspective, useful information, or building on others' points
- 0.8-1.0: new insight, unique angle, critical disagreement, essential correction, or aha-moment
- null intent + 0 urgency if you would just validate, encourage, or restate
```

The workflow hint is extracted from `_workflow_state.md` if present in the team's files. It includes the current step and status (e.g., "Active workflow: - **Current Step**: Design review; - **Status**: In progress"). See [workflows.md](workflows.md) for the full workflow model.

### LLM call parameters

- **Temperature:** 0.3
- **Max tokens:** 256
- **Model:** `settings.intent_probe_model` with fallback chain

### Response parsing

The LLM returns JSON like `{"intent": "I can explain the security implications", "urgency": 0.72}`. The system:

- Extracts the JSON object (handles code blocks and edge cases)
- Converts `"null"` string intents to Python `None`
- Clamps urgency to [0.0, 1.0]

If parsing fails entirely, returns `(None, 0.0)` — the agent abstains.

---

## Heuristic Fallback

When LLM probing fails, `_heuristic_response_score()` computes a fast score per agent:

| Factor | Score | Condition |
|---|---|---|
| Base | +0.1 | Always |
| Self-response | -1.0 | Agent just spoke (immediate disqualification) |
| Direct + user | +1.0 | Direct conversation, user trigger (guaranteed response) |
| Direct conversation | +0.2 | Any direct conversation |
| @mentioned | +0.6 | Agent name mentioned in message |
| Question detected | +0.25 to +0.32 | Message contains "?" or question words |
| Job relevance | 0 to +0.4 | Token overlap between message and agent profile |
| Role identity query | 0 or +0.22 | Message asks about roles/identity and agent has a role profile |
| Personality bonus | +/-0.08 | Engaged vs reserved personality keywords |
| Agent trigger penalty | -0.15 | Triggered by another agent, not mentioned |
| Engagement bias | +/-0.2 | From agent's learned preferences |

The agent with the highest margin above their `response_threshold` wins. Same forced-response rule applies: if the trigger is from a human and nobody clears the threshold, the best scorer is forced.

---

## Reply Generation

Once an agent is selected, `build_agent_reply()` generates their response. The LLM call uses:

- **Max tokens:** 16384 — deliberately high so agents are never truncated mid-thought. The agent's system prompt and verbosity setting control actual length.
- **Temperature:** from the agent's `temperature` field (default 0.7)
- **Model:** from the agent's `model` field with fallback chain

If a tool is matched (file operations, code generation, web search, etc.), the tool runs first and its output is included in the reply prompt as context.

---

## The `response_threshold` Field

Each agent has a `response_threshold` (default: 0.55) that acts as their personal bar for speaking up. It's used in both paths:

- **Intent probing:** `urgency >= response_threshold` to pass the filter
- **Heuristic:** `score - response_threshold` as the margin

A lower threshold means the agent is more chatty; higher means more selective.

---

## Observability

The pipeline records two types of `AgentLearningEvent` entries:

### `intent_probe`

Created for every candidate during `_gather_agent_intents()`:

```json
{
  "intent": "I should point out the budget constraint",
  "urgency": 0.68,
  "threshold": 0.55,
  "chain_step": 0
}
```

### `agent_thoughts`

Created for the agent that actually responds, after their message is flushed:

```json
{
  "intent": "I should point out the budget constraint",
  "urgency": 0.68,
  "chain_step": 0
}
```

These are surfaced in the UI via the "Show agent thoughts" preference toggle.

---

## Live Activity Tracking

An in-memory store (`_conversation_activity`) tracks what each agent is currently doing, exposed via `GET /conversations/{id}/activity`. The phases are:

| Phase | Set where | Meaning |
|---|---|---|
| `probing` | `_gather_agent_intents()` | Agent's intent is being evaluated via LLM |
| `tool` | `build_agent_reply()` | Agent is running a tool (detail = tool name) |
| `composing` | `build_agent_reply()` | Agent's reply is being generated via LLM |

Activity is cleared per-agent after each message flush, and for the entire conversation when the chain loop ends. Entries auto-expire after 120 seconds.

---

## Decision Flow Summary

```
trigger arrives
  |
  v
get candidate agents for conversation type
  |
  v
for chain_step in range(max_chain):
  |
  +-- block last speaker (if agent-triggered, multi-candidate)
  |
  +-- _select_responder()
  |     |
  |     +-- direct + 1 agent? --> respond immediately
  |     |
  |     +-- _gather_agent_intents()
  |     |     for each candidate:
  |     |       set activity "probing"
  |     |       LLM call --> {intent, urgency}
  |     |       record intent_probe event
  |     |     sort by urgency desc
  |     |
  |     +-- filter: urgency >= threshold
  |     |     any pass? --> return highest
  |     |
  |     +-- human trigger? --> force highest anyway
  |     +-- agent trigger? --> return None (pause)
  |     |
  |     +-- on error: heuristic fallback
  |
  +-- no result? --> break (chain ends)
  |
  +-- build_agent_reply(selected, intent)
  |     set activity "tool" / "composing"
  |
  +-- create message, flush
  +-- clear activity for this agent
  +-- store agent_thoughts event
  +-- apply short-term learning
  +-- schedule follow-up if needed
  +-- this message becomes next trigger
  |
clear all activity
return created messages
```
