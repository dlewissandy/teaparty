"""Issue #425: chat-tier cwd resolution maps the participant to a worktree.

When the human clicks a participants-card entry, the bridge launches the
proxy in the worktree of the person clicked.  The participants-card UI
encodes the click's scope in the conversation qualifier:

  * ``<slug>:<name>``  → click on a project page; cwd = that project's
    worktree.  Falls back to management when the slug doesn't resolve.
  * ``<name>`` (bare)  → click on the management page; cwd = management
    repo (the bridge's repo root).

These tests pin the resolver in isolation so a regression names the
specific case that drifted.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import MethodType

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from teaparty.bridge.server import TeaPartyBridge


class _MiniBridge:
    def __init__(self, repo_root: str, project_paths: dict[str, str]):
        self._repo_root = repo_root
        self._project_paths = project_paths

    def _lookup_project_path(self, slug: str) -> str | None:
        return self._project_paths.get(slug)


class ProxyChatCwdTest(unittest.TestCase):
    """Resolution per the issue's Intent table."""

    def setUp(self) -> None:
        self.repo_root = '/repo/management'
        self.projects = {
            'joke-book': '/repo/projects/joke-book',
            'thesis':    '/repo/projects/thesis',
        }
        self.mini = _MiniBridge(self.repo_root, self.projects)
        self.mini._proxy_chat_cwd = MethodType(
            TeaPartyBridge._proxy_chat_cwd, self.mini,
        )

    def test_management_human_maps_to_management_repo(self) -> None:
        # Bare-name qualifier is the management page click.
        self.assertEqual(
            self.mini._proxy_chat_cwd('primus'),
            self.repo_root,
            "Management-page participant click (bare-name qualifier) "
            "must launch the proxy in the management repo (#425)",
        )

    def test_project_human_maps_to_project_worktree(self) -> None:
        # The qualifier shape ``<slug>:<name>`` encodes the project scope.
        self.assertEqual(
            self.mini._proxy_chat_cwd('joke-book:primus'),
            '/repo/projects/joke-book',
            "Project-page participant click (slug:name qualifier) "
            "must launch the proxy in that project's worktree, not "
            "the management repo (#425)",
        )

    def test_each_project_resolves_to_its_own_worktree(self) -> None:
        # Negative-space: the resolver must not collapse different
        # projects to one default.
        self.assertNotEqual(
            self.mini._proxy_chat_cwd('joke-book:primus'),
            self.mini._proxy_chat_cwd('thesis:primus'),
            "Different projects must resolve to different worktrees; "
            "collapsing to a default loses scope (#425)",
        )

    def test_unknown_project_slug_falls_back_to_management(self) -> None:
        self.assertEqual(
            self.mini._proxy_chat_cwd('vanished:primus'),
            self.repo_root,
            "An unregistered project slug must fall back to the "
            "management repo (safe default; #425)",
        )

    def test_same_human_resolves_per_click_origin(self) -> None:
        # The same human clicked from different pages produces
        # different cwds — the qualifier carries the page-of-click.
        self.assertEqual(
            self.mini._proxy_chat_cwd('primus'),
            self.repo_root,
        )
        self.assertEqual(
            self.mini._proxy_chat_cwd('joke-book:primus'),
            '/repo/projects/joke-book',
            "Same participant clicked on the project page must land "
            "in the project worktree, not management (#425)",
        )


if __name__ == '__main__':
    unittest.main()
