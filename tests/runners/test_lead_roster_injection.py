"""Regression: a lead's agent.md gets the team roster appended at compose time.

A lead's first action is delegation, which requires knowing who is on
the team.  The previous design told leads to call ``ListTeamMembers``
on every dispatch; in the live joke-book run, ``research-lead``
skipped that call and went straight to Write.  Inlining the roster in
the system prompt removes that off-ramp.

This file pins:

1. The renderer produces a ``## Your team`` block for an agent that
   ``derive_team_roster`` recognizes as a lead.
2. The renderer is a no-op for agents that are not leads (specialists,
   unknown names) — the body is returned unchanged.
3. Bulk-applied prompt invariant: no lead agent.md still says ``You
   hold only the team-comm tools`` (the prior wording was wrong —
   leads have Read/Glob/Grep/Write/Edit/Bash for inspection and
   assembly).  This pin catches a partial revert that leaves some
   files updated and others stale.
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from teaparty.runners.launcher import (
    _agent_md_with_roster,
    _render_team_roster_block,
)


class _StubMember:
    def __init__(self, name: str, role: str = '', description: str = ''):
        self.name = name
        self.role = role
        self.description = description


class _StubRoster:
    def __init__(self, lead: str, members: list):
        self.lead = lead
        self.members = members


class RosterRendererTest(unittest.TestCase):
    """``_render_team_roster_block`` formats members tightly."""

    def test_lead_with_members_produces_block(self) -> None:
        """Mock ``derive_team_roster`` to return a known team."""
        from teaparty.config import roster as _roster_mod

        original = _roster_mod.derive_team_roster
        _roster_mod.derive_team_roster = lambda name, home: _StubRoster(
            lead=name,
            members=[
                _StubMember('researcher', 'workgroup-agent', 'Academic + general web research'),
                _StubMember('web-researcher', 'workgroup-agent', 'Current sources, news, blogs'),
                _StubMember('arxiv-researcher', 'workgroup-agent', 'arXiv papers'),
            ],
        )
        try:
            block = _render_team_roster_block(
                agent_name='research-lead',
                scope='management',
                teaparty_home='/tmp/_test_home',
            )
        finally:
            _roster_mod.derive_team_roster = original

        self.assertIn('## Your team', block)
        self.assertIn('researcher', block)
        self.assertIn('web-researcher', block)
        self.assertIn('arxiv-researcher', block)
        self.assertIn('Academic + general web research', block)
        # Every line carries weight — no trailing chatter beyond the
        # one-line "do not call ListTeamMembers" reminder.
        self.assertIn('Send to a member by name', block)

    def test_specialist_returns_empty(self) -> None:
        """A non-lead name returns an empty block — caller appends nothing."""
        from teaparty.config import roster as _roster_mod
        original = _roster_mod.derive_team_roster
        _roster_mod.derive_team_roster = lambda name, home: None
        try:
            block = _render_team_roster_block(
                agent_name='researcher',
                scope='management',
                teaparty_home='/tmp/_test_home',
            )
        finally:
            _roster_mod.derive_team_roster = original
        self.assertEqual(block, '')

    def test_lookup_failure_returns_empty(self) -> None:
        """Compose must not crash when roster derivation fails."""
        from teaparty.config import roster as _roster_mod
        original = _roster_mod.derive_team_roster

        def _boom(name, home):
            raise FileNotFoundError('no config')

        _roster_mod.derive_team_roster = _boom
        try:
            block = _render_team_roster_block(
                agent_name='research-lead',
                scope='management',
                teaparty_home='/tmp/_test_home',
            )
        finally:
            _roster_mod.derive_team_roster = original
        self.assertEqual(block, '')

    def test_agent_md_with_roster_appends_block(self) -> None:
        """Body is preserved; roster lands after the role text."""
        from teaparty.config import roster as _roster_mod
        original = _roster_mod.derive_team_roster
        _roster_mod.derive_team_roster = lambda name, home: _StubRoster(
            lead=name,
            members=[_StubMember('alice', 'workgroup-agent', 'cap A')],
        )
        try:
            body = (
                '---\nname: research-lead\n---\n'
                'You are the lead of the **Research** workgroup.\n'
            )
            updated = _agent_md_with_roster(
                body,
                agent_name='research-lead',
                scope='management',
                teaparty_home='/tmp/_test_home',
            )
        finally:
            _roster_mod.derive_team_roster = original

        # Original body is preserved verbatim.
        self.assertTrue(updated.startswith(body))
        # Roster appears at the end.
        self.assertIn('## Your team', updated)
        self.assertIn('alice', updated)


class LeadAgentMdInvariantTest(unittest.TestCase):
    """Source-level pin against partial reverts of the prompt rewrite."""

    def test_no_lead_agent_md_says_only_team_comm(self) -> None:
        """The misleading 'You hold only the team-comm tools' must stay gone.

        Leads have Read/Glob/Grep/Write/Edit/Bash — required for
        inspection and assembly.  The earlier wording was wrong; a
        partial revert that leaves the wrong prose in even one file
        re-introduces the catalog ↔ role mismatch that hid the
        delegation-skip bug.
        """
        repo_root = Path(__file__).parent.parent.parent
        leads = []
        for scope_dir in ('.teaparty/management/agents',
                          '.teaparty/project/agents'):
            base = repo_root / scope_dir
            if not base.exists():
                continue
            for child in base.iterdir():
                if not child.is_dir():
                    continue
                if '-lead' not in child.name:
                    continue
                md = child / 'agent.md'
                if md.exists():
                    leads.append(md)
        self.assertGreater(
            len(leads), 5,
            'expected to find multiple lead agent.md files',
        )
        offenders = [
            str(md) for md in leads
            if 'You hold only the team-comm tools' in md.read_text()
        ]
        self.assertEqual(
            offenders, [],
            'these lead agent.md files still contain the misleading '
            '"You hold only the team-comm tools" wording: '
            f'{offenders}',
        )


if __name__ == '__main__':
    unittest.main()
