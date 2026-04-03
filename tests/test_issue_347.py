"""Tests for Issue #347: Agent-dispatch proposal falsely claimed liaison agents not implemented.

Acceptance criteria:
1. proposal.md Supersedes section must not claim liaison agents are "not implemented"
2. proposal.md Supersedes section must reference orchestrator/office_manager.py when discussing #332
3. references/routing.md Disposition of Liaison Agents must name the actual implementation
   function: _build_roster_agents_json (supersedes old liaison builders)
4. That function must actually exist in orchestrator/office_manager.py and be called from invoke()
"""
import re
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).parent.parent
_PROPOSAL_PATH = _REPO_ROOT / 'docs' / 'proposals' / 'agent-dispatch' / 'proposal.md'
_ROUTING_PATH = _REPO_ROOT / 'docs' / 'proposals' / 'agent-dispatch' / 'references' / 'routing.md'
_OFFICE_MANAGER_PATH = _REPO_ROOT / 'orchestrator' / 'office_manager.py'


def _read(path: Path) -> str:
    return path.read_text()


def _supersedes_section(text: str) -> str:
    """Extract the Supersedes section from a markdown document."""
    match = re.search(r'## Supersedes\b(.+?)(?=\n## |\Z)', text, re.DOTALL)
    assert match, "Could not find '## Supersedes' section in document"
    return match.group(1)


def _disposition_section(text: str) -> str:
    """Extract the Disposition of Liaison Agents section from routing.md."""
    match = re.search(
        r'## Disposition of Liaison Agents\b(.+?)(?=\n## |\Z)', text, re.DOTALL
    )
    assert match, "Could not find '## Disposition of Liaison Agents' section in routing.md"
    return match.group(1)


# ── AC1: proposal.md must not claim liaison agents are "not implemented" ─────

class TestProposalDoesNotFalselyDenyLiaisons(unittest.TestCase):
    """proposal.md Supersedes section must not claim liaison agents are not implemented."""

    def setUp(self):
        self.supersedes = _supersedes_section(_read(_PROPOSAL_PATH))

    def test_supersedes_does_not_say_liaison_agents_not_implemented(self):
        """Supersedes section must not contain the false claim 'not implemented'."""
        # The original false claim was: "liaison agents are not implemented"
        self.assertNotIn(
            'not implemented',
            self.supersedes,
            "Supersedes section must not claim liaison agents are 'not implemented'",
        )

    def test_supersedes_issue_332_entry_does_not_deny_liaison_existence(self):
        """The #332 entry must not say liaison agents do not exist."""
        # The false claim pattern: issue #332 entry asserts non-existence
        issue_332_match = re.search(r'#332[^\n]*', self.supersedes)
        self.assertIsNotNone(issue_332_match, "Supersedes section must have a #332 entry")
        entry = issue_332_match.group(0)
        self.assertNotIn(
            'not implemented',
            entry,
            "#332 entry in Supersedes must not assert liaison agents are not implemented",
        )


# ── AC2: proposal.md Supersedes must acknowledge the actual implementation ───

class TestProposalAcknowledgesLiaisonImplementation(unittest.TestCase):
    """proposal.md Supersedes section must reference the actual liaison implementation."""

    def setUp(self):
        self.supersedes = _supersedes_section(_read(_PROPOSAL_PATH))

    def test_supersedes_references_office_manager(self):
        """Supersedes section must reference orchestrator/office_manager.py for #332."""
        self.assertIn(
            'office_manager.py',
            self.supersedes,
            "Supersedes section must reference orchestrator/office_manager.py "
            "to acknowledge the existing liaison implementation",
        )

    def test_supersedes_uses_supersedes_framing_not_nonexistence_framing(self):
        """The #332 disposition must say the implementation is superseded, not absent."""
        self.assertIn(
            'superseded',
            self.supersedes,
            "The #332 entry must use 'superseded' framing (acknowledging the implementation "
            "exists and is being replaced), not a non-existence claim",
        )


# ── AC3: routing.md must name the actual liaison functions ───────────────────

class TestRoutingMdDispositionNamesLiaisonFunctions(unittest.TestCase):
    """routing.md Disposition of Liaison Agents must name the actual implementation functions."""

    def setUp(self):
        self.disposition = _disposition_section(_read(_ROUTING_PATH))

    def test_disposition_names_build_roster_agents_json(self):
        """Disposition must name _build_roster_agents_json()."""
        self.assertIn(
            '_build_roster_agents_json',
            self.disposition,
            "Disposition of Liaison Agents must name _build_roster_agents_json() "
            "to accurately describe the current implementation",
        )

    def test_disposition_names_old_liaison_defs_as_superseded(self):
        """Disposition must reference old liaison defs as superseded."""
        self.assertIn(
            '_make_project_liaison_def',
            self.disposition,
            "Disposition must reference _make_project_liaison_def() as superseded",
        )

    def test_disposition_references_office_manager_module(self):
        """Disposition must reference orchestrator/office_manager.py."""
        self.assertIn(
            'office_manager.py',
            self.disposition,
            "Disposition of Liaison Agents must reference orchestrator/office_manager.py",
        )


# ── AC4: The named functions must actually exist in office_manager.py ────────

class TestLiaisonFunctionsExistInCode(unittest.TestCase):
    """The functions named in routing.md must actually exist in orchestrator/office_manager.py."""

    def setUp(self):
        self.source = _read(_OFFICE_MANAGER_PATH)

    def test_build_roster_agents_json_exists(self):
        """_build_roster_agents_json must be defined in orchestrator/office_manager.py."""
        self.assertIn(
            'def _build_roster_agents_json(',
            self.source,
            "_build_roster_agents_json must be defined in orchestrator/office_manager.py",
        )

    def test_build_roster_agents_json_called_from_invoke(self):
        """_build_roster_agents_json must be called in OfficeManagerSession.invoke()."""
        invoke_match = re.search(
            r'async def invoke\(.*?\)\s*->[^:]+:(.*?)(?=\n    async def |\n    def |\Z)',
            self.source,
            re.DOTALL,
        )
        self.assertIsNotNone(invoke_match, "OfficeManagerSession must have an invoke() method")
        invoke_body = invoke_match.group(1)
        self.assertIn(
            '_build_roster_agents_json',
            invoke_body,
            "_build_roster_agents_json must be called from invoke() — "
            "roster agents must actually run, not just be defined",
        )


if __name__ == '__main__':
    unittest.main()
