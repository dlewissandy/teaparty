"""Issue #425 follow-up: PreToolUse hooks must use the canonical
``hookSpecificOutput`` protocol so Claude Code actually honors deny
verdicts.

Discovered while testing the proxy: the worktree-jail hook returned
the legacy ``{"allowed": false, "reason": "..."}`` shape, which is
no longer recognized by current Claude Code versions.  A deny in
that shape was silently treated as "no decision" and the tool ran
anyway — leaving the proxy able to read absolute paths outside its
cwd.

Both ``worktree_hook.py`` and ``bash_jail_hook.py`` must now emit:

    {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "allow" | "deny",
            "permissionDecisionReason": "..."   # for deny
        }
    }

These tests pin the protocol shape so a future drift back to the
legacy-only format fails loudly.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

_REPO_ROOT = str(Path(__file__).parent.parent.parent)
_WORKTREE_HOOK = os.path.join(
    _REPO_ROOT, 'teaparty', 'workspace', 'worktree_hook.py',
)
_BASH_HOOK = os.path.join(
    _REPO_ROOT, 'teaparty', 'workspace', 'bash_jail_hook.py',
)


def _run(hook_path: str, payload: dict, cwd: str) -> dict:
    result = subprocess.run(
        [sys.executable, hook_path],
        input=json.dumps(payload).encode(),
        capture_output=True,
        cwd=cwd,
    )
    if result.returncode != 0:
        raise AssertionError(
            f'hook exited {result.returncode}: {result.stderr.decode()}',
        )
    return json.loads(result.stdout.decode())


class WorktreeHookProtocolTest(unittest.TestCase):
    """worktree_hook.py emits the canonical PreToolUse protocol."""

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix='hook-proto-')
        self.cwd = os.path.realpath(self._tmp)

    def tearDown(self) -> None:
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_deny_outside_cwd_uses_hookSpecificOutput(self) -> None:
        result = _run(
            _WORKTREE_HOOK,
            {'tool_name': 'Read', 'tool_input': {'file_path': '/etc/passwd'}},
            cwd=self.cwd,
        )
        # Canonical fields — what Claude Code reads.
        self.assertIn(
            'hookSpecificOutput', result,
            'PreToolUse deny must be wrapped in `hookSpecificOutput`; '
            'the legacy shape is ignored by current Claude Code (#425 '
            'follow-up).  Got: ' + json.dumps(result),
        )
        hso = result['hookSpecificOutput']
        self.assertEqual(
            hso.get('hookEventName'), 'PreToolUse',
            'hookSpecificOutput.hookEventName must be `PreToolUse`',
        )
        self.assertEqual(
            hso.get('permissionDecision'), 'deny',
            'hookSpecificOutput.permissionDecision must be `deny` to '
            'reject the tool call',
        )
        self.assertIn(
            'worktree',
            (hso.get('permissionDecisionReason') or '').lower(),
            'permissionDecisionReason must explain the boundary',
        )

    def test_allow_inside_cwd_uses_hookSpecificOutput(self) -> None:
        result = _run(
            _WORKTREE_HOOK,
            {'tool_name': 'Read', 'tool_input': {'file_path': 'src/foo.py'}},
            cwd=self.cwd,
        )
        self.assertIn(
            'hookSpecificOutput', result,
            'PreToolUse allow must also use `hookSpecificOutput` so '
            'Claude Code reads from a single canonical field.  Got: '
            + json.dumps(result),
        )
        self.assertEqual(
            result['hookSpecificOutput'].get('permissionDecision'),
            'allow',
        )

    def test_unknown_tool_allows_with_hookSpecificOutput(self) -> None:
        result = _run(
            _WORKTREE_HOOK,
            {'tool_name': 'SomeOtherTool', 'tool_input': {}},
            cwd=self.cwd,
        )
        self.assertEqual(
            result.get('hookSpecificOutput', {}).get('permissionDecision'),
            'allow',
            'tools the worktree-jail does not know must pass through '
            'as `permissionDecision: allow`',
        )

    def test_malformed_input_fails_open_with_hookSpecificOutput(self) -> None:
        result_raw = subprocess.run(
            [sys.executable, _WORKTREE_HOOK],
            input=b'not json{{{',
            capture_output=True,
            cwd=self.cwd,
        )
        self.assertEqual(result_raw.returncode, 0)
        result = json.loads(result_raw.stdout.decode())
        self.assertEqual(
            result.get('hookSpecificOutput', {}).get('permissionDecision'),
            'allow',
            'malformed hook input must fail OPEN — but in the '
            'canonical protocol shape, not the legacy one',
        )


class BashJailHookProtocolTest(unittest.TestCase):
    """bash_jail_hook.py emits the canonical PreToolUse protocol."""

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix='hook-proto-bash-')
        self.cwd = os.path.realpath(self._tmp)

    def tearDown(self) -> None:
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_deny_uses_hookSpecificOutput(self) -> None:
        result = _run(
            _BASH_HOOK,
            {
                'tool_name': 'Bash',
                'tool_input': {'command': 'cat /etc/passwd'},
            },
            cwd=self.cwd,
        )
        self.assertIn(
            'hookSpecificOutput', result,
            'PreToolUse deny must be wrapped in `hookSpecificOutput` '
            '(#425 follow-up).  Got: ' + json.dumps(result),
        )
        self.assertEqual(
            result['hookSpecificOutput'].get('permissionDecision'),
            'deny',
        )

    def test_allow_uses_hookSpecificOutput(self) -> None:
        result = _run(
            _BASH_HOOK,
            {
                'tool_name': 'Bash',
                'tool_input': {'command': 'ls .'},
            },
            cwd=self.cwd,
        )
        self.assertEqual(
            result.get('hookSpecificOutput', {}).get('permissionDecision'),
            'allow',
            'allowed Bash command must use `permissionDecision: allow` '
            'in the canonical shape',
        )

    def test_non_bash_tool_passes_through(self) -> None:
        result = _run(
            _BASH_HOOK,
            {
                'tool_name': 'Read',
                'tool_input': {'file_path': '/etc/passwd'},
            },
            cwd=self.cwd,
        )
        self.assertEqual(
            result.get('hookSpecificOutput', {}).get('permissionDecision'),
            'allow',
            'bash hook must allow non-Bash tools (the worktree-jail '
            'hook handles those)',
        )


if __name__ == '__main__':
    unittest.main()
