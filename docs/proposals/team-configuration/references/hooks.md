# Hooks

Hooks in project and workgroup YAML are shorthand references for dashboard display. The authoritative source is always `.claude/settings.json`.

## Configuration

In `project.yaml`:

```yaml
hooks:
  - event: PreToolUse
    matcher: Bash
    handler: .claude/hooks/validate-worktree.sh
```

This is just enough for display and awareness. The actual hook implementation lives in `.claude/settings.json`.

## Updates

If the Configuration Team modifies hooks, it edits `.claude/settings.json` and updates the YAML reference to match. The YAML is a map; the settings.json is the source of truth.
