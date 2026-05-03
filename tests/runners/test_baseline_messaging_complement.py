"""Regression: every agent gets the messaging-primitive minimum complement.

A dispatch-participating agent needs four MCP tools to function:
  * ``mcp__teaparty-config__Send`` — to delegate or reply.
  * ``mcp__teaparty-config__AskQuestion`` — to escalate to proxy/human.
  * ``mcp__teaparty-config__ListTeamMembers`` — for leads to find their team.
  * ``mcp__teaparty-config__CloseConversation`` — for leads to close threads.

Before this change, these were hand-replicated in each lead's per-agent
``settings.yaml`` (9 lead files).  One accidental edit silently broke
a lead's ability to send messages, find team members, ask questions,
or close threads.  This test pins the structural guarantee: the
baseline injection adds the messaging complement to every agent at
launch, regardless of what the per-agent settings declare.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from teaparty.runners.launcher import (
    BASELINE_ALLOW_RULES,
    _inject_baseline_deny,
)


MESSAGING_PRIMITIVES = (
    'mcp__teaparty-config__Send',
    'mcp__teaparty-config__AskQuestion',
    'mcp__teaparty-config__ListTeamMembers',
    'mcp__teaparty-config__CloseConversation',
)


class BaselineMessagingComplementTest(unittest.TestCase):
    """The four messaging primitives are universal allow-list entries."""

    def test_baseline_includes_each_messaging_primitive(self) -> None:
        """The constant itself enumerates the four tools."""
        for tool in MESSAGING_PRIMITIVES:
            self.assertIn(
                tool, BASELINE_ALLOW_RULES,
                f'{tool} must be in BASELINE_ALLOW_RULES — every '
                'dispatch-participating agent needs it',
            )

    def test_empty_settings_get_messaging_primitives(self) -> None:
        """An agent with no per-agent settings still gets the complement."""
        settings: dict = {}
        _inject_baseline_deny(settings)
        allow = settings['permissions']['allow']
        for tool in MESSAGING_PRIMITIVES:
            self.assertIn(tool, allow)

    def test_lead_with_only_specialty_tools_still_gets_messaging(self) -> None:
        """The reported failure mode: a specialist's settings.yaml that
        omits the messaging tools no longer leaves the agent stranded.
        """
        settings = {
            'permissions': {
                'allow': [
                    'Read', 'Write', 'Glob',
                    'mcp__teaparty-config__arxiv_search',
                ],
            },
        }
        _inject_baseline_deny(settings)
        allow = settings['permissions']['allow']
        for tool in MESSAGING_PRIMITIVES:
            self.assertIn(tool, allow)
        # Specialty tools are preserved.
        self.assertIn('mcp__teaparty-config__arxiv_search', allow)

    def test_existing_messaging_entries_are_not_duplicated(self) -> None:
        """A lead whose settings.yaml already lists the messaging tools
        sees them once each in the merged allow — no doubles.
        """
        settings = {
            'permissions': {
                'allow': list(MESSAGING_PRIMITIVES) + ['Bash'],
            },
        }
        _inject_baseline_deny(settings)
        allow = settings['permissions']['allow']
        for tool in MESSAGING_PRIMITIVES:
            self.assertEqual(
                allow.count(tool), 1,
                f'{tool} should appear exactly once after dedup',
            )


if __name__ == '__main__':
    unittest.main()
