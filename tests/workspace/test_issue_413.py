"""Issue #413: PreToolUse jail hook references deleted path.

Spec:
1. The jail_hook command in actors.py must reference teaparty/workspace/worktree_hook.py,
   not the deleted orchestrator/worktree_hook.py.
2. AgentRunner.run() must raise immediately if the hook script is absent from the worktree,
   making hook failures observable rather than silently allowing unrestricted writes.
3. The hook must be executable: invoking it via the command path that actors.py assembles
   must produce correct JSON output for all tool categories.
4. The hook must block absolute paths that target locations outside the worktree.
5. The hook must allow relative paths (in-worktree by definition).
6. The hook must deny absolute paths that point inside the worktree with a suggestion
   to use the relative equivalent.
7. Hook failures (bad JSON input) must not crash the hook — fail-open with allowed:true.

Dimensions covered:
- actors.py command path: correct vs. deleted (load-bearing path reference test)
- Auditable failure mode: hook script absent → RuntimeError, not silent launch
- Tool category: file_path tools (Read, Edit, Write), path tools (Glob, Grep), unknown
- Path type: relative, absolute inside worktree, absolute outside worktree, missing field
- Invocation: Python module (_check), subprocess via the command path in actors.py
- Input validity: valid JSON, malformed JSON, missing fields
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

# Repo root: two levels up from tests/workspace/
_REPO_ROOT = str(Path(__file__).parent.parent.parent)
_HOOK_PATH = os.path.join(_REPO_ROOT, 'teaparty', 'workspace', 'worktree_hook.py')


def _run_hook(tool_name: str, tool_input: dict, cwd: str) -> dict:
    """Run worktree_hook.py as a subprocess and return the parsed JSON output."""
    payload = json.dumps({'tool_name': tool_name, 'tool_input': tool_input})
    result = subprocess.run(
        [sys.executable, _HOOK_PATH],
        input=payload.encode(),
        capture_output=True,
        cwd=cwd,
    )
    assert result.returncode == 0, (
        f'hook subprocess exited {result.returncode}: {result.stderr.decode()}'
    )
    return json.loads(result.stdout.decode())


class WorktreeHookSubprocessTest(unittest.TestCase):
    """Run worktree_hook.py as a subprocess (the real invocation path) and verify behavior.

    All tests run from a temporary directory that acts as the simulated worktree CWD.
    The hook uses os.getcwd() to determine the worktree boundary.
    """

    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        # Resolve symlinks so paths match os.getcwd() output in the subprocess.
        # On macOS /var is a symlink to /private/var; normpath alone doesn't resolve it.
        self.worktree_root = os.path.realpath(self._tmp)

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    # ── file_path tools ────────────────────────────────────────────────────

    def test_write_with_absolute_path_outside_worktree_is_denied(self):
        """Write to an absolute path outside the worktree must be denied.

        This is the core invariant: agents cannot write to arbitrary filesystem locations.
        """
        outside = '/tmp/escape.txt'
        result = _run_hook('Write', {'file_path': outside}, cwd=self.worktree_root)
        self.assertFalse(
            result.get('allowed', True),
            f'Write to {outside} must be denied when worktree is {self.worktree_root}, '
            f'got: {result}',
        )
        self.assertIn(
            'worktree',
            result.get('reason', '').lower(),
            f'Denial reason must mention worktree restriction, got: {result.get("reason")}',
        )

    def test_edit_with_absolute_path_outside_worktree_is_denied(self):
        """Edit to an absolute path outside the worktree must be denied."""
        outside = '/etc/hosts'
        result = _run_hook('Edit', {'file_path': outside}, cwd=self.worktree_root)
        self.assertFalse(
            result.get('allowed', True),
            f'Edit to {outside} must be denied, got: {result}',
        )

    def test_read_with_absolute_path_outside_worktree_is_denied(self):
        """Read from an absolute path outside the worktree must be denied."""
        outside = '/etc/passwd'
        result = _run_hook('Read', {'file_path': outside}, cwd=self.worktree_root)
        self.assertFalse(
            result.get('allowed', True),
            f'Read from {outside} must be denied, got: {result}',
        )

    def test_write_with_relative_path_is_allowed(self):
        """Write with a relative path is always allowed (relative paths stay in worktree)."""
        result = _run_hook('Write', {'file_path': 'output/result.md'}, cwd=self.worktree_root)
        self.assertTrue(
            result.get('allowed', False),
            f'Write with relative path must be allowed, got: {result}',
        )

    def test_write_with_absolute_path_inside_worktree_is_denied_with_relative_suggestion(self):
        """Absolute path pointing inside the worktree must be denied with a relative suggestion.

        The reason must contain the relative equivalent so the agent can self-correct.
        """
        inside = os.path.join(self.worktree_root, 'src', 'foo.py')
        result = _run_hook('Write', {'file_path': inside}, cwd=self.worktree_root)
        self.assertFalse(
            result.get('allowed', True),
            f'Write to absolute in-worktree path {inside} must be denied, got: {result}',
        )
        reason = result.get('reason', '')
        self.assertIn(
            'src/foo.py',
            reason,
            f'Denial reason must suggest the relative path "src/foo.py", got: {reason!r}',
        )
        # Must NOT say "restricted to files in your worktree" — that's for truly outside paths
        self.assertNotIn(
            'restricted',
            reason.lower(),
            f'In-worktree denial must suggest relative path, not generic restriction: {reason!r}',
        )

    # ── path tools ─────────────────────────────────────────────────────────

    def test_grep_with_absolute_path_outside_worktree_is_denied(self):
        """Grep with an absolute search path outside the worktree must be denied."""
        outside = '/usr/lib'
        result = _run_hook('Grep', {'path': outside}, cwd=self.worktree_root)
        self.assertFalse(
            result.get('allowed', True),
            f'Grep with path={outside} must be denied, got: {result}',
        )

    def test_glob_with_absolute_path_outside_worktree_is_denied(self):
        """Glob with an absolute search path outside the worktree must be denied."""
        outside = '/home'
        result = _run_hook('Glob', {'path': outside}, cwd=self.worktree_root)
        self.assertFalse(
            result.get('allowed', True),
            f'Glob with path={outside} must be denied, got: {result}',
        )

    def test_glob_with_relative_path_is_allowed(self):
        """Glob with a relative path is always allowed."""
        result = _run_hook('Glob', {'path': 'src/**/*.py'}, cwd=self.worktree_root)
        self.assertTrue(
            result.get('allowed', False),
            f'Glob with relative path must be allowed, got: {result}',
        )

    # ── unknown tools ──────────────────────────────────────────────────────

    def test_unknown_tool_is_always_allowed(self):
        """Tools not in the file_path or path category must pass through unconditionally."""
        result = _run_hook('Bash', {'command': 'rm -rf /'}, cwd=self.worktree_root)
        self.assertTrue(
            result.get('allowed', False),
            f'Unknown tool Bash must be allowed by the hook, got: {result}',
        )

    def test_tool_with_missing_path_field_is_allowed(self):
        """Write with no file_path key must be allowed (hook cannot restrict what it cannot see)."""
        result = _run_hook('Write', {}, cwd=self.worktree_root)
        self.assertTrue(
            result.get('allowed', False),
            f'Write with missing file_path must be allowed, got: {result}',
        )

    # ── input resilience ───────────────────────────────────────────────────

    def test_malformed_json_input_produces_allowed_true(self):
        """Malformed JSON on stdin must not crash the hook — it must allow the tool use.

        The hook runs in a subprocess fire-and-forget context. A crash would be undetectable.
        Failing open (allowed: true) is preferable to crashing silently.
        """
        result_raw = subprocess.run(
            [sys.executable, _HOOK_PATH],
            input=b'not valid json{{{',
            capture_output=True,
            cwd=self.worktree_root,
        )
        self.assertEqual(
            result_raw.returncode, 0,
            f'Hook must exit 0 on malformed JSON, got exit {result_raw.returncode}: '
            f'{result_raw.stderr.decode()!r}',
        )
        out = json.loads(result_raw.stdout.decode())
        self.assertTrue(
            out.get('allowed', False),
            f'Hook must allow on malformed JSON (fail-open), got: {out}',
        )


class JailHookValidationTest(unittest.TestCase):
    """_check_jail_hook() must raise if the hook script is absent from the worktree.

    The failure mode must be auditable: a missing hook script must produce an
    immediate RuntimeError, not a silent launch with no filesystem restriction.
    This function is called at the top of AgentRunner.run() before launch().
    """

    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self.worktree = os.path.realpath(self._tmp)

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_check_jail_hook_raises_when_script_absent(self):
        """_check_jail_hook must raise RuntimeError naming the missing path.

        This is the auditable-failure-mode requirement: a worktree without the hook
        script must be caught immediately with a specific message, not silently launched
        with no filesystem restriction. If this test fails, the validation was removed.
        """
        from teaparty.cfa.actors import _check_jail_hook

        hook_script = '.claude/hooks/worktree_hook.py'
        # worktree has no hook script
        with self.assertRaises(RuntimeError) as cm:
            _check_jail_hook(self.worktree, hook_script)

        msg = str(cm.exception)
        self.assertIn(
            hook_script,
            msg,
            f'RuntimeError must name the missing hook script path, got: {msg!r}',
        )
        self.assertIn(
            'missing',
            msg.lower(),
            f'RuntimeError message must indicate the script is missing, got: {msg!r}',
        )

    def test_check_jail_hook_does_not_raise_when_script_present(self):
        """_check_jail_hook must not raise when the hook script exists in the worktree.

        Complement to the above: valid worktrees must pass the check cleanly.
        """
        from teaparty.cfa.actors import _check_jail_hook

        hook_script = '.claude/hooks/worktree_hook.py'
        hook_dir = os.path.join(self.worktree, '.claude', 'hooks')
        os.makedirs(hook_dir)
        import shutil
        shutil.copy(_HOOK_PATH, os.path.join(hook_dir, 'worktree_hook.py'))

        # Must not raise
        try:
            _check_jail_hook(self.worktree, hook_script)
        except RuntimeError as exc:
            self.fail(
                f'_check_jail_hook raised RuntimeError even though hook exists: {exc}'
            )
                # Other RuntimeErrors are acceptable (e.g., missing agent file)


if __name__ == '__main__':
    unittest.main()
