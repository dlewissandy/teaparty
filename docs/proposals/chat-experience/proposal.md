[Milestone 3: Human Interaction Layer](../milestone-3.md) >

# Chat Experience

The human participates in TeaParty through conversation. They talk to the office manager for coordination, chat with job and task agents for hands-on work, review and calibrate their proxy's model, and communicate with other team members through liaison sessions.

---

## Pattern 1: Office Manager Conversation

**Initiated by:** the human.
**Lifecycle:** open-ended, persistent across days or weeks.

The human opens a conversation with the office manager when they want to think, plan, or coordinate. The office manager answers by querying its team. Topics include project status, new project ideas, workgroup management, skill creation, scheduling, and cross-project steering.

The conversation meanders — free-form dialog between teammates. Sessions persist. The human can leave and come back hours or days later. Each session has an ID; the human can see past sessions, resume any of them, or start a new one.

---

## Pattern 2: Job and Task Chat

**One chat per job. One chat per task.** This is the human's channel to the agents working on that unit of work. Everything that involves the human happens here: escalations, interventions, status questions, course corrections.

**Escalations** — when the proxy lacks confidence, it posts in the chat. The proxy formulates its own message — no canned format. The human responds naturally. The escalation badge clears when resolved.

**Interventions** — the human types at any time, unsolicited. This triggers an INTERVENE event. See [cfa-extensions](../cfa-extensions/proposal.md) for how the lead processes interventions.

**Withdrawals** — the human clicks the Withdraw button on the dashboard. This is a kill signal, not a chat message. See [cfa-extensions](../cfa-extensions/proposal.md).

**One chat, not many.** There is no separate escalation or intervention window. The UI only needs one concept: **open the chat**.

### Who can speak

The D-A-I role model determines participation:

- **Decider** — can respond to escalations, intervene, and withdraw. Input is authoritative.
- **Advisor** — can interject (same mechanic as INTERVENE). Input is advisory.
- **Informed** — can read but not write.

---

## Pattern 3: Proxy Review Session

The human opens a chat with their own proxy to inspect and calibrate its model. See [proxy-review](../proxy-review/proposal.md).

---

## Pattern 4: Liaison Chat (Future)

The human opens a chat with another team member's proxy. See [proxy-review](../proxy-review/proposal.md) — liaison mode is deferred pending multi-machine and licensing considerations.

---

## Conversation Identity

See [references/conversation-identity.md](references/conversation-identity.md) for the identity and persistence table for each pattern.

---

## Learning from Conversations

Every pattern generates learning signals:

- **Office manager conversations** — steering chunks, context injections, inquiry patterns.
- **Job/task escalations** — the richest signal. Full dialog: proxy reasoning, human questions, corrections, final decision. Builds a model of the human's reasoning process.
- **Interventions** — correction signals. The human saw something the agents missed.
- **Proxy review sessions** — direct calibration. The strongest signal — explicit human intent about what the proxy should learn.

---

## Relationship to Other Proposals

- [messaging](../messaging/proposal.md) — the message bus that carries conversations
- [office-manager](../office-manager/proposal.md) — the office manager agent
- [cfa-extensions](../cfa-extensions/proposal.md) — INTERVENE and WITHDRAW as CfA events
- [proxy-review](../proxy-review/proposal.md) — proxy review and liaison sessions
- [dashboard-ui](../dashboard-ui/proposal.md) — the chat entry points on each dashboard
- [team-configuration](../team-configuration/proposal.md) — structural symmetry, liaison/instance model

