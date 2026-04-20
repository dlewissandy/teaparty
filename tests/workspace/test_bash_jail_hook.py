"""PreToolUse Bash jail hook — sandboxes Bash to the worktree.

The hook is defense-in-depth beside the narrow Bash allowlist in
settings.yaml.  It rejects commands that:

1. Reference system paths (/etc/, /var/, /usr/, /root/, /home/, ...)
2. Reference $HOME (~/...)
3. Contain absolute paths outside the current worktree
4. Write to .git/ or .claude/

These tests exercise each branch directly against ``_check_bash`` and
via subprocess (the path Claude CLI actually uses).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

# Repo root: two levels up from tests/workspace/
_REPO_ROOT = str(Path(__file__).parent.parent.parent)
sys.path.insert(0, _REPO_ROOT)

_HOOK_PATH = os.path.join(
    _REPO_ROOT, 'teaparty', 'workspace', 'bash_jail_hook.py',
)


def _run_hook(command: str, cwd: str) -> dict:
    """Invoke the hook as Claude CLI does and parse the JSON response."""
    payload = json.dumps({'tool_name': 'Bash', 'tool_input': {'command': command}})
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


class BashJailHookUnitTest(unittest.TestCase):
    """Direct ``_check_bash`` tests — cover each rejection branch."""

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix='tp-bash-jail-')
        self.worktree = os.path.realpath(self._tmp)

    def tearDown(self) -> None:
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _check(self, command: str) -> dict:
        from teaparty.workspace.bash_jail_hook import _check_bash
        return _check_bash(command, self.worktree)

    # ── Branch 1: system path substrings ───────────────────────────────

    def test_cat_etc_passwd_is_denied(self) -> None:
        r = self._check('cat /etc/passwd')
        self.assertFalse(r['allowed'], r)
        self.assertIn('/etc', r['reason'])

    def test_ls_var_log_is_denied(self) -> None:
        r = self._check('ls /var/log')
        self.assertFalse(r['allowed'], r)

    def test_usr_bin_reference_is_denied(self) -> None:
        """Even if not dangerous, /usr/ is out of sandbox."""
        r = self._check('ls /usr/bin')
        self.assertFalse(r['allowed'], r)

    # ── Branch 2: $HOME / ~/ ───────────────────────────────────────────

    def test_cat_home_ssh_is_denied(self) -> None:
        r = self._check('cat ~/.ssh/id_rsa')
        self.assertFalse(r['allowed'], r)
        self.assertIn('$HOME', r['reason'])

    def test_tilde_at_start_is_denied(self) -> None:
        r = self._check('~/bin/evil')
        self.assertFalse(r['allowed'], r)

    def test_tilde_inside_quotes_is_denied(self) -> None:
        r = self._check('echo "~/x"')
        self.assertFalse(r['allowed'], r)

    # ── Branch 3: absolute paths outside worktree ─────────────────────

    def test_absolute_path_outside_worktree_denied(self) -> None:
        r = self._check('echo hello > /tmp/evil.txt')
        self.assertFalse(r['allowed'], r)

    def test_absolute_path_inside_worktree_allowed(self) -> None:
        r = self._check(f'ls {self.worktree}/src')
        self.assertTrue(r['allowed'], r)

    def test_absolute_path_equal_to_worktree_allowed(self) -> None:
        r = self._check(f'ls {self.worktree}')
        self.assertTrue(r['allowed'], r)

    # ── Branch 4: writes to .git / .claude ─────────────────────────────

    def test_rm_git_config_denied(self) -> None:
        r = self._check('rm .git/config')
        self.assertFalse(r['allowed'], r)
        self.assertIn('.git', r['reason'])

    def test_rm_rf_claude_denied(self) -> None:
        r = self._check('rm -rf .claude/agents')
        self.assertFalse(r['allowed'], r)

    def test_mv_into_git_denied(self) -> None:
        r = self._check('mv evil .git/HEAD')
        self.assertFalse(r['allowed'], r)

    def test_tee_claude_settings_denied(self) -> None:
        r = self._check('tee .claude/settings.json')
        self.assertFalse(r['allowed'], r)

    def test_redirect_into_git_denied(self) -> None:
        r = self._check('echo x > .git/HEAD')
        self.assertFalse(r['allowed'], r)

    def test_redirect_into_claude_denied(self) -> None:
        r = self._check('echo x >> .claude/settings.json')
        self.assertFalse(r['allowed'], r)

    def test_read_from_git_allowed(self) -> None:
        """Reads from .git/ are fine — `git log`, `cat .git/HEAD`, etc."""
        r = self._check('cat .git/HEAD')
        self.assertTrue(r['allowed'], r)

    # ── Allow paths ────────────────────────────────────────────────────

    def test_plain_git_status_allowed(self) -> None:
        r = self._check('git status')
        self.assertTrue(r['allowed'], r)

    def test_pytest_allowed(self) -> None:
        r = self._check('pytest tests/ -q')
        self.assertTrue(r['allowed'], r)

    def test_echo_hello_allowed(self) -> None:
        r = self._check('echo hello')
        self.assertTrue(r['allowed'], r)

    def test_empty_command_allowed(self) -> None:
        r = self._check('')
        self.assertTrue(r['allowed'], r)

    # ── Parse-error resilience ────────────────────────────────────────

    def test_unbalanced_quotes_fail_open_on_tokenisation(self) -> None:
        """If shlex can't parse, we don't block on path checks — but the
        substring checks still apply.  A command with unbalanced quotes
        that does NOT touch forbidden paths should be allowed."""
        r = self._check('echo "unterminated')
        self.assertTrue(r['allowed'], r)

    def test_unbalanced_quotes_still_block_system_paths(self) -> None:
        """Substring check fires even when tokenisation fails."""
        r = self._check('cat "/etc/passwd')
        self.assertFalse(r['allowed'], r)


class BashJailHookSubprocessTest(unittest.TestCase):
    """Invoke the hook as Claude CLI does — via subprocess with JSON stdin."""

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix='tp-bash-jail-sub-')
        self.worktree = os.path.realpath(self._tmp)

    def tearDown(self) -> None:
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_subprocess_denies_etc(self) -> None:
        r = _run_hook('cat /etc/passwd', cwd=self.worktree)
        self.assertFalse(r.get('allowed', True), r)

    def test_subprocess_allows_git_status(self) -> None:
        r = _run_hook('git status', cwd=self.worktree)
        self.assertTrue(r.get('allowed', False), r)

    def test_subprocess_non_bash_tool_allowed(self) -> None:
        payload = json.dumps({
            'tool_name': 'Read',
            'tool_input': {'file_path': '/etc/passwd'},
        })
        result = subprocess.run(
            [sys.executable, _HOOK_PATH],
            input=payload.encode(), capture_output=True, cwd=self.worktree,
        )
        self.assertEqual(result.returncode, 0)
        out = json.loads(result.stdout.decode())
        self.assertTrue(
            out['allowed'],
            'Non-Bash tools must be passed through (other hooks handle them).',
        )

    def test_subprocess_malformed_input_fails_open(self) -> None:
        """Transport-level failure should not block agent work."""
        result = subprocess.run(
            [sys.executable, _HOOK_PATH],
            input=b'not json at all', capture_output=True, cwd=self.worktree,
        )
        self.assertEqual(result.returncode, 0)
        out = json.loads(result.stdout.decode())
        self.assertTrue(out['allowed'])


class BashJailHookStagedByLauncherTest(unittest.TestCase):
    """compose_launch_worktree must stage bash_jail_hook.py alongside worktree_hook."""

    def test_bash_jail_hook_staged_into_worktree(self) -> None:
        """The launcher's hook-staging must include bash_jail_hook.py."""
        import shutil
        import yaml
        tmp = tempfile.mkdtemp(prefix='tp-bash-stage-')
        self.addCleanup(shutil.rmtree, tmp, True)

        # Minimal teaparty tree (no hooks declared).
        tp_home = os.path.join(tmp, '.teaparty')
        scope_dir = os.path.join(tp_home, 'management')
        agents_dir = os.path.join(scope_dir, 'agents', 'x')
        os.makedirs(agents_dir)
        with open(os.path.join(agents_dir, 'agent.md'), 'w') as f:
            f.write('---\ndescription: x\n---\n')
        with open(os.path.join(scope_dir, 'settings.yaml'), 'w') as f:
            yaml.dump({}, f)

        worktree = os.path.join(tmp, 'worktree')
        os.makedirs(worktree)

        from teaparty.runners.launcher import compose_launch_worktree
        compose_launch_worktree(
            worktree=worktree,
            agent_name='x',
            scope='management',
            teaparty_home=tp_home,
        )

        staged = os.path.join(worktree, '.claude', 'hooks', 'bash_jail_hook.py')
        self.assertTrue(
            os.path.isfile(staged),
            f'bash_jail_hook.py not staged at {staged} — Bash sandboxing '
            f'will silently not run when the hook declaration in '
            f'settings.yaml invokes it.',
        )


if __name__ == '__main__':
    unittest.main()
