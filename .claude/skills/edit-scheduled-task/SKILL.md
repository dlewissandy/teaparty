---
name: edit-scheduled-task
description: Modify an existing scheduled task entry — change the schedule, arguments, skill reference, or enabled state.
argument-hint: <task-name>
user-invocable: false
allowed-tools: Read, Glob, Grep, Bash
---

# Edit Scheduled Task

Modify the scheduled task `$ARGUMENTS`.

## Steps

1. Locate the task entry. Check `~/.teaparty/teaparty.yaml` and `{project}/.teaparty.local/project.yaml`.
2. Read the current entry.
3. Clarify what needs to change. Read `schema.md` for field reference.
4. Call `EditScheduledTask(name, field, value)` with the change. If the `skill:` field is changing, confirm the new skill exists first.
5. Validate: cron expression parses, referenced skill exists.
6. Report what changed.
