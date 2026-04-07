"""Reads project dirs, session state files, and .heartbeat/.running sentinels.

Produces a unified snapshot of all projects/sessions/dispatches for the
bridge server.
Issue #149: migrated from .running to .heartbeat with backward compat fallback.
"""
import json
import os
import time
from dataclasses import dataclass, field
from datetime import datetime

from orchestrator.heartbeat import (
    _ALIVE_THRESHOLD,
    _DEAD_THRESHOLD,
    _get_cached_boot_time,
    _heartbeat_three_state,
    _running_file_is_stale,
    _running_pid_is_dead,
    is_heartbeat_stale,
    read_heartbeat,
)


def _check_fifo_has_reader(infra_dir: str) -> bool:
    """Return True if a live reader is blocking on the response FIFO.

    Opens the FIFO in non-blocking write mode: succeeds only if another
    process already has the read end open (i.e. the session is alive).
    FIFO is the legacy shell-based IPC path; the message bus is primary.
    """
    import errno
    fifo_path = os.path.join(infra_dir, '.input-response.fifo')
    if not os.path.exists(fifo_path):
        return False
    try:
        fd = os.open(fifo_path, os.O_WRONLY | os.O_NONBLOCK)
        os.close(fd)
        return True
    except OSError as e:
        if e.errno == errno.ENXIO:
            return False
        return False


def _is_heartbeat_alive(infra_dir: str) -> bool:
    """Return True if the .heartbeat in infra_dir indicates a live process.

    Issue #149: Checks .heartbeat first, falls back to .running.
    A terminal heartbeat (completed/withdrawn) returns False (not alive, but
    not orphaned either — it finished cleanly).
    """
    hb_path = os.path.join(infra_dir, '.heartbeat')
    if os.path.exists(hb_path):
        try:
            data = read_heartbeat(hb_path)
            status = data.get('status', '')
            if status in ('completed', 'withdrawn'):
                return False  # Terminal — not alive, not orphaned
            return not is_heartbeat_stale(hb_path)
        except Exception:
            return False

    # Fallback to .running
    running_path = os.path.join(infra_dir, '.running')
    if os.path.exists(running_path):
        return not _running_file_is_stale(running_path) and not _running_pid_is_dead(running_path)
    return False


def _read_cost_sidecar(infra_dir: str) -> float:
    """Read the running cost total from the engine's .cost sidecar file."""
    if not infra_dir:
        return 0.0
    cost_path = os.path.join(infra_dir, '.cost')
    try:
        with open(cost_path) as f:
            return float(f.read().strip())
    except (FileNotFoundError, ValueError, OSError):
        return 0.0


def _is_heartbeat_terminal(infra_dir: str) -> bool:
    """Return True if the .heartbeat shows a terminal status (completed/withdrawn).

    Issue #149: A terminal heartbeat means the dispatch finished cleanly.
    """
    hb_path = os.path.join(infra_dir, '.heartbeat')
    if os.path.exists(hb_path):
        try:
            data = read_heartbeat(hb_path)
            return data.get('status', '') in ('completed', 'withdrawn')
        except Exception:
            pass
    return False


# States where the human needs to act
HUMAN_ACTOR_STATES = frozenset([
    'INTENT_ASSERT', 'INTENT_ESCALATE', 'INTENT_QUESTION',
    'PLAN_ASSERT', 'PLANNING_ESCALATE', 'PLANNING_QUESTION',
    'TASK_ASSERT', 'WORK_ASSERT',
])


@dataclass
class DispatchState:
    """State of a single team dispatch."""
    team: str
    worktree_name: str
    worktree_path: str
    task: str
    status: str                  # active, complete, failed
    cfa_state: str = ''
    cfa_phase: str = ''
    is_running: bool = False
    infra_dir: str = ''
    stream_age_seconds: int = -1
    needs_input: bool = False
    heartbeat_status: str = ''   # alive, stale, dead


