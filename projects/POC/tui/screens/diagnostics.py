"""Diagnostics screen — running processes, worktree health, recovery actions."""
from __future__ import annotations

import os
import subprocess
import time

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header, Static


def _human_age(seconds: int) -> str:
    if seconds < 0:
        return '\u2014'
    if seconds < 60:
        return f'{seconds}s'
    if seconds < 3600:
        return f'{seconds // 60}m'
    return f'{seconds // 3600}h{seconds % 3600 // 60}m'


def _find_poc_processes() -> list[dict]:
    """Find all POC-related processes via pgrep."""
    processes = []

    # Orchestrator scripts
    try:
        result = subprocess.run(
            ['pgrep', '-f', r'(run\.sh|intent\.sh|plan-execute\.sh|dispatch\.sh)'],
            capture_output=True, text=True, timeout=5,
        )
        for pid_str in result.stdout.strip().split('\n'):
            pid_str = pid_str.strip()
            if pid_str:
                info = _get_process_info(int(pid_str))
                if info:
                    processes.append(info)
    except (subprocess.TimeoutExpired, ValueError):
        pass

    # Claude agent processes (running in POC worktrees)
    try:
        result = subprocess.run(
            ['pgrep', '-f', r'claude.*\.worktrees/'],
            capture_output=True, text=True, timeout=5,
        )
        seen_pids = {p['pid'] for p in processes}
        for pid_str in result.stdout.strip().split('\n'):
            pid_str = pid_str.strip()
            if pid_str:
                pid = int(pid_str)
                if pid not in seen_pids:
                    info = _get_process_info(pid)
                    if info:
                        processes.append(info)
    except (subprocess.TimeoutExpired, ValueError):
        pass

    return processes


def _get_process_info(pid: int) -> dict | None:
    """Get process info: command, CPU, elapsed, CWD."""
    try:
        ps_result = subprocess.run(
            ['ps', '-o', 'command=,pcpu=,etime=', '-p', str(pid)],
            capture_output=True, text=True, timeout=3,
        )
        if ps_result.returncode != 0:
            return None

        line = ps_result.stdout.strip()
        if not line:
            return None

        # Parse ps output — format varies, use last two fields as cpu and elapsed
        parts = line.rsplit(None, 2)
        if len(parts) >= 3:
            command, cpu, elapsed = parts[0], parts[1], parts[2]
        elif len(parts) == 2:
            command, cpu, elapsed = parts[0], parts[1], '?'
        else:
            command, cpu, elapsed = line, '?', '?'

        # Get CWD via lsof
        cwd = ''
        try:
            lsof_result = subprocess.run(
                ['lsof', '-a', '-p', str(pid), '-d', 'cwd', '-Fn'],
                capture_output=True, text=True, timeout=3,
            )
            for lsof_line in lsof_result.stdout.split('\n'):
                if lsof_line.startswith('n'):
                    cwd = lsof_line[1:]
                    break
        except subprocess.TimeoutExpired:
            pass

        # Shorten CWD for display
        cwd_short = cwd
        if '.worktrees/' in cwd:
            cwd_short = '.../' + cwd.split('.worktrees/')[-1]
        elif '/POC' in cwd:
            cwd_short = '.../POC'

        return {
            'pid': pid,
            'command': command,
            'cpu': cpu.strip(),
            'elapsed': elapsed.strip(),
            'cwd': cwd_short,
        }
    except (subprocess.TimeoutExpired, ValueError, OSError):
        return None


def _check_worktree_health(state_reader) -> list[dict]:
    """Check health of all worktrees."""
    health = []
    now = time.time()

    for session in state_reader.sessions:
        # Session worktree
        h = _check_single_worktree(session.worktree_name, session.worktree_path,
                                    session.status, session.stream_age_seconds, now)
        health.append(h)

        # Dispatch worktrees
        for d in session.dispatches:
            h = _check_single_worktree(d.worktree_name, d.worktree_path,
                                        d.status, d.stream_age_seconds, now)
            if d.infra_dir and d.is_running:
                h['has_running'] = True
            health.append(h)

    return health


