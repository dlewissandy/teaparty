"""Tests for issue #256: Agent configuration view — read-only modal from dashboard.

Verifies:
1. format_agent_config produces monospace text matching the design doc format
2. format_agent_config includes all sections: header, Model, Tools, MCP, Hooks, Prompt
3. format_agent_config handles minimal agent data (name only)
4. format_agent_config handles workgroup agents with role and model
5. AgentConfigModal is a ModalScreen with Escape binding to dismiss
6. AgentConfigModal renders formatted config text and read-only footer
7. Agent card click routing maps to agents card_name in action_card_click
8. Agent card items are built from config_reader agent data
"""
import unittest

from projects.POC.tui.screens.agent_config_modal import (
    AgentConfigModal,
    format_agent_config,
)


def _make_agent_config(**kwargs):
    """Create an agent config dict with optional overrides."""
    defaults = dict(
        name='Office Manager',
        role='Team Lead',
        file='.claude/agents/office-manager.md',
        status='active',
        model='claude-opus-4',
        max_turns=25,
        permission_mode='default',
        tools=['Read', 'Glob', 'Grep', 'Bash'],
        disallowed_tools=['Write', 'Edit'],
        mcp_servers=['ask-question'],
        mcp_tools=['mcp__ask-question__AskTeam'],
        hooks=[{'event': 'Stop', 'type': 'agent', 'detail': 'Summarize conversation'}],
        prompt='You are the office manager.',
    )
    defaults.update(kwargs)
    return defaults


class TestFormatAgentConfig(unittest.TestCase):
    """format_agent_config produces monospace text per agent-config-view.md design."""

    def test_header_includes_name_role_file_status(self):
        """Header section shows Agent, Role, File, Status fields."""
        cfg = _make_agent_config()
        text = format_agent_config(cfg)
        self.assertIn('Agent:  Office Manager', text)
        self.assertIn('Role:   Team Lead', text)
        self.assertIn('File:   .claude/agents/office-manager.md', text)
        self.assertIn('Status: active', text)

    def test_model_section_present(self):
        """Model section shows Model, Max turns, Permission mode."""
        cfg = _make_agent_config()
        text = format_agent_config(cfg)
        self.assertIn('Model', text)
        self.assertIn('claude-opus-4', text)
        self.assertIn('25', text)
        self.assertIn('default', text)

    def test_tools_section_shows_allowed_and_disallowed(self):
        """Tools section lists allowed and disallowed tools."""
        cfg = _make_agent_config()
        text = format_agent_config(cfg)
        self.assertIn('Allowed:', text)
        self.assertIn('  Read', text)
        self.assertIn('  Bash', text)
        self.assertIn('Disallowed:', text)
        self.assertIn('  Write', text)
        self.assertIn('  Edit', text)

    def test_mcp_section_shows_servers_and_tools(self):
        """MCP Servers section lists servers and MCP tools."""
        cfg = _make_agent_config()
        text = format_agent_config(cfg)
        self.assertIn('MCP Servers', text)
        self.assertIn('  ask-question', text)
        self.assertIn('MCP Tools:', text)
        self.assertIn('  mcp__ask-question__AskTeam', text)

    def test_hooks_section_shows_hook_entries(self):
        """Hooks section lists hook event and detail."""
        cfg = _make_agent_config()
        text = format_agent_config(cfg)
        self.assertIn('Hooks', text)
        self.assertIn('Stop', text)
        self.assertIn('Summarize conversation', text)

    def test_prompt_section_shows_system_prompt(self):
        """System Prompt section shows the agent's prompt text."""
        cfg = _make_agent_config()
        text = format_agent_config(cfg)
        self.assertIn('System Prompt', text)
        self.assertIn('You are the office manager.', text)

    def test_sections_use_box_drawing_separators(self):
        """Section headers use box-drawing characters per design doc."""
        cfg = _make_agent_config()
        text = format_agent_config(cfg)
        # Design doc uses "── Model ──────" style headers
        self.assertIn('──', text)
        self.assertIn('── Model ', text)
        self.assertIn('── Tools ', text)

    def test_minimal_agent_name_only(self):
        """An agent with just a name still produces valid output."""
        cfg = dict(name='auditor')
        text = format_agent_config(cfg)
        self.assertIn('Agent:  auditor', text)
        # Should not crash; sections with no data show appropriate fallbacks
        self.assertIn('Model', text)

    def test_workgroup_agent_with_role_and_model(self):
        """A workgroup agent dict (name, role, model) renders correctly."""
        cfg = dict(name='Architect', role='specialist', model='claude-opus-4')
        text = format_agent_config(cfg)
        self.assertIn('Agent:  Architect', text)
        self.assertIn('Role:   specialist', text)
        self.assertIn('claude-opus-4', text)

    def test_empty_tools_shows_none(self):
        """When no tools are configured, shows (none)."""
        cfg = _make_agent_config(tools=[], disallowed_tools=[])
        text = format_agent_config(cfg)
        self.assertIn('Allowed:', text)
        self.assertIn('(none)', text)

    def test_empty_mcp_shows_none(self):
        """When no MCP servers, shows (none)."""
        cfg = _make_agent_config(mcp_servers=[], mcp_tools=[])
        text = format_agent_config(cfg)
        self.assertIn('MCP Servers', text)
        self.assertIn('(none)', text)

    def test_empty_hooks_shows_none(self):
        """When no hooks, shows (none)."""
        cfg = _make_agent_config(hooks=[])
        text = format_agent_config(cfg)
        self.assertIn('Hooks', text)
        # After the Hooks header, should show (none)
        hooks_idx = text.index('Hooks')
        prompt_idx = text.index('System Prompt')
        hooks_section = text[hooks_idx:prompt_idx]
        self.assertIn('(none)', hooks_section)

    def test_no_prompt_shows_none(self):
        """When no prompt is set, shows (none)."""
        cfg = _make_agent_config(prompt='')
        text = format_agent_config(cfg)
        prompt_idx = text.index('System Prompt')
        prompt_section = text[prompt_idx:]
        self.assertIn('(none)', prompt_section)


