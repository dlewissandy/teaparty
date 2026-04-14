"""Specification tests for issue #410: artifact navigator pin toggle.

Each file/directory row in the artifact navigator must have a pin slot on
its right side. When unpinned the slot is empty (no visual clutter); when
pinned it shows a pushpin icon. Clicking the slot toggles pin state.

Pins are scope-aware: the page knows its scope (project/agent/workgroup/system)
from URL parameters and targets the correct pins.yaml for that scope via a
PATCH /api/pins endpoint.

These tests are load-bearing: each would fail if the feature were reverted.
"""
import os
import re
import shutil
import tempfile
import unittest
from pathlib import Path


STATIC_DIR = Path(__file__).resolve().parent.parent.parent / "teaparty" / "bridge" / "static"
SERVER_PY   = Path(__file__).resolve().parent.parent.parent / "teaparty" / "bridge" / "server.py"
CONFIG_PY   = Path(__file__).resolve().parent.parent.parent / "teaparty" / "config" / "config_reader.py"
ARTIFACT_JS = STATIC_DIR / "artifact-page.js"
ARTIFACTS_HTML = STATIC_DIR / "artifacts.html"
CONFIG_HTML    = STATIC_DIR / "config.html"
STYLES_CSS     = STATIC_DIR / "styles.css"


def _read(path: Path) -> str:
    return path.read_text(encoding='utf-8')


def _make_tmp(tc: unittest.TestCase) -> str:
    tmp = tempfile.mkdtemp(prefix='teaparty-test-410-')
    tc.addCleanup(shutil.rmtree, tmp, True)
    return tmp


# ── config_reader: add_pin ────────────────────────────────────────────────────

class TestAddPin(unittest.TestCase):
    """add_pin(scope_dir, path_root, abs_path, label) must persist a relative-path
    entry to pins.yaml, creating the file if absent.
    """

    def _import(self):
        from teaparty.config.config_reader import add_pin
        return add_pin

    def test_add_pin_function_exists(self):
        try:
            from teaparty.config import config_reader  # noqa: F401
            self.assertTrue(
                hasattr(config_reader, 'add_pin'),
                "add_pin not found in config_reader — required for pin toggle feature"
            )
        except ImportError as e:
            self.fail(f"Could not import config_reader: {e}")

    def test_add_pin_creates_pins_yaml(self):
        """add_pin must create pins.yaml when it does not exist."""
        add_pin = self._import()
        tmp = _make_tmp(self)
        scope_dir = os.path.join(tmp, 'scope')
        path_root = tmp
        abs_path = os.path.join(tmp, 'docs', 'readme.md')

        add_pin(scope_dir, path_root, abs_path, 'readme.md')

        pins_file = os.path.join(scope_dir, 'pins.yaml')
        self.assertTrue(os.path.isfile(pins_file),
            "add_pin must create pins.yaml in scope_dir")

    def test_add_pin_stores_relative_path(self):
        """Stored path must be relative to path_root, not absolute."""
        import yaml
        add_pin = self._import()
        tmp = _make_tmp(self)
        scope_dir = os.path.join(tmp, 'scope')
        path_root = tmp
        abs_path = os.path.join(tmp, 'docs', 'readme.md')

        add_pin(scope_dir, path_root, abs_path, 'readme.md')

        with open(os.path.join(scope_dir, 'pins.yaml')) as f:
            pins = yaml.safe_load(f)
        self.assertIsInstance(pins, list)
        self.assertEqual(len(pins), 1)
        stored_path = pins[0]['path']
        self.assertFalse(os.path.isabs(stored_path),
            f"Stored path must be relative, got: {stored_path!r}")
        self.assertIn('readme.md', stored_path)

    def test_add_pin_idempotent(self):
        """Pinning an already-pinned path must not create duplicate entries."""
        import yaml
        add_pin = self._import()
        tmp = _make_tmp(self)
        scope_dir = os.path.join(tmp, 'scope')
        path_root = tmp
        abs_path = os.path.join(tmp, 'docs', 'readme.md')

        add_pin(scope_dir, path_root, abs_path, 'readme.md')
        add_pin(scope_dir, path_root, abs_path, 'readme.md')

        with open(os.path.join(scope_dir, 'pins.yaml')) as f:
            pins = yaml.safe_load(f)
        self.assertEqual(len(pins), 1,
            "Pinning the same path twice must not create duplicate entries")

    def test_add_pin_appends_to_existing(self):
        """Adding a second distinct path appends without clobbering the first."""
        import yaml
        add_pin = self._import()
        tmp = _make_tmp(self)
        scope_dir = os.path.join(tmp, 'scope')
        path_root = tmp
        abs_a = os.path.join(tmp, 'a.md')
        abs_b = os.path.join(tmp, 'b.md')

        add_pin(scope_dir, path_root, abs_a, 'a.md')
        add_pin(scope_dir, path_root, abs_b, 'b.md')

        with open(os.path.join(scope_dir, 'pins.yaml')) as f:
            pins = yaml.safe_load(f)
        self.assertEqual(len(pins), 2,
            "Two distinct paths must produce two pin entries")


