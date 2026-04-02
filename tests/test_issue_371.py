"""Tests for issue #371: Dashboard — chat blade on config and artifact screens.

Acceptance criteria:
1. config.html has a blade element (id="blade") collapsed by default
2. renderWorkgroup() sets bladeConvId scoped to workgroup entity
3. renderAgent() sets bladeConvId scoped to agent entity
4. renderProject() sets bladeConvId scoped to project entity
5. renderGlobal() sets bladeConvId for management level
6. Agent config screen no longer has a navigational 'Chat' section card
7. index.html has a blade element connected to OM conv ID
8. artifacts.html has a blade element connected to config lead
9. ConversationType.CONFIG_LEAD exists in orchestrator/messaging.py
10. ConfigLeadSession class exists with invoke() and send_agent_message()
11. Server handles 'config:' prefix in conversation POST
12. Conv IDs are entity-scoped (two workgroups → two separate conversations)
"""
import asyncio
import json
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

_REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_REPO_ROOT))


# ── HTML source helpers ───────────────────────────────────────────────────────

def _get_config_html() -> str:
    return (_REPO_ROOT / 'bridge' / 'static' / 'config.html').read_text()


def _get_index_html() -> str:
    return (_REPO_ROOT / 'bridge' / 'static' / 'index.html').read_text()


def _get_artifacts_html() -> str:
    return (_REPO_ROOT / 'bridge' / 'static' / 'artifacts.html').read_text()


def _extract_fn(source: str, name: str) -> str:
    """Extract the body of a JS function by name (greedy, not perfect but sufficient)."""
    m = re.search(
        r'(?:async\s+)?function\s+' + re.escape(name) + r'\s*\([^)]*\)\s*\{',
        source,
    )
    if m is None:
        raise AssertionError(f'{name}() not found in source')
    start = m.start()
    # Walk forward counting braces to find the closing }
    depth = 0
    i = m.end() - 1  # position of opening {
    while i < len(source):
        if source[i] == '{':
            depth += 1
        elif source[i] == '}':
            depth -= 1
            if depth == 0:
                return source[start:i + 1]
        i += 1
    raise AssertionError(f'Could not find end of {name}() in source')


# ── Server / asyncio helpers ──────────────────────────────────────────────────

def _run(coro):
    return asyncio.run(coro)


def _make_teaparty_home(tmp: str) -> str:
    tp_home = os.path.join(tmp, '.teaparty')
    os.makedirs(tp_home)
    data = {
        'name': 'Test Org',
        'description': 'test',
        'lead': 'office-manager',
        'humans': {'decider': 'tester'},
        'projects': [],
        'workgroups': [],
        'hooks': [],
        'scheduled': [],
    }
    with open(os.path.join(tp_home, 'teaparty.yaml'), 'w') as f:
        yaml.dump(data, f)
    return tp_home


# ═══════════════════════════════════════════════════════════════════════════════
# AC1: Blade element in config.html, collapsed by default
# ═══════════════════════════════════════════════════════════════════════════════

class TestConfigHtmlBladePresentAndCollapsed(unittest.TestCase):
    """config.html must have a blade element that is collapsed by default."""

    def setUp(self):
        self.source = _get_config_html()

    def test_blade_element_exists_with_id(self):
        """A DOM element with id="blade" must be present in config.html."""
        self.assertIn('id="blade"', self.source,
            'config.html must have an element with id="blade"')

    def test_blade_collapsed_class_at_init(self):
        """The blade element must carry a CSS class indicating collapsed state on load.

        The blade is collapsed by default (success criterion 6). The initial
        HTML should not have the 'open' class on the blade, or should explicitly
        set it to the collapsed state.
        """
        # Extract the blade element definition
        blade_match = re.search(r'id="blade"[^>]*>', self.source)
        self.assertIsNotNone(blade_match, 'Could not find id="blade" element')
        blade_tag = blade_match.group(0)
        # The blade must NOT have 'open' class at initial render
        self.assertNotIn('class="blade open"', blade_tag,
            'Blade must be collapsed by default; "open" class must not appear in initial HTML')

    def test_blade_toggle_function_defined(self):
        """A JS function to toggle the blade open/closed must be defined."""
        self.assertRegex(self.source, r'function\s+toggleBlade\s*\(',
            'config.html must define a toggleBlade() function')

    def test_blade_has_iframe(self):
        """The blade body must embed chat.html via an iframe rather than re-implementing the chat UI."""
        self.assertIn('blade-iframe', self.source,
            'Blade must embed chat.html in an iframe (id "blade-iframe") — do not re-implement chat UI')

    def test_blade_iframe_loads_chat_html(self):
        """The blade iframe must point to chat.html with minimal=1 to suppress the navigator."""
        self.assertIn('chat.html', self.source,
            'Blade iframe must load chat.html')
        self.assertIn('minimal=1', self.source,
            'Blade iframe URL must include minimal=1 to suppress the chat navigator')