@dataclass
class SessionState:
    """Unified state of a session and its dispatches."""
    project: str                     # Parent project slug
    session_id: str
    worktree_name: str
    worktree_path: str
    task: str
    status: str                      # active, complete, failed
    cfa_phase: str = ''
    cfa_state: str = ''
    cfa_actor: str = ''
    needs_input: bool = False
    is_orphaned: bool = False
    dispatches: list = field(default_factory=list)
    stream_age_seconds: int = -1
    duration_seconds: int = -1
    infra_dir: str = ''
    files_changed: list = field(default_factory=list)
    heartbeat_status: str = ''       # alive, stale, dead
    total_cost_usd: float = 0.0      # cumulative cost from cost ledger
    backtrack_count: int = 0         # cross-phase backtracks from .cfa-state.json

    @property
    def escalation_count(self) -> int:
        """Total unresolved escalations in this session's subtree.

        Sums the session's own escalation (if needs_input) plus all
        dispatch-level escalations.
        """
        count = 1 if self.needs_input else 0
        count += sum(1 for d in self.dispatches if d.needs_input)
        return count


def _parse_session_ts(session_id: str) -> float:
    """Parse a session timestamp like '20260311-184909' to Unix epoch."""
    try:
        dt = datetime.strptime(session_id[:15], '%Y%m%d-%H%M%S')
        return dt.timestamp()
    except (ValueError, IndexError):
        return 0.0


@dataclass
class ProjectState:
    """State of a project and its sessions."""
    slug: str                        # "POC", "hierarchical-memory-paper"
    path: str                        # projects/{slug}/
    name: str = ''                   # display name from registry (e.g. "TeaParty")
    sessions: list = field(default_factory=list)
    active_count: int = 0
    attention_count: int = 0


