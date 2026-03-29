"""Tests for issue #284: bridge accumulates open SQLite connections — no close protocol.

Acceptance criteria:
1. bridge-api.md Startup section includes explicit teardown: connections opened by the
   poller loop on first encounter of a non-terminal session, closed on terminal state.
2. The spec names what triggers close (terminal CfA state diffed by the poller), not
   just "connections close when sessions complete".
3. The spec identifies the terminal states that trigger teardown
   (COMPLETED_WORK and WITHDRAWN).
"""
import os
import unittest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_BRIDGE_API = os.path.join(
    _REPO_ROOT, 'docs', 'proposals', 'ui-redesign', 'references', 'bridge-api.md',
)


def _read_spec():
    with open(_BRIDGE_API) as f:
        return f.read()


def _startup_section(content: str) -> str:
    """Extract the text of the Startup section (from ## Startup to the next ## heading)."""
    start = content.find('## Startup')
    if start == -1:
        return ''
    end = content.find('\n## ', start + 1)
    return content[start:end] if end != -1 else content[start:]


# ── Startup section teardown documentation ───────────────────────────────────

class TestStartupSectionDocumentsTeardown(unittest.TestCase):
    """The Startup section must document when connections are opened and closed."""

    def setUp(self):
        self.content = _read_spec()
        self.startup = _startup_section(self.content)

    def test_startup_section_exists(self):
        self.assertNotEqual(self.startup, '',
                            'bridge-api.md must contain a ## Startup section')

    def test_startup_section_mentions_connection_close_or_teardown(self):
        """Startup section must address teardown — not just opening connections."""
        section = self.startup.lower()
        has_teardown = (
            'close' in section
            or 'teardown' in section
            or 'tear down' in section
            or 'shut down' in section
            or 'shutdown' in section
        )
        self.assertTrue(
            has_teardown,
            'Startup section must document connection teardown/close, not only opening',
        )

    def test_startup_section_documents_when_connections_open(self):
        """Startup section must say connections are opened for active/non-terminal sessions."""
        section = self.startup.lower()
        has_open = (
            'open' in section
            or 'connect' in section
        )
        self.assertTrue(
            has_open,
            'Startup section must document when connections are opened (active sessions)',
        )


# ── Trigger identification ────────────────────────────────────────────────────

class TestSpecIdentifiesCloseTrigger(unittest.TestCase):
    """The spec must identify what triggers connection close, not just state the outcome."""

    def setUp(self):
        self.content = _read_spec()

    def test_spec_identifies_poller_as_close_trigger(self):
        """The spec must name the poller as the component responsible for closing connections."""
        self.assertIn(
            'poller', self.content.lower(),
            'bridge-api.md must mention the poller in connection to the close protocol',
        )

    def test_spec_names_terminal_states_that_trigger_close(self):
        """The spec must name terminal states, not just say 'sessions complete'."""
        self.assertIn(
            'COMPLETED_WORK', self.content,
            'bridge-api.md must name COMPLETED_WORK as a terminal state that triggers close',
        )
        self.assertIn(
            'WITHDRAWN', self.content,
            'bridge-api.md must name WITHDRAWN as a terminal state that triggers close',
        )

    def test_spec_names_both_terminal_states_near_connection_lifecycle(self):
        """COMPLETED_WORK and WITHDRAWN must appear in connection lifecycle context."""
        # Find the section that discusses connection lifecycle — it should name both states.
        # We look for a paragraph/section containing both states.
        content = self.content
        completed_idx = content.find('COMPLETED_WORK')
        withdrawn_idx = content.find('WITHDRAWN')
        self.assertGreater(completed_idx, -1,
                           'COMPLETED_WORK not found in bridge-api.md')
        self.assertGreater(withdrawn_idx, -1,
                           'WITHDRAWN not found in bridge-api.md')
        # They must appear within 500 characters of each other (same paragraph/list)
        self.assertLess(
            abs(completed_idx - withdrawn_idx), 500,
            'COMPLETED_WORK and WITHDRAWN must appear near each other in the '
            'connection lifecycle documentation, not scattered across the document',
        )


# ── Connection lifecycle protocol completeness ────────────────────────────────

class TestConnectionLifecycleProtocolIsComplete(unittest.TestCase):
    """The spec must describe the full lifecycle: open condition, close condition, trigger."""

    def setUp(self):
        self.content = _read_spec()

    def test_spec_says_connections_close_on_terminal_state(self):
        """The spec must link connection close to terminal state detection, not vague 'completion'."""
        # Accept either 'terminal' or explicit naming of the trigger mechanism
        content = self.content.lower()
        has_terminal_link = (
            'terminal' in content
            or 'terminal state' in content.replace('\n', ' ')
        )
        self.assertTrue(
            has_terminal_link,
            'bridge-api.md must use "terminal" to describe the states that trigger '
            'connection close, making the protocol unambiguous',
        )

    def test_spec_does_not_only_say_sessions_complete(self):
        """The vague phrase alone is insufficient — spec must give implementation detail."""
        # The original spec only said "Connections close when sessions complete."
        # After the fix, it must say MORE than just that. We verify additional detail
        # exists by checking the lifecycle section is longer than a single sentence.
        startup = _startup_section(self.content)
        # Count lifecycle-related lines in startup
        lifecycle_lines = [
            ln for ln in startup.splitlines()
            if any(kw in ln.lower() for kw in ('close', 'open', 'connect', 'session', 'bus'))
        ]
        self.assertGreater(
            len(lifecycle_lines), 2,
            'Startup section must have more than one line about the connection lifecycle; '
            'a single "connections close when sessions complete" is insufficient',
        )


if __name__ == '__main__':
    unittest.main()
