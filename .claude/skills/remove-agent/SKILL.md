---
name: remove-agent
description: Remove an agent definition from .claude/agents/ and clean up any workgroup roster references.
argument-hint: <agent-name>
user-invocable: false
allowed-tools: Read, Glob, Grep, Write, Edit, Bash
---

# Remove Agent

Remove the agent definition for `$ARGUMENTS`.

## Steps

1. Read the agent definition to understand its role and what references it.
2. Read `checklist.md` for safety checks.
3. Check all workgroup YAML files for roster entries that reference this agent.
4. Confirm with the human: list what will be removed and what will need updating.
5. Delete `.claude/agents/{name}.md`.
6. Remove roster entries from any workgroup YAMLs that listed this agent.
7. Report what was deleted and what was updated.
