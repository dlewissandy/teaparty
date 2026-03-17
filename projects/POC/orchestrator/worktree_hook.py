"""PreToolUse hook: restrict file tools to the worktree.

Runs as a subprocess of Claude Code.  Reads hook input from stdin,
checks whether the target path is within the worktree (cwd),
and returns allow/deny JSON.

Covers: Read, Edit, Write (file_path), Glob, Grep (path).

Messages are crafted to guide the agent without leaking directory structure:
- Outside worktree:  "You are restricted to files in your worktree"
- Absolute path to own worktree:  "Use relative path '<rel>' instead"
"""
from __future__ import annotations

import json
import os
import sys

# Tools that use 'file_path' for their target
_FILE_PATH_TOOLS = frozenset({'Read', 'Edit', 'Write'})
# Tools that use 'path' for their search directory
_PATH_TOOLS = frozenset({'Glob', 'Grep'})


def _check(tool_name: str, tool_input: dict) -> dict:
    # Extract the relevant path parameter
    if tool_name in _FILE_PATH_TOOLS:
        target = tool_input.get('file_path', '')
    elif tool_name in _PATH_TOOLS:
        target = tool_input.get('path', '')
    else:
        return {'allowed': True}

    if not target:
        return {'allowed': True}

    worktree = os.getcwd()

    # Relative paths resolve within worktree — always allowed
    if not os.path.isabs(target):
        return {'allowed': True}

    abs_target = os.path.normpath(target)
    worktree_norm = os.path.normpath(worktree)

    # Check if the absolute path is within the worktree
    if abs_target == worktree_norm or abs_target.startswith(worktree_norm + os.sep):
        # Absolute path to own worktree — suggest relative path
        rel = os.path.relpath(abs_target, worktree_norm)
        return {
            'allowed': False,
            'reason': f'Use relative path "{rel}" instead',
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
