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

> **Target design.** A code path for this model does not yet exist. The current `AskTeam` implementation is a synchronous Unix domain socket RPC to `DispatchListener` that blocks the caller for the full dispatch duration. Implementing this model requires replacing that RPC with bus-mediated `AskTeam` and `ReplyTo` tools, re-invocation plumbing, and `pending_count` management in the bus context record.

An agent-to-agent exchange works from the bus's perspective the same as a human-agent conversation. The execution model is write-then-exit-then-resume:

1. Caller posts a message to the recipient's context ID via `AskTeam` and exits its current turn
2. TeaParty spins up the recipient agent with the conversation history
3. Recipient responds via `ReplyTo`; the response is written to the bus on the same context ID; recipient exits
4. TeaParty appends the response to the caller's local conversation history file, then re-invokes the caller via `--resume $SESSION_ID`
5. Caller reads the response from conversation history and continues

The caller's `claude -p` process exits after posting. It does not run concurrently with the recipient. When the response is ready, TeaParty triggers re-invocation using the session ID captured from the caller's JSON output (`--output-format json` returns a `session_id` field). TeaParty stores the session ID in the conversation context record keyed by context ID, so it can match incoming responses to the correct caller for re-invocation.

State that the caller needs on re-invocation — pending context IDs, task intent — must be recorded in the conversation before the caller exits. `--resume` restores the conversation history thread; it does not restore in-memory state. Recording this state in the conversation is how it survives across process boundaries.

For follow-up turns, the caller posts again to the same context ID via `ReplyTo`; the recipient is re-invoked via `--resume` with the full updated history.

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

Worker-level questions stay inside the workgroup. The workgroup lead receives the escalation and resolves it without human involvement. Lead-level questions go to the project lead or OM; if the proxy can handle it, it does. If not, the escalation surfaces to the human via the job conversation's escalation badge. OM-level questions surface directly to the human.

The bus conversation hierarchy mirrors the workgroup hierarchy. CfA INTERVENE/WITHDRAW mechanics provide the propagation mechanism; gate logic applies at each conversation level independently.

For escalation propagation to work, each spawned agent must know its parent context ID at invocation time. TeaParty injects the parent context ID as part of the spawn environment — specifically, in the agent's initial conversation history or as an environment variable accessible to the MCP tool layer.

When a lead is re-invoked in a worker-level sub-conversation context and determines that the escalation cannot be resolved there, it takes two sequential actions: it records the unresolvable escalation in the sub-conversation, then posts the INTERVENE signal to the parent context ID via `ReplyTo`. That parent context ID was injected at the lead's spawn time. The lead is not simultaneously present in both contexts.

CfA Extensions is responsible for defining exactly what fields carry the parent context ID at spawn time and what the INTERVENE payload looks like in this cross-context case. This proposal places that requirement on CfA Extensions: every agent spawn must include the job-level context ID so that INTERVENE propagation has a target. CfA Extensions must also specify the receptive state precondition — what state the job-level conversation must be in when INTERVENE arrives.
