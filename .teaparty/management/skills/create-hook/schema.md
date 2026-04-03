# Hook Configuration Schema

## settings.json structure

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash",
        "hooks": [
          {
            "type": "command",
            "command": ".claude/hooks/pre-bash-check.sh",
            "statusMessage": "Checking..."
          }
        ]
      }
    ],
    "PostToolUse": [
      {
        "matcher": "Edit|Write",
        "hooks": [
          {
            "type": "command",
            "command": ".claude/hooks/auto-format.sh"
          }
        ]
      }
    ]
  }
}
```

## Handler types

| Type | When to use | Blocking? |
|---|---|---|
| `command` | Shell script; exit 0 proceeds, exit 2 blocks | Yes (PreToolUse only) |
| `agent` | Claude agent for judgment calls | Yes (PreToolUse only) |
| `prompt` | Quick inline prompt check | Yes (PreToolUse only) |
| `http` | External service webhook | No |

## Required fields per handler

**command:**
```json
{ "type": "command", "command": "path/to/script.sh", "statusMessage": "Optional..." }
```

**agent:**
```json
{ "type": "agent", "agentName": "agent-name" }
```

**prompt:**
```json
{ "type": "prompt", "prompt": "Should this proceed? Reply BLOCK or PROCEED." }
```

**http:**
```json
{ "type": "http", "url": "https://...", "method": "POST" }
```

## Matcher syntax

- Tool name: `"Bash"`, `"Write"`, `"Edit"`
- Multiple tools: `"Edit|Write"` (pipe-separated)
- All tools: omit matcher field
