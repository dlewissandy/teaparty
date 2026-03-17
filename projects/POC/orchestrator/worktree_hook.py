"""PreToolUse hook: restrict Read/Edit/Write to the worktree.

Runs as a subprocess of Claude Code.  Reads hook input from stdin,
checks whether the target file_path is within the worktree (cwd),
and returns allow/deny JSON.

Messages are crafted to guide the agent without leaking directory structure:
- Outside worktree:  "You are restricted to files in your worktree"
- Absolute path to own worktree:  "Use relative path '<rel>' to <verb> this file"
"""
from __future__ import annotations

import json
import os
import sys


def _check(tool_name: str, tool_input: dict) -> dict:
    file_path = tool_input.get('file_path', '')
    if not file_path:
        return {'allowed': True}

    worktree = os.getcwd()

    # Resolve the target path to absolute
    if os.path.isabs(file_path):
        abs_target = os.path.normpath(file_path)
    else:
        # Relative path — resolves within worktree, always allowed
        return {'allowed': True}

    worktree_norm = os.path.normpath(worktree)

    # Check if the absolute path is within the worktree
    if abs_target == worktree_norm or abs_target.startswith(worktree_norm + os.sep):
        # Absolute path to own worktree — suggest relative path
        rel = os.path.relpath(abs_target, worktree_norm)
        verb = 'read' if tool_name == 'Read' else 'write'
        return {
            'allowed': False,
            'reason': f'Use relative path "{rel}" to {verb} this file',
        }

    # Outside worktree entirely
    return {
        'allowed': False,
        'reason': 'You are restricted to files in your worktree',
    }


def main() -> None:
    try:
        raw = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, OSError):
        json.dump({'allowed': True}, sys.stdout)
        return

    tool_name = raw.get('tool_name', '')
    tool_input = raw.get('tool_input', {})

    result = _check(tool_name, tool_input)
    json.dump(result, sys.stdout)


if __name__ == '__main__':
    main()
