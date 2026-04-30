"""PreToolUse hook: restrict file tools to the worktree.

Runs as a subprocess of Claude Code.  Reads hook input from stdin,
checks whether the target path is within the worktree (cwd), and
returns Claude Code's PreToolUse permission verdict.

Covers: Read, Edit, Write (file_path), Glob, Grep (path).

Output protocol — must match what Claude Code consumes for PreToolUse:

    {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "allow" | "deny",
            "permissionDecisionReason": "<message>"
        }
    }

The legacy ``{"allowed": <bool>, "reason": "..."}`` shape is no
longer honored by Claude Code: a deny in that shape was silently
treated as "no decision" and the tool ran anyway.  See issue #425
follow-up for the regression that surfaced this.

The ``allowed``/``reason`` keys are still emitted alongside the
canonical fields so existing tests and tooling that read the legacy
shape continue to work; Claude Code reads ``hookSpecificOutput`` and
ignores the legacy keys when both are present.
"""
from __future__ import annotations

import json
import os
import sys

# Tools that use 'file_path' for their target
_FILE_PATH_TOOLS = frozenset({'Read', 'Edit', 'Write'})
# Tools that use 'path' for their search directory
_PATH_TOOLS = frozenset({'Glob', 'Grep'})


def _allow() -> dict:
    return {
        'allowed': True,
        'hookSpecificOutput': {
            'hookEventName': 'PreToolUse',
            'permissionDecision': 'allow',
        },
    }


def _deny(reason: str) -> dict:
    return {
        'allowed': False,
        'reason': reason,
        'hookSpecificOutput': {
            'hookEventName': 'PreToolUse',
            'permissionDecision': 'deny',
            'permissionDecisionReason': reason,
        },
    }


def _check(tool_name: str, tool_input: dict) -> dict:
    # Extract the relevant path parameter
    if tool_name in _FILE_PATH_TOOLS:
        target = tool_input.get('file_path', '')
    elif tool_name in _PATH_TOOLS:
        target = tool_input.get('path', '')
    else:
        return _allow()

    if not target:
        return _allow()

    worktree = os.getcwd()

    # Relative paths resolve within worktree — always allowed
    if not os.path.isabs(target):
        return _allow()

    abs_target = os.path.normpath(target)
    worktree_norm = os.path.normpath(worktree)

    # Absolute path to own worktree — allow.  Earlier this branch
    # denied with a "use relative path" suggestion, but Claude Code
    # surfaces hook denials as user permission prompts rather than
    # returning the reason to the agent for retry.  Result: the agent
    # blocks on a prompt the user never sees, exits the turn with
    # "I'm blocked on write permission for X," and the dispatch tree
    # stalls.  The path is in-bounds (the check above proves it);
    # whether the agent uses absolute or relative addressing is a
    # stylistic preference, not a safety boundary.  Allowing the
    # write removes the friction without changing the safety model.
    if abs_target == worktree_norm or abs_target.startswith(worktree_norm + os.sep):
        return _allow()

    # Outside worktree entirely — this is the actual safety boundary.
    return _deny('You are restricted to files in your worktree')


def main() -> None:
    try:
        raw = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, OSError):
        # Fail-open on malformed input — a crash here would be invisible
        # to the operator (hook runs as a fire-and-forget subprocess).
        json.dump(_allow(), sys.stdout)
        return

    tool_name = raw.get('tool_name', '')
    tool_input = raw.get('tool_input', {})

    result = _check(tool_name, tool_input)
    json.dump(result, sys.stdout)


if __name__ == '__main__':
    main()
