"""Tests for issue #307: Update CLAUDE.md and docs to reflect HTML dashboard replacing the TUI.

Acceptance criteria:
1. CLAUDE.md Quick Start describes ./teaparty.sh as HTML dashboard at localhost:8081 (not TUI)
2. CLAUDE.md Codebase section references bridge/ not TUI/projects/POC/tui
3. docs/detailed-design/agent-runtime.md EventBus section does not reference TUI as the UI
4. docs/detailed-design/heartbeat.md does not reference TUI display
5. docs/e2e/e2e-walkthrough.md does not describe the session using TUI terminology
6. docs/reference/autodiscovery.md does not use TUI as an example of a current interface
"""
import os
import re
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

CLAUDE_MD = os.path.join(REPO_ROOT, '.claude', 'CLAUDE.md')
AGENT_RUNTIME_MD = os.path.join(REPO_ROOT, 'docs', 'detailed-design', 'agent-runtime.md')
HEARTBEAT_MD = os.path.join(REPO_ROOT, 'docs', 'detailed-design', 'heartbeat.md')
E2E_WALKTHROUGH_MD = os.path.join(REPO_ROOT, 'docs', 'e2e', 'e2e-walkthrough.md')
AUTODISCOVERY_MD = os.path.join(REPO_ROOT, 'docs', 'reference', 'autodiscovery.md')


def _read(path):
    with open(path) as f:
        return f.read()


class TestClaudeMdQuickStart(unittest.TestCase):
    """CLAUDE.md Quick Start must describe the HTML dashboard, not the TUI."""

    def test_teaparty_sh_described_as_html_dashboard(self):
        """./teaparty.sh comment must mention HTML dashboard or bridge, not TUI."""
        content = _read(CLAUDE_MD)
        # Find the line with teaparty.sh
        lines = content.splitlines()
        sh_lines = [l for l in lines if 'teaparty.sh' in l]
        self.assertTrue(sh_lines, 'CLAUDE.md must have a ./teaparty.sh entry in Quick Start')
        sh_line = sh_lines[0]
        self.assertNotIn('TUI', sh_line,
                         'Quick Start teaparty.sh line must not say TUI')
        self.assertIn('localhost:8081', sh_line,
                      'Quick Start teaparty.sh line must reference localhost:8081 (HTML dashboard)')

    def test_quick_start_does_not_say_tui_dashboard(self):
        """Quick Start must not describe ./teaparty.sh as 'TUI dashboard'."""
        content = _read(CLAUDE_MD)
        self.assertNotIn('TUI dashboard', content,
                         'CLAUDE.md must not say "TUI dashboard" — it is an HTML dashboard')


class TestClaudeMdCodebaseSection(unittest.TestCase):
    """CLAUDE.md Codebase section must reference bridge/, not TUI paths."""

    def test_codebase_references_bridge_not_tui(self):
        """Codebase section must reference bridge/, not projects/POC/tui/."""
        content = _read(CLAUDE_MD)
        self.assertNotIn('projects/POC/tui', content,
                         'CLAUDE.md must not reference projects/POC/tui — TUI was retired')

    def test_codebase_has_bridge_entry(self):
        """Codebase section must mention bridge/ as the dashboard."""
        content = _read(CLAUDE_MD)
        self.assertIn('bridge/', content,
                      'CLAUDE.md Codebase section must list bridge/ as the dashboard')


class TestAgentRuntimeDocEventBus(unittest.TestCase):
    """agent-runtime.md EventBus section must reference the bridge dashboard, not TUI."""

    def test_event_bus_section_does_not_say_tui(self):
        """EventBus observability section must not describe TUI as the real-time display."""
        content = _read(AGENT_RUNTIME_MD)
        # Extract just the EventBus section
        idx = content.find('Event Bus and Observability')
        self.assertNotEqual(idx, -1, 'agent-runtime.md must have an EventBus section')
        section = content[idx:idx + 1000]  # scan the section
        self.assertNotIn('TUI', section,
                         'EventBus section must not say "TUI" — use bridge dashboard instead')

    def test_event_bus_section_references_bridge_dashboard(self):
        """EventBus section must reference the bridge dashboard as the real-time display."""
        content = _read(AGENT_RUNTIME_MD)
        idx = content.find('Event Bus and Observability')
        section = content[idx:idx + 1000]
        self.assertIn('bridge', section.lower(),
                      'EventBus section must reference the bridge dashboard as the UI subscriber')


class TestHeartbeatDoc(unittest.TestCase):
    """heartbeat.md must not say 'TUI display'."""

    def test_heartbeat_doc_does_not_say_tui_display(self):
        """state_reader.py line must not reference TUI display."""
        content = _read(HEARTBEAT_MD)
        self.assertNotIn('TUI display', content,
                         'heartbeat.md must not say "TUI display" — bridge dashboard is the UI')

    def test_heartbeat_doc_references_dashboard_display(self):
        """state_reader.py line must reference dashboard display."""
        content = _read(HEARTBEAT_MD)
        self.assertIn('dashboard', content.lower(),
                      'heartbeat.md must reference dashboard display instead of TUI display')


class TestE2EWalkthrough(unittest.TestCase):
    """e2e-walkthrough.md must not describe the session as happening in the TUI."""

    def test_walkthrough_does_not_say_this_is_the_tui(self):
        """Walkthrough must not say 'This is the TUI during the research phase'."""
        content = _read(E2E_WALKTHROUGH_MD)
        self.assertNotIn('This is the TUI during', content,
                         'e2e-walkthrough.md must not describe the session using TUI terminology')

    def test_walkthrough_image_alt_not_tui(self):
        """Image alt text must not say 'TUI workspace'."""
        content = _read(E2E_WALKTHROUGH_MD)
        self.assertNotIn('TUI workspace', content,
                         'e2e-walkthrough.md image alt text must not say "TUI workspace"')


class TestAutodiscoveryDoc(unittest.TestCase):
    """autodiscovery.md must not use TUI as an example of a current interface."""

    def test_autodiscovery_shifts_to_bridge_not_tui(self):
        """Context sensitivity example must reference bridge dashboard, not TUI."""
        content = _read(AUTODISCOVERY_MD)
        # Find the context-sensitivity example
        idx = content.find('Context sensitivity')
        if idx == -1:
            idx = content.find('context sensitivity')
        if idx != -1:
            example = content[idx:idx + 500]
            self.assertNotIn('the TUI', example,
                             'autodiscovery.md context sensitivity example must not reference the TUI')


if __name__ == '__main__':
    unittest.main()
