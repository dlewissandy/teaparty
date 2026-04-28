"""Regression: every settings.json gets a PreToolUse worktree_hook entry.

The PreToolUse worktree-jail hook is the actual sandbox boundary for
agent filesystem writes — it denies any path that resolves outside
``os.getcwd()``.  Before this change the hook was only registered
for the CfA engine's own session (the project lead in the job
worktree); dispatched workers had the hook script staged but never
wired into ``settings.json``, so Claude CLI fell back to its default
permission flow and prompted for any in-tree write.  Workers stalled
on prompts the operator never saw.

The fix moves registration into the launcher's ``_register_worktree_jail_hook``
helper, called by every settings-composition path.  Every agent that
ever launches has the hook in its PreToolUse declarations.
"""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from teaparty.runners.launcher import _register_worktree_jail_hook


class RegisterWorktreeJailHookTest(unittest.TestCase):
    """``_register_worktree_jail_hook`` adds a PreToolUse declaration."""

    def test_empty_settings_get_hook_entry(self) -> None:
        settings: dict = {}
        _register_worktree_jail_hook(settings)
        pre = settings['hooks']['PreToolUse']
        self.assertEqual(len(pre), 1)
        entry = pre[0]
        self.assertEqual(entry['matcher'], 'Read|Edit|Write|Glob|Grep')
        # The command resolves to an ABSOLUTE path to the package's
        # ``worktree_hook.py``.  Chat-tier launches (proxy, OM) run from
        # a cwd with no ``.claude/hooks/`` next to it; a relative path
        # produces ``can't open file`` on every Read/Edit/Write/Glob/Grep
        # invocation.  Absolute keeps both tiers on one codepath.
        cmd = entry['hooks'][0]['command']
        self.assertTrue(
            cmd.startswith('python3 /'),
            f'expected absolute path command, got {cmd!r}',
        )
        self.assertTrue(
            cmd.endswith('/teaparty/workspace/worktree_hook.py'),
            f'expected ship-with-package script, got {cmd!r}',
        )
        self.assertEqual(entry['hooks'][0]['type'], 'command')

    def test_existing_hooks_are_preserved(self) -> None:
        """Existing PreToolUse entries (enforce-ownership, bash-jail) survive."""
        settings = {
            'hooks': {
                'PreToolUse': [
                    {
                        'matcher': 'Edit|Write',
                        'hooks': [{'type': 'command',
                                   'command': '.claude/hooks/enforce-ownership.sh'}],
                    },
                    {
                        'matcher': 'Bash',
                        'hooks': [{'type': 'command',
                                   'command': 'python3 .claude/hooks/bash_jail_hook.py'}],
                    },
                ],
            },
        }
        _register_worktree_jail_hook(settings)
        pre = settings['hooks']['PreToolUse']
        # Existing entries kept, new entry appended.
        self.assertEqual(len(pre), 3)
        commands = [h.get('command') for entry in pre for h in entry.get('hooks', [])]
        self.assertIn('.claude/hooks/enforce-ownership.sh', commands)
        self.assertIn('python3 .claude/hooks/bash_jail_hook.py', commands)
        self.assertTrue(
            any(c.endswith('/teaparty/workspace/worktree_hook.py')
                for c in commands),
            f'no absolute worktree_hook.py command in {commands!r}',
        )

    def test_stale_relative_entry_is_healed(self) -> None:
        """A settings file written before the absolute-path migration is healed.

        Prior versions wrote ``python3 .claude/hooks/worktree_hook.py``
        (relative), which fails for chat-tier launches whose cwd has
        no staged ``.claude/hooks/``.  On the next launch the helper
        rewrites that entry to the absolute path so the broken
        config does not survive a process restart.
        """
        settings = {
            'hooks': {
                'PreToolUse': [
                    {
                        'matcher': 'Read|Edit|Write|Glob|Grep',
                        'hooks': [{
                            'type': 'command',
                            'command': 'python3 .claude/hooks/worktree_hook.py',
                        }],
                    },
                ],
            },
        }
        _register_worktree_jail_hook(settings)
        pre = settings['hooks']['PreToolUse']
        # Same single entry, but with the absolute-path command now.
        self.assertEqual(len(pre), 1)
        cmd = pre[0]['hooks'][0]['command']
        self.assertTrue(cmd.startswith('python3 /'))
        self.assertTrue(cmd.endswith('/teaparty/workspace/worktree_hook.py'))

    def test_idempotent_no_duplicate_on_repeated_calls(self) -> None:
        """Calling twice does not duplicate the entry."""
        settings: dict = {}
        _register_worktree_jail_hook(settings)
        _register_worktree_jail_hook(settings)
        pre = settings['hooks']['PreToolUse']
        worktree_hooks = [
            h for entry in pre for h in entry.get('hooks', [])
            if 'worktree_hook' in h.get('command', '')
        ]
        self.assertEqual(len(worktree_hooks), 1)

    def test_malformed_hooks_section_replaced(self) -> None:
        """If ``hooks`` is not a dict, replace it."""
        settings = {'hooks': 'not-a-dict'}
        _register_worktree_jail_hook(settings)
        self.assertIsInstance(settings['hooks'], dict)
        self.assertIn('PreToolUse', settings['hooks'])

    def test_compose_launch_config_registers_hook(self) -> None:
        """End-to-end: a fresh chat-tier compose has the hook in its settings.json.

        Pins the wiring at the call site (``compose_launch_config``);
        without this, only the helper unit-test would catch a
        regression that removed the call.
        """
        import json
        import os
        import tempfile
        from teaparty.runners.launcher import compose_launch_config

        with tempfile.TemporaryDirectory() as tmp:
            tp_home = os.path.join(tmp, '.teaparty')
            agent_dir = os.path.join(tp_home, 'management', 'agents', 'om')
            os.makedirs(agent_dir)
            with open(os.path.join(agent_dir, 'agent.md'), 'w') as f:
                f.write('---\nname: om\n---\nbody\n')
            with open(os.path.join(agent_dir, 'settings.yaml'), 'w') as f:
                f.write('permissions:\n  allow:\n    - Read\n    - Write\n')
            config_dir = os.path.join(tmp, 'cfg')
            compose_launch_config(
                config_dir=config_dir,
                agent_name='om',
                scope='management',
                teaparty_home=tp_home,
            )
            with open(os.path.join(config_dir, 'settings.json')) as f:
                settings = json.load(f)
            commands = [
                h.get('command')
                for entry in (settings.get('hooks') or {}).get('PreToolUse', [])
                for h in entry.get('hooks', [])
            ]
            self.assertTrue(
                any(c.endswith('/teaparty/workspace/worktree_hook.py')
                    and c.startswith('python3 /')
                    for c in commands),
                f'compose_launch_config did not register absolute hook: {commands!r}',
            )

    def test_chat_tier_hook_command_resolves_without_staging(self) -> None:
        """The hook must run from a chat-tier cwd that has no .claude/hooks/.

        Concrete regression: when the hook command was relative
        (``python3 .claude/hooks/worktree_hook.py``), every chat-tier
        proxy launch failed every Read with ``can't open file`` —
        because the proxy's launch_cwd is ``child_session.path``
        (a config dir, not a worktree) and ``.claude/hooks/`` is not
        next to it.  The proxy gave a meta-response about a hook
        configuration issue instead of ruling on the gate, and the
        dashboard's gate panel saw no resolution.

        This test pins the resolution: parse the registered command,
        check that the script path it points to actually exists.
        """
        import shlex
        settings: dict = {}
        _register_worktree_jail_hook(settings)
        cmd = settings['hooks']['PreToolUse'][0]['hooks'][0]['command']
        tokens = shlex.split(cmd)
        # Token 0 is the interpreter; token 1 must be the script path.
        self.assertEqual(tokens[0], 'python3')
        script_path = tokens[1]
        self.assertTrue(
            os.path.isabs(script_path),
            f'hook script path must be absolute, got {script_path!r}',
        )
        self.assertTrue(
            os.path.isfile(script_path),
            f'hook script path does not resolve to a file: {script_path!r}',
        )


if __name__ == '__main__':
    unittest.main()
