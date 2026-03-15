#!/usr/bin/env python3
"""Tests for issue #14: TUI Finder/VSCode buttons do nothing in drilldown.

Covers:
 1. create_dispatch_worktree registers in the MAIN repo manifest, not the
    session worktree's local manifest.
 2. StateReader populates worktree_path for dispatches when manifest entries
    exist in the main manifest.
 3. _session_worktree() returns a valid path when the manifest has a valid
    entry and the directory exists on disk.
 4. _session_worktree() glob fallback matches the current naming convention.
 5. Action handlers (open_finder, open_vscode) notify user when worktree not
    found — not silently returning.
"""
import asyncio
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent.parent))

from projects.POC.orchestrator.worktree import (
    create_dispatch_worktree,
    _register_worktree,
)
from projects.POC.tui.state_reader import StateReader, SessionState, DispatchState


# ── Helpers ───────────────────────────────────────────────────────────────────

def _run(coro):
    """Run a coroutine synchronously for testing."""
    return asyncio.run(coro)


def _make_repo_layout(tmpdir: str, project_slug: str = 'POC') -> dict:
    """Create a minimal on-disk layout matching the TUI's expectations."""
    repo_root = os.path.join(tmpdir, 'repo')
    projects_dir = os.path.join(repo_root, 'projects')
    poc_root = os.path.join(projects_dir, project_slug)
    sessions_dir = os.path.join(poc_root, '.sessions')
    worktrees_dir = os.path.join(poc_root, '.worktrees')
    manifest_path = os.path.join(repo_root, 'worktrees.json')

    os.makedirs(sessions_dir, exist_ok=True)
    os.makedirs(worktrees_dir, exist_ok=True)
    with open(manifest_path, 'w') as f:
        json.dump({'worktrees': []}, f)

    return {
        'repo_root': repo_root,
        'poc_root': poc_root,
        'projects_dir': projects_dir,
        'project_dir': poc_root,
        'sessions_dir': sessions_dir,
        'worktrees_dir': worktrees_dir,
        'manifest_path': manifest_path,
    }


def _make_session_on_disk(layout: dict, session_id: str, task_slug: str = 'test-task') -> dict:
    """Create session infra dir + worktree dir on disk, register in manifest."""
    short_id = session_id[-6:]
    worktree_name = f'session-{short_id}--{task_slug}'
    worktree_path = os.path.join(layout['worktrees_dir'], worktree_name)
    infra_dir = os.path.join(layout['sessions_dir'], session_id)

    os.makedirs(worktree_path, exist_ok=True)
    os.makedirs(infra_dir, exist_ok=True)
    for team in ('art', 'writing', 'editorial', 'research', 'coding'):
        os.makedirs(os.path.join(infra_dir, team), exist_ok=True)

    _register_worktree(layout['repo_root'], {
        'name': worktree_name,
        'path': worktree_path,
        'type': 'session',
        'team': '',
        'task': 'test task',
        'session_id': session_id,
        'status': 'active',
    })

    return {
        'infra_dir': infra_dir,
        'worktree_path': worktree_path,
        'worktree_name': worktree_name,
    }


def _make_dispatch_on_disk(layout: dict, session_info: dict,
                           team: str = 'coding', dispatch_id: str = '20260314-120000',
                           task_slug: str = 'dispatch-task') -> dict:
    """Create dispatch infra dir + worktree dir on disk. No manifest entry."""
    worktree_name = f'{team}-{dispatch_id[:6]}--{task_slug}'
    worktree_path = os.path.join(layout['worktrees_dir'], worktree_name)
    infra_dir = os.path.join(session_info['infra_dir'], team, dispatch_id)

    os.makedirs(worktree_path, exist_ok=True)
    os.makedirs(infra_dir, exist_ok=True)

    return {
        'infra_dir': infra_dir,
        'worktree_path': worktree_path,
        'worktree_name': worktree_name,
        'dispatch_id': dispatch_id,
        'team': team,
    }


def _make_mock_app(state_reader=None):
    """Create a mock app suitable for Textual Screen tests."""
    app = MagicMock()
    if state_reader:
        app.state_reader = state_reader
    return app


# ── Bug 1: Dispatch manifest written to wrong location ───────────────────────

