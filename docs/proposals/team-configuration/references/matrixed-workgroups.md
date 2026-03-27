# Matrixed Workgroups

Workgroups can be **shared across projects**. A coding workgroup that understands how the human likes to work — their testing conventions, review standards, architectural preferences — should be reusable across all coding projects. The human shouldn't have to re-teach a new coding team for every project.

## Reference vs. Definition

A project can either **define** a workgroup (inline, project-scoped) or **reference** one (shared, defined at a higher level). This follows the same precedence model as Claude Code's `.claude/` settings: project-level definitions override organization-level defaults.

- **Organization-level workgroups** live in `~/.teaparty/workgroups/`. Any project can reference them.
- **Project-level workgroups** live in `{project}/.teaparty/workgroups/`. They override organization-level workgroups of the same name for that project.

## Norm Precedence

When a shared workgroup is dispatched on a task, it reads norms from the requesting project, not from its own definition. The workgroup's own norms (quality practices, tool restrictions, delegation patterns) are its baseline. The project's norms layer on top — project norms trump workgroup norms, just as project `.claude/settings.json` trumps global settings.

## Cross-Project Learning

A shared workgroup's memory accumulates experience across all projects it serves. This is a feature: the coding workgroup learns patterns from project A that help it on project B. The structural filters on memory retrieval (project, job, task) scope what surfaces — a task on project B won't retrieve implementation details from project A, but it will retrieve general patterns about what the human cares about.
