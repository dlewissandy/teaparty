# Milestone 3: Human Interaction Layer

[GitHub Milestone](https://github.com/dlewissandy/teaparty/milestone/3)

Humans are team members, not external observers. This milestone builds the infrastructure for humans to participate at every level of the TeaParty hierarchy. The system learns from their participation at each level, and what it learns at one level informs how it works at others.

For the full participation model (hierarchy, proxy transitions, cold start, evaluation criteria), see [references/participation-model.md](references/participation-model.md).

All proposals in this milestone are designed for single-machine, single-user operation. Multi-user features (liaison mode, cross-machine messaging) are out of scope due to licensing constraints; see [compliance](messaging/references/compliance.md).

---

## Proposals

| Proposal | Description |
|----------|-------------|
| [Chat Experience](chat-experience/proposal.md) | Four interaction patterns: office manager conversations, job/task chats, proxy review, liaison |
| [CfA Extensions](cfa-extensions/proposal.md) | INTERVENE and WITHDRAW as new CfA events, interrupt propagation |
| [Office Manager](office-manager/proposal.md) | The human's coordination partner above the CfA protocol |
| [Messaging](messaging/proposal.md) | Message bus abstraction for human-agent conversations |
| [Dashboard UI](dashboard-ui/proposal.md) | Hierarchical dashboard with drill-down navigation |
| [Team Configuration](team-configuration/proposal.md) | File-based configuration tree mirroring the team hierarchy |
| [Configuration Team](configuration-team/proposal.md) | Workgroup for creating and modifying Claude Code artifacts |
| [Context Budget](context-budget/proposal.md) | Stream-based context extraction and compaction management |
| [Proxy Review](proxy-review/proposal.md) | Direct channel to inspect and calibrate the proxy's model, plus liaison mode for async team communication |
| [Agent Dispatch](agent-dispatch/proposal.md) | Single-agent invocations, bus-mediated agent-to-agent messaging, worktree skill isolation, routing rules replacing liaison agents |
