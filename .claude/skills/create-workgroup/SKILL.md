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

1. Determine scope: shared (org-level, goes in `~/.teaparty/workgroups/`) or project-scoped (`{project}/.teaparty/workgroups/`).
2. Ask for the workgroup's purpose, lead agent, and specialists. Read `schema.md` for the YAML structure.
3. Ask which skills the workgroup makes available (catalog). Note: this is not access control — per-agent access is controlled by the `skills:` allowlist in each agent definition.
4. Write the workgroup YAML file.
5. Add a `workgroups:` entry to the appropriate `teaparty.yaml` or `project.yaml`.
6. Validate. Read `checklist.md`.
7. Report the file path and summarize the roster and skills catalog.
