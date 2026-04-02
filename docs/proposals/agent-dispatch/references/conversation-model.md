[Agent Dispatch](../proposal.md) >

# Conversation Model

## Context Identity

Each agent-to-agent exchange has a stable conversation ID, the same as human-agent conversations. The ID is tied to the exchange, not the turn:

| Conversation type | ID scheme | Lifecycle |
|---|---|---|
| OM conversation | `om:{qualifier}` | Persistent across sessions |
| Job/session | `job:{project}:{session_id}` | Closes when session ends |
| Agent-to-agent exchange | `agent:{initiator_id}:{recipient_id}:{uuid}` | Closes when exchange resolves |

The `{uuid}` component is a UUID4 generated at context creation time. It ensures uniqueness even when the same initiator sends multiple parallel tasks to the same recipient — two simultaneous `Send` calls from `my-backend/lead` to `my-backend/coding/specialist` produce distinct context IDs with distinct UUIDs.

`Send` always creates a new context with a new UUID4 unless the caller explicitly supplies an existing context ID. Thread continuity across turns — having a lead continue an exchange with the same worker — is achieved by the caller tracking and reusing the context ID from a prior `Send`. There is no automatic lookup by `(initiator, recipient)` pair; such a lookup would be ambiguous in the parallel-send case. The explicit context-targeting interface is in [Send Tool](invocation-model.md#send-tool).

Multiple agent-to-agent conversations can be active simultaneously. A lead managing three parallel worker tasks holds three open context IDs.

## Multi-Turn Mechanics

> **Implementation status.** This model is implemented. `Send` and `Reply` are the current dispatch tools; `AskTeam` and `DispatchListener` have been retired (issues #358, #359). Re-invocation, `pending_count` management, and write-then-exit-then-resume are the current execution path.

An agent-to-agent exchange works from the bus's perspective the same as a human-agent conversation. The execution model is write-then-exit-then-resume:

1. Caller calls `Send(member, message)`. Before posting, the orchestrator flushes the current state to `{worktree}/.context/scratch.md`. The tool assembles the composite message (Task + Context envelope) and posts it to the bus. Caller exits its current turn.
2. TeaParty's bus event listener detects the new post and spawns the recipient agent via `claude -p` with the conversation history, which includes the composite message and the injected parent context ID.
3. Recipient does its work. When complete, it calls `Reply(message)`. The reply is written to the bus on the same context ID. Recipient exits.
4. TeaParty's bus event listener detects the `Reply` and appends it to the caller's local conversation history file, then re-invokes the caller via `--resume $SESSION_ID`.
5. Caller reads the reply from conversation history and continues.

The bus event listener is the central execution loop: a component in the TeaParty orchestrator process (in `orchestrator/`) that watches the bus for new posts and replies. It is responsible for spawning recipient agents (step 2), injecting replies into caller session files, and issuing `--resume` calls (step 4). It is distinct from the bus dispatcher (which handles authorization) and from the MCP tool handlers (which handle individual tool calls). The Messaging proposal must specify the notification interface the bus exposes to the event listener — whether push (callback), pull (polling), or an OS-level primitive.

The caller's `claude -p` process exits after `Send`. It does not run concurrently with the recipient. When the reply arrives, TeaParty triggers re-invocation using the session ID captured from the caller's JSON output (`--output-format json` returns a `session_id` field). TeaParty stores the session ID in the conversation context record keyed by context ID, so incoming replies can be matched to the correct caller for re-invocation.

State that the caller needs on re-invocation — pending context IDs, task intent — must be recorded in the conversation before the caller exits. `--resume` restores the conversation history thread; it does not restore in-memory state.

## Fan-In vs. Mid-Task Clarification

These are two distinct re-invocation patterns with different execution paths.

Fan-in: the lead calls `Send` to multiple workers (parallel dispatch), then exits. Each worker calls `Reply` when done. The lead is re-invoked in the parent context when `pending_count` reaches zero — after all workers have replied. This is the normal completion path.

Mid-task clarification: a worker, mid-task, calls `Send` targeting the lead (available via requestor injection). This opens a new context where the worker is the initiator and the lead is the recipient — a clarification thread separate from the worker's task thread. The bus event listener detects this post and immediately re-invokes the lead in that clarification context. The lead answers and calls `Reply`, closing the clarification thread.

The clarification thread is a peer thread of the worker's task thread. It has its own context record and its own `pending_count` (initialized to zero, since no sub-tasks were spawned). The lead's `Reply` on the clarification thread decrements that clarification context's record — not the task thread's `pending_count`. The fan-in counter on the parent (tracking the worker's task thread) is unchanged. The worker's task thread remains open; the worker resumes after the clarification closes.

The key structural fact: the lead can be re-invoked in a clarification sub-context while the worker's task thread and other workers' task threads are still open. The lead is present in the clarification context only — it cannot simultaneously process the parent context. The bus event listener enforces this with a per-agent re-invocation lock: only one `--resume` call for a given `agent_id` can be active at a time. A second re-invocation request for the same agent queues until the first completes and the process exits. The heartbeat dead-threshold (>300 seconds) is the de facto timeout: a queued re-invocation for a context whose counterpart has been marked abandoned is resolved via synthetic error delivery before it would wait indefinitely.

For the full serialization mechanics, see [Multi-Turn Clarification vs. Fan-In Re-Invocation](invocation-model.md#multi-turn-clarification-vs-fan-in-re-invocation).

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

For escalation propagation to work, each spawned agent must know two context IDs at invocation time: the immediate parent context ID (for `Reply`) and the job-level context ID (for INTERVENE propagation). TeaParty injects both via the agent's initial conversation history. The immediate parent and the job-level context may be the same (for direct workers of the session lead); they differ for agents more than one level below the job. CfA Extensions is responsible for specifying the exact field names.

**INTERVENE delivery.** When a lead determines that a worker's escalation cannot be resolved within the workgroup, it takes two sequential actions before exiting: first, it calls `Reply` on the clarification thread, giving the worker a meaningful signal that the escalation is being handled at a higher level and closing the thread. Second, it posts the INTERVENE signal to the job-level context ID via a directed `Send`. The `Reply` must come first — `Send` is write-then-exit, so the process terminates after the directed send. Calling `Reply` first ensures the clarification thread is closed before the process exits, leaving no open threads behind.

The lead posts to the job-level context ID using a directed `Send` — supplying `context_id` rather than opening a new thread. For a directed send, `member` is the roster name of the intended recipient (used for routing lookup), and `context_id` is the target conversation thread. The lead passes `member` as the session lead's roster name and `context_id` as the injected job-level context ID.

**Authorization for directed sends.** Directed sends — those that supply a `context_id` for escalation — bypass both the participant-set check and the routing table check. Authorization rests entirely on structural position in the conversation hierarchy: a spawned agent has implicit authority to post back to any context in its ancestry. This is the escalation carve-out. A worker two levels deep has no routing table entry to the session lead (workers do not have the project lead in their roster — cross-workgroup requests normally go through the workgroup lead). The routing table is not consulted for directed sends; the conversation hierarchy is. This carve-out is what makes escalation from any depth possible. Without it, workers below the project lead cannot reach the job-level context, and the escalation chain breaks. CfA Extensions is responsible for defining the INTERVENE payload format and the receptive state precondition — what state the job-level conversation must be in when INTERVENE arrives.

The lead is not simultaneously present in both contexts. While the lead is executing in the sub-conversation context, the parent context's pending count is unchanged. The INTERVENE signal propagates upward through the bus conversation hierarchy; the lead's presence in the sub-conversation closes when it calls `Reply` on the sub-context before the directed send.

**Escalation context.** When an agent escalates — posting a question or INTERVENE that crosses a context boundary — it uses `Send` targeting the appropriate roster member (workgroup lead, project lead, or human participant). `Send` applies the same flush-and-envelope construction as any other message: the orchestrator flushes the scratch file first, then assembles Task + Context. The receiver gets the escalating agent's message plus the lead's view of job state as of the spawning agent's last flush. The proxy receives a complete situation report: if it can answer confidently, it does; if not, it forwards the report unchanged via `Send` to the human participant in its own roster. The human sees exactly what the proxy received — no further synthesis or reframing occurs in the escalation chain.

Every agent spawn must include both the immediate parent context ID and the job-level context ID so that INTERVENE propagation has a target regardless of how deep in the hierarchy the escalating agent sits.