# ═══════════════════════════════════════════════════════════════════════════════
# AC2: renderWorkgroup() sets bladeConvId scoped to workgroup
# ═══════════════════════════════════════════════════════════════════════════════

class TestRenderWorkgroupSetsBladConvId(unittest.TestCase):
    """renderWorkgroup() must set bladeConvId to an entity-scoped conv ID."""

    def setUp(self):
        self.source = _get_config_html()
        self.fn_body = _extract_fn(self.source, 'renderWorkgroup')

    def test_bladeconvid_set_in_render_workgroup(self):
        """renderWorkgroup() must assign bladeConvId."""
        self.assertIn('bladeConvId', self.fn_body,
            'renderWorkgroup() must set bladeConvId')

    def test_workgroup_conv_id_uses_config_prefix(self):
        """renderWorkgroup() conv ID must use the 'config:' prefix."""
        self.assertIn("'config:", self.fn_body,
            'renderWorkgroup() must set bladeConvId with config: prefix')

    def test_workgroup_conv_id_includes_workgroup_name(self):
        """renderWorkgroup() conv ID must incorporate the workgroup name for entity scoping."""
        # The name variable must appear in the conv ID assignment
        self.assertRegex(self.fn_body, r'bladeConvId\s*=.*name',
            'renderWorkgroup() bladeConvId must include the workgroup name')

    def test_workgroup_conv_id_includes_project_slug_when_present(self):
        """renderWorkgroup() conv ID must include projectSlug for project-scoped workgroups."""
        self.assertRegex(self.fn_body, r'bladeConvId\s*=.*projectSlug',
            'renderWorkgroup() bladeConvId must incorporate projectSlug')


# ═══════════════════════════════════════════════════════════════════════════════
# AC3: renderAgent() sets bladeConvId scoped to agent
# ═══════════════════════════════════════════════════════════════════════════════

class TestRenderAgentSetsBladConvId(unittest.TestCase):
    """renderAgent() must set bladeConvId to an entity-scoped conv ID."""

    def setUp(self):
        self.source = _get_config_html()
        self.fn_body = _extract_fn(self.source, '_renderAgentContent')

    def test_bladeconvid_set_in_render_agent(self):
        """_renderAgentContent() must assign bladeConvId."""
        self.assertIn('bladeConvId', self.fn_body,
            '_renderAgentContent() must set bladeConvId')

    def test_agent_conv_id_uses_config_prefix(self):
        """_renderAgentContent() conv ID must use the 'config:' prefix."""
        self.assertIn("'config:", self.fn_body,
            '_renderAgentContent() must set bladeConvId with config: prefix')

    def test_agent_conv_id_includes_agent_name(self):
        """_renderAgentContent() conv ID must include the agent name."""
        self.assertRegex(self.fn_body, r'bladeConvId\s*=.*name',
            '_renderAgentContent() bladeConvId must include agent name')


# ═══════════════════════════════════════════════════════════════════════════════
# AC4: renderProject() sets bladeConvId scoped to project
# ═══════════════════════════════════════════════════════════════════════════════

