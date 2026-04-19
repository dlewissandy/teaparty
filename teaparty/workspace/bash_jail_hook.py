"""PreToolUse hook: sandbox Bash commands to the worktree.

Runs as a subprocess of Claude Code.  Reads hook input from stdin,
inspects the Bash command, and denies commands that:

  1. Reference system paths  (/etc/, /var/, /usr/, /root/, /home/, ...)
  2. Reference $HOME          (~/...)
  3. Contain absolute paths outside the current worktree (cwd)
  4. Write to .git/ or .claude/  (reads are allowed)

This hook is defense-in-depth, not a sound sandbox.  A determined agent
can bypass via environment expansion, subshells, or indirection.  It
catches accidental and obvious harmful shapes.  Pair with a narrow Bash
allowlist in the scope ``settings.yaml`` for primary enforcement.

Complementary to ``worktree_hook.py``, which covers Read/Edit/Write/
Glob/Grep; this one covers the Bash escape hatch.
"""
from __future__ import annotations

import json
import os
import re
import shlex
import sys


# Prefixes that are never legitimate for agent code to touch.  System
# and other-user paths.  We stop at a conservative set — the sandbox
# is "stay inside the worktree," not "list every possible path."
_FORBIDDEN_SUBSTRINGS = (
    '/etc/', '/var/', '/usr/', '/bin/', '/sbin/',
    '/root/', '/home/', '/boot/', '/sys/', '/proc/',
    '/opt/', '/private/', '/Library/',
)

# Repo-internal directories — reads allowed, writes never.
_INTERNAL_DIRS = ('.git', '.claude')

# Commands whose first token denotes a write operation.  Used to reject
# writes targeting repo internals.
_WRITE_COMMANDS = frozenset({
    'rm', 'mv', 'cp', 'chmod', 'chown', 'touch', 'mkdir', 'rmdir',
    'ln', 'tee',
})


def _deny(reason: str) -> dict:
    return {'allowed': False, 'reason': reason}


def _allow() -> dict:
    return {'allowed': True}


def _check_bash(command: str, worktree: str) -> dict:
    if not command:
        return _allow()

    worktree_norm = os.path.normpath(worktree)

    # Mask worktree-absolute paths before the substring scan.  The worktree
    # path itself may legitimately contain a "forbidden" substring (on macOS
    # tmp worktrees sit under ``/var/folders/...``); stripping
    # ``{worktree}/...`` spans from the command lets those through while
    # still catching genuine outside-the-sandbox references.
    scan_text = re.sub(
        re.escape(worktree_norm) + r'\S*', '', command,
    )

    # 1. System path substrings.  Fast reject before tokenisation so that
    #    even commands wrapped in awkward quoting do not slip through.
    for needle in _FORBIDDEN_SUBSTRINGS:
        if needle in scan_text:
            return _deny(
                f'Command references system path "{needle.rstrip("/")}"; '
                f'agent is sandboxed to the worktree.'
            )

    # 2. $HOME / ~/ expansion.  Match ~/ at the start of the command or
    #    after whitespace/quotes/equals — cheap string-level reject.
    if re.search(r'(^|[\s=:"\'])~(/|$)', command):
        return _deny(
            'Command references $HOME (~/); agent is sandboxed to the worktree.'
        )

    # 3. Absolute-path tokens outside the worktree.
    try:
        tokens = shlex.split(command, posix=True)
    except ValueError:
        # Unparseable (unbalanced quotes, etc.).  Fail open on tokenisation
        # so that legitimate complex shell constructs are not blanket-denied;
        # the substring checks above already catch the obvious threats.
        tokens = []

    for tok in tokens:
        if not tok.startswith('/'):
            continue
        norm = os.path.normpath(tok)
        if norm == worktree_norm or norm.startswith(worktree_norm + os.sep):
            continue
        return _deny(
            f'Absolute path "{tok}" is outside the worktree ({worktree_norm}).'
        )

    # 4. Writes to repo internals (.git / .claude).  We reject both the
    #    "first-token is a write verb, argument names an internal" shape
    #    and output-redirection into an internal path.
    if tokens and tokens[0] in _WRITE_COMMANDS:
        for tok in tokens[1:]:
            stripped = tok
            while stripped.startswith('./'):
                stripped = stripped[2:]
            for internal in _INTERNAL_DIRS:
                if stripped == internal or stripped.startswith(internal + '/'):
                    return _deny(
                        f'{tokens[0]} targets {internal}/; repo internals '
                        f'are not writable by agents.'
                    )

    for internal in _INTERNAL_DIRS:
        # Match `> .git`, `>> .git`, `> ./.git`, `>./.git/...`, etc.
        pattern = r'>+\s*(?:\./)?' + re.escape(internal) + r'(/|$|\s)'
        if re.search(pattern, command):
            return _deny(
                f'Output redirection into {internal}/; repo internals '
                f'are not writable by agents.'
            )

    return _allow()


def main() -> None:
    try:
        raw = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, OSError):
        # Malformed hook input — fail open (transport bug should not block
        # agent work).  The substring/token checks would have nothing to
        # examine anyway.
        json.dump({'allowed': True}, sys.stdout)
        return

    if raw.get('tool_name') != 'Bash':
        json.dump({'allowed': True}, sys.stdout)
        return

    command = raw.get('tool_input', {}).get('command', '') or ''
    result = _check_bash(command, os.getcwd())
    json.dump(result, sys.stdout)


if __name__ == '__main__':
    main()
