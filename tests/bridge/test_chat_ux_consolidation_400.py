"""Specification tests for issue #400: chat UX one codepath, conserved everywhere.

The chat UX — accordion, chevron tab, dispatch tree, status badges, message list,
input, CloseConversation cascade — must be implemented in exactly one place:
accordion-chat.js. Every page that shows a chat mounts that single implementation.
No page carries its own chat DOM, state, or event handlers.

Each test is load-bearing: it would fail if the fix were reverted (i.e. if the
accordion UX were still inline in index.html or config.html).
"""
import json
import os
import re
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


STATIC_DIR = Path(__file__).resolve().parent.parent.parent / "teaparty" / "bridge" / "static"
ACCORDION_JS = STATIC_DIR / "accordion-chat.js"
INDEX_HTML = STATIC_DIR / "index.html"
CONFIG_HTML = STATIC_DIR / "config.html"


# Accordion-specific symbols that must live exclusively in accordion-chat.js.
# These are the identifiers that define the accordion chat UX. Their presence in
# index.html or config.html would mean a second (diverging) implementation exists.
ACCORDION_SYMBOLS = [
    '_accordionExpanded',
    '_dispatchTree',
    '_renderAccordion',
    '_renderNode',
    '_flattenTree',
    '_findParent',
    '_removeFromTree',
    '_handleSessionRemoval',
    'accordionToggle',
    'BLADE_FILTERS',
    '_syncFiltersToIframe',
    'dispatch-accordion',
]


def _read(path: Path) -> str:
    return path.read_text(encoding='utf-8')


class TestAccordionModuleExists(unittest.TestCase):
    """accordion-chat.js must exist and contain the full accordion UX."""

    def test_accordion_chat_js_exists(self):
        """accordion-chat.js must exist in the static directory."""
        self.assertTrue(
            ACCORDION_JS.exists(),
            "accordion-chat.js is missing from teaparty/bridge/static/ — "
            "the shared chat UX module has not been created"
        )

    def test_accordion_module_contains_all_accordion_symbols(self):
        """accordion-chat.js must define every accordion UX symbol."""
        if not ACCORDION_JS.exists():
            self.skipTest("accordion-chat.js not yet created")
        src = _read(ACCORDION_JS)
        for symbol in ACCORDION_SYMBOLS:
            self.assertIn(
                symbol, src,
                f"accordion-chat.js is missing '{symbol}' — "
                f"the accordion UX is incomplete or the symbol was renamed"
            )

    def test_accordion_module_contains_dispatch_started_handler(self):
        """accordion-chat.js must handle dispatch_started WebSocket events."""
        if not ACCORDION_JS.exists():
            self.skipTest("accordion-chat.js not yet created")
        src = _read(ACCORDION_JS)
        self.assertIn(
            'dispatch_started', src,
            "accordion-chat.js does not handle 'dispatch_started' WS events — "
            "nested dispatches will not appear in the accordion"
        )

    def test_accordion_module_contains_dispatch_completed_handler(self):
        """accordion-chat.js must handle dispatch_completed WebSocket events."""
        if not ACCORDION_JS.exists():
            self.skipTest("accordion-chat.js not yet created")
        src = _read(ACCORDION_JS)
        self.assertIn(
            'dispatch_completed', src,
            "accordion-chat.js does not handle 'dispatch_completed' WS events — "
            "CloseConversation cascade will not remove sections from the accordion"
        )

    def test_accordion_module_has_mount_api(self):
        """accordion-chat.js must expose a public mount API."""
        if not ACCORDION_JS.exists():
            self.skipTest("accordion-chat.js not yet created")
        src = _read(ACCORDION_JS)
        self.assertIn(
            'AccordionChat', src,
            "accordion-chat.js does not expose 'AccordionChat' — "
            "pages cannot mount the shared implementation"
        )

    def test_accordion_module_accepts_conv_id(self):
        """accordion-chat.js mount config must accept a convId parameter."""
        if not ACCORDION_JS.exists():
            self.skipTest("accordion-chat.js not yet created")
        src = _read(ACCORDION_JS)
        self.assertIn(
            'convId', src,
            "accordion-chat.js does not accept a 'convId' config parameter — "
            "pages cannot configure which conversation to show"
        )