class TestRenderProjectSetsBladConvId(unittest.TestCase):
    """renderProject() must set bladeConvId for the project level."""

    def setUp(self):
        self.source = _get_config_html()
        self.fn_body = _extract_fn(self.source, 'renderProject')

    def test_bladeconvid_set_in_render_project(self):
        """renderProject() must assign bladeConvId."""
        self.assertIn('bladeConvId', self.fn_body,
            'renderProject() must set bladeConvId')

    def test_project_conv_id_uses_config_prefix(self):
        """renderProject() conv ID must use the 'config:' prefix."""
        self.assertIn("'config:", self.fn_body,
            'renderProject() must set bladeConvId with config: prefix')

    def test_project_conv_id_includes_slug(self):
        """renderProject() conv ID must include the project slug."""
        self.assertRegex(self.fn_body, r'bladeConvId\s*=.*slug',
            'renderProject() bladeConvId must include project slug')


# ═══════════════════════════════════════════════════════════════════════════════
# AC5: renderGlobal() sets bladeConvId for management level
# ═══════════════════════════════════════════════════════════════════════════════

class TestRenderGlobalSetsBladConvId(unittest.TestCase):
    """renderGlobal() must set bladeConvId to the management config lead conv ID."""

    def setUp(self):
        self.source = _get_config_html()
        self.fn_body = _extract_fn(self.source, 'renderGlobal')

    def test_bladeconvid_set_in_render_global(self):
        """renderGlobal() must assign bladeConvId."""
        self.assertIn('bladeConvId', self.fn_body,
            'renderGlobal() must set bladeConvId')

    def test_management_conv_id_is_management(self):
        """renderGlobal() conv ID must encode the management level."""
        self.assertIn('config:management', self.fn_body,
            'renderGlobal() must set bladeConvId = "config:management"')


# ═══════════════════════════════════════════════════════════════════════════════
# AC6: Agent config screen has no navigational 'Chat' section card
# ═══════════════════════════════════════════════════════════════════════════════

class TestAgentConfigScreenNoNavigationalChatSection(unittest.TestCase):
    """The agent config screen must not have a Chat section that navigates to chat.html.

    The blade supersedes the old Chat section card (success criterion: blade
    replaces the per-entity chat button). The old pattern was a 'Chat' sectionCard
    with an item calling openChat() that redirected to chat.html.
    """

    def setUp(self):
        self.source = _get_config_html()
        self.fn_body = _extract_fn(self.source, '_renderAgentContent')

    def test_no_standalone_chat_section_card_in_agent_render(self):
        """_renderAgentContent() must not render a separate 'Chat' sectionCard.

        The blade provides the chat UI inline; the old sectionCard('Chat', ...)
        pattern redirected to chat.html and is superseded.
        """
        # The old pattern was: sectionCard('Chat', chatItems, {})
        self.assertNotIn("sectionCard('Chat'", self.fn_body,
            "_renderAgentContent() must not render a 'Chat' sectionCard — blade replaces it")

    def test_no_agent_conv_id_for_navigation_in_agent_render(self):
        """_renderAgentContent() must not build an 'agent:' conv ID for navigation.

        The old pattern was: var agentConvId = 'agent:' + name; openChat(agentConvId)
        which navigated to chat.html. The blade replaces this inline; the 'agent:'
        conv ID for navigation must no longer be constructed.
        """
        self.assertNotRegex(self.fn_body, r"agentConvId\s*=\s*'agent:",
            "_renderAgentContent() must not construct agentConvId = 'agent:...' — blade replaces it")


# ═══════════════════════════════════════════════════════════════════════════════
# AC7: index.html has a blade connected to OM
# ═══════════════════════════════════════════════════════════════════════════════

class TestIndexHtmlHasOmBlade(unittest.TestCase):
    """index.html must have a blade element connected to the OM conversation."""

    def setUp(self):
        self.source = _get_index_html()

    def test_blade_element_present_in_index(self):
        """index.html must have a blade element (id="blade")."""
        self.assertIn('id="blade"', self.source,
            'index.html must have an element with id="blade"')

    def test_blade_toggle_function_defined_in_index(self):
        """index.html must define toggleBlade() or import it."""
        self.assertIn('toggleBlade', self.source,
            'index.html must define/use toggleBlade for the blade')

    def test_index_blade_uses_om_conv_id(self):
        """index.html blade must set bladeConvId to the OM conversation ID."""
        # The blade on index.html routes to the OM — bladeConvId must be set to omConvId
        self.assertIn('bladeConvId', self.source,
            'index.html must set bladeConvId for the blade conversation')


