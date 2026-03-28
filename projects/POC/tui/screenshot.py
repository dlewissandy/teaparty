#!/usr/bin/env python3
"""Capture a screenshot of the TUI dashboard for documentation.

Creates synthetic session data and renders the dashboard to an SVG file
using Textual's built-in export_screenshot().

Usage:
    uv run python -m projects.POC.tui.screenshot [output_path]

Default output: docs/images/tui-dashboard.svg
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path


# ── Synthetic state data ──────────────────────────────────────────────────────

@dataclass
class MockDispatch:
    team: str = ''
    dispatch_id: str = ''
    status: str = 'complete'
    task: str = ''
    exit_code: int = 0
    duration_seconds: int = 0
    cfa_state: str = ''


@dataclass
class MockSession:
    session_id: str = ''
    status: str = 'active'
    cfa_phase: str = ''
    cfa_state: str = ''
    task: str = ''
    needs_input: bool = False
    is_orphaned: bool = False
    stream_age_seconds: int = 0
    duration_seconds: int = 0
    dispatches: list = field(default_factory=list)


@dataclass
class MockProject:
    slug: str = ''
    sessions: list = field(default_factory=list)
    active_count: int = 0
    attention_count: int = 0


class MockStateReader:
    """Provides synthetic data for the dashboard screenshot."""

    def __init__(self):
        self.projects = [
            MockProject(
                slug='teaparty',
                sessions=[
                    MockSession(
                        session_id='20260314-091522',
                        status='active',
                        cfa_phase='execution',
                        cfa_state='WORK_IN_PROGRESS',
                        task='Implement skill lookup routing for the planning phase — System 1 fast path that checks skill library before cold-start planning',
                        needs_input=False,
                        stream_age_seconds=45,
                        duration_seconds=1847,
                        dispatches=[
                            MockDispatch(team='coding', dispatch_id='20260314-092001', status='complete', duration_seconds=312),
                            MockDispatch(team='coding', dispatch_id='20260314-093415', status='active', duration_seconds=180),
                        ],
                    ),
                    MockSession(
                        session_id='20260314-083012',
                        status='active',
                        cfa_phase='planning',
                        cfa_state='PLAN_ASSERT',
                        task='Add file locking to all shared-file write paths using filelock library',
                        needs_input=True,
                        stream_age_seconds=623,
                        duration_seconds=3214,
                    ),
                    MockSession(
                        session_id='20260313-211547',
                        status='complete',
                        cfa_phase='',
                        cfa_state='COMPLETED_WORK',
                        task='Wire track_reinforcement.py into extract_learnings() at session end',
                        stream_age_seconds=38412,
                        duration_seconds=2156,
                    ),
                    MockSession(
                        session_id='20260313-184205',
                        status='complete',
                        cfa_phase='',
                        cfa_state='COMPLETED_WORK',
                        task='Fix Finder/VSCode buttons in TUI drilldown screens',
                        stream_age_seconds=52800,
                        duration_seconds=945,
                    ),
                ],
                active_count=2,
                attention_count=1,
            ),
            MockProject(
                slug='hierarchical-memory-paper',
                sessions=[
                    MockSession(
                        session_id='20260312-155430',
                        status='complete',
                        cfa_phase='',
                        cfa_state='COMPLETED_WORK',
                        task='Draft related work section covering OpenClaw and FadeMem architectures',
                        stream_age_seconds=142000,
                        duration_seconds=4521,
                    ),
                ],
                active_count=0,
                attention_count=0,
            ),
            MockProject(
                slug='agentic-memory',
                sessions=[],
                active_count=0,
                attention_count=0,
            ),
        ]

    def reload(self):
        pass

    def find_project(self, slug):
        for p in self.projects:
            if p.slug == slug:
                return p
        return None

    def find_session(self, session_id):
        for p in self.projects:
            for s in p.sessions:
                if s.session_id == session_id:
                    return s
        return None


# ── Screenshot app ────────────────────────────────────────────────────────────

from textual.app import App


class ScreenshotApp(App):
    """Minimal app that renders the dashboard with mock data and saves a screenshot."""

    TITLE = 'TeaParty'
    CSS_PATH = 'styles.tcss'

    def __init__(self, output_path: str):
        super().__init__()
        self.output_path = output_path
        self.poc_root = str(Path(__file__).resolve().parent.parent)
        self.projects_dir = os.path.dirname(self.poc_root)
        self.state_reader = MockStateReader()
        self._in_process: dict = {}

    def has_in_process(self, session_id: str) -> bool:
        return False

    def on_mount(self) -> None:
        from projects.POC.tui.screens.management_dashboard import ManagementDashboard
        self.push_screen(ManagementDashboard())
        # Give the screen time to render, then capture
        self.set_timer(0.5, self._capture)

    def _capture(self) -> None:
        path = self.save_screenshot(self.output_path)
        print(f'Screenshot saved to: {path}', file=sys.stderr)
        self.exit()


def main():
    output = sys.argv[1] if len(sys.argv) > 1 else str(
        Path(__file__).resolve().parent.parent.parent.parent / 'docs' / 'images' / 'tui-dashboard.svg'
    )
    Path(output).parent.mkdir(parents=True, exist_ok=True)
    app = ScreenshotApp(output)
    app.run(headless=True)


if __name__ == '__main__':
    main()
