"""Tests for issue #310: Registry-based discovery, flatten repo structure, onboarding UI.

Acceptance criteria:
1. orchestrator/ package importable at repo root (not projects.POC.orchestrator)
2. bridge/ package importable at repo root (not projects.POC.bridge)
3. TeaPartyBridge constructor does not accept projects_dir parameter
4. bridge/__main__.py does not define --project-dir argument
5. teaparty.sh does not pass --project-dir
6. Bridge app exposes /api/projects/add and /api/projects/create endpoints
7. Dashboard HTML (index.html) has file-picker trigger for new/add project
"""
import inspect
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

_REPO_ROOT = Path(__file__).parent.parent


# ── 1 & 2. Flat package locations ────────────────────────────────────────────

class TestFlatPackageLocations(unittest.TestCase):
    """orchestrator and bridge must be importable as top-level packages."""

    def test_orchestrator_importable_at_root(self):
        """from orchestrator.engine import Orchestrator must work."""
        from orchestrator.engine import Orchestrator
        self.assertTrue(callable(Orchestrator))

    def test_bridge_importable_at_root(self):
        """from bridge.server import TeaPartyBridge must work."""
        from bridge.server import TeaPartyBridge
        self.assertTrue(callable(TeaPartyBridge))

    def test_orchestrator_config_reader_importable_at_root(self):
        """from orchestrator.config_reader import discover_projects must work."""
        from orchestrator.config_reader import discover_projects
        self.assertTrue(callable(discover_projects))

    def test_orchestrator_session_importable_at_root(self):
        """from orchestrator.session import Session must work."""
        from orchestrator.session import Session
        self.assertTrue(callable(Session))

    def test_scripts_cfa_state_importable_at_root(self):
        """from scripts.cfa_state import load_state must work."""
        from scripts.cfa_state import load_state
        self.assertTrue(callable(load_state))


# ── 3. TeaPartyBridge drops projects_dir ──────────────────────────────────────

class TestTeaPartyBridgeConstructorSignature(unittest.TestCase):
    """TeaPartyBridge.__init__ must not accept a projects_dir parameter."""

    def test_no_projects_dir_parameter(self):
        """TeaPartyBridge.__init__ must not have a projects_dir parameter."""
        from bridge.server import TeaPartyBridge
        sig = inspect.signature(TeaPartyBridge.__init__)
        self.assertNotIn(
            'projects_dir', sig.parameters,
            'TeaPartyBridge.__init__ must not accept projects_dir; '
            'project discovery comes from the registry only',
        )

    def test_teaparty_home_parameter_present(self):
        """TeaPartyBridge.__init__ must still accept teaparty_home."""
        from bridge.server import TeaPartyBridge
        sig = inspect.signature(TeaPartyBridge.__init__)
        self.assertIn('teaparty_home', sig.parameters)

    def test_static_dir_parameter_present(self):
        """TeaPartyBridge.__init__ must still accept static_dir."""
        from bridge.server import TeaPartyBridge
        sig = inspect.signature(TeaPartyBridge.__init__)
        self.assertIn('static_dir', sig.parameters)


# ── 4. bridge/__main__.py has no --project-dir ────────────────────────────────

class TestBridgeMainArgParser(unittest.TestCase):
    """bridge/__main__.py must not define a --project-dir CLI argument."""

    def _get_main_source(self) -> str:
        path = _REPO_ROOT / 'bridge' / '__main__.py'
        self.assertTrue(path.exists(), f'bridge/__main__.py not found at {path}')
        return path.read_text()

    def test_no_project_dir_argument(self):
        """bridge/__main__.py must not add --project-dir to the arg parser."""
        source = self._get_main_source()
        self.assertNotIn(
            '--project-dir', source,
            'bridge/__main__.py must not define --project-dir; '
            'project discovery is registry-only',
        )

    def test_project_dir_not_passed_to_bridge(self):
        """bridge/__main__.py must not pass projects_dir to TeaPartyBridge."""
        source = self._get_main_source()
        self.assertNotIn(
            'projects_dir', source,
            'bridge/__main__.py must not reference projects_dir',
        )


