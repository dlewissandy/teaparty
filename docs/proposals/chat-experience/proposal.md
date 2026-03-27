[Milestone 3: Human Interaction Layer](../milestone-3.md) >

# Chat Experience

The human participates in TeaParty through conversation. Four patterns cover all human-agent interaction.

---

## Pattern 1: Office Manager Conversation

**Initiated by:** the human.
**Lifecycle:** open-ended, persistent across days or weeks.

The human opens a conversation with the office manager when they want to think, plan, or coordinate. Topics include project status, new project ideas, workgroup management, skill creation, scheduling, and cross-project steering. Sessions persist and can be resumed. See [office-manager](../office-manager/proposal.md).

---

## Pattern 2: Job and Task Chat

**One chat per job. One chat per task.** Everything that involves the human happens here: escalations, interventions, status questions, course corrections.

**Escalations** land in the chat when the proxy lacks confidence. The proxy formulates its own message. The human responds naturally. The escalation badge clears when resolved.

**Interventions** are unsolicited human input at any time, triggering an INTERVENE event. Delivery happens at turn boundaries. See [cfa-extensions](../cfa-extensions/proposal.md).

**Withdrawals** use the dashboard Withdraw button. This is a kill signal, not a chat message. See [cfa-extensions](../cfa-extensions/proposal.md).

### Who can speak

The D-A-I role model determines participation:

- **Decider** -- can respond to escalations, intervene, and withdraw. Input is authoritative.
- **Advisor** -- can interject (same mechanic as INTERVENE). Input is advisory.
- **Informed** -- can read but not write.

---

## Pattern 3: Proxy Review Session

The human opens a chat with their own proxy to inspect and calibrate its model. See [proxy-review](../proxy-review/proposal.md).

---

## Pattern 4: Liaison Chat (Future)

The human opens a chat with another team member's proxy. Deferred pending multi-machine and licensing considerations. See [proxy-review](../proxy-review/proposal.md).

---

## Conversation Identity

See [references/conversation-identity.md](references/conversation-identity.md) for the identity and persistence table for each pattern.

---

## Learning from Conversations

Every pattern generates learning signals. Office manager conversations produce steering chunks and context injections. Job/task escalations are the richest signal, with full dialog between proxy reasoning and human corrections. Interventions capture moments where the human saw something the agents missed. Proxy review sessions are direct calibration -- the most direct signal since they carry explicit human intent, though they lack the artifact context that gate corrections provide. The activation weighting for review corrections versus gate corrections may need to differ; see [proxy-review open questions](../proxy-review/proposal.md#open-questions).

For examples of how learning crosses between conversation patterns, see [office-manager: Relationship to the Proxy](../office-manager/proposal.md#relationship-to-the-proxy).
