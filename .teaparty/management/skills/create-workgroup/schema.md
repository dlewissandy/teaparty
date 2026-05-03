# Workgroup YAML Schema

```yaml
# Workgroup — {name}
name: Coding
description: One-line description of what this workgroup does.
lead: coding-lead                   # → .claude/agents/coding-lead.md

team_file: .claude/agents/coding-team.json   # optional team JSON

agents:
  - name: Coding Lead
    role: team-lead
    model: claude-sonnet-4-5
  - name: Architect
    role: specialist
    model: claude-opus-4-5
  - name: Developer
    role: specialist
    model: claude-sonnet-4-5

# Workgroup-level skills catalog — lists skills this workgroup makes available for
# dispatch. NOT an access control list — per-agent access is controlled by the
# skills: allowlist in each agent definition.
skills:
  - fix-issue
  - code-cleanup

norms:
  quality:
    - Code review required before merge
  tools:
    - Developers may not use WebSearch
  delegation:
    - Architect produces the plan, Developer implements

stats:
  storage: .teaparty/stats/workgroup-name.json
```

## Scope locations

| Scope | Path |
|---|---|
| Shared (org-level) | `~/.teaparty/workgroups/{name}.yaml` |
| Project-scoped | `{project}/.teaparty/workgroups/{name}.yaml` |

## Agent roles

- `team-lead` — the workgroup lead; receives dispatches and coordinates
- `specialist` — domain expert; lead routes specific tasks to them

## Registration

After creating the YAML, add a `workgroups:` entry to the parent config:

```yaml
# In teaparty.yaml (shared) or project.yaml (project-scoped):
workgroups:
  - name: Coding
    config: workgroups/coding.yaml
    status: active
```
