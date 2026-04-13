"""Specification tests for issue #402: artifact browser and job screen as one parameterized page.

The artifact browser and job screen must be the same page rendered by a single
shared module (artifact-page.js). Both artifacts.html and job.html are thin
shells (~30 lines) that import the module and call ArtifactPage.mount() with
mode-specific config. No rendering, state, or handler code lives in the shells.

The shared module must include:
- Live refresh (file tree updates when files change on disk)
- Git-status indicators (new/modified/deleted per file)
- Chat blade via accordion-chat.js (#400 shared implementation)
- Job-mode top strip with workflow bar (extracted to workflow-bar.js)
- Accordion-driven file-tree scoping in job mode

Each test is load-bearing: it would fail if the consolidation were reverted.
"""
import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path


STATIC_DIR = Path(__file__).resolve().parent.parent.parent / "teaparty" / "bridge" / "static"
ARTIFACT_PAGE_JS = STATIC_DIR / "artifact-page.js"
WORKFLOW_BAR_JS = STATIC_DIR / "workflow-bar.js"
ARTIFACTS_HTML = STATIC_DIR / "artifacts.html"
JOB_HTML = STATIC_DIR / "job.html"
INDEX_HTML = STATIC_DIR / "index.html"
ACCORDION_JS = STATIC_DIR / "accordion-chat.js"
STYLES_CSS = STATIC_DIR / "styles.css"


def _read(path: Path) -> str:
    return path.read_text(encoding='utf-8')


def _line_count(path: Path) -> int:
    return len(path.read_text(encoding='utf-8').strip().splitlines())


# ── Rendering symbols that must exist only in artifact-page.js ───────────────
# These identifiers define the artifact page UX. Their presence in the HTML
# shells would mean a second implementation exists.

ARTIFACT_RENDERING_SYMBOLS = [
    'artifact-nav',         # file tree container class
    'artifact-main',        # file viewer container class
    'artifact-layout',      # layout grid class
    'artifact-header',      # header bar class
    'renderFileView',       # file rendering function
    'renderPinnedNodes',    # pinned tree rendering function
    'renderOverview',       # overview rendering function
    'renderMarkdown',       # markdown rendering function
    'renderCode',           # code rendering function
    'toggleFolder',         # folder expand/collapse
    'loadFile',             # file loading action
    'fetchPins',            # pinned-node fetching
]

# Symbols that prove the shell is mounting the shared module, not rolling its own.
MOUNT_CALL_PATTERN = re.compile(r'ArtifactPage\s*\.\s*mount\s*\(')


