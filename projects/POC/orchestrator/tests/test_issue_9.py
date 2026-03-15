"""Tests for issue #9: Point-not-paste in all agent definitions.

Every agent definition file must include a directive instructing agents
to reference files by path rather than pasting file contents into
messages, escalation files, or inter-agent communications.

Tests verify the directive exists in every role's prompt across all
7 agent definition files listed in the issue.
"""
import json
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent.parent))

AGENTS_DIR = Path(__file__).parent.parent.parent / 'agents'

# The 7 files explicitly listed in the issue
REQUIRED_FILES = [
    'intent-team.json',
    'uber-team.json',
    'art-team.json',
    'writing-team.json',
    'editorial-team.json',
    'research-team.json',
    'coding-team.json',
]


def _load_agents(filename):
    """Load agent definitions from a team JSON file."""
    path = AGENTS_DIR / filename
    with open(path) as f:
        return json.load(f)


def _has_point_not_paste(prompt):
    """Check if a prompt contains point-not-paste guidance.

    The directive must convey: reference files by path, do not paste
    file contents into messages or communications.

    We check for the concept, not exact wording. The prompt must contain
    both a positive instruction (use paths/references) and a negative
    instruction (don't paste/embed/relay contents).
    """
    lower = prompt.lower()

    # Positive: mentions referencing by path or using Read/Glob
    has_positive = any(phrase in lower for phrase in [
        'file path',
        'by path',
        'reference',
        'read/glob',
        'read tool',
        'inspect',
    ])

    # Negative: mentions not pasting/embedding/relaying contents
    has_negative = any(phrase in lower for phrase in [
        'not paste',
        'never paste',
        "don't paste",
        'do not paste',
        'not relay file content',
        "don't relay file content",
        'not embed file content',
        'never embed',
        'not include file content',
    ])

    return has_positive and has_negative


class TestPointNotPasteDirective(unittest.TestCase):
    """Every role in every listed agent file must have point-not-paste guidance."""

    def test_all_required_files_exist(self):
        """All 7 agent definition files from the issue exist."""
        for filename in REQUIRED_FILES:
            path = AGENTS_DIR / filename
            self.assertTrue(path.exists(), f"Missing agent file: {filename}")

    def test_every_role_has_point_not_paste(self):
        """Every role in every required agent file has point-not-paste guidance."""
        missing = []
        for filename in REQUIRED_FILES:
            agents = _load_agents(filename)
            for role_name, role_def in agents.items():
                prompt = role_def.get('prompt', '')
                if not _has_point_not_paste(prompt):
                    missing.append(f"{filename}:{role_name}")

        self.assertEqual(
            missing, [],
            f"These roles are missing point-not-paste guidance:\n"
            + '\n'.join(f"  - {m}" for m in missing),
        )

    def test_intent_team_has_directive(self):
        """intent-team.json roles have point-not-paste guidance."""
        agents = _load_agents('intent-team.json')
        for role_name, role_def in agents.items():
            with self.subTest(role=role_name):
                self.assertTrue(
                    _has_point_not_paste(role_def.get('prompt', '')),
                    f"intent-team.json:{role_name} missing point-not-paste",
                )

    def test_art_team_has_directive(self):
        """art-team.json roles have point-not-paste guidance."""
        agents = _load_agents('art-team.json')
        for role_name, role_def in agents.items():
            with self.subTest(role=role_name):
                self.assertTrue(
                    _has_point_not_paste(role_def.get('prompt', '')),
                    f"art-team.json:{role_name} missing point-not-paste",
                )

    def test_writing_team_has_directive(self):
        """writing-team.json roles have point-not-paste guidance."""
        agents = _load_agents('writing-team.json')
        for role_name, role_def in agents.items():
            with self.subTest(role=role_name):
                self.assertTrue(
                    _has_point_not_paste(role_def.get('prompt', '')),
                    f"writing-team.json:{role_name} missing point-not-paste",
                )

    def test_editorial_team_has_directive(self):
        """editorial-team.json roles have point-not-paste guidance."""
        agents = _load_agents('editorial-team.json')
        for role_name, role_def in agents.items():
            with self.subTest(role=role_name):
                self.assertTrue(
                    _has_point_not_paste(role_def.get('prompt', '')),
                    f"editorial-team.json:{role_name} missing point-not-paste",
                )

    def test_research_team_has_directive(self):
        """research-team.json roles have point-not-paste guidance."""
        agents = _load_agents('research-team.json')
        for role_name, role_def in agents.items():
            with self.subTest(role=role_name):
                self.assertTrue(
                    _has_point_not_paste(role_def.get('prompt', '')),
                    f"research-team.json:{role_name} missing point-not-paste",
                )

    def test_coding_team_has_directive(self):
        """coding-team.json roles have point-not-paste guidance."""
        agents = _load_agents('coding-team.json')
        for role_name, role_def in agents.items():
            with self.subTest(role=role_name):
                self.assertTrue(
                    _has_point_not_paste(role_def.get('prompt', '')),
                    f"coding-team.json:{role_name} missing point-not-paste",
                )

    def test_uber_team_has_directive(self):
        """uber-team.json roles have point-not-paste guidance."""
        agents = _load_agents('uber-team.json')
        for role_name, role_def in agents.items():
            with self.subTest(role=role_name):
                self.assertTrue(
                    _has_point_not_paste(role_def.get('prompt', '')),
                    f"uber-team.json:{role_name} missing point-not-paste",
                )


if __name__ == '__main__':
    unittest.main()
