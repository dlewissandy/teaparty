#!/usr/bin/env python3
"""PDF text extraction for research papers.

Downloads a PDF and extracts plain text. Tries PyMuPDF (fitz) first,
falls back to a basic stdlib approach that extracts what it can.

Usage:
    extract_pdf.py --url <pdf_url> --output <text_file>
    extract_pdf.py --file <local.pdf> --output <text_file>

Exit 0 always. Empty output file means extraction failed.
"""
import argparse
import os
import re
import sys
import tempfile
import urllib.request
import zlib
from pathlib import Path


def _log(msg: str) -> None:
    print(f"[extract_pdf] {msg}", file=sys.stderr)


# ── PyMuPDF extraction (preferred) ──────────────────────────────────────────

def extract_with_fitz(pdf_path: str, pages: str = "") -> str | None:
    """Extract text using PyMuPDF (fitz). Returns None if fitz unavailable."""
    try:
        import fitz  # type: ignore
    except ImportError:
        return None

    try:
        doc = fitz.open(pdf_path)
    except Exception as e:
        _log(f"fitz failed to open PDF: {e}")
        return None

    # Determine page range
    total_pages = len(doc)
    if pages:
        start, end = _parse_page_range(pages, total_pages)
    else:
        start, end = 0, total_pages

    text_parts = []
    for i in range(start, min(end, total_pages)):
        page = doc[i]
        text = page.get_text("text")
        if text.strip():
            text_parts.append(f"--- Page {i + 1} ---\n{text.strip()}")

    doc.close()
    return "\n\n".join(text_parts)


def _parse_page_range(pages: str, total: int) -> tuple[int, int]:
    """Parse page range string like '1-10' into (start, end) 0-indexed."""
    if "-" in pages:
        parts = pages.split("-", 1)
        try:
            start = max(0, int(parts[0]) - 1)
            end = min(total, int(parts[1]))
            return start, end
        except ValueError:
            return 0, total
    else:
        try:
            page = int(pages) - 1
            return max(0, page), min(total, page + 1)
        except ValueError:
            return 0, total


# ── Stdlib fallback extraction ──────────────────────────────────────────────

def extract_with_stdlib(pdf_path: str) -> str:
    """Basic PDF text extraction using stdlib only.

    Looks for text streams between stream/endstream markers and attempts
    FlateDecode decompression. This is crude but extracts something from
    many PDFs without any dependencies.
    """
    try:
        with open(pdf_path, "rb") as f:
            raw = f.read()
    except OSError as e:
        _log(f"Failed to read PDF: {e}")
        return ""

    text_parts = []

    # Find all stream/endstream pairs
    stream_pattern = re.compile(
        rb"stream\r?\n(.*?)endstream",
        re.DOTALL,
    )

    for match in stream_pattern.finditer(raw):
        data = match.group(1)

        # Try FlateDecode decompression
        try:
            decompressed = zlib.decompress(data)
        except zlib.error:
            decompressed = data

        # Extract text from content stream operators
        # Look for text between BT/ET blocks, extract Tj and TJ operators
        text = _extract_text_operators(decompressed)
        if text.strip():
            text_parts.append(text.strip())

    # Also try to find raw UTF-8 text segments
    if not text_parts:
        text = _extract_raw_text(raw)
        if text.strip():
            text_parts.append(text.strip())

    return "\n\n".join(text_parts)


def _extract_text_operators(data: bytes) -> str:
    """Extract text from PDF content stream text operators (Tj, TJ, ')."""
    text_parts = []

    # Match text in parentheses from Tj operator: (text) Tj
    tj_pattern = re.compile(rb"\(([^)]*)\)\s*Tj", re.DOTALL)
    for match in tj_pattern.finditer(data):
        text = _decode_pdf_string(match.group(1))
        if text:
            text_parts.append(text)

    # Match TJ arrays: [(text) -kern (text)] TJ
    tj_array_pattern = re.compile(rb"\[((?:\([^)]*\)|[^]]*)*)\]\s*TJ", re.DOTALL)
    for match in tj_array_pattern.finditer(data):
        array_content = match.group(1)
        for sub in re.finditer(rb"\(([^)]*)\)", array_content):
            text = _decode_pdf_string(sub.group(1))
            if text:
                text_parts.append(text)

    # Match ' operator: (text) '
    quote_pattern = re.compile(rb"\(([^)]*)\)\s*'", re.DOTALL)
    for match in quote_pattern.finditer(data):
        text = _decode_pdf_string(match.group(1))
        if text:
            text_parts.append(text)

    return " ".join(text_parts)


