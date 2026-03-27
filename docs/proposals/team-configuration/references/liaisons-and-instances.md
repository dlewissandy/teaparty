# Liaisons and Instances

In a human organization, the project lead on the management team *is* the project lead. In TeaParty, the team member at each level is a **liaison** — a lightweight representative of the subteam below. The liaison is the stable identity on the parent team: the contact point for queries, status, and coordination.

From the parent team's perspective, the liaison *is* the team lead. It knows its project's state, history, work output, team composition, and current blockers. It answers questions authoritatively. The office manager asks "how's the POC project going?" and the liaison answers — it doesn't need to spawn anything to provide status or discuss tradeoffs.

When execution is needed — a new session, a dispatch, a phase that requires active work — the liaison spawns **instances**: actual team lead processes with their own context, tools, and sessions. A liaison can spawn multiple concurrent instances. The project lead liaison on the management team might have three active project sessions running simultaneously, each as a separate instance.

This has no real-world analog. A human VP cannot instantiate three copies of themselves to run three meetings at once. But a liaison can, and this is fundamental to how TeaParty scales. The distinction between liaison and instance is an implementation detail, not a conversational one. To the parent team, the liaison is the project lead. The spawning capability is invisible.

The hierarchy is extensible upward. "Top" is arbitrary — a board of directors above the management team, or a department head above multiple office managers, would use the same team lead pattern. Nothing in the architecture assumes the management team is the root.
