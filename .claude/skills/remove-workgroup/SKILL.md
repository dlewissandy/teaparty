---
name: remove-workgroup
description: Remove a workgroup definition and its registration entry. Does not delete agent definitions used by the workgroup.
argument-hint: <workgroup-name>
user-invocable: false
allowed-tools: Read, Glob, Grep, Bash
---

# Remove Workgroup

Remove the workgroup `$ARGUMENTS`.

## Steps

1. Locate the workgroup YAML in `~/.teaparty/workgroups/` or `{project}/.teaparty.local/workgroups/`.
2. Read the safety checklist. Read `checklist.md`.
3. Confirm with the human: removing a workgroup deregisters it but does not delete agent definitions.
4. Call `RemoveWorkgroup(name)`. The tool removes the workgroup YAML file.
5. Remove the `workgroups:` entry from the parent `teaparty.yaml` or `project.yaml`.
6. Report what was removed.