# ═══════════════════════════════════════════════════════════════════════════════
# AC8: artifacts.html has a blade element
# ═══════════════════════════════════════════════════════════════════════════════

class TestArtifactsHtmlHasBlade(unittest.TestCase):
    """artifacts.html must have a blade element for config lead chat."""

    def setUp(self):
        self.source = _get_artifacts_html()

    def test_blade_element_present_in_artifacts(self):
        """artifacts.html must have a blade element (id="blade")."""
        self.assertIn('id="blade"', self.source,
            'artifacts.html must have an element with id="blade"')

    def test_artifacts_blade_uses_config_conv_id(self):
        """artifacts.html blade must connect to a config lead conversation."""
        self.assertIn('bladeConvId', self.source,
            'artifacts.html must set bladeConvId for the blade conversation')

    def test_artifacts_blade_scoped_to_file(self):
        """artifacts.html blade conv ID must include the file path for entity scoping."""
        self.assertRegex(self.source, r"bladeConvId.*(?:file|artifact|path)",
            'artifacts.html bladeConvId must incorporate the file path for scoping')

    def test_artifacts_browse_mode_conv_id_not_empty_suffix(self):
        """artifacts.html blade conv ID must not have an empty path suffix in browse mode.

        When no ?file= param is present, bladeConvId must not degrade to
        'config:artifact:{project}:' (empty path). A named fallback like 'browse' is required.
        """
        # The fallback for missing file must not be empty string
        self.assertNotIn("requestedFile || ''", self.source,
            "artifacts.html must not use empty string as fallback for bladeConvId path; "
            "use a named scope like 'browse'")
        self.assertRegex(self.source, r"bladeConvId.*browse|browse.*bladeConvId",
            "artifacts.html must use a named fallback (e.g. 'browse') for no-file blade conv ID")

    def test_artifacts_load_file_updates_blade_conv_id(self):
        """loadFile() must update bladeConvId to the newly selected file.

        Entity scoping must hold for mid-session navigation: if the user starts
        on file A then navigates to file B, the blade must switch to B's conv ID.
        """
        fn_body = _extract_fn(self.source, 'loadFile')
        self.assertIsNotNone(fn_body, 'loadFile() must exist in artifacts.html')
        self.assertIn('bladeConvId', fn_body,
            "loadFile() must update bladeConvId when a new file is selected")
        self.assertRegex(fn_body, r"bladeConvId\s*=.*artifact",
            "loadFile() must assign a 'config:artifact:...' conv ID using the new path")


# ═══════════════════════════════════════════════════════════════════════════════
# AC9: ConversationType.CONFIG_LEAD in messaging.py
# ═══════════════════════════════════════════════════════════════════════════════

class TestConversationTypeConfigLeadExists(unittest.TestCase):
    """ConversationType.CONFIG_LEAD must be defined in orchestrator/messaging.py."""

    def test_config_lead_enum_member_exists(self):
        """ConversationType must have a CONFIG_LEAD member."""
        from orchestrator.messaging import ConversationType
        self.assertIn('CONFIG_LEAD', ConversationType.__members__,
            'ConversationType must have a CONFIG_LEAD member')

    def test_config_lead_has_config_prefix(self):
        """The 'config' prefix must map to config_lead conversation type."""
        from orchestrator.messaging import _PREFIXES, ConversationType
        self.assertIn(ConversationType.CONFIG_LEAD, _PREFIXES,
            'CONFIG_LEAD must have a prefix entry in _PREFIXES')
        self.assertEqual(_PREFIXES[ConversationType.CONFIG_LEAD], 'config',
            "CONFIG_LEAD prefix must be 'config'")

    def test_make_conversation_id_for_config_lead(self):
        """make_conversation_id() must produce 'config:{qualifier}' for CONFIG_LEAD."""
        from orchestrator.messaging import ConversationType, make_conversation_id
        conv_id = make_conversation_id(ConversationType.CONFIG_LEAD, 'management')
        self.assertEqual(conv_id, 'config:management')

    def test_config_lead_workgroup_conv_id_format(self):
        """make_conversation_id for workgroup scope must be 'config:wg:{project}:{name}'."""
        from orchestrator.messaging import ConversationType, make_conversation_id
        conv_id = make_conversation_id(ConversationType.CONFIG_LEAD, 'wg:myproject:coding')
        self.assertEqual(conv_id, 'config:wg:myproject:coding')


