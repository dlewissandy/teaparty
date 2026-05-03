"""Regression: ``--tools`` derivation must not force ToolSearch.

A long-running implementation injected ``ToolSearch`` into every
agent's ``--tools``, regardless of the agent's
``permissions.allow``.  ToolSearch can fetch any tool's schema by
name, so agents could discover (and then attempt to call) tools
outside their whitelist.  The call hit Claude Code's permission
prompt and stalled the agent — the joke-book research-lead failure
mode.

The fix: ``derive_tools_from_settings`` returns exactly the bare
names found in the allow list, with no ToolSearch backdoor.  Agents
that genuinely need tool discovery must place ``ToolSearch`` in
their own ``permissions.allow``.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from teaparty.runners.launcher import derive_tools_from_settings


class DeriveToolsTest(unittest.TestCase):
    """The whitelist is the whole story; ToolSearch is not auto-injected."""

    def test_research_lead_does_not_get_toolsearch(self) -> None:
        """The reported failure path: a workgroup-lead's allow list does not
        include ToolSearch, and the derived ``--tools`` must not either.
        """
        allow = [
            'mcp__teaparty-config__Send',
            'mcp__teaparty-config__ListTeamMembers',
            'mcp__teaparty-config__CloseConversation',
            'mcp__teaparty-config__AskQuestion',
            'Bash',
        ]
        tools = derive_tools_from_settings(allow)
        self.assertIsNotNone(tools)
        self.assertNotIn('ToolSearch', tools.split(','))

    def test_explicit_toolsearch_is_preserved(self) -> None:
        """An agent that explicitly opts into discovery still gets it."""
        allow = ['Read', 'Write', 'ToolSearch']
        tools = derive_tools_from_settings(allow)
        self.assertIn('ToolSearch', tools.split(','))

    def test_strips_permission_pattern_to_bare_name(self) -> None:
        """``Write(/path/**)`` becomes ``Write`` for the --tools list."""
        allow = ['Write(/path/**)', 'Edit(/path/**)', 'Read']
        tools = derive_tools_from_settings(allow).split(',')
        self.assertEqual(tools, ['Write', 'Edit', 'Read'])

    def test_dedupes_repeated_names(self) -> None:
        """Two patterns for the same tool collapse to one bare name."""
        allow = ['Write(/a/**)', 'Write(/b/**)', 'Read']
        tools = derive_tools_from_settings(allow).split(',')
        self.assertEqual(tools, ['Write', 'Read'])

    def test_empty_allow_returns_none(self) -> None:
        """Without any allow entries (and no frontmatter fallback), no list."""
        self.assertIsNone(derive_tools_from_settings([]))

    def test_falls_back_to_frontmatter_tools(self) -> None:
        """Pre-migration agents still get a tools list via frontmatter."""
        tools = derive_tools_from_settings([], frontmatter_tools='Read, Write,Edit')
        self.assertEqual(tools, 'Read,Write,Edit')

    def test_lead_allow_list_round_trip(self) -> None:
        """A workgroup-lead's actual allow list (from the live joke-book
        config) round-trips to a clean comma-joined --tools without
        ToolSearch contamination.
        """
        allow = [
            'mcp__teaparty-config__Send',
            'mcp__teaparty-config__ListTeamMembers',
            'mcp__teaparty-config__CloseConversation',
            'mcp__teaparty-config__AskQuestion',
            'Bash',
            'Read(*/.claude/**)',
            'Read(*/.claude/skills/**)',
            'Skill',
        ]
        tools = derive_tools_from_settings(allow)
        names = tools.split(',')
        # Whitelist names round-trip as bare names, exactly once each,
        # in the order the allow list specifies.
        self.assertEqual(names, [
            'mcp__teaparty-config__Send',
            'mcp__teaparty-config__ListTeamMembers',
            'mcp__teaparty-config__CloseConversation',
            'mcp__teaparty-config__AskQuestion',
            'Bash',
            'Read',
            'Skill',
        ])
        # No ToolSearch.
        self.assertNotIn('ToolSearch', names)
        # No specialist tools that aren't in the allow list.
        for forbidden in (
            'mcp__teaparty-config__semantic_scholar_search',
            'mcp__teaparty-config__arxiv_search',
            'mcp__teaparty-config__pubmed_search',
            'mcp__teaparty-config__patent_search_uspto',
            'mcp__teaparty-config__youtube_transcript',
        ):
            self.assertNotIn(forbidden, names)


if __name__ == '__main__':
    unittest.main()