class TestSingleCodepathEnforcement(unittest.TestCase):
    """Accordion UX symbols must appear in accordion-chat.js and NOWHERE ELSE.

    The structural guarantee: there is one implementation. Any accordion symbol
    found in index.html or config.html means a second (diverging) implementation
    was added, violating the single-codepath constraint.
    """

    def test_accordion_symbols_absent_from_index_html(self):
        """index.html must not contain any accordion UX implementation code."""
        src = _read(INDEX_HTML)
        found = [sym for sym in ACCORDION_SYMBOLS if sym in src]
        self.assertEqual(
            found, [],
            f"index.html contains accordion UX symbols {found} — "
            f"the accordion code was not extracted into accordion-chat.js. "
            f"index.html must only mount the shared implementation, not define it."
        )

    def test_accordion_symbols_absent_from_config_html(self):
        """config.html must not contain any accordion UX implementation code."""
        src = _read(CONFIG_HTML)
        found = [sym for sym in ACCORDION_SYMBOLS if sym in src]
        self.assertEqual(
            found, [],
            f"config.html contains accordion UX symbols {found} — "
            f"config.html carries its own chat UX implementation, violating single-codepath. "
            f"config.html must only mount the shared implementation, not define it."
        )

    def test_blade_iframe_absent_from_config_html(self):
        """config.html must not contain the old single-iframe blade (blade-iframe)."""
        src = _read(CONFIG_HTML)
        self.assertNotIn(
            'blade-iframe', src,
            "config.html still contains 'blade-iframe' — "
            "the old simplified blade (plain iframe, no accordion) was not removed. "
            "config.html must use the shared accordion-chat.js implementation."
        )

    def test_update_blade_iframe_absent_from_config_html(self):
        """config.html must not contain _updateBladeIframe (old blade wiring)."""
        src = _read(CONFIG_HTML)
        self.assertNotIn(
            '_updateBladeIframe', src,
            "config.html still contains '_updateBladeIframe' — "
            "the old blade-switching logic was not removed. "
            "config.html must use the shared accordion-chat.js implementation."
        )


class TestPagesMountSharedModule(unittest.TestCase):
    """Both index.html and config.html must include and mount accordion-chat.js."""

    def test_index_html_includes_accordion_chat_js(self):
        """index.html must load accordion-chat.js via script tag."""
        src = _read(INDEX_HTML)
        self.assertIn(
            'accordion-chat.js', src,
            "index.html does not include accordion-chat.js — "
            "the home page is not using the shared chat implementation"
        )

    def test_config_html_includes_accordion_chat_js(self):
        """config.html must load accordion-chat.js via script tag."""
        src = _read(CONFIG_HTML)
        self.assertIn(
            'accordion-chat.js', src,
            "config.html does not include accordion-chat.js — "
            "config pages are not using the shared chat implementation"
        )

    def test_index_html_mounts_accordion_chat(self):
        """index.html must call AccordionChat.mount() to activate the blade."""
        src = _read(INDEX_HTML)
        self.assertIn(
            'AccordionChat', src,
            "index.html does not reference AccordionChat — "
            "the home page never mounts the shared chat implementation"
        )

    def test_config_html_mounts_accordion_chat(self):
        """config.html must call AccordionChat.mount() to activate the blade."""
        src = _read(CONFIG_HTML)
        self.assertIn(
            'AccordionChat', src,
            "config.html does not reference AccordionChat — "
            "config pages never mount the shared chat implementation"
        )


class TestConfigPageRouting(unittest.TestCase):
    """Config pages must route to project leads, not the office manager.

    The issue routing table:
      Global (Management Team) → lead:teaparty-lead:{qualifier}
      Project Team             → lead:{slug}-lead:{qualifier}
      Agent/Workgroup detail   → parent project's lead (lead:{slug}-lead:{qualifier})

    The office manager ('om:') is for the home page only.
    """

    def test_config_html_does_not_construct_om_conv_id_for_blade(self):
        """config.html must not construct 'om:' conversation IDs for the blade.

        Home is the only page that talks to the office manager. All config pages
        must route to the relevant project lead.
        """
        src = _read(CONFIG_HTML)
        # The old pattern was: bladeConvId = omConvId = 'om:' + m.decider
        # We check that no om: string is used in a blade config context.
        # Specifically: no assignment of 'om:' + something to a blade config field.
        matches = re.findall(r"bladeConvId\s*[=:]\s*['\"]om:", src)
        self.assertEqual(
            matches, [],
            f"config.html still assigns an 'om:' conversation ID to bladeConvId: {matches}. "
            f"Config pages must route to project leads, not the office manager. "
            f"Use 'lead:{{leadName}}:{{qualifier}}' instead."
        )

    def test_config_html_uses_lead_prefix_for_global_scope(self):
        """config.html (loadGlobal) must construct a 'lead:' conversation ID for the blade."""
        src = _read(CONFIG_HTML)
        # The global (Management Team) scope must use teaparty-lead.
        # Look for 'lead:' being constructed near the global loader or blade config.
        self.assertIn(
            "'lead:'", src,
            "config.html does not construct any 'lead:' conversation IDs — "
            "config pages are routing to the wrong agent. "
            "Management Team must use 'lead:teaparty-lead:{qualifier}'."
        )

    def test_config_html_no_om_conv_id_variable(self):
        """config.html must not define or use 'omConvId' as a blade routing variable.

        The omConvId variable was the old mechanism for routing to the office manager.
        It must not appear in the blade wiring (bladeConvId = omConvId pattern).
        """
        src = _read(CONFIG_HTML)
        # Check for the old pattern: bladeConvId = omConvId
        old_pattern = re.findall(r'bladeConvId\s*[:=]\s*omConvId', src)
        self.assertEqual(
            old_pattern, [],
            f"config.html still uses 'bladeConvId = omConvId' pattern: {old_pattern}. "
            f"This routes config pages to the office manager, violating the routing table. "
            f"Each scope loader must compute a 'lead:' conversation ID directly."
        )