class TestDispatchManifestLocation(unittest.TestCase):
    """create_dispatch_worktree must write to the MAIN repo manifest,
    not to worktrees.json inside the session worktree."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.layout = _make_repo_layout(self.tmpdir)

    def test_dispatch_manifest_goes_to_repo_root(self):
        """Dispatch entries must appear in {repo_root}/worktrees.json,
        not in {session_worktree}/worktrees.json."""
        session_info = _make_session_on_disk(self.layout, '20260314-120000')
        session_wt = session_info['worktree_path']

        async def fake_run_git(cwd, *args):
            pass

        async def fake_run_git_output(cwd, *args):
            # Simulate: git rev-parse --show-toplevel returns worktree root
            if 'rev-parse' in args and '--show-toplevel' in args:
                return session_wt + '\n'
            return '\n'

        with patch('projects.POC.orchestrator.worktree._run_git', new=fake_run_git), \
             patch('projects.POC.orchestrator.worktree._run_git_output', new=fake_run_git_output):
            _run(create_dispatch_worktree(
                team='coding',
                task='test dispatch task',
                session_worktree=session_wt,
                infra_dir=session_info['infra_dir'],
            ))

        # Dispatch entry MUST be in the main manifest
        with open(self.layout['manifest_path']) as f:
            main_manifest = json.load(f)

        dispatch_entries = [e for e in main_manifest['worktrees']
                           if e.get('type') == 'dispatch']
        self.assertGreater(
            len(dispatch_entries), 0,
            "Dispatch entry missing from main repo manifest — "
            "it was probably written to the session worktree's worktrees.json instead"
        )

        # Must NOT be in the session worktree's worktrees.json
        session_manifest_path = os.path.join(session_wt, 'worktrees.json')
        if os.path.exists(session_manifest_path):
            with open(session_manifest_path) as f:
                session_manifest = json.load(f)
            session_dispatch_entries = [e for e in session_manifest.get('worktrees', [])
                                        if e.get('type') == 'dispatch']
            self.assertEqual(
                len(session_dispatch_entries), 0,
                "Dispatch entry leaked to session worktree's worktrees.json"
            )


# ── Bug 2: StateReader dispatch worktree_path ────────────────────────────────

class TestStateReaderDispatchResolution(unittest.TestCase):
    """StateReader must populate dispatch worktree_path from the manifest."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.layout = _make_repo_layout(self.tmpdir)

    def test_dispatch_worktree_path_populated_from_manifest(self):
        """When manifest has a dispatch entry, DispatchState.worktree_path is populated."""
        session_id = '20260314-120000'
        session_info = _make_session_on_disk(self.layout, session_id)
        dispatch_info = _make_dispatch_on_disk(
            self.layout, session_info, team='coding', dispatch_id='20260314-120500',
        )

        # Register dispatch in the MAIN manifest
        _register_worktree(self.layout['repo_root'], {
            'name': dispatch_info['worktree_name'],
            'path': dispatch_info['worktree_path'],
            'type': 'dispatch',
            'team': 'coding',
            'task': 'test dispatch',
            'session_id': dispatch_info['dispatch_id'],
            'status': 'active',
        })

        reader = StateReader(self.layout['poc_root'], projects_dir=self.layout['projects_dir'])
        reader.reload()

        session = reader.find_session(session_id)
        self.assertIsNotNone(session)
        self.assertGreater(len(session.dispatches), 0, "No dispatches found")

        dispatch = session.dispatches[0]
        self.assertEqual(dispatch.worktree_path, dispatch_info['worktree_path'])

    def test_dispatch_worktree_path_empty_without_manifest(self):
        """Without manifest entry, worktree_path is empty (the bug state)."""
        session_id = '20260314-120000'
        session_info = _make_session_on_disk(self.layout, session_id)
        _make_dispatch_on_disk(
            self.layout, session_info, team='coding', dispatch_id='20260314-120500',
        )
        # NOT registering dispatch in manifest

        reader = StateReader(self.layout['poc_root'], projects_dir=self.layout['projects_dir'])
        reader.reload()

        session = reader.find_session(session_id)
        self.assertIsNotNone(session)
        self.assertGreater(len(session.dispatches), 0)

        dispatch = session.dispatches[0]
        self.assertEqual(dispatch.worktree_path, '')


# ── Bug 3: Session worktree path resolution ──────────────────────────────────

class TestSessionWorktreeResolution(unittest.TestCase):
    """_session_worktree() must find worktrees via manifest path or glob fallback.

    Tests the path resolution logic directly (extracted from drilldown.py)
    to avoid Textual app property complications.
    """

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.layout = _make_repo_layout(self.tmpdir)

    def _resolve_session_worktree(self, session: SessionState, reader: StateReader) -> str | None:
        """Replicate _session_worktree() logic without needing a real Screen."""
        import glob as _glob
        if not session:
            return None
        if session.worktree_path and os.path.isdir(session.worktree_path):
            return session.worktree_path
        proj = reader.find_project(session.project)
        if proj:
            short_id = session.session_id[-6:]
            pattern = os.path.join(proj.path, '.worktrees', f'session-{short_id}--*')
            matches = _glob.glob(pattern)
            if matches and os.path.isdir(matches[0]):
                return matches[0]
        return None

    def test_session_worktree_via_manifest_path(self):
        """When manifest has a valid path and directory exists, return it."""
        session_id = '20260314-130000'
        session_info = _make_session_on_disk(self.layout, session_id, task_slug='my-task')

        reader = StateReader(self.layout['poc_root'], projects_dir=self.layout['projects_dir'])
        reader.reload()
        session = reader.find_session(session_id)

        result = self._resolve_session_worktree(session, reader)
        self.assertIsNotNone(result, "_session_worktree() should find the worktree via manifest")
        self.assertEqual(result, session_info['worktree_path'])

    def test_session_worktree_glob_fallback(self):
        """When manifest path is empty but worktree exists with conventional naming,
        glob fallback should find it."""
        session_id = '20260314-140000'
        session_info = _make_session_on_disk(self.layout, session_id, task_slug='glob-test')

        # Clear the manifest path
        with open(self.layout['manifest_path']) as f:
            manifest = json.load(f)
        for entry in manifest['worktrees']:
            if entry.get('session_id') == session_id:
                entry['path'] = ''
        with open(self.layout['manifest_path'], 'w') as f:
            json.dump(manifest, f)

        reader = StateReader(self.layout['poc_root'], projects_dir=self.layout['projects_dir'])
        reader.reload()
        session = reader.find_session(session_id)

        result = self._resolve_session_worktree(session, reader)
        self.assertIsNotNone(
            result,
            f"Glob fallback should find session-{session_id[-6:]}--* "
            f"in {self.layout['worktrees_dir']}"
        )
        self.assertEqual(result, session_info['worktree_path'])


