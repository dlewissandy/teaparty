"""Tests for issue #292: Bridge framing must accurately characterize implementation scope.

The issue names seven specific new components that the bridge adds. Tests verify
that each one is present by name in the relevant characterization sections — not
just that some qualifying language exists somewhere nearby.

Acceptance criteria:
1. proposal.md Bridge Server section names all seven new components individually
2. proposal.md Bridge Server section names all three structural gaps by issue number
3. proposal.md Bridge Server section gives a concrete size estimate
4. proposal.md does not use "thin" in any unqualified context
5. bridge-api.md introduction new-code list names all six components
6. bridge-api.md introduction names all three structural gaps
"""
import os
import re
import unittest


def _repo_root() -> str:
    here = os.path.dirname(__file__)
    return os.path.normpath(os.path.join(here, '..'))


def _read_doc(rel_path: str) -> str:
    path = os.path.join(_repo_root(), rel_path)
    with open(path) as f:
        return f.read()


def _extract_bridge_server_section(text: str) -> str:
    """Extract text from '## Bridge Server' until the next ## heading."""
    pattern = r'^## Bridge Server$(.*?)(?=^## |\Z)'
    match = re.search(pattern, text, re.MULTILINE | re.DOTALL)
    if match:
        return match.group(1)
    return ''


def _extract_intro(text: str) -> str:
    """Extract bridge-api.md intro: text before the first horizontal rule."""
    parts = text.split('\n---\n', 1)
    return parts[0] if parts else text


# The seven new components enumerated in issue #292.
# Each tuple: (canonical phrase to search, human-readable label for error messages).
PROPOSAL_NEW_COMPONENTS = [
    ('static file serving',                     'static file serving'),
    ('seven REST',                               'seven REST endpoint groups'),
    ('WebSocket with five event types',          'WebSocket with five event types'),
    ('polling loop',                             'polling loop'),
    ('state diff',                               'state diffing'),
    ('per-session',                              'per-session message bus lifecycle'),
    ('workgroup scanner',                        'workgroup scanner'),
    ('conversation routing',                     'conversation routing across multiple databases'),
]

# Size floor mentioned in the issue ("300–500 line bridge").
SIZE_INDICATORS = ['300', '500']

# The three structural gaps the issue says the framing obscures.
STRUCTURAL_GAPS = [
    ('#280', 'StateReader coupling (#280)'),
    ('#278', 'withdrawal path (#278)'),
    ('workgroup scanner', 'workgroup scanner (missing backing function)'),
]

# The six components in the bridge-api.md "new code" bulleted list.
BRIDGE_API_NEW_COMPONENTS = [
    ('static file serving',              'static file serving'),
    ('polling loop',                     'polling loop with state diffing'),
    ('state diff',                       'state diffing'),
    ('per-session',                      'per-session connection lifecycle'),
    ('five push-event',                  'WebSocket with five push-event types'),
    ('conversation routing',             'conversation routing across multiple databases'),
    ('workgroup scanner',                'workgroup scanner'),
]


