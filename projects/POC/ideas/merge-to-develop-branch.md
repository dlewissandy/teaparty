# Idea: Merge session worktrees to a develop branch, not main

## Problem

Session worktrees currently squash-merge into `main`. This means every completed session lands directly on the primary branch. If a session produces broken or incomplete work, `main` is degraded. There is no buffer between "agent finished" and "code is runnable."

## Desired behaviour

- Sessions merge into a `develop` branch instead of `main`.
- `main` remains the "always runnable" branch — only promoted to from `develop` after verification.
- The TUI should reflect this: session merge targets `develop`, and promotion from `develop` to `main` is a separate, deliberate action.

## Scope

This affects:
- The merge step in `orchestrator/session.py` (both fresh sessions and resumed sessions)
- The merge step in `orchestrator/merge.py` (`squash_merge` target)
- The dispatch merge path in `orchestrator/actors.py` (`DispatchRunner`)
- The TUI's display of branch state and any merge-related UI
- Worktree creation (worktrees are currently branched from HEAD of the repo; may need to branch from `develop` instead)
