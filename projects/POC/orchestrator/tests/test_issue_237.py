"""Issue #237: Implement exploration rate and staleness guard in _calibrate_confidence.

The conceptual design (human-proxies.md) specifies exploration rate and staleness
guard as safety backstops against overconfident auto-approval.  These were present
in the legacy should_escalate() pipeline but were never wired into the ACT-R
confidence path.  This issue implements them in _calibrate_confidence().
"""

import re
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

DOCS_ROOT = Path(__file__).resolve().parents[4] / "docs"
HUMAN_PROXIES = DOCS_ROOT / "conceptual-design" / "human-proxies.md"


def _make_accuracy(*, posterior_correct=9, posterior_total=10,
                   last_updated=None):
    """Build an accuracy dict matching get_accuracy() return shape."""
    if last_updated is None:
        last_updated = date.today().isoformat()
    return {
        'prior_correct': 0, 'prior_total': 0,
        'posterior_correct': posterior_correct,
        'posterior_total': posterior_total,
        'last_updated': last_updated,
    }


class TestStalenessGuard(unittest.TestCase):
    """Staleness guard caps confidence when feedback is too old."""

    def _calibrate(self, accuracy, **kw):
        from projects.POC.orchestrator.proxy_agent import _calibrate_confidence
        defaults = dict(
            agent_confidence=0.95, state='PLAN_ASSERT',
            project_slug='POC', proxy_model_path='/tmp/fake',
            team='alpha', _random=0.99,  # defeat exploration
        )
        defaults.update(kw)
        with patch(
            'projects.POC.orchestrator.proxy_agent._get_memory_depth',
            return_value=5,
        ):
            return _calibrate_confidence(accuracy=accuracy, **defaults)

    def test_fresh_feedback_passes_through(self):
        """Feedback from today does not trigger staleness."""
        acc = _make_accuracy(last_updated=date.today().isoformat())
        conf = self._calibrate(acc)
        self.assertEqual(conf, 0.95)

    def test_stale_feedback_caps_confidence(self):
        """Feedback older than STALENESS_DAYS caps confidence at 0.5."""
        stale = (date.today() - timedelta(days=8)).isoformat()
        acc = _make_accuracy(last_updated=stale)
        conf = self._calibrate(acc)
        self.assertLessEqual(conf, 0.5)

    def test_exactly_at_boundary_passes(self):
        """Feedback exactly STALENESS_DAYS old does not trigger."""
        boundary = (date.today() - timedelta(days=7)).isoformat()
        acc = _make_accuracy(last_updated=boundary)
        conf = self._calibrate(acc)
        self.assertEqual(conf, 0.95)

    def test_no_accuracy_data_skips_staleness(self):
        """No accuracy data means no staleness check — passthrough."""
        conf = self._calibrate(None)
        self.assertEqual(conf, 0.95)

    def test_missing_last_updated_skips_staleness(self):
        """Accuracy row without last_updated skips staleness check."""
        acc = _make_accuracy()
        acc['last_updated'] = None
        conf = self._calibrate(acc)
        self.assertEqual(conf, 0.95)


class TestExplorationRate(unittest.TestCase):
    """Exploration rate randomly forces escalation."""

    def _calibrate(self, random_roll, **kw):
        from projects.POC.orchestrator.proxy_agent import _calibrate_confidence
        defaults = dict(
            agent_confidence=0.95, state='PLAN_ASSERT',
            project_slug='POC', proxy_model_path='/tmp/fake',
            team='alpha', accuracy=_make_accuracy(),
        )
        defaults.update(kw)
        with patch(
            'projects.POC.orchestrator.proxy_agent._get_memory_depth',
            return_value=5,
        ):
            return _calibrate_confidence(_random=random_roll, **defaults)

    def test_low_roll_caps_confidence(self):
        """Random roll below EXPLORATION_RATE (0.15) caps confidence."""
        conf = self._calibrate(0.05)
        self.assertLessEqual(conf, 0.5)

    def test_high_roll_passes_through(self):
        """Random roll above EXPLORATION_RATE passes through."""
        conf = self._calibrate(0.99)
        self.assertEqual(conf, 0.95)

    def test_roll_at_boundary_passes(self):
        """Roll exactly at EXPLORATION_RATE (0.15) passes through."""
        conf = self._calibrate(0.15)
        self.assertEqual(conf, 0.95)


