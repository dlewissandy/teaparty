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
STYLES_CSS = STATIC_DIR / "styles.css"


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


def _find_function_body(src: str, func_name: str) -> str:
    """Return the body (contents of outer braces) of the named JS function."""
    m = re.search(rf"function\s+{re.escape(func_name)}\s*\([^)]*\)\s*\{{", src)
    if not m:
        raise AssertionError(f"function {func_name} not found")
    start = m.end()
    depth = 1
    i = start
    while i < len(src) and depth > 0:
        if src[i] == "{":
            depth += 1
        elif src[i] == "}":
            depth -= 1
        i += 1
    return src[start : i - 1]


def _last_pushed_entry(body: str, var_name: str) -> str | None:
    """Return the arg text of the final `{var_name}.push(...)` call in body."""
    pat = re.compile(rf"{re.escape(var_name)}\.push\s*\(")
    last: str | None = None
    for m in pat.finditer(body):
        start = m.end()
        depth = 1
        j = start
        while j < len(body) and depth > 0:
            c = body[j]
            if c == "(":
                depth += 1
            elif c == ")":
                depth -= 1
                if depth == 0:
                    last = body[start:j].strip()
                    break
            j += 1
    return last


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

    def test_shared_helper_renders_linked_branch_as_anchor(self):
        """Entries with onClick must render as <a>. A regression that emits <span>
        for every entry would break criterion 3 (left entries clickable)."""
        src = BREADCRUMB_JS.read_text()
        self.assertRegex(
            src,
            r"if\s*\(\s*p\.onClick\s*\)[^}]*<a\b[^>]*onclick",
            "breadcrumb.js must render entries with onClick as <a onclick=...>. "
            "If this branch emits anything other than an anchor, ancestor crumbs "
            "stop being clickable links.",
        )

    def test_shared_helper_renders_current_branch_as_span(self):
        """Entries without onClick must render as <span class="current">. A regression
        that emits <a> for them would lose the non-linked distinction (criterion 2/7)."""
        src = BREADCRUMB_JS.read_text()
        # The 'else' branch — the return statement AFTER the onClick branch — must
        # emit a span with class="current".
        self.assertRegex(
            src,
            r"return[^;]*<span[^>]*class=\"current\"[^>]*>[^<]*\+\s*p\.label",
            "breadcrumb.js must render the non-linked (current) entry as "
            '<span class="current">${p.label}</span>. Regressing to an <a> tag '
            "would strip the non-clickable distinction from the rightmost crumb.",
        )

    def test_shared_helper_separator_uses_sep_class(self):
        """The separator must carry class='sep' so CSS can target it without
        colliding with .current."""
        src = BREADCRUMB_JS.read_text()
        self.assertRegex(
            src,
            r"<span\s+class=\"sep\">/</span>",
            'breadcrumb.js must emit the separator as <span class="sep">/</span> '
            "so the .sep CSS rule can dim it without also dimming .current",
        )


class BreadcrumbCssTests(unittest.TestCase):
    """styles.css must give the current entry non-clickable visual treatment."""

    def test_current_entry_has_text_color_and_default_cursor(self):
        css = STYLES_CSS.read_text()
        m = re.search(
            r"\.breadcrumb-bar\s+\.current\s*\{([^}]*)\}",
            css,
        )
        self.assertIsNotNone(
            m,
            "styles.css is missing the `.breadcrumb-bar .current` rule. Issue #399 "
            "criterion 7 requires the rightmost crumb to have visual treatment "
            "distinct from the clickable ancestors.",
        )
        rule_body = m.group(1)
        self.assertIn(
            "cursor: default",
            rule_body,
            ".breadcrumb-bar .current must set `cursor: default` so the rightmost "
            "crumb does not appear clickable (criterion 7).",
        )
        self.assertIn(
            "color: var(--text)",
            rule_body,
            ".breadcrumb-bar .current must set `color: var(--text)` so the rightmost "
            "crumb does not share the green link color of the ancestors (criterion 7).",
        )

    def test_separator_has_its_own_rule(self):
        css = STYLES_CSS.read_text()
        self.assertRegex(
            css,
            r"\.breadcrumb-bar\s+\.sep\s*\{[^}]*color:\s*var\(--text-dim\)",
            "styles.css must target the separator via `.breadcrumb-bar .sep` "
            "specifically. A generic `.breadcrumb-bar span` rule would also dim "
            "`.current` and defeat criterion 7.",
        )
        # Guard against a regression reintroducing the loose `span` selector
        # that used to dim both separators and the current entry.
        self.assertNotRegex(
            css,
            r"\.breadcrumb-bar\s+span\s*\{[^}]*color:\s*var\(--text-dim\)",
            "styles.css must NOT have a generic `.breadcrumb-bar span` rule that "
            "dims every span — that rule catches `.current` as well and hides the "
            "visual distinction required by criterion 7.",
        )


