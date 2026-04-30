"""Issue #425: chat-tier cwd resolution maps the participant to a worktree.

When the human clicks a participants-card entry, the bridge launches the
proxy in the worktree of the person clicked.  Per the issue's intent table:

  * `office-manager`        → management repo (the bridge's repo root).
  * `<slug>-lead`           → that project's worktree.
  * Anything else (or an    → management repo (safe default).
    unknown slug)

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

    def test_office_manager_maps_to_management_repo(self) -> None:
        self.assertEqual(
            self.mini._proxy_chat_cwd('office-manager'),
            self.repo_root,
            "OM card click must launch the proxy in the management "
            "repo (#425 intent table)",
        )

    def test_project_lead_maps_to_project_worktree(self) -> None:
        self.assertEqual(
            self.mini._proxy_chat_cwd('joke-book-lead'),
            '/repo/projects/joke-book',
            "Project-lead card click must launch the proxy in that "
            "project's worktree, not the management repo (#425)",
        )

    def test_each_project_lead_maps_to_its_own_worktree(self) -> None:
        # Negative-space-ish: the resolver must not collapse to a single
        # default for any project lead.
        self.assertNotEqual(
            self.mini._proxy_chat_cwd('joke-book-lead'),
            self.mini._proxy_chat_cwd('thesis-lead'),
            "Different project leads must resolve to different "
            "worktrees; collapsing to a default loses scope (#425)",
        )

    def test_unknown_lead_falls_back_to_management(self) -> None:
        self.assertEqual(
            self.mini._proxy_chat_cwd('vanished-lead'),
            self.repo_root,
            "An unregistered project slug must fall back to the "
            "management repo (safe default; #425)",
        )

    def test_arbitrary_qualifier_falls_back_to_management(self) -> None:
        # A qualifier that is neither office-manager nor a *-lead.
        self.assertEqual(
            self.mini._proxy_chat_cwd('alice'),
            self.repo_root,
            "An unrecognized qualifier must fall back to management; "
            "the proxy must never launch in an unspecified cwd (#425)",
        )


if __name__ == '__main__':
    unittest.main()
