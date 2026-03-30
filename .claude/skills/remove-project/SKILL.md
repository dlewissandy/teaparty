---
name: remove-project
description: Remove a project from the TeaParty registry. Does not delete the project directory — only removes the registration entry.
argument-hint: <project-name>
user-invocable: false
allowed-tools: Read, Glob, Grep, Write, Edit, Bash
---

# Remove Project

Remove `$ARGUMENTS` from the TeaParty registry.

## Steps

1. Read `~/.teaparty/teaparty.yaml` to locate the registry entry.
2. Read the safety checklist before proceeding. Read `checklist.md`.
3. Confirm with the human: removing a project from the registry does not delete files, but active sessions pointing to this project will lose their team context.
4. Remove the `teams:` entry from `teaparty.yaml`.
5. Report what was removed and note that the project directory and `.teaparty/project.yaml` are untouched.
