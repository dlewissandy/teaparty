[Milestone 3: Human Interaction Layer](../milestone-3.md) >

# Agent Dispatch

Agents are not subprocesses inside a lead's context. Each agent is an independent `claude -p` invocation with its own working environment, its own skill set, and its own conversation thread on the message bus. The lead coordinates by posting messages, not by holding its team in memory.

---

## Single-Agent Invocations

Every agent — lead or worker — runs as a standalone `claude -p` process. There are no team bundles, no `--agents` flag, no lead spawning teammates via the `Agent` tool. When a lead needs a team member's work, it posts a message to the bus. TeaParty spins up the receiving agent independently.

This changes the lead's role: it decomposes work, posts requests, and synthesizes responses. It no longer needs to hold the whole team in context simultaneously.

See [references/invocation-model.md](references/invocation-model.md) for the worktree composition step, skill isolation via `--setting-sources project`, and MCP scoping via `--settings`.

---

## Agent-to-Agent Messaging

Agent-to-agent communication goes through the message bus — the same bus that carries human-agent conversations. This supersedes the current messaging proposal's statement that agent-to-agent communication is "via MCP tools and dispatch, not through the message bus."

When an agent posts a message to a teammate (via `AskTeam` MCP tool), the bus creates a conversation context. TeaParty spins up the receiving agent with that context. The exchange is multi-turn: the receiving agent can ask a follow-up, the caller can respond, all on the same context ID. The caller is not blocked — it can continue other work while waiting for a response.

See [references/conversation-model.md](references/conversation-model.md) for context identity, multi-turn mechanics, the navigator hierarchy, and escalation routing.

---

## Routing and Boundaries

Bus routing determines which agents can initiate conversations with which others. Routing policy is derived from workgroup membership — a coding worker does not have a direct bus route to a config specialist. Cross-team requests within a project go through the project lead or OM.

Cross-project communication is always mediated by the office manager. Project-scoped agents have no direct bus routes to other projects. The OM holds cross-project context and translates between them.

This replaces the liaison agent concept. Pattern 4 (Liaison Chat) in the chat-experience proposal is superseded: the liaison function is now a routing rule in the bus, not a separate agent role.

See [references/routing.md](references/routing.md) for the full routing rule structure, the OM's cross-project gateway role, and the disposition of #332.

---

## Skill Isolation

Each agent invocation gets a worktree with a composed `.claude/skills/` directory. Skill composition is: common skills available to all roles, plus the role-specific skills for that agent's workgroup, plus project-scoped skills for the active project. The orchestrator performs this composition at spawn time — it already knows the agent's role and project context.

`--setting-sources project` suppresses user-scope skill discovery, so the agent sees exactly the composed set and nothing else. TeaParty's own orchestration skills are never in the composition unless the agent's role explicitly includes them.

---

## Supersedes

- [messaging/proposal.md](../messaging/proposal.md) — "Agent to Agent" section: agent-to-agent now goes through the bus
- [chat-experience/proposal.md](../chat-experience/proposal.md) — Pattern 4 (Liaison Chat): replaced by bus routing rules and OM mediation
- #332 — OM chat invocation missing liaisons: liaison agents are not implemented; bus routing rules cover the routing function

---

## Prerequisites

- [Messaging](../messaging/proposal.md) — bus transport, conversation identity, adapter interface
- [Office Manager](../office-manager/proposal.md) — OM as cross-project gateway

---

## Relationship to Other Proposals

- [Team Configuration](../team-configuration/proposal.md) — workgroup membership is the input to routing rule derivation
- [CfA Extensions](../cfa-extensions/proposal.md) — escalation events bubble up the conversation chain using the same INTERVENE/WITHDRAW mechanics
- [Context Budget](../context-budget/proposal.md) — each agent invocation has its own context; the budget applies per-invocation
