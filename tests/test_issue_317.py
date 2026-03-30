"""Tests for issue #317: Replace prompt() with modal dialogs in project onboarding UI.

Acceptance criteria:
1. No prompt() calls remain in the onboarding functions
2. Modal dialog function exists (showProjectModal)
3. Modal has labeled inputs for path and name (om-path, om-name)
4. Inline error display element exists (om-error)
5. No alert() calls in the onboarding path
6. Both /api/projects/create and /api/projects/add are still called on confirm
"""
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).parent.parent


class TestOnboardingModalUI(unittest.TestCase):
    """index.html onboarding must use a modal dialog, not prompt() or alert()."""

    def _get_index_source(self) -> str:
        for candidate in [
            _REPO_ROOT / 'bridge' / 'static' / 'index.html',
            _REPO_ROOT / 'docs' / 'proposals' / 'ui-redesign' / 'mockup' / 'index.html',
        ]:
            if candidate.exists():
                return candidate.read_text()
        self.fail('index.html not found in bridge/static/ or docs mockup')

    def test_no_prompt_calls(self):
        """index.html must not use prompt() for onboarding input."""
        source = self._get_index_source()
        self.assertNotIn(
            'prompt(',
            source,
            'index.html must not use prompt() — replace with a modal dialog',
        )

    def test_modal_function_exists(self):
        """index.html must define showProjectModal for onboarding."""
        source = self._get_index_source()
        self.assertIn(
            'showProjectModal',
            source,
            'index.html must define showProjectModal() for the onboarding dialog',
        )

    def test_modal_path_input_exists(self):
        """Modal must contain a path input (om-path)."""
        source = self._get_index_source()
        self.assertIn(
            'om-path',
            source,
            'Modal must have a path input element with id om-path',
        )

    def test_modal_name_input_exists(self):
        """Modal must contain a name input (om-name)."""
        source = self._get_index_source()
        self.assertIn(
            'om-name',
            source,
            'Modal must have a project name input element with id om-name',
        )

    def test_modal_inline_error_display_exists(self):
        """Modal must display errors inline (om-error), not via alert()."""
        source = self._get_index_source()
        self.assertIn(
            'om-error',
            source,
            'Modal must have an inline error element with id om-error',
        )

    def test_no_alert_in_onboarding(self):
        """index.html must not call alert() in the onboarding path."""
        source = self._get_index_source()
        # Extract the section around pickAndCreateProject/pickAndAddProject
        # to avoid false positives from unrelated code.
        start = source.find('pickAndCreateProject')
        end = source.rfind('pickAndAddProject') + 200
        if start == -1 or end < start:
            self.fail('pickAndCreateProject/pickAndAddProject not found in index.html')
        onboarding_section = source[start:end]
        self.assertNotIn(
            'alert(',
            onboarding_section,
            'Onboarding functions must not use alert() — show errors inline in the modal',
        )

    def test_create_calls_projects_create_endpoint(self):
        """pickAndCreateProject must POST to /api/projects/create."""
        source = self._get_index_source()
        self.assertIn(
            '/api/projects/create',
            source,
            'index.html must call /api/projects/create when creating a new project',
        )

    def test_add_calls_projects_add_endpoint(self):
        """pickAndAddProject must POST to /api/projects/add."""
        source = self._get_index_source()
        self.assertIn(
            '/api/projects/add',
            source,
            'index.html must call /api/projects/add when adding an existing project',
        )

    def test_modal_calls_load_data_on_success(self):
        """Modal must call loadData() after a successful API response."""
        source = self._get_index_source()
        # Find the modal function and check loadData() is called within it.
        start = source.find('showProjectModal')
        end = source.find('pickAndCreateProject', start + 1)
        if start == -1:
            self.fail('showProjectModal not found in index.html')
        modal_fn = source[start:end] if end > start else source[start:start + 2000]
        self.assertIn(
            'loadData()',
            modal_fn,
            'showProjectModal must call loadData() after a successful API response',
        )


if __name__ == '__main__':
    unittest.main()