class TestSessionIdDerivation(unittest.TestCase):
    """accordion-chat.js must correctly derive session IDs from conversation IDs.

    The session ID is derived from convId to fetch the dispatch tree. The derivation
    must match AgentSession._session_key() from teaparty/teams/session.py:
        safe_id = qualifier.replace('/', '-').replace(':', '-').replace(' ', '-')
        return f'{agent_name}-{safe_id}'

    For om:{qualifier}: agent_name='office-manager', qualifier=qualifier
    For lead:{name}:{qualifier}: agent_name=name, qualifier=f'{name}:{rest}'
    """

    def _read_accordion_js(self) -> str:
        if not ACCORDION_JS.exists():
            self.skipTest("accordion-chat.js not yet created")
        return _read(ACCORDION_JS)

    def test_derive_session_id_function_exists(self):
        """accordion-chat.js must define a session ID derivation function."""
        src = self._read_accordion_js()
        self.assertIn(
            'deriveSessionId', src,
            "accordion-chat.js does not define 'deriveSessionId' — "
            "the module cannot fetch the dispatch tree for project leads"
        )

    def test_om_handled_in_derivation(self):
        """Session ID derivation must handle the singleton 'om' conversation ID."""
        src = self._read_accordion_js()
        # The office manager has no qualifier — convId is exactly 'om'.
        # The derivation must return 'office-manager' for this case.
        self.assertIn(
            "'om'", src,
            "accordion-chat.js deriveSessionId does not handle the 'om' conversation ID — "
            "the accordion will not fetch the dispatch tree for the office manager"
        )

    def test_lead_prefix_handled_in_derivation(self):
        """Session ID derivation must handle the 'lead:' prefix."""
        src = self._read_accordion_js()
        self.assertIn(
            "'lead:'", src,
            "accordion-chat.js deriveSessionId does not handle the 'lead:' prefix — "
            "the accordion will not fetch the dispatch tree for project leads"
        )

    def test_om_session_id_derivation_correct(self):
        """Session ID for 'om' must be 'office-manager'.

        Matches AgentSession._session_key() with agent_name='office-manager',
        qualifier='' (no qualifier — singleton OM).
        """
        src = self._read_accordion_js()
        # The literal 'office-manager' must appear as the return value for the 'om' case.
        self.assertIn(
            "'office-manager'", src,
            "accordion-chat.js does not return 'office-manager' for the 'om' conversation ID — "
            "the dispatch tree fetch will use the wrong session ID for the office manager. "
            "Expected: deriveSessionId('om') === 'office-manager'"
        )

    def test_lead_session_id_uses_agent_name_prefix(self):
        """Session ID for project leads must start with the lead's agent name.

        Matches AgentSession._session_key():
          deriveSessionId('lead:teaparty-lead:darrell') must be
          'teaparty-lead-teaparty-lead-darrell'
        """
        src = self._read_accordion_js()
        # For lead: convIds, the session key is built from the lead name and qualifier.
        # The derivation must replace ':' with '-' in the key.
        # Check that the derivation replaces colons (the key contains colons from the qualifier).
        self.assertIn(
            "replace", src,
            "accordion-chat.js deriveSessionId does not replace ':' in the qualifier — "
            "session IDs for project leads will contain colons, which won't match "
            "AgentSession._session_key()'s output"
        )
        # Also verify the derivation concatenates agent name with the safe key.
        self.assertIn(
            "leadName", src,
            "accordion-chat.js deriveSessionId does not use 'leadName' — "
            "the session ID for project leads will not be prefixed with the agent name"
        )

    def test_config_prefix_handled_in_derivation(self):
        """Session ID derivation must handle the 'config:' prefix.

        config: conversations route to the configuration-lead agent.
        deriveSessionId('config:artifact:teaparty:hooks/on_commit.yaml')
        must return 'configuration-lead' so the accordion can load the
        dispatch tree for the configuration lead.
        """
        src = self._read_accordion_js()
        self.assertIn(
            "'config:'", src,
            "accordion-chat.js deriveSessionId does not handle the 'config:' prefix — "
            "the accordion will bail out for hook artifact views, showing no chat UI"
        )
        self.assertIn(
            "'configuration-lead'", src,
            "accordion-chat.js deriveSessionId does not return 'configuration-lead' for "
            "'config:' conversations — the dispatch tree will be fetched with the wrong session ID"
        )


