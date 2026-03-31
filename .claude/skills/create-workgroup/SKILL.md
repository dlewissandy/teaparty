---
name: create-workgroup
description: Create a new workgroup definition YAML file with agent roster, skills catalog, norms, and delegation rules.
argument-hint: <workgroup-name> [--scope shared|project] [--project <project-name>]
user-invocable: false
allowed-tools: Read, Glob, Grep, Bash
---

# Create Workgroup

Create a workgroup definition for `$ARGUMENTS`.

## Steps

1. Determine scope: shared (org-level) or project-scoped.
2. Ask for the workgroup's purpose, lead agent, and specialists. Read `schema.md` for the YAML structure.
3. Ask which skills the workgroup makes available (catalog). Note: this is not access control — per-agent access is controlled by the `skills:` allowlist in each agent definition.
4. Call `CreateWorkgroup(name, description, lead, agents_yaml, skills, norms_yaml)` with the collected fields.
5. The `CreateWorkgroup` tool writes the YAML file. If the workgroup must also appear in a `teaparty.yaml` or `project.yaml` registry, use `EditWorkgroup` or confirm the registration path with the human.
6. Validate: YAML parses, lead agent exists, all listed skills exist.
7. Report what was created.