# ═══════════════════════════════════════════════════════════════════════════════
# AC10: ConfigLeadSession class exists with required methods
# ═══════════════════════════════════════════════════════════════════════════════

class TestConfigLeadSessionExists(unittest.TestCase):
    """ConfigLeadSession must exist in orchestrator/config_lead.py."""

    def test_config_lead_module_importable(self):
        """orchestrator.config_lead must be importable."""
        import importlib
        mod = importlib.import_module('orchestrator.config_lead')
        self.assertIsNotNone(mod)

    def test_config_lead_session_class_exists(self):
        """ConfigLeadSession must be defined in orchestrator.config_lead."""
        from orchestrator.config_lead import ConfigLeadSession
        self.assertTrue(callable(ConfigLeadSession))

    def test_config_lead_session_has_invoke(self):
        """ConfigLeadSession must have an async invoke() method."""
        from orchestrator.config_lead import ConfigLeadSession
        self.assertTrue(hasattr(ConfigLeadSession, 'invoke'),
            'ConfigLeadSession must have an invoke() method')
        import inspect
        self.assertTrue(inspect.iscoroutinefunction(ConfigLeadSession.invoke),
            'ConfigLeadSession.invoke() must be async')

    def test_config_lead_session_has_send_agent_message(self):
        """ConfigLeadSession must have a send_agent_message() method for error injection."""
        from orchestrator.config_lead import ConfigLeadSession
        self.assertTrue(hasattr(ConfigLeadSession, 'send_agent_message'),
            'ConfigLeadSession must have send_agent_message()')

    def test_config_lead_session_instantiates(self):
        """ConfigLeadSession(teaparty_home, qualifier) must instantiate without error."""
        from orchestrator.config_lead import ConfigLeadSession
        with tempfile.TemporaryDirectory() as tmp:
            session = ConfigLeadSession(tmp, 'management')
            self.assertIsNotNone(session)

    def test_config_lead_session_conversation_id_uses_config_prefix(self):
        """ConfigLeadSession.conversation_id must be 'config:{qualifier}'."""
        from orchestrator.config_lead import ConfigLeadSession
        with tempfile.TemporaryDirectory() as tmp:
            session = ConfigLeadSession(tmp, 'management')
            self.assertEqual(session.conversation_id, 'config:management')

    def test_config_lead_session_two_qualifiers_produce_different_conv_ids(self):
        """Two ConfigLeadSessions with different qualifiers must have different conv IDs.

        This verifies that workgroup scoping actually creates separate conversations.
        """
        from orchestrator.config_lead import ConfigLeadSession
        with tempfile.TemporaryDirectory() as tmp:
            s1 = ConfigLeadSession(tmp, 'wg:proj:coding')
            s2 = ConfigLeadSession(tmp, 'wg:proj:design')
            self.assertNotEqual(s1.conversation_id, s2.conversation_id,
                'Different entity qualifiers must produce different conversation IDs')

    def test_config_lead_bus_path_helper_exists(self):
        """config_lead_bus_path() helper must be defined."""
        from orchestrator.config_lead import config_lead_bus_path
        with tempfile.TemporaryDirectory() as tmp:
            path = config_lead_bus_path(tmp)
            self.assertTrue(path.endswith('.db'),
                'config_lead_bus_path() must return a path to a SQLite database')


# ═══════════════════════════════════════════════════════════════════════════════
# AC11: Server handles 'config:' prefix in conversation POST
# ═══════════════════════════════════════════════════════════════════════════════

