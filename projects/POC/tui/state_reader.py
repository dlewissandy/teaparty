"""Reads project dirs, session state files, and .running sentinels.

Produces a unified snapshot of all projects/sessions/dispatches for the TUI.
"""
import json
import os
import time
from dataclasses import dataclass, field


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
    dispatches: list = field(default_factory=list)
    stream_age_seconds: int = -1
    infra_dir: str = ''
    files_changed: list = field(default_factory=list)


@dataclass
class ProjectState:
    """State of a project and its sessions."""
    slug: str                        # "POC", "hierarchical-memory-paper"
    path: str                        # projects/{slug}/
    sessions: list = field(default_factory=list)
    active_count: int = 0
    attention_count: int = 0


class StateReader:
    """Reads all project state files and produces unified project/session list."""

    def __init__(self, poc_root: str):
        self.poc_root = poc_root
        # projects/ dir is the parent of POC
        self.projects_dir = os.path.dirname(poc_root)
        # Repo root is parent of projects/
        repo_root = os.path.dirname(self.projects_dir)
        self.manifest_path = os.path.join(repo_root, 'worktrees.json')
        self._projects: list[ProjectState] = []

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
        manifest = self._load_manifest()
        now = time.time()

        # Index worktree entries by session_id
        session_entries = {}
        dispatch_by_sid = {}
        for entry in manifest.get('worktrees', []):
            sid = entry.get('session_id', '')
            if entry.get('type') == 'session':
                session_entries[sid] = entry
            elif entry.get('type') == 'dispatch':
                dispatch_by_sid[sid] = entry

        # Scan all project directories
        projects = []
        try:
            slugs = sorted(os.listdir(self.projects_dir))
        except OSError:
            slugs = []

        for slug in slugs:
            proj_path = os.path.join(self.projects_dir, slug)
            sessions_dir = os.path.join(proj_path, '.sessions')
            if not os.path.isdir(sessions_dir):
                continue

            proj_sessions = self._scan_project_sessions(
                slug, sessions_dir, session_entries, dispatch_by_sid, now,
            )

            active = sum(1 for s in proj_sessions if s.status == 'active')
            attention = sum(1 for s in proj_sessions if s.needs_input)

            projects.append(ProjectState(
                slug=slug,
                path=proj_path,
                sessions=proj_sessions,
                active_count=active,
                attention_count=attention,
            ))

        # Sort: projects with active sessions first, then by slug
        projects.sort(key=lambda p: (-p.active_count, -p.attention_count, p.slug))

        self._projects = projects
        return projects

    def _scan_project_sessions(self, slug: str, sessions_dir: str,
                                session_entries: dict,
                                dispatch_by_sid: dict,
                                now: float) -> list[SessionState]:
        """Scan .sessions/ for a single project and build SessionState list."""
        sessions = []
        try:
            ts_dirs = sorted(os.listdir(sessions_dir), reverse=True)
        except OSError:
            return sessions

        for ts_dir in ts_dirs:
            sess_path = os.path.join(sessions_dir, ts_dir)
            if not os.path.isdir(sess_path) or not ts_dir[0].isdigit():
                continue

            # Try to find matching worktree entry
            entry = session_entries.get(ts_dir, {})

            dispatches = self._find_dispatches_for_session(
                sess_path, dispatch_by_sid,
            )
            sess = self._build_session(slug, ts_dir, sess_path, entry, dispatches, now)
            sessions.append(sess)

        return sessions

    def _find_dispatches_for_session(self, sess_dir: str,
                                      dispatch_by_sid: dict) -> list[dict]:
        """Find dispatch entries within a session directory.

        Scans {sess_dir}/{team}/{dispatch_ts}/ dirs and matches
        dispatch timestamps back to worktrees.json entries.
        """
        matched = []
        teams = ('art', 'writing', 'editorial', 'research', 'coding')

        for team in teams:
            team_dir = os.path.join(sess_dir, team)
            if not os.path.isdir(team_dir):
                continue
            try:
                for dispatch_ts in sorted(os.listdir(team_dir)):
                    dispatch_dir = os.path.join(team_dir, dispatch_ts)
                    if not os.path.isdir(dispatch_dir) or not dispatch_ts[0].isdigit():
                        continue
                    entry = dispatch_by_sid.get(dispatch_ts)
                    if entry:
                        entry = dict(entry)
                        entry['_infra_dir'] = dispatch_dir
                        matched.append(entry)
                    else:
                        # Synthetic entry for dir without manifest record
                        matched.append({
                            'name': f'{team}-{dispatch_ts}',
                            'path': '',
                            'type': 'dispatch',
                            'team': team,
                            'task': '',
                            'session_id': dispatch_ts,
                            'status': 'active' if os.path.exists(
                                os.path.join(dispatch_dir, '.running')) else 'complete',
                            '_infra_dir': dispatch_dir,
                        })
            except OSError:
                continue

        return matched

    def _load_manifest(self) -> dict:
        try:
            with open(self.manifest_path) as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return {'worktrees': []}

    def _build_session(self, project: str, session_id: str,
                        infra_dir: str, entry: dict,
                        dispatches: list, now: float) -> SessionState:
        # Read CfA state
        cfa = self._read_cfa(os.path.join(infra_dir, '.cfa-state.json'))
        cfa_phase = cfa.get('phase', '')
        cfa_state = cfa.get('state', '')
        cfa_actor = cfa.get('actor', '')

        # Determine if human input needed
        needs_input = cfa_state in HUMAN_ACTOR_STATES
        if os.path.exists(os.path.join(infra_dir, '.input-request.json')):
            needs_input = True

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

        # Task: prefer worktrees.json, fall back to INTENT.md
        task = entry.get('task', '')
        if not task:
            task = self._read_intent(infra_dir)

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
            dispatches=dispatch_states,
            stream_age_seconds=stream_age,
            infra_dir=infra_dir,
        )

    def _build_dispatch(self, entry: dict, now: float) -> DispatchState:
        team = entry.get('team', '')
        infra_dir = entry.get('_infra_dir', '')
        is_running = False
        cfa_state = ''
        cfa_phase = ''
        stream_age = -1

        if infra_dir:
            is_running = os.path.exists(os.path.join(infra_dir, '.running'))
            cfa = self._read_cfa(os.path.join(infra_dir, '.cfa-state.json'))
            cfa_state = cfa.get('state', '')
            cfa_phase = cfa.get('phase', '')
            stream_age = self._stream_age(infra_dir, now)

        return DispatchState(
            team=team,
            worktree_name=entry.get('name', ''),
            worktree_path=entry.get('path', ''),
            task=entry.get('task', ''),
            status=entry.get('status', 'active'),
            cfa_state=cfa_state,
            cfa_phase=cfa_phase,
            is_running=is_running,
            infra_dir=infra_dir,
            stream_age_seconds=stream_age,
        )

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
            if d.infra_dir:
                for name in ('.exec-stream.jsonl', '.plan-stream.jsonl'):
                    path = os.path.join(d.infra_dir, name)
                    if os.path.exists(path):
                        files.append(path)

        return files
