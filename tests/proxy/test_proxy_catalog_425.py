"""Issue #425: proxy settings.yaml catalog is read-only and recursion-safe.

The proxy is a read-only reviewer.  Its catalog must contain the file-read
tools (Read, Glob, Grep), the skill loader, and the messaging tools needed
to reply.  It MUST NOT contain Write/Edit/Bash (mutation), AskQuestion (would
recurse: proxy can't escalate to itself), or any agent-callable memory tool —
the proxy accesses memory through host-side hooks, not tools.

Each test pins one slice of the catalog so a regression names the exact
violation rather than a vague "settings drifted."
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent.parent.parent))


def _load_proxy_allow() -> list[str]:
    repo_root = Path(__file__).resolve().parents[2]
    settings_path = (
        repo_root / '.teaparty' / 'management' / 'agents'
        / 'proxy' / 'settings.yaml'
    )
    if not settings_path.exists():
        raise AssertionError(
            f'proxy settings.yaml missing at {settings_path}; '
            f'#425 requires the file to define the catalog',
        )
    with open(settings_path) as fh:
        data = yaml.safe_load(fh) or {}
    return list((data.get('permissions') or {}).get('allow') or [])


class ProxyCatalogReadAccessTest(unittest.TestCase):
    """Read tools needed for the diligence rail."""

    def test_allow_contains_read(self) -> None:
        allow = _load_proxy_allow()
        self.assertIn(
            'Read', allow,
            'catalog missing Read; proxy cannot inspect deliverables '
            'without it (#425 diligence rail)',
        )

    def test_allow_contains_glob(self) -> None:
        allow = _load_proxy_allow()
        self.assertIn(
            'Glob', allow,
            'catalog missing Glob; proxy cannot walk the worktree '
            'without it (#425 diligence rail)',
        )

    def test_allow_contains_grep(self) -> None:
        allow = _load_proxy_allow()
        self.assertIn(
            'Grep', allow,
            'catalog missing Grep; proxy cannot verify question '
            'claims by searching the worktree (#425 diligence rail)',
        )


class ProxyCatalogSkillLoaderTest(unittest.TestCase):
    def test_allow_contains_skill(self) -> None:
        allow = _load_proxy_allow()
        self.assertIn(
            'Skill', allow,
            'catalog missing Skill; the escalation skill cannot be '
            'loaded at runtime without it (#425)',
        )


class ProxyCatalogMessagingTest(unittest.TestCase):
    """Messaging + close tools — proxy needs to reply and close."""

    @staticmethod
    def _has_named(allow: list[str], name: str) -> bool:
        return any(
            tool == name or tool.endswith(f'__{name}')
            for tool in allow
        )

    def test_allow_contains_send(self) -> None:
        allow = _load_proxy_allow()
        self.assertTrue(
            self._has_named(allow, 'Send'),
            'catalog missing Send; proxy cannot deliver a reply (#425)',
        )

    def test_allow_contains_list_team_members(self) -> None:
        allow = _load_proxy_allow()
        self.assertTrue(
            self._has_named(allow, 'ListTeamMembers'),
            'catalog missing ListTeamMembers (#425 catalog)',
        )

    def test_allow_contains_close_conversation(self) -> None:
        allow = _load_proxy_allow()
        self.assertTrue(
            self._has_named(allow, 'CloseConversation'),
            'catalog missing CloseConversation; proxy cannot terminate '
            'its dialog cleanly (#425 catalog)',
        )


class ProxyCatalogMutationExcludedTest(unittest.TestCase):
    """Mutation tools must not appear — proxy is a reviewer."""

    def test_allow_excludes_write(self) -> None:
        allow = _load_proxy_allow()
        self.assertNotIn(
            'Write', allow,
            'catalog must not contain Write; proxy is a read-only '
            'reviewer (#425 — security boundary)',
        )

    def test_allow_excludes_edit(self) -> None:
        allow = _load_proxy_allow()
        self.assertNotIn(
            'Edit', allow,
            'catalog must not contain Edit; proxy is a read-only '
            'reviewer (#425 — security boundary)',
        )

    def test_allow_excludes_bash(self) -> None:
        allow = _load_proxy_allow()
        self.assertNotIn(
            'Bash', allow,
            'catalog must not contain Bash; proxy must not run '
            'shell commands (#425 — security boundary)',
        )


class ProxyCatalogRecursionExcludedTest(unittest.TestCase):
    def test_allow_excludes_ask_question(self) -> None:
        allow = _load_proxy_allow()
        present = any(
            tool == 'AskQuestion' or tool.endswith('__AskQuestion')
            for tool in allow
        )
        self.assertFalse(
            present,
            'catalog must not contain AskQuestion; proxy escalating to '
            'itself is infinite recursion (#425)',
        )


class ProxyCatalogNoMemoryToolsTest(unittest.TestCase):
    """Memory access is host-side hooks only — no agent-callable tools."""

    def test_allow_excludes_proxy_memory_tools(self) -> None:
        allow = _load_proxy_allow()
        for tool in allow:
            self.assertNotIn(
                'ProxyMemory', tool,
                f'catalog contains unexpected memory tool {tool!r}; '
                f'#425 keeps memory access in host hooks, not tools',
            )


if __name__ == '__main__':
    unittest.main()
