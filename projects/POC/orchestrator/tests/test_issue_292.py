"""Tests for issue #292: Bridge framing must accurately characterize implementation scope.

Acceptance criteria:
1. proposal.md Bridge Server section does not use "thin" without qualification
2. proposal.md Bridge Server section cross-references the known structural gaps
3. bridge-api.md introduction enumerates what is new vs delegated
4. bridge-api.md introduction surfaces all three known structural gaps
"""
import os
import re
import unittest


def _repo_root() -> str:
    here = os.path.dirname(__file__)
    return os.path.normpath(os.path.join(here, '..', '..', '..', '..'))


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


class TestProposalBridgeServerFraming(unittest.TestCase):
    """proposal.md Bridge Server section must characterize scope accurately."""

    def _bridge_section(self) -> str:
        content = _read_doc('docs/proposals/ui-redesign/proposal.md')
        return _extract_bridge_server_section(content)

    def test_thin_is_qualified_or_absent_in_bridge_server_section(self):
        """If 'thin' appears in the Bridge Server section it must be scoped to mean
        'no business logic duplication', not 'small implementation effort'.

        The text 'thin async Python server' sets incorrect expectations for sprint
        sizing (see issue #292). If retained, 'thin' must be explicitly qualified.
        """
        section = self._bridge_section()
        self.assertNotEqual(section, '', "Bridge Server section not found in proposal.md")

        if 'thin' not in section.lower():
            # Removed entirely — criterion satisfied.
            return

        # If 'thin' is present it must be scoped.  Qualifying phrases signal that
        # the author has explained what 'thin' means.
        qualification_phrases = [
            'no business logic',
            'business logic',
            'implementation effort',
            'sprint',
            'new server',
            'new component',
            'not small',
        ]
        found = any(phrase in section.lower() for phrase in qualification_phrases)
        self.assertTrue(
            found,
            "Bridge Server section uses 'thin' without qualifying what it means. "
            "Must clarify that 'thin' refers to no business logic duplication, not "
            "small implementation effort. Current section:\n" + section,
        )

    def test_bridge_server_section_cross_references_structural_gaps(self):
        """Bridge Server section must reference the known structural gaps so that
        implementers reading the proposal see them before diving into the full spec.

        Gaps to surface: StateReader coupling (#280), withdrawal path (#278), and
        the missing workgroup scanner.  These were obscured by the 'thin' framing.
        """
        section = self._bridge_section()
        self.assertNotEqual(section, '', "Bridge Server section not found in proposal.md")

        # Require at least two of the three gaps to be visible in this section.
        gaps_found = sum([
            '#280' in section,
            '#278' in section,
            'workgroup scanner' in section.lower() or 'workgroup' in section.lower(),
        ])
        self.assertGreaterEqual(
            gaps_found, 2,
            "Bridge Server section cross-references fewer than 2 of the 3 known "
            "structural gaps (#278 withdrawal, #280 StateReader coupling, workgroup "
            "scanner).  All three should be visible here so planners don't miss them.",
        )

    def test_bridge_server_section_does_not_claim_no_reimplementation_without_scope(self):
        """'no reimplementation' is misleading if it is the only scope signal.

        The phrase 'no reimplementation' means the bridge doesn't duplicate business
        logic — but the bridge IS new server code (aiohttp server, polling loop,
        state diffing, session lifecycle, workgroup scanner, WebSocket multiplexing,
        conversation routing).  The section must not leave the reader with the
        impression that the bridge requires essentially no new code.
        """
        section = self._bridge_section()
        self.assertNotEqual(section, '', "Bridge Server section not found in proposal.md")

        has_no_reimplementation = 'no reimplementation' in section.lower()
        if not has_no_reimplementation:
            # Phrase removed — criterion satisfied.
            return

        # If the phrase is still present, the section must also describe what IS new.
        new_work_indicators = [
            'new server',
            'new component',
            'polling loop',
            'state diff',
            'workgroup scanner',
            'session lifecycle',
            'new code',
            '300',
            '500',
        ]
        also_describes_new_work = any(p in section.lower() for p in new_work_indicators)
        self.assertTrue(
            also_describes_new_work,
            "Bridge Server section says 'no reimplementation' without also describing "
            "what IS new (aiohttp server, polling loop, state diffing, session lifecycle, "
            "workgroup scanner).  This leaves an incorrect impression of minimal effort.",
        )


class TestBridgeAPIIntroFraming(unittest.TestCase):
    """bridge-api.md introduction must characterize scope accurately."""

    def _intro(self) -> str:
        content = _read_doc('docs/proposals/ui-redesign/references/bridge-api.md')
        return _extract_intro(content)

    def test_intro_describes_what_is_new_not_only_what_is_delegated(self):
        """The bridge-api.md introduction must describe new implementation work, not
        only say the bridge 'exposes existing data' or 'imports existing modules'.

        The current text leads only with delegation ('exposes TeaParty's existing
        data', 'imports existing modules directly') and does not mention: the aiohttp
        server, the 1-second polling loop with state diffing, per-session message bus
        lifecycle management, the workgroup scanner, WebSocket event multiplexing, or
        conversation routing across multiple databases.
        """
        intro = self._intro()

        # These are the NEW components that the introduction must describe.
        new_components = [
            'polling loop',
            'state diff',
            'lifecycle',
            'workgroup scanner',
            'new server',
            'new component',
            'new code',
            'message relay',
            'per-session',
        ]
        found = any(p in intro.lower() for p in new_components)
        self.assertTrue(
            found,
            "bridge-api.md introduction does not describe any new implementation "
            "components.  Must enumerate what the bridge adds (polling loop, state "
            "diffing, session lifecycle management, workgroup scanner) alongside what "
            "it delegates to existing infrastructure.",
        )

    def test_intro_surfaces_all_three_structural_gaps(self):
        """The bridge-api.md introduction must make all three structural gaps visible.

        Currently the intro references #280 (StateReader) but omits #278 (withdrawal)
        and the workgroup scanner.  A reader who only reads the introduction should
        know all three gaps exist before diving into the per-endpoint specification.
        """
        intro = self._intro()

        has_280 = '#280' in intro
        has_278 = '#278' in intro
        has_workgroup_scanner = 'workgroup scanner' in intro.lower()

        missing = []
        if not has_280:
            missing.append('#280 (StateReader coupling)')
        if not has_278:
            missing.append('#278 (withdrawal path)')
        if not has_workgroup_scanner:
            missing.append('workgroup scanner (no existing backing function)')

        self.assertFalse(
            missing,
            "bridge-api.md introduction is missing structural gap references: "
            + ', '.join(missing) + ".  All three must be visible in the introduction "
            "so implementers planning from the intro alone see the full scope.",
        )