class TestServerHandlesConfigConvPrefix(unittest.TestCase):
    """bridge/server.py must handle POST /api/conversations/config:{qualifier}."""

    def test_server_creates_config_lead_conversation_on_post(self):
        """CONFIG_LEAD conversation creation must work via the bus."""
        from orchestrator.config_lead import config_lead_bus_path
        from orchestrator.messaging import ConversationType, SqliteMessageBus

        with tempfile.TemporaryDirectory() as tmp:
            tp_home = _make_teaparty_home(tmp)
            bus_path = config_lead_bus_path(tp_home)
            os.makedirs(os.path.dirname(bus_path), exist_ok=True)
            bus = SqliteMessageBus(bus_path)
            conv = bus.create_conversation(ConversationType.CONFIG_LEAD, 'management')
            self.assertEqual(conv.id, 'config:management')
            self.assertEqual(conv.type, ConversationType.CONFIG_LEAD)

    def test_server_config_prefix_handler_registered(self):
        """bridge/server.py source must handle 'config:' prefix in _handle_conversation_post."""
        server_src = (_REPO_ROOT / 'bridge' / 'server.py').read_text()
        self.assertIn("config:", server_src,
            "server.py must handle 'config:' prefix in conversation POST handler")

    def test_server_invokes_config_lead_on_config_conv_post(self):
        """Server must call _invoke_config_lead() when posting to a config: conversation."""
        server_src = (_REPO_ROOT / 'bridge' / 'server.py').read_text()
        self.assertIn('_invoke_config_lead', server_src,
            "server.py must define and call _invoke_config_lead()")

    def test_server_config_lead_sessions_dict_exists(self):
        """BridgeServer must track ConfigLeadSession instances (per-qualifier cache)."""
        server_src = (_REPO_ROOT / 'bridge' / 'server.py').read_text()
        self.assertIn('_config_lead_sessions', server_src,
            "server.py must maintain a _config_lead_sessions dict")


# ═══════════════════════════════════════════════════════════════════════════════
# AC12: Entity-scoped conv IDs — two workgroups → two conversations
# ═══════════════════════════════════════════════════════════════════════════════

class TestEntityScopedConvIds(unittest.TestCase):
    """Conv IDs must be scoped to the specific entity viewed."""

    def test_two_workgroups_same_project_have_different_conv_ids(self):
        """Two workgroups in the same project must have separate blade conv IDs.

        Success criterion 4: 'Two workgroups in the same project have separate
        blade conversations -- both with the same project config lead, but
        scoped independently.'
        """
        from orchestrator.config_lead import ConfigLeadSession
        with tempfile.TemporaryDirectory() as tmp:
            s_coding = ConfigLeadSession(tmp, 'wg:myproject:coding')
            s_design = ConfigLeadSession(tmp, 'wg:myproject:design')
            self.assertNotEqual(s_coding.conversation_id, s_design.conversation_id)
            self.assertEqual(s_coding.conversation_id, 'config:wg:myproject:coding')
            self.assertEqual(s_design.conversation_id, 'config:wg:myproject:design')

    def test_workgroup_and_agent_with_same_name_have_different_conv_ids(self):
        """A workgroup and an agent with the same name must have different conv IDs."""
        from orchestrator.config_lead import ConfigLeadSession
        with tempfile.TemporaryDirectory() as tmp:
            s_wg = ConfigLeadSession(tmp, 'wg:proj:foo')
            s_agent = ConfigLeadSession(tmp, 'agent:proj:foo')
            self.assertNotEqual(s_wg.conversation_id, s_agent.conversation_id)

    def test_management_and_project_have_different_conv_ids(self):
        """Management-level and project-level blade conv IDs must differ."""
        from orchestrator.config_lead import ConfigLeadSession
        with tempfile.TemporaryDirectory() as tmp:
            s_mgmt = ConfigLeadSession(tmp, 'management')
            s_proj = ConfigLeadSession(tmp, 'project:myproject')
            self.assertNotEqual(s_mgmt.conversation_id, s_proj.conversation_id)

    def test_workgroup_conv_id_format(self):
        """config:wg:{project}:{name} must be the workgroup blade conv ID format."""
        from orchestrator.config_lead import ConfigLeadSession
        with tempfile.TemporaryDirectory() as tmp:
            s = ConfigLeadSession(tmp, 'wg:jainai:configuration')
            self.assertEqual(s.conversation_id, 'config:wg:jainai:configuration')

    def test_agent_conv_id_format(self):
        """config:agent:{project}:{name} must be the agent blade conv ID format."""
        from orchestrator.config_lead import ConfigLeadSession
        with tempfile.TemporaryDirectory() as tmp:
            s = ConfigLeadSession(tmp, 'agent:jainai:auditor')
            self.assertEqual(s.conversation_id, 'config:agent:jainai:auditor')
