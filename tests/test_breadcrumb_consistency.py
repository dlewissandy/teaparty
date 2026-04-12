"""Specification-based tests for issue #399.

Every page under teaparty/bridge/static/ that renders a breadcrumb bar must:
  1. Render it via the shared breadcrumbBar(parts) helper from breadcrumb.js,
     not via hand-rolled inline <a href="index.html">Home</a> markup.
  2. Pass at least two entries to breadcrumbBar — Home plus a current-page entry.
  3. Make the rightmost (current-page) entry non-linked: the object literal for
     the last entry MUST NOT contain an onClick field.

The rightmost label must match the page's own title. For static pages this is
a literal match (e.g. "Statistics" in stats.html). For chat.html the last
entry label is the dynamic conversation header (variable reference, not a
literal), since the title is resolved asynchronously.
"""

import re
import unittest
from pathlib import Path


STATIC_DIR = Path(__file__).resolve().parent.parent / "teaparty" / "bridge" / "static"
BREADCRUMB_JS = STATIC_DIR / "breadcrumb.js"


def _find_breadcrumb_calls(text: str) -> list[str]:
    """Return the raw argument text of every breadcrumbBar(...) *call site*.

    Excludes the function declaration `function breadcrumbBar(parts)` and any
    call whose argument is not an inline JS array literal (those are built
    dynamically and linted at their build sites instead).
    """
    out: list[str] = []
    needle = "breadcrumbBar("
    i = 0
    while True:
        idx = text.find(needle, i)
        if idx < 0:
            break
        # Skip the function declaration itself.
        before = text[max(0, idx - 20):idx]
        if re.search(r"function\s+$", before):
            i = idx + len(needle)
            continue
        start = idx + len(needle)
        depth = 1
        j = start
        in_str: str | None = None
        while j < len(text) and depth > 0:
            c = text[j]
            if in_str:
                if c == "\\":
                    j += 2
                    continue
                if c == in_str:
                    in_str = None
                j += 1
                continue
            if c in ("'", '"'):
                in_str = c
            elif c == "(":
                depth += 1
            elif c == ")":
                depth -= 1
                if depth == 0:
                    arg = text[start:j].strip()
                    # Only lint inline array-literal args. Variable args
                    # (e.g. breadcrumbBar(crumbs)) are checked via the
                    # spec-specific tests that inspect the construction site.
                    if arg.startswith("["):
                        out.append(arg)
                    break
            j += 1
        i = j + 1
    return out


def _split_array_elements(arr_literal: str) -> list[str]:
    """Split a JS array literal '[a, {x:1}, ...]' into top-level element strings."""
    s = arr_literal.strip()
    assert s.startswith("[") and s.endswith("]"), f"expected array literal, got: {s!r}"
    inner = s[1:-1]
    elems: list[str] = []
    buf: list[str] = []
    depth = 0
    in_str: str | None = None
    k = 0
    while k < len(inner):
        c = inner[k]
        if in_str:
            buf.append(c)
            if c == "\\" and k + 1 < len(inner):
                buf.append(inner[k + 1])
                k += 2
                continue
            if c == in_str:
                in_str = None
            k += 1
            continue
        if c in ("'", '"'):
            in_str = c
            buf.append(c)
        elif c in "([{":
            depth += 1
            buf.append(c)
        elif c in ")]}":
            depth -= 1
            buf.append(c)
        elif c == "," and depth == 0:
            part = "".join(buf).strip()
            if part:
                elems.append(part)
            buf = []
        else:
            buf.append(c)
        k += 1
    tail = "".join(buf).strip()
    if tail:
        elems.append(tail)
    return elems


def _last_entry_label(entry: str) -> str | None:
    """Extract the `label:` value (as written) from a breadcrumb entry object literal."""
    m = re.search(r"label\s*:\s*(.+?)(?:,\s*(?:onClick|icon)|\s*\})", entry, re.DOTALL)
    if not m:
        return None
    return m.group(1).strip()


