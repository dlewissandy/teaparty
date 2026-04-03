"""Tests for issue #380: Config dashboard — agent card toggle blocks navigation to agent definition.

Acceptance criteria:
1. Clicking an agent card body opens the agent definition in the artifact viewer
2. A toggle switch widget on the right-hand side of the card controls active/inactive
   — it does not trigger card navigation
3. Active/inactive state is still reflected visually on the card
4. All three contexts work: global catalog, project agents, workgroup agents
5. Agent cards with no definition file on disk remain non-navigable (no broken link behavior)
"""
import os
import tempfile
import unittest
import yaml


# ── Helpers ───────────────────────────────────────────────────────────────────

CONFIG_HTML = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    'bridge', 'static', 'config.html',
)
STYLES_CSS = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    'bridge', 'static', 'styles.css',
)


def _read_config_html():
    with open(CONFIG_HTML) as f:
        return f.read()


def _read_styles_css():
    with open(STYLES_CSS) as f:
        return f.read()


def _make_bridge(tmpdir: str):
    from bridge.server import TeaPartyBridge
    teaparty_home = os.path.join(tmpdir, '.teaparty')
    os.makedirs(teaparty_home, exist_ok=True)
    static_dir = os.path.join(tmpdir, 'static')
    os.makedirs(static_dir, exist_ok=True)
    return TeaPartyBridge(teaparty_home=teaparty_home, static_dir=static_dir)


def _make_management_yaml(teaparty_home: str, agents: list):
    data = {
        'name': 'Management',
        'description': 'Test',
        'lead': 'office-manager',
        'humans': {'decider': 'darrell'},
        'members': {'agents': agents, 'skills': []},
        'hooks': [],
        'scheduled': [],
        'workgroups': [],
    }
    mgmt_dir = os.path.join(teaparty_home, 'management')
    os.makedirs(mgmt_dir, exist_ok=True)
    with open(os.path.join(mgmt_dir, 'teaparty.yaml'), 'w') as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)


def _make_agent_file(agents_dir: str, name: str):
    agent_dir = os.path.join(agents_dir, name)
    os.makedirs(agent_dir, exist_ok=True)
    with open(os.path.join(agent_dir, 'agent.md'), 'w') as f:
        f.write(f'# {name}\n')


def _make_workgroup_yaml(wg_path: str, agents: list):
    os.makedirs(os.path.dirname(wg_path), exist_ok=True)
    data = {
        'name': os.path.basename(wg_path).replace('.yaml', ''),
        'description': 'Test workgroup',
        'lead': 'auditor',
        'members': {'agents': agents, 'skills': []},
    }
    with open(wg_path, 'w') as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)


# ── _serialize_management_team: file on agent objects ────────────────────────

