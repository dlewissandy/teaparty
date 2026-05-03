"""Regression: bare ``Write``/``Edit`` allow grants are not path-scoped.

The launcher previously rewrote a bare ``Write`` allow entry into
``Write(<worktree>/**)`` plus ``Write(/tmp/**)`` etc.  The intent was
defense-in-depth on top of the worktree-jail hook (which is the
actual sandbox).  In practice the path-pattern matcher's quirks
(absolute-vs-relative, macOS symlink resolution like ``/var`` vs
``/private/var``, glob anchoring) caused in-tree writes to fall
through to a permission prompt.  The agent waited, never got a
grant, and exited its turn with "I'm blocked on permission."

Now the launcher passes bare ``Write`` / ``Edit`` through to Claude
CLI unchanged.  The worktree-jail hook (PreToolUse) is the real
sandbox; the deny patterns block catalog writes; the worktree's git
boundary is the underlying isolation.  Path-scoping the allow list
added no safety beyond those layers and created the friction that
hung dispatched workers.

This test pins the new behavior.
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from teaparty.runners.launcher import _inject_baseline_deny


class BareWritePassesThroughTest(unittest.TestCase):
    """``permissions.allow`` bare write tools survive composition unchanged."""

    def test_bare_write_is_not_path_scoped(self) -> None:
        """A settings dict with bare ``Write`` keeps ``Write`` after baseline injection."""
        settings = {
            'permissions': {
                'allow': ['Read', 'Write', 'Edit'],
            },
        }
        _inject_baseline_deny(settings)
        allow = settings['permissions']['allow']
        self.assertIn('Write', allow)
        self.assertIn('Edit', allow)
        # No path-scoped variants got generated.
        for entry in allow:
            self.assertFalse(
                entry.startswith('Write(') or entry.startswith('Edit('),
                f'unexpected path-scoped entry: {entry!r}',
            )

    def test_no_scope_writes_to_worktree_function(self) -> None:
        """The function is gone — the brittle middle layer is removed.

        Pinning the absence so a future refactor can't accidentally
        bring it back without revisiting the safety analysis.
        """
        from teaparty.runners import launcher
        self.assertFalse(
            hasattr(launcher, '_scope_writes_to_worktree'),
            '_scope_writes_to_worktree was removed; do not reintroduce '
            'without revisiting the friction-vs-safety analysis',
        )


if __name__ == '__main__':
    unittest.main()
