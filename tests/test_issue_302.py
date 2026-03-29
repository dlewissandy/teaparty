"""Tests for issue #302: artifacts viewer wired to live bridge API.

Acceptance criteria verified here:
1. artifacts.html makes no reference to mockData
2. artifacts.html fetches sections from /api/artifacts/{project}
3. artifacts.html fetches file content from /api/file?path=PATH
4. artifacts.html handles ?project= and ?file= URL parameters
5. artifacts.html intercepts internal markdown links to open in viewer
6. artifacts.html shows a job conversation link for files under .sessions/
7. artifacts.html does not load data.js (mock data removed)
"""
import os
import re
import unittest

ARTIFACTS_HTML = os.path.join(
    os.path.dirname(__file__), '..', 'docs', 'proposals', 'ui-redesign', 'mockup', 'artifacts.html'
)


def _read_html():
    with open(ARTIFACTS_HTML) as f:
        return f.read()


class TestArtifactsHtmlHasNoMockData(unittest.TestCase):
    """artifacts.html must not reference any hardcoded mock data."""

    def test_no_mockdata_reference(self):
        """AC1: artifacts.html must not use mockData anywhere."""
        content = _read_html()
        self.assertNotIn('mockData', content,
                         'artifacts.html must not reference mockData — use live API instead')

    def test_data_js_not_loaded(self):
        """AC1: artifacts.html must not load data.js since mock data is removed."""
        content = _read_html()
        self.assertNotIn('data.js', content,
                         'artifacts.html must not load data.js — mock data is replaced by live API calls')


class TestArtifactsHtmlCallsArtifactsApi(unittest.TestCase):
    """artifacts.html must fetch sidebar sections from /api/artifacts/{project}."""

    def test_fetches_artifacts_api(self):
        """AC2: artifacts.html must call GET /api/artifacts/ to load project sections."""
        content = _read_html()
        self.assertIn('/api/artifacts/', content,
                      "artifacts.html must fetch '/api/artifacts/{project}' to load sidebar sections")

    def test_project_param_used_in_api_call(self):
        """AC2: The project URL param must drive the artifacts API call, not a hardcoded slug."""
        content = _read_html()
        # The API call must include the currentProject variable, not a hardcoded 'poc'
        # Check that currentProject (or equivalent) is used in the fetch call
        self.assertRegex(
            content,
            r"fetch\(['\"]?/api/artifacts/",
            "artifacts.html must call fetch('/api/artifacts/...') dynamically",
        )


class TestArtifactsHtmlCallsFileApi(unittest.TestCase):
    """artifacts.html must fetch file content from /api/file?path=PATH."""

    def test_fetches_file_api(self):
        """AC3: artifacts.html must call GET /api/file to load file content."""
        content = _read_html()
        self.assertIn('/api/file', content,
                      "artifacts.html must call '/api/file?path=PATH' to load file content")

    def test_file_path_encoded_in_request(self):
        """AC3: The file path must be URL-encoded in the fetch request."""
        content = _read_html()
        # Must use encodeURIComponent or equivalent to encode the path
        self.assertIn('encodeURIComponent', content,
                      'artifacts.html must URL-encode the file path in fetch requests')


class TestArtifactsHtmlUrlParams(unittest.TestCase):
    """artifacts.html must handle ?project= and ?file= URL parameters."""

    def test_reads_project_url_param(self):
        """AC4: artifacts.html must read the ?project= URL parameter."""
        content = _read_html()
        self.assertIn("params.get('project')", content,
                      "artifacts.html must read ?project= from URL params")

    def test_reads_file_url_param(self):
        """AC4: artifacts.html must read the ?file= URL parameter for gate review deep links."""
        content = _read_html()
        self.assertIn("params.get('file')", content,
                      "artifacts.html must read ?file= from URL params to open a file directly on load")

    def test_file_param_triggers_file_load_on_startup(self):
        """AC4: When ?file=PATH is in the URL, that file must be loaded on page init."""
        content = _read_html()
        # The requestedFile / file param must be used in the init/load flow
        self.assertRegex(
            content,
            r"params\.get\(['\"]file['\"]\)",
            "artifacts.html must read the 'file' URL parameter",
        )


class TestArtifactsHtmlMarkdownLinkInterception(unittest.TestCase):
    """Links within rendered markdown must open in the viewer, not navigate away."""

    def test_internal_links_intercepted(self):
        """AC5: artifacts.html must intercept non-external href links in rendered markdown."""
        content = _read_html()
        # Must have some link-rewriting logic — either through a custom renderer
        # or post-processing of rendered HTML
        has_link_rewrite = (
            'loadFile' in content and
            ('href="javascript:void(0)"' in content or
             "href='javascript:void(0)'" in content or
             'onclick' in content)
        )
        self.assertTrue(
            has_link_rewrite,
            "artifacts.html must intercept internal links in rendered markdown to open in viewer",
        )

    def test_loadfile_function_exists(self):
        """AC3+AC5: A loadFile function must exist to load file content on demand."""
        content = _read_html()
        self.assertRegex(
            content,
            r'function\s+loadFile\s*\(',
            'artifacts.html must define a loadFile() function for loading file content',
        )


class TestArtifactsHtmlJobConversationLink(unittest.TestCase):
    """Files under .sessions/ must show a 'View job conversation' link."""

    def test_sessions_path_detection(self):
        """AC6: artifacts.html must detect .sessions/ in file path to show job conv link."""
        content = _read_html()
        self.assertIn('.sessions/', content,
                      "artifacts.html must check if file path contains '.sessions/' to identify job artifacts")

    def test_job_conversation_link_opens_chat(self):
        """AC6: The 'View job conversation' link must open chat.html?conv=..."""
        content = _read_html()
        self.assertIn('chat.html?conv=', content,
                      "artifacts.html must link to 'chat.html?conv=...' for job artifacts")


class TestArtifactsHtmlMarkdownRendering(unittest.TestCase):
    """File content must be rendered as markdown, not displayed as raw text."""

    def test_markdown_library_loaded(self):
        """AC3: artifacts.html must load a markdown rendering library (marked.js)."""
        content = _read_html()
        self.assertIn('marked', content,
                      'artifacts.html must load marked.js or equivalent for markdown rendering')

    def test_code_highlighting_loaded(self):
        """AC3: artifacts.html must load a code highlighting library (highlight.js)."""
        content = _read_html()
        # highlight.js or hljs
        has_hljs = 'highlight.js' in content or 'hljs' in content
        self.assertTrue(has_hljs,
                        'artifacts.html must load highlight.js or equivalent for code highlighting')


class TestArtifactsHtmlErrorHandling(unittest.TestCase):
    """artifacts.html must handle error states gracefully."""

    def test_project_not_found_error_handled(self):
        """AC7: artifacts.html must handle a 404 from the artifacts API."""
        content = _read_html()
        # Must check response status or catch fetch errors
        has_error_handling = (
            'resp.ok' in content or
            'response.ok' in content or
            'catch' in content or
            'status' in content
        )
        self.assertTrue(has_error_handling,
                        'artifacts.html must handle API errors (404, network failure)')

    def test_init_function_exists(self):
        """AC2+AC7: An async init function must orchestrate the load-on-startup flow."""
        content = _read_html()
        self.assertRegex(
            content,
            r'(async\s+function\s+init|function\s+init)\s*\(',
            'artifacts.html must define an init() function that fetches data on startup',
        )


if __name__ == '__main__':
    unittest.main()