# ── config_reader: remove_pin ─────────────────────────────────────────────────

class TestRemovePin(unittest.TestCase):
    """remove_pin(scope_dir, path_root, abs_path) must remove the matching entry
    from pins.yaml without touching other entries.
    """

    def _import(self):
        from teaparty.config.config_reader import add_pin, remove_pin
        return add_pin, remove_pin

    def test_remove_pin_function_exists(self):
        try:
            from teaparty.config import config_reader  # noqa: F401
            self.assertTrue(
                hasattr(config_reader, 'remove_pin'),
                "remove_pin not found in config_reader — required for pin toggle feature"
            )
        except ImportError as e:
            self.fail(f"Could not import config_reader: {e}")

    def test_remove_pin_removes_entry(self):
        """remove_pin must delete the matching entry from pins.yaml."""
        import yaml
        add_pin, remove_pin = self._import()
        tmp = _make_tmp(self)
        scope_dir = os.path.join(tmp, 'scope')
        path_root = tmp
        abs_path = os.path.join(tmp, 'docs', 'readme.md')

        add_pin(scope_dir, path_root, abs_path, 'readme.md')
        remove_pin(scope_dir, path_root, abs_path)

        with open(os.path.join(scope_dir, 'pins.yaml')) as f:
            pins = yaml.safe_load(f) or []
        self.assertEqual(pins, [],
            "remove_pin must leave pins.yaml empty after removing the sole entry")

    def test_remove_pin_does_not_affect_other_entries(self):
        """Removing one pin must leave other entries intact."""
        import yaml
        add_pin, remove_pin = self._import()
        tmp = _make_tmp(self)
        scope_dir = os.path.join(tmp, 'scope')
        path_root = tmp
        abs_a = os.path.join(tmp, 'a.md')
        abs_b = os.path.join(tmp, 'b.md')

        add_pin(scope_dir, path_root, abs_a, 'a.md')
        add_pin(scope_dir, path_root, abs_b, 'b.md')
        remove_pin(scope_dir, path_root, abs_a)

        with open(os.path.join(scope_dir, 'pins.yaml')) as f:
            pins = yaml.safe_load(f) or []
        self.assertEqual(len(pins), 1,
            "remove_pin must only remove the matching entry")
        self.assertIn('b.md', pins[0]['path'])

    def test_remove_pin_noop_when_not_pinned(self):
        """Removing a path that is not pinned must not raise and must not corrupt pins."""
        import yaml
        add_pin, remove_pin = self._import()
        tmp = _make_tmp(self)
        scope_dir = os.path.join(tmp, 'scope')
        path_root = tmp
        abs_a = os.path.join(tmp, 'a.md')
        abs_b = os.path.join(tmp, 'b.md')

        add_pin(scope_dir, path_root, abs_a, 'a.md')
        # remove_pin on a path that was never added must not raise
        try:
            remove_pin(scope_dir, path_root, abs_b)
        except Exception as e:
            self.fail(f"remove_pin must not raise when path is not pinned: {e}")

        with open(os.path.join(scope_dir, 'pins.yaml')) as f:
            pins = yaml.safe_load(f) or []
        self.assertEqual(len(pins), 1,
            "remove_pin must not corrupt other entries when path is not found")

    def test_remove_pin_noop_when_no_pins_file(self):
        """remove_pin on a scope with no pins.yaml must not raise."""
        _, remove_pin = self._import()
        tmp = _make_tmp(self)
        scope_dir = os.path.join(tmp, 'scope')
        path_root = tmp
        abs_path = os.path.join(tmp, 'x.md')

        try:
            remove_pin(scope_dir, path_root, abs_path)
        except Exception as e:
            self.fail(f"remove_pin must not raise when pins.yaml is absent: {e}")


