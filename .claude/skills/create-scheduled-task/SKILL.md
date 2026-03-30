---
name: create-scheduled-task
description: Add a new scheduled task entry to teaparty.yaml or project.yaml and create the /schedule trigger. The referenced skill must exist before the task is created.
argument-hint: <task-name>
user-invocable: false
allowed-tools: Read, Glob, Grep, Write, Edit, Bash
---

# Create Scheduled Task

Create a scheduled task named `$ARGUMENTS`.

## Steps

1. Confirm the skill exists. A scheduled task must reference an existing skill. If it does not exist, stop and request the Skills Specialist create it first.
2. Ask for the schedule (cron expression or natural language like "every night at 2am") and any arguments to pass to the skill.
3. Determine scope: management-level task (`~/.teaparty/teaparty.yaml`) or project-scoped (`{project}/.teaparty/project.yaml`).
4. Read `schema.md` for the `scheduled:` entry format and cron expression syntax.
5. Add the entry to the appropriate YAML file under `scheduled:`.
6. Validate: cron expression parses, referenced skill exists, task name is unique.
7. Report: task name, schedule, skill, and file updated.
