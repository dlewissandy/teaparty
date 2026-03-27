# Self-Improvement: Automated Validation and Evolution of Configuration Artifacts

Teams can improve their own capabilities over time — validating that skills work correctly, testing that hooks fire as expected, and evolving their configuration based on what they learn. This happens below the radar of what the human needs to know about.

**Not part of Milestone 3.** This proposal is for a future milestone, once the configuration infrastructure ([team-configuration](../team-configuration/proposal.md), [configuration-team](../configuration-team/proposal.md)) is in place.

---

## The Idea

When the Configuration Team creates a skill, agent, or hook, it currently reports completion and the human reviews the result. There is no automated validation step — no way to know if the skill actually works, the agent has the right tools, or the hook fires on the right events.

Self-improvement wires validation and evolution into the team's normal workflow:

- **Skills** can be tested by invoking them with a sample input and checking the output
- **Agents** can be tested by spawning them with a simple prompt and verifying they have the right tools and permissions
- **Hooks** can be tested by simulating the trigger event and checking the handler's response
- **Norms** can be evaluated by reviewing recent gate outcomes against the stated norms and flagging drift

If hooks and skills support self-testing as a built-in capability, the Configuration Team can validate artifacts as part of the creation flow — no human involvement needed.

---

## Evolution

Beyond validation, teams can evolve their own configuration:

- A workgroup that consistently encounters the same kind of task could propose a new skill to the Configuration Team
- A proxy that notices a pattern of corrections could suggest a norm update
- A team lead that observes repeated backtrack patterns could recommend a workflow change

These are agent-initiated proposals that flow through the normal CfA protocol — the human approves or rejects at the gate, but the initiative comes from the agents.

---

## Prerequisites

- [Team Configuration](../team-configuration/proposal.md) — the YAML configuration tree must be in place
- [Configuration Team](../configuration-team/proposal.md) — the team that creates and modifies artifacts must exist
- [CfA Extensions](../cfa-extensions/proposal.md) — agent-initiated proposals need the CfA protocol

---

## Open Questions

1. **Scope of autonomous evolution.** How much can agents change without human approval? Skill optimization (progressive disclosure refactoring) is low-risk. Changing an agent's permission mode is high-risk. The boundary needs definition.

2. **Feedback loop safety.** Self-modifying agents risk positive feedback loops — an agent makes itself more autonomous, which lets it make itself more autonomous. The decider must remain the circuit breaker.