# ── Server: PATCH /api/pins endpoint ─────────────────────────────────────────

class TestPinsPatchEndpoint(unittest.TestCase):
    """The server must expose PATCH /api/pins for scope-targeted pin mutation.

    The existing PATCH /api/artifacts/{project}/pins is a full-replace endpoint
    for project scope only. The new endpoint must support all scopes via query
    params (?scope=&name=&project=) and accept {"add": {path, label}} or {"remove": {path}}.
    """

    def test_patch_api_pins_route_registered(self):
        """server.py must register PATCH /api/pins."""
        src = _read(SERVER_PY)
        self.assertIn("add_patch('/api/pins'", src,
            "PATCH /api/pins route not registered in server.py — "
            "scope-aware pin toggle has no server endpoint")

    def test_patch_api_pins_handler_exists(self):
        """server.py must define a handler for PATCH /api/pins."""
        src = _read(SERVER_PY)
        # The handler referenced in add_patch('/api/pins', self._handle_pins_patch)
        self.assertTrue(
            '_handle_pins_patch' in src or '_handle_pin_toggle' in src,
            "No handler for PATCH /api/pins found in server.py — "
            "the route is registered but has no implementation"
        )

    def test_patch_handler_calls_add_pin_or_remove_pin(self):
        """The PATCH /api/pins handler must delegate to add_pin or remove_pin."""
        src = _read(SERVER_PY)
        self.assertTrue(
            'add_pin' in src and 'remove_pin' in src,
            "server.py handler must call add_pin and remove_pin from config_reader"
        )

    def test_patch_handler_uses_discriminated_body_format(self):
        """Handler must parse {add: {path, label}} or {remove: {path}} body format."""
        src = _read(SERVER_PY)
        # The handler must discriminate on 'add' and 'remove' keys in the body,
        # not a generic 'action' field.
        self.assertTrue(
            "'add' in body" in src or '"add" in body' in src or "body['add']" in src or 'body["add"]' in src,
            "Handler does not parse 'add' key from body — must use discriminated union format"
        )
        self.assertTrue(
            "'remove' in body" in src or '"remove" in body' in src or "body['remove']" in src or 'body["remove"]' in src,
            "Handler does not parse 'remove' key from body — must use discriminated union format"
        )

    def test_patch_handler_imports_add_remove_pin(self):
        """The handler must import both add_pin and remove_pin from config_reader."""
        src = _read(SERVER_PY)
        self.assertIn('add_pin', src,
            "add_pin not found in server.py")
        self.assertIn('remove_pin', src,
            "remove_pin not found in server.py")


# ── artifact-page.js: _togglePin and scope-aware fetchPins ───────────────────

