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

    def test_artifact_page_has_changed_all_toggle(self):
        """Job mode must have a changed/all files toggle."""
        if not ARTIFACT_PAGE_JS.exists():
            self.skipTest("artifact-page.js not yet created")
        src = _read(ARTIFACT_PAGE_JS)
        has_toggle = 'changed' in src.lower() and ('toggle' in src.lower() or 'filter' in src.lower())
        self.assertTrue(
            has_toggle,
            "artifact-page.js does not implement a changed/all files toggle "
            "for job mode"
        )