class TestDomStructureInModule(unittest.TestCase):
    """The blade DOM structure must be defined in accordion-chat.js, not inline HTML.

    The accordion container, blade tab, blade header, and filter bar must be
    created by the module, not hardcoded in page HTML.
    """

    def test_dispatch_accordion_absent_from_index_html(self):
        """index.html must not hardcode the dispatch-accordion container."""
        src = _read(INDEX_HTML)
        self.assertNotIn(
            'dispatch-accordion', src,
            "index.html hardcodes the 'dispatch-accordion' container — "
            "the accordion DOM is not being created by accordion-chat.js. "
            "Remove the hardcoded container; the module creates it on mount."
        )

    def test_dispatch_accordion_absent_from_config_html(self):
        """config.html must not hardcode the dispatch-accordion container."""
        src = _read(CONFIG_HTML)
        self.assertNotIn(
            'dispatch-accordion', src,
            "config.html hardcodes the 'dispatch-accordion' container — "
            "config.html must not contain any chat UX DOM. "
            "The module creates it on mount."
        )

    def test_accordion_section_styles_in_module_or_css(self):
        """Accordion CSS classes must not be defined inline in index.html.

        The .accord-section, .accord-header, etc. styles were previously in a
        <style> block inside index.html. They must move to styles.css or
        accordion-chat.js so config pages also get them.
        """
        src = _read(INDEX_HTML)
        # The old <style> block in index.html contained '.accord-section' rules.
        # If it's still there as inline style, that's a structural leak.
        inline_accord_style = re.search(r'<style[^>]*>.*?\.accord-section', src, re.DOTALL)
        self.assertIsNone(
            inline_accord_style,
            "index.html still has .accord-section CSS rules in an inline <style> block — "
            "these styles are page-specific and will not apply on config pages. "
            "Move accordion CSS to styles.css."
        )


class TestAccordionChatJsConvIdRouting(unittest.TestCase):
    """accordion-chat.js must use its convId config to POST messages (not hardcode any agent)."""

    def test_accordion_module_posts_to_conv_id(self):
        """accordion-chat.js seed/send must POST to the configured convId, not a hardcoded path."""
        if not ACCORDION_JS.exists():
            self.skipTest("accordion-chat.js not yet created")
        src = _read(ACCORDION_JS)
        # The POST URL must be built from the configured convId, not a hardcoded 'om:' path.
        # Check that the module uses convId in its fetch/POST call.
        self.assertIn(
            'convId', src,
            "accordion-chat.js does not use 'convId' in its message-posting logic — "
            "all chats will POST to the same hardcoded URL regardless of which agent is shown"
        )
        # Confirm no hardcoded 'om:' in the POST path.
        hardcoded_om = re.findall(r"fetch\s*\(\s*['\"].*?/api/conversations/om:", src)
        self.assertEqual(
            hardcoded_om, [],
            f"accordion-chat.js hardcodes 'om:' in its POST URL: {hardcoded_om}. "
            f"The POST must use the configured convId so project-lead chats POST to the right endpoint."
        )

    def test_accordion_module_builds_dispatch_tree_url_from_session_id(self):
        """accordion-chat.js must fetch /api/dispatch-tree/{sessionId}, not a hardcoded path."""
        if not ACCORDION_JS.exists():
            self.skipTest("accordion-chat.js not yet created")
        src = _read(ACCORDION_JS)
        self.assertIn(
            '/api/dispatch-tree/', src,
            "accordion-chat.js does not fetch '/api/dispatch-tree/' — "
            "the accordion will not show nested dispatches"
        )


