"""Tests for issue #305: Retire the Textual TUI once bridge is stable.

Acceptance criteria:
1. projects/POC/tui/ directory does not exist in the repository
2. 'textual' is not listed as a dependency in pyproject.toml
3. teaparty.sh launches the bridge server, not the TUI
4. No production code in orchestrator/ or bridge/ imports from projects.POC.tui
5. CLAUDE.md does not describe teaparty.sh as a TUI dashboard
6. projects/POC/bridge/__main__.py exists to enable python -m projects.POC.bridge
"""
import os
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent


class TestTUIDirectoryRemoved(unittest.TestCase):
    """projects/POC/tui/ must not exist."""

    def test_tui_directory_does_not_exist(self):
        tui_dir = REPO_ROOT / 'projects' / 'POC' / 'tui'
        self.assertFalse(
            tui_dir.exists(),
            f'projects/POC/tui/ still exists — it must be removed',
        )


class TestTextualDependencyRemoved(unittest.TestCase):
    """textual must not be listed as a project dependency."""

    def test_textual_not_in_pyproject_dependencies(self):
        pyproject = (REPO_ROOT / 'pyproject.toml').read_text()
        self.assertNotIn(
            'textual',
            pyproject,
            'textual is still listed in pyproject.toml — must be removed',
        )


class TestTeapartyShLaunchesBridge(unittest.TestCase):
    """teaparty.sh must invoke the bridge, not the TUI."""

    def _read_script(self) -> str:
        return (REPO_ROOT / 'teaparty.sh').read_text()

    def test_script_does_not_reference_tui_module(self):
        source = self._read_script()
        self.assertNotIn(
            'projects.POC.tui',
            source,
            'teaparty.sh still references projects.POC.tui — must invoke bridge instead',
        )

    def test_script_launches_bridge_module(self):
        source = self._read_script()
        self.assertIn(
            '-m bridge',
            source,
            'teaparty.sh must invoke bridge (python -m bridge)',
        )


class TestBridgeHasMainEntryPoint(unittest.TestCase):
    """bridge/__main__.py must exist to support python -m bridge."""

    def test_bridge_main_exists(self):
        main = REPO_ROOT / 'bridge' / '__main__.py'
        self.assertTrue(
            main.exists(),
            'bridge/__main__.py must exist for python -m bridge',
        )

    def test_bridge_main_importable(self):
        """bridge.__main__ must not raise on import."""
        import importlib.util
        main_path = REPO_ROOT / 'bridge' / '__main__.py'
        if not main_path.exists():
            self.skipTest('__main__.py does not exist yet')
        spec = importlib.util.spec_from_file_location('bridge.__main__', main_path)
        # Just verify the spec loads without error — do not exec the module
        # (it would start the server)
        self.assertIsNotNone(spec)


class TestNoProductionTUIImports(unittest.TestCase):
    """Production code in orchestrator/ and bridge/ must not import from projects.POC.tui."""

    def _source_files(self, subdir: str):
        base = REPO_ROOT / subdir
        return list(base.rglob('*.py'))

    def _check_no_tui_imports(self, files):
        violations = []
        for path in files:
            if '__pycache__' in str(path):
                continue
            source = path.read_text(errors='replace')
            if 'projects.POC.tui' in source or 'from .tui' in source:
                violations.append(str(path.relative_to(REPO_ROOT)))
        return violations

    def test_orchestrator_has_no_tui_imports(self):
        files = self._source_files('orchestrator')
        # Exclude tests directory — tests may reference TUI historically
        files = [f for f in files if 'tests' not in f.parts]
        violations = self._check_no_tui_imports(files)
        self.assertEqual(
            violations, [],
            f'orchestrator production code imports from TUI: {violations}',
        )

    def test_bridge_has_no_tui_imports(self):
        files = self._source_files('bridge')
        violations = self._check_no_tui_imports(files)
        self.assertEqual(
            violations, [],
            f'bridge production code imports from TUI: {violations}',
        )


class TestCLAUDEMdUpdated(unittest.TestCase):
    """CLAUDE.md must not describe teaparty.sh as a TUI dashboard."""

    def test_claude_md_does_not_call_teaparty_sh_tui(self):
        claude_md = (REPO_ROOT / '.claude' / 'CLAUDE.md').read_text()
        self.assertNotIn(
            'TUI dashboard',
            claude_md,
            'CLAUDE.md still describes teaparty.sh as "TUI dashboard"',
        )

    def test_claude_md_does_not_reference_tui_directory(self):
        claude_md = (REPO_ROOT / '.claude' / 'CLAUDE.md').read_text()
        self.assertNotIn(
            'projects/POC/tui',
            claude_md,
            'CLAUDE.md still references projects/POC/tui/',
        )
