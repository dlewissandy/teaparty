# Compaction Thresholds and Actions

The orchestrator triggers compaction when context utilization exceeds specific thresholds. The control mechanism is turn-boundary injection: the orchestrator waits for the current turn to complete, then injects the compaction command as the next prompt via `--resume`.

| Threshold | Action | Owner |
|-----------|--------|-------|
| 70% | Warning. Orchestrator ensures scratch files are current. | Orchestrator |
| 78% | Compact. Orchestrator injects `/compact` via `--resume` at the next turn boundary, with a focus derived from the current task. | Orchestrator |
| ~83% | Auto-compaction fires (Claude Code's built-in behavior). Acts as a backstop if orchestrator compaction did not reduce context sufficiently. | Claude Code |

The orchestrator's proactive threshold (78%) fires below Claude Code's built-in auto-compaction (~83%). This gives the orchestrator control over the compaction focus argument, directing the agent's attention to the current task rather than relying on Claude Code's generic summarization. If orchestrator-managed compaction does not reduce context below 83%, the built-in fires as a safety net.

The focus argument to `/compact` is generated from the current CfA state and task description: `/compact focus on implementing ACT-R retrieval -- current phase is WORK, 2 of 4 tasks complete`.

Budget pausing uses the same mechanism: the orchestrator withholds the next prompt until the human responds to the budget escalation.
