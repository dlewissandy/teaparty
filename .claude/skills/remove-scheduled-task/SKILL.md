---
name: remove-scheduled-task
description: Remove a scheduled task entry from teaparty.yaml or project.yaml.
argument-hint: <task-name>
user-invocable: false
allowed-tools: Read, Glob, Grep, Write, Edit, Bash
---

# Remove Scheduled Task

Remove the scheduled task `$ARGUMENTS`.

## Steps

1. Locate the task entry in `~/.teaparty/teaparty.yaml` or `{project}/.teaparty/project.yaml`.
2. Read `checklist.md` for safety checks.
3. Confirm with the human: show the entry that will be removed.
4. Remove the entry from the `scheduled:` list.
5. Validate the resulting YAML parses correctly.
6. Report what was removed.
