# Agent Dispatch

How TeaParty routes messages to agents and how agent responses are produced.

TeaParty does not select speakers or orchestrate turn-taking. It dispatches user messages to Claude, which handles all coordination autonomously. Multi-agent collaboration uses Claude's native team sessions with streaming I/O.

---

## Routing

Messages are routed by conversation kind. Job conversations with multiple agents use persistent team sessions; single-agent and direct conversations use isolated per-agent invocations. Fan-out (`@each`) runs one invocation per agent independently. Admin conversations are handled by a deterministic command handler without LLM selection. Activity conversations produce no auto-response.

Only user messages trigger responses in job conversations. Agent messages are ignored to prevent re-triggering loops.

---

## Multi-Agent Team Sessions

When multiple agents need to collaborate, TeaParty uses **persistent team sessions** — long-lived `claude` processes with bidirectional `stream-json` I/O.

A user message is dispatched to an existing team session or starts a new one. The session spawns a `claude` process with all agent definitions and designates the lead. Agents contribute messages one at a time as they respond; each message is committed to the database immediately and picked up by the frontend's polling.

**Session lifecycle**: Created on the first message to a multi-agent job conversation. Reused for all follow-up messages in the same conversation (the process retains full context). Stopped when the conversation is cancelled or the server shuts down.

**Lead agent**: The agent with `is_lead=True` is the team lead. Its prompt includes a teammates roster so it knows who to delegate to. Other agents receive the same file context but not the teammate list.

**File access**: Workspace-enabled workgroups use git worktrees; non-workspace workgroups use virtual files materialized to a temporary directory. After each exchange, file changes on disk are synced back to the workgroup's virtual file store.

---

## Independent Fan-Out (`@each`)

When a message is addressed `@each`, every agent receives the same conversation history and responds independently via separate `claude -p` invocations. No agent sees another's response. Fan-out takes priority over team invocation when both are present.

---

## Lead Agents

Every organizational level has an explicit lead agent (`is_lead=True`) that serves as the default responder and the top-level agent in multi-agent team sessions.

| Level | Created when | Role |
|---|---|---|
| Home | User first login | Creates orgs, manages partnerships |
| Organization | Organization is created | Orchestrates engagements, projects; decomposes work to workgroups |
| Workgroup | Workgroup is created | Manages jobs, onboards agents |

See [ARCHITECTURE.md](ARCHITECTURE.md) for the full hierarchy and how lead agents interact across levels.

---

## Hierarchical Team Dispatch

Projects and engagements create hierarchical teams — multiple independent Claude Code team sessions connected by liaison agents. See [hierarchical-teams.md](hierarchical-teams.md) for the full design.

When a project starts, a team session is created with the org lead as team lead and one liaison per participating workgroup. The org lead coordinates work using native team primitives; liaisons relay tasks to sub-teams and results back up.

When a liaison dispatches to a subteam for the first time, a job and job conversation are created, a new team session is launched, and the liaison's message becomes the initial task prompt. Subsequent liaison calls send messages to the existing session.

**Async notification bridge**: When a sub-team produces notable output (completion, question, stall), TeaParty injects a notification into the parent team session addressed to the relevant liaison. The liaison relays it to the team lead. This bridges the async gap between independent processes without the liaison needing to poll.

**Engagement dispatch** follows the same pattern in two phases: single-agent dispatch during negotiation, then a full team session (org lead + internal liaisons + external liaison) once work begins.

**Job teams inherit configuration** from their workgroup defaults, optionally overridden by the parent project: model, permission mode, max turns, and cost/time limits.

---

## Feedback Routing

When agents need human input, feedback flows up the hierarchy: job agent → workgroup lead → org lead → human. The response routes back down the same path. Each level filters and contextualizes before escalating.
