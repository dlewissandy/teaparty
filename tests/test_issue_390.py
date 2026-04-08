"""Issue #390: Restructure codebase for progressive discovery.

Specification-based tests verifying the target package structure,
import paths, dead code removal, and domain independence.
"""

import importlib
import os
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


class TestPackageStructureExists(unittest.TestCase):
    """Verify the teaparty/ top-level package and all sub-packages exist."""

    EXPECTED_PACKAGES = [
        "teaparty",
        "teaparty.cfa",
        "teaparty.cfa.statemachine",
        "teaparty.cfa.gates",
        "teaparty.proxy",
        "teaparty.learning",
        "teaparty.learning.procedural",
        "teaparty.learning.episodic",
        "teaparty.learning.research",
        "teaparty.bridge",
        "teaparty.bridge.state",
        "teaparty.mcp",
        "teaparty.mcp.server",
        "teaparty.mcp.tools",
        "teaparty.runners",
        "teaparty.messaging",
        "teaparty.teams",
        "teaparty.workspace",
        "teaparty.config",
        "teaparty.scheduling",
        "teaparty.scripts",
        "teaparty.util",
    ]

    def test_all_packages_have_init_files(self):
        """Every package directory must contain __init__.py."""
        for pkg in self.EXPECTED_PACKAGES:
            pkg_path = REPO_ROOT / pkg.replace(".", "/") / "__init__.py"
            self.assertTrue(
                pkg_path.exists(),
                f"Missing __init__.py for package {pkg} at {pkg_path}",
            )

    def test_top_level_package_has_main(self):
        """teaparty/__main__.py must exist for CLI entry."""
        self.assertTrue((REPO_ROOT / "teaparty" / "__main__.py").exists())


class TestDeadCodeRemoved(unittest.TestCase):
    """Dead code identified in the issue must not exist anywhere."""

    DEAD_FILES = [
        "orchestrator/tui_bridge.py",
        "scripts/retroactive_extract.py",
        "scripts/seed_publishing_company.py",
    ]

    def test_dead_files_do_not_exist(self):
        for f in self.DEAD_FILES:
            self.assertFalse(
                (REPO_ROOT / f).exists(),
                f"Dead code not removed: {f}",
            )


class TestOldDirectoriesRemoved(unittest.TestCase):
    """The old orchestrator/ and scripts/ top-level directories should not
    contain Python source files after the restructure."""

    def test_orchestrator_has_no_python_source(self):
        """orchestrator/ should not contain .py files."""
        orch = REPO_ROOT / "orchestrator"
        if orch.exists():
            py_files = list(orch.glob("*.py"))
            self.assertEqual(
                py_files, [],
                f"orchestrator/ still contains Python files: {[f.name for f in py_files]}",
            )

    def test_scripts_has_no_python_source(self):
        """scripts/ should not contain .py files (recursively)."""
        scripts = REPO_ROOT / "scripts"
        if scripts.exists():
            py_files = list(scripts.rglob("*.py"))
            self.assertEqual(
                py_files, [],
                f"scripts/ still contains Python files: {[f.name for f in py_files]}",
            )


class TestCfaModuleLocations(unittest.TestCase):
    """CfA protocol modules exist at their target paths."""

    def test_engine_in_cfa(self):
        self.assertTrue((REPO_ROOT / "teaparty/cfa/engine.py").exists())

    def test_session_in_cfa(self):
        self.assertTrue((REPO_ROOT / "teaparty/cfa/session.py").exists())

    def test_actors_in_cfa(self):
        self.assertTrue((REPO_ROOT / "teaparty/cfa/actors.py").exists())

    def test_dispatch_in_cfa(self):
        self.assertTrue((REPO_ROOT / "teaparty/cfa/dispatch.py").exists())

    def test_state_machine_json_in_statemachine(self):
        self.assertTrue(
            (REPO_ROOT / "teaparty/cfa/statemachine/cfa-state-machine.json").exists()
        )

    def test_state_machine_json_not_at_root(self):
        self.assertFalse(
            (REPO_ROOT / "cfa-state-machine.json").exists(),
            "cfa-state-machine.json should have moved to teaparty/cfa/statemachine/",
        )


class TestProxyIndependentOfCfa(unittest.TestCase):
    """proxy/ must be importable without pulling in CfA engine."""

    def test_proxy_agent_importable(self):
        mod = importlib.import_module("teaparty.proxy.agent")
        self.assertTrue(hasattr(mod, "__name__"))

    def test_proxy_review_importable(self):
        mod = importlib.import_module("teaparty.proxy.review")
        self.assertTrue(hasattr(mod, "__name__"))


