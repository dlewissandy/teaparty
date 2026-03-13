# BUG: Finder and VSCode buttons in TUI drilldown do nothing

**Discovered:** 2026-03-12
**Severity:** Medium — usability; workaround is manual navigation
**Component:** `tui/screens/drilldown.py`, `tui/screens/dispatch_drilldown.py`

## Observed behaviour

In the TUI's session drilldown screen, pressing F1 (Finder) or F2 (VSCode) produces no visible effect. Neither Finder nor VSCode opens. No error message is displayed. The buttons appear active in the footer bar (not grayed out), suggesting the TUI believes it has a valid worktree path, yet nothing happens when pressed.

The expected behaviour is that F1 opens the session's worktree directory in Finder, and F2 opens it in VSCode.

## Reproduction

1. Start a session via the TUI that creates a worktree (e.g., any project with `.worktrees/` directories).
2. Navigate to the session drilldown screen.
3. Press F1 or F2.
4. Nothing happens. No Finder window, no VSCode window, no error.

The worktree directory exists on disk — for example, `projects/hierarchical-memory-paper/.worktrees/session-221105--i-have-a-collection-of-ideas-t/` is present and accessible.

## Affected screens

- `DrilldownScreen` (`tui/screens/drilldown.py`) — session-level F1/F2
- `DispatchDrilldownScreen` (`tui/screens/dispatch_drilldown.py`) — dispatch-level F1/F2

Both screens have the same symptom. The handlers call `_session_worktree()` / `_dispatch_worktree()` to resolve the path, and if the path is `None`, they silently return without feedback. The `check_action()` method that controls button graying also calls the same path resolution, so the grayed-out state and the handler share the same failure mode — if path resolution sometimes succeeds in `check_action` but fails in the handler (or vice versa), the button can appear enabled but do nothing, or appear disabled when it should work.

## Additional context

The worktree naming convention on disk is `session-{short_id}--{slug}` (e.g., `session-221105--i-have-a-collection-of-ideas-t`), where `short_id` is the last 6 characters of the full session ID. The TUI's worktree path resolution has a two-step lookup: first checking an explicit `worktree_path` field on the session object, then falling back to a conventional path pattern. If neither resolves to an existing directory, the buttons silently do nothing.