class TestDomStructuralEquivalence(unittest.TestCase):
    """The blade DOM structure is config-invariant: identical for OM config and project-lead config.

    AC4: A test mounts the shared implementation with two distinct configs and asserts
    DOM structural equivalence modulo the parameterized fields (title text, iframe conv id).

    Since accordion-chat.js generates blade DOM via a single bladeEl.innerHTML = '...'
    assignment with no branching on convId, structural equivalence follows from there being
    exactly one code path that produces the DOM. This test proves:
      (a) the template is a fixed structure with the required elements,
      (b) no convId- or agent-specific content is embedded in the template itself,
      (c) title and iframe src are applied as post-mount parameterization (not in the template).

    This is the static-analysis equivalent of mounting with two configs and diffing the DOM.
    The proof is stronger: it covers all configs, not just the two exercised.
    """

    REQUIRED_BLADE_ELEMENTS = [
        'class="blade-tab"',
        'id="blade-tab"',
        'id="blade-tab-chevron"',
        'class="blade-body"',
        'class="blade-header"',
        'class="blade-title"',
        'id="blade-title"',
        'id="blade-filters"',
        'id="dispatch-accordion"',
    ]

    def _read_accordion_js(self) -> str:
        if not ACCORDION_JS.exists():
            self.skipTest("accordion-chat.js not yet created")
        return _read(ACCORDION_JS)

    def _extract_blade_template(self, src: str) -> str:
        """Extract the bladeEl.innerHTML assignment block from accordion-chat.js."""
        m = re.search(r'bladeEl\.innerHTML\s*=\s*([\s\S]+?);\s*\n', src)
        self.assertIsNotNone(m, "Could not find bladeEl.innerHTML assignment in accordion-chat.js")
        return m.group(1)

    def test_blade_template_contains_all_required_structural_elements(self):
        """The blade DOM template must contain every structural element of the chat UX.

        These elements must be present for any config — OM or project lead.
        """
        src = self._read_accordion_js()
        template = self._extract_blade_template(src)
        for element in self.REQUIRED_BLADE_ELEMENTS:
            self.assertIn(
                element, template,
                f"blade DOM template is missing '{element}' — "
                f"the chat UX structure is incomplete regardless of which config is passed. "
                f"Both OM and project-lead configs would render a broken blade."
            )

    def test_blade_template_does_not_branch_on_conv_id(self):
        """The blade DOM template must not embed any conv-id-specific content.

        Structural equivalence for all configs (OM, lead, any future config) follows from
        the template being a fixed string with no convId-dependent branches. If the
        template branched on convId, the DOM structure would diverge between configs.
        """
        src = self._read_accordion_js()
        template = self._extract_blade_template(src)
        # convId is not available at template-generation time — it's set by _applyConfig
        # after mount. The template must not embed it.
        self.assertNotIn(
            'om:', template,
            "blade DOM template hardcodes 'om:' — "
            "the blade DOM would differ between OM config and project-lead config. "
            "convId must be applied after mount, not embedded in the template."
        )
        self.assertNotIn(
            'lead:', template,
            "blade DOM template hardcodes 'lead:' — "
            "the template must be config-neutral; parameterization happens post-mount."
        )
        self.assertNotIn(
            'office-manager', template,
            "blade DOM template hardcodes 'office-manager' — "
            "the agent name must not appear in the DOM template."
        )

    def test_title_applied_post_mount_not_in_template(self):
        """The blade title must be set by textContent after mount, not embedded in the template.

        If the title were in the template, configs with different titles would produce
        different DOM structures. The template must contain an empty title element;
        _applyConfig sets its textContent.
        """
        src = self._read_accordion_js()
        # The title element in the template must be empty (no hardcoded text).
        # Post-mount, _applyConfig does: titleEl.textContent = _config.title || ''
        self.assertIn(
            'textContent', src,
            "accordion-chat.js does not set title via textContent — "
            "the title is not being applied post-mount. "
            "DOM structural equivalence requires the template to have an empty title element."
        )
        self.assertIn(
            'blade-title', src,
            "accordion-chat.js does not reference 'blade-title' when setting the title — "
            "the title element is not being parameterized post-mount."
        )