class TestProposalBridgeServerFraming(unittest.TestCase):
    """proposal.md Bridge Server section must enumerate all new components by name."""

    def _section(self) -> str:
        content = _read_doc('docs/proposals/ui-redesign/proposal.md')
        s = _extract_bridge_server_section(content)
        self.assertNotEqual(s, '', "Bridge Server section not found in proposal.md")
        return s

    def test_all_new_components_named_individually(self):
        """Every new component enumerated in issue #292 must appear by name in the
        Bridge Server section.

        The issue lists: static file serving, seven REST endpoint groups, WebSocket
        with five event types, polling loop with state diffing, per-session message
        bus lifecycle management, conversation routing across multiple databases, and
        workgroup scanner.  A characterization that omits any of these leaves the
        implementer without a complete scope picture.
        """
        section = self._section().lower()
        missing = [
            label for phrase, label in PROPOSAL_NEW_COMPONENTS
            if phrase.lower() not in section
        ]
        self.assertFalse(
            missing,
            "Bridge Server section is missing these new components:\n  "
            + '\n  '.join(missing),
        )

    def test_size_estimate_present(self):
        """Bridge Server section must give a concrete line-count estimate so planners
        have a floor for sprint sizing.  The issue cites 300–500 lines.
        """
        section = self._section()
        found = any(indicator in section for indicator in SIZE_INDICATORS)
        self.assertTrue(
            found,
            "Bridge Server section has no size estimate. "
            "Must include the 300–500 line floor from the issue so planners can size.",
        )

    def test_all_three_structural_gaps_named(self):
        """Bridge Server section must name all three structural gaps by issue number
        or exact description so planners see them without reading further.
        """
        section = self._section()
        missing = [
            label for phrase, label in STRUCTURAL_GAPS
            if phrase not in section and phrase.lower() not in section.lower()
        ]
        self.assertFalse(
            missing,
            "Bridge Server section is missing these structural gap references:\n  "
            + '\n  '.join(missing),
        )

    def test_thin_absent_from_entire_proposal(self):
        """'thin' must not appear anywhere in proposal.md as an unqualified scope
        signal for the bridge.

        Any occurrence of 'thin' describing the bridge sets incorrect expectations.
        The word may still appear in unrelated contexts (e.g. 'thin client') but
        must not be used to characterize the bridge's implementation size.
        """
        content = _read_doc('docs/proposals/ui-redesign/proposal.md')
        # Find every line containing 'thin' (case-insensitive).
        lines_with_thin = [
            (i + 1, line.rstrip())
            for i, line in enumerate(content.splitlines())
            if 'thin' in line.lower()
        ]
        bridge_thin_lines = [
            f"  line {lineno}: {line}"
            for lineno, line in lines_with_thin
            # 'within' contains 'thin' as a substring — skip it.
            if re.search(r'\bthin\b', line, re.IGNORECASE)
        ]
        self.assertFalse(
            bridge_thin_lines,
            "proposal.md still contains 'thin' as a standalone word:\n"
            + '\n'.join(bridge_thin_lines)
            + "\nRemove or replace — 'thin' sets incorrect implementation-effort expectations.",
        )


class TestBridgeAPIIntroFraming(unittest.TestCase):
    """bridge-api.md introduction must enumerate all new components and all three gaps."""

    def _intro(self) -> str:
        content = _read_doc('docs/proposals/ui-redesign/references/bridge-api.md')
        return _extract_intro(content)

    def test_all_new_components_named_in_intro(self):
        """The bridge-api.md introduction new-code list must name every component
        that the bridge implements as new code.

        The list (from the spec): aiohttp app with static file serving, polling loop
        with state diffing, per-session connection lifecycle, WebSocket with five
        push-event types, conversation routing across multiple databases, and workgroup
        scanner.  A future edit that silently drops a component from the list would
        otherwise pass the tests.
        """
        intro = self._intro().lower()
        missing = [
            label for phrase, label in BRIDGE_API_NEW_COMPONENTS
            if phrase.lower() not in intro
        ]
        self.assertFalse(
            missing,
            "bridge-api.md introduction is missing these new-code components:\n  "
            + '\n  '.join(missing),
        )

    def test_all_three_structural_gaps_in_intro(self):
        """bridge-api.md introduction must name all three structural gaps so a reader
        who stops after the intro has a complete picture of what is not yet built.
        """
        intro = self._intro()
        missing = [
            label for phrase, label in STRUCTURAL_GAPS
            if phrase not in intro and phrase.lower() not in intro.lower()
        ]
        self.assertFalse(
            missing,
            "bridge-api.md introduction is missing these structural gap references:\n  "
            + '\n  '.join(missing),
        )

    def test_delegated_infrastructure_listed(self):
        """bridge-api.md introduction must also list what the bridge delegates to
        existing infrastructure, so the new-vs-delegated distinction is explicit.

        Required delegated items: SqliteMessageBus, StateReader, config_reader.
        """
        intro = self._intro()
        required = ['SqliteMessageBus', 'StateReader', 'config_reader']
        missing = [name for name in required if name not in intro]
        self.assertFalse(
            missing,
            "bridge-api.md introduction is missing these delegated-infrastructure "
            "entries:\n  " + '\n  '.join(missing),
        )
