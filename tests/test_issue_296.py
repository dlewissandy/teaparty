"""Tests for issue #296: proposal overstates TUI size by ~6-8x.

The ui-redesign proposal claimed "65k-line Textual TUI" in two places.
The actual TUI source (Python + TCSS) is approximately 7,000 lines.

Acceptance criteria:
1. The proposal no longer contains "65k" in any form.
2. The proposal references an accurate line count (~7,000 or similar).
3. The actual TUI source files total fewer than 20,000 lines (far below the
   claimed 65k), confirming the claim was never supportable.
"""
import os
import unittest


_PROPOSAL = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    'docs', 'proposals', 'ui-redesign', 'proposal.md',
)

_TUI_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    'projects', 'POC', 'tui',
)


def _proposal_text():
    with open(_PROPOSAL) as f:
        return f.read()


def _tui_line_count():
    total = 0
    for dirpath, _, filenames in os.walk(_TUI_DIR):
        for name in filenames:
            if name.endswith(('.py', '.tcss')):
                with open(os.path.join(dirpath, name)) as f:
                    total += sum(1 for _ in f)
    return total


class TestProposalLineCountCorrected(unittest.TestCase):
    """Proposal must not overstate TUI size."""

    def test_proposal_does_not_claim_65k(self):
        text = _proposal_text()
        self.assertNotIn('65k', text,
                         'proposal must not claim 65k lines — the actual count is ~7,000')

    def test_proposal_references_accurate_count(self):
        text = _proposal_text()
        # Accept any of: ~7k, ~7,000, 7k, 7,000 — all are accurate within margin
        accurate = any(token in text for token in ('~7k', '~7,000', '7k-line', '7,000-line'))
        self.assertTrue(accurate,
                        'proposal must reference accurate TUI size (~7k or ~7,000 lines)')

    def test_actual_tui_source_is_well_below_65k(self):
        count = _tui_line_count()
        self.assertLess(count, 20_000,
                        f'TUI source is {count} lines — far below 65k, confirming the claim was false')


if __name__ == '__main__':
    unittest.main()
