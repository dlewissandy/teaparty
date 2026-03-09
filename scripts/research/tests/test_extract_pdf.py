"""Tests for scripts/research/extract_pdf.py"""

import os
import shutil
import sys
import tempfile
import unittest
import zlib
from pathlib import Path
from unittest.mock import patch, MagicMock

# Allow importing from scripts/research/
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import extract_pdf as ep


class TestExtractWithStdlib(unittest.TestCase):
    """Tests for stdlib-based PDF text extraction."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _make_pdf_with_text_stream(self, text: str) -> str:
        """Create a minimal PDF-like file with a FlateDecode text stream."""
        # Encode text as a PDF content stream with Tj operator
        content_stream = f"BT ({text}) Tj ET".encode("ascii")
        compressed = zlib.compress(content_stream)

        pdf_data = (
            b"%PDF-1.4\n"
            b"1 0 obj\n<< /Type /Page >>\nendobj\n"
            b"2 0 obj\n<< /Length " + str(len(compressed)).encode() + b" /Filter /FlateDecode >>\n"
            b"stream\n" + compressed + b"\nendstream\n"
            b"endobj\n"
            b"%%EOF\n"
        )

        path = os.path.join(self.tmpdir, "test.pdf")
        with open(path, "wb") as f:
            f.write(pdf_data)
        return path

    def test_extract_text_from_compressed_stream(self):
        path = self._make_pdf_with_text_stream("Hello World")
        text = ep.extract_with_stdlib(path)
        self.assertIn("Hello", text)
        self.assertIn("World", text)

    def test_extract_from_nonexistent_file(self):
        text = ep.extract_with_stdlib("/nonexistent/path.pdf")
        self.assertEqual(text, "")

    def test_extract_from_empty_file(self):
        path = os.path.join(self.tmpdir, "empty.pdf")
        Path(path).write_bytes(b"")
        text = ep.extract_with_stdlib(path)
        self.assertEqual(text, "")


class TestExtractWithFitz(unittest.TestCase):
    """Tests for PyMuPDF extraction (mocked)."""

    def test_returns_none_when_fitz_unavailable(self):
        # fitz likely not installed in test env
        # extract_with_fitz returns None if import fails
        result = ep.extract_with_fitz("/nonexistent.pdf")
        # Either None (fitz not available) or error handling
        # We can't guarantee fitz is/isn't installed, so just ensure no crash
        self.assertTrue(result is None or isinstance(result, str))


class TestParsePageRange(unittest.TestCase):
    """Tests for _parse_page_range()."""

    def test_range(self):
        start, end = ep._parse_page_range("1-10", 20)
        self.assertEqual(start, 0)  # 1-indexed → 0-indexed
        self.assertEqual(end, 10)

    def test_single_page(self):
        start, end = ep._parse_page_range("5", 20)
        self.assertEqual(start, 4)  # 1-indexed → 0-indexed
        self.assertEqual(end, 5)

    def test_clamps_to_total(self):
        start, end = ep._parse_page_range("1-100", 10)
        self.assertEqual(start, 0)
        self.assertEqual(end, 10)

    def test_invalid_range(self):
        start, end = ep._parse_page_range("abc", 10)
        self.assertEqual(start, 0)
        self.assertEqual(end, 10)


class TestDecodePdfString(unittest.TestCase):
    """Tests for _decode_pdf_string()."""

    def test_basic_text(self):
        result = ep._decode_pdf_string(b"Hello World")
        self.assertEqual(result, "Hello World")

    def test_escape_sequences(self):
        result = ep._decode_pdf_string(b"Hello\\nWorld")
        self.assertEqual(result, "Hello\nWorld")

    def test_escaped_parens(self):
        result = ep._decode_pdf_string(b"\\(text\\)")
        self.assertEqual(result, "(text)")


class TestExtractTextOperators(unittest.TestCase):
    """Tests for _extract_text_operators()."""

    def test_tj_operator(self):
        data = b"BT (Hello World) Tj ET"
        result = ep._extract_text_operators(data)
        self.assertIn("Hello World", result)

    def test_tj_array(self):
        data = b"BT [(Hello) -50 (World)] TJ ET"
        result = ep._extract_text_operators(data)
        self.assertIn("Hello", result)
        self.assertIn("World", result)

    def test_no_text_operators(self):
        data = b"BT /F1 12 Tf ET"
        result = ep._extract_text_operators(data)
        self.assertEqual(result.strip(), "")


class TestDownloadPdf(unittest.TestCase):
    """Tests for download_pdf()."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    @patch("extract_pdf.urllib.request.urlopen")
    def test_download_success(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.read.return_value = b"%PDF-1.4 test content"
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        dest = os.path.join(self.tmpdir, "downloaded.pdf")
        result = ep.download_pdf("https://example.com/paper.pdf", dest)
        self.assertTrue(result)
        self.assertTrue(os.path.exists(dest))

    @patch("extract_pdf.urllib.request.urlopen")
    def test_download_failure(self, mock_urlopen):
        mock_urlopen.side_effect = Exception("Network error")
        dest = os.path.join(self.tmpdir, "failed.pdf")
        result = ep.download_pdf("https://example.com/paper.pdf", dest)
        self.assertFalse(result)


class TestMainFunction(unittest.TestCase):
    """Tests for the main() entry point."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_main_with_nonexistent_file(self):
        output = os.path.join(self.tmpdir, "output.txt")
        with patch("sys.argv", ["extract_pdf.py", "--file", "/nonexistent.pdf", "--output", output]):
            result = ep.main()
        self.assertEqual(result, 0)
        # Output file should exist but be empty
        self.assertTrue(os.path.exists(output))
        self.assertEqual(Path(output).read_text(), "")


if __name__ == "__main__":
    unittest.main()
