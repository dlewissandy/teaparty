[Milestone 3: Human Interaction Layer](../milestone-3.md) >

# Proxy Review Sessions

The human can talk directly to the proxy that models their decision-making — inspecting what it's learned, correcting patterns that are wrong, and reinforcing ones that matter. In the future, they can also query other team members' proxies for status and context.

---

## Two Modes, One Agent

The proxy serves two roles depending on who's talking to it:

### Self-Review (your own proxy)

When you open a chat with your own proxy, you get full transparency into its model of you. This is a calibration session:

- **Inspect**: "What patterns have you picked up about my review preferences?"
- **Correct**: "Stop flagging missing rollback strategies — we decided that's not needed for internal tools"
- **Reinforce**: "I care more about test coverage than you think"
- **Explore**: "What are you least confident about?"

The proxy responds from its actual ACT-R memory — retrieving chunks, explaining activation levels, and surfacing its salient percepts. Corrections are recorded as high-activation learning signals that immediately influence future gate predictions.

This replaces manual editing of `proxy-patterns.md` with a conversation. The human talks to the agent that models them, and the agent updates its model in real time.

### Liaison Mode (someone else's proxy) — Future

When you open a chat with another team member's proxy, the proxy acts as a liaison. It answers questions about what that person has been working on, what decisions they've made, and what their priorities are — drawn from steering chunks, gate outcomes, and work history.

It does not expose the internal model: no confidence scores, no prediction patterns, no correction history. The proxy answers the way a knowledgeable colleague would — from the work record, not from the personality model.

This serves two purposes:

**Asynchronous team communication.** "Hey, what has Joe been working on?" works even when Joe is offline. The proxy answers from accumulated context.

**Escalation to other humans.** "Why did Joe tell the foo project to use the bar library?" If the proxy can answer from its recorded context, it does. If it can't, it escalates to the actual human — which lands in Joe's dashboard as an escalation badge, just like any other escalation.

**Out of scope for this milestone.** Liaison mode requires cross-machine agent communication, which is blocked by privacy (proxy memory is local and never committed) and licensing constraints (invoking another user's `claude -p` is prohibited). See [messaging compliance](../messaging/references/compliance.md). Self-review works today; liaison mode is deferred.

---

## Scope

Proxy review sessions have no project or job scope. The proxy is a global entity (one per human, shared across all projects). Learnings from a review session are global — they influence the proxy's behavior everywhere.

This is intentional. The review session is about calibrating the proxy's model of the human, not about any specific piece of work.

---

## Dashboard Integration

The management dashboard gets a **Humans** card listing all team members (from the `humans:` key in `teaparty.yaml`). Each entry shows the human's name and role.

| Who you click | What opens |
|---------------|-----------|
| Yourself | Proxy review session — full transparency, calibration mode |
| Someone else | Liaison chat — work history and decisions, no internal model |

The proxy agent handles both modes. It knows who's asking (the current decider) and adjusts its disclosure accordingly.

---

## Privacy Boundary

The distinction between self-review and liaison mode is a privacy boundary:

| Information | Self-review | Liaison mode |
|-------------|------------|-------------|
| What the human decided at gates | Yes | Yes |
| What steering directives they gave | Yes | Yes |
| What they've been working on | Yes | Yes |
| Proxy confidence scores | Yes | No |
| Prediction accuracy history | Yes | No |
| Correction patterns | Yes | No |
| Salient percepts and activation levels | Yes | No |

The proxy's internal model of a person — how they think, what they miss, where they're predictable — is private to that person. The work record is shared.

---

## Relationship to Decider-Advisor-Informed Roles

The D-A-I role model (see [team-configuration](../team-configuration/proposal.md)) determines what each human can do in team chats. The proxy review session is orthogonal — it's about the human's relationship with their own proxy, not their role on a team.

- **Deciders** use self-review to calibrate the proxy that models them at gates.
- **Advisors** use self-review to calibrate any proxy that represents them (if they are a decider on another team). They use liaison mode to understand what other team members care about.
- **Informed** members can use liaison mode to ask questions about team activity, but they have no proxy of their own to review (they are not modeled).

Only humans who are a decider on at least one team have a proxy to review.

---

## Relationship to Other Proposals

- [office-manager](../office-manager/proposal.md) — the office manager is for organizational coordination; the proxy review is for personal calibration. Different agents, different purposes.
- [chat-experience](../chat-experience/proposal.md) — proxy review sessions follow the same chat pattern (one chat, same stream filtering, same escalation mechanics).
- [dashboard-ui](../dashboard-ui/proposal.md) — the Humans card on the management dashboard is the entry point.
- [team-configuration](../team-configuration/proposal.md) — the `humans:` key in YAML provides the data for the Humans card.
- [cognitive-architecture](../cognitive-architecture.md) — the proxy's ACT-R memory is what the self-review session exposes and corrects.

---

## Open Questions

1. **Correction strength.** When the human corrects the proxy in a review session, how strong is the learning signal relative to a gate correction? Gate corrections come with full artifact context. Review corrections are abstract ("care more about X"). The activation boost may need to differ.
