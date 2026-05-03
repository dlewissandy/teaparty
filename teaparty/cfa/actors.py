"""Actor-side helpers — the surviving surface after engine unification.

The CfA engine used to wrap each agent turn in ``run_phase`` /
``_interpret_output`` / ``ActorContext`` / ``ActorResult``.  Issue
#422 unified both tiers onto ``run_agent_loop`` (in
``teaparty/messaging/child_dispatch.py``); the engine now calls
``runners.launcher.launch`` directly through the loop and reads the
skill's outcome by inspecting ``./.phase-outcome.json`` after each
turn.

What's left here is the launch-prep + post-launch helpers that the
engine still needs:

* ``InputProvider`` — Protocol type for the human-input async callable
  threaded through ``Session`` and ``Orchestrator``.
* ``_stage_jail_hook`` / ``_check_jail_hook`` — copy + validate the
  worktree jail hook the engine installs in every launch's settings.
* ``_relocate_plan_file`` — copy a freshly-written plan from
  ``~/.claude/plans/`` into the session worktree (claude stashes
  plans there when ``--permission-mode plan`` is set).
* ``_relocate_misplaced_artifact`` — move agent-written artifacts
  out of arbitrary absolute paths into the session worktree by
  parsing the stream JSONL for the actual write target.
"""
from __future__ import annotations

import json
import logging as _logging
import os
import shutil
from pathlib import Path
from typing import Protocol

from teaparty.messaging.bus import InputRequest


# ── Protocols ────────────────────────────────────────────────────────────────

class InputProvider(Protocol):
    """Async callable that returns human input text."""
    async def __call__(self, request: InputRequest) -> str: ...


_actor_log = _logging.getLogger('teaparty.cfa.actors')


# ── Worktree jail hook (Issue #150) ─────────────────────────────────────────

def _stage_jail_hook(session_worktree: str, hook_script: str) -> None:
    """Copy the CfA jail hook script into the worktree at *hook_script*.

    The hook script lives in the teaparty package at
    ``teaparty/workspace/worktree_hook.py``.  It is copied into the
    worktree so the PreToolUse ``command`` (which references the path
    relative to cwd) resolves without requiring the external project's
    git tree to contain teaparty source.

    Idempotent — overwrites any existing copy.
    """
    src = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        'workspace', 'worktree_hook.py',
    )
    if not os.path.isfile(src):
        raise RuntimeError(
            f'Jail hook source missing from teaparty package: {src}. '
            f'Install is broken.'
        )
    dst = os.path.join(session_worktree, hook_script)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.copy2(src, dst)


def _check_jail_hook(session_worktree: str, hook_script: str) -> None:
    """Raise RuntimeError if the jail hook script is absent from the worktree.

    The hook runs as a subprocess relative to the worktree CWD. If the file is
    missing the subprocess fails silently and agents run without restriction.
    Raising here makes the failure loud and immediate rather than invisible.
    """
    hook_path = os.path.join(session_worktree, hook_script)
    if not os.path.isfile(hook_path):
        raise RuntimeError(
            f'Jail hook script missing: {hook_path}. '
            f'Cannot launch agent without filesystem restriction. '
            f'Ensure {hook_script} exists in the worktree checkout.'
        )


# ── Plan relocation ──────────────────────────────────────────────────────────

def _relocate_plan_file(target_path: str, start_time: float) -> bool:
    """Detect a newly created plan in ~/.claude/plans/ and copy it to target_path.

    Claude stores plans in ~/.claude/plans/ when using --permission-mode plan.
    The shell version (plan-execute.sh) snapshots the directory before/after and
    moves the newest file. This is the Python equivalent.

    Returns True if a plan was successfully relocated.
    """
    plans_dir = Path.home() / '.claude' / 'plans'
    if not plans_dir.is_dir():
        return False

    # Find plan files created after start_time (newest first)
    candidates = []
    for f in plans_dir.iterdir():
        if not f.is_file() or f.suffix != '.md':
            continue
        try:
            mtime = f.stat().st_mtime
        except OSError:
            continue
        if mtime >= start_time:
            candidates.append((mtime, f))

    if not candidates:
        return False

    # Pick the newest
    candidates.sort(reverse=True)
    _, best = candidates[0]

    try:
        shutil.copy2(str(best), target_path)
        return True
    except OSError:
        return False


# ── Artifact relocation (Issue #157) ────────────────────────────────────────

def _relocate_misplaced_artifact(
    target_dir: str, stream_file: str, artifact_name: str,
) -> bool:
    """Move an artifact to target_dir so it exists in exactly one location.

    Parses the stream JSONL to find the actual path the agent used in its
    Write or Edit tool calls.  If the file was written elsewhere, moves it
    to target_dir/<artifact_name>.

    Always refreshes the target — after corrections at approval gates, the
    agent re-edits the artifact and the existing copy becomes stale.

    Returns True if a file was moved.
    """
    # Find where the agent actually wrote/edited the artifact
    actual_path = _find_artifact_path_in_stream(stream_file, artifact_name)
    if not actual_path:
        return False

    if not os.path.isfile(actual_path):
        return False  # agent wrote it but file is gone (shouldn't happen)

    expected = os.path.join(target_dir, artifact_name)

    # Skip if the source IS the target (agent wrote directly to the right place)
    if os.path.abspath(actual_path) == os.path.abspath(expected):
        return False

    try:
        shutil.move(actual_path, expected)
        _actor_log.info(
            'Moved artifact to worktree: %s → %s', actual_path, expected,
        )
        return True
    except OSError:
        _actor_log.warning(
            'Failed to move artifact: %s → %s', actual_path, expected,
            exc_info=True,
        )
        return False


def _find_artifact_path_in_stream(stream_file: str, artifact_name: str) -> str:
    """Scan a stream JSONL file for the last Write or Edit tool call that
    touched artifact_name.

    Returns the absolute file_path from the tool input, or '' if not found.
    Detects both Write and Edit calls so that post-correction edits are
    found.
    """
    if not stream_file or not os.path.isfile(stream_file):
        return ''

    last_path = ''
    try:
        with open(stream_file) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    evt = json.loads(line)
                except ValueError:
                    continue
                for block in evt.get('message', {}).get('content', []):
                    if not isinstance(block, dict):
                        continue
                    if block.get('name') not in ('Write', 'Edit'):
                        continue
                    file_path = block.get('input', {}).get('file_path', '')
                    if file_path and os.path.basename(file_path) == artifact_name:
                        last_path = file_path
    except OSError:
        pass

    return last_path
