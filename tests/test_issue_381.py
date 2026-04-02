"""Tests for issue #381: Section cards should resize to fit their contents.

Acceptance criteria:
1. Section cards expand vertically to fit all content (no max-height cap)
2. No internal scrollbar appears inside a section card (no overflow-y: auto on section-scroll)
3. Multi-column layout continues to reflow correctly at all viewport widths
4. Project cards and chart cards are unaffected
"""
import re
import sys
import unittest
from pathlib import Path

STYLES_CSS = Path(__file__).parent.parent / 'bridge' / 'static' / 'styles.css'


def _extract_rule(css: str, selector: str) -> str | None:
    """Return the declaration block for an exact selector, skipping nested rules."""
    pattern = re.escape(selector) + r'\s*\{([^}]*)\}'
    m = re.search(pattern, css)
    return m.group(1) if m else None


class TestSectionCardLayout(unittest.TestCase):

    def setUp(self):
        self.css = STYLES_CSS.read_text()

    def _section_rule(self) -> str:
        decl = _extract_rule(self.css, '.section')
        self.assertIsNotNone(decl, ".section rule not found in styles.css")
        return decl

    def _section_scroll_rule(self) -> str:
        decl = _extract_rule(self.css, '.section-scroll')
        self.assertIsNotNone(decl, ".section-scroll rule not found in styles.css")
        return decl

    # Criterion 1: section cards expand to fit content — no max-height cap
    def test_section_has_no_max_height_constraint(self):
        decl = self._section_rule()
        self.assertNotIn(
            'max-height',
            decl,
            ".section must not have a max-height constraint — cards should grow to fit content",
        )

    # Criterion 2: no internal scrollbar inside section cards
    def test_section_scroll_has_no_overflow_y_auto(self):
        decl = self._section_scroll_rule()
        self.assertNotIn(
            'overflow-y',
            decl,
            ".section-scroll must not set overflow-y — no scrollbar should appear inside a card",
        )

    # Criterion 3: multi-column reflow rule is preserved
    def test_sections_multi_column_layout_preserved(self):
        self.assertIn('columns: 1', self.css, ".sections columns: 1 rule must be present")
        self.assertIn('columns: 2', self.css, ".sections columns: 2 media-query rule must be present")

    # Criterion 4: project and chart cards are not affected
    def test_project_and_chart_card_rules_unchanged(self):
        for selector in ('.project-card', '.chart-card'):
            decl = _extract_rule(self.css, selector)
            if decl is not None:
                self.assertNotIn(
                    'max-height: 280px',
                    decl,
                    f"{selector} should not have acquired a max-height: 280px constraint",
                )


if __name__ == '__main__':
    unittest.main()