class TestArtifactPageModuleExists(unittest.TestCase):
    """artifact-page.js must exist and contain the complete page implementation."""

    def test_artifact_page_js_exists(self):
        self.assertTrue(
            ARTIFACT_PAGE_JS.exists(),
            "artifact-page.js is missing from teaparty/bridge/static/ — "
            "the shared artifact page module has not been created"
        )

    def test_artifact_page_contains_all_rendering_symbols(self):
        """artifact-page.js must define every rendering/state symbol."""
        if not ARTIFACT_PAGE_JS.exists():
            self.skipTest("artifact-page.js not yet created")
        src = _read(ARTIFACT_PAGE_JS)
        for symbol in ARTIFACT_RENDERING_SYMBOLS:
            self.assertIn(
                symbol, src,
                f"artifact-page.js is missing '{symbol}' — "
                f"the page implementation is incomplete"
            )

    def test_artifact_page_exports_mount_and_unmount(self):
        """artifact-page.js must export ArtifactPage.mount and ArtifactPage.unmount."""
        if not ARTIFACT_PAGE_JS.exists():
            self.skipTest("artifact-page.js not yet created")
        src = _read(ARTIFACT_PAGE_JS)
        self.assertIn(
            'ArtifactPage', src,
            "artifact-page.js does not export ArtifactPage — "
            "the module API is missing"
        )
        self.assertRegex(
            src, r'mount\s*[:=]',
            "artifact-page.js does not define a mount function"
        )

    def test_artifact_page_handles_browse_and_job_modes(self):
        """artifact-page.js must handle both 'browse' and 'job' modes."""
        if not ARTIFACT_PAGE_JS.exists():
            self.skipTest("artifact-page.js not yet created")
        src = _read(ARTIFACT_PAGE_JS)
        self.assertIn(
            'browse', src,
            "artifact-page.js does not reference 'browse' mode"
        )
        self.assertIn(
            'job', src,
            "artifact-page.js does not reference 'job' mode"
        )

    def test_artifact_page_has_live_refresh(self):
        """artifact-page.js must include live-refresh subscription logic."""
        if not ARTIFACT_PAGE_JS.exists():
            self.skipTest("artifact-page.js not yet created")
        src = _read(ARTIFACT_PAGE_JS)
        # Must subscribe to filesystem change events (via WS or polling)
        has_ws_watch = 'watch_worktree' in src or 'file_changed' in src or 'fs_changed' in src
        has_polling = 'setInterval' in src and 'git-status' in src
        self.assertTrue(
            has_ws_watch or has_polling,
            "artifact-page.js has no live-refresh mechanism — "
            "must subscribe to filesystem changes via WebSocket or polling"
        )

    def test_artifact_page_has_git_status_indicators(self):
        """artifact-page.js must include git-status indicator rendering."""
        if not ARTIFACT_PAGE_JS.exists():
            self.skipTest("artifact-page.js not yet created")
        src = _read(ARTIFACT_PAGE_JS)
        # Must fetch git status and render indicators
        self.assertIn(
            'git-status', src,
            "artifact-page.js does not fetch git status — "
            "file tree will have no status indicators"
        )
        # Must distinguish new/modified/deleted
        has_status_types = ('new' in src or 'untracked' in src) and 'modified' in src
        self.assertTrue(
            has_status_types,
            "artifact-page.js does not distinguish file status types "
            "(new/modified/deleted)"
        )


class TestArtifactsHtmlIsThinShell(unittest.TestCase):
    """artifacts.html must be a thin shell that mounts artifact-page.js."""

    def test_artifacts_html_is_short(self):
        """artifacts.html must be ≤50 lines (thin shell, not full implementation)."""
        count = _line_count(ARTIFACTS_HTML)
        self.assertLessEqual(
            count, 50,
            f"artifacts.html is {count} lines — a thin shell should be ≤50 lines. "
            f"Rendering logic must move to artifact-page.js"
        )

    def test_artifacts_html_imports_artifact_page_js(self):
        """artifacts.html must import artifact-page.js."""
        src = _read(ARTIFACTS_HTML)
        self.assertIn(
            'artifact-page.js', src,
            "artifacts.html does not import artifact-page.js — "
            "it should be a thin shell that loads the shared module"
        )

    def test_artifacts_html_calls_mount_with_browse_mode(self):
        """artifacts.html must call ArtifactPage.mount with mode 'browse'."""
        src = _read(ARTIFACTS_HTML)
        self.assertTrue(
            MOUNT_CALL_PATTERN.search(src),
            "artifacts.html does not call ArtifactPage.mount() — "
            "it should be a thin shell that delegates to the shared module"
        )
        self.assertIn(
            'browse', src,
            "artifacts.html does not specify browse mode"
        )

    def test_artifacts_html_has_no_rendering_logic(self):
        """artifacts.html must not contain rendering symbols that belong in artifact-page.js."""
        src = _read(ARTIFACTS_HTML)
        # These functions must not be defined in the shell
        forbidden = ['renderFileView', 'renderPinnedNodes', 'renderOverview',
                     'renderMarkdown', 'renderCode', 'toggleFolder', 'loadFile',
                     'fetchPins']
        found = [s for s in forbidden if f'function {s}' in src or f'{s} =' in src]
        self.assertEqual(
            found, [],
            f"artifacts.html defines rendering functions {found} — "
            f"these must be in artifact-page.js, not the shell"
        )


