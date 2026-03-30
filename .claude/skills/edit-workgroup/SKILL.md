---
name: edit-workgroup
description: Modify an existing workgroup definition — add or remove agents, update skills catalog, change norms or delegation rules.
argument-hint: <workgroup-name>
user-invocable: false
allowed-tools: Read, Glob, Grep, Write, Edit, Bash
---

# Edit Workgroup

Modify the workgroup definition for `$ARGUMENTS`.

## Steps

1. Locate the workgroup YAML file. Check `~/.teaparty/workgroups/` and `{project}/.teaparty/workgroups/`.
2. Read the current definition.
3. Clarify what needs to change. Read `schema.md` for field reference.
4. Apply changes with Edit — preserve unchanged fields.
5. Validate: YAML parses, lead agent exists, all listed skills exist.
6. Report what changed.