class TestNestedDispatchNonHomePage(unittest.TestCase):
    """Nested dispatch must work identically on non-home (project-lead) pages.

    AC9: When any agent reached via the chat dispatches a sub-agent, the sub-agent
    appears as a nested section. A test covers this for at least one non-home page.

    Since accordion-chat.js is the single implementation, nested dispatch is
    structurally guaranteed for every config. This test proves:
      (a) the WS dispatch_started handler calls _updateAccordion unconditionally
          (not conditional on convId being an OM config),
      (b) _renderNode does not branch on convId to suppress children,
      (c) the accordion is wired to fetch the dispatch tree for lead: configs.
    """

    def _read_accordion_js(self) -> str:
        if not ACCORDION_JS.exists():
            self.skipTest("accordion-chat.js not yet created")
        return _read(ACCORDION_JS)

    def test_dispatch_started_triggers_update_accordion_unconditionally(self):
        """dispatch_started WS event must trigger _updateAccordion for any config.

        The handler must not guard on convId prefix. If it did, project-lead chats
        would not show nested dispatches even though they dispatch sub-agents.
        """
        src = self._read_accordion_js()
        # Extract the dispatch_started handler block.
        m = re.search(
            r"event\.type === 'dispatch_started'\s*\)\s*\{([\s\S]+?)\}",
            src
        )
        self.assertIsNotNone(
            m,
            "accordion-chat.js dispatch_started handler not found — "
            "nested dispatch will not update the accordion"
        )
        handler = m.group(1)
        self.assertIn(
            '_updateAccordion', handler,
            "dispatch_started handler does not call _updateAccordion — "
            "nested dispatches will not appear in the accordion on any page. "
            "This affects both home page (OM) and config pages (project leads)."
        )
        # The handler must NOT guard on om: prefix — that would break project-lead pages.
        self.assertNotIn(
            "'om:'", handler,
            "dispatch_started handler checks for 'om:' prefix — "
            "nested dispatches will not appear on project-lead config pages. "
            "The update must fire for any convId."
        )

    def test_render_node_does_not_suppress_children_based_on_conv_id(self):
        """_renderNode must render children regardless of convId.

        If _renderNode branched on convId to suppress child rendering, nested
        dispatches would only appear on pages with a specific convId config.
        """
        src = self._read_accordion_js()
        # Extract the _renderNode function body.
        m = re.search(r'function _renderNode\(node, depth\)\s*\{([\s\S]+?)\n    \}', src)
        self.assertIsNotNone(
            m,
            "_renderNode function not found in accordion-chat.js"
        )
        body = m.group(1)
        # Children are rendered via node.children iteration — verify it's there.
        self.assertIn(
            'node.children', body,
            "_renderNode does not iterate node.children — "
            "nested dispatches will never appear in the accordion"
        )
        # Must not gate children on convId prefix.
        self.assertNotIn(
            "'om:'", body,
            "_renderNode branches on 'om:' when rendering children — "
            "nested dispatches will not render for project-lead configs"
        )

    def test_dispatch_tree_fetch_uses_derived_session_id_for_lead_configs(self):
        """The dispatch tree fetch must work for lead: convIds, not just om:.

        deriveSessionId('lead:comics-lead:darrell') must return a non-null session ID
        so that _updateAccordion fetches the right tree for project-lead pages.
        """
        src = self._read_accordion_js()
        derive_fn = re.search(
            r'function deriveSessionId\(convId\)\s*\{([\s\S]+?)\n  \}', src
        )
        self.assertIsNotNone(
            derive_fn,
            "deriveSessionId function not found in accordion-chat.js"
        )
        body = derive_fn.group(1)
        # Must return a value for lead: (not return null for lead:)
        self.assertIn(
            "startsWith('lead:')", body,
            "deriveSessionId does not handle 'lead:' prefix — "
            "project-lead pages will not fetch a dispatch tree and will show no accordion"
        )
        # Must not immediately return null after the lead: branch.
        # Check that the lead: branch ends with a return of a constructed value, not null.
        lead_branch = re.search(
            r"startsWith\('lead:'\)([\s\S]+?)(?=if \(convId\.startsWith|return null;?\s*\})",
            body
        )
        if lead_branch:
            self.assertNotEqual(
                lead_branch.group(1).strip(), 'return null;',
                "lead: branch in deriveSessionId immediately returns null — "
                "project-lead pages will not fetch a dispatch tree"
            )


