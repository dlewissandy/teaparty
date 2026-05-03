# Hook Edit Reference

Read `../create-hook/schema.md` for the full hook structure.
Read `../create-hook/event-reference.md` for event names and blocking behavior.

## Locating a hook

Hooks are nested: `hooks → {Event} → [{matcher: ..., hooks: [...]}]`.

To find the right entry:
1. Identify the event (`PreToolUse`, `PostToolUse`, etc.)
2. Find the matcher group (`"matcher": "Bash"`)
3. Find the handler within that group's `hooks` array

## Common edits

**Change the handler script path:**
```json
"command": ".claude/hooks/new-script.sh"
```

**Narrow the matcher:**
```json
"matcher": "Write"   // was "Edit|Write", now only Write
```

**Change handler type (command → agent):**
```json
{ "type": "agent", "agentName": "my-reviewer" }
```

**Move from project to local scope:**
Remove from `.claude/settings.json`, add to `.claude/settings.local.json`.
