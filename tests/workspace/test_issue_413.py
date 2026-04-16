"""Issue #413: PreToolUse jail hook references deleted path.

Spec:
1. The jail_hook command in actors.py must reference teaparty/workspace/worktree_hook.py,
   not the deleted orchestrator/worktree_hook.py.
2. The hook must be executable: invoking it via the command path that actors.py assembles
   must produce correct JSON output for all tool categories.
3. The hook must block absolute paths that target locations outside the worktree.
4. The hook must allow relative paths (in-worktree by definition).
5. The hook must deny absolute paths that point inside the worktree with a suggestion
   to use the relative equivalent.
6. Hook failures (bad JSON input) must not crash the hook — fail-open with allowed:true.

Dimensions covered:
- actors.py command path: correct vs. deleted (load-bearing path reference test)
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


class ActorsJailHookPathTest(unittest.TestCase):
    """Verify actors.py references the hook at its actual filesystem location."""

    def _actors_command(self) -> str:
        """Return the jail_hook command string from actors.py source."""
        actors_src = os.path.join(_REPO_ROOT, 'teaparty', 'cfa', 'actors.py')
        with open(actors_src) as f:
            content = f.read()
        m = re.search(r"'command':\s*'([^']*worktree_hook\.py)'", content)
        self.assertIsNotNone(
            m,
            'jail_hook command containing worktree_hook.py not found in actors.py — '
            'the hook setup may have been removed or restructured',
        )
        return m.group(1)  # e.g. 'python3 teaparty/workspace/worktree_hook.py'

    def test_actors_jail_hook_script_path_exists_on_disk(self):
        """The path embedded in actors.py jail_hook command must resolve to a real file.

        If this test fails with 'file does not exist at .../orchestrator/worktree_hook.py',
        the command in actors.py still points to the deleted pre-flatten location.
        """
        command = self._actors_command()
        parts = command.split()
        script_rel = parts[-1]  # last token is the script path
        full_path = os.path.join(_REPO_ROOT, script_rel)
        self.assertTrue(
            os.path.isfile(full_path),
            f'Jail hook file does not exist at {full_path}. '
            f'actors.py references {script_rel!r} but that path does not exist. '
            f'The hook is inactive — agents can write anywhere.',
        )

    def test_actors_jail_hook_does_not_reference_deleted_orchestrator_path(self):
        """The deleted orchestrator/ path must not appear in the jail_hook command.

        If this test fails, the hook still points to the pre-flatten location that
        no longer exists, making the jail silently inactive.
        """
        actors_src = os.path.join(_REPO_ROOT, 'teaparty', 'cfa', 'actors.py')
        with open(actors_src) as f:
            content = f.read()
        self.assertNotIn(
            'orchestrator/worktree_hook.py',
            content,
            'actors.py still references the deleted orchestrator/worktree_hook.py path. '
            'This makes the jail hook inactive on every agent launch.',
        )


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


if __name__ == '__main__':
    unittest.main()