class StateReader:
    """Reads all project state files and produces unified project/session list.

    Args:
        repo_root: Path to the repo root.
        projects_dir: Optional path to scan for project subdirs (test/legacy use).
            When None, uses registry-based discovery from teaparty_home.
        teaparty_home: Path to .teaparty config dir for registry-based discovery.
        in_process_checker: Optional callback (session_id) -> bool.
    """

    def __init__(self, repo_root: str, projects_dir: str | None = None,
                 teaparty_home: str | None = None,
                 in_process_checker=None):
        self.repo_root = repo_root
        self.poc_root = repo_root  # backward-compat alias
        self.projects_dir = projects_dir
        self.teaparty_home = teaparty_home
        self._projects: list[ProjectState] = []
        self._in_process_checker = in_process_checker

    @property
    def projects(self) -> list[ProjectState]:
        return self._projects

    @property
    def sessions(self) -> list[SessionState]:
        """Flat list of all sessions across all projects."""
        result = []
        for proj in self._projects:
            result.extend(proj.sessions)
        return result

    def reload(self) -> list[ProjectState]:
        """Read all state files and produce unified project/session list."""
        now = time.time()

        # Collect (slug, proj_path, name) tuples from registry or directory scan
        project_paths: list[tuple[str, str, str]] = []
        if self.teaparty_home:
            from orchestrator.config_reader import load_management_team, discover_projects
            team = load_management_team(teaparty_home=self.teaparty_home)
            for entry in discover_projects(team):
                slug = os.path.basename(entry['path'].rstrip('/'))
                project_paths.append((slug, entry['path'], entry.get('name', slug)))
            project_paths.sort(key=lambda t: t[0])
        elif self.projects_dir is not None:
            try:
                for slug in sorted(os.listdir(self.projects_dir)):
                    proj_path = os.path.join(self.projects_dir, slug)
                    if os.path.isdir(os.path.join(proj_path, '.teaparty', 'jobs')):
                        project_paths.append((slug, proj_path, slug))
            except OSError:
                pass
        else:
            raise ValueError(
                'StateReader requires either teaparty_home (registry mode) '
                'or projects_dir (directory scan mode)'
            )

        projects = []
        for slug, proj_path, name in project_paths:
            proj_sessions = self._scan_project_jobs(slug, proj_path, now)

            active = sum(1 for s in proj_sessions if s.status == 'active')
            attention = sum(s.escalation_count for s in proj_sessions)

            projects.append(ProjectState(
                slug=slug,
                path=proj_path,
                name=name,
                sessions=proj_sessions,
                active_count=active,
                attention_count=attention,
            ))

        # Sort: most recently active projects first
        def _newest_session_ts(p):
            if p.sessions:
                return max(s.session_id for s in p.sessions)
            return ''
        projects.sort(key=lambda p: _newest_session_ts(p), reverse=True)

        self._projects = projects
        return projects

    def _scan_project_jobs(self, slug: str, proj_path: str,
                           now: float) -> list[SessionState]:
        """Scan .teaparty/jobs/ for a project and build SessionState list."""
        jobs_dir = os.path.join(proj_path, '.teaparty', 'jobs')
        if not os.path.isdir(jobs_dir):
            return []

        sessions = []
        try:
            job_dirs = sorted(os.listdir(jobs_dir), reverse=True)
        except OSError:
            return sessions

        for job_name in job_dirs:
            job_dir = os.path.join(jobs_dir, job_name)
            job_json = os.path.join(job_dir, 'job.json')
            if not os.path.isfile(job_json):
                continue

            try:
                with open(job_json) as f:
                    job_state = json.load(f)
            except (json.JSONDecodeError, OSError):
                continue

            job_id = job_state.get('job_id', '')
            session_id = job_id[4:] if job_id.startswith('job-') else job_id

            # Build worktree entry from job state
            worktree_path = os.path.join(job_dir, 'worktree')
            entry = {
                'name': job_name,
                'path': worktree_path if os.path.isdir(worktree_path) else '',
                'type': 'session',
                'status': job_state.get('status', 'active'),
                'task': '',
            }

            # Find tasks (dispatches) under the job
            dispatches = self._find_job_tasks(job_dir, now)

            sess = self._build_session(slug, session_id, job_dir, entry, dispatches, now)
            sessions.append(sess)

        return sessions

    def _find_job_tasks(self, job_dir: str, now: float) -> list[dict]:
        """Find task entries within a job directory."""
        tasks_dir = os.path.join(job_dir, 'tasks')
        if not os.path.isdir(tasks_dir):
            return []

        matched = []
        try:
            for task_name in sorted(os.listdir(tasks_dir)):
                task_dir = os.path.join(tasks_dir, task_name)
                task_json = os.path.join(task_dir, 'task.json')
                if not os.path.isfile(task_json):
                    continue

                try:
                    with open(task_json) as f:
                        task_state = json.load(f)
                except (json.JSONDecodeError, OSError):
                    continue

                task_id = task_state.get('task_id', '')
                dispatch_id = task_id[5:] if task_id.startswith('task-') else task_id

                dispatch_alive = _is_heartbeat_alive(task_dir)
                status = task_state.get('status', 'active')
                if status == 'active' and not dispatch_alive:
                    status = 'complete'

                matched.append({
                    'name': task_name,
                    'path': os.path.join(task_dir, 'worktree'),
                    'type': 'dispatch',
                    'team': task_state.get('team', ''),
                    'task': '',
                    'session_id': dispatch_id,
                    'status': status,
                    '_infra_dir': task_dir,
                })
        except OSError:
            pass

        return matched

    def _build_session(self, project: str, session_id: str,
                        infra_dir: str, entry: dict,
                        dispatches: list, now: float) -> SessionState:
        # Read CfA state
        cfa = self._read_cfa(os.path.join(infra_dir, '.cfa-state.json'))
        cfa_phase = cfa.get('phase', '')
        cfa_state = cfa.get('state', '')
        cfa_actor = cfa.get('actor', '')
        backtrack_count = cfa.get('backtrack_count', 0)

        # Determine if human input needed
        needs_input = cfa_state in HUMAN_ACTOR_STATES
        if os.path.exists(os.path.join(infra_dir, '.input-request.json')):
            needs_input = True

        # Orphan detection: no live process is driving this non-terminal session.
        # Issue #149: check .heartbeat first, fall back to .running.
        is_orphaned = False
        if cfa_state not in ('COMPLETED_WORK', 'WITHDRAWN', ''):
            if _is_heartbeat_terminal(infra_dir):
                # Terminal heartbeat — not orphaned, just finished
                is_orphaned = False
            elif _is_heartbeat_alive(infra_dir):
                # Live heartbeat or .running — check in-process and FIFO
                is_orphaned = False
                if self._in_process_checker is not None:
                    # Read PID from heartbeat or .running
                    running_pid = -1
                    hb_path = os.path.join(infra_dir, '.heartbeat')
                    running_path = os.path.join(infra_dir, '.running')
                    if os.path.exists(hb_path):
                        try:
                            running_pid = read_heartbeat(hb_path).get('pid', -1)
                        except Exception:
                            pass
                    elif os.path.exists(running_path):
                        try:
                            with open(running_path) as _f:
                                running_pid = int(_f.read().strip())
                        except (ValueError, OSError):
                            pass
                    if running_pid == os.getpid():
                        if not self._in_process_checker(session_id):
                            is_orphaned = True
                if not is_orphaned:
                    fifo_path = os.path.join(infra_dir, '.input-response.fifo')
                    if cfa_state in HUMAN_ACTOR_STATES and os.path.exists(fifo_path):
                        is_orphaned = not _check_fifo_has_reader(infra_dir)
            else:
                # No live heartbeat or .running — orphaned
                is_orphaned = True

        # Stream age
        stream_age = self._stream_age(infra_dir, now)

        # Build dispatch states
        dispatch_states = [self._build_dispatch(d, now) for d in dispatches]

        # Infer status from CfA or entry
        status = entry.get('status', '')
        if not status:
            if cfa_state in ('COMPLETED_WORK', 'WITHDRAWN'):
                status = 'complete'
            elif cfa_state:
                status = 'active'
            elif stream_age >= 0:
                status = 'active'
            else:
                status = 'complete'

        # Duration: wall-clock time from session start to now (active) or
        # to last activity (complete/failed/withdrawn)
        start_epoch = _parse_session_ts(session_id)
        if start_epoch > 0:
            if status in ('complete', 'failed'):
                if stream_age >= 0:
                    # End at last stream activity
                    duration = max(0, int(now - stream_age - start_epoch))
                else:
                    duration = -1  # no stream files — unknown end time
            else:
                duration = max(0, int(now - start_epoch))
        else:
            duration = -1

        # Task: prefer PROMPT.txt (canonical full prompt), fall back to
        # entry dict, then INTENT.md title
        task = self._read_prompt(infra_dir) or entry.get('task', '')
        if not task:
            task = self._read_intent(infra_dir)

        # Issue #254: session-level heartbeat three-state
        heartbeat_status = _heartbeat_three_state(infra_dir)

        return SessionState(
            project=project,
            session_id=session_id,
            worktree_name=entry.get('name', ''),
            worktree_path=entry.get('path', ''),
            task=task,
            status=status,
            cfa_phase=cfa_phase,
            cfa_state=cfa_state,
            cfa_actor=cfa_actor,
            needs_input=needs_input,
            is_orphaned=is_orphaned,
            dispatches=dispatch_states,
            stream_age_seconds=stream_age,
            duration_seconds=duration,
            infra_dir=infra_dir,
            heartbeat_status=heartbeat_status,
            total_cost_usd=_read_cost_sidecar(infra_dir),
            backtrack_count=backtrack_count,
        )

    def _build_dispatch(self, entry: dict, now: float) -> DispatchState:
        team = entry.get('team', '')
        infra_dir = entry.get('_infra_dir', '')
        is_running = False
        cfa_state = ''
        cfa_phase = ''
        stream_age = -1
        needs_input = False
        heartbeat_status = ''

        if infra_dir:
            # Issue #149: use heartbeat for liveness, fallback to .running
            is_running = _is_heartbeat_alive(infra_dir)
            cfa = self._read_cfa(os.path.join(infra_dir, '.cfa-state.json'))
            cfa_state = cfa.get('state', '')
            cfa_phase = cfa.get('phase', '')
            stream_age = self._stream_age(infra_dir, now)

            # Issue #254: detect escalations at dispatch level
            needs_input = cfa_state in HUMAN_ACTOR_STATES
            if os.path.exists(os.path.join(infra_dir, '.input-request.json')):
                needs_input = True

            # Issue #254: heartbeat three-state indicator
            heartbeat_status = _heartbeat_three_state(infra_dir)

        # Derive status from actual PID liveness, not just the entry dict.
        # A dispatch whose process is dead is complete, not active.
        status = entry.get('status', 'active')
        if status == 'active' and infra_dir and not is_running:
            status = 'complete'

        return DispatchState(
            team=team,
            worktree_name=entry.get('name', ''),
            worktree_path=entry.get('path', ''),
            task=entry.get('task', ''),
            status=status,
            cfa_state=cfa_state,
            cfa_phase=cfa_phase,
            is_running=is_running,
            infra_dir=infra_dir,
            stream_age_seconds=stream_age,
            needs_input=needs_input,
            heartbeat_status=heartbeat_status,
        )

    def _read_prompt(self, infra_dir: str) -> str:
        """Read the full original prompt from PROMPT.txt."""
        prompt_path = os.path.join(infra_dir, 'PROMPT.txt')
        try:
            with open(prompt_path) as f:
                return f.read().strip()
        except (FileNotFoundError, OSError):
            return ''

    def _read_intent(self, infra_dir: str) -> str:
        """Read the session task from INTENT.md title or session.log."""
        # Try INTENT.md title first
        intent_path = os.path.join(infra_dir, 'INTENT.md')
        try:
            with open(intent_path) as f:
                for line in f:
                    line = line.strip()
                    if line.startswith('# INTENT:'):
                        return line[len('# INTENT:'):].strip()
        except (FileNotFoundError, OSError):
            pass
        # Fall back to session.log Task: line
        log_path = os.path.join(infra_dir, 'session.log')
        try:
            with open(log_path) as f:
                first = f.readline()
                if 'Task: ' in first:
                    return first.split('Task: ', 1)[1].strip()
        except (FileNotFoundError, OSError):
            pass
        return ''

    def _read_cfa(self, path: str) -> dict:
        try:
            with open(path) as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def _stream_age(self, infra_dir: str, now: float) -> int:
        best_mtime = 0
        for name in ('.intent-stream.jsonl', '.plan-stream.jsonl', '.exec-stream.jsonl'):
            path = os.path.join(infra_dir, name)
            try:
                mt = os.path.getmtime(path)
                if mt > best_mtime:
                    best_mtime = mt
            except OSError:
                continue

        if best_mtime == 0:
            return -1
        return int(now - best_mtime)

    def find_session(self, session_id: str) -> SessionState | None:
        """Find a session by its ID across all projects."""
        for proj in self._projects:
            for s in proj.sessions:
                if s.session_id == session_id:
                    return s
        return None

    def find_project(self, slug: str) -> ProjectState | None:
        """Find a project by slug."""
        for p in self._projects:
            if p.slug == slug:
                return p
        return None

    def active_stream_files(self, session_id: str) -> list[str]:
        """Return paths to all JSONL stream files for a session."""
        session = self.find_session(session_id)
        if not session:
            return []

        files = []
        infra = session.infra_dir

        for name in ('.intent-stream.jsonl', '.plan-stream.jsonl', '.exec-stream.jsonl'):
            path = os.path.join(infra, name)
            if os.path.exists(path):
                files.append(path)

        for d in session.dispatches:
            if d.infra_dir and d.status == 'active':
                for name in ('.exec-stream.jsonl', '.plan-stream.jsonl'):
                    path = os.path.join(d.infra_dir, name)
                    if os.path.exists(path):
                        files.append(path)

        return files