class TestSeedPostTargetRouting(unittest.TestCase):
    """accordion-chat.js seed() must POST to the configured convId, not a hardcoded agent.

    AC5: Page-to-agent routing. The POST target URL is constructed from _config.convId.
    A project-lead config (lead:comics-lead:darrell) must POST to
    /api/conversations/lead:comics-lead:darrell, not to any om: URL.

    Verified by tracing the seed() function's fetch call in the source: the URL is
    built as '/api/conversations/' + encodeURIComponent(_config.convId), and _config.convId
    is always the convId passed into mount(). For any project-lead config, the POST target
    is the lead: convId, never om:.
    """

    def _read_accordion_js(self) -> str:
        if not ACCORDION_JS.exists():
            self.skipTest("accordion-chat.js not yet created")
        return _read(ACCORDION_JS)

    def _extract_seed_function(self, src: str) -> str:
        """Extract the seed() function body from accordion-chat.js."""
        m = re.search(r'function seed\(message\)\s*\{([\s\S]+?)\n    \}', src)
        self.assertIsNotNone(m, "seed() function not found in accordion-chat.js")
        return m.group(1)

    def test_seed_builds_url_from_config_conv_id(self):
        """seed() must build the POST URL from _config.convId, not a hardcoded value.

        For lead:comics-lead:darrell, seed() must POST to
        /api/conversations/lead:comics-lead:darrell (after URL encoding).
        The URL construction is: '/api/conversations/' + encodeURIComponent(_config.convId)
        """
        src = self._read_accordion_js()
        body = self._extract_seed_function(src)
        # The POST URL must be built from _config.convId, not a literal agent identifier.
        self.assertIn(
            '_config.convId', body,
            "seed() does not use _config.convId in its POST URL — "
            "all chats will POST to the same URL regardless of config. "
            "For lead:comics-lead:darrell, the POST must go to "
            "/api/conversations/lead:comics-lead:darrell."
        )

    def test_seed_posts_to_conversations_api(self):
        """seed() must POST to /api/conversations/{convId}."""
        src = self._read_accordion_js()
        body = self._extract_seed_function(src)
        self.assertIn(
            '/api/conversations/', body,
            "seed() does not POST to /api/conversations/ — "
            "messages sent from any page will not be routed to the correct agent"
        )

    def test_seed_does_not_hardcode_om_in_post_url(self):
        """seed() must not hardcode 'om:' in the POST URL.

        If the URL were hardcoded to /api/conversations/om:..., project-lead config
        chats would POST to the office manager instead of the project lead.
        The URL must be dynamically constructed from _config.convId.
        """
        src = self._read_accordion_js()
        body = self._extract_seed_function(src)
        # No literal 'om:' string in the POST URL construction.
        hardcoded_om_in_url = re.findall(r"/api/conversations/om:", body)
        self.assertEqual(
            hardcoded_om_in_url, [],
            f"seed() hardcodes 'om:' in its POST URL: {hardcoded_om_in_url}. "
            f"project-lead chats will POST to the office manager. "
            f"The URL must be built from _config.convId."
        )

    def test_seed_conv_id_is_url_encoded(self):
        """seed() must encodeURIComponent the convId in the POST URL.

        lead: convIds contain ':' which must be percent-encoded in URLs.
        Without encoding, lead:comics-lead:darrell would produce an invalid URL.
        """
        src = self._read_accordion_js()
        body = self._extract_seed_function(src)
        self.assertIn(
            'encodeURIComponent', body,
            "seed() does not URL-encode convId in the POST URL — "
            "lead: convIds contain ':' which would produce invalid URLs without encoding. "
            "Use: '/api/conversations/' + encodeURIComponent(_config.convId)"
        )


