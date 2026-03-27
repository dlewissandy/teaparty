# Cost Budget Enforcement

The `result` events include `total_cost_usd` and per-model cost breakdowns. The orchestrator tracks cumulative cost per job and per project.

## Budget Enforcement

| Level | Budget source | Enforcement |
|-------|-------------|-------------|
| Job | Project norms or explicit budget in job config | Orchestrator warns at 80%, pauses at 100% |
| Project | Project YAML | Orchestrator aggregates across jobs |
| Management | `teaparty.yaml` | Orchestrator aggregates across projects |

When a budget is exceeded, the orchestrator can pause the job and escalate to the human via the job's chat: "This job has used $X of its $Y budget. Continue?"
