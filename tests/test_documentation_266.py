"""Specification tests for issue #266: documentation matches Milestone 3 as-built.

These tests verify that documentation describes the system as implemented
after Milestone 3, not the pre-M3 architecture. Each test encodes a
specific acceptance criterion from the issue.
"""
import os
import re
import unittest

DOCS = os.path.join(os.path.dirname(__file__), "..", "docs")


def _read(relpath: str) -> str:
    """Read a doc file relative to docs/."""
    path = os.path.join(DOCS, relpath)
    if not os.path.exists(path):
        return ""
    with open(path) as f:
        return f.read()


def _exists(relpath: str) -> bool:
    return os.path.exists(os.path.join(DOCS, relpath))


class TestNoStaleReferences(unittest.TestCase):
    """AC-23: No stale references remain in any doc."""

    STALE_PATTERNS = [
        (r"projects/POC/", "references deleted POC directory"),
        (r"orchestrator/engine\.py", "references old orchestrator path"),
        (r"orchestrator/session\.py", "references old orchestrator path"),
        (r"orchestrator/actors\.py", "references old orchestrator path"),
        (r"orchestrator/claude_runner\.py", "references old orchestrator path"),
        (r"orchestrator/learnings\.py", "references old orchestrator path"),
        (r"scripts/cfa_state\.py", "references old scripts path"),
        (r"scripts/approval_gate\.py", "references old scripts path"),
    ]

    DOC_FILES = [
        "overview.md",
        "conceptual-design/agent-dispatch.md",
        "conceptual-design/hierarchical-teams.md",
        "conceptual-design/human-proxies.md",
        "conceptual-design/cfa-state-machine.md",
        "detailed-design/index.md",
        "detailed-design/agent-runtime.md",
        "detailed-design/cfa-state-machine.md",
        "detailed-design/approval-gate.md",
        "detailed-design/heartbeat.md",
        "detailed-design/learning-system.md",
        "reference/folder-structure.md",
    ]

    def test_no_stale_path_references(self):
        """No doc references pre-M3 file paths."""
        violations = []
        for doc in self.DOC_FILES:
            content = _read(doc)
            if not content:
                continue
            for pattern, reason in self.STALE_PATTERNS:
                if re.search(pattern, content):
                    violations.append(f"{doc}: {reason} ({pattern})")
        self.assertEqual(violations, [], "\n".join(violations))

    def test_no_liaison_references_in_dispatch(self):
        """agent-dispatch.md does not describe liaison agents."""
        content = _read("conceptual-design/agent-dispatch.md")
        self.assertNotIn("relay_to_subteam", content)
        # "liaison" may appear in historical context but not as current model
        if "liaison" in content.lower():
            # Allow only if qualified as "replaced" or "former"
            lines = [
                ln for ln in content.split("\n")
                if "liaison" in ln.lower()
                and "replaced" not in ln.lower()
                and "former" not in ln.lower()
                and "no longer" not in ln.lower()
            ]
            self.assertEqual(
                lines, [],
                "agent-dispatch.md references liaisons as current: "
                + "; ".join(lines),
            )

    def test_no_persistent_team_sessions(self):
        """agent-dispatch.md describes one-shot launch, not persistent sessions."""
        content = _read("conceptual-design/agent-dispatch.md")
        self.assertNotIn(
            "long-lived",
            content.lower(),
            "Should not describe long-lived processes",
        )
        self.assertNotIn(
            "bidirectional stream-json",
            content.lower(),
            "Should not describe bidirectional I/O model",
        )


class TestOverview(unittest.TestCase):
    """AC-2: overview.md describes the M3 architecture."""

    def _make_content(self):
        return _read("overview.md")

    def test_describes_office_manager(self):
        content = self._make_content()
        self.assertIn("Office Manager", content)

    def test_describes_project_manager(self):
        content = self._make_content()
        self.assertIn("Project Manager", content)

    def test_describes_bus_dispatch(self):
        """Overview mentions bus-mediated dispatch, not liaison relay."""
        content = self._make_content()
        self.assertTrue(
            "Send" in content or "bus" in content.lower() or "message bus" in content.lower(),
            "Overview should describe bus-mediated dispatch",
        )

    def test_no_home_agent(self):
        """Overview does not describe Home agent as current."""
        content = self._make_content()
        # Home agent may be mentioned as future but not in agent types table
        lines = content.split("\n")
        in_agent_types = False
        for line in lines:
            if "Agent Types" in line:
                in_agent_types = True
            if in_agent_types and line.startswith("#"):
                in_agent_types = False
            if in_agent_types and "Home agent" in line:
                self.fail("Agent Types table should not list Home agent")

    def test_technology_stack_paths(self):
        """Technology stack references teaparty/ not projects/POC/."""
        content = self._make_content()
        self.assertNotIn("projects/POC/", content)
        self.assertIn("teaparty/", content)


