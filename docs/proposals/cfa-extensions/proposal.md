[Milestone 3: Human Interaction Layer](../milestone-3.md) >

# CfA Extensions: INTERVENE and WITHDRAW

The human can intervene in any active job or task at any time — redirecting work, correcting course, or stopping everything. INTERVENE and WITHDRAW extend the CfA protocol to handle these unsolicited human actions.

---

## INTERVENE

An unsolicited course correction. The human types in a job or task chat when nobody asked them to. The lead receives the message and reassesses:

- **Continue with adjustment.** The current work is still valid; the lead incorporates the new information and proceeds from the current CfA state.
- **Backtrack.** The current work is invalidated. The lead returns to an earlier phase (typically PLAN, sometimes INTENT) with the human's instruction as new context.
- **Withdraw.** The lead judges that the intervention fundamentally changes the mission. The current session is no longer viable.

The key distinction from an escalation response: an escalation response answers a question. An intervention changes the question. The agent doesn't need to defend or redo the current artifact — it needs to reassess whether the current trajectory still makes sense.

The D-A-I role model applies: a decider's intervention is authoritative, an advisor's intervention is advisory. The lead has full discretion in both cases, but treats decider input with greater weight.

---

## WITHDRAW

A kill signal. The human clicks the Withdraw button on the dashboard. Everything stops:

- All active dispatches in the hierarchy are killed
- Subteam dispatches under the withdrawn workflow are cascaded — the entire process tree dies
- The CfA state transitions to WITHDRAWN
- The withdrawal is recorded in the session log

This is not a message in the chat. It is a kill signal. There is no pause-and-assess. The kill cascades immediately.

---

## Event Comparison

| Property | Protocol transition | INTERVENE | WITHDRAW |
|----------|-------------------|-----------|----------|
| Triggered by | Protocol participant (reviewer, approver) | Human typing in chat (unsolicited) | Human clicking Withdraw |
| Received by | Current role holder | Team/project lead | Entire hierarchy |
| What it means | "This artifact needs work" | "The world changed" | "Stop" |
| Lead discretion | N/A — transition rules apply | Full — continue, backtrack, or withdraw | None — immediate |
| Cascades | No | Lead decides | Yes — kills all children |

---

## Interrupt Propagation

When the human intervenes on a project lead that has active subteam dispatches:

- The lead pauses to process the intervention
- If the lead continues with adjustment, dispatches resume (or are adjusted)
- If the lead backtracks, active dispatches are withdrawn — the work they're doing is no longer aligned with the new direction
- If the lead withdraws, cascading withdrawal kills all dispatches

When the human withdraws directly, there is no pause-and-assess. The kill cascades immediately.

---

## Learning Signals

Both events are recorded as memory chunks. Interventions are particularly strong learning signals — they capture moments where the human saw something the agents missed, which is exactly what the proxy needs to learn.

---

## Relationship to Other Proposals

- [chat-experience](../chat-experience/proposal.md) — INTERVENE and WITHDRAW are triggered from the chat UI
- [dashboard-ui](../dashboard-ui/proposal.md) — WITHDRAW button on job and task dashboards
- [cognitive-architecture](../cognitive-architecture.md) — intervention chunks feed the proxy's learning system
- [CfA state machine](../../conceptual-design/cfa-state-machine.md) — the base protocol this extends

---

## Resolved: Intervention Handling

**Backtrack depth.** When an INTERVENE causes a backtrack, the lead sends the intervention through the proxy. The proxy weighs whether escalation to the human is required, or whether the lead can handle it autonomously. This is consistent with how all gate decisions work — the proxy predicts the human's intent, the lead acts, and if the proxy is uncertain, the human reviews.

**Advisor intervention weight.** Advisors can interject with advisory input. The proxy weighs whether the interjection requires escalation to the human, or whether the lead can handle it autonomously. The norms system provides guidance to the proxy, but the proxy makes the call about escalation.
