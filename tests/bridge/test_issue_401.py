"""Issue #401: Internal links must open in place, never in a new tab.

The TeaParty UI must not programmatically spawn tabs or windows for internal
navigation. Concretely, under ``teaparty/bridge/static/``:

1. No occurrence of ``window.open`` may exist in any ``.html`` file. The
   intent is absolute — every programmatic navigation to another internal
   page assigns to ``location.href`` instead.

2. No ``target="_blank"`` (or single-quoted equivalent) may appear on an
   internal anchor. An allowlist covers exactly one external-link exception:
   the generic Markdown renderer in ``chat.html`` that produces anchors for
   arbitrary URLs inside agent message content (lines 233 and 235 of the
   renderer for ``isJobChat`` relative paths and generic external hrefs).

   Note: the issue says line 233 (the ``isJobChat`` session-file branch) is
   also internal and must be rewritten. Only line 235 — the generic external
   href — remains allowlisted.

A grep of the static tree confirms both rules; this test is the enforcement
point the issue's success criterion #6 calls for.
"""
from __future__ import annotations

import pathlib
import re
import unittest


REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
STATIC_DIR = REPO_ROOT / 'teaparty' / 'bridge' / 'static'

# Allowlist: (relative path from STATIC_DIR, line substring) for the ONE
# external-link exception. Every other occurrence is a violation.
TARGET_BLANK_ALLOWLIST = {
    # chat.html generic Markdown renderer for arbitrary external URLs in
    # agent message content. See issue #401 scope: external links are out
    # of scope.
    ('chat.html', "return '<a href=\"' + href + '\" target=\"_blank\">' + label + '</a>';"),
}


def _iter_html_files() -> list[pathlib.Path]:
    return sorted(STATIC_DIR.rglob('*.html'))


class NavigationInPlaceTests(unittest.TestCase):
    """Issue #401 enforcement: internal navigation never spawns tabs."""

    def test_no_window_open_in_static_html(self) -> None:
        """No file under teaparty/bridge/static may call window.open.

        `window.open` is the programmatic tab-spawn the issue forbids.
        Every internal navigation must use `location.href = ...` instead.
        A match here means a regression was introduced that will silently
        start opening new tabs on the user.
        """
        offenders: list[str] = []
        for path in _iter_html_files():
            text = path.read_text()
            for lineno, line in enumerate(text.splitlines(), start=1):
                if 'window.open' in line:
                    rel = path.relative_to(STATIC_DIR).as_posix()
                    offenders.append(f"{rel}:{lineno}: {line.strip()}")
        self.assertEqual(
            offenders,
            [],
            "Issue #401: teaparty/bridge/static contains window.open calls. "
            "Internal navigation must use location.href. Offenders:\n  "
            + "\n  ".join(offenders),
        )

    def test_no_internal_target_blank_in_static_html(self) -> None:
        """No internal anchor may carry target="_blank".

        The single allowlisted exception is the generic Markdown renderer
        in chat.html that produces anchors for arbitrary external URLs
        inside agent message content (see TARGET_BLANK_ALLOWLIST). Any
        other occurrence is a regression.
        """
        pattern = re.compile(r'''target\s*=\s*["']_blank["']''')
        offenders: list[str] = []
        for path in _iter_html_files():
            text = path.read_text()
            rel = path.relative_to(STATIC_DIR).as_posix()
            for lineno, line in enumerate(text.splitlines(), start=1):
                if not pattern.search(line):
                    continue
                if (rel, line.strip()) in TARGET_BLANK_ALLOWLIST:
                    continue
                offenders.append(f"{rel}:{lineno}: {line.strip()}")
        self.assertEqual(
            offenders,
            [],
            "Issue #401: teaparty/bridge/static contains target=\"_blank\" "
            "on internal anchors. Remove the attribute so internal links "
            "open in place. Offenders:\n  "
            + "\n  ".join(offenders),
        )

    def test_allowlist_entries_still_exist(self) -> None:
        """Every TARGET_BLANK_ALLOWLIST entry must still match a real line.

        Dead allowlist entries silently weaken the rule — if the code has
        changed, the allowlist must shrink with it.
        """
        for rel, expected in TARGET_BLANK_ALLOWLIST:
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