class TestAgentConfigModal(unittest.TestCase):
    """AgentConfigModal is a ModalScreen showing read-only agent config."""

    def test_modal_is_modal_screen(self):
        """AgentConfigModal inherits from ModalScreen."""
        from textual.screen import ModalScreen
        self.assertTrue(issubclass(AgentConfigModal, ModalScreen))

    def test_modal_accepts_agent_config(self):
        """AgentConfigModal constructor accepts an agent config dict."""
        cfg = _make_agent_config()
        modal = AgentConfigModal(cfg)
        self.assertEqual(modal._agent_config, cfg)

    def test_modal_has_escape_binding(self):
        """AgentConfigModal has an Escape key binding for dismissal."""
        bindings = {b.key for b in AgentConfigModal.BINDINGS}
        self.assertIn('escape', bindings)

    def test_modal_stores_formatted_text(self):
        """AgentConfigModal pre-formats the config text."""
        cfg = _make_agent_config()
        modal = AgentConfigModal(cfg)
        # The modal should use format_agent_config
        expected = format_agent_config(cfg)
        self.assertEqual(modal._formatted_text, expected)


class TestAgentCardClickRouting(unittest.TestCase):
    """Agent card clicks open the agent config modal."""

    def test_dashboard_screen_handles_agents_card_name(self):
        """action_card_click handles card_name='agents' without error."""
        import inspect
        from projects.POC.tui.screens.dashboard_screen import DashboardScreen
        source = inspect.getsource(DashboardScreen.action_card_click)
        # The method should reference 'agents' as a handled card name
        self.assertIn("'agents'", source)


class TestBuildAgentItems(unittest.TestCase):
    """Agent card items are built from config_reader data."""

    def test_build_management_agent_items_from_name_list(self):
        """Management-level agents (list of strings) produce card items."""
        from projects.POC.tui.screens.dashboard_screen import build_agent_items
        agents = ['office-manager', 'auditor', 'researcher']
        items = build_agent_items(agents)
        self.assertEqual(len(items), 3)
        self.assertEqual(items[0].label, 'office-manager')
        self.assertEqual(items[1].label, 'auditor')

    def test_build_workgroup_agent_items_from_dict_list(self):
        """Workgroup-level agents (list of dicts) produce card items with role."""
        from projects.POC.tui.screens.dashboard_screen import build_agent_items
        agents = [
            {'name': 'Coding Lead', 'role': 'team-lead', 'model': 'claude-sonnet-4'},
            {'name': 'Architect', 'role': 'specialist', 'model': 'claude-opus-4'},
        ]
        items = build_agent_items(agents)
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0].label, 'Coding Lead')
        self.assertIn('team-lead', items[0].detail)

    def test_build_agent_items_empty_list(self):
        """Empty agent list produces no items."""
        from projects.POC.tui.screens.dashboard_screen import build_agent_items
        items = build_agent_items([])
        self.assertEqual(items, [])

    def test_agent_item_data_carries_config_dict(self):
        """Each agent item's data dict carries the agent config for modal display."""
        from projects.POC.tui.screens.dashboard_screen import build_agent_items
        agents = ['office-manager']
        items = build_agent_items(agents)
        self.assertIsInstance(items[0].data, dict)
        self.assertEqual(items[0].data['name'], 'office-manager')

    def test_workgroup_agent_item_data_carries_full_dict(self):
        """Workgroup agent items carry name, role, model in data."""
        from projects.POC.tui.screens.dashboard_screen import build_agent_items
        agents = [{'name': 'Architect', 'role': 'specialist', 'model': 'claude-opus-4'}]
        items = build_agent_items(agents)
        self.assertEqual(items[0].data['name'], 'Architect')
        self.assertEqual(items[0].data['role'], 'specialist')
        self.assertEqual(items[0].data['model'], 'claude-opus-4')


if __name__ == '__main__':
    unittest.main()