class BreadcrumbHelperTests(unittest.TestCase):
    """The shared helper must exist and define the canonical breadcrumbBar function."""

    def test_shared_helper_file_exists(self):
        self.assertTrue(
            BREADCRUMB_JS.is_file(),
            f"shared helper missing: expected {BREADCRUMB_JS} to exist so every static "
            "page can render its breadcrumb via a single implementation",
        )

    def test_shared_helper_defines_breadcrumbBar(self):
        src = BREADCRUMB_JS.read_text()
        self.assertIn(
            "function breadcrumbBar",
            src,
            "breadcrumb.js must define function breadcrumbBar(parts) — this is the "
            "single helper all static pages are required to use",
        )

    def test_shared_helper_renders_current_entry_without_onclick(self):
        """The helper must produce non-anchor output for entries missing onClick."""
        src = BREADCRUMB_JS.read_text()
        # Helper should branch on presence of onClick and render a non-anchor
        # form (span-styled) for the current entry.
        self.assertRegex(
            src,
            r"onClick",
            "breadcrumb.js must inspect onClick to decide linked vs current entry",
        )
        self.assertIn(
            "current",
            src,
            'breadcrumb.js must tag the non-linked entry with class "current" so CSS '
            "can give it distinct, non-clickable styling",
        )


class BreadcrumbCallSiteTests(unittest.TestCase):
    """Every breadcrumbBar([...]) call must yield a spec-conforming bar."""

    PAGES = ("config.html", "stats.html", "artifacts.html", "chat.html")

    def _calls_in(self, page: str) -> list[str]:
        return _find_breadcrumb_calls((STATIC_DIR / page).read_text())

    def test_every_page_uses_the_shared_helper(self):
        for page in self.PAGES:
            with self.subTest(page=page):
                calls = self._calls_in(page)
                self.assertGreaterEqual(
                    len(calls),
                    1,
                    f"{page} must render its breadcrumb via breadcrumbBar([...]) — "
                    "no page may hand-roll inline <a href=index.html>Home</a> markup",
                )

    def test_every_breadcrumb_call_has_at_least_two_entries(self):
        for page in self.PAGES:
            for call in self._calls_in(page):
                with self.subTest(page=page, call=call[:80]):
                    elems = _split_array_elements(call)
                    self.assertGreaterEqual(
                        len(elems),
                        2,
                        f"{page}: breadcrumbBar call has {len(elems)} entries, "
                        "expected ≥2 (Home + current page)",
                    )

    def test_every_breadcrumb_call_last_entry_is_nonlinked(self):
        for page in self.PAGES:
            for call in self._calls_in(page):
                elems = _split_array_elements(call)
                last = elems[-1]
                with self.subTest(page=page, last=last):
                    self.assertNotIn(
                        "onClick",
                        last,
                        f"{page}: rightmost breadcrumb entry {last!r} contains "
                        "onClick — the current-page entry must be non-linked",
                    )

    def test_no_page_renders_home_only_literal_bar(self):
        """Reject the pre-fix pattern: <div class='breadcrumb-bar'><a href='index.html'>Home</a></div>."""
        pat = re.compile(
            r'<div[^>]*class="breadcrumb-bar"[^>]*>\s*<a\s+href="index\.html"[^>]*>\s*Home\s*</a>\s*</div>',
            re.IGNORECASE,
        )
        for html in STATIC_DIR.glob("*.html"):
            with self.subTest(page=html.name):
                self.assertIsNone(
                    pat.search(html.read_text()),
                    f"{html.name} still contains the hand-rolled Home-only breadcrumb. "
                    "It must render via breadcrumbBar([...]) instead.",
                )


