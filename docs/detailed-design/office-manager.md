# The Office Manager: Human-Initiated Conversation

The current system is asymmetric. Agents talk to the human when *they* need something: at approval gates, during escalations, when the proxy is uncertain. The human waits. This is unlike any real team collaboration, where the manager walks in at any time, asks what's going on, redirects priorities, or tells everyone to stop.

The office manager is the agent that makes conversation bidirectional. It is available on demand to the human, knows where everything is and who's doing what, and can relay the human's instructions to the right places.

---

## What the Office Manager Is

The office manager is a `claude -p` agent. Same runtime substrate as every other agent: invoked via the CLI, stream-json output, tools for reading files and inspecting state. It is not a special case, not a UI widget, not a chatbot wrapper. It is an agent that happens to serve the human directly rather than serving a CfA protocol phase.

It is the human's interface to the entire platform. Not to one session or one project, but to everything. When the human wants to know what's happening, they talk to the office manager. When they want something to change, they tell it. When they have a thought that doesn't fit into any active session's workflow, the office manager is where it goes.

The proxy agent stands *in for* the human at gates. The office manager stands *between* the human and the work. The proxy is a surrogate; the office manager is a liaison.

## What the Office Manager Is Not

It is not the proxy. The proxy is a full Claude agent that stands in for the human at gates, reasoning about artifacts with tools and ACT-R memory. The office manager doesn't make gate decisions. It listens, answers, and acts on the human's behalf across the platform.

It is not an orchestrator. It does not run CfA phases, invoke agents, or manage session state machines. It can *influence* orchestrators by sending signals they must respect (pause, withdraw), but the orchestration machinery executes independently. The distinction is between authority and execution: the office manager gives instructions; orchestrators carry them out.

It is not a dashboard. The TUI dashboard shows state. The office manager *interprets* state ("the planning phase has been running for 45 minutes, which is unusually long for this project") and takes action on it.

---

## Relationship to the CfA Protocol

The office manager operates on the CfA protocol from outside, like a supervisor. It is not a CfA participant. It does not occupy a role in the state machine (proposer, reviewer, approver). It is the human's direct channel for overriding the protocol when they choose to.

Withdrawal and pause are not CfA state transitions initiated by a protocol participant. They are human interventions that the protocol must respect. This is analogous to a manager walking into a meeting and canceling it. The manager is not a meeting participant, but the meeting still ends.

This framing matters because the CfA state machine has defined roles and legal transitions. The office manager is not bound by those roles. It acts with the human's authority, and the protocol accommodates that authority as an external force.

---

## The Conversation

The human opens a conversation from the TUI dashboard. The office manager is invoked via `claude -p` with an agent definition that establishes its role and tools, access to all project directories, session infra dirs, and git worktrees via Read/Glob/Grep tools, ACT-R memory chunks from prior conversations, and MCP tools for signaling active orchestrators (pause, withdraw). The pause and withdraw MCP tools do not exist yet and must be built.

The conversation is free-form. The human can ask anything.

### Inquiry

> "What's going on with the POC project?"

The office manager reads session state files, git logs, dispatch results, CfA state JSONs. It synthesizes a status report. Not a dump of raw data, but a narrative: what's running, what's blocked, what completed recently, what looks unusual.

> "Can you tell me more about the most current session of the joke-book project?"

It reads the specific session's infra directory (INTENT.md, PLAN.md, .work-summary.md, the stream JSONL, dispatch logs) and explains what happened, what decisions were made, where the session sits in the CfA lifecycle.

> "Why did the planning phase backtrack?"

It reads the CfA state history and the backtrack feedback, then explains the chain of events.

### Steering

> "Focus on security aspects first for all active sessions."

The office manager records this as a priority directive in shared memory. When the proxy next retrieves memories at a gate, this high-activation chunk surfaces and influences the review. The steering doesn't require the office manager to reach into active sessions and modify prompts. It influences future behavior through memory.