# ── 5. teaparty.sh has no --project-dir ───────────────────────────────────────

class TestTeapartyShScript(unittest.TestCase):
    """teaparty.sh must not document or pass --project-dir."""

    def _get_script_source(self) -> str:
        path = _REPO_ROOT / 'teaparty.sh'
        self.assertTrue(path.exists(), f'teaparty.sh not found at {path}')
        return path.read_text()

    def test_no_project_dir_in_teaparty_sh(self):
        """teaparty.sh must not mention --project-dir."""
        source = self._get_script_source()
        self.assertNotIn(
            '--project-dir', source,
            'teaparty.sh must not mention --project-dir; '
            'project discovery is registry-only',
        )


# ── 6. Bridge project management API endpoints ───────────────────────────────

class TestBridgeProjectEndpoints(unittest.TestCase):
    """Bridge app must expose /api/projects/add and /api/projects/create."""

    def _get_app_routes(self):
        from bridge.server import TeaPartyBridge
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            bridge = TeaPartyBridge(
                teaparty_home=tmp,
                static_dir=tmp,
            )
            app = bridge._build_app()
            return {str(r.resource)} if hasattr(r, 'resource') else set()

    def _get_server_source(self) -> str:
        path = _REPO_ROOT / 'bridge' / 'server.py'
        self.assertTrue(path.exists(), f'bridge/server.py not found at {path}')
        return path.read_text()

    def test_projects_add_endpoint_in_source(self):
        """/api/projects/add endpoint must be registered in bridge/server.py."""
        source = self._get_server_source()
        self.assertIn(
            '/api/projects/add', source,
            'bridge/server.py must register /api/projects/add endpoint',
        )

    def test_projects_create_endpoint_in_source(self):
        """/api/projects/create endpoint must be registered in bridge/server.py."""
        source = self._get_server_source()
        self.assertIn(
            '/api/projects/create', source,
            'bridge/server.py must register /api/projects/create endpoint',
        )

    def test_projects_add_handler_calls_add_project(self):
        """bridge/server.py must delegate /api/projects/add to config_reader.add_project."""
        source = self._get_server_source()
        self.assertIn(
            'add_project', source,
            'bridge/server.py /api/projects/add must call add_project()',
        )

    def test_projects_create_handler_calls_create_project(self):
        """bridge/server.py must delegate /api/projects/create to config_reader.create_project."""
        source = self._get_server_source()
        self.assertIn(
            'create_project', source,
            'bridge/server.py /api/projects/create must call create_project()',
        )


# ── 7. Dashboard HTML has project onboarding ─────────────────────────────────

class TestDashboardProjectOnboardingUI(unittest.TestCase):
    """Dashboard index.html must have file-picker-based New/Add project actions."""

    def _get_index_source(self) -> str:
        # After flattening, static files should be served from bridge/static/
        # or docs/proposals/ui-redesign/mockup/
        for candidate in [
            _REPO_ROOT / 'bridge' / 'static' / 'index.html',
            _REPO_ROOT / 'docs' / 'proposals' / 'ui-redesign' / 'mockup' / 'index.html',
        ]:
            if candidate.exists():
                return candidate.read_text()
        self.fail('index.html not found in bridge/static/ or docs mockup')

    def test_new_project_button_present(self):
        """index.html must contain a New Project button or action."""
        source = self._get_index_source()
        self.assertIn(
            'New Project', source,
            'index.html must have a "New Project" button',
        )

    def test_add_project_or_file_picker_present(self):
        """index.html must trigger a file-picker or project-add dialog."""
        source = self._get_index_source()
        has_picker = any(kw in source for kw in [
            'showDirectoryPicker', 'showOpenFilePicker', 'file-picker',
            'filePicker', 'pickFolder', 'Add Project', 'addProject',
            '/api/projects/add', '/api/projects/create',
        ])
        self.assertTrue(
            has_picker,
            'index.html must include a file picker or project add/create API call',
        )

    def test_project_onboarding_calls_api(self):
        """index.html must POST to /api/projects/add or /api/projects/create."""
        source = self._get_index_source()
        has_api_call = (
            '/api/projects/add' in source or
            '/api/projects/create' in source
        )
        self.assertTrue(
            has_api_call,
            'index.html must call /api/projects/add or /api/projects/create '
            'when creating/adding a project',
        )