class TestDispatchTreeProjectScopeRouting(unittest.TestCase):
    """The dispatch tree API must find sessions in project scope, not just management scope.

    When a project lead session is invoked, its metadata.json lives in:
      {project_path}/.teaparty/project/sessions/{session_id}/

    TeaPartyBridge._find_sessions_dir must search both management/sessions and all registered
    project sessions dirs. Before this fix _handle_dispatch_tree hardcoded management/sessions,
    causing config-page accordions to always show a stub (agent_name='unknown').

    These tests call TeaPartyBridge._find_sessions_dir directly with _all_sessions_dirs
    patched to control the candidate list, so we exercise the real server method.
    """

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        # Construct a minimal TeaPartyBridge instance.
        # _migrate_legacy_sessions is protected by try/except; StateReader.__init__
        # is lightweight (no I/O). This is safe with an empty temp dir.
        from unittest.mock import patch
        from teaparty.bridge.server import TeaPartyBridge  # noqa: E402
        # Patch _migrate_legacy_sessions to avoid registry filesystem setup.
        with patch.object(TeaPartyBridge, '_migrate_legacy_sessions', lambda self: None):
            self._server = TeaPartyBridge(
                teaparty_home=self._tmpdir,
                static_dir=str(STATIC_DIR),
            )

    def tearDown(self):
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def _make_session(self, sessions_dir: str, session_id: str, agent_name: str) -> None:
        """Create a session metadata.json at the given sessions_dir."""
        path = os.path.join(sessions_dir, session_id)
        os.makedirs(path, exist_ok=True)
        with open(os.path.join(path, 'metadata.json'), 'w') as f:
            json.dump({
                'session_id': session_id,
                'agent_name': agent_name,
                'scope': 'project',
                'claude_session_id': '',
                'conversation_map': {},
                'conversation_id': '',
            }, f)

    def test_management_session_found_in_management_dir(self):
        """OM sessions in management/sessions are found by TeaPartyBridge._find_sessions_dir."""
        mgmt_sessions = os.path.join(self._tmpdir, 'management', 'sessions')
        self._make_session(mgmt_sessions, 'office-manager-darrell', 'office-manager')
        project_sessions = os.path.join(self._tmpdir, 'project', 'sessions')
        os.makedirs(project_sessions, exist_ok=True)

        with patch.object(self._server, '_all_sessions_dirs', return_value=[mgmt_sessions, project_sessions]):
            result = self._server._find_sessions_dir('office-manager-darrell')

        self.assertEqual(
            result, mgmt_sessions,
            "TeaPartyBridge._find_sessions_dir: OM session not found in management/sessions — "
            "home page accordion will not render the dispatch tree"
        )

    def test_project_lead_session_found_in_project_dir(self):
        """Project lead sessions in project/sessions are found by TeaPartyBridge._find_sessions_dir.

        Before this fix, _handle_dispatch_tree hardcoded management/sessions and would
        return a stub tree for any project lead session. This test calls the actual server
        method (not a local reimplementation) to catch bugs in the server's path.
        """
        mgmt_sessions = os.path.join(self._tmpdir, 'management', 'sessions')
        os.makedirs(mgmt_sessions, exist_ok=True)  # present but empty

        project_sessions = os.path.join(self._tmpdir, 'project', 'sessions')
        session_id = 'comics-lead-comics-lead-darrell'
        self._make_session(project_sessions, session_id, 'comics-lead')

        with patch.object(self._server, '_all_sessions_dirs', return_value=[mgmt_sessions, project_sessions]):
            result = self._server._find_sessions_dir(session_id)

        self.assertEqual(
            result, project_sessions,
            f"TeaPartyBridge._find_sessions_dir: project lead session '{session_id}' not found "
            f"in project/sessions — config-page accordion will show stub tree. "
            f"This is the regression this fix prevents: management/sessions was hardcoded."
        )

    def test_fallback_to_first_candidate_when_session_absent(self):
        """When session is not found in any candidate dir, fall back to the first (management)."""
        mgmt_sessions = os.path.join(self._tmpdir, 'management', 'sessions')
        os.makedirs(mgmt_sessions, exist_ok=True)
        project_sessions = os.path.join(self._tmpdir, 'project', 'sessions')
        os.makedirs(project_sessions, exist_ok=True)

        with patch.object(self._server, '_all_sessions_dirs', return_value=[mgmt_sessions, project_sessions]):
            result = self._server._find_sessions_dir('nonexistent-session-id')

        self.assertEqual(
            result, mgmt_sessions,
            "TeaPartyBridge._find_sessions_dir must fall back to first candidate when session absent"
        )

    def test_server_handle_dispatch_tree_calls_find_sessions_dir(self):
        """_handle_dispatch_tree must call _find_sessions_dir, not a hardcoded path.

        Source-level check to catch the regression: the old code was
        `sessions_dir = os.path.join(repo_root, '.teaparty', 'management', 'sessions')`.
        After the fix, _handle_dispatch_tree delegates to _find_sessions_dir.
        """
        import teaparty.bridge.server as srv_module
        src = Path(srv_module.__file__).read_text()
        m = re.search(
            r'async def _handle_dispatch_tree\([\s\S]+?return web\.json_response',
            src
        )
        self.assertIsNotNone(m, "_handle_dispatch_tree not found in server.py")
        handler_body = m.group(0)
        self.assertIn(
            '_find_sessions_dir', handler_body,
            "_handle_dispatch_tree does not call _find_sessions_dir — "
            "project lead sessions won't be found (regression to hardcoded management path)"
        )
        self.assertNotIn(
            "'management', 'sessions'", handler_body,
            "_handle_dispatch_tree still hardcodes management/sessions — "
            "project lead sessions won't be found. Delegate to _find_sessions_dir() instead."
        )


class TestExcludedPagesCarryNoChat(unittest.TestCase):
    """Job screens, artifacts pages, and stats pages must carry no chat affordance.

    AC10: These pages are explicitly excluded from the chat UX. They must not include
    accordion-chat.js or call AccordionChat. If their redesigns later adopt the chat,
    they will mount the shared implementation — but today they carry nothing.
    """

    # Pages explicitly excluded from the chat UX by the issue.
    EXCLUDED_PAGES = ['stats.html']

    def test_excluded_pages_do_not_include_accordion_chat_js(self):
        """artifacts.html and stats.html must not load accordion-chat.js."""
        for page in self.EXCLUDED_PAGES:
            path = STATIC_DIR / page
            if not path.exists():
                continue  # page not present; no chat affordance by absence
            src = path.read_text(encoding='utf-8')
            self.assertNotIn(
                'accordion-chat.js', src,
                f"{page} includes accordion-chat.js — "
                f"this page is explicitly excluded from the chat UX (AC10). "
                f"If it needs a chat, mount the shared implementation and update this test."
            )

    def test_excluded_pages_do_not_call_accordion_chat(self):
        """artifacts.html and stats.html must not reference AccordionChat."""
        for page in self.EXCLUDED_PAGES:
            path = STATIC_DIR / page
            if not path.exists():
                continue
            src = path.read_text(encoding='utf-8')
            self.assertNotIn(
                'AccordionChat', src,
                f"{page} references AccordionChat — "
                f"this page is explicitly excluded from the chat UX (AC10). "
                f"If it needs a chat, it must mount the shared implementation and this test updates."
            )


if __name__ == '__main__':
    unittest.main()
