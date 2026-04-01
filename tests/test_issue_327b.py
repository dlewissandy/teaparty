"""Tests for issue #327 follow-up: org catalog is filesystem-only; no YAML registration needed.

Design decision (see issue comment):
- The org-level Skill Catalog is defined entirely by {teaparty_home}/.claude/skills/.
- teaparty.yaml skills: is an agent allowlist, not a catalog registration list.
- _serialize_management_team must never fall back to t.skills (YAML list) for the catalog.

Acceptance criteria:
1. _serialize_management_team returns [] when no discovered_skills are passed — not the YAML list.
2. _serialize_management_team returns the discovered list when passed, regardless of YAML contents.
3. teaparty.yaml skills: comment describes the field as an agent allowlist.
4. proposal.md Skill Discovery section states the catalog is filesystem-only, no registration step.
"""
import os
import tempfile
import unittest


def _make_bridge(teaparty_home, static_dir=None):
    from bridge.server import TeaPartyBridge
    if static_dir is None:
        static_dir = os.path.join(teaparty_home, 'static')
    os.makedirs(static_dir, exist_ok=True)
    return TeaPartyBridge(teaparty_home=teaparty_home, static_dir=static_dir)


def _make_management_team(yaml_skills):
    from orchestrator.config_reader import ManagementTeam
    return ManagementTeam(name='Test')


# ── Criterion 1: no fallback to YAML list ─────────────────────────────────────

class TestManagementTeamSerializerNoYamlFallback(unittest.TestCase):
    """_serialize_management_team must not fall back to t.skills (YAML list)."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.bridge = _make_bridge(self.tmp)

    def test_returns_empty_list_when_discovered_skills_not_passed(self):
        """When no discovered_skills param is given, skills must be [] — not the YAML list.

        The YAML list is an agent allowlist, not the catalog source. Returning it as
        the catalog would show uninstalled skills as if they were available.
        """
        team = _make_management_team(yaml_skills=['sprint-plan', 'audit'])
        result = self.bridge._serialize_management_team(team)
        self.assertEqual(
            result['skills'], [],
            '_serialize_management_team must return [] when discovered_skills is not passed — '
            'the YAML list is an agent allowlist, not the org catalog.',
        )

    def test_yaml_skills_list_does_not_appear_in_catalog_output(self):
        """Skills declared in teaparty.yaml skills: must not appear in the serialized catalog
        unless they are also in the discovered_skills list."""
        team = _make_management_team(yaml_skills=['yaml-only-skill'])
        result = self.bridge._serialize_management_team(team)
        self.assertNotIn(
            'yaml-only-skill', result['skills'],
            'A skill declared only in teaparty.yaml skills: must not appear in the catalog — '
            'the catalog is filesystem-discovered only.',
        )


# ── Criterion 2: discovered list is used as-is ────────────────────────────────

class TestManagementTeamSerializerUsesDiscoveredList(unittest.TestCase):
    """When discovered_skills is passed, it is returned exactly."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.bridge = _make_bridge(self.tmp)

    def test_returns_discovered_skills_regardless_of_yaml_list(self):
        """discovered_skills overrides any YAML-declared list."""
        team = _make_management_team(yaml_skills=['yaml-only'])
        result = self.bridge._serialize_management_team(
            team, discovered_skills=['fs-skill-a', 'fs-skill-b']
        )
        result_names = [s['name'] if isinstance(s, dict) else s for s in result['skills']]
        self.assertEqual(result_names, ['fs-skill-a', 'fs-skill-b'])

    def test_discovered_empty_list_returns_empty_not_yaml(self):
        """An explicit empty discovered list means no skills — not a fallback to YAML."""
        team = _make_management_team(yaml_skills=['yaml-skill'])
        result = self.bridge._serialize_management_team(team, discovered_skills=[])
        self.assertEqual(result['skills'], [],
            'Empty discovered_skills must return [] — not fall back to YAML list.')


# ── Criterion 3: teaparty.yaml skills: comment ────────────────────────────────

class TestTeapartyYamlSkillsComment(unittest.TestCase):
    """teaparty.yaml skills: must be documented as an agent allowlist,
    not as catalog registration."""

    _YAML_PATH = os.path.join(
        os.path.dirname(__file__), '..',
        'docs/proposals/team-configuration/examples/teaparty.yaml',
    )

    def setUp(self):
        with open(self._YAML_PATH) as f:
            self.content = f.read()

    def test_skills_comment_does_not_say_catalog_registration(self):
        """The skills: comment must not describe it as a catalog registration requirement."""
        self.assertNotIn(
            'Catalog registration', self.content,
            'teaparty.yaml skills: must not be described as catalog registration — '
            'it is an agent allowlist. Catalog is filesystem-only.',
        )

    def test_skills_comment_describes_agent_allowlist_or_equivalent(self):
        """The skills: comment must convey that this controls agent access, not catalog display."""
        has_allowlist_framing = (
            'allowlist' in self.content.lower()
            or 'agent' in self.content.lower()
            or 'invoke' in self.content.lower()
        )
        self.assertTrue(
            has_allowlist_framing,
            'teaparty.yaml skills: comment must describe the field in terms of agent access '
            '(allowlist/invoke), not catalog display.',
        )


# ── Criterion 4: proposal.md Skill Discovery section ──────────────────────────

class TestProposalSkillDiscoverySection(unittest.TestCase):
    """proposal.md Skill Discovery section must state catalog is filesystem-only
    with no registration step."""

    _PROPOSAL_PATH = os.path.join(
        os.path.dirname(__file__), '..',
        'docs/proposals/team-configuration/proposal.md',
    )

    def setUp(self):
        with open(self._PROPOSAL_PATH) as f:
            self.content = f.read()

    def test_proposal_does_not_describe_yaml_as_catalog_registration(self):
        """Proposal must not describe teaparty.yaml skills: as a catalog registration list."""
        self.assertNotIn(
            'catalog registration', self.content.lower(),
            'proposal.md must not describe teaparty.yaml skills: as catalog registration — '
            'the catalog is filesystem-only.',
        )

    def test_proposal_states_catalog_is_filesystem_only(self):
        """Proposal must explicitly state that the org catalog comes from the filesystem."""
        has_filesystem_statement = (
            'filesystem' in self.content.lower()
            or '.claude/skills' in self.content
        )
        self.assertTrue(
            has_filesystem_statement,
            'proposal.md must state that the org catalog is filesystem-derived.',
        )

    def test_proposal_describes_yaml_skills_as_allowlist(self):
        """Proposal must describe teaparty.yaml skills: as an agent allowlist."""
        self.assertIn(
            'allowlist', self.content.lower(),
            'proposal.md must describe teaparty.yaml skills: as an agent allowlist.',
        )


if __name__ == '__main__':
    unittest.main()