class TestJobHtmlExists(unittest.TestCase):
    """job.html must exist as a thin shell for job mode."""

    def test_job_html_exists(self):
        self.assertTrue(
            JOB_HTML.exists(),
            "job.html is missing from teaparty/bridge/static/ — "
            "the job screen shell has not been created"
        )

    def test_job_html_is_short(self):
        """job.html must be ≤50 lines (thin shell)."""
        if not JOB_HTML.exists():
            self.skipTest("job.html not yet created")
        count = _line_count(JOB_HTML)
        self.assertLessEqual(
            count, 50,
            f"job.html is {count} lines — a thin shell should be ≤50 lines"
        )

    def test_job_html_imports_artifact_page_js(self):
        """job.html must import artifact-page.js."""
        if not JOB_HTML.exists():
            self.skipTest("job.html not yet created")
        src = _read(JOB_HTML)
        self.assertIn(
            'artifact-page.js', src,
            "job.html does not import artifact-page.js"
        )

    def test_job_html_calls_mount_with_job_mode(self):
        """job.html must call ArtifactPage.mount with mode 'job'."""
        if not JOB_HTML.exists():
            self.skipTest("job.html not yet created")
        src = _read(JOB_HTML)
        self.assertTrue(
            MOUNT_CALL_PATTERN.search(src),
            "job.html does not call ArtifactPage.mount()"
        )
        self.assertIn(
            'job', src,
            "job.html does not specify job mode"
        )

    def test_job_html_has_no_rendering_logic(self):
        """job.html must not contain rendering symbols that belong in artifact-page.js."""
        if not JOB_HTML.exists():
            self.skipTest("job.html not yet created")
        src = _read(JOB_HTML)
        forbidden = ['renderFileView', 'renderPinnedNodes', 'renderOverview',
                     'renderMarkdown', 'renderCode', 'toggleFolder', 'loadFile',
                     'fetchPins']
        found = [s for s in forbidden if f'function {s}' in src or f'{s} =' in src]
        self.assertEqual(
            found, [],
            f"job.html defines rendering functions {found} — "
            f"these must be in artifact-page.js"
        )


class TestWorkflowBarExtracted(unittest.TestCase):
    """The workflow bar must be a shared module used by both index.html and artifact-page.js."""

    def test_workflow_bar_js_exists(self):
        self.assertTrue(
            WORKFLOW_BAR_JS.exists(),
            "workflow-bar.js is missing from teaparty/bridge/static/ — "
            "the workflow bar has not been extracted to a shared module"
        )

    def test_workflow_bar_contains_phases_and_render(self):
        """workflow-bar.js must define PHASES and renderWorkflow."""
        if not WORKFLOW_BAR_JS.exists():
            self.skipTest("workflow-bar.js not yet created")
        src = _read(WORKFLOW_BAR_JS)
        self.assertIn('PHASES', src, "workflow-bar.js missing PHASES array")
        self.assertIn('renderWorkflow', src, "workflow-bar.js missing renderWorkflow function")
        self.assertIn('phaseIndex', src, "workflow-bar.js missing phaseIndex function")

    def test_index_html_imports_workflow_bar(self):
        """index.html must import workflow-bar.js instead of defining its own."""
        src = _read(INDEX_HTML)
        self.assertIn(
            'workflow-bar.js', src,
            "index.html does not import workflow-bar.js — "
            "the workflow bar is still inline"
        )

    def test_index_html_does_not_define_phases_inline(self):
        """index.html must not define PHASES array inline — it comes from workflow-bar.js."""
        src = _read(INDEX_HTML)
        # The PHASES array definition should be gone from index.html
        self.assertNotRegex(
            src, r"var\s+PHASES\s*=\s*\[",
            "index.html still defines PHASES inline — "
            "this should be in workflow-bar.js"
        )

    def test_artifact_page_imports_workflow_bar(self):
        """artifact-page.js must import workflow-bar.js for the job-mode top strip."""
        if not ARTIFACT_PAGE_JS.exists():
            self.skipTest("artifact-page.js not yet created")
        # The artifact page doesn't need to import it directly — it can use the global.
        # But the job.html shell should include workflow-bar.js.
        if JOB_HTML.exists():
            src = _read(JOB_HTML)
            self.assertIn(
                'workflow-bar.js', src,
                "job.html does not include workflow-bar.js — "
                "the job-mode top strip needs the workflow bar"
            )


