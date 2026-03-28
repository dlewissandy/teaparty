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
import os
import tempfile
import unittest

from projects.POC.tui.screens.agent_config_modal import (
    AgentConfigModal,
    enrich_agent_config,
    format_agent_config,
    read_agent_file,
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


    def test_modal_has_modify_via_chat_button(self):
        """AgentConfigModal has a 'Modify via Chat' button for office manager."""
        import inspect
        source = inspect.getsource(AgentConfigModal)
        self.assertIn('Modify via Chat', source)
        self.assertIn('agent-config-modify-btn', source)

    def test_modal_has_close_button(self):
        """AgentConfigModal has a Close button."""
        import inspect
        source = inspect.getsource(AgentConfigModal)
        self.assertIn('agent-config-close-btn', source)


class TestReadAgentFile(unittest.TestCase):
    """read_agent_file extracts frontmatter and prompt from .md agent definitions."""

    def test_reads_frontmatter_model(self):
        """Extracts model from YAML frontmatter."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False) as f:
            f.write('---\nmodel: claude-opus-4\nmaxTurns: 25\n---\nYou are a test agent.\n')
            path = f.name
        try:
            result = read_agent_file(path)
            self.assertEqual(result['model'], 'claude-opus-4')
            self.assertEqual(result['max_turns'], 25)
            self.assertEqual(result['prompt'], 'You are a test agent.')
        finally:
            os.unlink(path)

    def test_reads_tools_and_permission(self):
        """Extracts allowedTools, disallowedTools, permissionMode."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False) as f:
            f.write('---\npermissionMode: plan\nallowedTools:\n  - Read\n  - Grep\ndisallowedTools:\n  - Write\n---\nPrompt text.\n')
            path = f.name
        try:
            result = read_agent_file(path)
            self.assertEqual(result['permission_mode'], 'plan')
            self.assertEqual(result['tools'], ['Read', 'Grep'])
            self.assertEqual(result['disallowed_tools'], ['Write'])
        finally:
            os.unlink(path)

    def test_reads_mcp_servers(self):
        """Extracts mcpServers from frontmatter."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False) as f:
            f.write('---\nmcpServers:\n  - ask-question\n---\n')
            path = f.name
        try:
            result = read_agent_file(path)
            self.assertEqual(result['mcp_servers'], ['ask-question'])
        finally:
            os.unlink(path)

    def test_nonexistent_file_returns_empty(self):
        """Non-existent file returns empty dict."""
        result = read_agent_file('/no/such/file.md')
        self.assertEqual(result, {})

    def test_file_without_frontmatter_returns_prompt_only(self):
        """File without frontmatter treats entire content as prompt."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False) as f:
            f.write('You are a simple agent with no config.')
            path = f.name
        try:
            result = read_agent_file(path)
            self.assertEqual(result['prompt'], 'You are a simple agent with no config.')
            self.assertNotIn('model', result)
        finally:
            os.unlink(path)

    def test_empty_file_returns_empty(self):
        """Empty file returns empty dict."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False) as f:
            f.write('')
            path = f.name
        try:
            result = read_agent_file(path)
            self.assertEqual(result, {})
        finally:
            os.unlink(path)


class TestEnrichAgentConfig(unittest.TestCase):
    """enrich_agent_config merges file data into the config dict."""

    def test_enriches_from_agent_file(self):
        """Reads agent file and merges model, tools, prompt into config."""
        tmpdir = tempfile.mkdtemp()
        agent_dir = os.path.join(tmpdir, '.claude', 'agents')
        os.makedirs(agent_dir)
        with open(os.path.join(agent_dir, 'test-agent.md'), 'w') as f:
            f.write('---\nmodel: claude-opus-4\nmaxTurns: 30\nallowedTools:\n  - Read\n  - Glob\n---\nYou are a test agent.\n')
        config = {'name': 'test-agent', 'file': '.claude/agents/test-agent.md'}
        enriched = enrich_agent_config(config, search_dirs=[tmpdir])
        self.assertEqual(enriched['model'], 'claude-opus-4')
        self.assertEqual(enriched['max_turns'], 30)
        self.assertEqual(enriched['tools'], ['Read', 'Glob'])
        self.assertEqual(enriched['prompt'], 'You are a test agent.')
        # Original fields preserved
        self.assertEqual(enriched['name'], 'test-agent')

    def test_existing_config_values_take_precedence(self):
        """Config dict values are not overwritten by file data."""
        tmpdir = tempfile.mkdtemp()
        agent_dir = os.path.join(tmpdir, '.claude', 'agents')
        os.makedirs(agent_dir)
        with open(os.path.join(agent_dir, 'lead.md'), 'w') as f:
            f.write('---\nmodel: claude-sonnet-4\n---\nFile prompt.\n')
        config = {'name': 'lead', 'file': '.claude/agents/lead.md', 'model': 'claude-opus-4', 'role': 'team-lead'}
        enriched = enrich_agent_config(config, search_dirs=[tmpdir])
        # Config's model takes precedence over file's
        self.assertEqual(enriched['model'], 'claude-opus-4')
        self.assertEqual(enriched['role'], 'team-lead')
        # File's prompt is added since config didn't have one
        self.assertEqual(enriched['prompt'], 'File prompt.')

    def test_no_file_returns_config_unchanged(self):
        """When no agent file exists, config is returned as-is."""
        config = {'name': 'missing', 'file': '.claude/agents/missing.md'}
        enriched = enrich_agent_config(config, search_dirs=['/nonexistent'])
        self.assertEqual(enriched, config)

    def test_no_file_key_returns_config_unchanged(self):
        """When config has no file key, returned as-is."""
        config = {'name': 'bare'}
        enriched = enrich_agent_config(config)
        self.assertEqual(enriched, config)


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
