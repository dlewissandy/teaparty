"""Issue #401: Internal links must open in place, never in a new tab.

The TeaParty UI must not programmatically spawn tabs or windows for
internal navigation, AND any element that navigates to a new page must
be an ``<a href>`` so browser-native gestures (Cmd-click, middle-click)
work. Concretely, under ``teaparty/bridge/static/``:

1. No occurrence of ``window.open`` may exist in any text source file.

2. No ``target="_blank"`` (or single-quoted / unquoted equivalent) may
   appear on an internal anchor. An allowlist covers exactly one
   external-link exception: the generic Markdown renderer in ``chat.html``
   that produces anchors for arbitrary URLs inside agent message content.

3. No inline ``onclick`` handler may navigate via ``location.href`` or
   ``window.location`` assignment. Navigation handlers must be ``<a
   href>`` elements so Cmd-click, Ctrl-click, and middle-click open the
   destination in a new tab natively. Assignments to ``location.href``
   inside plain JS function bodies (e.g. post-fetch navigation) are
   allowed because there is no click target to make into an anchor.

See ``docs/systems/bridge/navigation.md`` for the convention these
tests enforce.
"""
from __future__ import annotations

import pathlib
import re
import unittest


REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
STATIC_DIR = REPO_ROOT / 'teaparty' / 'bridge' / 'static'
CONVENTION_DOC = 'docs/systems/bridge/navigation.md'

# Every file extension we expect to find under STATIC_DIR. If a new
# extension appears, test_static_tree_shape fails and forces the author to
# decide consciously whether the guard needs to cover it. This pins the
# "rglob over the tree" assumption down so a future .js file cannot
# silently escape the guard.
TEXT_EXTENSIONS = {'.html', '.htm', '.js', '.mjs', '.ts', '.tsx', '.jsx',
                   '.vue', '.svelte', '.css', '.md', '.json', '.svg'}
BINARY_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.gif', '.ico', '.webp',
                     '.woff', '.woff2', '.ttf', '.otf', '.eot'}

# Allowlist entry: (relative path, expected stripped line). Each entry
# must match exactly one line in the file, and that line is the single
# allowlisted occurrence of target="_blank" for that file. Any second
# occurrence — e.g. from copy-paste duplication — will fail the test.
TARGET_BLANK_ALLOWLIST: dict[str, str] = {
    # chat.html generic Markdown renderer for arbitrary external URLs in
    # agent message content. See issue #401 scope: external links are out
    # of scope.
    'chat.html': "return '<a href=\"' + href + '\" target=\"_blank\">' + label + '</a>';",
}


def _iter_scannable_files() -> list[pathlib.Path]:
    """Every text source file under STATIC_DIR."""
    return sorted(
        p for p in STATIC_DIR.rglob('*')
        if p.is_file() and p.suffix.lower() in TEXT_EXTENSIONS
    )


