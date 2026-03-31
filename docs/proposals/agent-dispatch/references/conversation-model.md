[Agent Dispatch](../proposal.md) >

# Conversation Model

## Context Identity

Each agent-to-agent exchange has a stable conversation ID, the same as human-agent conversations. The ID is tied to the exchange, not the turn:

| Conversation type | ID scheme | Lifecycle |
|---|---|---|
| OM conversation | `om:{qualifier}` | Persistent across sessions |
| Job/session | `job:{project}:{session_id}` | Closes when session ends |
| Agent-to-agent exchange | `agent:{initiator_id}:{recipient_role}:{token}` | Closes when exchange resolves |

Multiple agent-to-agent conversations can be active simultaneously. A lead managing three parallel worker tasks holds three open context IDs.

## Multi-Turn Mechanics

An agent-to-agent exchange works identically to a human-agent conversation from the bus's perspective:

1. Caller posts a message to the recipient's context ID (via `AskTeam` MCP tool)
2. TeaParty spins up the recipient agent with the conversation history
3. Recipient responds; response is written to the bus on the same context ID
4. If the caller needs to follow up, it posts again to the same context ID
5. Recipient is re-invoked via `--resume` with the updated history

The caller is not blocked between steps 2 and 3. It continues its own work. When the response arrives on the bus, TeaParty delivers it to the caller's context at its next turn boundary — the same eventually-consistent delivery used for human interventions.

## Navigator Hierarchy

Agent-to-agent sub-conversations appear in the navigator nested under the job that spawned them:

```
Sessions
  └── my-project / fix-auth-bug
        ├── [main job conversation]
        ├── coding-lead → coding-worker-1
        ├── coding-lead → coding-worker-2
        └── coding-lead → qa-reviewer
```

The human's default view is the job-level conversation. Sub-conversations are navigable but not pushed. A sub-conversation that escalates surfaces a badge at the job level.

The caller's view in its own conversation shows that it sent a message and received a response, with a link to the sub-conversation. The full multi-turn exchange lives in the sub-conversation.

## Escalation Routing

When an agent calls `AskQuestion` and cannot proceed, the escalation routes up the conversation chain:

1. **Worker-level escalation**: handled within the workgroup sub-conversation. The workgroup lead receives the question and resolves it. The human is not involved.
2. **Lead-level escalation**: the project lead or OM receives it. If the proxy can handle it at confidence, it does. If not, it surfaces to the human via the job conversation's escalation badge.
3. **OM-level escalation**: surfaces directly to the human.

The bus conversation hierarchy mirrors the workgroup hierarchy. No new escalation mechanism is needed — the existing CfA gate logic applies at each level, with the conversation chain as the propagation path.
