---
name: edit-project
description: Modify an existing project's configuration in project.yaml or update its registry entry in teaparty.yaml.
argument-hint: <project-name>
user-invocable: false
allowed-tools: Read, Glob, Grep, Write, Edit, Bash
---

# Edit Project

Modify the configuration for `$ARGUMENTS`.

## Steps

1. Read the current `{project}/.teaparty/project.yaml` to understand the existing configuration.
2. Read `~/.teaparty/teaparty.yaml` to see the registry entry.
3. Clarify what specifically needs to change. Read `schema.md` for the full field reference.
4. Apply the changes using the Edit tool — preserve unchanged fields.
5. If the project path moved, update the registry entry in `teaparty.yaml`.
6. Validate: YAML parses, lead agent exists, all referenced workgroups exist.
7. Report what changed.
