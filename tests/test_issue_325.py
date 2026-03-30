"""Tests for issue #325: Dashboard cards masonry layout, natural card heights.

Acceptance criteria:
1. .sections container uses CSS columns, not display:grid (config page)
2. .chart-grid container uses CSS columns, not display:grid (stats page)
3. .project-grid container uses CSS columns, not display:grid (home page)
4. Card elements (.section, .chart-card, .project-card) have break-inside:avoid
   to prevent column splits
5. Single-column layout is preserved at mobile widths (max-width: 800px)
"""
import os
import re
import unittest

STATIC_DIR = os.path.join(os.path.dirname(__file__), '..', 'bridge', 'static')


def _read(filename):
    with open(os.path.join(STATIC_DIR, filename)) as f:
        return f.read()


def _normalize(css):
    """Strip whitespace for easier pattern matching."""
    return re.sub(r'\s+', ' ', css)


class TestSectionsMasonryLayout(unittest.TestCase):
    """styles.css: .sections must use CSS columns, not grid."""

    def setUp(self):
        self.css = _read('styles.css')

    def _sections_rule_block(self):
        """Extract the .sections rule block text."""
        m = re.search(r'\.sections\s*\{([^}]*)\}', self.css)
        self.assertIsNotNone(m, ".sections rule not found in styles.css")
        return m.group(1)

    def test_sections_does_not_use_display_grid(self):
        """Cards must not be forced to equal row heights via CSS grid."""
        block = self._sections_rule_block()
        self.assertNotIn('display: grid', _normalize(block),
                         ".sections must not use display:grid (causes equal row heights)")
        self.assertNotIn('display:grid', _normalize(block),
                         ".sections must not use display:grid (causes equal row heights)")

    def test_sections_uses_columns_property(self):
        """Cards must pack in masonry columns, not grid rows."""
        block = self._sections_rule_block()
        # Must match standalone 'columns:' not 'grid-template-columns:'
        self.assertRegex(
            _normalize(block),
            r'(?<![a-z-])columns\s*:',
            ".sections must use the CSS columns property for masonry layout"
        )

    def test_sections_mobile_is_single_column(self):
        """Mobile breakpoint (max-width ≤ 800px or min-width ≥ 800px) must keep 1 column."""
        # Accept either max-width:800px or absence of multi-column in mobile scope.
        # The key requirement: at narrow widths cards must not force 2 columns.
        # We look for a media query that sets .sections to columns:1 or column-count:1.
        media_blocks = re.findall(
            r'@media[^{]*\{(.*?)\}(?=\s*(?:@|\.|#|[a-z]))',
            self.css, re.DOTALL
        )
        # Alternatively: there should be a min-width media query that enables 2 columns,
        # implying the default (mobile-first) is 1.
        has_min_width_2col = bool(re.search(
            r'@media[^{]*min-width[^{]*\{[^}]*\.sections[^}]*columns\s*:\s*2',
            self.css, re.DOTALL
        ))
        # Or: max-width query sets columns to 1
        has_max_width_1col = bool(re.search(
            r'@media[^{]*max-width[^{]*\{[^}]*\.sections[^}]*columns\s*:\s*1',
            self.css, re.DOTALL
        ))
        self.assertTrue(
            has_min_width_2col or has_max_width_1col,
            ".sections must be single-column on mobile: either default to 1 column with "
            "a min-width media query enabling 2, or a max-width query setting 1"
        )


class TestSectionCardBreakInside(unittest.TestCase):
    """.section cards must not split across column boundaries."""

    def setUp(self):
        self.css = _read('styles.css')

    def test_section_has_break_inside_avoid(self):
        """Cards clipped by a column break would show partial content."""
        m = re.search(r'\.section\s*\{([^}]*)\}', self.css)
        self.assertIsNotNone(m, ".section rule not found in styles.css")
        block = m.group(1)
        self.assertIn('break-inside', block,
                      ".section must have break-inside:avoid to prevent column splits")
        self.assertIn('avoid', block,
                      ".section must have break-inside:avoid")


class TestChartGridMasonryLayout(unittest.TestCase):
    """styles.css: .chart-grid must use CSS columns, not grid."""

    def setUp(self):
        self.css = _read('styles.css')

    def _chart_grid_rule_block(self):
        m = re.search(r'\.chart-grid\s*\{([^}]*)\}', self.css)
        self.assertIsNotNone(m, ".chart-grid rule not found in styles.css")
        return m.group(1)

    def test_chart_grid_does_not_use_display_grid(self):
        """Chart cards must not be forced to equal row heights."""
        block = self._chart_grid_rule_block()
        normalized = _normalize(block)
        self.assertNotIn('display: grid', normalized,
                         ".chart-grid must not use display:grid")
        self.assertNotIn('display:grid', normalized,
                         ".chart-grid must not use display:grid")

    def test_chart_grid_uses_columns_property(self):
        """Chart cards must use masonry column layout."""
        block = self._chart_grid_rule_block()
        self.assertRegex(
            _normalize(block),
            r'(?<![a-z-])columns\s*:',
            ".chart-grid must use the CSS columns property"
        )


class TestChartCardBreakInside(unittest.TestCase):
    """.chart-card must not split across columns."""

    def setUp(self):
        self.css = _read('styles.css')

    def test_chart_card_has_break_inside_avoid(self):
        """Chart cards clipped mid-content would confuse readers."""
        m = re.search(r'\.chart-card\s*\{([^}]*)\}', self.css)
        self.assertIsNotNone(m, ".chart-card rule not found in styles.css")
        block = m.group(1)
        self.assertIn('break-inside', block,
                      ".chart-card must have break-inside:avoid")
        self.assertIn('avoid', block,
                      ".chart-card must have break-inside:avoid")


class TestProjectGridMasonryLayout(unittest.TestCase):
    """index.html: .project-grid must use CSS columns, not grid."""

    def setUp(self):
        self.html = _read('index.html')

    def _project_grid_rule(self):
        """Extract inline .project-grid style rule from index.html."""
        m = re.search(r'\.project-grid\s*\{([^}]*)\}', self.html)
        self.assertIsNotNone(m, ".project-grid rule not found in index.html")
        return m.group(1)

    def test_project_grid_does_not_use_display_grid(self):
        """Project cards must not be forced to equal row heights."""
        block = self._project_grid_rule()
        normalized = _normalize(block)
        self.assertNotIn('display: grid', normalized,
                         ".project-grid must not use display:grid")
        self.assertNotIn('display:grid', normalized,
                         ".project-grid must not use display:grid")

    def test_project_grid_uses_columns_property(self):
        """Project cards must use masonry column layout."""
        block = self._project_grid_rule()
        self.assertRegex(
            _normalize(block),
            r'(?<![a-z-])columns\s*:',
            ".project-grid must use the CSS columns property"
        )


class TestProjectCardBreakInside(unittest.TestCase):
    """.project-card must not split across columns."""

    def setUp(self):
        self.html = _read('index.html')

    def test_project_card_has_break_inside_avoid(self):
        """Project cards clipped by a column break lose their bottom sections."""
        m = re.search(r'\.project-card\s*\{([^}]*)\}', self.html)
        self.assertIsNotNone(m, ".project-card rule not found in index.html")
        block = m.group(1)
        self.assertIn('break-inside', block,
                      ".project-card must have break-inside:avoid")
        self.assertIn('avoid', block,
                      ".project-card must have break-inside:avoid")