class TestNewDocsExist(unittest.TestCase):
    """AC-14 through AC-21: New documents exist."""

    def test_conceptual_messaging(self):
        self.assertTrue(
            _exists("conceptual-design/messaging.md"),
            "Missing docs/conceptual-design/messaging.md",
        )

    def test_conceptual_team_configuration(self):
        self.assertTrue(
            _exists("conceptual-design/team-configuration.md"),
            "Missing docs/conceptual-design/team-configuration.md",
        )

    def test_conceptual_office_manager(self):
        self.assertTrue(
            _exists("conceptual-design/office-manager.md"),
            "Missing docs/conceptual-design/office-manager.md",
        )

    def test_detailed_context_budget(self):
        self.assertTrue(
            _exists("detailed-design/context-budget.md"),
            "Missing docs/detailed-design/context-budget.md",
        )

    def test_detailed_messaging(self):
        self.assertTrue(
            _exists("detailed-design/messaging.md"),
            "Missing docs/detailed-design/messaging.md",
        )

    def test_detailed_team_configuration(self):
        self.assertTrue(
            _exists("detailed-design/team-configuration.md"),
            "Missing docs/detailed-design/team-configuration.md",
        )

    def test_detailed_launcher(self):
        """Either launcher.md exists or unified-agent-launch.md was rewritten."""
        has_launcher = _exists("detailed-design/launcher.md")
        # If no launcher.md, check that unified-agent-launch.md describes
        # the as-built system (contains "launch()" function reference)
        if not has_launcher:
            content = _read("detailed-design/unified-agent-launch.md")
            self.assertIn(
                "launch(",
                content,
                "Neither launcher.md exists nor unified-agent-launch.md "
                "describes the as-built launch() function",
            )

    def test_reference_dashboard(self):
        self.assertTrue(
            _exists("reference/dashboard.md"),
            "Missing docs/reference/dashboard.md",
        )


class TestFolderStructure(unittest.TestCase):
    """AC-1: folder-structure.md describes the current layout."""

    def _make_content(self):
        return _read("reference/folder-structure.md")

    def test_describes_teaparty_package(self):
        content = self._make_content()
        self.assertIn("teaparty/", content)

    def test_describes_teaparty_config(self):
        content = self._make_content()
        self.assertIn(".teaparty/", content)

    def test_no_orchestrator_at_root(self):
        content = self._make_content()
        # Should not describe orchestrator/ at repo root as current
        self.assertFalse(
            re.search(r"^\s*├── orchestrator/", content, re.MULTILINE),
            "Should not show orchestrator/ as top-level directory",
        )


class TestCfaStateMachine(unittest.TestCase):
    """AC-6: CfA state machine doc includes INTERVENE and WITHDRAW."""

    def _make_content(self):
        return _read("conceptual-design/cfa-state-machine.md")

    def test_mentions_intervene(self):
        content = self._make_content()
        self.assertIn("INTERVENE", content)

    def test_mentions_withdraw(self):
        content = self._make_content()
        self.assertIn("WITHDRAW", content)


class TestDetailedDesignIndex(unittest.TestCase):
    """AC-7: detailed-design/index.md is current."""

    def _make_content(self):
        return _read("detailed-design/index.md")

    def test_no_poc_references(self):
        content = self._make_content()
        self.assertNotIn("projects/POC/", content)

    def test_references_teaparty_package(self):
        content = self._make_content()
        self.assertIn("teaparty/", content)

    def test_mentions_unified_launcher(self):
        content = self._make_content()
        self.assertTrue(
            "unified" in content.lower() or "launch" in content.lower(),
            "Should mention the unified launcher",
        )


class TestMkdocsNav(unittest.TestCase):
    """AC-22: mkdocs.yml navigation includes new docs."""

    def _make_content(self):
        path = os.path.join(DOCS, "..", "mkdocs.yml")
        if not os.path.exists(path):
            return ""
        with open(path) as f:
            return f.read()

    def test_nav_includes_messaging(self):
        content = self._make_content()
        if not content:
            self.skipTest("mkdocs.yml not found")
        self.assertIn("messaging", content.lower())

    def test_nav_includes_team_configuration(self):
        content = self._make_content()
        if not content:
            self.skipTest("mkdocs.yml not found")
        self.assertIn("team-configuration", content.lower())


if __name__ == "__main__":
    unittest.main()
