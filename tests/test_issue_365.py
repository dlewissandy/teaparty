"""Tests for Issue #365: Config screen — unify "Artifacts" / "Pins" naming inconsistency.

Acceptance criteria:
1. Management config screen Artifacts card (orgArtifactItems) remains labelled "Artifacts"
2. Project config screen artifact store sections card labelled "Sessions" (not "Artifacts")
3. Project config screen pinned-items card labelled "Artifacts" (not "Pins")
4. No remaining "Pins" labels in sectionCard calls in config.html
"""
import unittest
from pathlib import Path

_CONFIG_HTML = Path(__file__).parent.parent / 'bridge' / 'static' / 'config.html'


def _config_html_source() -> str:
    return _CONFIG_HTML.read_text()


# ── AC1: Management screen Artifacts card stays labelled "Artifacts" ──────────

class TestManagementScreenArtifactCardLabel(unittest.TestCase):
    """Management screen must keep the orgArtifactItems card labelled 'Artifacts'."""

    def test_management_orgArtifactItems_card_is_labelled_artifacts(self):
        """sectionCard containing orgArtifactItems must use 'Artifacts'."""
        src = _config_html_source()
        self.assertIn(
            "sectionCard('Artifacts', orgArtifactItems",
            src,
            "Management screen Artifacts card must be labelled 'Artifacts'",
        )

    def test_management_screen_does_not_label_orgArtifactItems_as_sessions(self):
        """Management screen must not label the orgArtifactItems card 'Sessions'."""
        src = _config_html_source()
        self.assertNotIn(
            "sectionCard('Sessions', orgArtifactItems",
            src,
            "Management screen must not use 'Sessions' for the Artifacts card",
        )


# ── AC2: Project screen artifact store card labelled "Sessions" ───────────────

class TestProjectScreenArtifactCardLabel(unittest.TestCase):
    """Project screen must label the artifact store sections card 'Sessions'."""

    def test_project_artifactItems_card_is_labelled_sessions(self):
        """sectionCard containing artifactItems must use 'Sessions', not 'Artifacts'."""
        src = _config_html_source()
        self.assertIn(
            "sectionCard('Sessions', artifactItems",
            src,
            "Project screen artifact store card must be labelled 'Sessions'",
        )

    def test_project_screen_does_not_label_artifactItems_as_artifacts(self):
        """Project screen must not label the artifactItems card 'Artifacts'."""
        src = _config_html_source()
        self.assertNotIn(
            "sectionCard('Artifacts', artifactItems",
            src,
            "Project screen must not use 'Artifacts' for the artifact store sections card; use 'Sessions'",
        )


# ── AC3: Project screen pinned-items card labelled "Artifacts" ────────────────

class TestProjectScreenPinsCardLabel(unittest.TestCase):
    """Project screen must label the pinned-items card 'Artifacts'."""

    def test_project_pinItems_card_is_labelled_artifacts(self):
        """sectionCard containing pinItems must use 'Artifacts'."""
        src = _config_html_source()
        self.assertIn(
            "sectionCard('Artifacts', pinItems",
            src,
            "Project screen pinned-items card must be labelled 'Artifacts'",
        )

    def test_project_screen_does_not_label_pinItems_as_pins(self):
        """Project screen must not label the pinned-items card 'Pins'."""
        src = _config_html_source()
        self.assertNotIn(
            "sectionCard('Pins', pinItems",
            src,
            "Project screen must not use 'Pins' for the pinned-items card; use 'Artifacts'",
        )


# ── AC4: No remaining "Pins" labels in sectionCard calls ─────────────────────

class TestNoPinsLabelsRemain(unittest.TestCase):
    """No sectionCard call in config.html should use 'Pins' as its label."""

    def test_no_section_card_labelled_pins(self):
        """config.html must not contain sectionCard('Pins', ...) anywhere."""
        src = _config_html_source()
        self.assertNotIn(
            "sectionCard('Pins'",
            src,
            "No sectionCard call may use the label 'Pins'",
        )


if __name__ == '__main__':
    unittest.main()
