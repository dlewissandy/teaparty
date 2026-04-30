"""Issue #425: structural assertion that one participants-card component
is used by every page that surfaces one.

The acceptance bullet reads: "Every page that surfaces a participants
card uses the same component; clicking a participant produces a launch
with the cwd from the Intent table."  The per-qualifier resolver is
covered separately (`tests/bridge/test_proxy_chat_cwd_425.py`).  This
test pins the structural half: there is exactly one ``participantItems``
function definition in the bridge frontend, and it is the only producer
of proxy-chat URLs from a participants card — no per-page divergent
copies, no ad-hoc click handlers that bypass the resolver.
"""
from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))


_STATIC_DIR = (
    Path(__file__).resolve().parents[2] / 'teaparty' / 'bridge' / 'static'
)


def _read_all_html_and_js() -> dict[str, str]:
    """Return {relative_path: content} for every HTML/JS file under static/."""
    out: dict[str, str] = {}
    for path in _STATIC_DIR.rglob('*'):
        if path.suffix not in ('.html', '.js'):
            continue
        out[str(path.relative_to(_STATIC_DIR))] = path.read_text()
    return out


class ParticipantsCardSingleDefinitionTest(unittest.TestCase):
    """Exactly one ``function participantItems`` definition exists."""

    def test_one_definition_in_static_bundle(self) -> None:
        files = _read_all_html_and_js()
        defining = []
        for relpath, content in files.items():
            # Match ``function participantItems(`` with optional whitespace.
            if re.search(r'function\s+participantItems\s*\(', content):
                defining.append(relpath)
        self.assertEqual(
            len(defining), 1,
            f"expected exactly one participantItems function "
            f"definition; found {len(defining)} at {defining}.  Per "
            f"#425, every page that surfaces a participants card must "
            f"use the same component — no per-page variants.",
        )


class ParticipantsCardChatLinkShapeTest(unittest.TestCase):
    """Every chat-link emission for a participants-card click goes
    through the canonical ``proxy:[<slug>:]<name>`` qualifier shape.

    A regression where a page hard-codes its own ``chat.html?conv=…``
    URL with a divergent qualifier shape would let project context
    leak away again.  We catch this by asserting the only producer of
    ``chat.html?conv=proxy:`` URLs in the static bundle lives inside
    ``participantItems``.
    """

    def test_no_other_chat_link_emitter_for_proxy(self) -> None:
        files = _read_all_html_and_js()
        # Find files that contain a hard-coded proxy chat URL.  We allow
        # exactly one — config.html — and only inside the
        # participantItems function.
        offenders: list[str] = []
        for relpath, content in files.items():
            for match in re.finditer(
                r"chat\.html\?conv=['\"]?proxy:", content,
            ):
                # Find the enclosing function name by walking backwards
                # to the nearest ``function <name>`` declaration.
                head = content[:match.start()]
                fn_match = list(
                    re.finditer(r'function\s+([A-Za-z_]\w*)', head),
                )
                fn_name = fn_match[-1].group(1) if fn_match else ''
                if fn_name != 'participantItems':
                    offenders.append(f'{relpath}:{fn_name or "<top-level>"}')
        self.assertEqual(
            offenders, [],
            f"found chat.html?conv=proxy: URLs outside participantItems: "
            f"{offenders}.  Per #425, only the unified participants-card "
            f"component may emit proxy chat URLs; ad-hoc emitters bypass "
            f"the qualifier-shape contract that carries project scope.",
        )


if __name__ == '__main__':
    unittest.main()
