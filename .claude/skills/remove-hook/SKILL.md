---
name: remove-hook
description: Remove a hook entry from .claude/settings.json or .claude/settings.local.json.
argument-hint: <hook-description>
user-invocable: false
allowed-tools: Read, Glob, Grep, Write, Edit, Bash
---

# Remove Hook

Remove the hook for `$ARGUMENTS`.

## Steps

1. Read `.claude/settings.json` to locate the hook entry by event and matcher.
2. Read `checklist.md` for safety checks.
3. Confirm with the human: describe which hook will be removed (event, matcher, handler).
4. Remove the handler entry from the appropriate `hooks` array.
5. If the matcher group's `hooks` array is now empty, remove the entire matcher group.
6. Validate the resulting JSON parses correctly.
7. Report what was removed.
