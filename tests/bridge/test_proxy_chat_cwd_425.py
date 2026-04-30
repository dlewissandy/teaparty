"""Issue #425: chat-tier cwd resolution maps the participant to a worktree
and materializes a per-chat clone.

When the human clicks a participants-card entry, the bridge:

  1. Resolves the *source* worktree from the qualifier:
     - ``<slug>:<name>``  → the project's worktree.
     - ``<name>`` (bare)  → the management repo.
  2. Materializes that source as a per-chat clone (real-file copy, no
     symlinks) at a stable path under the management home, reusing it
     across turns of the same chat.
  3. Hands the clone path to ``_invoke_proxy`` as cwd.

These tests pin each piece in isolation so a regression names the
specific case that drifted.
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import MethodType

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from teaparty.bridge.server import TeaPartyBridge


class _MiniBridge:
    def __init__(
        self,
        repo_root: str,
        teaparty_home: str,
        project_paths: dict[str, str],
    ):
        self._repo_root = repo_root
        self.teaparty_home = teaparty_home
        self._project_paths = project_paths

    def _lookup_project_path(self, slug: str) -> str | None:
        return self._project_paths.get(slug)


def _bind(mini: _MiniBridge, *names: str) -> None:
    for name in names:
        setattr(mini, name, MethodType(getattr(TeaPartyBridge, name), mini))


class ProxyChatSourceWorktreeTest(unittest.TestCase):
    """Source-worktree resolution per the issue's Intent table."""

    def setUp(self) -> None:
        self.repo_root = '/repo/management'
        self.projects = {
            'joke-book': '/repo/projects/joke-book',
            'thesis':    '/repo/projects/thesis',
        }
        self.mini = _MiniBridge(self.repo_root, '/tp', self.projects)
        _bind(self.mini, '_proxy_chat_source_worktree')

    def test_management_human_maps_to_management_repo(self) -> None:
        self.assertEqual(
            self.mini._proxy_chat_source_worktree('primus'),
            self.repo_root,
            "Management-page participant click (bare-name qualifier) "
            "must source the proxy from the management repo (#425)",
        )

    def test_project_human_maps_to_project_worktree(self) -> None:
        self.assertEqual(
            self.mini._proxy_chat_source_worktree('joke-book:primus'),
            '/repo/projects/joke-book',
            "Project-page participant click (slug:name qualifier) "
            "must source the proxy from that project's worktree (#425)",
        )

    def test_each_project_resolves_to_its_own_worktree(self) -> None:
        self.assertNotEqual(
            self.mini._proxy_chat_source_worktree('joke-book:primus'),
            self.mini._proxy_chat_source_worktree('thesis:primus'),
            "Different projects must resolve to different sources "
            "(#425 — no collapsing to a default)",
        )

    def test_unknown_project_slug_falls_back_to_management(self) -> None:
        self.assertEqual(
            self.mini._proxy_chat_source_worktree('vanished:primus'),
            self.repo_root,
            "An unregistered project slug must fall back to the "
            "management repo (safe default; #425)",
        )

    def test_same_human_resolves_per_click_origin(self) -> None:
        self.assertEqual(
            self.mini._proxy_chat_source_worktree('primus'),
            self.repo_root,
        )
        self.assertEqual(
            self.mini._proxy_chat_source_worktree('joke-book:primus'),
            '/repo/projects/joke-book',
            "Same participant clicked on the project page must source "
            "from the project worktree, not management (#425)",
        )