class TestArtifactPagePinToggle(unittest.TestCase):
    """artifact-page.js must expose a pin toggle function and use scope params
    when fetching pins.
    """

    def test_toggle_pin_function_exists(self):
        """artifact-page.js must define a _togglePin (or togglePin) function."""
        src = _read(ARTIFACT_JS)
        self.assertTrue(
            '_togglePin' in src or 'togglePin' in src,
            "_togglePin not found in artifact-page.js — "
            "clicking a pin slot has no handler"
        )

    def test_fetch_pins_uses_scope_params(self):
        """fetchPins must include scope/name/project query params, not just project path."""
        src = _read(ARTIFACT_JS)
        # The old hardcoded URL: /api/artifacts/{project}/pins
        # The new URL: /api/pins?scope=...&name=...&project=...
        self.assertIn('/api/pins', src,
            "fetchPins must call /api/pins (scope-aware) not /api/artifacts/{project}/pins")
        # Must pass scope param
        self.assertTrue(
            'scope' in src and ('pinScope' in src or '_config.pinScope' in src or 'scope=' in src),
            "fetchPins must pass the scope parameter to /api/pins"
        )

    def test_artifact_nav_pin_css_class_referenced(self):
        """artifact-page.js must reference artifact-nav-pin class for the pin slot."""
        src = _read(ARTIFACT_JS)
        self.assertIn('artifact-nav-pin', src,
            "artifact-nav-pin class not found in artifact-page.js — "
            "pin slot has no DOM representation in rendered rows")

    def test_toggle_pin_exposed_on_global(self):
        """_togglePin must be exposed on ArtifactPage so onclick handlers can call it."""
        src = _read(ARTIFACT_JS)
        self.assertTrue(
            'ArtifactPage._togglePin' in src or "ArtifactPage['_togglePin']" in src,
            "_togglePin not exposed on ArtifactPage global — "
            "onclick='ArtifactPage._togglePin(...)' in nav rows would silently fail"
        )

    def test_pin_slot_in_render_file_tree(self):
        """_renderFileTree must emit an artifact-nav-pin slot for each file/dir row.

        The slot variables (dirPinSlot, filePinSlot) are unique to _renderFileTree;
        asserting on them is unambiguous even though the function is nested inside _render().
        """
        src = _read(ARTIFACT_JS)
        self.assertIn('dirPinSlot', src,
            "dirPinSlot not found in artifact-page.js — "
            "directory rows in _renderFileTree have no pin slot")
        self.assertIn('filePinSlot', src,
            "filePinSlot not found in artifact-page.js — "
            "file rows in _renderFileTree have no pin slot")

    def test_pin_slot_in_render_pinned_nodes(self):
        """_renderPinnedNodes must check _pinnedPathSet to decide pin icon per node.

        When a pinned dir is expanded, its children include non-pinned items.
        Rendering all children with artifact-nav-pin.pinned was wrong — it showed
        pushpin icons on items the user never pinned.  The fix uses isPinned to
        conditionally apply .pinned so only items in _pinnedPathSet get the icon.
        """
        src = _read(ARTIFACT_JS)
        pn_match = re.search(r'function _renderPinnedNodes\b(.+?)(?=\n  function |\n  var |\Z)',
                              src, re.DOTALL)
        self.assertIsNotNone(pn_match,
            "_renderPinnedNodes not found in artifact-page.js")
        pn_body = pn_match.group(0)
        self.assertIn('_pinnedPathSet[node.path]', pn_body,
            "_renderPinnedNodes must check _pinnedPathSet[node.path] to determine "
            "whether each node is pinned — hardcoding .pinned for all rows is wrong")
        self.assertIn('isPinned', pn_body,
            "_renderPinnedNodes must use an isPinned variable to conditionally apply "
            "the .pinned class and pushpin icon")

    def test_init_and_refresh_call_scope_aware_fetch_pins(self):
        """_init() and _refresh() must call fetchPins() for scope-aware pin loading.

        The legacy /api/artifacts/{project}/pins endpoint is project-scope only.
        Using it directly in _init/_refresh breaks scopes other than project (criterion 5)
        and leaves _pinnedPathSet empty on load (breaking criterion 1 in the file tree).
        """
        src = _read(ARTIFACT_JS)
        # Confirm the legacy endpoint does NOT appear in _init or _refresh body
        # (it may appear in _handle_artifact_pins in server.py, but not here)
        legacy_url = "'/api/artifacts/' + encodeURIComponent(project) + '/pins'"
        # Count occurrences — at most 0 from _init/_refresh (they were replaced with fetchPins())
        occurrences = src.count(legacy_url)
        self.assertEqual(occurrences, 0,
            f"Legacy /api/artifacts/{{project}}/pins URL still present {occurrences} time(s) in "
            "artifact-page.js — _init/_refresh must use fetchPins() for scope-aware loading"
        )

    def test_toggle_pin_calls_fetch_pins_then_render(self):
        """_togglePin must call fetchPins() then _render() so the count header updates.

        Criterion 8: the pinned count button ('Pinned (N)') derives from
        _pinnedNodes.length, which is only updated by fetchPins(). Dropping
        either call from _togglePin would leave the header stale after toggle.
        """
        src = _read(ARTIFACT_JS)
        # Find _togglePin function body
        toggle_match = re.search(r'async function _togglePin\b(.+?)(?=\n  async function |\n  function |\n  var |\Z)',
                                  src, re.DOTALL)
        self.assertIsNotNone(toggle_match,
            "_togglePin not found in artifact-page.js")
        body = toggle_match.group(0)
        self.assertIn('fetchPins()', body,
            "_togglePin must call fetchPins() to update _pinnedNodes and count header")
        self.assertIn('_render()', body,
            "_togglePin must call _render() so count header re-renders after pin change")

    def test_folder_row_onclick_guards_against_pin_slot_click(self):
        """Folder row onclick must not fire _toggleFolder when click originates from pin slot.

        Without this guard, clicking the pin span inside a folder div bubbles to the
        parent onclick even after event.stopPropagation() in the child — causing
        _toggleFolder to fire alongside _togglePin. The guard checks event.target
        so that _toggleFolder only runs when the click is NOT on the pin slot.
        """
        src = _read(ARTIFACT_JS)
        # Both _renderPinnedNodes and _renderFileTree must guard folder onclick
        folder_onclicks = re.findall(
            r"onclick=\"if\(!event\.target\.classList\.contains\(\\'artifact-nav-pin\\'\)\)ArtifactPage\._toggleFolder",
            src,
        )
        self.assertGreaterEqual(len(folder_onclicks), 2,
            "Folder row onclick must guard against artifact-nav-pin clicks in "
            "both _renderPinnedNodes and _renderFileTree — found "
            f"{len(folder_onclicks)} guarded call(s), expected at least 2")

    def test_auto_expand_for_filters_always_expands_pinned_ancestors(self):
        """_autoExpandForFilters must expand ancestors of pinned files unconditionally.

        Previously it returned early when _filterPinned was false, so the minimum
        tree for pinned items was never built on initial load — the user had to toggle
        the Pinned filter twice to trigger expansion.  The fix removes the early-exit
        guard and always includes pinned file paths in the expansion targets.
        """
        src = _read(ARTIFACT_JS)
        fn_match = re.search(
            r'async function _autoExpandForFilters\b(.+?)(?=\n  async function |\n  function |\n  var |\Z)',
            src, re.DOTALL)
        self.assertIsNotNone(fn_match, "_autoExpandForFilters not found in artifact-page.js")
        body = fn_match.group(0)
        # Must NOT short-circuit on filter state
        self.assertNotIn('if (!_filterPinned && !_filterChanged) return', body,
            "_autoExpandForFilters must not skip expansion when filters are off — "
            "pinned minimum tree should always be built")
        # Must walk _pinnedNodes unconditionally (not inside an if (_filterPinned) block)
        self.assertIn('_pinnedNodes', body,
            "_autoExpandForFilters must walk _pinnedNodes to collect pinned file paths")

    def test_auto_expand_builds_minimum_tree_for_pinned_only_view(self):
        """_autoExpandForFilters must expand pinned dirs that contain other pinned items
        when _repoFiles is empty (management scope with no worktree).

        Without this, the pinned-only view shows a flat list even when some pinned
        items are children of other pinned dirs — the tree structure is invisible.
        """
        src = _read(ARTIFACT_JS)
        fn_match = re.search(
            r'async function _autoExpandForFilters\b(.+?)(?=\n  async function |\n  function |\n  var |\Z)',
            src, re.DOTALL)
        self.assertIsNotNone(fn_match, "_autoExpandForFilters not found in artifact-page.js")
        body = fn_match.group(0)
        self.assertIn('_repoFiles.length === 0', body,
            "_autoExpandForFilters must handle the no-repo case (management scope) "
            "by expanding pinned dirs whose children are also pinned")
        self.assertIn('startsWith(dirPrefix)', body,
            "_autoExpandForFilters must detect pinned items that are children of "
            "other pinned dirs via startsWith(dirPrefix)")