def _check_single_worktree(name: str, path: str, status: str,
                            stream_age: int, now: float) -> dict:
    """Check health of a single worktree."""
    exists = os.path.isdir(path) if path else False
    issues = []

    if status == 'active' and not exists:
        issues.append('path missing')
    if status == 'active' and stream_age > 3600:
        issues.append(f'stream stale ({_human_age(stream_age)})')
    if status == 'failed':
        # Check for .running sentinel that shouldn't be there
        if path and os.path.exists(os.path.join(path, '.running')):
            issues.append('.running stale')

    return {
        'name': name[:40],
        'status': status,
        'stream_age': stream_age,
        'exists': exists,
        'issues': issues,
        'path': path,
        'has_running': False,
    }


class DiagnosticsScreen(Screen):
    """Process and worktree health diagnostics."""

    BINDINGS = [
        Binding('escape', 'go_back', 'Back', show=True),
        Binding('c', 'clean_stale', 'Clean Stale', show=True),
        Binding('r', 'reap_orphans', 'Reap Orphans', show=True),
        Binding('f5', 'refresh', 'Refresh', show=True),
    ]

    def compose(self) -> ComposeResult:
        yield Header()
        yield Vertical(
            Static('PROCESSES', classes='section-title'),
            DataTable(id='process-table'),
            Static('WORKTREE HEALTH', classes='section-title'),
            Static('', id='health-panel'),
        )
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one('#process-table', DataTable)
        table.add_column('PID', width=8)
        table.add_column('Command')
        table.add_column('CPU', width=6)
        table.add_column('Elapsed', width=10)
        table.add_column('Working Dir', width=30)
        self._refresh_data()

    def _refresh_data(self) -> None:
        # Processes
        table = self.query_one('#process-table', DataTable)
        table.clear()

        processes = _find_poc_processes()
        for p in processes:
            table.add_row(
                str(p['pid']),
                p['command'],
                p['cpu'],
                p['elapsed'],
                p['cwd'],
            )

        if not processes:
            table.add_row('', '(no processes found)', '', '', '')

        # Worktree health
        health_panel = self.query_one('#health-panel', Static)
        health = _check_worktree_health(self.app.state_reader)

        lines = []
        for h in health:
            if h['issues']:
                icon = '\u26a0'  # warning
                style = '[yellow]'
                detail = ', '.join(h['issues'])
                lines.append(f'  {style}{icon} {h["name"]:<42} {h["status"]:<10} {detail}[/]')
            elif h['status'] == 'active':
                icon = '\u2713'
                lines.append(f'  [green]{icon}[/green] {h["name"]:<42} {h["status"]:<10} stream: {_human_age(h["stream_age"])}')
            elif h['status'] == 'complete':
                lines.append(f'  [dim]\u2713 {h["name"]:<42} {h["status"]}[/dim]')
            elif h['status'] == 'failed':
                icon = '\u2717'
                lines.append(f'  [red]{icon}[/red] {h["name"]:<42} {h["status"]}')

        if not lines:
            lines.append('  (no worktrees)')

        health_panel.update('\n'.join(lines))

    def periodic_refresh(self) -> None:
        self._refresh_data()

    def action_go_back(self) -> None:
        self.app.pop_screen()

    def action_clean_stale(self) -> None:
        """Remove stale .running sentinel files."""
        health = _check_worktree_health(self.app.state_reader)
        cleaned = 0
        for h in health:
            if '.running stale' in ' '.join(h.get('issues', [])):
                running_path = os.path.join(h['path'], '.running')
                try:
                    os.unlink(running_path)
                    cleaned += 1
                except OSError:
                    pass
        self._refresh_data()

    def action_reap_orphans(self) -> None:
        """Run ops/reap.sh to clean orphaned worktrees."""
        reap_script = os.path.join(self.app.poc_root, 'ops', 'reap.sh')
        if os.path.exists(reap_script):
            subprocess.Popen(['bash', reap_script])
        self._refresh_data()

    def action_refresh(self) -> None:
        self._refresh_data()