But the human needs to know whether their steering took effect. On the next conversation, the office manager can inspect recent proxy gate decisions and their retrieval context to report whether the steering chunk was actually retrieved and influential. This closes the feedback loop: the human steers, the system responds (or doesn't), and the human can see what happened.

> "That approach to the database migration won't work because we're switching to Postgres next quarter."

Context that exists only in the human's head. The office manager records it as a memory chunk. When the proxy or an agent team next works on database-related tasks, this context is retrievable. For directives that should remain influential over weeks rather than hours, the memory system may need a "pinned" activation floor that resists normal ACT-R decay. This is a memory system design question, not an office manager question, but the office manager is the primary source of such long-lived directives.

### Action

> "Can you make sure all my projects are committed and pushed?"

The office manager uses its Bash and Read tools to check git status across all project worktrees, commits and pushes where needed, and reports what it did.

> "Withdraw the current session on the POC project."

The office manager signals the active orchestrator via MCP to set the CfA state to WITHDRAWN. The orchestrator handles the cleanup.

> "Hold the presses — stop all active dispatches."

The office manager signals all active orchestrators to pause. This means no new phases launch; work already in progress completes. See Interruption below.

---

## Two Kinds of Influence

The office manager has two distinct mechanisms for transmitting the human's intent to the rest of the system. They serve different purposes and the boundary between them is scope and urgency.

**Memory-based steering** is for durable preferences that should influence all future work across sessions. "Focus on security." "We're switching to Postgres next quarter." These are recorded as memory chunks in the shared pool. They propagate indirectly, surfacing in any agent's retrieval when the structural context matches. They are broad, ongoing, and eventually consistent.

**Priority injection** is for urgent, targeted intervention in a specific active session. "Stop doing X right now in this session." The office manager writes a `.priority-context` file in the session's infra directory. The orchestrator includes it in the next agent prompt, using the same prompt-prepend mechanism as `backtrack_context`. The difference from `backtrack_context` is scope: backtrack context operates within a single phase's correction rounds, while priority injection operates across phase boundaries. The orchestrator would check for a `.priority-context` file before each phase, not just during correction rounds.

The discriminator is simple. If the human's intent is "from now on, across everything," it goes through memory. If the intent is "right now, in that specific session," it goes through injection.

---

## Authority and Conflict Resolution

The office manager's directives represent the human's current explicit intent. The proxy's decisions are based on learned patterns from prior gate interactions. When they conflict, the office manager's directives take precedence.

This is consistent with how the proxy already works. At gates, human corrections override proxy predictions. A steering chunk from the office manager is conceptually equivalent to a gate correction: it is the human speaking directly, right now, about what they want. The proxy's learned pattern ("this human usually approves plans without rollback strategies") yields to the office manager's explicit directive ("I want rollback strategies in every plan").

The precedence is temporal and explicit. The most recent direct human statement wins. If the human told the office manager "focus on security" yesterday and then approves a non-security plan at a gate today, the gate approval is now the most recent signal. The system does not maintain a hierarchy of directive types. It maintains recency and explicitness as the arbiters.

---

## Memory

The office manager uses the same ACT-R memory infrastructure as the proxy. Same `MemoryChunk` dataclass, same activation dynamics, same SQLite storage. Different chunk types.

### Chunk Types

| Type | What it captures | Example |
|------|-----------------|---------|
| `inquiry` | What the human asked about | "Asked about POC project status" |
| `steering` | Priority or preference directive | "Wants security focus across all sessions" |
| `action_request` | What the human asked the office manager to do | "Requested commit and push for all projects" |
| `context_injection` | Domain knowledge the human volunteered | "Switching to Postgres next quarter" |

### Shared Memory Pool

The office manager and the proxy operate on the same human. What the office manager learns about the human's priorities is relevant to the proxy's gate decisions. What the proxy learns about the human's review patterns is relevant to the office manager's status reports.

Both agents read and write to the same `.proxy-memory.db`. Chunk type discriminates reads: the proxy queries for `gate_outcome` chunks, the office manager queries for `inquiry` and `steering` chunks. But either can query across types when the structural filters match. The proxy retrieving a `steering` chunk ("human said focus on security") while reviewing a security plan is exactly the right behavior.

This is a shared resource with concurrent access. SQLite in WAL mode supports concurrent readers with a single writer, and the write pattern (infrequent chunk insertions from either agent) makes contention negligible. Both agents may be active simultaneously; the database handles this without coordination.

A `steering` chunk with high activation naturally surfaces in both agents' retrievals when the situation matches. The office manager heard it; the proxy benefits from it without explicit forwarding.

### Recording Chunks from Conversation

The proxy records one chunk per gate interaction, a well-defined moment with clear structure. The office manager's conversations are less structured.

The office manager itself decides what to record. At conversation end, the TUI issues a final prompt turn asking the office manager to summarize what the human cared about and produce memory chunks. This is consistent with how agents work in this system: they are autonomous, not scripted. The recording is an agent judgment, not a mechanical extraction. The office manager has the full conversation context and can distinguish what mattered from what was incidental.

---

## Interruption

The office manager's hardest infrastructure requirement is intervention in active work. This requires infrastructure that doesn't fully exist yet.

### What Exists

- **CfA state machine** supports WITHDRAWN, with transitions from most active states
- **MCP tools** for agent-to-human escalation (AskQuestion) and agent-to-team dispatch (AskTeam). No MCP tools exist yet for orchestrator signaling (pause, withdraw).
- **Event bus** publishes orchestrator events that the TUI subscribes to
- **Stall watchdog** in `claude_runner.py` monitors subprocess liveness

### What's Needed

**Pause MCP tool.** A mechanism for the office manager to tell an active orchestrator: "stop launching new work, but let current work complete." This is not withdrawal (which terminates). It is a resumable hold.

One approach: the orchestrator checks for a `.paused` sentinel file in the session infra directory before each phase transition. The office manager creates the file; removing it resumes. The orchestrator's main loop already checks for terminal states between phases. Adding a pause check at the same point in the loop would be straightforward, though the pause semantics (resumable hold) differ from terminal state checks.

**Withdraw MCP tool.** A mechanism for the office manager to set a session's CfA state to WITHDRAWN. The orchestrator already handles the WITHDRAWN state; what's missing is the external signal path.

**Priority injection file.** The `.priority-context` file mechanism described in "Two Kinds of Influence" above. The orchestrator would check for this file before each phase, using the same prompt-prepend mechanism as `backtrack_context` but operating across phase boundaries rather than within a single phase's correction rounds.

**Dispatch throttle.** For "hold the presses" across all active work, the office manager needs to signal all active orchestrators, not just one. A global pause file (e.g., in the projects directory) that all orchestrators check before dispatching. The platform must provide a session discovery mechanism so the office manager can enumerate what's running. The existing `.running` sentinel convention in dispatch directories is a starting point.

---

## Session Lifecycle

The office manager's conversation is a `claude -p` session. Unlike agent turns within a CfA session (which are single-turn invocations), the office manager conversation may be multi-turn. The runtime substrate is the same; the usage pattern differs.

### Invocation

The human presses a key in the TUI. The TUI invokes `claude -p` with:

```
claude -p \
  --output-format stream-json \
  --agents <office-manager-agents.json> \
  --agent office-manager \
  --permission-mode bypassPermissions \
  --allowedTools Read,Glob,Grep,Bash \
  --mcp-config <mcp-config.json>
```

The prompt includes the human's message, serialized ACT-R memory chunks (retrieved before invocation by a thin wrapper, analogous to how `proxy_agent.py` retrieves chunks before building the proxy prompt), and a current platform state summary covering which projects exist, which sessions are active, and recent completions.

### Multi-Turn

The first invocation returns a session ID. Subsequent messages from the human use `--resume <session_id>` to continue the conversation. The office manager retains full context across turns within a conversation. Operational concerns around multi-turn (context window limits, session persistence across TUI restarts) should be addressed in detailed design.

### Conversation End

The human closes the conversation (keystroke or "thanks, that's all"). The TUI issues one final prompt turn asking the office manager to produce memory chunks summarizing the conversation. The TUI then stores the conversation transcript for future retrieval and discards the session (or keeps it for later resume).

### Between Conversations

The office manager is not persistent between conversations. Each conversation starts fresh from `claude -p`. But the ACT-R memory carries forward: what the human asked about last time, what priorities they set, what context they provided. The office manager doesn't remember the conversation verbatim, but the memory system preserves what the agent judged worth remembering.

A fresh agent with persistent memory avoids unbounded conversational state, context window pressure, and accumulated drift. It should be a fresh agent with good memory, not a long-running process with growing context.

---

## Relationship to the Proxy

The proxy and the office manager serve the same human through different channels.

The proxy is the human's shadow inside the CfA protocol. It appears at gates, reasons about artifacts with tools, and earns autonomy through accurate prediction. Its memory is tuned for gate decisions: what the human approves, what they correct, what they attend to in artifacts.

The office manager is the human's voice outside the CfA protocol. It appears when the human initiates conversation, acts on the human's behalf across the platform, and earns trust by being useful. Its memory is tuned for priorities, concerns, and cross-cutting context.

They share memory because they serve the same human. A steering directive given to the office manager should influence the proxy's next gate review. A pattern the proxy learned ("this human always asks about rollback plans") should inform the office manager's status reports. The shared memory pool makes this cross-pollination automatic rather than requiring explicit forwarding between agents.

The office manager does not replace the proxy, and the proxy does not replace the office manager. The boundary between them is load-bearing: the proxy's autonomy model depends on being the sole gate decision-maker, with accuracy tracking. If the office manager could also approve gates, the proxy's accuracy metrics would lose their meaning. When a human asks the office manager to approve something, the right response is to record their preference so the proxy handles it accordingly.

---

## Open Questions

1. **How is the conversation triggered from the TUI?** A dedicated keystroke? A persistent chat panel? An overlay that appears on demand?

2. **Should the office manager proactively surface information?** "I noticed the POC session has been in planning for an hour — want me to check on it?" This would require periodic polling or event bus triggers. It's proactive conversation initiation *from* the agent *to* the human, which is the reverse of the pattern this document describes. A future extension, not part of the core design.

3. **What are the evaluation criteria for success?** The proxy has a natural metric (gate prediction accuracy). The office manager's equivalent likely centers on conversation utility: did the human get what they needed? This should be defined during detailed design once usage patterns are clearer.