# ── Structural: no projects.POC imports in source files ───────────────────────

class TestNoProjectsPOCImportsInSource(unittest.TestCase):
    """No source file in orchestrator/ or bridge/ may import from projects.POC.*"""

    def _find_poc_imports_in_dir(self, dir_name: str) -> list[str]:
        """Return list of 'file:line: import' for any projects.POC.* import found."""
        violations = []
        root = _REPO_ROOT / dir_name
        if not root.exists():
            return [f'directory {dir_name}/ does not exist']
        for path in root.rglob('*.py'):
            if '__pycache__' in str(path):
                continue
            for i, line in enumerate(path.read_text().splitlines(), 1):
                if 'projects.POC' in line and not line.strip().startswith('#'):
                    violations.append(f'{path.relative_to(_REPO_ROOT)}:{i}: {line.strip()}')
        return violations

    def test_orchestrator_has_no_projects_poc_imports(self):
        """orchestrator/ must not contain any 'from projects.POC' imports."""
        violations = self._find_poc_imports_in_dir('orchestrator')
        self.assertEqual(
            violations, [],
            f'orchestrator/ contains projects.POC imports:\n' +
            '\n'.join(violations[:10]),
        )

    def test_bridge_has_no_projects_poc_imports(self):
        """bridge/ must not contain any 'from projects.POC' imports."""
        violations = self._find_poc_imports_in_dir('bridge')
        self.assertEqual(
            violations, [],
            f'bridge/ contains projects.POC imports:\n' +
            '\n'.join(violations[:10]),
        )

    def test_scripts_has_no_projects_poc_imports(self):
        """scripts/ must not contain any 'from projects.POC' imports."""
        violations = self._find_poc_imports_in_dir('scripts')
        self.assertEqual(
            violations, [],
            f'scripts/ contains projects.POC imports:\n' +
            '\n'.join(violations[:10]),
        )

    def _find_poc_path_strings_in_dir(self, dir_name: str) -> list[str]:
        """Return violations where 'projects/POC' appears as a string literal (not comment)."""
        violations = []
        root = _REPO_ROOT / dir_name
        if not root.exists():
            return [f'directory {dir_name}/ does not exist']
        for path in root.rglob('*.py'):
            if '__pycache__' in str(path):
                continue
            for i, line in enumerate(path.read_text().splitlines(), 1):
                stripped = line.strip()
                if 'projects/POC' in line and not stripped.startswith('#'):
                    violations.append(f'{path.relative_to(_REPO_ROOT)}:{i}: {stripped}')
        return violations

    def test_orchestrator_has_no_projects_poc_paths(self):
        """orchestrator/ must not contain 'projects/POC' string literals."""
        violations = self._find_poc_path_strings_in_dir('orchestrator')
        self.assertEqual(
            violations, [],
            'orchestrator/ contains projects/POC path strings:\n' +
            '\n'.join(violations[:10]),
        )

    def test_bridge_has_no_projects_poc_paths(self):
        """bridge/ must not contain 'projects/POC' string literals."""
        violations = self._find_poc_path_strings_in_dir('bridge')
        self.assertEqual(
            violations, [],
            'bridge/ contains projects/POC path strings:\n' +
            '\n'.join(violations[:10]),
        )


if __name__ == '__main__':
    unittest.main()