class PageSpecificLabelTests(unittest.TestCase):
    """The rightmost breadcrumb label must match each page's own identity."""

    def _last_label(self, page: str, which: int = 0) -> str:
        calls = _find_breadcrumb_calls((STATIC_DIR / page).read_text())
        self.assertGreater(
            len(calls), which, f"{page} has no breadcrumbBar call #{which}"
        )
        elems = _split_array_elements(calls[which])
        self.assertGreaterEqual(len(elems), 2, f"{page}: breadcrumb too short")
        label = _last_entry_label(elems[-1])
        self.assertIsNotNone(
            label, f"{page}: rightmost entry {elems[-1]!r} has no label field"
        )
        return label

    def test_stats_rightmost_is_statistics(self):
        label = self._last_label("stats.html")
        self.assertIn(
            "Statistics",
            label,
            f"stats.html rightmost breadcrumb label is {label!r}, expected 'Statistics' "
            "to match the page identity",
        )

    def test_artifacts_rightmost_is_artifacts(self):
        label = self._last_label("artifacts.html")
        self.assertIn(
            "Artifacts",
            label,
            f"artifacts.html rightmost breadcrumb label is {label!r}, expected 'Artifacts'",
        )

    def test_config_loadglobal_rightmost_is_management_team(self):
        """loadGlobal must pass Management Team as the current-page entry, not just Home."""
        src = (STATIC_DIR / "config.html").read_text()
        # Locate the loadGlobal function body so the assertion is scoped to it.
        m = re.search(r"function\s+loadGlobal\s*\([^)]*\)\s*\{", src)
        self.assertIsNotNone(m, "config.html must define loadGlobal()")
        body_start = m.end()
        depth = 1
        i = body_start
        while i < len(src) and depth > 0:
            if src[i] == "{":
                depth += 1
            elif src[i] == "}":
                depth -= 1
            i += 1
        body = src[body_start:i]
        calls = _find_breadcrumb_calls(body)
        self.assertEqual(
            len(calls),
            1,
            "loadGlobal() must make exactly one breadcrumbBar call",
        )
        elems = _split_array_elements(calls[0])
        self.assertGreaterEqual(
            len(elems),
            2,
            "loadGlobal() breadcrumb must include Home AND 'Management Team' — "
            "currently it only passes Home, so the page title is invisible in the bar",
        )
        last_label = _last_entry_label(elems[-1])
        self.assertIsNotNone(last_label, f"loadGlobal last entry has no label: {elems[-1]!r}")
        self.assertIn(
            "Management Team",
            last_label,
            f"loadGlobal rightmost crumb label is {last_label!r}, expected 'Management Team' "
            "to match the page H1",
        )

    def test_chat_rightmost_is_dynamic_conversation_title(self):
        """Standalone chat page must use the conversation's header title as the last crumb."""
        src = (STATIC_DIR / "chat.html").read_text()
        calls = _find_breadcrumb_calls(src)
        self.assertGreaterEqual(
            len(calls),
            1,
            "chat.html must call breadcrumbBar([...]) to render its bar via the shared helper",
        )
        # At least one call must use headerTitle (a JS variable, not a string literal)
        # as the last entry's label, so the crumb reflects the resolved conversation title.
        matched = False
        for call in calls:
            elems = _split_array_elements(call)
            if len(elems) < 2:
                continue
            last = elems[-1]
            label = _last_entry_label(last)
            if label and "headerTitle" in label:
                matched = True
                break
        self.assertTrue(
            matched,
            "chat.html must pass `headerTitle` (the resolved conversation title) as the "
            "rightmost breadcrumb label so the current conversation is shown in the bar",
        )


class MinimalChatBehaviorTests(unittest.TestCase):
    """chat.html minimal mode (iframe in accordion blade) must still hide the bar."""

    def test_minimal_mode_still_hides_breadcrumb(self):
        src = (STATIC_DIR / "chat.html").read_text()
        # The minimal branch must continue to suppress the bar. Either by setting
        # display:none on the slot, or by skipping the breadcrumb render entirely.
        self.assertRegex(
            src,
            r"minimal[^}]*(breadcrumb|display\s*=\s*['\"]none)",
            "chat.html minimal mode must continue to hide the breadcrumb — the "
            "accordion already conveys location, so the bar is redundant there",
        )


if __name__ == "__main__":
    unittest.main()