# ── Bug 4: Action handlers must not silently fail ─────────────────────────────

class TestActionHandlerFeedback(unittest.TestCase):
    """Action handlers should notify user when worktree is not found."""

    def test_action_open_finder_calls_open_file_when_path_exists(self):
        """When worktree exists, action_open_finder must call open_file."""
        tmpdir = tempfile.mkdtemp()
        layout = _make_repo_layout(tmpdir)
        session_id = '20260314-150000'
        session_info = _make_session_on_disk(layout, session_id)

        from projects.POC.tui.screens.drilldown import DrilldownScreen

        reader = StateReader(layout['poc_root'], projects_dir=layout['projects_dir'])
        reader.reload()

        screen = DrilldownScreen.__new__(DrilldownScreen)
        screen._session = reader.find_session(session_id)

        # Use PropertyMock to override the class-level 'app' property
        mock_app = _make_mock_app(reader)
        with patch.object(type(screen), 'app', new_callable=PropertyMock, return_value=mock_app), \
             patch('projects.POC.tui.screens.drilldown.open_file') as mock_open:
            screen.action_open_finder()
            mock_open.assert_called_once_with(session_info['worktree_path'])

    def test_action_open_finder_notifies_when_path_missing(self):
        """When worktree not found, action_open_finder should notify user."""
        from projects.POC.tui.screens.drilldown import DrilldownScreen

        screen = DrilldownScreen.__new__(DrilldownScreen)
        screen._session = None
        screen.notify = MagicMock()

        mock_app = _make_mock_app()
        with patch.object(type(screen), 'app', new_callable=PropertyMock, return_value=mock_app), \
             patch('projects.POC.tui.screens.drilldown.open_file') as mock_open:
            screen.action_open_finder()
            mock_open.assert_not_called()
            screen.notify.assert_called_once()

    def test_action_open_vscode_notifies_when_path_missing(self):
        """When worktree not found, action_open_vscode should notify user."""
        from projects.POC.tui.screens.drilldown import DrilldownScreen

        screen = DrilldownScreen.__new__(DrilldownScreen)
        screen._session = None
        screen.notify = MagicMock()

        mock_app = _make_mock_app()
        with patch.object(type(screen), 'app', new_callable=PropertyMock, return_value=mock_app), \
             patch('subprocess.Popen') as mock_popen:
            screen.action_open_vscode()
            mock_popen.assert_not_called()
            screen.notify.assert_called_once()


# ── Bug 5: Dispatch drilldown action handlers ─────────────────────────────────

class TestDispatchDrilldownActions(unittest.TestCase):
    """DispatchDrilldownScreen action handlers must not silently fail."""

    def test_action_open_finder_notifies_when_path_missing(self):
        """Dispatch open_finder should notify when worktree not found."""
        from projects.POC.tui.screens.dispatch_drilldown import DispatchDrilldownScreen

        dispatch = DispatchState(
            team='coding', worktree_name='', worktree_path='',
            task='test', status='active', infra_dir='',
        )
        parent_session = SessionState(
            project='POC', session_id='20260314-120000',
            worktree_name='', worktree_path='',
            task='test', status='active', infra_dir='',
        )

        screen = DispatchDrilldownScreen.__new__(DispatchDrilldownScreen)
        screen._dispatch = dispatch
        screen._parent_session = parent_session
        screen.notify = MagicMock()

        mock_app = _make_mock_app()
        with patch.object(type(screen), 'app', new_callable=PropertyMock, return_value=mock_app), \
             patch('projects.POC.tui.screens.dispatch_drilldown.open_file') as mock_open:
            screen.action_open_finder()
            mock_open.assert_not_called()
            screen.notify.assert_called_once()


if __name__ == '__main__':
    unittest.main()