class NavigationInPlaceTests(unittest.TestCase):
    """Issue #401 enforcement: internal navigation never spawns tabs."""

    def test_static_tree_shape(self) -> None:
        """Every file under STATIC_DIR must be a known text or binary type.

        The regression guards below scan TEXT_EXTENSIONS. If a commit
        introduces a new extension (a `.jsx` file, a `.vue` component),
        this test fails and forces the author to add the extension to
        TEXT_EXTENSIONS consciously — preventing silent evacuation of
        the guard via a new file type.
        """
        known = TEXT_EXTENSIONS | BINARY_EXTENSIONS
        unknown: list[str] = []
        for path in STATIC_DIR.rglob('*'):
            if not path.is_file():
                continue
            if path.suffix.lower() not in known:
                unknown.append(path.relative_to(STATIC_DIR).as_posix())
        self.assertEqual(
            unknown,
            [],
            f"Issue #401: unknown file extensions under "
            f"teaparty/bridge/static/. Add each to TEXT_EXTENSIONS or "
            f"BINARY_EXTENSIONS in this test so the window.open / "
            f"target=_blank guards either cover it or explicitly skip "
            f"it. See {CONVENTION_DOC}. Offenders: {unknown}",
        )

    def test_no_window_open_in_static_sources(self) -> None:
        """No text source under teaparty/bridge/static may call window.open.

        `window.open` is the programmatic tab-spawn the issue forbids.
        Every internal navigation must use `location.href = ...` instead.
        A match here means a regression was introduced that will silently
        start opening new tabs on the user.
        """
        offenders: list[str] = []
        for path in _iter_scannable_files():
            text = path.read_text()
            for lineno, line in enumerate(text.splitlines(), start=1):
                if 'window.open' in line:
                    rel = path.relative_to(STATIC_DIR).as_posix()
                    offenders.append(f"{rel}:{lineno}: {line.strip()}")
        self.assertEqual(
            offenders,
            [],
            f"Issue #401: teaparty/bridge/static contains window.open "
            f"calls. Internal navigation must use location.href. See "
            f"{CONVENTION_DOC}. Offenders:\n  "
            + "\n  ".join(offenders),
        )

    def test_no_internal_target_blank_in_static_sources(self) -> None:
        """No internal anchor may carry target="_blank".

        The single allowlisted exception per file lives in
        TARGET_BLANK_ALLOWLIST. Exactly one line per allowlisted file may
        match the pattern, and it must match the expected stripped text —
        a duplicate (e.g. copy-paste refactor) fails the test.
        """
        # Match double-quoted, single-quoted, AND unquoted forms:
        # target="_blank", target='_blank', target=_blank.
        pattern = re.compile(r'''target\s*=\s*["']?_blank["']?\b''')
        offenders: list[str] = []
        allowlist_hits: dict[str, list[tuple[int, str]]] = {
            rel: [] for rel in TARGET_BLANK_ALLOWLIST
        }
        for path in _iter_scannable_files():
            text = path.read_text()
            rel = path.relative_to(STATIC_DIR).as_posix()
            for lineno, line in enumerate(text.splitlines(), start=1):
                if not pattern.search(line):
                    continue
                stripped = line.strip()
                expected = TARGET_BLANK_ALLOWLIST.get(rel)
                if expected is not None and stripped == expected:
                    allowlist_hits[rel].append((lineno, stripped))
                    continue
                offenders.append(f"{rel}:{lineno}: {stripped}")
        self.assertEqual(
            offenders,
            [],
            f"Issue #401: teaparty/bridge/static contains target=\"_blank\" "
            f"on internal anchors. Remove the attribute so internal links "
            f"open in place. See {CONVENTION_DOC}. Offenders:\n  "
            + "\n  ".join(offenders),
        )
        # Every allowlist entry must match exactly one line — no silent
        # duplication.
        for rel, hits in allowlist_hits.items():
            self.assertEqual(
                len(hits),
                1,
                f"Issue #401: allowlisted external-link exception in "
                f"{rel} must match exactly one line; got {len(hits)} "
                f"matches at lines {[h[0] for h in hits]}. "
                f"Duplicate renderer branches are silent regressions.",
            )

    def test_no_onclick_navigation_via_location_href(self) -> None:
        """No onclick handler may navigate via location.href assignment.

        Anything that changes the page must be an `<a href>` so
        browser-native gestures (Cmd-click, middle-click, etc.) work.
        An `onclick="location.href='...'"` handler strips those
        gestures — plain click works, but the user can no longer
        choose to open the target in a new tab.

        This test is deliberately scoped to inline event attributes
        (``onclick="..."``, ``onClick: "..."``), not to assignments
        inside plain JS function bodies. Post-fetch navigation
        (e.g. createJob → POST → location.href = new_url) has no
        click target to convert into an anchor and is exempt.
        """
        inline_onclick = re.compile(
            r'''on[cC]lick\s*[=:]\s*["'][^"']*\blocation\s*\.\s*href\b'''
        )
        offenders: list[str] = []
        for path in _iter_scannable_files():
            text = path.read_text()
            rel = path.relative_to(STATIC_DIR).as_posix()
            for lineno, line in enumerate(text.splitlines(), start=1):
                if inline_onclick.search(line):
                    offenders.append(f"{rel}:{lineno}: {line.strip()}")
        self.assertEqual(
            offenders,
            [],
            f"Issue #401: teaparty/bridge/static contains onclick "
            f"handlers that navigate via location.href. Use an "
            f"<a href=\"...\"> element instead so Cmd-click / "
            f"middle-click open the target in a new tab. See "
            f"{CONVENTION_DOC}. Offenders:\n  "
            + "\n  ".join(offenders),
        )

    def test_allowlist_entries_still_exist(self) -> None:
        """Every TARGET_BLANK_ALLOWLIST entry must still match a real line.

        Dead allowlist entries silently weaken the rule — if the code has
        changed, the allowlist must shrink with it.
        """
        for rel, expected in TARGET_BLANK_ALLOWLIST.items():
            path = STATIC_DIR / rel
            self.assertTrue(
                path.exists(),
                f"Issue #401: allowlisted file {rel} no longer exists; "
                f"remove the stale entry from TARGET_BLANK_ALLOWLIST.",
            )
            text = path.read_text()
            stripped_lines = {line.strip() for line in text.splitlines()}
            self.assertIn(
                expected,
                stripped_lines,
                f"Issue #401: allowlisted line in {rel} no longer matches "
                f"source. Expected: {expected!r}. Update or remove the "
                f"TARGET_BLANK_ALLOWLIST entry.",
            )


if __name__ == '__main__':
    unittest.main()