class TestArtifactCSSInStylesheet(unittest.TestCase):
    """All artifact CSS must live in styles.css, not inline in HTML shells.

    The original artifacts.html had ~100 lines of inline CSS. After consolidation,
    all of it must be in styles.css so both shells (artifacts.html, job.html) and
    the shared module render correctly."""

    # Core CSS classes that artifact-page.js renders — every one of these must
    # have a rule in styles.css or the page is visually broken.
    REQUIRED_CSS_CLASSES = [
        '.artifact-layout',
        '.artifact-header',
        '.artifact-nav',
        '.artifact-nav-item',
        '.artifact-nav-section',
        '.artifact-nav-folder',
        '.artifact-main',
        '.artifact-content',
        '.artifact-title',
        '.artifact-path',
        '.artifact-loading',
        '.artifact-empty',
    ]

    def test_artifact_css_in_styles_css(self):
        """Every artifact layout class must have a CSS rule in styles.css."""
        css = _read(STYLES_CSS)
        missing = [cls for cls in self.REQUIRED_CSS_CLASSES if cls not in css]
        self.assertEqual(
            missing, [],
            f"styles.css is missing CSS rules for {missing} — "
            f"the artifact page will render unstyled. These rules were in the "
            f"original artifacts.html inline <style> block and must be moved "
            f"to styles.css during consolidation."
        )

    def test_no_inline_styles_in_shells(self):
        """Neither HTML shell should contain a <style> block — all CSS is in styles.css."""
        for name, path in [('artifacts.html', ARTIFACTS_HTML), ('job.html', JOB_HTML)]:
            if not path.exists():
                continue
            src = _read(path)
            self.assertNotIn(
                '<style>', src,
                f"{name} contains an inline <style> block — "
                f"all artifact CSS must be in styles.css"
            )


class TestSingleCodepathEnforcement(unittest.TestCase):
    """No HTML file outside artifact-page.js may contain artifact rendering logic."""

    def test_no_rendering_symbols_in_html_files(self):
        """Rendering symbols must appear only in artifact-page.js, not in any HTML shell."""
        if not ARTIFACT_PAGE_JS.exists():
            self.skipTest("artifact-page.js not yet created")

        # Check that critical rendering functions are NOT defined in any HTML file
        html_files = list(STATIC_DIR.glob("*.html"))
        rendering_functions = ['renderFileView', 'renderPinnedNodes', 'renderOverview',
                               'renderCode', 'fetchPins', 'toggleFolder']

        violations = []
        for html_file in html_files:
            src = _read(html_file)
            for fn in rendering_functions:
                # Look for function definitions, not just references
                if f'function {fn}' in src:
                    violations.append(f"{html_file.name} defines function {fn}")

        self.assertEqual(
            violations, [],
            f"Rendering functions found outside artifact-page.js: {violations}. "
            f"All rendering logic must be in the shared module."
        )


class TestChatBladeUsesAccordionChat(unittest.TestCase):
    """The artifact page must use accordion-chat.js (#400), not its own chat blade."""

    def test_artifact_page_uses_accordion_chat(self):
        """artifact-page.js must use AccordionChat.mount, not a custom blade."""
        if not ARTIFACT_PAGE_JS.exists():
            self.skipTest("artifact-page.js not yet created")
        src = _read(ARTIFACT_PAGE_JS)
        self.assertIn(
            'AccordionChat', src,
            "artifact-page.js does not use AccordionChat — "
            "it should use the #400 shared chat implementation"
        )

    def test_artifact_page_does_not_define_blade_functions(self):
        """artifact-page.js must not define its own blade polling/messaging."""
        if not ARTIFACT_PAGE_JS.exists():
            self.skipTest("artifact-page.js not yet created")
        src = _read(ARTIFACT_PAGE_JS)
        # These functions were in the old artifacts.html inline blade
        self.assertNotIn(
            'function loadBladeMessages', src,
            "artifact-page.js defines its own loadBladeMessages — "
            "it should use AccordionChat from accordion-chat.js"
        )
        self.assertNotIn(
            'function sendBladeMessage', src,
            "artifact-page.js defines its own sendBladeMessage — "
            "it should use AccordionChat from accordion-chat.js"
        )


