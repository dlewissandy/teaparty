# Scheduled Task Schema

## YAML entry format

```yaml
scheduled:
  - name: nightly-test-sweep        # unique identifier; kebab-case
    schedule: "0 2 * * *"           # cron expression
    skill: test-sweep               # must exist in .claude/skills/
    args: "--all-projects"          # optional arguments passed to the skill
    enabled: true                   # default: true
```

## Cron expression syntax

```
┌─── minute (0–59)
│ ┌─── hour (0–23)
│ │ ┌─── day of month (1–31)
│ │ │ ┌─── month (1–12)
│ │ │ │ ┌─── day of week (0–6, Sunday=0)
│ │ │ │ │
* * * * *
```

## Common schedules

| Natural language | Cron expression |
|---|---|
| Every night at 2am | `0 2 * * *` |
| Every Monday at 9am | `0 9 * * 1` |
| Every hour | `0 * * * *` |
| Every 15 minutes | `*/15 * * * *` |
| First of every month at midnight | `0 0 1 * *` |

## Required fields

- `name` — unique identifier; must not conflict with other scheduled entries in the same file
- `schedule` — valid cron expression (5 fields)
- `skill` — must exist as `.claude/skills/{skill}/SKILL.md`

## Scope

| Scope | File | Use for |
|---|---|---|
| Management | `~/.teaparty/teaparty.yaml` | Cross-project tasks (digests, sweeps) |
| Project | `{project}/.teaparty/project.yaml` | Project-specific recurring work |
