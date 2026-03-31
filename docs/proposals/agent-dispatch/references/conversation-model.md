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

> **Target design.** A code path for this model does not yet exist. The current `AskTeam` implementation is a synchronous Unix domain socket RPC to `DispatchListener` that blocks the caller for the full dispatch duration. Implementing this model requires replacing that RPC with bus-mediated `Send` and `Reply` tools, re-invocation plumbing, and `pending_count` management in the bus context record.

An agent-to-agent exchange works from the bus's perspective the same as a human-agent conversation. The execution model is write-then-exit-then-resume:

1. Caller calls `Send(member, message)`. Before posting, the orchestrator flushes the current state to `{worktree}/.context/scratch.md`. The tool assembles the composite message (Task + Context envelope) and posts it to the bus. Caller exits its current turn.
2. TeaParty spawns the recipient agent with the conversation history, which includes the composite message and the injected parent context ID.
3. Recipient does its work. When complete, it calls `Reply(message)`. The reply is written to the bus on the same context ID. Recipient exits.
4. TeaParty appends the reply to the caller's local conversation history file, then re-invokes the caller via `--resume $SESSION_ID`.
5. Caller reads the reply from conversation history and continues.

The caller's `claude -p` process exits after `Send`. It does not run concurrently with the recipient. When the reply arrives, TeaParty triggers re-invocation using the session ID captured from the caller's JSON output (`--output-format json` returns a `session_id` field). TeaParty stores the session ID in the conversation context record keyed by context ID, so it can match incoming replies to the correct caller for re-invocation.

State that the caller needs on re-invocation — pending context IDs, task intent — must be recorded in the conversation before the caller exits. `--resume` restores the conversation history thread; it does not restore in-memory state.

For follow-up turns before `Reply`, the recipient calls `Send` targeting the requestor (injected into its roster); the caller responds via another `Send` to the same member. The thread stays open until `Reply` closes it.

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

Worker-level questions stay inside the workgroup. The workgroup lead receives the escalation and resolves it without human involvement. Lead-level questions go to the project lead or OM; if the proxy can handle it, it does. If not, the escalation surfaces to the human. OM-level questions surface directly to the human.

The bus conversation hierarchy mirrors the workgroup hierarchy. CfA INTERVENE/WITHDRAW mechanics provide the propagation mechanism; gate logic applies at each conversation level independently.

For escalation propagation to work, each spawned agent must know its parent context ID at invocation time. TeaParty injects the parent context ID as part of the spawn environment — specifically, in the agent's initial conversation history or as an environment variable accessible to the MCP tool layer.

When a lead is re-invoked in a worker-level sub-conversation context and determines that the escalation cannot be resolved there, it takes two sequential actions: it records the unresolvable escalation in the sub-conversation, then posts the INTERVENE signal to the parent context ID via `ReplyTo`. That parent context ID was injected at the lead's spawn time. The lead is not simultaneously present in both contexts.

**Escalation context.** When an agent escalates — posting an INTERVENE or a question that crosses a context boundary — it uses `Send` targeting the appropriate roster member (workgroup lead, project lead, or human participant). `Send` applies the same flush-and-envelope construction as any other message: the orchestrator flushes the scratch file first, then assembles Task + Context. The receiver gets the escalating agent's message plus a current snapshot of the job state. The proxy receives a complete situation report. If it can answer confidently, it does. If not, it forwards the report unchanged via `Send` to the human participant in its own roster. The human sees exactly what the proxy received — no further synthesis or reframing occurs in the escalation chain.

CfA Extensions is responsible for defining exactly what fields carry the parent context ID at spawn time and what the INTERVENE payload looks like in this cross-context case. This proposal places that requirement on CfA Extensions: every agent spawn must include the job-level context ID so that INTERVENE propagation has a target. CfA Extensions must also specify the receptive state precondition — what state the job-level conversation must be in when INTERVENE arrives.
