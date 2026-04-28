"""Regression: ``_load_agent_tools`` reads settings.yaml, not just frontmatter.

The MCP middleware's ``tools/list`` filter calls ``_load_agent_tools``
to discover what an agent is allowed to see in its tool catalog.
``_load_agent_tools`` previously read only the frontmatter ``tools:``
field — but agents have migrated to ``permissions.allow`` in
``settings.yaml``, which is also where the launcher's ``--tools``
derivation reads from.  So the MCP filter saw an empty whitelist for
every migrated agent and fell through to "pass-through, all tools" —
exactly the leak that let research-lead see ``semantic_scholar_search``.

This test pins the contract: the function reads settings.yaml first,
falls back to frontmatter, and returns ``None`` only when neither
declares an allow list.
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from teaparty.mcp.server.main import _load_agent_tools


class LoadAgentToolsSettingsTest(unittest.TestCase):
    """``_load_agent_tools`` honors the actual whitelist source."""

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix='load-tools-')
        self.teaparty_home = os.path.join(self._tmp, '.teaparty')
        self.agent_dir = os.path.join(
            self.teaparty_home, 'management', 'agents', 'research-lead',
        )
        os.makedirs(self.agent_dir)
        # Agents need an agent.md to be discovered at all.
        with open(os.path.join(self.agent_dir, 'agent.md'), 'w') as f:
            f.write('---\nname: research-lead\n---\nbody\n')

    def tearDown(self) -> None:
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _resolve_to_test_home(self):
        """Patch ``_resolve_teaparty_home`` to point at the temp dir."""
        return patch(
            'teaparty.mcp.server.main._resolve_teaparty_home',
            return_value=self.teaparty_home,
        )

    def _write_settings(self, allow: list[str]) -> None:
        path = os.path.join(self.agent_dir, 'settings.yaml')
        import yaml
        with open(path, 'w') as f:
            yaml.safe_dump({'permissions': {'allow': allow}}, f)

    # ── The reported bug ──────────────────────────────────────────────────

    def test_settings_yaml_is_the_primary_source(self) -> None:
        """When settings.yaml declares permissions.allow, that's the whitelist.

        The agent has no frontmatter ``tools:`` field — the legacy code
        path returned None and the filter passed through.  After the
        fix, the function reads settings.yaml and returns the allow set.
        """
        self._write_settings([
            'mcp__teaparty-config__Send',
            'mcp__teaparty-config__ListTeamMembers',
            'mcp__teaparty-config__AskQuestion',
            'mcp__teaparty-config__CloseConversation',
            'Bash',
        ])
        with self._resolve_to_test_home():
            tools = _load_agent_tools('research-lead', scope='management')
        self.assertIsNotNone(tools)
        # Bare names (mcp__ prefix stripped) for the MCP list_tools filter.
        self.assertEqual(tools, {'Send', 'ListTeamMembers', 'AskQuestion',
                                  'CloseConversation', 'Bash'})

    def test_specialist_tools_not_in_allow_are_filtered(self) -> None:
        """The specific failure: a research-lead's allow list does not
        include ``semantic_scholar_search`` etc.  After the fix, those
        names do NOT appear in the returned set.
        """
        self._write_settings([
            'mcp__teaparty-config__Send',
            'mcp__teaparty-config__AskQuestion',
        ])
        with self._resolve_to_test_home():
            tools = _load_agent_tools('research-lead', scope='management')
        for forbidden in (
            'semantic_scholar_search',
            'arxiv_search',
            'pubmed_search',
            'patent_search_uspto',
            'youtube_transcript',
        ):
            self.assertNotIn(forbidden, tools)

    def test_permission_patterns_strip_to_bare_names(self) -> None:
        """``Write(/path/**)`` becomes ``Write`` for the filter."""
        self._write_settings([
            'Write(/some/path/**)',
            'Edit(/another/**)',
            'Read',
        ])
        with self._resolve_to_test_home():
            tools = _load_agent_tools('research-lead', scope='management')
        self.assertEqual(tools, {'Write', 'Edit', 'Read'})

    # ── Fallback to frontmatter ────────────────────────────────────────────

    def test_falls_back_to_frontmatter_tools(self) -> None:
        """Agents not yet migrated still work via the frontmatter field."""
        # Replace agent.md with one that has a tools: field, no settings.yaml.
        with open(os.path.join(self.agent_dir, 'agent.md'), 'w') as f:
            f.write(
                '---\n'
                'name: research-lead\n'
                'tools: Read, Write, Bash\n'
                '---\nbody\n',
            )
        with self._resolve_to_test_home():
            tools = _load_agent_tools('research-lead', scope='management')
        self.assertEqual(tools, {'Read', 'Write', 'Bash'})

    def test_settings_takes_precedence_over_frontmatter(self) -> None:
        """When both are present, settings.yaml wins (it's the migration target)."""
        with open(os.path.join(self.agent_dir, 'agent.md'), 'w') as f:
            f.write(
                '---\n'
                'name: research-lead\n'
                'tools: Read, Write\n'
                '---\nbody\n',
            )
        self._write_settings(['Bash', 'Edit'])
        with self._resolve_to_test_home():
            tools = _load_agent_tools('research-lead', scope='management')
        self.assertEqual(tools, {'Bash', 'Edit'})

    def test_no_allow_anywhere_returns_none(self) -> None:
        """Neither settings nor frontmatter → pass-through is the only sane default."""
        with self._resolve_to_test_home():
            tools = _load_agent_tools('research-lead', scope='management')
        self.assertIsNone(tools)

    def test_missing_agent_returns_none(self) -> None:
        """Unknown agent → pass-through (caller decides what that means)."""
        with self._resolve_to_test_home():
            tools = _load_agent_tools('nonexistent', scope='management')
        self.assertIsNone(tools)


if __name__ == '__main__':
    unittest.main()