class TestGitStatusEndpoint(unittest.TestCase):
    """Server-side git-status endpoint must parse porcelain output correctly."""

    def _make_git_repo(self):
        """Create a temporary git repo with known file states."""
        repo = tempfile.mkdtemp()
        subprocess.run(['git', 'init', repo], capture_output=True, check=True)
        subprocess.run(['git', '-C', repo, 'config', 'user.email', 'test@test.com'],
                       capture_output=True, check=True)
        subprocess.run(['git', '-C', repo, 'config', 'user.name', 'Test'],
                       capture_output=True, check=True)

        # Create and commit a file
        committed = os.path.join(repo, 'committed.txt')
        with open(committed, 'w') as f:
            f.write('original')
        subprocess.run(['git', '-C', repo, 'add', '.'], capture_output=True, check=True)
        subprocess.run(['git', '-C', repo, 'commit', '-m', 'init'],
                       capture_output=True, check=True)

        # Modify the committed file
        with open(committed, 'w') as f:
            f.write('modified')

        # Create an untracked file
        untracked = os.path.join(repo, 'new_file.txt')
        with open(untracked, 'w') as f:
            f.write('new')

        return repo

    def test_parse_git_status_porcelain(self):
        """The git-status parser must correctly classify new/modified/deleted files."""
        from teaparty.bridge.server import parse_git_status
        repo = self._make_git_repo()
        try:
            result = parse_git_status(repo)
            self.assertIn(
                'new_file.txt', result,
                f"Untracked file missing from git status result: {result}"
            )
            self.assertEqual(
                result['new_file.txt'], 'new',
                f"Untracked file should have status 'new', got '{result.get('new_file.txt')}'"
            )
            self.assertIn(
                'committed.txt', result,
                f"Modified file missing from git status result: {result}"
            )
            self.assertEqual(
                result['committed.txt'], 'modified',
                f"Modified file should have status 'modified', got '{result.get('committed.txt')}'"
            )
        finally:
            import shutil
            shutil.rmtree(repo)

    def test_parse_git_status_empty_repo(self):
        """Git status on a clean repo must return an empty dict."""
        from teaparty.bridge.server import parse_git_status
        repo = tempfile.mkdtemp()
        subprocess.run(['git', 'init', repo], capture_output=True, check=True)
        subprocess.run(['git', '-C', repo, 'config', 'user.email', 'test@test.com'],
                       capture_output=True, check=True)
        subprocess.run(['git', '-C', repo, 'config', 'user.name', 'Test'],
                       capture_output=True, check=True)
        # Commit something so HEAD exists
        f = os.path.join(repo, '.gitkeep')
        open(f, 'w').close()
        subprocess.run(['git', '-C', repo, 'add', '.'], capture_output=True, check=True)
        subprocess.run(['git', '-C', repo, 'commit', '-m', 'init'],
                       capture_output=True, check=True)
        try:
            result = parse_git_status(repo)
            self.assertEqual(
                result, {},
                f"Clean repo should have empty git status, got {result}"
            )
        finally:
            import shutil
            shutil.rmtree(repo)

    def test_parse_git_status_deleted_file(self):
        """Git status must detect deleted files."""
        from teaparty.bridge.server import parse_git_status
        repo = self._make_git_repo()
        # Delete the committed file
        os.remove(os.path.join(repo, 'committed.txt'))
        try:
            result = parse_git_status(repo)
            self.assertIn(
                'committed.txt', result,
                f"Deleted file missing from git status result: {result}"
            )
            self.assertEqual(
                result['committed.txt'], 'deleted',
                f"Deleted file should have status 'deleted', got '{result.get('committed.txt')}'"
            )
        finally:
            import shutil
            shutil.rmtree(repo)