class ProxyChatWorkspaceMaterializationTest(unittest.TestCase):
    """The chat path materializes a per-chat clone (real files, no
    symlinks), reuses it across turns, and isolates one chat's clone
    from another's."""

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix='proxy-chat-mat-')
        self.repo_root = os.path.join(self._tmp, 'mgmt')
        self.teaparty_home = os.path.join(self._tmp, 'mgmt-tp')
        os.makedirs(self.repo_root)
        os.makedirs(self.teaparty_home)
        # Write some files in the management repo so it's a meaningful source.
        for relpath in ('README.md', 'docs/intro.md'):
            full = os.path.join(self.repo_root, relpath)
            os.makedirs(os.path.dirname(full), exist_ok=True)
            with open(full, 'w') as f:
                f.write(f'# {relpath}\n')
        # And a separate "project" worktree.
        self.project_path = os.path.join(self._tmp, 'jokebook')
        os.makedirs(os.path.join(self.project_path, 'manuscript'))
        with open(
            os.path.join(self.project_path, 'manuscript', 'chapter-1.md'),
            'w',
        ) as f:
            f.write('# chapter one\n')

        self.mini = _MiniBridge(
            self.repo_root,
            self.teaparty_home,
            {'jokebook': self.project_path},
        )
        _bind(
            self.mini,
            '_proxy_chat_source_worktree',
            '_proxy_chat_clone_dir',
            '_ensure_proxy_chat_workspace',
        )

    def tearDown(self) -> None:
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_clone_is_under_management_home(self) -> None:
        clone = self.mini._ensure_proxy_chat_workspace('jokebook:primus')
        self.assertTrue(
            clone.startswith(self.teaparty_home),
            f'chat clone must live under management home '
            f'({self.teaparty_home}); got {clone}.  Memory and storage '
            f'invariant (#425): proxy state lives at management.',
        )

    def test_clone_holds_source_files_at_root(self) -> None:
        clone = self.mini._ensure_proxy_chat_workspace('jokebook:primus')
        target = os.path.join(clone, 'manuscript', 'chapter-1.md')
        self.assertTrue(
            os.path.isfile(target),
            f"source file 'manuscript/chapter-1.md' must appear in "
            f"chat clone at {target}; #425 — proxy reads work via "
            f"./<relpath> from cwd",
        )

    def test_clone_contains_no_symlinks(self) -> None:
        clone = self.mini._ensure_proxy_chat_workspace('jokebook:primus')
        symlinks: list[str] = []
        for dirpath, _dirs, files in os.walk(clone):
            for name in files:
                full = os.path.join(dirpath, name)
                if os.path.islink(full):
                    symlinks.append(os.path.relpath(full, clone))
        self.assertEqual(
            symlinks, [],
            f'chat clone contains symlinks: {symlinks}; #425 forbids '
            f'symlinks (worktree-jail would reject via realpath)',
        )

    def test_repeated_call_reuses_existing_clone(self) -> None:
        # Snapshot is taken at chat-open time; subsequent turns of the
        # same chat must reuse the same clone (the proxy reviews "what
        # the work looked like when the human opened this chat").
        clone1 = self.mini._ensure_proxy_chat_workspace('jokebook:primus')
        # Mutate the clone to mark it.
        marker = os.path.join(clone1, '.chat-marker')
        with open(marker, 'w') as f:
            f.write('round-1')
        clone2 = self.mini._ensure_proxy_chat_workspace('jokebook:primus')
        self.assertEqual(
            clone1, clone2,
            'reusing the chat clone path keeps multiple turns inside '
            'the same snapshot (#425)',
        )
        self.assertTrue(
            os.path.isfile(marker),
            f'reuse must NOT re-clone over the existing dir; the '
            f"marker file at {marker} should survive (#425 — chat "
            f"snapshot is stable across turns)",
        )

    def test_distinct_qualifiers_get_distinct_clones(self) -> None:
        a = self.mini._ensure_proxy_chat_workspace('jokebook:primus')
        b = self.mini._ensure_proxy_chat_workspace('primus')
        self.assertNotEqual(
            a, b,
            f"different qualifiers must produce different clone paths; "
            f"got {a} and {b}.  Two chats must not share a workspace "
            f"(#425).",
        )


if __name__ == '__main__':
    unittest.main()
