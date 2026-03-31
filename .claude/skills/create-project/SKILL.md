---
name: create-project
description: Register a new project in the TeaParty registry and create its .teaparty/project.yaml configuration.
argument-hint: <project-name> [--path <path>]
user-invocable: false
allowed-tools: Read, Glob, Grep, Bash
---

# Create Project

Register `$ARGUMENTS` as a new project in TeaParty.

## Steps

1. Read `~/.teaparty/teaparty.yaml` to understand the current registry.
2. Ask the human for any missing details: project path, description, lead agent, decider. Read `schema.md` for the full field reference.
3. Call `AddProject(name, path, description, lead, decider)` to register an existing directory, or `CreateProject(name, path, description, lead, decider)` to create a new directory with full scaffolding.
4. Both tools create `.teaparty.local/project.yaml` and add the registry entry atomically.
5. Validate the result. Read `checklist.md` for the validation checklist.
6. Report what was created: file paths and key fields set.
