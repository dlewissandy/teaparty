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
        """artifacts.html's H1 is built in render() as `{displayName} Artifacts`.
        The crumb must reflect the same expression, not a hardcoded literal, so
        loading a different project updates both together (criterion 2)."""
        src = (STATIC_DIR / "artifacts.html").read_text()
        # The H1 source: <span class="artifact-header-title">' + escHtml(displayName) + ' Artifacts</span>
        self.assertRegex(
            src,
            r'artifact-header-title"[^>]*>\'\s*\+\s*escHtml\(displayName\)\s*\+\s*\'\s*Artifacts',
            "artifacts.html must build its H1 from `displayName + ' Artifacts'` — "
            "if this changes, update the crumb in the same render() call together.",
        )
        label = self._last_label("artifacts.html")
        # Crumb label must also reference displayName AND end with ' Artifacts'
        # so the two always render identical strings.
        self.assertIn(
            "displayName",
            label,
            f"artifacts.html rightmost crumb label is {label!r}, but the H1 is "
            "built from `displayName`. The crumb must reference `displayName` "
            "too so they always agree (criterion 2). Hardcoding 'Artifacts' "
            "leaves the crumb stale when a different project is loaded.",
        )
        self.assertIn(
            "Artifacts",
            label,
            f"artifacts.html rightmost crumb label is {label!r}, expected it to "
            "end with ' Artifacts' to match the H1",
        )

    def test_artifacts_breadcrumb_rendered_inside_render_function(self):
        """artifacts.html's crumb must be re-rendered whenever render() runs, so
        changing project (and therefore displayName) updates the crumb. A single
        DOMContentLoaded injection is not enough — it would leave the crumb
        frozen at the initial project's name."""
        src = (STATIC_DIR / "artifacts.html").read_text()
        body = _find_function_body(src, "render")
        self.assertIn(
            "breadcrumbBar",
            body,
            "artifacts.html's render() must call breadcrumbBar(...) so the "
            "crumb refreshes whenever the page re-renders with a new "
            "displayName (criterion 2).",
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

    def test_config_loadworkgroup_last_crumb_is_nonlinked(self):
        """loadWorkgroup builds its bar via `var crumbs = [...]; crumbs.push(...)`
        and passes `crumbs` (a variable) to breadcrumbBar. The inline-literal
        linter skips this path, so check the final `.push(...)` explicitly: its
        object literal must not contain onClick (criterion 1)."""
        src = (STATIC_DIR / "config.html").read_text()
        body = _find_function_body(src, "loadWorkgroup")
        last = _last_pushed_entry(body, "crumbs")
        self.assertIsNotNone(
            last,
            "loadWorkgroup must build its breadcrumb via crumbs.push(...) calls",
        )
        self.assertNotIn(
            "onClick",
            last,
            f"loadWorkgroup's final crumbs.push entry {last!r} contains onClick "
            "— the rightmost crumb (current workgroup) must be non-linked",
        )
        # And the current-entry label must match the workgroup name that titles
        # the page (spec.title in the same function).
        self.assertRegex(
            body,
            r"title:\s*name\b",
            "loadWorkgroup must set `title: name` so the H1 matches the "
            "rightmost crumb label (criterion 2)",
        )
        self.assertIn(
            "name",
            last,
            f"loadWorkgroup's final crumb {last!r} must reference the workgroup "
            "`name` so the crumb matches the page H1",
        )

    def test_config_buildagentspec_last_crumb_is_nonlinked(self):
        """_buildAgentSpec uses the same crumbs-variable pattern as loadWorkgroup
        and is invisible to the inline-literal linter for the same reason."""
        src = (STATIC_DIR / "config.html").read_text()
        body = _find_function_body(src, "_buildAgentSpec")
        last = _last_pushed_entry(body, "crumbs")
        self.assertIsNotNone(
            last,
            "_buildAgentSpec must build its breadcrumb via crumbs.push(...) calls",
        )
        self.assertNotIn(
            "onClick",
            last,
            f"_buildAgentSpec's final crumbs.push entry {last!r} contains "
            "onClick — the rightmost crumb (current agent) must be non-linked",
        )
        self.assertIn(
            "name",
            last,
            f"_buildAgentSpec's final crumb {last!r} must reference `name` so "
            "it matches the agent detail H1 (criterion 2)",
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


class ConfigLoadingAndErrorBreadcrumbTests(unittest.TestCase):
    """Criterion 1: every page shows its current location as the rightmost
    breadcrumb entry — including during loading and after a fetch error.
    config.html used to blank the slot in showLoading/showError, leaving the
    user with no "you are here" indicator until the data resolved. The fix
    pre-populates the slot from URL scope before the fetch fires."""

    def test_show_loading_does_not_blank_breadcrumb_slot(self):
        src = (STATIC_DIR / "config.html").read_text()
        body = _find_function_body(src, "showLoading")
        self.assertNotIn(
            "breadcrumb-slot",
            body,
            "showLoading() must not touch #breadcrumb-slot — blanking the slot "
            "during an in-flight fetch leaves the user with no 'you are here' "
            "indicator. The slot is populated from URL scope before the fetch "
            "fires in renderScope.",
        )

    def test_show_error_does_not_blank_breadcrumb_slot(self):
        src = (STATIC_DIR / "config.html").read_text()
        body = _find_function_body(src, "showError")
        self.assertNotIn(
            "breadcrumb-slot",
            body,
            "showError() must not touch #breadcrumb-slot — blanking the slot on "
            "a failed fetch leaves the error screen with no location indicator. "
            "The scope-derived crumb from renderScope must survive the error.",
        )

    def test_render_scope_populates_breadcrumb_before_loading(self):
        """renderScope must call breadcrumbBar(scopeCrumbs(...)) into the slot
        *before* awaiting the loader, so the bar is visible during the in-flight
        fetch and survives a rejection."""
        src = (STATIC_DIR / "config.html").read_text()
        body = _find_function_body(src, "renderScope")
        # Sequence: slot population → showLoading → loader.
        idx_slot = body.find("breadcrumb-slot")
        idx_load = body.find("showLoading")
        idx_await = body.find("await loader")
        self.assertGreater(
            idx_slot, -1, "renderScope must set the breadcrumb-slot innerHTML"
        )
        self.assertGreater(
            idx_load, idx_slot,
            "renderScope must populate the breadcrumb slot BEFORE calling "
            "showLoading — otherwise the Loading... placeholder flashes with "
            "no location context",
        )
        self.assertGreater(
            idx_await, idx_load,
            "renderScope must await the loader only AFTER both the breadcrumb "
            "is set and showLoading has run",
        )
        self.assertRegex(
            body,
            r"breadcrumbBar\s*\(\s*scopeCrumbs\s*\(\s*scope\s*\)\s*\)",
            "renderScope must derive the initial crumbs via scopeCrumbs(scope) "
            "so every scope level (global/project/workgroup/agent) has a "
            "consistent pre-fetch breadcrumb",
        )

    def test_scope_crumbs_helper_covers_every_level(self):
        """scopeCrumbs must handle all four scope levels and produce a
        rightmost non-linked entry for each."""
        src = (STATIC_DIR / "config.html").read_text()
        body = _find_function_body(src, "scopeCrumbs")
        for level in ("global", "project", "workgroup", "agent"):
            with self.subTest(level=level):
                # loadAgent and loadWorkgroup share the same tail branch, so
                # 'global' and 'project' need explicit mentions; the tail
                # catches 'workgroup' and 'agent' via the generic fallthrough.
                if level in ("global", "project"):
                    self.assertIn(
                        f"'{level}'",
                        body,
                        f"scopeCrumbs must handle scope.level === '{level}' "
                        "explicitly",
                    )
        # Rightmost entry must be non-linked in every branch: there must be at
        # least one `crumbs.push({ label: ... })` that has no `onClick` field.
        self.assertRegex(
            body,
            r"crumbs\.push\s*\(\s*\{\s*label:\s*[^}]*\}\s*\)",
            "scopeCrumbs must push a current (non-linked) entry with just a label",
        )
        # Verify none of the terminal pushes leak an onClick by scanning the
        # final push in every control-flow path.
        pushes = re.findall(r"crumbs\.push\s*\(\s*(\{[^}]*\})\s*\)", body)
        self.assertGreaterEqual(
            len(pushes), 4,
            f"scopeCrumbs must push at least 4 distinct entries across its "
            f"branches (Home, Management Team, optional project, current). "
            f"Found {len(pushes)}.",
        )
        # The helper must end with a non-onClick push in each terminal return
        # path. Check that the LAST push before each `return crumbs;` has no
        # onClick.
        returns = [m.start() for m in re.finditer(r"return\s+crumbs\s*;", body)]
        self.assertGreaterEqual(
            len(returns), 2,
            f"scopeCrumbs must have multiple return paths (at least "
            "global-only and non-global). Found " f"{len(returns)}.",
        )
        for ret_pos in returns:
            preceding = body[:ret_pos]
            push_matches = list(
                re.finditer(r"crumbs\.push\s*\(\s*(\{[^}]*\})\s*\)", preceding)
            )
            if not push_matches:
                continue
            last_push = push_matches[-1].group(1)
            with self.subTest(last_push=last_push[:80]):
                self.assertNotIn(
                    "onClick",
                    last_push,
                    f"scopeCrumbs path ending at byte {ret_pos} has last push "
                    f"{last_push!r} containing onClick — the rightmost crumb "
                    "must be non-linked",
                )

    def test_every_renderscope_caller_passes_scope_metadata(self):
        """Every renderScope(...) call site must pass a scope descriptor so
        the pre-fetch breadcrumb is derivable. A caller that omits scope would
        render an empty crumb during loading/error."""
        src = (STATIC_DIR / "config.html").read_text()
        # Match every renderScope(...) call and extract the argument list.
        # Skip the function declaration itself.
        for m in re.finditer(r"(?<!function\s)renderScope\s*\(", src):
            start = m.end()
            depth = 1
            j = start
            in_str: str | None = None
            while j < len(src) and depth > 0:
                c = src[j]
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
            args = src[start : j - 1]
            # Skip the function declaration (it has parameter names, not a call)
            if re.match(r"\s*loader\s*,\s*scope\s*$", args):
                continue
            with self.subTest(args=args[:80]):
                self.assertIn(
                    "level:",
                    args,
                    f"renderScope call {args[:120]!r} is missing a scope "
                    "descriptor with `level:`. Every call site must pass "
                    "{level, name, projectSlug} so the pre-fetch breadcrumb "
                    "matches the scope.",
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
