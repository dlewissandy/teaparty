---
name: edit-scheduled-task
description: Modify an existing scheduled task entry — change the schedule, arguments, skill reference, or enabled state.
argument-hint: <task-name>
user-invocable: false
allowed-tools: Read, Glob, Grep, Write, Edit, Bash
---

# Edit Scheduled Task

Modify the scheduled task `$ARGUMENTS`.

## Steps

1. Locate the task entry. Check `~/.teaparty/teaparty.yaml` and `{project}/.teaparty/project.yaml`.
2. Read the current entry.
3. Clarify what needs to change. Read `schema.md` for field reference.
4. Apply the change with Edit — preserve all other scheduled entries.
5. If the `skill:` field is changing, confirm the new skill exists first.
6. Validate: cron expression parses, referenced skill exists.
7. Report what changed.
