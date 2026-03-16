#!/usr/bin/env python3
"""Tests for issue #158: Dispatch idle time indicators only update after activity.

The drilldown screen's dispatch list shows age labels (e.g., "3m", "15s") but
only updates them when the dispatch list structure changes (add/remove/status).
Between structural changes, the age labels are stale.

Tests verify:
  1. When dispatch structure is unchanged but stream_age_seconds has increased,
     the OptionList labels are updated with the new age
  2. Age-only updates do not trigger a full OptionList rebuild (no clear_options)
"""
import os
import sys
import unittest
from dataclasses import dataclass
from unittest.mock import MagicMock, patch, call

from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent.parent))

from projects.POC.tui.screens.drilldown import DrilldownScreen, _human_age


@dataclass
class _FakeDispatch:
    team: str = 'coding'
    worktree_name: str = 'session--test-task'
    worktree_path: str = '/tmp/worktree'
    task: str = 'test task'
    status: str = 'active'
    infra_dir: str = '/tmp/infra'
    stream_age_seconds: int = 60


@dataclass
class _FakeSession:
    dispatches: list = None
    project: str = 'POC'
    session_id: str = 'test-session'
    cfa_phase: str = 'execution'
    cfa_state: str = 'TASK_IN_PROGRESS'
    is_orphaned: bool = False
    needs_input: bool = False
    worktree_path: str = '/tmp/worktree'
    task: str = 'test task'
    infra_dir: str = '/tmp/infra'

    def __post_init__(self):
        if self.dispatches is None:
            self.dispatches = []


class TestDispatchAgeUpdatesOnRefresh(unittest.TestCase):
    """Age labels must update every refresh cycle, not just on structural changes."""

    def _make_screen(self):
        """Create a DrilldownScreen with mocked Textual internals."""
        screen = DrilldownScreen.__new__(DrilldownScreen)
        screen.session_id = 'test-session'
        screen._session = None
        screen._dispatch_map = {}
        screen._last_dispatch_key = ''
        screen._last_header = ''
        screen._last_meta = ''
        screen._last_todos = []
        screen._input_latched = False
        screen._input_cooldown = False
        screen._shown_dialog_reply = ''
        screen._in_proc = None
        screen._scroll_locked = False
        return screen

    def test_age_labels_update_without_structural_change(self):
        """When dispatches haven't changed structurally but age has increased,
        the displayed age labels must be updated."""
        screen = self._make_screen()

        dispatch = _FakeDispatch(stream_age_seconds=60)
        screen._session = _FakeSession(dispatches=[dispatch])

        # Mock the OptionList widget
        ol = MagicMock()
        ol.option_count = 2  # 1 team header + 1 dispatch
        screen.query_one = MagicMock(return_value=ol)

        # First call: builds the list
        screen._update_dispatches()

        # Verify list was built (clear_options called)
        ol.clear_options.assert_called()
        ol.clear_options.reset_mock()

        # Second call: same structure, but age increased
        dispatch.stream_age_seconds = 120
        screen._update_dispatches()

        # The list must NOT be rebuilt (no clear_options)
        ol.clear_options.assert_not_called()

        # But the age label must be updated via replace_option_prompt_at_index
        ol.replace_option_prompt_at_index.assert_called()
        # The new label should contain the updated age
        prompt_arg = ol.replace_option_prompt_at_index.call_args[0][1]
        self.assertIn(_human_age(120), prompt_arg,
                      "Age label must reflect updated stream_age_seconds")

    def test_no_age_update_when_empty(self):
        """When there are no active dispatches, age update must not run."""
        screen = self._make_screen()
        screen._session = _FakeSession(dispatches=[])

        ol = MagicMock()
        screen.query_one = MagicMock(return_value=ol)

        screen._update_dispatches()
        screen._update_dispatches()

        # replace_option_prompt_at_index should never be called
        ol.replace_option_prompt_at_index.assert_not_called()


if __name__ == '__main__':
    unittest.main()
