"""Issue #237: Conceptual design documents confidence mechanisms that do not exist.

Verify that human-proxies.md describes the actual confidence model (ACT-R memory
depth, two-pass prediction, accuracy-based autonomy) and does not claim superseded
EMA-based mechanisms as active decision-making features.
"""

import re
import unittest
from pathlib import Path

DOCS_ROOT = Path(__file__).resolve().parents[4] / "docs"
HUMAN_PROXIES = DOCS_ROOT / "conceptual-design" / "human-proxies.md"


class TestHumanProxiesConfidenceModel(unittest.TestCase):
    """Verify human-proxies.md reflects the actual confidence architecture."""

    @classmethod
    def setUpClass(cls):
        cls.text = HUMAN_PROXIES.read_text()

    # ------------------------------------------------------------------
    # Superseded mechanisms must not be described as active
    # ------------------------------------------------------------------

    def test_no_ema_as_decision_mechanism(self):
        """EMA may be mentioned as monitoring, but not as the confidence decision."""
        confidence_section = self._extract_section("The Confidence Model")
        self.assertNotRegex(
            confidence_section,
            r"(?i)exponential moving average.*auto-approves",
            "§Confidence Model should not describe EMA as the approval mechanism",
        )

    def test_no_exploration_rate_as_active(self):
        """Exploration rate (15% escalation floor) does not exist in active path."""
        self.assertNotRegex(
            self.text,
            r"(?i)escalates 15% of the time",
            "Doc should not claim a 15% exploration rate exists",
        )

    def test_no_staleness_guard_as_active(self):
        """7-day staleness guard does not exist in active path."""
        self.assertNotRegex(
            self.text,
            r"(?i)7\+?\s*days?.*forces? escalation",
            "Doc should not claim a 7-day staleness guard exists",
        )

    def test_no_five_mechanisms(self):
        """The doc should not claim 'five mechanisms govern the model'."""
        self.assertNotIn(
            "Five mechanisms",
            self.text,
            "Doc should not reference the superseded five-mechanism model",
        )

    # ------------------------------------------------------------------
    # Actual architecture must be present
    # ------------------------------------------------------------------

    def test_describes_actr_memory_depth(self):
        """§Confidence Model should reference ACT-R memory depth."""
        confidence_section = self._extract_section("The Confidence Model")
        self.assertRegex(
            confidence_section,
            r"(?i)ACT-R|memory depth",
            "§Confidence Model should describe ACT-R memory depth",
        )

    def test_describes_two_pass_prediction(self):
        """§Confidence Model should reference two-pass prediction."""
        confidence_section = self._extract_section("The Confidence Model")
        self.assertRegex(
            confidence_section,
            r"(?i)two.pass|prior.*posterior",
            "§Confidence Model should describe two-pass prediction",
        )

    def test_references_approval_gate_detail(self):
        """Doc should reference approval-gate.md for implementation details."""
        self.assertIn(
            "approval-gate.md",
            self.text,
            "Doc should reference approval-gate.md for implementation details",
        )

    def test_cold_start_references_memory_depth(self):
        """§Cold Start to Warm Start should reference memory depth, not observation counts."""
        cold_start_section = self._extract_section("Cold Start to Warm Start")
        self.assertNotRegex(
            cold_start_section,
            r"< ?5 observations",
            "§Cold Start should not reference superseded '< 5 observations' threshold",
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _extract_section(self, heading):
        """Extract text from a ## heading to the next ## heading."""
        pattern = rf"## {re.escape(heading)}\s*\n(.*?)(?=\n## |\Z)"
        match = re.search(pattern, self.text, re.DOTALL)
        self.assertIsNotNone(match, f"Section '## {heading}' not found")
        return match.group(1)