# ── artifacts.html: scope URL params ─────────────────────────────────────────

class TestArtifactsHtmlScopeParams(unittest.TestCase):
    """artifacts.html must read scope and name from URL params and pass them
    to ArtifactPage.mount() so the page targets the correct pins.yaml.
    """

    def test_scope_param_read_from_url(self):
        """artifacts.html must read a 'scope' param from the URL."""
        src = _read(ARTIFACTS_HTML)
        self.assertTrue(
            "params.get('scope')" in src or 'params.get("scope")' in src,
            "artifacts.html does not read 'scope' URL param — "
            "pin toggle has no way to know which scope to target"
        )

    def test_name_param_read_from_url(self):
        """artifacts.html must read a 'name' param from the URL (agent/workgroup/job name)."""
        src = _read(ARTIFACTS_HTML)
        self.assertTrue(
            "params.get('name')" in src or 'params.get("name")' in src,
            "artifacts.html does not read 'name' URL param — "
            "agent and workgroup scopes cannot identify their target"
        )

    def test_scope_passed_to_mount(self):
        """artifacts.html must pass pinScope (or scope) to ArtifactPage.mount()."""
        src = _read(ARTIFACTS_HTML)
        self.assertTrue(
            'pinScope' in src or "'scope':" in src or '"scope":' in src,
            "pinScope not passed to ArtifactPage.mount() — "
            "the page will not know which scope's pins to show"
        )

    def test_name_passed_to_mount(self):
        """artifacts.html must pass pinName (or name) to ArtifactPage.mount()."""
        src = _read(ARTIFACTS_HTML)
        self.assertTrue(
            'pinName' in src or "'name':" in src or '"name":' in src,
            "pinName not passed to ArtifactPage.mount() — "
            "agent/workgroup scopes will have no target name"
        )


