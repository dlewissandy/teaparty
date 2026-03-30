---
name: create-project
description: Register a new project in the TeaParty registry and create its .teaparty/project.yaml configuration.
argument-hint: <project-name> [--path <path>]
user-invocable: false
allowed-tools: Read, Glob, Grep, Write, Edit, Bash
---

# Create Project

Register `$ARGUMENTS` as a new project in TeaParty.

## Steps

1. Read `~/.teaparty/teaparty.yaml` to understand the current registry.
2. Ask the human for any missing details: project path, description, lead agent, decider. Read `schema.md` for the full field reference.
3. Create `{project}/.teaparty/project.yaml` with the project's configuration.
4. Add a `teams:` entry in `~/.teaparty/teaparty.yaml` pointing to the new project path.
5. Validate the result. Read `checklist.md` for the validation checklist.
6. Report what was created: file paths and key fields set.
