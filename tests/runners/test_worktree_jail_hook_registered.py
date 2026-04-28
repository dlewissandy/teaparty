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
        self.assertEqual(
            entry['hooks'][0]['command'],
            'python3 .claude/hooks/worktree_hook.py',
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
        self.assertIn('python3 .claude/hooks/worktree_hook.py', commands)

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
            self.assertIn('python3 .claude/hooks/worktree_hook.py', commands)


if __name__ == '__main__':
    unittest.main()
