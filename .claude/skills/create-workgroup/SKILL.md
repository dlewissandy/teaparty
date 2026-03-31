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
5. Add a `workgroups:` entry to the appropriate `teaparty.yaml` or `project.yaml` using `EditScheduledTask` or by directly referencing the workgroup.
6. Validate: YAML parses, lead agent exists, all listed skills exist.
7. Report what was created.
