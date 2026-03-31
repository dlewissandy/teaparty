---
name: edit-project
description: Modify an existing project's configuration in project.yaml or update its registry entry in teaparty.yaml.
argument-hint: <project-name>
user-invocable: false
allowed-tools: Read, Glob, Grep, Bash
---

# Edit Project

Modify the configuration for `$ARGUMENTS`.

## Steps

1. Read the current `{project}/.teaparty.local/project.yaml` to understand the existing configuration.
2. Read `~/.teaparty/teaparty.yaml` to see the registry entry.
3. Clarify what specifically needs to change. Read `schema.md` for the full field reference.
4. To update `project.yaml` fields, call `ScaffoldProjectYaml(project_path, name, description, lead, decider)`. This always overwrites with the provided values.
5. Validate: YAML parses, lead agent exists, all referenced workgroups exist.
6. Report what changed.
