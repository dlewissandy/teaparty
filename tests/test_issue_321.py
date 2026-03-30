"""Tests for issue #321: Remove TUI from projects/POC/tui/ (dead code).

Acceptance criteria:
1. projects/POC/tui/ directory does not exist in the repository
2. No production source in orchestrator/ or bridge/ contains stale TUI actor names
3. No production source in orchestrator/ or bridge/ imports from projects.POC.tui
4. No orchestrator source (outside tui_bridge.py) describes current consumers as TUI
5. uv run pytest passes after deletion
"""
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent


class TestTUIDirectoryDeleted(unittest.TestCase):
    """projects/POC/tui/ must not exist."""

    def test_tui_directory_does_not_exist(self):
        tui_dir = REPO_ROOT / 'projects' / 'POC' / 'tui'
        self.assertFalse(
            tui_dir.exists(),
            'projects/POC/tui/ still exists — it must be deleted',
        )


class TestNoStaleTUIReferencesInOrchestrator(unittest.TestCase):
    """orchestrator/ must not contain stale TUI actor names or module references."""

    def _source_files(self, subdir: str):
        base = REPO_ROOT / subdir
        return [
            p for p in base.rglob('*.py')
            if '__pycache__' not in str(p)
        ]

    def test_withdraw_does_not_use_tui_withdraw_actor(self):
        """orchestrator/withdraw.py must not use 'tui-withdraw' as actor name."""
        withdraw_py = REPO_ROOT / 'orchestrator' / 'withdraw.py'
        source = withdraw_py.read_text()
        self.assertNotIn(
            'tui-withdraw',
            source,
            "orchestrator/withdraw.py must not use 'tui-withdraw' actor name — "
            "TUI is retired; use 'orchestrator-withdraw' instead",
        )

    def test_orchestrator_has_no_projects_poc_tui_imports(self):
        """orchestrator/ must not import from projects.POC.tui."""
        files = self._source_files('orchestrator')
        violations = []
        for path in files:
            source = path.read_text(errors='replace')
            if 'projects.POC.tui' in source or 'from .tui' in source:
                violations.append(str(path.relative_to(REPO_ROOT)))
        self.assertEqual(
            violations, [],
            f'orchestrator imports from retired projects.POC.tui: {violations}',
        )

    def test_bridge_has_no_projects_poc_tui_imports(self):
        """bridge/ must not import from projects.POC.tui."""
        files = self._source_files('bridge')
        violations = []
        for path in files:
            source = path.read_text(errors='replace')
            if 'projects.POC.tui' in source or 'from .tui' in source:
                violations.append(str(path.relative_to(REPO_ROOT)))
        self.assertEqual(
            violations, [],
            f'bridge imports from retired projects.POC.tui: {violations}',
        )

    def test_orchestrator_source_does_not_describe_tui_as_current_consumer(self):
        """orchestrator/ source (excluding tui_bridge.py) must not describe TUI as current consumer.

        Stale comments like 'the TUI reads this' or 'TUI subscribes' describe a
        retired system and must be updated to reference the bridge.
        Allowed: tui_bridge.py (legitimately named), 'the retired TUI' (accurate history).
        """
        files = [
            p for p in (REPO_ROOT / 'orchestrator').rglob('*.py')
            if '__pycache__' not in str(p) and p.name != 'tui_bridge.py'
        ]
        # Patterns that indicate TUI is described as a current (not retired) consumer
        stale_patterns = [
            'the TUI (',
            'the TUI can',
            'the TUI doesn',
            'the TUI shows',
            'for TUI status',
            'for TUI observability',
            'for TUI compatibility',
            '↔ TUI',
            'TUI) subscribes',
            'TUI (or CLI)',
            'TUI (or any',
            'TUI (or messaging',
            '(TUI)',
            'via the input_provider (TUI',
            'Used by TUI',
            'bridge server and TUI',
            "TUI's own PID",
            'crash the TUI',
        ]
        violations = []
        for path in files:
            source = path.read_text(errors='replace')
            for pattern in stale_patterns:
                if pattern in source:
                    violations.append(f'{path.relative_to(REPO_ROOT)}: {pattern!r}')
        self.assertEqual(
            violations, [],
            f'orchestrator source describes TUI as current consumer: {violations}',
        )


if __name__ == '__main__':
    unittest.main()