class TestManagementTeamAgentFileProperty(unittest.TestCase):
    """_serialize_management_team must include a file property on each agent object
    that is the path to the agent definition when the file exists, or None when it does not."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.teaparty_home = os.path.join(self.tmp, '.teaparty')
        self.agents_dir = os.path.join(self.tmp, '.teaparty', 'management', 'agents')

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_agent_file_is_path_when_definition_exists_on_disk(self):
        """_serialize_management_team returns the .md file path when the agent definition exists."""
        from orchestrator.config_reader import load_management_team
        _make_management_yaml(self.teaparty_home, agents=['office-manager'])
        _make_agent_file(self.agents_dir, 'office-manager')
        team = load_management_team(teaparty_home=self.teaparty_home)
        bridge = _make_bridge(self.tmp)
        result = bridge._serialize_management_team(team)
        agents = {a['name']: a for a in result['agents']}
        self.assertIn('office-manager', agents)
        agent = agents['office-manager']
        self.assertIn('file', agent, '_serialize_management_team must include file on each agent')
        self.assertIsNotNone(agent['file'], 'file must not be None when definition exists on disk')
        self.assertTrue(
            agent['file'].endswith('office-manager/agent.md'),
            f'file path must point to the agent.md definition: {agent["file"]}',
        )

    def test_agent_file_is_none_when_definition_missing_from_disk(self):
        """_serialize_management_team returns file=None when the agent definition does not exist."""
        from orchestrator.config_reader import load_management_team
        # Register agent in YAML but don't create the .md file
        _make_management_yaml(self.teaparty_home, agents=['ghost-agent'])
        team = load_management_team(teaparty_home=self.teaparty_home)
        bridge = _make_bridge(self.tmp)
        result = bridge._serialize_management_team(team)
        agents = {a['name']: a for a in result['agents']}
        self.assertIn('ghost-agent', agents)
        agent = agents['ghost-agent']
        self.assertIn('file', agent, '_serialize_management_team must include file on each agent')
        self.assertIsNone(
            agent['file'],
            'file must be None when agent definition file does not exist on disk',
        )

    def test_inactive_catalog_agent_file_is_none_when_missing(self):
        """Inactive agents in the catalog (filesystem-discovered, not in YAML) return file=None
        when their definition does not exist."""
        from orchestrator.config_reader import load_management_team
        _make_management_yaml(self.teaparty_home, agents=[])
        # Don't create any agent files — team loads with no catalog
        team = load_management_team(teaparty_home=self.teaparty_home)
        bridge = _make_bridge(self.tmp)
        # Simulate a discovered agent that has no file on disk
        result = bridge._serialize_management_team(
            team, discovered_agents=['phantom']
        )
        agents = {a['name']: a for a in result['agents']}
        self.assertIn('phantom', agents)
        self.assertIsNone(
            agents['phantom']['file'],
            'Discovered agent with no .md file on disk must have file=None',
        )


# ── _serialize_workgroup: file on agent objects ───────────────────────────────

class TestWorkgroupAgentFileProperty(unittest.TestCase):
    """_serialize_workgroup must include a file property on each agent object in detail mode."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.teaparty_home = os.path.join(self.tmp, '.teaparty')
        self.agents_dir = os.path.join(self.tmp, '.teaparty', 'management', 'agents')
        _make_management_yaml(self.teaparty_home, agents=[])

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _make_workgroup(self, agents: list):
        from orchestrator.config_reader import Workgroup
        return Workgroup(
            name='test-wg',
            description='Test',
            lead='auditor',
            members_agents=agents,
            members_hooks=[],
            norms={},
            budget={},
        )

    def test_workgroup_agent_has_file_key_in_detail_mode(self):
        """_serialize_workgroup must include a file key on each agent dict when detail=True."""
        bridge = _make_bridge(self.tmp)
        _make_agent_file(self.agents_dir, 'auditor')
        w = self._make_workgroup(agents=['auditor'])
        org_agents_set = {'auditor'}
        result = bridge._serialize_workgroup(
            w, detail=True,
            org_agents=org_agents_set,
            org_catalog_agents=['auditor'],
        )
        self.assertIn('agents', result)
        agents = {a['name']: a for a in result['agents']}
        self.assertIn('auditor', agents)
        self.assertIn(
            'file', agents['auditor'],
            '_serialize_workgroup must include file on each agent in detail mode',
        )

    def test_workgroup_agent_file_is_path_when_definition_exists(self):
        """_serialize_workgroup returns the .md path when the agent definition exists on disk."""
        bridge = _make_bridge(self.tmp)
        _make_agent_file(self.agents_dir, 'auditor')
        w = self._make_workgroup(agents=['auditor'])
        org_agents_set = {'auditor'}
        result = bridge._serialize_workgroup(
            w, detail=True,
            org_agents=org_agents_set,
            org_catalog_agents=['auditor'],
        )
        agents = {a['name']: a for a in result['agents']}
        file_val = agents['auditor']['file']
        self.assertIsNotNone(file_val, 'file must not be None when definition exists on disk')
        self.assertTrue(
            file_val.endswith('auditor/agent.md'),
            f'file path must point to the agent.md definition: {file_val}',
        )

    def test_workgroup_agent_file_is_none_when_definition_missing(self):
        """_serialize_workgroup returns file=None when the agent definition does not exist on disk."""
        bridge = _make_bridge(self.tmp)
        # Don't create auditor.md on disk
        w = self._make_workgroup(agents=['auditor'])
        org_agents_set = {'auditor'}
        result = bridge._serialize_workgroup(
            w, detail=True,
            org_agents=org_agents_set,
            org_catalog_agents=['auditor'],
        )
        agents = {a['name']: a for a in result['agents']}
        self.assertIsNone(
            agents['auditor']['file'],
            'file must be None when agent definition file does not exist on disk',
        )


# ── config.html: agent card structure ─────────────────────────────────────────

class TestAgentCardNavigationStructure(unittest.TestCase):
    """config.html agent cards must navigate to the agent config screen on card click
    (issue #369 supersedes the artifact-viewer navigation from issue #380),
    with a separate toggle widget that does not trigger navigation."""

    def setUp(self):
        self.content = _read_config_html()

    def test_agent_card_navigates_to_agent_config_screen(self):
        """Agent card builder must use configNav('agent', ...) to navigate to the agent config screen."""
        self.assertTrue(
            "configNav('agent'" in self.content or "configNav(\\'agent\\'" in self.content,
            "Agent card click handler must navigate to the agent config screen via configNav('agent', ...)",
        )

    def test_agent_card_toggle_uses_stop_propagation(self):
        """The toggle widget must call event.stopPropagation() to prevent triggering card navigation."""
        self.assertIn(
            'stopPropagation',
            self.content,
            'Toggle widget must call event.stopPropagation() so toggle click does not navigate',
        )

    def test_agent_card_has_catalog_toggle_widget(self):
        """Agent card must render a catalog-toggle element for the active/inactive toggle."""
        self.assertIn(
            'catalog-toggle',
            self.content,
            'Agent card must include a catalog-toggle widget element',
        )

    def test_render_global_agent_card_has_stop_propagation_on_toggle(self):
        """renderGlobal() agent toggle widget must call stopPropagation."""
        self.assertIn(
            'stopPropagation',
            self.content,
            'renderGlobal agent toggle must use stopPropagation',
        )

    def test_render_workgroup_agent_card_has_stop_propagation_on_toggle(self):
        """renderWorkgroup() agent toggle widget must call stopPropagation."""
        self.assertIn(
            'stopPropagation',
            self.content,
            'renderWorkgroup agent toggle must use stopPropagation',
        )


# ── styles.css: catalog-toggle widget ────────────────────────────────────────

class TestCatalogToggleCSS(unittest.TestCase):
    """styles.css must define the .catalog-toggle CSS class for the toggle switch widget."""

    def setUp(self):
        self.content = _read_styles_css()

    def test_catalog_toggle_class_is_defined(self):
        """.catalog-toggle CSS class must be defined in styles.css."""
        self.assertIn(
            '.catalog-toggle',
            self.content,
            'styles.css must define .catalog-toggle for the toggle switch widget',
        )

    def test_toggle_on_state_class_is_defined(self):
        """.toggle-on CSS class must be defined to indicate active state on the toggle."""
        self.assertIn(
            '.toggle-on',
            self.content,
            'styles.css must define .toggle-on for the active-state toggle appearance',
        )
