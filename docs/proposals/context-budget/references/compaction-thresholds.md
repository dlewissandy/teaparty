# Compaction Thresholds and Actions

The orchestrator triggers compaction when context utilization exceeds specific thresholds:

| Threshold | Action |
|-----------|--------|
| 70% | Warning. Orchestrator ensures scratch files are current. |
| 85% | Compact. Orchestrator triggers `/compact` with a focus derived from the current task. |
| 95% | Auto-compaction fires (Claude Code's built-in behavior). Scratch files ensure nothing critical is lost. |

The focus argument to `/compact` is generated from the current CfA state and task description: `/compact focus on implementing ACT-R retrieval — current phase is WORK, 2 of 4 tasks complete`.
