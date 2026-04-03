# Hooks

Hooks in project and workgroup YAML are shorthand references for dashboard display. The authoritative source is always `.teaparty/management/settings.yaml`.

## Configuration

In `project.yaml`:

```yaml
hooks:
  - event: PreToolUse
    matcher: Bash
    handler: .teaparty/project/hooks/validate-worktree.sh
```

This is just enough for display and awareness. The actual hook implementation lives in `.teaparty/management/settings.yaml`.

## Updates

If the Configuration Team modifies hooks, it edits `.teaparty/management/settings.yaml` and updates the YAML reference to match. The YAML is a map; the settings.yaml is the source of truth.
