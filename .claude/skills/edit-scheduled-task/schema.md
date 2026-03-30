# Scheduled Task Edit Reference

Read `../create-scheduled-task/schema.md` for the full entry format and cron syntax.

## Common edits

**Change the schedule:**
```yaml
schedule: "0 6 * * *"   # was 2am, now 6am
```

**Disable without removing:**
```yaml
enabled: false
```

**Change the skill arguments:**
```yaml
args: "--project my-backend --verbose"
```

**Change the skill reference:**
```yaml
skill: new-skill-name    # confirm .claude/skills/new-skill-name/SKILL.md exists first
```

## Enabling/disabling vs. removing

Prefer `enabled: false` over removal if the task may be re-enabled later. Use `remove-scheduled-task` only when the task is permanently retired.
