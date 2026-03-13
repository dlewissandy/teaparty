# Idea: Merge conflict resolution through human proxy with escalation

## Problem

The orchestrator currently resolves merge conflicts by accepting "theirs" unconditionally. This is a silent, lossy operation: work from the target branch is overwritten without review. In cases where both sides made meaningful changes to the same region — which is exactly when conflicts arise — the correct resolution is not always one side or the other. It may require combining both, choosing selectively, or recognising that the conflict signals a coordination failure that needs human attention.

Merge conflicts are decisions. The current approach treats them as infrastructure plumbing.

## Where this happens

- `orchestrator/merge.py` — `squash_merge()` resolves conflicts during session-to-main merges.
- `orchestrator/actors.py` — `DispatchRunner` merges dispatch worktrees back into the session worktree after subteam completion.
- Any future multi-agent scenario where two branches touch the same file regions concurrently.

## Why "theirs" is wrong as a default

1. **Dispatch merges lose session-level edits.** If the session worktree has changes to a file that a dispatch subteam also edited, the dispatch's version wins and the session-level edits vanish silently.
2. **Concurrent dispatches overwrite each other.** When two dispatch teams edit overlapping regions, the second merge overwrites the first team's work.
3. **No audit trail.** The human never learns that a conflict occurred or that content was discarded. The merge log shows success.

## Desired behaviour

Merge conflicts should flow through the same proxy-with-escalation pattern as other CfA decision points:

1. **Detect** the conflict (files, regions, both versions).
2. **Consult the human proxy.** The proxy sees the conflict context — which files, what both sides wrote — and decides whether it can resolve automatically or must escalate.
3. **Auto-resolve** if the proxy is confident (e.g., the conflict is in a generated file, or one side is clearly a superset of the other).
4. **Escalate to the human** if the proxy is not confident, presenting both versions and the surrounding context so the human can make an informed choice.
5. **Record the outcome** so the proxy learns the human's merge preferences over time, just as it learns approval preferences.

## What this is not

This is not a general-purpose merge tool or a diff viewer. It is the application of the existing proxy escalation pattern to a decision point that currently has no oversight.