# ── config.html: scope forwarding in pin item links ──────────────────────────

class TestConfigHtmlScopeForwarding(unittest.TestCase):
    """config.html renders pinned-item links as artifacts.html?file=...
    Each call site must also forward scope and name so that artifacts.html
    opens in the correct scope context (and pin toggles go to the right scope).

    Four call sites in config.html:
      1. Global/system pins (line ~292)
      2. Project pins (line ~352)
      3. Workgroup pins (line ~427)
      4. Agent pins (line ~521)
    """

    def test_render_pin_items_accepts_scope_context(self):
        """renderPinItems (or equivalent) must accept scope context as a parameter."""
        src = _read(CONFIG_HTML)
        # The function must be defined with at least two params (pins + scope context)
        matches = re.findall(r'function renderPinItems\s*\(([^)]*)\)', src)
        self.assertTrue(len(matches) > 0,
            "renderPinItems not found in config.html")
        params_str = matches[0]
        param_count = len([p for p in params_str.split(',') if p.strip()])
        self.assertGreaterEqual(param_count, 2,
            f"renderPinItems has only {param_count} param(s); "
            "must accept scope context as a second parameter"
        )

    def test_artifacts_links_include_scope_param(self):
        """Links generated by renderPinItems must include scope= in the URL."""
        src = _read(CONFIG_HTML)
        # The link construction in renderPinItems must include scope
        # Find the renderPinItems function body
        fn_match = re.search(r'function renderPinItems\b(.+?)(?=\nfunction |\n</script>|\Z)',
                              src, re.DOTALL)
        self.assertIsNotNone(fn_match,
            "renderPinItems function body not found in config.html")
        fn_body = fn_match.group(0)
        self.assertIn('scope', fn_body,
            "renderPinItems does not include scope in generated artifact links — "
            "clicking a pinned item will open artifacts.html without scope context"
        )

    def test_project_call_site_passes_scope(self):
        """The project-level renderPinItems call must pass scope:'project' in the same call."""
        src = _read(CONFIG_HTML)
        # Match the scope key with a value of 'project' within a renderPinItems call
        self.assertTrue(
            re.search(r"renderPinItems\([^)]*scope\s*:\s*'project'", src) or
            re.search(r'renderPinItems\([^)]*scope\s*:\s*"project"', src),
            "Project-level renderPinItems call does not pass scope:'project' — "
            "links to artifacts.html will open without scope context"
        )

    def test_agent_call_site_passes_scope(self):
        """The agent-level renderPinItems call must pass scope='agent' in the same call."""
        src = _read(CONFIG_HTML)
        self.assertTrue(
            re.search(r"renderPinItems\([^)]*'agent'", src) or
            re.search(r'renderPinItems\([^)]*"agent"', src),
            "Agent-level renderPinItems call does not pass 'agent' scope — "
            "links to artifacts.html will open without scope context"
        )

    def test_workgroup_call_site_passes_scope(self):
        """The workgroup-level renderPinItems call must pass scope='workgroup' in the same call."""
        src = _read(CONFIG_HTML)
        self.assertTrue(
            re.search(r"renderPinItems\([^)]*'workgroup'", src) or
            re.search(r'renderPinItems\([^)]*"workgroup"', src),
            "Workgroup-level renderPinItems call does not pass 'workgroup' scope — "
            "links to artifacts.html will open without scope context"
        )