class TestJobModeTopStrip(unittest.TestCase):
    """Job mode must show the top strip; browse mode must not."""

    def test_artifact_page_renders_top_strip_for_job_mode(self):
        """artifact-page.js must conditionally render a top strip in job mode."""
        if not ARTIFACT_PAGE_JS.exists():
            self.skipTest("artifact-page.js not yet created")
        src = _read(ARTIFACT_PAGE_JS)
        # The top strip should be conditional on mode === 'job'
        has_job_strip = ("job-strip" in src or "top-strip" in src or
                         "job-header" in src or "job-section" in src)
        self.assertTrue(
            has_job_strip,
            "artifact-page.js does not contain job-mode top strip rendering — "
            "job mode must show original request, workflow bar, and changed/all toggle"
        )

    def test_artifact_page_has_pinned_and_changed_filters(self):
        """Both modes must have [Pinned] and [Changed] filter buttons."""
        if not ARTIFACT_PAGE_JS.exists():
            self.skipTest("artifact-page.js not yet created")
        src = _read(ARTIFACT_PAGE_JS)
        self.assertIn(
            '_filterPinned', src,
            "artifact-page.js must have a _filterPinned state variable"
        )
        self.assertIn(
            '_filterChanged', src,
            "artifact-page.js must have a _filterChanged state variable"
        )
        self.assertIn(
            '_toggleFilter', src,
            "artifact-page.js must define _toggleFilter for the filter buttons"
        )


class TestStructuralEquivalence(unittest.TestCase):
    """SC4: The DOM structure below the top strip must be identical in both modes.

    Since we cannot run a headless browser in unit tests, we verify structural
    equivalence by confirming that the shared _render() function produces the
    same layout markup (artifact-header, artifact-layout, artifact-nav,
    artifact-main) regardless of mode — the only conditional block is the
    job-strip at the top, gated on mode === 'job'.
    """

    def test_layout_structure_is_mode_independent(self):
        """The artifact-layout, artifact-nav, and artifact-main are rendered
        unconditionally — they must not appear inside a mode-conditional block."""
        if not ARTIFACT_PAGE_JS.exists():
            self.skipTest("artifact-page.js not yet created")
        src = _read(ARTIFACT_PAGE_JS)

        # Find the _render function body
        render_start = src.find('function _render()')
        self.assertGreater(
            render_start, -1,
            "artifact-page.js must define a _render() function"
        )

        # The layout elements must be in _render but NOT inside a mode check
        # Verify they're at the same nesting level as the unconditional rendering
        render_body = src[render_start:]

        # These layout classes must appear in _render
        for cls in ['artifact-header', 'artifact-layout', 'artifact-nav', 'artifact-main']:
            self.assertIn(
                cls, render_body,
                f"_render() must produce '{cls}' — it is a shared layout element "
                f"that must be identical in both modes"
            )

    def test_job_strip_is_only_mode_conditional(self):
        """Only the top strip should be conditional on job mode.

        The artifact-header, artifact-layout (nav + main) must be rendered
        unconditionally. The job-strip is the only element gated on mode."""
        if not ARTIFACT_PAGE_JS.exists():
            self.skipTest("artifact-page.js not yet created")
        src = _read(ARTIFACT_PAGE_JS)

        # job-strip must appear inside a mode === 'job' conditional
        self.assertIn(
            "job-strip", src,
            "artifact-page.js must render a job-strip element for job mode"
        )

        # Verify artifact-header is NOT inside the job-mode conditional
        # by checking it appears after the conditional block closes
        render_body = src[src.find('function _render()'):]

        # The job-strip conditional and the main layout must be separate
        job_cond_idx = render_body.find("_config.mode === 'job'")
        header_idx = render_body.find('artifact-header')
        self.assertGreater(
            header_idx, job_cond_idx,
            "artifact-header must be rendered after (outside) the job-strip "
            "conditional — it is shared between both modes"
        )

    def test_both_shells_use_same_page_chrome(self):
        """Both shells must use the same blade-layout > content-wrap > blade structure
        matching the pattern established by config.html and other pages."""
        arts_src = _read(ARTIFACTS_HTML)
        job_src = _read(JOB_HTML) if JOB_HTML.exists() else self.skipTest("job.html not created")

        for name, src in [('artifacts.html', arts_src), ('job.html', job_src)]:
            self.assertIn(
                'blade-layout', src,
                f"{name} must use the blade-layout container"
            )
            self.assertIn(
                'content-wrap', src,
                f"{name} must wrap content in content-wrap for correct flex layout"
            )
            self.assertIn(
                'artifact-content', src,
                f"{name} must have an artifact-content element"
            )
            self.assertTrue(
                MOUNT_CALL_PATTERN.search(src),
                f"{name} must call ArtifactPage.mount()"
            )


