"""Tests for issue #382: Clicking human participant opens manager chat instead of proxy chat.

Acceptance criteria:
1. Clicking a human participant card on the global config page opens the proxy chat for that human
2. Clicking a human participant card on the project config page does the same
3. The office manager chat is unaffected (manager card unchanged)
4. Behavior is consistent with how the manager card constructs and routes its conversation ID
"""
import re
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).parent.parent
_CONFIG_HTML = _REPO_ROOT / 'bridge' / 'static' / 'config.html'


def _read_config_html() -> str:
    return _CONFIG_HTML.read_text()


class TestGlobalConfigHumanParticipantClickHandler(unittest.TestCase):
    """Global config view: human participant cards must open proxy chat, not OM chat."""

    def test_global_human_participant_does_not_pass_om_conv_id(self):
        """Human participant forEach in renderGlobal must not pass omConvId to openChat."""
        source = _read_config_html()
        # Find the renderGlobal function body
        render_global_match = re.search(
            r'async function renderGlobal\(\)(.*?)^async function ',
            source,
            re.DOTALL | re.MULTILINE,
        )
        self.assertIsNotNone(render_global_match, 'renderGlobal function not found in config.html')
        render_global = render_global_match.group(1)

        # The humans forEach must not use openChat(omConvId) — that routes to the office manager
        self.assertNotIn(
            "openChat(omConvId)",
            render_global,
            "renderGlobal humans forEach must not call openChat(omConvId) — "
            "that opens the office manager chat, not the proxy chat",
        )

    def test_global_human_participant_has_role_select(self):
        """Human participant forEach in renderGlobal must render a role-select dropdown."""
        source = _read_config_html()
        render_global_match = re.search(
            r'async function renderGlobal\(\)(.*?)^async function ',
            source,
            re.DOTALL | re.MULTILINE,
        )
        self.assertIsNotNone(render_global_match, 'renderGlobal function not found in config.html')
        render_global = render_global_match.group(1)

        self.assertIn(
            "role-select",
            render_global,
            "renderGlobal humans forEach must render a role-select dropdown",
        )

    def test_global_human_participant_calls_setParticipantRole(self):
        """Human participant forEach in renderGlobal must call setParticipantRole on change."""
        source = _read_config_html()
        render_global_match = re.search(
            r'async function renderGlobal\(\)(.*?)^async function ',
            source,
            re.DOTALL | re.MULTILINE,
        )
        self.assertIsNotNone(render_global_match, 'renderGlobal function not found in config.html')
        render_global = render_global_match.group(1)

        self.assertIn(
            "setParticipantRole",
            render_global,
            "renderGlobal humans forEach must call setParticipantRole "
            "(human cards use role selection, not chat navigation)",
        )


class TestProjectConfigHumanParticipantClickHandler(unittest.TestCase):
    """Project config view: human participant cards must open proxy chat, not OM chat."""

    def test_project_human_participant_does_not_pass_om_conv_id(self):
        """Human participant forEach in renderProject must not pass omConvId to openChat."""
        source = _read_config_html()
        render_project_match = re.search(
            r'async function renderProject\(slug\)(.*?)^async function ',
            source,
            re.DOTALL | re.MULTILINE,
        )
        self.assertIsNotNone(render_project_match, 'renderProject function not found in config.html')
        render_project = render_project_match.group(1)

        self.assertNotIn(
            "openChat(omConvId)",
            render_project,
            "renderProject humans forEach must not call openChat(omConvId) — "
            "that opens the office manager chat, not the proxy chat",
        )

    def test_project_human_participant_has_role_select(self):
        """Human participant forEach in renderProject must render a role-select dropdown."""
        source = _read_config_html()
        render_project_match = re.search(
            r'async function renderProject\(slug\)(.*?)^async function ',
            source,
            re.DOTALL | re.MULTILINE,
        )
        self.assertIsNotNone(render_project_match, 'renderProject function not found in config.html')
        render_project = render_project_match.group(1)

        self.assertIn(
            "role-select",
            render_project,
            "renderProject humans forEach must render a role-select dropdown",
        )

    def test_project_human_participant_calls_setParticipantRole(self):
        """Human participant forEach in renderProject must call setParticipantRole on change."""
        source = _read_config_html()
        render_project_match = re.search(
            r'async function renderProject\(slug\)(.*?)^async function ',
            source,
            re.DOTALL | re.MULTILINE,
        )
        self.assertIsNotNone(render_project_match, 'renderProject function not found in config.html')
        render_project = render_project_match.group(1)

        self.assertIn(
            "setParticipantRole",
            render_project,
            "renderProject humans forEach must call setParticipantRole "
            "(human cards use role selection, not chat navigation)",
        )


class TestManagerCardUnaffected(unittest.TestCase):
    """Manager card click handlers must remain unchanged."""

    def test_global_manager_card_still_uses_om_conv_id(self):
        """The office manager card in renderGlobal must still use omConvId."""
        source = _read_config_html()
        render_global_match = re.search(
            r'async function renderGlobal\(\)(.*?)^async function ',
            source,
            re.DOTALL | re.MULTILINE,
        )
        self.assertIsNotNone(render_global_match, 'renderGlobal function not found in config.html')
        render_global = render_global_match.group(1)

        # The OM (lead) card must still route to omConvId — fixing human cards must not break this
        self.assertIn(
            "omConvId",
            render_global,
            "The office manager card in renderGlobal must still reference omConvId",
        )
        self.assertIn(
            "m.lead",
            render_global,
            "The office manager (lead) card must still be present in renderGlobal",
        )

    def test_project_manager_card_still_uses_manager_conv_id(self):
        """The manager card in renderProject must still use managerConvId."""
        source = _read_config_html()
        render_project_match = re.search(
            r'async function renderProject\(slug\)(.*?)^async function ',
            source,
            re.DOTALL | re.MULTILINE,
        )
        self.assertIsNotNone(render_project_match, 'renderProject function not found in config.html')
        render_project = render_project_match.group(1)

        self.assertIn(
            "managerConvId",
            render_project,
            "renderProject manager card must still route to managerConvId",
        )


class TestHumanCardsUseRoleSelectNotChat(unittest.TestCase):
    """Human participant cards must use role-select dropdowns, not chat navigation."""

    def test_manager_card_still_uses_manager_conv_id_construction(self):
        """Project manager card must still use 'manager:' + team.decider for chat."""
        source = _read_config_html()

        self.assertIn(
            "'manager:' + team.decider",
            source,
            "Manager card must use 'manager:' + team.decider (baseline pattern unchanged)",
        )

    def test_human_cards_do_not_use_openChat(self):
        """Human participant cards must not call openChat — they use role-select instead."""
        source = _read_config_html()

        # Extract the humans forEach blocks and verify they don't call openChat
        humans_blocks = re.findall(
            r'\((?:m|team)\.humans \|\| \[\]\)\.forEach\(function\(h\)\s*\{(.*?)\}\);',
            source,
            re.DOTALL,
        )
        self.assertGreater(len(humans_blocks), 0, 'Must find at least one humans forEach block')
        for block in humans_blocks:
            self.assertNotIn(
                'openChat',
                block,
                'Human participant forEach must not call openChat — uses role-select instead',
            )
