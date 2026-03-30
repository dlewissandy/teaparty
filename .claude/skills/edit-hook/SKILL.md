---
name: edit-hook
description: Modify an existing hook in .claude/settings.json — change the matcher, handler command, or handler type.
argument-hint: <hook-description>
user-invocable: false
allowed-tools: Read, Glob, Grep, Write, Edit, Bash
---

# Edit Hook

Modify the hook for `$ARGUMENTS`.

## Steps

1. Read `.claude/settings.json` (and `.claude/settings.local.json` if local hooks are in scope).
2. Locate the hook entry by event and matcher.
3. Clarify what needs to change. Read `schema.md` for field reference.
4. Apply the change with Edit — preserve all other hook entries.
5. Validate: event name is valid, matcher parses, handler type is recognized.
6. Report what changed.