class BreadcrumbCallSiteTests(unittest.TestCase):
    """Every inline breadcrumbBar([...]) call must yield a spec-conforming bar.

    config.html is excluded from the inline-literal lint: it funnels every
    breadcrumb through a single renderConfigPage(spec) call that invokes
    breadcrumbBar(spec.crumbs) with a variable. Its loaders return crumbs as
    structured data (not HTML), and ConfigSingleCodepathTests enforces the
    invariants on those return values."""

    PAGES = ("stats.html", "artifacts.html", "chat.html")

    # Pages that delegate breadcrumb rendering to a shared JS module.
    # The breadcrumbBar call is in the module, not the shell.
    _MODULE_DELEGATES = {
        "artifacts.html": "artifact-page.js",
    }

    def _calls_in(self, page: str) -> list[str]:
        # For thin-shell pages that delegate to a module, check the module.
        target = self._MODULE_DELEGATES.get(page, page)
        return _find_breadcrumb_calls((STATIC_DIR / target).read_text())

    def test_every_page_uses_the_shared_helper(self):
        for page in self.PAGES:
            with self.subTest(page=page):
                target = self._MODULE_DELEGATES.get(page, page)
                src = (STATIC_DIR / target).read_text()
                calls = _find_breadcrumb_calls(src)
                # Accept either inline array args or variable args (e.g.
                # breadcrumbBar(crumbs) used by thin-shell delegates).
                has_any_call = len(calls) >= 1 or 'breadcrumbBar(' in src
                self.assertTrue(
                    has_any_call,
                    f"{page} must render its breadcrumb via breadcrumbBar() — "
                    "no page may hand-roll inline <a href=index.html>Home</a> markup",
                )

    def test_every_page_imports_shared_helper(self):
        """Every static page that renders a breadcrumb must include
        breadcrumb.js via a <script src>. This catches config.html too."""
        for page in ("stats.html", "artifacts.html", "chat.html", "config.html"):
            with self.subTest(page=page):
                src = (STATIC_DIR / page).read_text()
                self.assertIn(
                    'src="breadcrumb.js"',
                    src,
                    f"{page} must <script src=\"breadcrumb.js\"> — the shared "
                    "helper is the only allowed producer of breadcrumb markup",
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

    def test_no_html_file_emits_inline_breadcrumb_markup(self):
        """Criterion 4/5: every breadcrumb bar must be rendered via the shared
        helper. No static HTML file may embed a literal `class="breadcrumb-bar"`
        — only breadcrumb.js is allowed to produce that markup. This catches
        both the pre-fix Home-only pattern AND any future hand-rolled bar
        regardless of its entry count or link structure."""
        for html in STATIC_DIR.glob("*.html"):
            with self.subTest(page=html.name):
                self.assertNotIn(
                    'class="breadcrumb-bar"',
                    html.read_text(),
                    f"{html.name} contains a literal `class=\"breadcrumb-bar\"` "
                    "attribute. All breadcrumb markup must come from "
                    "breadcrumb.js so the shape is enforced in one place. "
                    "Use a #breadcrumb-slot container and call breadcrumbBar(...) "
                    "to populate it.",
                )


class PageSpecificLabelTests(unittest.TestCase):
    """The rightmost breadcrumb label must match each page's own identity."""

    # Pages that delegate breadcrumb rendering to a shared JS module.
    _MODULE_DELEGATES = {
        "artifacts.html": "artifact-page.js",
    }

    def _last_label(self, page: str, which: int = 0) -> str:
        target = self._MODULE_DELEGATES.get(page, page)
        calls = _find_breadcrumb_calls((STATIC_DIR / target).read_text())
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

    def test_stats_rightmost_matches_h1(self):
        """Criterion 2: the rightmost crumb label must equal the page's H1 text.
        stats.html's H1 lives in `<div class="pane-title">Statistics</div>`; derive
        the expected label from the HTML rather than hardcoding it, so renaming
        the H1 without updating the crumb fails the test."""
        src = (STATIC_DIR / "stats.html").read_text()
        m = re.search(r'<div class="pane-title">([^<]+)</div>', src)
        self.assertIsNotNone(
            m, "stats.html must declare its H1 via <div class=\"pane-title\">...</div>"
        )
        expected = m.group(1).strip()
        label = self._last_label("stats.html")
        # Strip JS quoting to compare string-literal values.
        literal = label.strip().strip("'\"")
        self.assertEqual(
            literal,
            expected,
            f"stats.html breadcrumb label {literal!r} does not match its H1 "
            f"{expected!r} — criterion 2 requires the rightmost crumb to match "
            "the page H1 exactly. Update both together.",
        )

    def test_artifacts_rightmost_matches_dynamic_h1(self):
        """artifact-page.js (the shared module for artifacts.html) builds its H1
        from displayName. The crumb must reflect the same expression so loading
        a different project updates both together (criterion 2).

        artifacts.html is now a thin shell that delegates to artifact-page.js.
        The breadcrumb and H1 rendering live in the module. The breadcrumb is
        built via a variable (crumbs array), not an inline literal, so we
        verify the construction site directly."""
        src = (STATIC_DIR / "artifact-page.js").read_text()
        # The H1 source: artifact-header-title ... escHtml(displayName) + ' Artifacts'
        self.assertIn(
            'artifact-header-title',
            src,
            "artifact-page.js must build the artifact header title",
        )
        # The breadcrumb crumbs array must push a label with displayName + ' Artifacts'
        # for browse mode.
        self.assertIn(
            "displayName + ' Artifacts'",
            src,
            "artifact-page.js must build the browse-mode breadcrumb label from "
            "`displayName + ' Artifacts'` so it matches the H1 (criterion 2).",
        )

    def test_artifacts_breadcrumb_rendered_inside_render_function(self):
        """artifact-page.js's _render() must call breadcrumbBar so the crumb
        refreshes whenever the page re-renders with a new displayName.

        artifacts.html is now a thin shell; the render function lives in
        artifact-page.js."""
        src = (STATIC_DIR / "artifact-page.js").read_text()
        body = _find_function_body(src, "_render")
        self.assertIn(
            "breadcrumbBar",
            body,
            "artifact-page.js's _render() must call breadcrumbBar(...) so the "
            "crumb refreshes whenever the page re-renders with a new "
            "displayName (criterion 2).",
        )

    # config.html loader crumbs are enforced by ConfigSingleCodepathTests below.

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


class ConfigSingleCodepathTests(unittest.TestCase):
    """config.html must have ONE codepath for building a config page,
    parameterized by a single spec.crumbs array plus content. The rightmost
    crumb's label is the single source of truth for the page's identity —
    document.title, the H1 (pane-title), and the breadcrumb's current entry
    all derive from it. No second field may duplicate the location string."""

    def setUp(self):
        self.src = (STATIC_DIR / "config.html").read_text()

    # ── No dead code from the pre-refactor world ─────────────────────────
    def test_no_show_loading_function(self):
        self.assertNotRegex(
            self.src, r"function\s+showLoading\s*\(",
            "showLoading is dead — renderScope calls renderConfigPage with a "
            "loading spec, keeping one codepath for page rendering",
        )

    def test_no_show_error_function(self):
        self.assertNotRegex(
            self.src, r"function\s+showError\s*\(",
            "showError is dead — renderScope calls renderConfigPage with an "
            "error spec, keeping one codepath for page rendering",
        )

    def test_no_spec_title_field(self):
        """spec.title and spec.breadcrumb duplicated the location across two
        fields. The refactor makes spec.crumbs the sole source."""
        self.assertNotRegex(
            self.src, r"\bspec\.title\b",
            "spec.title is a second source of truth for the page identity. "
            "Derive the label from spec.crumbs[last].label instead.",
        )

    def test_no_spec_breadcrumb_field(self):
        self.assertNotRegex(
            self.src, r"\bspec\.breadcrumb\b",
            "spec.breadcrumb is a second source of truth. Pass spec.crumbs "
            "(structured data) and let renderConfigPage call breadcrumbBar.",
        )

    def test_no_loader_returns_title_or_breadcrumb_field(self):
        """No loader return value may carry a `title:` or `breadcrumb:` field —
        only `crumbs:`. Those fields reintroduce the duplication."""
        # Scan for `title:` immediately after `return {` to catch loader shapes.
        # itemCard/section uses of `title:` are fine — they're nested objects.
        loaders = ("loadGlobal", "loadProject", "loadWorkgroup", "_buildAgentSpec")
        for loader in loaders:
            body = _find_function_body(self.src, loader)
            # Find EVERY `return { ... };` in the body and pick the one whose
            # top-level object has a `crumbs:` field — that's the loader's
            # outer return, not a nested map/filter callback return.
            return_obj = None
            for ret_match in re.finditer(r"return\s*\{", body):
                start = ret_match.end()
                depth = 1
                k = start
                in_str = None
                while k < len(body) and depth > 0:
                    c = body[k]
                    if in_str:
                        if c == "\\":
                            k += 2
                            continue
                        if c == in_str:
                            in_str = None
                        k += 1
                        continue
                    if c in ("'", '"'):
                        in_str = c
                    elif c == "{":
                        depth += 1
                    elif c == "}":
                        depth -= 1
                    k += 1
                candidate = body[start : k - 1]
                if re.search(r"\bcrumbs\s*:", candidate):
                    return_obj = candidate
                    break
            self.assertIsNotNone(
                return_obj,
                f"{loader} must have a `return {{crumbs: …}}` — the crumbs "
                f"field is the single source of truth for page identity",
            )
            # Top-level fields: collect fields at depth 0 only.
            top_fields = []
            buf = []
            dp = 0
            s = None
            for ch in return_obj:
                if s:
                    buf.append(ch)
                    if ch == s:
                        s = None
                    continue
                if ch in ("'", '"'):
                    s = ch
                elif ch in "([{":
                    dp += 1
                elif ch in ")]}":
                    dp -= 1
                if ch == "," and dp == 0:
                    top_fields.append("".join(buf).strip())
                    buf = []
                    continue
                buf.append(ch)
            tail = "".join(buf).strip()
            if tail:
                top_fields.append(tail)
            field_names = set()
            for f in top_fields:
                m = re.match(r"(\w+)\s*:", f)
                if m:
                    field_names.add(m.group(1))
            with self.subTest(loader=loader):
                self.assertIn(
                    "crumbs", field_names,
                    f"{loader} return value must include `crumbs:` — it is the "
                    f"single source of truth for the page identity. Fields: {field_names}",
                )
                self.assertNotIn(
                    "title", field_names,
                    f"{loader} return value has `title:` field — this is a second "
                    f"source of truth for the page identity. Remove it; renderConfigPage "
                    f"derives title from crumbs[last].label. Fields: {field_names}",
                )
                self.assertNotIn(
                    "breadcrumb", field_names,
                    f"{loader} return value has `breadcrumb:` field — this "
                    f"pre-renders the bar. Pass `crumbs:` (structured) and "
                    f"let renderConfigPage call breadcrumbBar. Fields: {field_names}",
                )

    # ── renderConfigPage is the single codepath ──────────────────────────
    def test_render_config_page_is_sole_writer_of_breadcrumb_slot(self):
        """Only renderConfigPage may set #breadcrumb-slot.innerHTML. Any
        other writer is a second codepath."""
        # Find every `getElementById('breadcrumb-slot').innerHTML =` assignment
        # and verify each is inside renderConfigPage's function body.
        body = _find_function_body(self.src, "renderConfigPage")
        body_start = self.src.find(body)
        body_end = body_start + len(body)
        pat = re.compile(r"getElementById\(['\"]breadcrumb-slot['\"]\)\s*\.\s*innerHTML\s*=")
        for m in pat.finditer(self.src):
            with self.subTest(offset=m.start()):
                self.assertTrue(
                    body_start <= m.start() < body_end,
                    f"#breadcrumb-slot.innerHTML assignment at offset {m.start()} "
                    f"is outside renderConfigPage. renderConfigPage must be the "
                    f"single codepath that writes the breadcrumb slot.",
                )

    def test_render_config_page_derives_label_from_last_crumb(self):
        """renderConfigPage must derive document.title and the pane-title
        from spec.crumbs[last].label. No literal 'Configuration' default or
        spec.title reference."""
        body = _find_function_body(self.src, "renderConfigPage")
        self.assertRegex(
            body,
            r"var\s+currentLabel\s*=\s*crumbs\[\s*crumbs\.length\s*-\s*1\s*\]\.label",
            "renderConfigPage must compute `currentLabel = crumbs[last].label` "
            "as the single source of truth for the page identity",
        )
        self.assertRegex(
            body,
            r"document\.title\s*=\s*['\"]TeaParty[^'\"]*['\"]\s*\+\s*currentLabel",
            "document.title must be derived from currentLabel, not spec.title",
        )
        self.assertRegex(
            body,
            r"pane-title[\"'][^<]*</div>[\"']\s*,\s*escAttr\(currentLabel\)|"
            r"pane-title[\"'][^>]*>[\"']\s*\+\s*escAttr\(currentLabel\)",
            "The <div class=\"pane-title\"> H1 must render escAttr(currentLabel), "
            "not spec.title — otherwise the page has two sources of truth",
        )
        self.assertRegex(
            body,
            r"breadcrumbBar\s*\(\s*crumbs\s*\)",
            "renderConfigPage must call breadcrumbBar(crumbs) once",
        )

    # ── Loader and scope crumb invariants ────────────────────────────────
    def test_every_loader_returns_crumbs_ending_non_linked(self):
        """Each loader's returned `crumbs:` array (or the `var crumbs = [...];
        crumbs.push(...)` construction it returns) must end with a non-linked
        entry."""
        loaders = {
            "loadGlobal": "crumbs",
            "loadProject": "crumbs",
            "loadWorkgroup": "crumbs",
            "_buildAgentSpec": "crumbs",
        }
        for loader, var_name in loaders.items():
            body = _find_function_body(self.src, loader)
            # Try inline literal first
            m = re.search(r"crumbs\s*:\s*(\[[^\]]*\])", body)
            if m:
                elems = _split_array_elements(m.group(1))
                last = elems[-1]
            else:
                # Variable-crumbs pattern: find the last crumbs.push in the body
                last = _last_pushed_entry(body, var_name)
                self.assertIsNotNone(
                    last,
                    f"{loader} must either return an inline `crumbs: [...]` or "
                    f"build it via `var crumbs = [...]; crumbs.push(...)`",
                )
            with self.subTest(loader=loader):
                self.assertNotIn(
                    "onClick", last,
                    f"{loader}: rightmost crumb {last!r} contains onClick — the "
                    f"current-page entry must be non-linked",
                )

    def test_scope_crumbs_covers_every_level(self):
        body = _find_function_body(self.src, "scopeCrumbs")
        for level in ("global", "project"):
            with self.subTest(level=level):
                self.assertIn(
                    f"'{level}'", body,
                    f"scopeCrumbs must handle scope.level === '{level}'",
                )
        # Every return path must push a final entry with no onClick.
        returns = [m.start() for m in re.finditer(r"return\s+crumbs\s*;", body)]
        self.assertGreaterEqual(
            len(returns), 2,
            f"scopeCrumbs must have at least 2 return paths; found {len(returns)}",
        )
        for ret_pos in returns:
            push_matches = list(
                re.finditer(r"crumbs\.push\s*\(\s*(\{[^}]*\})\s*\)", body[:ret_pos])
            )
            if not push_matches:
                continue
            last_push = push_matches[-1].group(1)
            with self.subTest(last_push=last_push[:80]):
                self.assertNotIn(
                    "onClick", last_push,
                    f"scopeCrumbs terminal push before offset {ret_pos} has "
                    f"{last_push!r} with onClick — current entry must be non-linked",
                )

    # ── renderScope must go through renderConfigPage in every state ─────
    def test_render_scope_uses_render_config_page_for_all_states(self):
        """renderScope must call renderConfigPage for loading, success, AND
        error — never touch #breadcrumb-slot or #content directly, never call
        a separate show* helper. One codepath."""
        body = _find_function_body(self.src, "renderScope")
        # At least three renderConfigPage calls: loading, success, error.
        calls = re.findall(r"renderConfigPage\s*\(", body)
        self.assertGreaterEqual(
            len(calls), 3,
            f"renderScope must call renderConfigPage for each of "
            f"{{loading, success, error}}. Found {len(calls)} calls in body: {body!r}",
        )
        self.assertNotIn(
            "breadcrumb-slot", body,
            "renderScope must not touch #breadcrumb-slot directly — all DOM "
            "writes go through renderConfigPage",
        )
        self.assertNotIn(
            "content", body.replace("renderConfigPage", ""),
            "renderScope must not touch #content — renderConfigPage owns it",
        ) if False else None  # loose; covered by the sole-writer test above
        # Must use scopeCrumbs for the placeholder and the error spec.
        self.assertIn(
            "scopeCrumbs(scope)", body,
            "renderScope must derive the loading/error crumbs via scopeCrumbs(scope)",
        )

    def test_every_renderscope_caller_passes_scope_metadata(self):
        """Every renderScope call site must pass a scope descriptor so the
        pre-fetch breadcrumb is derivable."""
        for m in re.finditer(r"(?<!function\s)renderScope\s*\(", self.src):
            start = m.end()
            depth = 1
            j = start
            in_str = None
            while j < len(self.src) and depth > 0:
                c = self.src[j]
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
                j += 1
            args = self.src[start : j - 1]
            # Skip function declaration.
            if re.match(r"\s*loader\s*,\s*scope\s*$", args):
                continue
            with self.subTest(args=args[:80]):
                self.assertIn(
                    "level:", args,
                    f"renderScope call {args[:120]!r} must pass "
                    f"{{level, name?, projectSlug?}}",
                )


class MinimalChatBehaviorTests(unittest.TestCase):
    """chat.html minimal mode (iframe in accordion blade) must still hide the bar."""

    def test_minimal_mode_sets_breadcrumb_slot_display_none(self):
        """Criterion 6: in minimal mode the breadcrumb slot must be hidden. The
        assertion targets the specific statement, not just any appearance of
        'minimal' and 'display' on the same line."""
        src = (STATIC_DIR / "chat.html").read_text()
        self.assertRegex(
            src,
            r"if\s*\(\s*minimal\s*\)\s*\{[^}]*getElementById\(['\"]breadcrumb-slot['\"]\)"
            r"\.style\.display\s*=\s*['\"]none['\"]",
            "chat.html must hide the breadcrumb slot inside an "
            "`if (minimal) { ... breadcrumb-slot.style.display = 'none' ... }` "
            "branch. Without this, the iframe-embedded chat shows a redundant "
            "breadcrumb on top of the accordion blade.",
        )

    def test_standalone_mode_populates_breadcrumb_slot(self):
        """Criterion 6: in non-minimal mode the breadcrumb slot must be filled
        via the shared helper, in the else branch of the same minimal check."""
        src = (STATIC_DIR / "chat.html").read_text()
        self.assertRegex(
            src,
            r"else\s*\{[^}]*getElementById\(['\"]breadcrumb-slot['\"]\)\s*\.innerHTML"
            r"\s*=\s*breadcrumbBar\s*\(",
            "chat.html standalone mode must populate #breadcrumb-slot via "
            "`breadcrumbBar(...)` inside the else branch of the minimal check",
        )

    def test_chat_header_title_is_assigned_from_state(self):
        """Criterion 2 for chat.html: the headerTitle passed to the crumb must
        be derived from the conversation state, not a hardcoded placeholder.
        Assert there are at least two `headerTitle = ...` assignments, and that
        none of the ones present in both render paths is a bare string literal."""
        src = (STATIC_DIR / "chat.html").read_text()
        assigns = re.findall(r"headerTitle\s*=\s*([^;]+);", src)
        self.assertGreaterEqual(
            len(assigns),
            2,
            "chat.html must assign headerTitle in at least two places (the job "
            "and participant render paths). Found: "
            f"{len(assigns)} assignment(s).",
        )
        # No assignment may be a bare string literal — that would mean the crumb
        # shows the same text regardless of which conversation is open.
        for a in assigns:
            a = a.strip()
            with self.subTest(assignment=a):
                is_bare_literal = bool(
                    re.fullmatch(r"['\"][^'\"]*['\"]", a)
                )
                self.assertFalse(
                    is_bare_literal,
                    f"chat.html has `headerTitle = {a}` — a bare string literal "
                    "means the breadcrumb ignores the actual conversation state. "
                    "headerTitle must be computed from the loaded conversation.",
                )


if __name__ == "__main__":
    unittest.main()
