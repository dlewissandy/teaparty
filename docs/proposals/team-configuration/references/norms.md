# Norms

Norms are advisory, not enforced by code. They are natural-language statements that agents read and incorporate into their judgment. This is consistent with the project's core principle: agents are autonomous, not scripted.

## Structure

Norms appear at three levels:

- **Organization norms** (in `teaparty.yaml`) — organization-wide standards
- **Workgroup norms** (in workgroup YAML) — team-specific practices
- **Project norms** (in `project.yaml`) — project-specific quality and delegation rules

## Precedence

Norms follow the same precedence model as Claude Code's `.claude/` settings: **project trumps organization**.

When a shared workgroup is dispatched on a project task, the agent reads norms from both its workgroup definition and the requesting project. If they conflict, the project's norms win. This means a shared coding workgroup behaves consistently in its own practices (review process, delegation patterns) but adapts to each project's quality requirements (test coverage thresholds, migration rules).

The layering:

1. **Workgroup norms** — the baseline (how this team works)
2. **Project norms** — the override (what this project requires)

An agent reads both and treats conflicts as "project wins." This is not a merge — if the project says "all changes require integration tests" and the workgroup says "unit tests are sufficient," the project norm applies for tasks in that project.

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
```

Agents incorporate these norms naturally: they're part of the context that shapes decisions, not rules enforced by runtime validation.