class TestLearningIndependentOfCfa(unittest.TestCase):
    """learning/ must be importable without pulling in CfA engine."""

    def test_learning_extract_importable(self):
        mod = importlib.import_module("teaparty.learning.extract")
        self.assertTrue(hasattr(mod, "__name__"))


class TestMcpDecomposed(unittest.TestCase):
    """mcp_server.py monolith must be decomposed into teaparty/mcp/."""

    def test_mcp_server_main_exists(self):
        self.assertTrue((REPO_ROOT / "teaparty/mcp/server/main.py").exists())

    def test_mcp_tools_config_crud_exists(self):
        self.assertTrue((REPO_ROOT / "teaparty/mcp/tools/config_crud.py").exists())

    def test_mcp_tools_escalation_exists(self):
        self.assertTrue((REPO_ROOT / "teaparty/mcp/tools/escalation.py").exists())

    def test_mcp_tools_messaging_exists(self):
        self.assertTrue((REPO_ROOT / "teaparty/mcp/tools/messaging.py").exists())

    def test_mcp_tools_intervention_exists(self):
        self.assertTrue((REPO_ROOT / "teaparty/mcp/tools/intervention.py").exists())

    def test_old_mcp_server_monolith_removed(self):
        self.assertFalse(
            (REPO_ROOT / "orchestrator/mcp_server.py").exists(),
            "mcp_server.py monolith should be decomposed into teaparty/mcp/",
        )


class TestBridgeStateModules(unittest.TestCase):
    """State reader/writer moved from orchestrator/ to teaparty/bridge/state/."""

    def test_state_reader_in_bridge(self):
        self.assertTrue((REPO_ROOT / "teaparty/bridge/state/reader.py").exists())

    def test_state_writer_in_bridge(self):
        self.assertTrue((REPO_ROOT / "teaparty/bridge/state/writer.py").exists())

    def test_heartbeat_in_bridge(self):
        self.assertTrue((REPO_ROOT / "teaparty/bridge/state/heartbeat.py").exists())

    def test_dashboard_stats_in_bridge(self):
        self.assertTrue((REPO_ROOT / "teaparty/bridge/state/dashboard_stats.py").exists())

    def test_navigation_in_bridge(self):
        self.assertTrue((REPO_ROOT / "teaparty/bridge/state/navigation.py").exists())


class TestRunnerModules(unittest.TestCase):
    """Runner backends in teaparty/runners/."""

    def test_claude_runner(self):
        self.assertTrue((REPO_ROOT / "teaparty/runners/claude.py").exists())

    def test_ollama_runner(self):
        self.assertTrue((REPO_ROOT / "teaparty/runners/ollama.py").exists())

    def test_deterministic_runner(self):
        self.assertTrue((REPO_ROOT / "teaparty/runners/deterministic.py").exists())


class TestMessagingModules(unittest.TestCase):
    """Communication infrastructure in teaparty/messaging/."""

    def test_bus(self):
        self.assertTrue((REPO_ROOT / "teaparty/messaging/bus.py").exists())

    def test_conversations(self):
        self.assertTrue((REPO_ROOT / "teaparty/messaging/conversations.py").exists())

    def test_dispatcher(self):
        self.assertTrue((REPO_ROOT / "teaparty/messaging/dispatcher.py").exists())

    def test_listener(self):
        self.assertTrue((REPO_ROOT / "teaparty/messaging/listener.py").exists())


class TestPackageDocstrings(unittest.TestCase):
    """Each sub-package __init__.py should have a docstring describing its domain."""

    PACKAGES_WITH_DOCSTRINGS = [
        "teaparty",
        "teaparty.cfa",
        "teaparty.proxy",
        "teaparty.learning",
        "teaparty.bridge",
        "teaparty.mcp",
        "teaparty.runners",
        "teaparty.messaging",
        "teaparty.teams",
        "teaparty.workspace",
        "teaparty.config",
        "teaparty.scheduling",
        "teaparty.scripts",
        "teaparty.util",
    ]

    def test_init_files_have_docstrings(self):
        for pkg in self.PACKAGES_WITH_DOCSTRINGS:
            init_path = REPO_ROOT / pkg.replace(".", "/") / "__init__.py"
            if not init_path.exists():
                self.fail(f"{pkg}/__init__.py does not exist")
            content = init_path.read_text()
            self.assertTrue(
                content.strip().startswith('"""') or content.strip().startswith("'''"),
                f"{pkg}/__init__.py must have a docstring, got: {content[:80]!r}",
            )


if __name__ == "__main__":
    unittest.main()