# ── styles.css: artifact-nav-pin class ───────────────────────────────────────

class TestPinSlotCss(unittest.TestCase):
    """styles.css must define the artifact-nav-pin class used by pin slots."""

    def test_artifact_nav_pin_class_defined(self):
        """styles.css must define .artifact-nav-pin."""
        src = _read(STYLES_CSS)
        self.assertIn('.artifact-nav-pin', src,
            ".artifact-nav-pin not defined in styles.css — "
            "pin slots will have no styling")

    def test_pin_slot_has_fixed_width(self):
        """The pin slot must have a fixed width so it does not shift content."""
        src = _read(STYLES_CSS)
        # Find the .artifact-nav-pin rule
        pin_block = re.search(r'\.artifact-nav-pin\s*\{([^}]*)\}', src, re.DOTALL)
        self.assertIsNotNone(pin_block,
            ".artifact-nav-pin rule not found in styles.css")
        rule_body = pin_block.group(1)
        self.assertIn('width', rule_body,
            ".artifact-nav-pin must have an explicit width to prevent layout shift")

    def test_unpinned_slot_has_no_pointer_cursor(self):
        """The base pin slot (unpinned) must not show a pointer cursor.

        The spec says there is no hover state on unpinned items. The pointer
        cursor is an affordance; it must only appear on the .pinned variant.
        """
        src = _read(STYLES_CSS)
        # Find the .artifact-nav-pin rule (without .pinned modifier)
        pin_base = re.search(r'\.artifact-nav-pin\s*\{([^}]*)\}', src, re.DOTALL)
        self.assertIsNotNone(pin_base, ".artifact-nav-pin rule not found")
        base_body = pin_base.group(1)
        self.assertNotIn('pointer', base_body,
            ".artifact-nav-pin base rule must not have cursor:pointer — "
            "spec requires no hover affordance on unpinned items"
        )
        # .pinned must have pointer
        pinned_block = re.search(r'\.artifact-nav-pin\.pinned\s*\{([^}]*)\}', src, re.DOTALL)
        self.assertIsNotNone(pinned_block,
            ".artifact-nav-pin.pinned rule not found in styles.css")
        pinned_body = pinned_block.group(1)
        self.assertIn('pointer', pinned_body,
            ".artifact-nav-pin.pinned must have cursor:pointer"
        )