def _decode_pdf_string(data: bytes) -> str:
    """Decode a PDF string, handling escape sequences."""
    # Unescape PDF string escapes
    result = data
    result = result.replace(b"\\n", b"\n")
    result = result.replace(b"\\r", b"\r")
    result = result.replace(b"\\t", b"\t")
    result = result.replace(b"\\(", b"(")
    result = result.replace(b"\\)", b")")
    result = result.replace(b"\\\\", b"\\")

    try:
        return result.decode("utf-8", errors="replace")
    except Exception:
        try:
            return result.decode("latin-1", errors="replace")
        except Exception:
            return ""


def _extract_raw_text(data: bytes) -> str:
    """Last-resort: find readable ASCII/UTF-8 text segments in raw PDF bytes."""
    # Find runs of printable ASCII characters
    text_runs = re.findall(rb"[\x20-\x7e]{20,}", data)
    if not text_runs:
        return ""

    # Filter out binary-looking content (PDF operators, etc.)
    filtered = []
    for run in text_runs:
        text = run.decode("ascii", errors="replace")
        # Skip PDF syntax lines
        if any(kw in text for kw in ["obj", "endobj", "stream", "xref", "/Type", "/Font"]):
            continue
        # Keep lines with enough word-like content
        words = text.split()
        if len(words) >= 3:
            filtered.append(text)

    return "\n".join(filtered)


# ── Download ────────────────────────────────────────────────────────────────

def download_pdf(url: str, dest: str) -> bool:
    """Download a PDF from URL. Returns True on success."""
    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "research-tool/1.0"},
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = resp.read()

        with open(dest, "wb") as f:
            f.write(data)

        _log(f"Downloaded {len(data)} bytes from {url}")
        return True

    except Exception as e:
        _log(f"Download failed: {e}")
        return False


# ── Main ────────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(description="PDF text extraction for research papers")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--url", help="PDF URL to download and extract")
    group.add_argument("--file", help="Local PDF file path")
    parser.add_argument("--output", required=True, help="Output text file path")
    parser.add_argument("--pages", default="", help="Page range, e.g., 1-10 (PyMuPDF only)")
    args = parser.parse_args()

    # Ensure output directory exists
    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)

    # Ensure output file exists (empty = extraction failed)
    Path(args.output).write_text("")

    # Get PDF file path
    pdf_path = args.file
    tmp_file = None

    if args.url:
        tmp_file = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
        tmp_file.close()
        pdf_path = tmp_file.name
        if not download_pdf(args.url, pdf_path):
            _cleanup(tmp_file.name)
            return 0

    if not pdf_path or not Path(pdf_path).is_file():
        _log("No PDF file available")
        _cleanup(tmp_file.name if tmp_file else None)
        return 0

    # Try PyMuPDF first
    text = extract_with_fitz(pdf_path, args.pages)
    if text is None:
        _log("PyMuPDF not available, using stdlib fallback")
        text = extract_with_stdlib(pdf_path)

    if text and text.strip():
        Path(args.output).write_text(text)
        _log(f"Extracted {len(text)} characters to {args.output}")
    else:
        _log("No text extracted from PDF")

    _cleanup(tmp_file.name if tmp_file else None)
    return 0


def _cleanup(path: str | None) -> None:
    """Remove temporary file if it exists."""
    if path:
        try:
            os.unlink(path)
        except OSError:
            pass


if __name__ == "__main__":
    sys.exit(main())
