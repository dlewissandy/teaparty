# Norms

Norms are advisory natural-language statements that agents read and incorporate into their judgment. They are not enforced by code -- agents are autonomous, not scripted.

When an agent violates a norm, the human corrects the gate decision, and the proxy learns to anticipate that correction in the future. Enforcement happens through learning, not through code.

For norms that must remain influential over extended periods, the memory system could use a pinned activation floor (ACT-R's `set-base-levels` / `fixedActivation`), setting a minimum base-level activation for tagged chunks so they resist normal decay. The tradeoff is that pinned chunks consume retrieval capacity that contextually relevant but unpinned chunks would otherwise occupy. Whether pinning is worth the cost depends on empirical decay rates under standard dynamics.

Cost budgets are distinct from norms. They live in their own `budget:` YAML key and are enforced mechanically by the orchestrator. See [context-budget/cost-budget.md](../../context-budget/references/cost-budget.md).

## Structure

Norms appear at three levels:

- **Organization norms** (in `teaparty.yaml`)
- **Workgroup norms** (in workgroup YAML)
- **Project norms** (in `project.yaml`)

## Precedence

Norms follow the same precedence model as Claude Code's `.claude/` settings: **project trumps organization**.

When a shared workgroup is dispatched on a project task, the agent reads norms from both its workgroup definition and the requesting project. If they conflict, the project's norms win. This means a shared coding workgroup behaves consistently in its own practices (review process, delegation patterns) but adapts to each project's quality requirements (test coverage thresholds, migration rules).

The layering:

1. **Workgroup norms** -- the baseline (how this team works)
2. **Project norms** -- the override (what this project requires)

An agent reads both and treats conflicts as "project wins." This is not a merge. If the project says "all changes require integration tests" and the workgroup says "unit tests are sufficient," the project norm applies for tasks in that project.

## Example

From a workgroup's YAML (baseline practices):

```yaml
norms:
  quality:
    - Code review required before merge
    - Test coverage must not decrease
  tools:
    - Developers may not use WebSearch
    - Architect has read-only access
  delegation:
    - Architect produces the plan, Developer implements
    - Reviewer checks against plan before approval
```

From a project's `project.yaml` (project-specific overrides):

```yaml
norms:
  quality:
    - All code changes must have tests
    - Database migrations require rollback strategies
  delegation:
    - Coding workgroup handles implementation and testing
    - Research workgroup handles design proposals and literature review

budget:
  job_limit_usd: 5.00
  project_limit_usd: 50.00
```

Agents incorporate norms naturally: they shape decisions, not enforce rules. Budgets are separate and mechanically enforced.
