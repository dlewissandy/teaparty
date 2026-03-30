# Hook Lifecycle Events

## Events

| Event | When it fires | Can block? |
|---|---|---|
| `PreToolUse` | Before any tool runs | Yes — exit 2 cancels the tool call |
| `PostToolUse` | After any tool completes | No — tool already ran |
| `Notification` | When Claude sends a notification | No |
| `Stop` | When Claude stops responding | No |

## Blocking behavior

Only `PreToolUse` hooks can block. To block a tool call, the handler must exit with code 2. Exit code 0 allows the tool to proceed. Any other exit code is treated as an error (logged, does not block).

`PostToolUse` hooks fire after the tool has already run. They cannot undo the tool's effect. Use them for side effects (formatting, logging, notifications) not for enforcement.

## Scope

| File | Scope |
|---|---|
| `.claude/settings.json` | Project-scoped, checked in, affects all team members |
| `.claude/settings.local.json` | Local-only, not checked in, affects only your session |

Choose local for personal workflow hooks; choose project for team-wide enforcement.

## Common patterns

**Block dangerous bash commands (PreToolUse, Bash):**
```json
{ "type": "command", "command": ".claude/hooks/check-bash-safety.sh" }
```

**Auto-format after file edits (PostToolUse, Edit|Write):**
```json
{ "type": "command", "command": ".claude/hooks/auto-format.sh" }
```

**Log all tool calls (PostToolUse, no matcher):**
```json
{ "type": "command", "command": ".claude/hooks/log-tool-use.sh" }
```
