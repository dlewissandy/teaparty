"""Tests for Issue #349: Artifact viewer — copy file content button.

Acceptance criteria:
1. Copy button appears in the file view header when a file is open
2. Clicking it writes the full file text to the clipboard via navigator.clipboard.writeText()
3. Button gives brief visual confirmation ("Copied") then reverts after ~1.5s
4. Button is absent on the overview screen and for binary files (images, PDFs)
"""
import re
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).parent.parent
_ARTIFACTS_HTML = _REPO_ROOT / 'bridge' / 'static' / 'artifacts.html'


def _html() -> str:
    return _ARTIFACTS_HTML.read_text()


class TestCopyButtonPresence(unittest.TestCase):
    """Copy button must appear in the header only when a text file is loaded."""

    def test_copy_button_rendered_when_file_loaded(self):
        """render() must include a Copy button when selectedFile is set and fileContent is non-null/non-empty."""
        html = _html()
        # The render function must condition copy button on selectedFile and fileContent being present.
        # We verify it contains a copy-related button rendered inside the header.
        self.assertIn('copyFileContent', html,
                      "artifacts.html must define a copyFileContent function or similar for the copy button")

    def test_copy_button_absent_on_overview(self):
        """Copy button must not appear when no file is selected (overview screen)."""
        html = _html()
        # The copy button must be conditionally rendered only when selectedFile !== null and
        # fileContent is non-null and non-empty. The render() function must gate it.
        # Check that the copy button HTML is inside a conditional block for selectedFile/fileContent.
        # We verify that the copy button is not unconditionally emitted (not in the static header string).
        # The Refresh button IS unconditional; Copy must be conditional.
        # Find the headerHtml construction — it should NOT contain 'Copy' unconditionally.
        header_match = re.search(r'var headerHtml\s*=.*?;', html, re.DOTALL)
        self.assertIsNotNone(header_match, "artifacts.html must define headerHtml in render()")
        header_block = header_match.group(0)
        self.assertNotIn('Copy', header_block,
                         "Copy button must not be in the unconditional header — it must be conditional on file state")

    def test_copy_button_hidden_for_binary_files(self):
        """Copy button must not appear for image or PDF files (binary, rendered via URL)."""
        html = _html()
        # Binary files set fileContent = '' (empty string sentinel).
        # The copy button must be hidden when fileContent is '' (falsy check or explicit binary check).
        # The condition must exclude the empty-string sentinel used for binary files.
        # We look for the condition that gates the copy button — it must check fileContent truthy/length.
        self.assertRegex(
            html,
            r'fileContent\s*(&&\s*fileContent|\s*!==\s*null|\s*\.length)',
            "Copy button condition must check fileContent is non-empty (not the binary sentinel '')"
        )


class TestCopyButtonClipboard(unittest.TestCase):
    """Clicking Copy must write fileContent to the clipboard."""

    def test_clipboard_write_text_called(self):
        """Copy action must use navigator.clipboard.writeText() to write file content."""
        html = _html()
        self.assertIn('navigator.clipboard.writeText', html,
                      "artifacts.html must call navigator.clipboard.writeText() for the copy action")

    def test_clipboard_write_uses_file_content(self):
        """The writeText call must pass fileContent, not some other value."""
        html = _html()
        # Must call writeText with fileContent
        self.assertRegex(
            html,
            r'navigator\.clipboard\.writeText\s*\(\s*fileContent\s*\)',
            "navigator.clipboard.writeText must be called with fileContent"
        )


class TestCopyButtonFeedback(unittest.TestCase):
    """Copy button must show brief visual feedback then revert."""

    def test_copied_label_feedback(self):
        """Button text must change to 'Copied' after click."""
        html = _html()
        self.assertIn('Copied', html,
                      "artifacts.html must set button text to 'Copied' as visual feedback after copy")

    def test_feedback_reverts_after_timeout(self):
        """Button label must revert to original after ~1.5s via setTimeout."""
        html = _html()
        self.assertIn('setTimeout', html,
                      "artifacts.html must use setTimeout to revert the 'Copied' label back to 'Copy'")

    def test_feedback_duration_approximately_1500ms(self):
        """Revert timeout must be approximately 1500ms (1000–2000ms range is acceptable)."""
        html = _html()
        # Find setTimeout calls near 'Copied' — look for a numeric timeout in 1000–2000 range.
        # We look for setTimeout(... , <N>) where N is between 1000 and 2000.
        matches = re.findall(r'setTimeout\s*\([^,]+,\s*(\d+)\s*\)', html)
        self.assertTrue(
            any(1000 <= int(m) <= 2000 for m in matches),
            f"setTimeout duration must be 1000–2000ms for copy feedback; found timeouts: {matches}"
        )
