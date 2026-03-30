---
name: create-hook
description: Add a new hook to .claude/settings.json or .claude/settings.local.json — choose the lifecycle event, matcher, and handler type.
argument-hint: <hook-description>
user-invocable: false
allowed-tools: Read, Glob, Grep, Write, Edit, Bash
---

# Create Hook

Add a hook for `$ARGUMENTS`.

## Steps

1. Read the current `.claude/settings.json` to see existing hooks. If local-only, read `.claude/settings.local.json`.
2. Ask clarifying questions if needed: which lifecycle event, what should the hook match, what should the handler do?
3. Read `event-reference.md` to confirm the event name and understand blocking behavior.
4. Read `schema.md` for the full hook JSON structure.
5. Add the hook entry under the appropriate event key. Use Edit to add to existing hooks — never overwrite the file.
6. If the handler is a `command` type, create the handler script if it doesn't exist.
7. Validate: event name is valid, matcher parses, handler type is recognized, referenced scripts exist.
8. Report the hook added: event, matcher, handler type, and whether it is blocking.
