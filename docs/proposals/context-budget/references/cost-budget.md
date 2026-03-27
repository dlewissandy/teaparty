# Cost Budget Enforcement

The `result` events include `total_cost_usd` and per-model cost breakdowns. The orchestrator tracks cumulative cost per job and per project.

## Budget Configuration

Cost budgets are configuration values with mechanical enforcement, not advisory norms. They live in their own YAML key, separate from the `norms:` block:

```yaml
budget:
  job_limit_usd: 5.00
  project_limit_usd: 50.00
```

Norms are advisory statements that agents incorporate into judgment. Budgets are hard limits that the orchestrator enforces. Keeping them separate avoids conflating the two.

## Enforcement

| Level | Budget source | Enforcement |
|-------|-------------|-------------|
| Job | `budget:` in project YAML or job config | Orchestrator warns at 80%, pauses at 100% |
| Project | `budget:` in project YAML | Orchestrator aggregates across jobs |
| Management | `budget:` in `teaparty.yaml` | Orchestrator aggregates across projects |

When a budget is exceeded, the orchestrator pauses the job at the next turn boundary (the same mechanism as compaction triggering: withhold the next prompt via `--resume` until the human responds) and escalates to the human via the job's chat: "This job has used $X of its $Y budget. Continue?"
