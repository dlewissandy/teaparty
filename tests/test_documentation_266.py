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
        "systems/messaging/dispatch.md",
        "systems/human-proxy/index.md",
        "systems/cfa-orchestration/index.md",
        "systems/cfa-orchestration/state-machine.md",
        "systems/index.md",
        "systems/workspace/agent-runtime.md",
        "systems/human-proxy/approval-gate.md",
        "systems/bridge/heartbeat.md",
        "systems/learning/index.md",
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
        """dispatch doc does not describe liaison agents."""
        content = _read("systems/messaging/dispatch.md")
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
                "dispatch.md references liaisons as current: "
                + "; ".join(lines),
            )

    def test_no_persistent_team_sessions(self):
        """dispatch doc describes one-shot launch, not persistent sessions."""
        content = _read("systems/messaging/dispatch.md")
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

    def test_describes_project_lead(self):
        """overview.md documents the Project Lead role (current team lead)."""
        content = self._make_content()
        self.assertIn("Project Lead", content)

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

    def test_messaging_doc(self):
        self.assertTrue(
            _exists("systems/messaging/index.md"),
            "Missing docs/systems/messaging/index.md",
        )

    def test_team_configuration_doc(self):
        self.assertTrue(
            _exists("reference/team-configuration.md"),
            "Missing docs/reference/team-configuration.md",
        )

    def test_office_manager_documented_in_overview(self):
        """Office Manager is documented in overview.md (org model)."""
        content = _read("overview.md")
        self.assertIn(
            "Office Manager", content,
            "overview.md should document the Office Manager role",
        )

    def test_context_budget_doc(self):
        self.assertTrue(
            _exists("systems/cfa-orchestration/context-budget.md"),
            "Missing docs/systems/cfa-orchestration/context-budget.md",
        )

    def test_messaging_implementation_doc(self):
        self.assertTrue(
            _exists("systems/messaging/bus-and-conversations.md"),
            "Missing docs/systems/messaging/bus-and-conversations.md",
        )

    def test_launcher_doc(self):
        """unified-launch.md describes the as-built launch() function."""
        content = _read("systems/workspace/unified-launch.md")
        self.assertIn(
            "launch(",
            content,
            "unified-launch.md should describe the as-built launch() function",
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
        return _read("systems/cfa-orchestration/index.md") + "\n" + _read(
            "systems/cfa-orchestration/state-machine.md"
        )

    def test_mentions_intervene(self):
        content = self._make_content()
        self.assertIn("INTERVENE", content)

    def test_mentions_withdraw(self):
        content = self._make_content()
        self.assertIn("WITHDRAW", content)


class TestArchitectureIndex(unittest.TestCase):
    """AC-7: systems/index.md (formerly detailed-design/index.md) is current."""

    def _make_content(self):
        return _read("systems/index.md")

    def test_no_poc_references(self):
        content = self._make_content()
        self.assertNotIn("projects/POC/", content)

    def test_references_teaparty_package(self):
        content = self._make_content()
        self.assertIn("teaparty/", content)

    def test_mentions_unified_launcher(self):
        """Unified launcher is documented under systems/workspace/."""
        content = _read("systems/workspace/index.md") + "\n" + _read(
            "systems/workspace/unified-launch.md"
        )
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