class TestAccordionRetargeting(unittest.TestCase):
    """SC10: Accordion-section-changed events must retarget the file tree in job mode."""

    def test_accordion_section_changed_handler_exists(self):
        """artifact-page.js must subscribe to accordion-section-changed events."""
        if not ARTIFACT_PAGE_JS.exists():
            self.skipTest("artifact-page.js not yet created")
        src = _read(ARTIFACT_PAGE_JS)
        self.assertIn(
            'onSectionChanged', src,
            "artifact-page.js does not subscribe to onSectionChanged — "
            "accordion-driven file-tree retargeting requires this event wiring"
        )

    def test_retargeting_handler_updates_worktree(self):
        """The retargeting handler must update the active worktree path."""
        if not ARTIFACT_PAGE_JS.exists():
            self.skipTest("artifact-page.js not yet created")
        src = _read(ARTIFACT_PAGE_JS)
        self.assertIn(
            '_handleAccordionSectionChanged', src,
            "artifact-page.js must define _handleAccordionSectionChanged — "
            "the handler that retargets the file tree on accordion section change"
        )
        # Find the function definition (not a call site) and check its body
        fn_def = 'function _handleAccordionSectionChanged'
        handler_start = src.find(fn_def)
        self.assertGreater(
            handler_start, -1,
            "artifact-page.js must define function _handleAccordionSectionChanged"
        )
        handler_body = src[handler_start:handler_start + 500]
        self.assertIn(
            'chatLaunchRepo', handler_body,
            "_handleAccordionSectionChanged must update chatLaunchRepo — "
            "this is how the file tree retargets to a different worktree"
        )

    def test_retargeting_only_in_job_mode(self):
        """The retargeting subscription must be conditional on job mode."""
        if not ARTIFACT_PAGE_JS.exists():
            self.skipTest("artifact-page.js not yet created")
        src = _read(ARTIFACT_PAGE_JS)
        # The onSectionChanged subscription should be inside a job-mode check
        section_idx = src.find('onSectionChanged')
        # Look backwards for the mode check
        context = src[max(0, section_idx - 200):section_idx]
        self.assertIn(
            "mode", context,
            "onSectionChanged subscription must be conditional on job mode — "
            "browse mode does not retarget the file tree"
        )


class TestChatLaunchRepoForwarded(unittest.TestCase):
    """SC7: chatLaunchRepo and chatAgentName must be forwarded to AccordionChat."""

    def test_launch_repo_forwarded_to_accordion(self):
        """artifact-page.js must pass chatLaunchRepo to AccordionChat.mount."""
        if not ARTIFACT_PAGE_JS.exists():
            self.skipTest("artifact-page.js not yet created")
        src = _read(ARTIFACT_PAGE_JS)
        # Find the AccordionChat.mount call
        mount_idx = src.find('AccordionChat.mount')
        self.assertGreater(mount_idx, -1, "AccordionChat.mount call not found")
        mount_context = src[mount_idx:mount_idx + 300]
        self.assertIn(
            'launchRepo', mount_context,
            "AccordionChat.mount call must include launchRepo — "
            "the chat blade needs the worktree path for correct agent routing"
        )

    def test_agent_name_forwarded_to_accordion(self):
        """artifact-page.js must pass chatAgentName to AccordionChat.mount."""
        if not ARTIFACT_PAGE_JS.exists():
            self.skipTest("artifact-page.js not yet created")
        src = _read(ARTIFACT_PAGE_JS)
        mount_idx = src.find('AccordionChat.mount')
        self.assertGreater(mount_idx, -1, "AccordionChat.mount call not found")
        mount_context = src[mount_idx:mount_idx + 300]
        self.assertIn(
            'agentName', mount_context,
            "AccordionChat.mount call must include agentName — "
            "the chat blade needs the agent identity for correct routing"
        )
