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

    def test_global_human_participant_uses_proxy_conv_id_prefix(self):
        """Human participant forEach in renderGlobal must construct a proxy: conversation ID."""
        source = _read_config_html()
        render_global_match = re.search(
            r'async function renderGlobal\(\)(.*?)^async function ',
            source,
            re.DOTALL | re.MULTILINE,
        )
        self.assertIsNotNone(render_global_match, 'renderGlobal function not found in config.html')
        render_global = render_global_match.group(1)

        # The humans forEach must use 'proxy:' prefix (matching how manager card uses 'manager:')
        self.assertIn(
            "proxy:",
            render_global,
            "renderGlobal humans forEach must construct a proxy: conversation ID "
            "(analogous to how manager card uses 'manager:' + decider)",
        )

    def test_global_human_participant_onclick_uses_proxy_prefix_with_h_name(self):
        """Human participant forEach in renderGlobal must use 'proxy:' + h.name in the onclick."""
        source = _read_config_html()
        render_global_match = re.search(
            r'async function renderGlobal\(\)(.*?)^async function ',
            source,
            re.DOTALL | re.MULTILINE,
        )
        self.assertIsNotNone(render_global_match, 'renderGlobal function not found in config.html')
        render_global = render_global_match.group(1)

        self.assertIn(
            "'proxy:' + h.name",
            render_global,
            "renderGlobal humans forEach must use 'proxy:' + h.name to construct the conv ID "
            "(identical pattern to manager card using 'manager:' + team.decider)",
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

    def test_project_human_participant_uses_proxy_conv_id_prefix(self):
        """Human participant forEach in renderProject must construct a proxy: conversation ID."""
        source = _read_config_html()
        render_project_match = re.search(
            r'async function renderProject\(slug\)(.*?)^async function ',
            source,
            re.DOTALL | re.MULTILINE,
        )
        self.assertIsNotNone(render_project_match, 'renderProject function not found in config.html')
        render_project = render_project_match.group(1)

        self.assertIn(
            "proxy:",
            render_project,
            "renderProject humans forEach must construct a proxy: conversation ID",
        )

    def test_project_human_participant_onclick_uses_proxy_prefix_with_h_name(self):
        """Human participant forEach in renderProject must use 'proxy:' + h.name in the onclick."""
        source = _read_config_html()
        render_project_match = re.search(
            r'async function renderProject\(slug\)(.*?)^async function ',
            source,
            re.DOTALL | re.MULTILINE,
        )
        self.assertIsNotNone(render_project_match, 'renderProject function not found in config.html')
        render_project = render_project_match.group(1)

        self.assertIn(
            "'proxy:' + h.name",
            render_project,
            "renderProject humans forEach must use 'proxy:' + h.name to construct the conv ID",
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
            "Office Manager",
            render_global,
            "The office manager card must still be present in renderGlobal",
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


class TestProxyConvIdShapeMatchesManagerPattern(unittest.TestCase):
    """Proxy conv ID construction must mirror how the manager card constructs its ID."""

    def test_proxy_conv_id_construction_mirrors_manager_conv_id_construction(self):
        """Both manager and human card onclick handlers must use string concatenation with a
        colon-prefixed identifier: 'manager:' + decider for manager, 'proxy:' + h.name for human.
        """
        source = _read_config_html()

        # Manager card uses: 'manager:' + team.decider
        self.assertIn(
            "'manager:' + team.decider",
            source,
            "Manager card must use 'manager:' + team.decider (baseline pattern unchanged)",
        )

        # Human card must use analogous pattern: 'proxy:' + h.name
        self.assertIn(
            "'proxy:' + h.name",
            source,
            "Human participant cards must use 'proxy:' + h.name — "
            "identical construction to manager card using 'manager:' + team.decider",
        )