class TestGateOrdering(unittest.TestCase):
    """Verify gate priority: cold-start > genuine tension > staleness >
    exploration > accuracy > passthrough."""

    def _calibrate(self, *, depth=5, genuine_tension=False,
                   accuracy=None, random_roll=0.99):
        from projects.POC.orchestrator.proxy_agent import _calibrate_confidence
        with patch(
            'projects.POC.orchestrator.proxy_agent._get_memory_depth',
            return_value=depth,
        ):
            return _calibrate_confidence(
                agent_confidence=0.95, state='PLAN_ASSERT',
                project_slug='POC', proxy_model_path='/tmp/fake',
                team='alpha', accuracy=accuracy,
                genuine_tension=genuine_tension, _random=random_roll,
            )

    def test_cold_start_beats_everything(self):
        """Cold start caps even with fresh accuracy and no tension."""
        conf = self._calibrate(depth=1, accuracy=_make_accuracy())
        self.assertLessEqual(conf, 0.5)

    def test_genuine_tension_beats_staleness(self):
        """Genuine tension caps even with fresh feedback."""
        conf = self._calibrate(
            genuine_tension=True, accuracy=_make_accuracy(),
        )
        self.assertLessEqual(conf, 0.5)

    def test_staleness_beats_exploration(self):
        """Stale feedback caps even when exploration roll is high."""
        stale = (date.today() - timedelta(days=10)).isoformat()
        conf = self._calibrate(
            accuracy=_make_accuracy(last_updated=stale), random_roll=0.99,
        )
        self.assertLessEqual(conf, 0.5)

    def test_exploration_beats_accuracy(self):
        """Exploration can cap even with high accuracy."""
        conf = self._calibrate(
            accuracy=_make_accuracy(posterior_correct=10, posterior_total=10),
            random_roll=0.01,
        )
        self.assertLessEqual(conf, 0.5)


class TestDocDesignAlignment(unittest.TestCase):
    """Verify human-proxies.md describes the implemented confidence model."""

    @classmethod
    def setUpClass(cls):
        cls.text = HUMAN_PROXIES.read_text()

    def test_no_ema_as_decision_mechanism(self):
        """EMA may be mentioned as monitoring, but not as the confidence decision."""
        section = self._extract_section("The Confidence Model")
        self.assertNotRegex(
            section,
            r"(?i)exponential moving average.*auto-approves",
            "§Confidence Model should not describe EMA as the approval mechanism",
        )

    def test_describes_actr_memory_depth(self):
        section = self._extract_section("The Confidence Model")
        self.assertRegex(section, r"(?i)ACT-R|memory depth")

    def test_describes_two_pass_prediction(self):
        section = self._extract_section("The Confidence Model")
        self.assertRegex(section, r"(?i)two.pass|prior.*posterior")

    def test_describes_genuine_tension_guard(self):
        section = self._extract_section("The Confidence Model")
        self.assertRegex(section, r"(?i)genuine tension")

    def test_describes_exploration_rate(self):
        section = self._extract_section("The Confidence Model")
        self.assertRegex(section, r"(?i)exploration rate")

    def test_describes_staleness_guard(self):
        section = self._extract_section("The Confidence Model")
        self.assertRegex(section, r"(?i)staleness guard")

    def test_describes_accuracy_based_autonomy(self):
        section = self._extract_section("The Confidence Model")
        self.assertRegex(section, r"(?i)accuracy.based autonomy")

    def test_references_approval_gate_detail(self):
        self.assertIn("approval-gate.md", self.text)

    def _extract_section(self, heading):
        pattern = rf"## {re.escape(heading)}\s*\n(.*?)(?=\n## |\Z)"
        match = re.search(pattern, self.text, re.DOTALL)
        self.assertIsNotNone(match, f"Section '## {heading}' not found")
        return match.group(1)
