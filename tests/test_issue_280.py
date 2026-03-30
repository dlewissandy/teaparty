"""Tests for issue #280: StateReader extracted to orchestrator, no TUI coupling.

Acceptance criteria:
1. projects.POC.orchestrator.state_reader exports StateReader and all data classes
2. _heartbeat_three_state and the 30s/300s thresholds live in the orchestrator module
3. orchestrator/state_reader.py has no imports from projects.POC.tui
4. The bridge-api spec names projects.POC.orchestrator.state_reader, not tui
"""
import ast
import os
import subprocess
import textwrap
import unittest


def _orchestrator_state_reader_path() -> str:
    here = os.path.dirname(__file__)
    return os.path.join(here, '..', 'orchestrator', 'state_reader.py')


def _tui_state_reader_path() -> str:
    here = os.path.dirname(__file__)
    return os.path.join(here, '..', '..', 'tui', 'state_reader.py')


class TestOrchestratorStateReaderExists(unittest.TestCase):
    """The orchestrator must own the state reader module."""

    def test_orchestrator_state_reader_module_importable(self):
        """StateReader must be importable from orchestrator.state_reader."""
        from orchestrator.state_reader import StateReader  # noqa: F401

    def test_orchestrator_state_reader_exports_data_classes(self):
        """ProjectState, SessionState, DispatchState must be in the orchestrator module."""
        from orchestrator.state_reader import (  # noqa: F401
            ProjectState,
            SessionState,
            DispatchState,
        )

    def test_orchestrator_state_reader_exports_human_actor_states(self):
        """HUMAN_ACTOR_STATES must be in the orchestrator module."""
        from orchestrator.state_reader import HUMAN_ACTOR_STATES
        self.assertIsInstance(HUMAN_ACTOR_STATES, frozenset)
        self.assertIn('WORK_ASSERT', HUMAN_ACTOR_STATES)


class TestHeartbeatThreeStateInOrchestrator(unittest.TestCase):
    """_heartbeat_three_state and its thresholds must live in the orchestrator."""

    def test_heartbeat_three_state_importable_from_orchestrator(self):
        """_heartbeat_three_state must be importable from the orchestrator module."""
        from orchestrator.state_reader import _heartbeat_three_state  # noqa: F401

    def test_alive_threshold_is_30_seconds(self):
        """_ALIVE_THRESHOLD must be 30 seconds (one BEAT_INTERVAL) in the orchestrator module."""
        from orchestrator.state_reader import _ALIVE_THRESHOLD
        self.assertEqual(_ALIVE_THRESHOLD, 30)

    def test_dead_threshold_is_300_seconds(self):
        """_DEAD_THRESHOLD must be 300 seconds (5 minutes) in the orchestrator module."""
        from orchestrator.state_reader import _DEAD_THRESHOLD
        self.assertEqual(_DEAD_THRESHOLD, 300)


class TestNoCouplingToTUI(unittest.TestCase):
    """orchestrator/state_reader.py must not import from projects.POC.tui."""

    def _get_source(self) -> str:
        path = os.path.normpath(_orchestrator_state_reader_path())
        with open(path) as f:
            return f.read()

    def test_orchestrator_state_reader_has_no_tui_imports_at_module_level(self):
        """No top-level 'from projects.POC.tui' imports in orchestrator/state_reader.py."""
        source = self._get_source()
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                if isinstance(node, ast.ImportFrom) and node.module:
                    self.assertFalse(
                        node.module.startswith('projects.POC.tui'),
                        f"orchestrator/state_reader.py has TUI import: "
                        f"from {node.module} (line {node.lineno})",
                    )

    def test_orchestrator_state_reader_has_no_tui_string_references(self):
        """No 'projects.POC.tui' string anywhere in orchestrator/state_reader.py
        (catches lazy imports inside function bodies)."""
        source = self._get_source()
        self.assertNotIn(
            'projects.POC.tui',
            source,
            "orchestrator/state_reader.py references projects.POC.tui — "
            "this creates a dependency on the module it supersedes.",
        )


class TestTUIStateReaderNoLongerOwnsCanonicalCode(unittest.TestCase):
    """tui/state_reader.py must not define StateReader independently;
    the orchestrator module is canonical."""

    def test_tui_does_not_define_state_reader_class(self):
        """tui/state_reader.py must not define its own StateReader class.

        After the fix, StateReader lives in the orchestrator and the TUI
        either re-exports it or is removed.  An independent TUI definition
        means the coupling was not resolved.
        """
        path = os.path.normpath(_tui_state_reader_path())
        if not os.path.exists(path):
            # File removed entirely — coupling resolved.
            return
        with open(path) as f:
            source = f.read()
        tree = ast.parse(source)
        class_names = [
            node.name for node in ast.walk(tree)
            if isinstance(node, ast.ClassDef)
        ]
        self.assertNotIn(
            'StateReader',
            class_names,
            "tui/state_reader.py still defines StateReader independently. "
            "StateReader must be defined only in projects.POC.orchestrator.state_reader.",
        )


class TestBridgeAPISpecNamesOrchestratorModule(unittest.TestCase):
    """The bridge-api spec must reference projects.POC.orchestrator.state_reader."""

    def _get_bridge_api_content(self) -> str | None:
        """Read bridge-api.md from the feature/ui-redesign-proposal branch."""
        here = os.path.dirname(__file__)
        repo_root = os.path.normpath(os.path.join(here, '..', '..', '..', '..'))
        try:
            result = subprocess.run(
                ['git', 'show',
                 'feature/ui-redesign-proposal:docs/proposals/ui-redesign/references/bridge-api.md'],
                capture_output=True, text=True, cwd=repo_root,
            )
            if result.returncode == 0:
                return result.stdout
        except Exception:
            pass
        return None

    def test_bridge_api_spec_imports_state_reader_from_orchestrator(self):
        """bridge-api.md must name projects.POC.orchestrator.state_reader as the import source."""
        content = self._get_bridge_api_content()
        if content is None:
            self.skipTest("feature/ui-redesign-proposal branch not accessible")
        self.assertIn(
            'orchestrator.state_reader',
            content,
            "bridge-api.md does not reference projects.POC.orchestrator.state_reader. "
            "The spec must name the orchestrator module, not the TUI.",
        )

    def test_bridge_api_spec_does_not_import_from_tui(self):
        """bridge-api.md must not say StateReader is imported from the TUI package."""
        content = self._get_bridge_api_content()
        if content is None:
            self.skipTest("feature/ui-redesign-proposal branch not accessible")
        # The spec should not say 'from tui' or 'tui.state_reader'
        self.assertNotIn(
            'tui.state_reader',
            content,
            "bridge-api.md still references tui.state_reader. "
            "StateReader must come from the orchestrator module.",
        )
