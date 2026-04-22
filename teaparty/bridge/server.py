"""Bridge server — aiohttp app, REST endpoints, static file serving.

Entry point for the TeaParty browser UI. Exposes the orchestrator's existing
data through REST endpoints and a WebSocket. Imports existing modules directly;
no new protocol is introduced.

Usage::

    bridge = TeaPartyBridge(
        teaparty_home='~/.teaparty',
        static_dir='bridge/static',
    )
    bridge.run(port=8081)

Design: docs/proposals/ui-redesign/references/bridge-api.md
Issue #297.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Set

import yaml

from aiohttp import web

from teaparty.messaging.conversations import ConversationType, SqliteMessageBus, agent_bus_path
from teaparty.proxy.hooks import proxy_bus_path
from teaparty.teams.session import AgentSession, read_session_title
from teaparty.bridge.state.reader import StateReader
from teaparty.bridge.state.heartbeat import _heartbeat_three_state
from teaparty.config.config_reader import (
    load_management_team,
    load_project_team,
    load_workgroup,
    discover_projects,
    discover_agents,
    discover_skills,
    discover_workgroups,
    discover_hooks,
    merge_catalog,
    load_management_workgroups,
    resolve_workgroups,
    toggle_management_membership,
    toggle_project_membership,
    toggle_workgroup_membership,
    set_participant_role_management,
    set_participant_role_project,
    set_participant_role_workgroup,
    read_agent_frontmatter,
    write_agent_frontmatter,
    management_dir,
    management_agents_dir,
    management_skills_dir,
    management_settings_path,
    management_workgroups_dir,
    project_teaparty_dir,
    project_agents_dir,
    project_skills_dir,
    project_settings_path,
    project_workgroups_dir,
    WorkgroupRef,
    WorkgroupEntry,
)
from teaparty.cfa.statemachine.cfa_state import load_state as _load_cfa_file
from teaparty.bridge.poller import StatePoller
from teaparty.bridge.message_relay import MessageRelay

_log = logging.getLogger('teaparty.bridge.server')


# ── Pure helpers (exported for testing) ──────────────────────────────────────

def _resolve_conversation_type(type_str: str) -> ConversationType:
    """Convert a ?type= query string to a ConversationType enum member.

    Uses ConversationType[type_str.upper()] so that 'project_session'
    becomes ConversationType.PROJECT_SESSION.  Raises KeyError for unknown types.
    """
    return ConversationType[type_str.upper()]




def _classify_heartbeat(infra_dir: str) -> str:
    """Return heartbeat liveness as 'alive', 'stale', or 'dead'.

    Delegates to _heartbeat_three_state() from teaparty.bridge.state.heartbeat.
    """
    return _heartbeat_three_state(infra_dir)


def _load_cfa_state(infra_dir: str) -> dict | None:
    """Load CfA state from {infra_dir}/.cfa-state.json.

    Returns a dict with phase, state, actor, history, backtrack_count, or
    None if the file is missing.
    """
    cfa_path = os.path.join(infra_dir, '.cfa-state.json')
    if not os.path.exists(cfa_path):
        return None
    try:
        cfa = _load_cfa_file(cfa_path)
        return {
            'phase': cfa.phase,
            'state': cfa.state,
            'actor': cfa.actor,
            'history': cfa.history,
            'backtrack_count': cfa.backtrack_count,
        }
    except Exception:
        return None


def _detect_workgroup_overrides(org_workgroup, project_workgroup) -> list[str]:
    """Return a list of field names where the project workgroup diverges from org.

    Compares norms, budget, lead, and agents.  Returns names of
    overridden categories, e.g. ['norms', 'budget'].
    """
    overrides: list[str] = []
    if project_workgroup.norms != org_workgroup.norms:
        overrides.append('norms')
    if project_workgroup.budget != org_workgroup.budget:
        overrides.append('budget')
    if project_workgroup.lead != org_workgroup.lead:
        overrides.append('lead')
    if project_workgroup.members_agents != org_workgroup.members_agents:
        overrides.append('agents')
    return overrides


def _list_directory(path: str) -> list[dict]:
    """Return a list of entries in the given directory.

    Each entry has: name (str), path (str, absolute), is_dir (bool).
    Raises FileNotFoundError if the path does not exist or is not a directory.
    """
    path = os.path.expanduser(path)
    if not os.path.isdir(path):
        raise FileNotFoundError(f'Directory not found: {path}')
    entries = []
    for name in sorted(os.listdir(path)):
        full = os.path.join(path, name)
        entries.append({
            'name': name,
            'path': os.path.abspath(full),
            'is_dir': os.path.isdir(full),
        })
    return entries


def _parse_artifacts(content: str) -> dict[str, str]:
    """Parse markdown headings into a section dict.

    Returns {heading_text: section_body} for each ## heading found.
    """
    sections: dict[str, str] = {}
    current_heading: str | None = None
    current_lines: list[str] = []

    for line in content.splitlines():
        if line.startswith('## '):
            if current_heading is not None:
                sections[current_heading] = '\n'.join(current_lines).strip()
            current_heading = line[3:].strip()
            current_lines = []
        elif current_heading is not None:
            current_lines.append(line)

    if current_heading is not None:
        sections[current_heading] = '\n'.join(current_lines).strip()

    return sections


# CfA session artifacts at the worktree root.  These are gitignored by
# design (they never ship to main) but are review-critical during the
# session.  Always surface them in the artifact browser so the reviewer
# can see and open them regardless of git status.
_SESSION_ARTIFACTS: tuple[str, ...] = ('INTENT.md', 'PLAN.md', 'WORK_SUMMARY.md')


def parse_git_status(worktree_path: str) -> dict[str, str]:
    """Run ``git status --porcelain`` and return ``{relative_path: status}``.

    Status values: ``'new'`` (untracked), ``'modified'``, ``'deleted'``,
    ``'session'`` (CfA session artifact — gitignored but always surfaced).
    Files with no changes are omitted.
    """
    import subprocess as _sp
    try:
        result = _sp.run(
            ['git', 'status', '--porcelain'],
            cwd=worktree_path, capture_output=True, text=True, timeout=10,
        )
    except (FileNotFoundError, _sp.TimeoutExpired):
        result = None
    statuses: dict[str, str] = {}
    if result is not None and result.returncode == 0:
        for line in result.stdout.splitlines():
            if len(line) < 4:
                continue
            xy = line[:2]
            filepath = line[3:].strip()
            # Handle renames: "R  old -> new"
            if ' -> ' in filepath:
                filepath = filepath.split(' -> ')[-1]
            if xy == '??' or xy == 'A ' or xy == 'AM':  # staged-new then modified
                statuses[filepath] = 'new'
            elif xy[1] == 'D' or xy[0] == 'D':
                statuses[filepath] = 'deleted'
            else:
                statuses[filepath] = 'modified'
    # Surface CfA session artifacts regardless of git state.  They're
    # gitignored so git-status never reports them, but they must always
    # be visible to the human reviewer.  Don't override a real git status
    # if one was reported (e.g., an unusual repo where they're tracked).
    for name in _SESSION_ARTIFACTS:
        if name in statuses:
            continue
        if os.path.isfile(os.path.join(worktree_path, name)):
            statuses[name] = 'session'
    return statuses


# ── Bridge class ──────────────────────────────────────────────────────────────

class TeaPartyBridge:
    """aiohttp bridge server exposing TeaParty data via REST and WebSocket.

    Project discovery is registry-based: reads ~/.teaparty/teaparty.yaml.
    No projects_dir argument — all project paths come from the registry.

    Args:
        teaparty_home: Path to the .teaparty config directory (~ is expanded).
        static_dir:    Path to the directory containing static HTML files.
    """

    # Repo root: walk up from this file to find the root (Issue #320 moved
    # server.py from repo root into teaparty/bridge/, so dirname(dirname) is wrong).
    from teaparty import find_poc_root as _find_poc_root
    _repo_root: str = _find_poc_root()

    def __init__(self, teaparty_home: str, static_dir: str):
        self.teaparty_home = os.path.expanduser(teaparty_home)
        self.static_dir = os.path.expanduser(static_dir)
        self._llm_backend = os.environ.get('TEAPARTY_LLM_BACKEND', 'claude')
        self._mcp_asgi_app = None       # Set in _on_startup
        self._mcp_task: asyncio.Task | None = None
        self._mcp_shutdown_event: asyncio.Event | None = None
        self._ws_clients: Set[web.WebSocketResponse] = set()
        # Shared bus registry: session_id -> SqliteMessageBus.
        # Populated by the StatePoller; consumed by MessageRelay.
        self._buses: dict[str, SqliteMessageBus] = {}
        # Agent buses: agent-name -> SqliteMessageBus (persistent, not session-scoped).
        self._agent_buses: dict[str, SqliteMessageBus] = {}
        # Per-qualifier asyncio locks and unified sessions.
        self._agent_locks: dict[str, asyncio.Lock] = {}
        self._agent_sessions: dict[str, AgentSession] = {}
        self._active_job_tasks: dict[str, asyncio.Task] = {}
        # Level-triggered auto-resume (follow-up to #383): when a job task
        # dies with unconsumed human input on the bus, the status callback
        # kicks off one auto-resume to pick up the waiting message.  This
        # dict tracks the last attempt per session so a crash-loop doesn't
        # hammer resume indefinitely — a second auto-resume is suppressed
        # for ``_AUTO_RESUME_COOLDOWN_SECONDS`` after the previous attempt.
        self._last_auto_resume: dict[str, float] = {}
        # Per-project paused flag (issue #403). When a project slug is in
        # this set, new dispatches for it are refused and sending a
        # message to any of its agents implicitly triggers a resume.
        self._paused_projects: set[str] = set()
        # StateReader uses registry-based project discovery.
        self._state_reader = StateReader(
            repo_root=self._repo_root,
            teaparty_home=self.teaparty_home,
        )

        # Migrate legacy .sessions/ data to .teaparty/jobs/ (issue #387).
        # One-time on startup so compute_stats stays read-only.
        self._migrate_legacy_sessions()

        # Restore paused-project flags from disk (issue #403).
        # Each paused project has a marker file at {project}/.teaparty/paused.
        self._restore_paused_flags()

    def _migrate_legacy_sessions(self) -> None:
        """Migrate .sessions/ data to .teaparty/jobs/ for all registered projects."""
        from teaparty.workspace.job_store import migrate_legacy_sessions
        try:
            team = load_management_team(teaparty_home=self.teaparty_home)
            for entry in discover_projects(team):
                migrate_legacy_sessions(entry['path'])
        except Exception:
            _log.warning('Legacy session migration failed', exc_info=True)

    def _restore_paused_flags(self) -> None:
        """Read paused marker files from disk into _paused_projects."""
        try:
            team = load_management_team(teaparty_home=self.teaparty_home)
            for entry in discover_projects(team):
                marker = os.path.join(entry['path'], '.teaparty', 'paused')
                if os.path.isfile(marker):
                    slug = os.path.basename(entry['path'].rstrip('/'))
                    self._paused_projects.add(slug)
                    _log.info('Restored paused flag for project %s', slug)
        except Exception:
            _log.warning('Failed to restore paused flags', exc_info=True)

    @staticmethod
    def _write_paused_marker(project_path: str) -> None:
        """Write the paused marker file for a project."""
        marker = os.path.join(project_path, '.teaparty', 'paused')
        os.makedirs(os.path.dirname(marker), exist_ok=True)
        with open(marker, 'w') as f:
            f.write('')

    @staticmethod
    def _remove_paused_marker(project_path: str) -> None:
        """Remove the paused marker file for a project."""
        marker = os.path.join(project_path, '.teaparty', 'paused')
        try:
            os.unlink(marker)
        except FileNotFoundError:
            pass

    def run(self, port: int = 8081) -> None:
        """Start the bridge server and block until interrupted."""
        # Publish the port so agent invocations can compose .mcp.json
        # pointing to the HTTP MCP endpoint at /mcp/{scope}/{agent}.
        os.environ['TEAPARTY_BRIDGE_PORT'] = str(port)
        app = self._build_app()
        web.run_app(app, port=port)

    def _build_app(self) -> web.Application:
        """Build and return the aiohttp application with all routes registered."""
        app = web.Application()

        # ── State endpoints ───────────────────────────────────────────────────
        app.router.add_get('/api/state', self._handle_state_all)
        app.router.add_get('/api/state/{project}', self._handle_state_project)
        app.router.add_get('/api/cfa/{session_id}', self._handle_cfa_state)
        app.router.add_get('/api/heartbeat/{session_id}', self._handle_heartbeat)

        # ── Stats endpoint ────────────────────────────────────────────────────
        app.router.add_get('/api/stats', self._handle_stats)

        # ── Telemetry endpoints (Issue #405 / #406) ───────────────────────────
        app.router.add_get('/api/telemetry/events', self._handle_telemetry_events)
        app.router.add_get('/api/telemetry/stats/{scope}', self._handle_telemetry_stats)
        app.router.add_get('/api/telemetry/chart/{chart_type}', self._handle_telemetry_chart)

        # ── Config endpoints ──────────────────────────────────────────────────
        app.router.add_get('/api/config', self._handle_config)
        app.router.add_post('/api/config/management/toggle', self._handle_config_management_toggle)
        app.router.add_post('/api/config/management/participant', self._handle_config_management_participant)
        app.router.add_get('/api/config/{project}', self._handle_config_project)
        app.router.add_post('/api/config/{project}/toggle', self._handle_config_project_toggle)
        app.router.add_post('/api/config/{project}/participant', self._handle_config_project_participant)
        app.router.add_get('/api/workgroups', self._handle_workgroups)
        app.router.add_post('/api/workgroups/{name}/toggle', self._handle_workgroup_toggle)
        app.router.add_post('/api/workgroups/{name}/participant', self._handle_workgroup_participant)
        app.router.add_get('/api/workgroups/{name}', self._handle_workgroup_detail)
        app.router.add_patch('/api/workgroups/{name}', self._handle_workgroup_patch)
        app.router.add_get('/api/agents/{name}', self._handle_agent_detail)
        app.router.add_patch('/api/agents/{name}', self._handle_agent_patch)
        app.router.add_get('/api/catalog/org', self._handle_catalog_org)
        app.router.add_get('/api/catalog/{project}', self._handle_catalog)

        # ── Message endpoints ─────────────────────────────────────────────────
        app.router.add_get('/api/conversations', self._handle_conversations_list)
        app.router.add_get('/api/conversations/{id}', self._handle_conversation_get)
        app.router.add_post('/api/conversations/{id}', self._handle_conversation_post)

        # ── Artifact endpoints ────────────────────────────────────────────────
        app.router.add_get('/api/pins', self._handle_pins)
        app.router.add_patch('/api/pins', self._handle_pins_patch)
        app.router.add_get('/api/artifacts/{project}', self._handle_artifacts)
        app.router.add_get('/api/artifacts/{project}/pins', self._handle_artifact_pins)
        app.router.add_patch('/api/artifacts/{project}/pins', self._handle_artifact_pins_patch)
        app.router.add_get('/api/file', self._handle_file)
        app.router.add_get('/api/session/{session_id}/file', self._handle_session_file)

        # ── Task endpoints ───────────────────────────────────────────────────
        app.router.add_get('/api/sessions/{session_id}/tasks', self._handle_session_tasks)
        app.router.add_get('/api/dispatch-tree/{session_id}', self._handle_dispatch_tree)

        # ── Action endpoints ──────────────────────────────────────────────────
        app.router.add_post('/api/jobs', self._handle_create_job)
        app.router.add_post('/api/withdraw/{session_id}', self._handle_withdraw)
        app.router.add_get('/api/jobs/{slug}/{session_id}/status', self._handle_job_status)
        app.router.add_post('/api/jobs/{slug}/{session_id}/wake', self._handle_job_wake)
        app.router.add_get('/api/projects/{slug}/escalation', self._handle_escalation_get)
        app.router.add_patch('/api/projects/{slug}/escalation', self._handle_escalation_patch)

        # ── Filesystem navigation endpoint ────────────────────────────────────
        app.router.add_get('/api/fs/list', self._handle_fs_list)
        app.router.add_get('/api/git-status', self._handle_git_status)

        # ── Project management endpoints ──────────────────────────────────────
        app.router.add_post('/api/projects/add', self._handle_projects_add)
        app.router.add_post('/api/projects/create', self._handle_projects_create)

        # ── Project pause / resume (issue #403) ────────────────────────────
        app.router.add_post(
            '/api/projects/{slug}/pause', self._handle_project_pause)
        app.router.add_post(
            '/api/projects/{slug}/resume', self._handle_project_resume)
        app.router.add_post(
            '/api/projects/{slug}/remove', self._handle_project_remove)

        # ── WebSocket ─────────────────────────────────────────────────────────
        app.router.add_get('/ws', self._handle_websocket)

        # ── MCP server (shared, per-agent filtering) ─────────────────────────
        app.router.add_route('*', '/mcp', self._handle_mcp)
        app.router.add_route('*', '/mcp/{scope}/{agent}', self._handle_mcp)
        app.router.add_route('*', '/mcp/{scope}/{agent}/{session_id}', self._handle_mcp)

        # ── Static files ──────────────────────────────────────────────────────
        if not os.path.isdir(self.static_dir):
            raise FileNotFoundError(
                f'static_dir does not exist: {self.static_dir}'
            )
        app.router.add_get('/', self._handle_index)
        app.router.add_static('/', self.static_dir, show_index=True)

        app.on_startup.append(self._on_startup)
        app.on_cleanup.append(self._on_cleanup)

        return app

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def _handle_mcp(self, request: web.Request) -> web.StreamResponse:
        """Forward MCP requests to the shared ASGI app.

        Bridges aiohttp request/response to ASGI scope/receive/send.
        """
        # Build ASGI scope
        scope = {
            'type': 'http',
            'asgi': {'version': '3.0'},
            'http_version': '1.1',
            'method': request.method,
            'path': request.path,
            'query_string': request.query_string.encode() if request.query_string else b'',
            'headers': [(k.lower().encode(), v.encode()) for k, v in request.headers.items()],
            'server': (request.host.split(':')[0], request.url.port or 80),
        }

        body = await request.read()

        # ASGI receive — after delivering the body, block until the
        # client actually disconnects.  The MCP Streamable HTTP transport
        # polls receive() to detect disconnection; returning
        # http.disconnect immediately would kill SSE streams on the
        # first poll.
        sent_body = False
        disconnect_event = asyncio.Event()

        async def receive():
            nonlocal sent_body
            if not sent_body:
                sent_body = True
                return {'type': 'http.request', 'body': body, 'more_body': False}
            # Block until the client drops the connection (or the ASGI
            # app finishes and cancels this coroutine).
            await disconnect_event.wait()
            return {'type': 'http.disconnect'}

        # ASGI send — collect response parts
        response = web.StreamResponse()
        response_started = False

        async def send(msg):
            nonlocal response_started
            if msg['type'] == 'http.response.start':
                if response_started:
                    return  # headers already sent
                response.set_status(msg['status'])
                for name, value in msg.get('headers', []):
                    # Skip content-length — aiohttp manages it
                    if name.lower() != b'content-length':
                        response.headers[name.decode()] = value.decode()
                try:
                    await response.prepare(request)
                except ConnectionResetError:
                    disconnect_event.set()
                    return
                response_started = True
            elif msg['type'] == 'http.response.body':
                body_data = msg.get('body', b'')
                if body_data and response_started:
                    try:
                        await response.write(body_data)
                    except ConnectionResetError:
                        disconnect_event.set()

        try:
            await self._mcp_asgi_app(scope, receive, send)
        except Exception:
            _log.debug('ASGI app error (client may have disconnected)',
                        exc_info=True)
        finally:
            disconnect_event.set()

        if response_started:
            try:
                await response.write_eof()
            except (ConnectionResetError, Exception):
                pass
        return response

    async def _on_startup(self, app: web.Application) -> None:
        # Start the shared MCP server (same event loop, no threading)
        from teaparty.mcp.server.main import create_http_app
        self._mcp_asgi_app, mcp_starlette, mcp_server = create_http_app()
        # Run the session manager inside a dedicated asyncio task so that the
        # anyio task group it uses enters and exits within the same task —
        # a requirement anyio enforces.  Calling __aenter__/__aexit__ from
        # aiohttp's on_startup/on_shutdown hooks violates this because those
        # hooks run in different tasks, leaving a dangling async generator on
        # shutdown (logged as "asyncgen error during closing").
        self._mcp_shutdown_event = asyncio.Event()
        ready = asyncio.Event()

        async def _run_mcp_session(session_mgr, shutdown_event, ready_event):
            async with session_mgr.run():
                ready_event.set()
                await shutdown_event.wait()

        self._mcp_task = asyncio.ensure_future(
            _run_mcp_session(mcp_server.session_manager,
                             self._mcp_shutdown_event, ready)
        )
        await ready.wait()
        _log.info('MCP server started (in-process, same event loop)')

        async def broadcast(event: dict) -> None:
            payload = json.dumps(event)
            for ws in list(self._ws_clients):
                try:
                    await ws.send_str(payload)
                except Exception:
                    pass

        # ── Telemetry store (Issue #405) ──────────────────────────────────
        # One SQLite database at {teaparty_home}/telemetry.db. Every write
        # path in the codebase routes through telemetry.record_event; this
        # wires the broadcast hook so each write fans out to WebSocket
        # clients via the local `broadcast` closure.
        try:
            from teaparty import telemetry
            from teaparty.telemetry import events as telem_events
            telemetry.set_teaparty_home(self.teaparty_home)
            telemetry.set_broadcaster(broadcast, asyncio.get_running_loop())
            # One-time migration of pre-telemetry per-scope data files.
            try:
                telemetry.migrate_metrics_db(self.teaparty_home)
            except Exception:
                _log.warning(
                    'telemetry migration failed', exc_info=True,
                )
            telemetry.record_event(
                telem_events.SERVER_START,
                scope='management',
                data={
                    'teaparty_home_path': self.teaparty_home,
                },
            )
        except Exception:
            _log.warning(
                'failed to initialize telemetry store', exc_info=True,
            )

        def bus_factory(infra_dir: str) -> SqliteMessageBus:
            db_path = os.path.join(infra_dir, 'messages.db')
            bus = SqliteMessageBus(db_path)
            # Key by session_id (last path component) so MessageRelay emits the
            # correct session_id in WebSocket events, not a filesystem path.
            self._buses[os.path.basename(infra_dir)] = bus
            return bus

        def bus_teardown(bus: SqliteMessageBus) -> None:
            # Remove the closed bus from the MessageRelay registry by object
            # identity — the StatePoller and server._buses use different keys,
            # so we can't match by key alone.
            for key in [k for k, v in list(self._buses.items()) if v is bus]:
                self._buses.pop(key, None)

        poller = StatePoller(
            self._state_reader, broadcast,
            bus_factory=bus_factory,
            bus_teardown=bus_teardown,
        )
        relay = MessageRelay(self._buses, broadcast)
        self._message_relay = relay

        app['_poller_task'] = asyncio.create_task(poller.run())
        app['_relay_task'] = asyncio.create_task(relay.run())

        # Open persistent agent buses and register them for MessageRelay polling.
        # Agent-name keys are stable and will never collide with a session_id.
        for agent_name in ('office-manager', 'project-manager', 'proxy', 'configuration-lead'):
            self._get_agent_bus(agent_name)

    async def _on_cleanup(self, app: web.Application) -> None:
        # Emit server_shutdown telemetry before tearing anything down.
        try:
            from teaparty import telemetry
            from teaparty.telemetry import events as telem_events
            telemetry.record_event(
                telem_events.SERVER_SHUTDOWN,
                scope='management',
                data={'graceful': True},
            )
            telemetry.set_broadcaster(None)
        except Exception:
            pass

        # Shut down MCP session manager — signal the dedicated task to exit
        # the anyio task group from within the same task that entered it.
        if self._mcp_shutdown_event is not None:
            self._mcp_shutdown_event.set()
        if self._mcp_task is not None:
            try:
                await asyncio.wait_for(self._mcp_task, timeout=5.0)
            except (asyncio.TimeoutError, asyncio.CancelledError, Exception):
                self._mcp_task.cancel()
                try:
                    await self._mcp_task
                except (asyncio.CancelledError, Exception):
                    pass

        for key in ('_poller_task', '_relay_task'):
            task = app.get(key)
            if task is not None:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        for bus in self._buses.values():
            bus.close()
        # Agent buses registered in self._buses are closed above.
        # Close any agent buses opened lazily but not in self._buses.
        for name, bus in self._agent_buses.items():
            if name not in self._buses:
                bus.close()
        # Stop bus event listeners so socket servers are cleaned up.
        for session in self._agent_sessions.values():
            await session.stop()

    # ── State handlers ────────────────────────────────────────────────────────

    async def _handle_state_all(self, request: web.Request) -> web.Response:
        projects = self._state_reader.reload()
        data = [self._serialize_project(p) for p in projects]
        # Stamp the paused flag (issue #403) so a fresh page load shows
        # the paused status pill without waiting for a WebSocket event.
        for entry in data:
            slug = entry.get('slug', '')
            if slug and slug in self._paused_projects:
                entry['paused'] = True
        return web.json_response(data)

    async def _handle_state_project(self, request: web.Request) -> web.Response:
        slug = request.match_info['project']
        self._state_reader.reload()
        project = self._state_reader.find_project(slug)
        if project is None:
            return web.json_response({'error': f'project not found: {slug}'}, status=404)
        return web.json_response(self._serialize_project(project))

    async def _handle_cfa_state(self, request: web.Request) -> web.Response:
        session_id = request.match_info['session_id']
        infra_dir = self._resolve_session_infra(session_id)
        if infra_dir is None:
            return web.json_response({'error': f'session not found: {session_id}'}, status=404)
        state = _load_cfa_state(infra_dir)
        if state is None:
            return web.json_response({'error': 'cfa-state.json not found'}, status=404)
        # Include worktree_path so the browser can construct absolute artifact URLs.
        state['worktree_path'] = os.path.join(infra_dir, 'worktree')
        return web.json_response(state)

    async def _handle_heartbeat(self, request: web.Request) -> web.Response:
        session_id = request.match_info['session_id']
        infra_dir = self._resolve_session_infra(session_id)
        if infra_dir is None:
            return web.json_response({'status': 'dead'})
        status = _classify_heartbeat(infra_dir)
        return web.json_response({'session_id': session_id, 'status': status})

    async def _handle_stats(self, request: web.Request) -> web.Response:
        from teaparty.bridge.stats import compute_stats
        data = compute_stats(self.teaparty_home)
        return web.json_response(data)

    # ── Telemetry handlers (Issue #405) ────────────────────────────────────
    async def _handle_telemetry_events(
        self, request: web.Request,
    ) -> web.Response:
        """Raw event query. Supports scope, agent, session, event_type,
        start_ts, end_ts, limit. Used by admin dashboards."""
        from teaparty import telemetry

        def qp(name):
            v = request.query.get(name)
            return v if v else None

        def fp(name):
            v = request.query.get(name)
            try:
                return float(v) if v else None
            except (TypeError, ValueError):
                return None

        def ip(name):
            v = request.query.get(name)
            try:
                return int(v) if v else None
            except (TypeError, ValueError):
                return None

        events = telemetry.query_events(
            scope=qp('scope'),
            agent=qp('agent'),
            session=qp('session'),
            event_type=qp('event_type'),
            start_ts=fp('start_ts'),
            end_ts=fp('end_ts'),
            limit=ip('limit') or 1000,
        )
        return web.json_response({
            'events': [
                {
                    'id':         e.id,
                    'ts':         e.ts,
                    'scope':      e.scope,
                    'agent_name': e.agent_name,
                    'session_id': e.session_id,
                    'event_type': e.event_type,
                    'data':       e.data,
                }
                for e in events
            ],
        })

    async def _handle_telemetry_stats(
        self, request: web.Request,
    ) -> web.Response:
        """Aggregated stats for a scope.  Used by the stats bar on mount
        to fetch the baseline snapshot.

        Path param: ``scope`` (use ``all`` for org-wide).
        Query params: ``agent``, ``session``, ``time_range``
            (``today`` | ``7d`` | ``30d`` | ``all``; default ``today``).
        """
        import time as _t
        from teaparty import telemetry
        from teaparty.telemetry.query import _today_range, _days_range

        scope = request.match_info['scope']
        s = scope if scope != 'all' else None
        agent   = request.query.get('agent') or None
        session = request.query.get('session') or None

        tr_param = request.query.get('time_range', 'today')
        if tr_param == 'today':
            tr = _today_range()
        elif tr_param == '7d':
            tr = _days_range(7)
        elif tr_param == '30d':
            tr = _days_range(30)
        else:
            tr = None  # all time

        summary = telemetry.stats_summary(
            scope=s, agent=agent, session=session,
            time_range=tr,
        )
        return web.json_response({
            'scope':                   scope,
            # Core counts (paged ticker)
            'total_cost':              summary['cost_today'],
            'turn_count':              summary['turn_count_today'],
            'total_tokens':            summary['total_tokens_today'],
            'processing_ms':           summary['processing_ms_today'],
            'active_sessions':         summary['active_sessions'],
            'gates_awaiting_input':    summary['gates_waiting'],
            'backtrack_count':         summary['backtrack_count_today'],
            'jobs_started':            summary['jobs_started_today'],
            'sessions_closed':         summary['sessions_closed_today'],
            'withdrawals':             summary['withdrawals_today'],
            'escalations_proxy':       summary['escalations_proxy_today'],
            'escalations_human':       summary['escalations_human_today'],
            'tool_retries':            summary['tool_retries_today'],
            'errors':                  summary['errors_today'],
            'conversations_started':   summary['conversations_started_today'],
            'conversations_closed':    summary['conversations_closed_today'],
            # Friction / infra
            'commits':                 summary['commits_today'],
            'stalls':                  summary['stalls_today'],
            'ratelimits':              summary['ratelimits_today'],
            'ctx_compacted':           summary['ctx_compacted_today'],
            'ctx_warnings':            summary['ctx_warnings_today'],
            'mcp_failures':            summary['mcp_failures_today'],
            # Human involvement
            'interjections':           summary['interjections_today'],
            'corrections':             summary['corrections_today'],
            'sess_timed_out':          summary['sess_timed_out_today'],
            'sess_abandoned':          summary['sess_abandoned_today'],
            # Scalar summaries kept for chart page / legacy consumers
            'escalation_count':        summary['escalation_count_today'],
            'proxy_answered_fraction': summary['proxy_answered_fraction'],
            'gate_pass_rate':          summary['gate_pass_rate'],
            # Detailed breakdowns for the chart page.
            'backtrack_cost':      telemetry.backtrack_cost(
                scope=s, agent=agent, session=session, time_range=tr,
            ),
            'phase_distribution':  telemetry.phase_distribution(
                scope=s, agent=agent, session=session, time_range=tr,
            ),
            'escalation_stats':    telemetry.escalation_stats(
                scope=s, agent=agent, session=session, time_range=tr,
            ),
            'proxy_answer_rate':   telemetry.proxy_answer_rate(
                scope=s, agent=agent, session=session, time_range=tr,
            ),
            'withdrawal_phase_distribution': telemetry.withdrawal_phase_distribution(
                scope=s, agent=agent, session=session, time_range=tr,
            ),
        })

    async def _handle_telemetry_chart(
        self, request: web.Request,
    ) -> web.Response:
        """Chart data for the stats graph page (Issue #406).

        Path param: ``chart_type`` — one of the eight chart types.
        Query params: ``scope``, ``agent``, ``session``,
            ``time_range`` (``today`` | ``7d`` | ``30d`` | ``all``; default ``7d``),
            ``days`` (integer, overrides time_range days if present).
        """
        import time as _t
        from datetime import datetime, timezone
        from teaparty import telemetry
        from teaparty.telemetry import events as E
        from teaparty.telemetry.query import query_events, _today_range, _days_range

        chart_type = request.match_info['chart_type']
        scope   = request.query.get('scope') or None
        agent   = request.query.get('agent') or None
        session = request.query.get('session') or None

        tr_param = request.query.get('time_range', '7d')
        if tr_param == 'today':
            tr = _today_range()
            days = 1
        elif tr_param == '30d':
            tr = _days_range(30)
            days = 30
        elif tr_param == 'all':
            tr = None
            days = 365
        else:  # '7d' default
            tr = _days_range(7)
            days = 7
        if request.query.get('days'):
            try:
                days = int(request.query['days'])
                tr = _days_range(days)
            except (TypeError, ValueError):
                pass

        # ── Helpers ──────────────────────────────────────────────────────────

        def _daily_buckets(n_days: int) -> list[str]:
            """Return ISO-date strings for the last n_days days (oldest first)."""
            now_ts = _t.time()
            result = []
            for d in range(n_days - 1, -1, -1):
                dt = datetime.fromtimestamp(now_ts - d * 86400, tz=timezone.utc)
                result.append(dt.strftime('%Y-%m-%d'))
            return result

        def _bucket_key(ts: float) -> str:
            return datetime.fromtimestamp(ts, tz=timezone.utc).strftime('%Y-%m-%d')

        # ── Chart type dispatch ───────────────────────────────────────────────

        if chart_type == 'cost_over_time':
            evts = query_events(
                event_type=E.TURN_COMPLETE, scope=scope, agent=agent, session=session,
                start_ts=tr[0] if tr else None, end_ts=tr[1] if tr else None,
            )
            buckets = _daily_buckets(days)
            daily: dict[str, float] = {b: 0.0 for b in buckets}
            for ev in evts:
                key = _bucket_key(ev.ts)
                if key in daily:
                    daily[key] = round(daily[key] + float(ev.data.get('cost_usd', 0.0) or 0.0), 6)
            return web.json_response({
                'chart_type': chart_type,
                'data': [{'date': k, 'cost_usd': v} for k, v in daily.items()],
            })

        elif chart_type == 'turns_per_day':
            evts = query_events(
                event_type=E.TURN_COMPLETE, scope=scope, agent=agent, session=session,
                start_ts=tr[0] if tr else None, end_ts=tr[1] if tr else None,
            )
            buckets = _daily_buckets(days)
            daily2: dict[str, int] = {b: 0 for b in buckets}
            for ev in evts:
                key = _bucket_key(ev.ts)
                if key in daily2:
                    daily2[key] += 1
            return web.json_response({
                'chart_type': chart_type,
                'data': [{'date': k, 'count': v} for k, v in daily2.items()],
            })

        elif chart_type == 'active_sessions_timeline':
            # Compute historically accurate active session counts at each
            # 6-hour checkpoint.  At checkpoint t: count sessions whose
            # session_create.ts <= t and whose first terminal event (if any)
            # has ts > t.
            from teaparty.telemetry import events as _tev
            terminal_types = [
                _tev.SESSION_COMPLETE, _tev.SESSION_CLOSED,
                _tev.SESSION_WITHDRAWN, _tev.SESSION_TIMED_OUT,
                _tev.SESSION_ABANDONED,
            ]
            created_events = telemetry.query_events(
                event_type=_tev.SESSION_CREATE, scope=scope, agent=agent,
            )
            terminal_events = telemetry.query_events(
                event_types=terminal_types, scope=scope, agent=agent,
            )
            # Build maps: session_id -> earliest create/close timestamp.
            created_at: dict[str, float] = {}
            for e in created_events:
                if e.session_id and (e.session_id not in created_at
                                     or e.ts < created_at[e.session_id]):
                    created_at[e.session_id] = e.ts
            closed_at: dict[str, float] = {}
            for e in terminal_events:
                if e.session_id and (e.session_id not in closed_at
                                     or e.ts < closed_at[e.session_id]):
                    closed_at[e.session_id] = e.ts

            now_ts = _t.time()
            start_ts = tr[0] if tr else (now_ts - days * 86400)
            end_ts   = tr[1] if tr else now_ts
            interval = 6 * 3600
            samples = []
            t = start_ts
            while t <= end_ts:
                count = sum(
                    1 for sid, c_ts in created_at.items()
                    if c_ts <= t and (sid not in closed_at or closed_at[sid] > t)
                )
                dt_str = datetime.fromtimestamp(t, tz=timezone.utc).strftime('%Y-%m-%d %H:%M')
                samples.append({'ts': t, 'datetime': dt_str, 'count': count})
                t += interval
            return web.json_response({'chart_type': chart_type, 'data': samples})

        elif chart_type == 'phase_distribution':
            dist = telemetry.phase_distribution(
                scope=scope, agent=agent, session=session, time_range=tr,
            )
            return web.json_response({
                'chart_type': chart_type,
                'data': [{'phase': k, 'count': v} for k, v in dist.items()],
            })

        elif chart_type == 'backtrack_cost':
            kinds = ['plan_to_intent', 'work_to_plan', 'work_to_intent']
            data = []
            for kind in kinds:
                cost = telemetry.backtrack_cost(
                    scope=scope, agent=agent, session=session, kind=kind, time_range=tr,
                )
                count = telemetry.backtrack_count(
                    scope=scope, agent=agent, session=session, kind=kind, time_range=tr,
                )
                data.append({'kind': kind, 'cost_usd': cost, 'count': count})
            return web.json_response({'chart_type': chart_type, 'data': data})

        elif chart_type == 'escalation_outcomes':
            par = telemetry.proxy_answer_rate(
                scope=scope, agent=agent, session=session, time_range=tr,
            )
            return web.json_response({
                'chart_type': chart_type,
                'data': {
                    'by_proxy': par['by_proxy'],
                    'by_human': par['by_human'],
                    'total':    par['total'],
                    'proxy_rate': par['proxy_rate'],
                },
            })

        elif chart_type == 'withdrawal_phases':
            dist = telemetry.withdrawal_phase_distribution(
                scope=scope, agent=agent, session=session, time_range=tr,
            )
            return web.json_response({
                'chart_type': chart_type,
                'data': [{'phase': k, 'count': v} for k, v in dist.items()],
            })

        elif chart_type == 'gate_pass_rate':
            gpr = telemetry.gate_pass_rate(
                scope=scope, agent=agent, session=session, time_range=tr,
            )
            return web.json_response({
                'chart_type': chart_type,
                'data': [
                    {'gate_type': k, 'passed': v['passed'], 'failed': v['failed'], 'rate': v['rate']}
                    for k, v in gpr.items()
                ],
            })

        else:
            return web.json_response(
                {'error': f'unknown chart_type: {chart_type!r}'},
                status=404,
            )

    # ── Config handlers ───────────────────────────────────────────────────────

    async def _handle_config(self, request: web.Request) -> web.Response:
        try:
            team = load_management_team(teaparty_home=self.teaparty_home)
            projects = discover_projects(team)
            for p in projects:
                p['slug'] = os.path.basename(p['path'])
            org_agents_dir = management_agents_dir(self.teaparty_home)
            org_skills_dir = management_skills_dir(self.teaparty_home)
            discovered_agents = discover_agents(org_agents_dir)
            discovered_skills = discover_skills(org_skills_dir)
            return web.json_response({
                'management_team': self._serialize_management_team(
                    team,
                    discovered_agents=discovered_agents,
                    discovered_skills=discovered_skills,
                ),
                'projects': projects,
            })
        except FileNotFoundError:
            return web.json_response({'management_team': None, 'projects': []})

    async def _handle_config_project(self, request: web.Request) -> web.Response:
        slug = request.match_info['project']
        project_dir = self._lookup_project_path(slug)
        if project_dir is None:
            return web.json_response({'error': f'project not found: {slug}'}, status=404)
        try:
            team = load_project_team(project_dir)
        except FileNotFoundError:
            return web.json_response({'error': f'project config not found: {slug}'}, status=404)

        try:
            mgmt = load_management_team(teaparty_home=self.teaparty_home)
            org_agents: list[str] = mgmt.members_agents
            org_catalog_skills: list[str] = discover_skills(
                management_skills_dir(self.teaparty_home)
            )
        except FileNotFoundError:
            org_agents = []
            org_catalog_skills = []

        org_catalog_agents: list[str] = discover_agents(
            management_agents_dir(self.teaparty_home)
        )

        local_skills: list[str] = discover_skills(
            project_skills_dir(project_dir)
        )

        project_catalog = merge_catalog(
            management_dir(self.teaparty_home),
            project_teaparty_dir(project_dir),
        )

        members_workgroups_lower = {m.lower() for m in team.members_workgroups}
        workgroups = []
        seen_workgroup_names_lower: set[str] = set()
        for entry in team.workgroups:
            source = 'shared' if isinstance(entry, WorkgroupRef) else 'local'
            try:
                resolved = resolve_workgroups(
                    [entry], project_dir=project_dir,
                    teaparty_home=self.teaparty_home,
                )
                for w in resolved:
                    overrides: list[str] = []
                    if isinstance(entry, WorkgroupRef):
                        org_path = os.path.join(
                            self.teaparty_home, 'workgroups', f'{entry.ref}.yaml'
                        )
                        project_path = os.path.join(
                            project_dir, '.teaparty', 'workgroups', f'{entry.ref}.yaml'
                        )
                        if os.path.exists(project_path) and os.path.exists(org_path):
                            try:
                                org_wg = load_workgroup(org_path)
                                overrides = _detect_workgroup_overrides(org_wg, w)
                            except Exception:
                                pass
                    workgroup_active = w.name.lower() in members_workgroups_lower
                    workgroups.append(
                        self._serialize_workgroup(
                            w, source=source, overrides=overrides,
                            active=workgroup_active,
                        )
                    )
                    seen_workgroup_names_lower.add(w.name.lower())
                    seen_workgroup_names_lower.add(w.name.lower().replace(' ', '-'))
            except FileNotFoundError:
                _log.warning('Workgroup not found, skipping: %s', entry)

        # Append management catalog workgroups not yet referenced by this project,
        # so the UI can show the full catalog with toggles (same pattern as agents/skills).
        org_wg_dir = management_workgroups_dir(self.teaparty_home)
        for wg_name in discover_workgroups(org_wg_dir):
            if wg_name.lower() in seen_workgroup_names_lower:
                continue
            org_wg_path = os.path.join(org_wg_dir, f'{wg_name}.yaml')
            try:
                org_wg = load_workgroup(org_wg_path)
                wg_active = org_wg.name.lower() in members_workgroups_lower
                workgroups.append(
                    self._serialize_workgroup(org_wg, source='shared', active=wg_active)
                )
            except Exception:
                _log.warning('Could not load org workgroup: %s', wg_name)

        return web.json_response({
            'project': slug,
            'team': self._serialize_project_team(
                team,
                org_agents=org_agents,
                org_catalog_agents=org_catalog_agents,
                local_skills=local_skills,
                org_catalog_skills=org_catalog_skills,
                teaparty_home=self.teaparty_home,
                project_dir=project_dir,
                catalog_hooks=project_catalog.hooks,
            ),
            'workgroups': workgroups,
        })

    async def _handle_config_management_toggle(self, request: web.Request) -> web.Response:
        try:
            body = await request.json()
        except Exception:
            return web.json_response({'error': 'invalid JSON body'}, status=400)
        kind = body.get('type', '')
        name = body.get('name', '')
        active = body.get('active')
        if kind not in ('agent', 'workgroup', 'skill', 'hook', 'scheduled_task') or not name or not isinstance(active, bool):
            return web.json_response(
                {'error': 'body must include type (agent|workgroup|skill|hook|scheduled_task), name, and active (bool)'},
                status=400,
            )
        try:
            toggle_management_membership(self.teaparty_home, kind, name, active)
        except (FileNotFoundError, ValueError) as exc:
            return web.json_response({'error': str(exc)}, status=404)
        return web.json_response({'ok': True})

    async def _handle_config_project_toggle(self, request: web.Request) -> web.Response:
        slug = request.match_info['project']
        project_dir = self._lookup_project_path(slug)
        if project_dir is None:
            return web.json_response({'error': f'project not found: {slug}'}, status=404)
        try:
            body = await request.json()
        except Exception:
            return web.json_response({'error': 'invalid JSON body'}, status=400)
        kind = body.get('type', '')
        name = body.get('name', '')
        active = body.get('active')
        if kind not in ('agent', 'workgroup', 'skill', 'hook', 'scheduled_task') or not name or not isinstance(active, bool):
            return web.json_response(
                {'error': 'body must include type (agent|workgroup|skill|hook|scheduled_task), name, and active (bool)'},
                status=400,
            )
        if kind == 'workgroup' and name.lower() == 'configuration' and active:
            return web.json_response(
                {'error': 'Configuration workgroup cannot be added to dispatch members'},
                status=400,
            )
        # Build catalog for first-deactivation seeding
        catalog = None
        if kind == 'skill' and not active:
            catalog = (
                discover_skills(project_skills_dir(project_dir))
                + discover_skills(management_skills_dir(self.teaparty_home))
            )
        try:
            toggle_project_membership(
                project_dir, kind, name, active, catalog=catalog,
                teaparty_home=self.teaparty_home,
            )
        except (FileNotFoundError, ValueError) as exc:
            return web.json_response({'error': str(exc)}, status=404)
        return web.json_response({'ok': True})

    async def _handle_config_management_participant(self, request: web.Request) -> web.Response:
        try:
            body = await request.json()
        except Exception:
            return web.json_response({'error': 'invalid JSON body'}, status=400)
        name = body.get('name', '')
        role = body.get('role', '')
        if not name or not role:
            return web.json_response({'error': 'body must include name and role'}, status=400)
        try:
            set_participant_role_management(self.teaparty_home, name, role)
        except (FileNotFoundError, ValueError) as exc:
            return web.json_response({'error': str(exc)}, status=400)
        return web.json_response({'ok': True})

    async def _handle_config_project_participant(self, request: web.Request) -> web.Response:
        slug = request.match_info['project']
        project_dir = self._lookup_project_path(slug)
        if project_dir is None:
            return web.json_response({'error': f'project not found: {slug}'}, status=404)
        try:
            body = await request.json()
        except Exception:
            return web.json_response({'error': 'invalid JSON body'}, status=400)
        name = body.get('name', '')
        role = body.get('role', '')
        if not name or not role:
            return web.json_response({'error': 'body must include name and role'}, status=400)
        try:
            set_participant_role_project(project_dir, name, role)
        except (FileNotFoundError, ValueError) as exc:
            return web.json_response({'error': str(exc)}, status=400)
        return web.json_response({'ok': True})

    async def _handle_workgroup_participant(self, request: web.Request) -> web.Response:
        wg_name = request.match_info['name']
        project_slug = request.rel_url.query.get('project')
        try:
            body = await request.json()
        except Exception:
            return web.json_response({'error': 'invalid JSON body'}, status=400)
        name = body.get('name', '')
        role = body.get('role', '')
        if not name or not role:
            return web.json_response({'error': 'body must include name and role'}, status=400)
        if project_slug:
            project_dir = self._lookup_project_path(project_slug)
            if project_dir is None:
                return web.json_response({'error': f'project not found: {project_slug}'}, status=404)
            yaml_path = os.path.join(project_workgroups_dir(project_dir), f'{wg_name}.yaml')
            if not os.path.exists(yaml_path):
                yaml_path = os.path.join(management_workgroups_dir(self.teaparty_home), f'{wg_name}.yaml')
        else:
            yaml_path = os.path.join(management_workgroups_dir(self.teaparty_home), f'{wg_name}.yaml')
        try:
            set_participant_role_workgroup(yaml_path, name, role)
        except (FileNotFoundError, ValueError) as exc:
            return web.json_response({'error': str(exc)}, status=400)
        return web.json_response({'ok': True})

    async def _handle_workgroup_toggle(self, request: web.Request) -> web.Response:
        wg_name = request.match_info['name']
        project_slug = request.rel_url.query.get('project')
        try:
            body = await request.json()
        except Exception:
            return web.json_response({'error': 'invalid JSON body'}, status=400)
        kind = body.get('type', '')
        name = body.get('name', '')
        active = body.get('active')
        if kind not in ('agent', 'hook') or not name or not isinstance(active, bool):
            return web.json_response(
                {'error': 'body must include type (agent|hook), name, and active (bool)'},
                status=400,
            )
        if project_slug:
            project_dir = self._lookup_project_path(project_slug)
            if project_dir is None:
                return web.json_response({'error': f'project not found: {project_slug}'}, status=404)
            yaml_path = os.path.join(project_workgroups_dir(project_dir), f'{wg_name}.yaml')
            if not os.path.exists(yaml_path):
                yaml_path = os.path.join(management_workgroups_dir(self.teaparty_home), f'{wg_name}.yaml')
        else:
            yaml_path = os.path.join(management_workgroups_dir(self.teaparty_home), f'{wg_name}.yaml')
        try:
            toggle_workgroup_membership(yaml_path, kind, name, active)
        except (FileNotFoundError, ValueError) as exc:
            return web.json_response({'error': str(exc)}, status=404)
        return web.json_response({'ok': True})

    async def _handle_workgroups(self, request: web.Request) -> web.Response:
        try:
            team = load_management_team(teaparty_home=self.teaparty_home)
            workgroups = load_management_workgroups(team, teaparty_home=self.teaparty_home)
            members_lower = {m.lower() for m in team.members_workgroups}
            return web.json_response([
                self._serialize_workgroup(w, active=w.name.lower() in members_lower)
                for w in workgroups
            ])
        except Exception:
            return web.json_response([])

    async def _handle_workgroup_detail(self, request: web.Request) -> web.Response:
        name = request.match_info['name']
        project_slug = request.rel_url.query.get('project')
        project_dir: str | None = None
        try:
            if project_slug:
                project_dir = self._lookup_project_path(project_slug)
                if project_dir is None:
                    return web.json_response({'error': f'project not found: {project_slug}'}, status=404)
                team = load_project_team(project_dir)
                workgroups = resolve_workgroups(
                    team.workgroups, project_dir=project_dir, teaparty_home=self.teaparty_home
                )
            else:
                mgmt_team = load_management_team(teaparty_home=self.teaparty_home)
                workgroups = load_management_workgroups(mgmt_team, teaparty_home=self.teaparty_home)
        except FileNotFoundError as exc:
            return web.json_response({'error': str(exc)}, status=404)

        catalog = merge_catalog(
            management_dir(self.teaparty_home),
            project_teaparty_dir(project_dir) if project_dir else None,
        )
        org_catalog_agents: list[str] = catalog.agents
        org_hooks: list[dict] = catalog.hooks
        # Management-only set for 'shared' vs 'local' source tagging in the serializer.
        org_agents_set: set[str] = set(
            discover_agents(management_agents_dir(self.teaparty_home))
        )

        parent_humans = team.humans if project_slug else mgmt_team.humans
        members_lower: set[str] | None = (
            {m.lower() for m in team.members_workgroups} if project_slug else None
        )
        for w in workgroups:
            if w.name == name:
                wg_active = (w.name.lower() in members_lower) if members_lower is not None else None
                return web.json_response(
                    self._serialize_workgroup(
                        w, detail=True,
                        org_agents=org_agents_set,
                        org_catalog_agents=org_catalog_agents,
                        org_hooks_catalog=org_hooks,
                        active=wg_active,
                        parent_humans=parent_humans,
                    )
                )
        return web.json_response({'error': f'workgroup not found: {name}'}, status=404)

    async def _handle_workgroup_patch(self, request: web.Request) -> web.Response:
        name = request.match_info['name']
        project_slug = request.rel_url.query.get('project')
        project_dir: str | None = None
        if project_slug:
            project_dir = self._lookup_project_path(project_slug)
            if project_dir is None:
                return web.json_response({'error': f'project not found: {project_slug}'}, status=404)
            yaml_path = os.path.join(project_workgroups_dir(project_dir), f'{name}.yaml')
            if not os.path.exists(yaml_path):
                # Legacy fallback
                yaml_path = os.path.join(project_dir, '.teaparty.local', 'workgroups', f'{name}.yaml')
            if not os.path.exists(yaml_path):
                yaml_path = os.path.join(management_workgroups_dir(self.teaparty_home), f'{name}.yaml')
        else:
            yaml_path = os.path.join(management_workgroups_dir(self.teaparty_home), f'{name}.yaml')
        if not os.path.exists(yaml_path):
            return web.json_response({'error': f'workgroup not found: {name}'}, status=404)
        try:
            body = await request.json()
        except Exception:
            return web.json_response({'error': 'invalid JSON body'}, status=400)
        with open(yaml_path) as f:
            data = yaml.safe_load(f) or {}
        members = data.setdefault('members', {})
        if 'agents' in body:
            if not isinstance(body['agents'], list):
                return web.json_response({'error': 'agents must be a list'}, status=400)
            members['agents'] = body['agents']
        if 'hooks' in body:
            if not isinstance(body['hooks'], list):
                return web.json_response({'error': 'hooks must be a list'}, status=400)
            members['hooks'] = body['hooks']
        if 'artifacts' in body:
            if not isinstance(body['artifacts'], list):
                return web.json_response({'error': 'artifacts must be a list'}, status=400)
            data['artifacts'] = body['artifacts']
        with open(yaml_path, 'w') as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=False)
        wg = load_workgroup(yaml_path)
        catalog = merge_catalog(
            management_dir(self.teaparty_home),
            project_teaparty_dir(project_dir) if project_dir else None,
        )
        return web.json_response(
            self._serialize_workgroup(
                wg, detail=True,
                org_agents=set(discover_agents(management_agents_dir(self.teaparty_home))),
                org_catalog_agents=catalog.agents,
                org_hooks_catalog=catalog.hooks,
            )
        )

    def _agent_settings_path(self, agent_dir: str) -> str:
        return os.path.join(agent_dir, 'settings.yaml')

    def _read_agent_settings(self, agent_dir: str) -> dict:
        path = self._agent_settings_path(agent_dir)
        if not os.path.isfile(path):
            return {}
        try:
            with open(path) as f:
                return yaml.safe_load(f) or {}
        except (OSError, yaml.YAMLError):
            return {}

    def _write_agent_settings(self, agent_dir: str, data: dict) -> None:
        path = self._agent_settings_path(agent_dir)
        with open(path, 'w') as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=False)

    def _strip_frontmatter_field(self, agent_md_path: str, field: str) -> None:
        """Remove ``field`` from the agent.md frontmatter if present. Leaves
        the prose body untouched. Used when ownership of a field moves out
        of frontmatter (e.g. tools → settings.yaml permissions.allow)."""
        from teaparty.config.config_reader import _FRONTMATTER_RE
        try:
            with open(agent_md_path) as f:
                content = f.read()
        except OSError:
            return
        m = _FRONTMATTER_RE.match(content)
        if not m:
            return
        fm = yaml.safe_load(m.group(1)) or {}
        if field not in fm:
            return
        fm.pop(field)
        body = m.group(2)
        fm_str = yaml.dump(fm, default_flow_style=False, sort_keys=False).rstrip()
        with open(agent_md_path, 'w') as f:
            f.write(f'---\n{fm_str}\n---\n{body}')

    async def _handle_agent_detail(self, request: web.Request) -> web.Response:
        name = request.match_info['name']
        project_slug = request.rel_url.query.get('project')
        path: str | None = None
        if project_slug:
            project_dir = self._lookup_project_path(project_slug)
            if project_dir is None:
                return web.json_response({'error': f'project not found: {project_slug}'}, status=404)
            proj_path = os.path.join(project_agents_dir(project_dir), name, 'agent.md')
            if os.path.exists(proj_path):
                path = proj_path
        if path is None:
            org_path = os.path.join(management_agents_dir(self.teaparty_home), name, 'agent.md')
            if os.path.exists(org_path):
                path = org_path
        if path is None:
            return web.json_response({'error': f'agent not found: {name}'}, status=404)
        fm = read_agent_frontmatter(path)
        # settings.yaml permissions.allow is authoritative for tool
        # assignments (Claude Code uses permissions.allow, not frontmatter
        # tools, for MCP auto-approval). Fall back to frontmatter tools
        # only for agents not yet migrated to settings.yaml.
        settings = self._read_agent_settings(os.path.dirname(path))
        allow = (settings.get('permissions') or {}).get('allow')
        if allow is not None:
            fm['tools'] = ', '.join(allow)
        fm['_path'] = path
        fm['_dir'] = os.path.dirname(path)
        return web.json_response(fm)

    async def _handle_agent_patch(self, request: web.Request) -> web.Response:
        name = request.match_info['name']
        project_slug = request.rel_url.query.get('project')
        path: str | None = None
        if project_slug:
            project_dir = self._lookup_project_path(project_slug)
            if project_dir is None:
                return web.json_response({'error': f'project not found: {project_slug}'}, status=404)
            proj_path = os.path.join(project_agents_dir(project_dir), name, 'agent.md')
            if os.path.exists(proj_path):
                path = proj_path
        if path is None:
            org_path = os.path.join(management_agents_dir(self.teaparty_home), name, 'agent.md')
            if os.path.exists(org_path):
                path = org_path
        if path is None:
            return web.json_response({'error': f'agent not found: {name}'}, status=404)
        try:
            body = await request.json()
        except Exception:
            return web.json_response({'error': 'invalid JSON body'}, status=400)
        if not isinstance(body, dict):
            return web.json_response({'error': 'body must be a JSON object'}, status=400)
        # Route 'tools' updates to settings.yaml permissions.allow (the
        # field Claude Code actually honors); everything else continues
        # to write into agent.md frontmatter.
        fm_updates = dict(body)
        agent_dir = os.path.dirname(path)
        if 'tools' in fm_updates:
            tools_value = fm_updates.pop('tools') or ''
            tool_list = [t.strip() for t in tools_value.split(',') if t.strip()]
            settings = self._read_agent_settings(agent_dir)
            perms = settings.get('permissions') or {}
            perms['allow'] = tool_list
            settings['permissions'] = perms
            self._write_agent_settings(agent_dir, settings)
            # settings.yaml is now the single source of truth — drop any
            # stale `tools:` from frontmatter to avoid divergence.
            self._strip_frontmatter_field(path, 'tools')
        if fm_updates:
            write_agent_frontmatter(path, fm_updates)
        fm = read_agent_frontmatter(path)
        settings = self._read_agent_settings(agent_dir)
        allow = (settings.get('permissions') or {}).get('allow')
        if allow is not None:
            fm['tools'] = ', '.join(allow)
        return web.json_response(fm)

    async def _handle_catalog(self, request: web.Request) -> web.Response:
        slug = request.match_info['project']
        project_dir = self._lookup_project_path(slug)
        if project_dir is None:
            return web.json_response({'error': f'project not found: {slug}'}, status=404)
        catalog = merge_catalog(
            management_dir(self.teaparty_home),
            project_teaparty_dir(project_dir),
        )
        return web.json_response({
            'agents': catalog.agents,
            'skills': catalog.skills,
            'hooks': catalog.hooks,
            'tools': self._get_tools_catalog(),
        })

    async def _handle_catalog_org(self, request: web.Request) -> web.Response:
        catalog = merge_catalog(management_dir(self.teaparty_home))
        return web.json_response({
            'agents': catalog.agents,
            'skills': catalog.skills,
            'hooks': catalog.hooks,
            'tools': self._get_tools_catalog(),
        })

    def _get_tools_catalog(self) -> list[str]:
        """Return built-in + MCP tool names for the config UI catalog."""
        builtins = [
            'Read', 'Glob', 'Grep', 'Bash', 'Write', 'Edit',
            'WebSearch', 'WebFetch', 'Send', 'Reply',
            'TodoRead', 'TodoWrite', 'NotebookRead', 'NotebookEdit',
        ]
        try:
            from teaparty.mcp.server.main import list_mcp_tool_names
            return builtins + list_mcp_tool_names()
        except Exception:
            return builtins

    # ── Message handlers ──────────────────────────────────────────────────────

    async def _handle_conversations_list(self, request: web.Request) -> web.Response:
        type_str = request.rel_url.query.get('type', '')
        if type_str:
            try:
                conv_type = _resolve_conversation_type(type_str)
            except KeyError:
                return web.json_response(
                    {'error': f'unknown conversation type: {type_str}'}, status=400)
        else:
            conv_type = None

        # Route office_manager type to the persistent OM bus (issue #290)
        if conv_type == ConversationType.OFFICE_MANAGER:
            bus = self._get_agent_bus('office-manager')
            convs = bus.active_conversations(conv_type)
            result = []
            for c in convs:
                d = self._serialize_conversation(c)
                session = self._agent_sessions.get('om')
                title = (
                    (session.conversation_title if session else None)
                    or read_session_title(self.teaparty_home, 'office-manager', '')
                )
                if title:
                    d['title'] = title
                result.append(d)
            return web.json_response(result)

        # Route project_manager type to the persistent PM bus
        if conv_type == ConversationType.PROJECT_MANAGER:
            bus = self._get_agent_bus('project-manager')
            convs = bus.active_conversations(conv_type)
            result = []
            for c in convs:
                d = self._serialize_conversation(c)
                # qualifier is '{slug}:{user}' — strip the 'pm:' prefix
                qualifier = c.id[len('pm:'):] if c.id.startswith('pm:') else ''
                if qualifier:
                    session = self._agent_sessions.get(f'pm:{qualifier}')
                    title = (
                        (session.conversation_title if session else None)
                        or read_session_title(self.teaparty_home, 'project-manager', qualifier)
                    )
                    if title:
                        d['title'] = title
                result.append(d)
            return web.json_response(result)

        # Route proxy type to the persistent proxy bus (issue #331)
        if conv_type == ConversationType.PROXY:
            bus = self._get_agent_bus('proxy')
            convs = bus.active_conversations(conv_type)
            result = []
            for c in convs:
                d = self._serialize_conversation(c)
                qualifier = c.id[len('proxy:'):] if c.id.startswith('proxy:') else ''
                if qualifier:
                    session = self._agent_sessions.get(f'proxy:{qualifier}')
                    title = (
                        (session.conversation_title if session else None)
                        or read_session_title(self.teaparty_home, 'proxy', qualifier)
                    )
                    if title:
                        d['title'] = title
                result.append(d)
            return web.json_response(result)

        # Aggregate across all active session buses
        convs = []
        for bus in self._buses.values():
            try:
                convs.extend(bus.active_conversations(conv_type))
            except Exception:
                pass

        return web.json_response([self._serialize_conversation(c) for c in convs])

    async def _handle_conversation_get(self, request: web.Request) -> web.Response:
        """Return ``{messages, cursor}`` for a conversation (issue #398).

        The cursor is the atomic watermark captured in the same read as the
        messages. Clients carry it in a WebSocket ``subscribe`` frame so the
        server can deliver the join between fetch and live stream exactly
        once.
        """
        conv_id = request.match_info['id']
        bus = self._bus_for_conversation(conv_id)
        if bus is None:
            return web.json_response({'messages': [], 'cursor': ''}, status=200)

        # Task conv IDs need remapping: the frontend asks for
        # task:{project}:{session_id}:{dispatch_id} but the child's bus
        # stores the conversation as job:{project}:{dispatch_id} (issue #389).
        bus_conv_id = conv_id
        if conv_id.startswith('task:'):
            parts = conv_id.split(':')
            if len(parts) >= 4:
                project_slug = parts[1]
                dispatch_id = ':'.join(parts[3:])
                bus_conv_id = f'job:{project_slug}:{dispatch_id}'

        messages, cursor = bus.receive_since_cursor(bus_conv_id, '')
        return web.json_response({
            'messages': [self._serialize_message(m) for m in messages],
            'cursor': cursor,
        })

    async def _handle_conversation_post(self, request: web.Request) -> web.Response:
        conv_id = request.match_info['id']
        try:
            body = await request.json()
            content = body.get('content', '')
        except Exception:
            return web.json_response({'error': 'invalid JSON body'}, status=400)

        if not content:
            return web.json_response({'error': 'content is required'}, status=400)

        # Human interjection into an agent-to-agent conversation (issue #383).
        # The bridge finds the interjection socket for the active session and
        # forwards the message so the agent is --resumed with the human's input.
        if conv_id.startswith('agent:'):
            return await self._handle_agent_conversation_post(conv_id, content)

        bus = self._bus_for_conversation(conv_id)
        if bus is None:
            return web.json_response({'error': f'conversation not found: {conv_id}'}, status=404)

        # Auto-create the conversation on first POST so it appears in active_conversations()
        # (sidebar) and the human doesn't need to reload the page.
        if conv_id == 'om':
            bus.create_conversation(ConversationType.OFFICE_MANAGER, '')
        elif conv_id.startswith('pm:'):
            qualifier = conv_id[len('pm:'):]
            bus.create_conversation(ConversationType.PROJECT_MANAGER, qualifier)
        elif conv_id.startswith('proxy:'):
            qualifier = conv_id[len('proxy:'):]
            bus.create_conversation(ConversationType.PROXY, qualifier)
        elif conv_id.startswith('config:'):
            qualifier = conv_id[len('config:'):]
            bus.create_conversation(ConversationType.CONFIG_LEAD, qualifier)
        elif conv_id.startswith('lead:'):
            parts = conv_id.split(':', 2)
            qualifier = parts[2] if len(parts) > 2 else ''
            bus.create_conversation(ConversationType.PROJECT_LEAD, qualifier)

        try:
            msg_id = bus.send(conv_id, 'human', content)
        except ValueError as exc:
            return web.json_response({'error': str(exc)}, status=409)

        # Telemetry: chat_message_sent (Issue #405).
        try:
            from teaparty import telemetry
            from teaparty.telemetry import events as _telem_events
            target_session = ''
            telem_scope = 'management'
            if conv_id.startswith('job:'):
                _parts = conv_id.split(':')
                if len(_parts) >= 3:
                    telem_scope = _parts[1]
                    target_session = _parts[2]
            telemetry.record_event(
                _telem_events.CHAT_MESSAGE_SENT,
                scope=telem_scope,
                session_id=target_session or None,
                data={
                    'conv_id':           conv_id,
                    'target_session_id': target_session,
                    'content_len':       len(content),
                    'was_awaiting_input': False,
                },
            )
        except Exception:
            pass

        # Implicit resume (issue #403): if this message targets a session
        # in a paused project, resume the smallest subtree containing
        # the target before invoking the agent.
        #
        #   lead:{lead}:{qualifier}       → resume every top-level job
        #                                   dispatched by that lead
        #                                   (project-wide)
        #   job:{slug}:{session_id}[:{d}] → resume just that job's
        #                                   subtree
        paused_slug = ''
        target_root_sid = ''  # empty → resume whole project
        if conv_id.startswith('lead:'):
            parts = conv_id.split(':', 2)
            if len(parts) > 1:
                paused_slug = self._slug_for_lead(parts[1])
        elif conv_id.startswith('job:'):
            parts = conv_id.split(':')
            if len(parts) >= 3:
                paused_slug = parts[1]
                target_root_sid = parts[2]
        if paused_slug and paused_slug in self._paused_projects:
            from teaparty.workspace.pause_resume import (
                resume_project_subtree, resume_session_subtree,
            )
            sessions_dir = self._sessions_dir_for_project(paused_slug)
            if sessions_dir:
                for agent_session in self._project_owner_sessions(paused_slug):
                    try:
                        try:
                            agent_session.rehydrate_paused_factories(
                                paused_slug, sessions_dir)
                        except Exception:
                            _log.exception('factory rehydration failed')
                        if target_root_sid:
                            await resume_session_subtree(
                                target_root_sid, sessions_dir, agent_session)
                        else:
                            await resume_project_subtree(
                                paused_slug, sessions_dir, agent_session)
                    except Exception:
                        _log.exception(
                            'implicit resume failed for %s', paused_slug)
            # Only clear the project-paused flag if the entire subtree
            # was resumed. A per-job resume leaves other jobs paused,
            # so keep the flag set for the project.
            if not target_root_sid:
                self._paused_projects.discard(paused_slug)
                project_path = self._lookup_project_path(paused_slug)
                if project_path:
                    self._remove_paused_marker(project_path)

        # Invoke the agent asynchronously; reply will appear in the bus and
        # be broadcast by MessageRelay.
        if conv_id == 'om':
            asyncio.create_task(self._invoke_om())
        elif conv_id.startswith('pm:'):
            asyncio.create_task(self._invoke_pm(qualifier))
        elif conv_id.startswith('proxy:'):
            # Skip auto-invoke when an EscalationListener owns the loop
            # for this qualifier — the listener fires the proxy itself
            # with the correct cwd / teaparty_home / scope.  A parallel
            # HTTP-triggered invoke would double-respond per human turn
            # and run the proxy in the wrong cwd (the skill would fail
            # to Read ./QUESTION.md).
            from teaparty.mcp.registry import is_escalation_active
            if not is_escalation_active(qualifier):
                asyncio.create_task(self._invoke_proxy(qualifier))
        elif conv_id.startswith('config:'):
            asyncio.create_task(self._invoke_config_lead(qualifier))
        elif conv_id.startswith('lead:'):
            parts = conv_id.split(':', 2)
            lead_name = parts[1] if len(parts) > 1 else ''
            lead_qualifier = parts[2] if len(parts) > 2 else ''
            if lead_name:
                asyncio.create_task(self._invoke_project_lead(lead_name, lead_qualifier))
        elif conv_id.startswith('job:'):
            # Resume the CfA session so the orchestrator processes the human's message.
            parts = conv_id.split(':')
            if len(parts) >= 3:
                project_slug = parts[1]
                session_id = parts[2]
                asyncio.create_task(self._resume_job_session(project_slug, session_id))

        return web.json_response({'id': msg_id})

    async def _handle_agent_conversation_post(
        self, conv_id: str, content: str,
    ) -> web.Response:
        """Handle a human message posted to an agent-to-agent conversation.

        Finds the AgentSession whose BusEventListener owns this
        conversation and calls ``handle_interjection`` directly — the
        bridge and the listener share a process, no IPC needed.
        """
        listener = self._find_interjection_listener(conv_id)
        if listener is None:
            return web.json_response(
                {'error': f'No active session found for conversation: {conv_id}'},
                status=404,
            )

        try:
            response = await listener.handle_interjection(conv_id, content)
        except Exception as exc:
            return web.json_response(
                {'error': f'Interjection failed: {exc}'}, status=502,
            )

        if response.get('status') == 'error':
            return web.json_response(
                {'error': response.get('reason', 'unknown error')}, status=409,
            )

        # Telemetry: interjection_received — human typed into an agent
        # conversation that wasn't awaiting input (Issue #405).
        try:
            from teaparty import telemetry
            from teaparty.telemetry import events as _telem_events
            telemetry.record_event(
                _telem_events.INTERJECTION_RECEIVED,
                scope='management',
                data={
                    'conv_id': conv_id,
                    'content_len': len(content),
                    'was_session_awaiting_child': False,
                },
            )
        except Exception:
            pass

        return web.json_response({'status': 'ok'})

    def _find_interjection_listener(self, conv_id: str):
        """Return the BusEventListener whose bus owns ``conv_id``.

        Walks active AgentSessions, checks each one's bus for an
        agent_context record matching ``conv_id``, and returns that
        session's listener.  Returns None if no active session owns it.
        """
        for agent_session in self._agent_sessions.values():
            bus = getattr(agent_session, '_bus', None)
            listener = getattr(agent_session, '_bus_listener', None)
            if bus is None or listener is None:
                continue
            try:
                if bus.get_agent_context(conv_id) is not None:
                    return listener
            except Exception:
                continue
        return None

    async def _invoke_agent(
        self,
        *,
        session_key: str,
        agent_name: str,
        qualifier: str,
        conversation_type: ConversationType,
        cwd: str,
        teaparty_home: str = '',
        org_home: str = '',
        scope: str = 'management',
        agent_role: str = '',
        dispatches: bool = False,
        post_invoke_hook=None,
        build_prompt_hook=None,
        project_slug: str = '',
        launch_cwd_override: str = '',
    ) -> None:
        """Unified agent invocation — one codepath for all agent types.

        Creates or reuses an AgentSession, acquires a per-qualifier lock
        to serialize concurrent invocations, and delegates to invoke().

        teaparty_home: sessions live where the work lives. Management agents
        use the teaparty repo's .teaparty/. Project agents use the project
        repo's .teaparty/.
        """
        effective_home = teaparty_home or self.teaparty_home

        if session_key not in self._agent_locks:
            self._agent_locks[session_key] = asyncio.Lock()
        lock = self._agent_locks[session_key]

        async with lock:
            if session_key not in self._agent_sessions:
                self._agent_sessions[session_key] = AgentSession(
                    effective_home,
                    agent_name=agent_name,
                    scope=scope,
                    qualifier=qualifier,
                    conversation_type=conversation_type,
                    agent_role=agent_role or agent_name,
                    llm_backend=self._llm_backend,
                    dispatches=dispatches,
                    post_invoke_hook=post_invoke_hook,
                    build_prompt_hook=build_prompt_hook,
                    on_dispatch=self._broadcast_dispatch,
                    project_slug=project_slug,
                    paused_check=(
                        (lambda s=project_slug: s in self._paused_projects)
                        if project_slug else None
                    ),
                    org_home=org_home or None,
                    # Issue #420: supply the bridge's proxy invocation hook
                    # so AskQuestion routes through the proxy + /escalation
                    # skill.  The proxy agent itself is excluded — its own
                    # EscalationListener (if any) must not recurse through
                    # itself.
                    proxy_invoker_fn=(
                        self._invoke_proxy
                        if agent_name != 'proxy' else None
                    ),
                )
            session = self._agent_sessions[session_key]
            try:
                await session.invoke(
                    cwd=cwd, launch_cwd_override=launch_cwd_override,
                )
            except Exception:
                _log.exception('%s invocation failed for %r', agent_name, qualifier)
                try:
                    session.send_agent_message(
                        'Sorry, I encountered an error and could not respond. '
                        'Please try again.'
                    )
                except Exception:
                    _log.exception(
                        'Failed to write error message for %s %r', agent_name, qualifier,
                    )

    async def _invoke_om(self) -> None:
        """Invoke the office manager agent.

        Runs as a fire-and-forget asyncio task. The OM agent reads the conversation
        history, responds, and writes its reply to the OM bus. MessageRelay picks
        up the reply and broadcasts it to WebSocket clients.

        Concurrent invocations queue via an asyncio.Lock — the second message
        begins only after the first completes, ensuring the --resume session ID
        from the first turn is available to the second.

        On runner failure, writes an error message to the bus so the human sees
        feedback rather than silence.
        """
        await self._invoke_agent(
            session_key='om',
            agent_name='office-manager',
            qualifier='',
            conversation_type=ConversationType.OFFICE_MANAGER,
            dispatches=True,
            cwd=self._repo_root,
        )

    async def _invoke_pm(self, qualifier: str) -> None:
        """Invoke the project manager agent for the given conversation qualifier.

        qualifier is '{project_slug}:{user_id}' e.g. 'jainai:primus'.
        Runs as a fire-and-forget asyncio task. Concurrent invocations for the
        same qualifier queue via an asyncio.Lock.
        """
        parts = qualifier.split(':', 1)
        project_slug = parts[0]
        project_path = self._lookup_project_path(project_slug)
        cwd = project_path if project_path is not None else self._repo_root
        # Sessions live where the work lives: project repo's .teaparty/.
        project_tp = os.path.join(cwd, '.teaparty') if project_path else self.teaparty_home
        await self._invoke_agent(
            session_key=f'pm:{qualifier}',
            agent_name='project-manager',
            agent_role=f'{project_slug}-project-manager',
            qualifier=qualifier,
            conversation_type=ConversationType.PROJECT_MANAGER,
            teaparty_home=project_tp,
            scope='project',
            cwd=cwd,
            project_slug=project_slug,
        )

    async def _invoke_proxy(
        self,
        qualifier: str,
        cwd: str | None = None,
        teaparty_home: str = '',
        scope: str = 'management',
    ) -> None:
        """Invoke the proxy agent for the given conversation qualifier.

        Runs as a fire-and-forget asyncio task. The proxy agent reads the
        conversation history and ACT-R memory, responds, processes any
        [CORRECTION:...] signals, and writes its reply to the proxy bus.
        MessageRelay picks up the reply and broadcasts it to WebSocket clients.

        Concurrent invocations for the same qualifier queue via an asyncio.Lock —
        the second message begins only after the first completes, ensuring the
        --resume session ID from the first turn is available to the second.

        On runner failure, writes an error message to the bus so the human sees
        feedback rather than silence.

        ``cwd`` is None for ordinary proxy chat — the registry resolves the
        proxy's launch_cwd to the repo root.  The escalation path (issue #420)
        passes a per-escalation session directory, which becomes the proxy's
        ``launch_cwd_override`` so ``./QUESTION.md`` resolves correctly.

        ``teaparty_home``/``scope`` default to the bridge's management home.
        The escalation path passes the caller's home and scope so the proxy's
        escalation session lives alongside the caller's session — required for
        ``build_dispatch_tree`` to walk into the escalation's child node.
        """
        from teaparty.proxy.hooks import proxy_post_invoke, proxy_build_prompt
        await self._invoke_agent(
            session_key=f'proxy:{qualifier}',
            agent_name='proxy',
            agent_role='proxy',
            qualifier=qualifier,
            conversation_type=ConversationType.PROXY,
            cwd=cwd if cwd is not None else self._repo_root,
            launch_cwd_override=cwd or '',
            teaparty_home=teaparty_home,
            scope=scope,
            post_invoke_hook=proxy_post_invoke,
            build_prompt_hook=proxy_build_prompt,
        )

    async def _invoke_config_lead(self, qualifier: str) -> None:
        """Invoke the configuration-lead agent for the given conversation qualifier.

        Runs as a fire-and-forget asyncio task. The config lead agent reads the
        conversation history and responds. MessageRelay picks up the reply and
        broadcasts it to WebSocket clients.

        Concurrent invocations for the same qualifier queue via an asyncio.Lock.

        On runner failure, writes an error message to the bus so the human sees
        feedback rather than silence.
        """
        cwd = self._cwd_for_config_qualifier(qualifier)
        # Config lead scope follows the qualifier: management-level work stays
        # in the teaparty repo, project-level work uses the project repo.
        if cwd != self._repo_root:
            config_tp = os.path.join(cwd, '.teaparty')
            config_scope = 'project'
        else:
            config_tp = self.teaparty_home
            config_scope = 'management'
        await self._invoke_agent(
            session_key=f'config:{qualifier}',
            agent_name='configuration-lead',
            qualifier=qualifier,
            conversation_type=ConversationType.CONFIG_LEAD,
            teaparty_home=config_tp,
            scope=config_scope,
            dispatches=True,
            cwd=cwd,
        )

    async def _invoke_project_lead(self, lead_name: str, qualifier: str) -> None:
        """Invoke a project lead agent for a direct human conversation.

        Runs as a fire-and-forget asyncio task. The lead agent reads the
        conversation history and responds. MessageRelay picks up the reply
        and broadcasts it to WebSocket clients.
        """
        key = f'{lead_name}:{qualifier}'
        from teaparty.config.roster import resolve_lead_project_path
        project_path = resolve_lead_project_path(lead_name, self.teaparty_home)
        cwd = project_path if project_path else self._repo_root
        project_tp = os.path.join(cwd, '.teaparty') if project_path else self.teaparty_home
        await self._invoke_agent(
            session_key=f'pl:{key}',
            agent_name=lead_name,
            qualifier=key,
            conversation_type=ConversationType.PROJECT_LEAD,
            teaparty_home=project_tp,
            org_home=self.teaparty_home if project_path else '',
            scope='project',
            cwd=cwd,
            project_slug=self._slug_for_lead(lead_name),
        )

    def _cwd_for_config_qualifier(self, qualifier: str) -> str:
        """Resolve the working directory for a config lead invocation.

        Qualifiers that encode a project slug (e.g. 'wg:{slug}:{name}',
        'agent:{slug}:{name}', 'project:{slug}') run in the project's directory.
        Management-level qualifiers run in the repo root.
        """
        # qualifier forms: 'management', 'project:{slug}', 'wg:{slug}:{name}',
        # 'agent:{slug}:{name}', 'artifact:{slug}:{path}'
        slug: str | None = None
        parts = qualifier.split(':', 2)
        kind = parts[0]
        if kind == 'project' and len(parts) >= 2:
            slug = parts[1]
        elif kind in ('wg', 'agent', 'artifact') and len(parts) >= 2:
            slug = parts[1] or None  # empty string means org-level
        if slug:
            project_path = self._lookup_project_path(slug)
            if project_path:
                return project_path
        return self._repo_root

    # ── Artifact handlers ─────────────────────────────────────────────────────

    async def _handle_artifacts(self, request: web.Request) -> web.Response:
        project = request.match_info['project']
        if project == 'org':
            md_path = os.path.join(self.teaparty_home, '..', 'organization.md')
        else:
            proj_path = self._lookup_project_path(project)
            if proj_path is None:
                return web.json_response({'error': f'project not found: {project}'}, status=404)
            md_path = os.path.join(proj_path, 'project.md')

        md_path = os.path.normpath(md_path)
        try:
            with open(md_path) as f:
                content = f.read()
        except FileNotFoundError:
            return web.json_response({'error': f'artifact not found: {project}'}, status=404)

        sections = _parse_artifacts(content)
        return web.json_response(sections)

    async def _handle_pins(self, request: web.Request) -> web.Response:
        """GET /api/pins?scope={scope}&name={name}&project={slug}

        Unified pin endpoint. Returns pins from pins.yaml for any scope.

        Scopes:
          system  — .teaparty/management/pins.yaml (paths relative to repo root)
          project — {project}/.teaparty/project/pins.yaml (paths relative to project root)
          agent   — {agents_dir}/{name}/pins.yaml (paths relative to agent dir)
          workgroup — {workgroups_dir}/{name}/pins.yaml (paths relative to workgroup dir)
          job     — {project}/.sessions/{name}/pins.yaml (paths relative to session dir)
        """
        from teaparty.config.config_reader import (
            management_agents_dir,
            management_dir,
            management_workgroups_dir,
            project_agents_dir,
            project_sessions_dir,
            project_workgroups_dir,
            resolve_pins,
        )

        scope = request.rel_url.query.get('scope', '')
        name = request.rel_url.query.get('name', '')
        project_slug = request.rel_url.query.get('project', '')

        if scope == 'system':
            scope_dir = management_dir(self.teaparty_home)
            path_root = os.path.dirname(self.teaparty_home)  # repo root

        elif scope == 'project':
            proj_path = self._lookup_project_path(project_slug)
            if proj_path is None:
                return web.json_response({'error': f'project not found: {project_slug}'}, status=404)
            scope_dir = os.path.join(proj_path, '.teaparty', 'project')
            path_root = proj_path

        elif scope == 'agent':
            if not name:
                return web.json_response({'error': 'agent scope requires name'}, status=400)
            # Try project-level first, then management-level
            scope_dir = None
            path_root = None
            if project_slug:
                proj_path = self._lookup_project_path(project_slug)
                if proj_path:
                    candidate = os.path.join(project_agents_dir(proj_path), name)
                    if os.path.isdir(candidate):
                        scope_dir = candidate
                        path_root = candidate
            if scope_dir is None:
                candidate = os.path.join(management_agents_dir(self.teaparty_home), name)
                if os.path.isdir(candidate):
                    scope_dir = candidate
                    path_root = candidate
            if scope_dir is None:
                return web.json_response({'error': f'agent not found: {name}'}, status=404)
            # Fall back to defaults when no pins.yaml is configured: an
            # agent's own defining files (prompt + settings) are what the
            # config page should always show without requiring every agent
            # to opt in via pins.yaml.  If the agent has a pins.yaml, that
            # list is authoritative — we don't mix.
            result = resolve_pins(scope_dir, path_root)
            if not result and not os.path.isfile(os.path.join(scope_dir, 'pins.yaml')):
                for rel, label in (
                    ('agent.md', 'Prompt & Identity'),
                    ('settings.yaml', 'Tool & File Permissions'),
                ):
                    abs_path = os.path.normpath(os.path.join(path_root, rel))
                    if os.path.exists(abs_path):
                        result.append({
                            'path': abs_path,
                            'rel_path': rel,
                            'label': label,
                            'is_dir': os.path.isdir(abs_path),
                        })
            return web.json_response(result)

        elif scope == 'workgroup':
            if not name:
                return web.json_response({'error': 'workgroup scope requires name'}, status=400)
            scope_dir = None
            path_root = None
            if project_slug:
                proj_path = self._lookup_project_path(project_slug)
                if proj_path:
                    candidate = os.path.join(project_workgroups_dir(proj_path), name)
                    if os.path.isdir(candidate):
                        scope_dir = candidate
                        path_root = candidate
            if scope_dir is None:
                candidate = os.path.join(management_workgroups_dir(self.teaparty_home), name)
                if os.path.isdir(candidate):
                    scope_dir = candidate
                    path_root = candidate
            if scope_dir is None:
                return web.json_response({'error': f'workgroup not found: {name}'}, status=404)
            # Fall back to workgroup YAML artifacts field if no pins.yaml.
            result = resolve_pins(scope_dir, path_root)
            if not result:
                wg_yaml = os.path.join(scope_dir, name + '.yaml')
                if not os.path.isfile(wg_yaml):
                    # Workgroup YAML may live directly in the workgroups dir
                    wg_yaml = os.path.join(os.path.dirname(scope_dir), name + '.yaml')
                if os.path.isfile(wg_yaml):
                    with open(wg_yaml) as _f:
                        wg_data = yaml.safe_load(_f) or {}
                    for art in wg_data.get('artifacts', []):
                        rel = art.get('path', '') if isinstance(art, dict) else str(art)
                        label = (art.get('label', '') if isinstance(art, dict) else '') or os.path.basename(rel.rstrip('/\\'))
                        abs_path = os.path.normpath(os.path.join(path_root, rel))
                        result.append({'path': abs_path, 'rel_path': rel, 'label': label, 'is_dir': os.path.isdir(abs_path)})
            return web.json_response(result)

        elif scope == 'job':
            if not name or not project_slug:
                return web.json_response({'error': 'job scope requires name and project'}, status=400)
            proj_path = self._lookup_project_path(project_slug)
            if proj_path is None:
                return web.json_response({'error': f'project not found: {project_slug}'}, status=404)
            scope_dir = os.path.join(project_sessions_dir(proj_path), name)
            path_root = scope_dir

        else:
            return web.json_response({'error': f'unknown scope: {scope}'}, status=400)

        return web.json_response(resolve_pins(scope_dir, path_root))

    async def _handle_pins_patch(self, request: web.Request) -> web.Response:
        """PATCH /api/pins — add or remove a single pin for any scope.

        Query params mirror GET /api/pins: scope=, name=, project=
        Body: {action: 'add'|'remove', path: <abs_path>, label: <str>}
        """
        from teaparty.config.config_reader import (
            add_pin,
            remove_pin,
            management_dir,
            management_agents_dir,
            project_agents_dir,
            project_workgroups_dir,
            management_workgroups_dir,
            project_sessions_dir,
        )

        scope = request.rel_url.query.get('scope', '')
        name = request.rel_url.query.get('name', '')
        project_slug = request.rel_url.query.get('project', '')

        try:
            body = await request.json()
        except Exception:
            return web.json_response({'error': 'invalid JSON body'}, status=400)

        # Body: {"add": {"path": "...", "label": "..."}} or {"remove": {"path": "..."}}
        if 'add' in body:
            action = 'add'
            add_data = body['add']
            if not isinstance(add_data, dict):
                return web.json_response({'error': 'add must be an object'}, status=400)
            abs_path = add_data.get('path', '')
            label = add_data.get('label', '') or os.path.basename(abs_path.rstrip('/\\'))
        elif 'remove' in body:
            action = 'remove'
            remove_data = body['remove']
            if not isinstance(remove_data, dict):
                return web.json_response({'error': 'remove must be an object'}, status=400)
            abs_path = remove_data.get('path', '')
            label = ''
        else:
            return web.json_response({'error': 'body must have "add" or "remove" key'}, status=400)

        if not abs_path:
            return web.json_response({'error': 'path is required'}, status=400)

        # Resolve scope_dir and path_root using the same logic as _handle_pins
        if scope == 'system':
            scope_dir = management_dir(self.teaparty_home)
            path_root = os.path.dirname(self.teaparty_home)

        elif scope == 'project':
            proj_path = self._lookup_project_path(project_slug)
            if proj_path is None:
                return web.json_response({'error': f'project not found: {project_slug}'}, status=404)
            scope_dir = os.path.join(proj_path, '.teaparty', 'project')
            path_root = proj_path

        elif scope == 'agent':
            if not name:
                return web.json_response({'error': 'agent scope requires name'}, status=400)
            scope_dir = None
            path_root = None
            if project_slug:
                proj_path = self._lookup_project_path(project_slug)
                if proj_path:
                    candidate = os.path.join(project_agents_dir(proj_path), name)
                    if os.path.isdir(candidate):
                        scope_dir = candidate
                        path_root = candidate
            if scope_dir is None:
                candidate = os.path.join(management_agents_dir(self.teaparty_home), name)
                if os.path.isdir(candidate):
                    scope_dir = candidate
                    path_root = candidate
            if scope_dir is None:
                return web.json_response({'error': f'agent not found: {name}'}, status=404)

        elif scope == 'workgroup':
            if not name:
                return web.json_response({'error': 'workgroup scope requires name'}, status=400)
            scope_dir = None
            path_root = None
            if project_slug:
                proj_path = self._lookup_project_path(project_slug)
                if proj_path:
                    candidate = os.path.join(project_workgroups_dir(proj_path), name)
                    if os.path.isdir(candidate):
                        scope_dir = candidate
                        path_root = candidate
            if scope_dir is None:
                candidate = os.path.join(management_workgroups_dir(self.teaparty_home), name)
                if os.path.isdir(candidate):
                    scope_dir = candidate
                    path_root = candidate
            if scope_dir is None:
                return web.json_response({'error': f'workgroup not found: {name}'}, status=404)

        elif scope == 'job':
            if not name or not project_slug:
                return web.json_response({'error': 'job scope requires name and project'}, status=400)
            proj_path = self._lookup_project_path(project_slug)
            if proj_path is None:
                return web.json_response({'error': f'project not found: {project_slug}'}, status=404)
            scope_dir = os.path.join(project_sessions_dir(proj_path), name)
            path_root = scope_dir

        else:
            return web.json_response({'error': f'unknown scope: {scope}'}, status=400)

        if action == 'add':
            add_pin(scope_dir, path_root, abs_path, label)
        else:
            remove_pin(scope_dir, path_root, abs_path)

        return web.json_response({'ok': True})

    async def _handle_artifact_pins(self, request: web.Request) -> web.Response:
        """GET /api/artifacts/{project}/pins — return pins with absolute paths and is_dir.

        Reads from pins.yaml first; falls back to artifact_pins in project.yaml
        for backward compatibility.
        """
        from teaparty.config.config_reader import load_project_team, resolve_pins
        project = request.match_info['project']
        proj_path = self._lookup_project_path(project)
        if proj_path is None:
            return web.json_response({'error': f'project not found: {project}'}, status=404)

        # Try pins.yaml first
        scope_dir = os.path.join(proj_path, '.teaparty', 'project')
        result = resolve_pins(scope_dir, proj_path)
        if result:
            return web.json_response(result)

        # Fall back to artifact_pins in project.yaml
        try:
            team = load_project_team(project_dir=proj_path)
        except FileNotFoundError:
            return web.json_response([])

        result = []
        for pin in team.artifact_pins:
            rel = pin.get('path', '')
            label = pin.get('label') or os.path.basename(rel.rstrip('/\\')) or rel
            abs_path = os.path.normpath(os.path.join(proj_path, rel))
            result.append({
                'path': abs_path,
                'rel_path': rel,
                'label': label,
                'is_dir': os.path.isdir(abs_path),
            })
        return web.json_response(result)

    async def _handle_artifact_pins_patch(self, request: web.Request) -> web.Response:
        """PATCH /api/artifacts/{project}/pins — replace artifact_pins in project YAML."""
        project = request.match_info['project']
        proj_path = self._lookup_project_path(project)
        if proj_path is None:
            return web.json_response({'error': f'project not found: {project}'}, status=404)
        try:
            body = await request.json()
        except Exception:
            return web.json_response({'error': 'invalid JSON body'}, status=400)
        pins = body.get('artifact_pins')
        if not isinstance(pins, list):
            return web.json_response({'error': 'artifact_pins must be a list'}, status=400)
        from teaparty.config.config_reader import project_config_path
        yaml_path = project_config_path(proj_path)
        if not os.path.exists(yaml_path):
            # Legacy fallback
            legacy = os.path.join(proj_path, '.teaparty.local', 'project.yaml')
            if os.path.exists(legacy):
                yaml_path = legacy
            else:
                return web.json_response({'error': f'project config not found: {project}'}, status=404)
        with open(yaml_path) as f:
            data = yaml.safe_load(f) or {}
        data['artifact_pins'] = pins
        with open(yaml_path, 'w') as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=False)
        return web.json_response({'ok': True, 'artifact_pins': pins})

    _BINARY_CONTENT_TYPES = {
        '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg',
        '.png': 'image/png', '.gif': 'image/gif',
        '.svg': 'image/svg+xml', '.webp': 'image/webp',
        '.pdf': 'application/pdf',
    }

    async def _handle_file(self, request: web.Request) -> web.Response:
        path = request.rel_url.query.get('path', '')
        if not path:
            return web.json_response({'error': 'path parameter required'}, status=400)
        path = os.path.expanduser(path)
        if os.path.isdir(path):
            return web.json_response({'error': f'path is a directory: {path}'}, status=400)
        ext = os.path.splitext(path)[1].lower()
        binary_ct = self._BINARY_CONTENT_TYPES.get(ext)
        try:
            if binary_ct:
                with open(path, 'rb') as f:
                    body = f.read()
                return web.Response(body=body, content_type=binary_ct)
            else:
                with open(path) as f:
                    content = f.read()
                return web.Response(text=content, content_type='text/plain')
        except FileNotFoundError:
            return web.json_response({'error': f'file not found: {path}'}, status=404)
        except PermissionError:
            return web.json_response({'error': 'permission denied'}, status=403)

    async def _handle_session_file(self, request: web.Request) -> web.Response:
        """GET /api/session/{session_id}/file?path=<relative> — read a file from a session's worktree."""
        session_id = request.match_info['session_id']
        rel_path = request.rel_url.query.get('path', '')
        if not rel_path:
            return web.json_response({'error': 'path parameter required'}, status=400)

        infra_dir = self._resolve_session_infra(session_id)
        if not infra_dir:
            return web.json_response({'error': f'session not found: {session_id}'}, status=404)

        # Resolve worktree from infra_dir
        from teaparty.cfa.session import _resolve_worktree_path, _find_repo_root_from
        sessions_parent = os.path.dirname(infra_dir)
        project_dir = os.path.dirname(sessions_parent)
        worktree = _resolve_worktree_path(infra_dir, session_id, project_dir)
        if not worktree:
            # Fall back to project directory
            worktree = project_dir

        abs_path = os.path.normpath(os.path.join(worktree, rel_path))
        # Security: ensure path stays within worktree or project
        if not abs_path.startswith(worktree) and not abs_path.startswith(project_dir):
            return web.json_response({'error': 'path escapes worktree'}, status=403)

        ext = os.path.splitext(abs_path)[1].lower()
        binary_ct = self._BINARY_CONTENT_TYPES.get(ext)
        try:
            if binary_ct:
                with open(abs_path, 'rb') as f:
                    body = f.read()
                return web.Response(body=body, content_type=binary_ct)
            else:
                with open(abs_path) as f:
                    content = f.read()
                return web.Response(text=content, content_type='text/plain')
        except FileNotFoundError:
            return web.json_response({'error': f'file not found: {rel_path}'}, status=404)
        except PermissionError:
            return web.json_response({'error': 'permission denied'}, status=403)

    # ── Filesystem navigation handler ─────────────────────────────────────────

    def _resolve_session_worktree(self, session_id: str) -> str | None:
        """Resolve a session's worktree path from its session_id.

        Returns the absolute worktree path, or None if the session cannot
        be located.
        """
        if not session_id:
            return None
        infra_dir = self._resolve_session_infra(session_id)
        if not infra_dir:
            return None
        from teaparty.cfa.session import _resolve_worktree_path
        sessions_parent = os.path.dirname(infra_dir)
        project_dir = os.path.dirname(sessions_parent)
        return _resolve_worktree_path(infra_dir, session_id, project_dir)

    async def _handle_fs_list(self, request: web.Request) -> web.Response:
        """GET /api/fs/list?path=<p>|?project=<slug>|?session=<id> — list directory contents.

        Accepts an explicit ``path``, a ``project`` slug resolved to the
        project directory, or a ``session`` id resolved to the session's
        worktree.  Session takes precedence over project so job views
        always see the worktree files, not the project root.
        """
        path = request.rel_url.query.get('path', '')
        session = request.rel_url.query.get('session', '')
        project = request.rel_url.query.get('project', '')
        if not path and session:
            worktree = self._resolve_session_worktree(session)
            if not worktree:
                return web.json_response(
                    {'error': f'session not found: {session}'}, status=404)
            path = worktree
        if not path and project:
            proj_path = self._lookup_project_path(project)
            if proj_path is None:
                return web.json_response({'error': f'project not found: {project}'}, status=404)
            path = proj_path
        if not path:
            return web.json_response({'error': 'path, project, or session parameter required'}, status=400)
        try:
            entries = _list_directory(path)
        except FileNotFoundError as exc:
            return web.json_response({'error': str(exc)}, status=404)
        return web.json_response({'path': path, 'entries': entries})

    async def _handle_git_status(self, request: web.Request) -> web.Response:
        """GET /api/git-status?path=<p>|?project=<slug>|?session=<id> — git status for a worktree.

        Returns ``{files: {relative_path: status}}`` where status is
        ``'new'``, ``'modified'``, ``'deleted'``, or ``'session'`` (CfA
        session artifact surfaced even when gitignored).  Accepts the
        same parameter set as ``/api/fs/list``.
        """
        path = request.rel_url.query.get('path', '')
        session = request.rel_url.query.get('session', '')
        project = request.rel_url.query.get('project', '')
        if not path and session:
            worktree = self._resolve_session_worktree(session)
            if not worktree:
                return web.json_response(
                    {'error': f'session not found: {session}'}, status=404)
            path = worktree
        if not path and project:
            proj_path = self._lookup_project_path(project)
            if proj_path is None:
                return web.json_response(
                    {'error': f'project not found: {project}'}, status=404)
            path = proj_path
        if not path:
            return web.json_response(
                {'error': 'path or project parameter required'}, status=400)
        path = os.path.expanduser(path)
        if not os.path.isdir(path):
            return web.json_response(
                {'error': f'directory not found: {path}'}, status=404)
        files = parse_git_status(path)
        return web.json_response({'files': files})

    # ── Project management handlers ───────────────────────────────────────────

    async def _handle_projects_add(self, request: web.Request) -> web.Response:
        """POST /api/projects/add — register an existing directory as a project.

        Body: {"name": str, "path": str, "description": str, "decider": str}
        Response: updated management team serialization.
        """
        from teaparty.config.config_reader import add_project
        try:
            body = await request.json()
        except Exception:
            return web.json_response({'error': 'invalid JSON body'}, status=400)

        name = body.get('name', '').strip()
        path = body.get('path', '').strip()
        if not name or not path:
            return web.json_response({'error': 'name and path are required'}, status=400)

        try:
            team = add_project(
                name, path,
                teaparty_home=self.teaparty_home,
                description=body.get('description', ''),
                decider=body.get('decider', ''),
            )
        except ValueError as exc:
            return web.json_response({'error': str(exc)}, status=409)

        discovered_skills = discover_skills(
            management_skills_dir(self.teaparty_home)
        )
        return web.json_response({
            'ok': True,
            'management_team': self._serialize_management_team(
                team, discovered_skills=discovered_skills,
            ),
        })

    async def _handle_projects_create(self, request: web.Request) -> web.Response:
        """POST /api/projects/create — scaffold a new project directory and register it.

        Body: {"name": str, "path": str, "description": str, "decider": str}
        Response: updated management team serialization.
        """
        from teaparty.config.config_reader import create_project
        try:
            body = await request.json()
        except Exception:
            return web.json_response({'error': 'invalid JSON body'}, status=400)

        name = body.get('name', '').strip()
        path = body.get('path', '').strip()
        if not name or not path:
            return web.json_response({'error': 'name and path are required'}, status=400)

        try:
            team = create_project(
                name, path,
                teaparty_home=self.teaparty_home,
                description=body.get('description', ''),
                decider=body.get('decider', ''),
            )
        except ValueError as exc:
            return web.json_response({'error': str(exc)}, status=409)

        discovered_skills = discover_skills(
            management_skills_dir(self.teaparty_home)
        )
        return web.json_response({
            'ok': True,
            'management_team': self._serialize_management_team(
                team, discovered_skills=discovered_skills,
            ),
        })

    # ── Project pause / resume (issue #403) ───────────────────────────────

    def _sessions_dir_for_project(self, slug: str) -> str | None:
        """Return the sessions dir where the project lead's dispatch
        tree lives. The project lead runs with scope='project' and
        teaparty_home={project}/.teaparty, so its dispatched children
        are under {project}/.teaparty/project/sessions/.
        """
        path = self._lookup_project_path(slug)
        if not path:
            return None
        return os.path.join(path, '.teaparty', 'project', 'sessions')

    def _project_owner_sessions(self, slug: str) -> list:
        """Return the AgentSessions that own the project's dispatch tree.

        The duplication bug (issue #403 /chide review): iterating every
        live AgentSession for pause/resume populates unrelated OM /
        config-lead / proxy sessions with factories and tasks bound to
        the wrong bus, scope, and teaparty_home. The correct owner is
        the project-lead AgentSession whose ``project_slug`` matches.

        Multiple leads can match if two humans are chatting with the
        same project lead under different qualifiers — each has its own
        dispatch tree; pause/resume applies to all of them.
        """
        return [
            s for s in self._agent_sessions.values()
            if getattr(s, 'project_slug', '') == slug
        ]

    async def _handle_project_pause(self, request: web.Request) -> web.Response:
        """POST /api/projects/{slug}/pause — stop every running claude
        process for the project and set the per-project paused flag.
        """
        from teaparty.workspace.pause_resume import pause_project_subtree
        slug = request.match_info['slug']
        if not self._lookup_project_path(slug):
            return web.json_response(
                {'error': f'project not found: {slug}'}, status=404)
        sessions_dir = self._sessions_dir_for_project(slug)
        if sessions_dir is None:
            return web.json_response({'error': 'no sessions dir'}, status=500)

        owners = self._project_owner_sessions(slug)
        if not owners:
            return web.json_response(
                {'error': f'no active project-lead session for {slug}; '
                          f'open the lead chat first'},
                status=409)
        all_paused: list[str] = []
        for agent_session in owners:
            try:
                paused = await pause_project_subtree(
                    slug, sessions_dir, agent_session)
                all_paused.extend(paused)
            except Exception:
                _log.exception('pause failed for agent_session')
        self._paused_projects.add(slug)
        project_path = self._lookup_project_path(slug)
        if project_path:
            self._write_paused_marker(project_path)
        payload = json.dumps({
            'type': 'project_paused',
            'project': slug,
            'session_ids': sorted(set(all_paused)),
        })
        for ws in list(self._ws_clients):
            try:
                await ws.send_str(payload)
            except Exception:
                pass
        return web.json_response(
            {'ok': True, 'paused': sorted(set(all_paused))})

    async def _handle_project_resume(self, request: web.Request) -> web.Response:
        """POST /api/projects/{slug}/resume — rebuild the task chain
        per persisted phase and clear the paused flag.
        """
        from teaparty.workspace.pause_resume import resume_project_subtree
        slug = request.match_info['slug']
        if not self._lookup_project_path(slug):
            return web.json_response(
                {'error': f'project not found: {slug}'}, status=404)
        sessions_dir = self._sessions_dir_for_project(slug)
        if sessions_dir is None:
            return web.json_response({'error': 'no sessions dir'}, status=500)

        owners = self._project_owner_sessions(slug)
        if not owners:
            return web.json_response(
                {'error': f'no active project-lead session for {slug}; '
                          f'open the lead chat first'},
                status=409)
        all_resumed: list[str] = []
        for agent_session in owners:
            try:
                # Cross-restart: rebuild factories from disk before the
                # walker consults them. Idempotent — factories from a
                # live pause simply get replaced with equivalent ones.
                try:
                    agent_session.rehydrate_paused_factories(
                        slug, sessions_dir)
                except Exception:
                    _log.exception('factory rehydration failed')
                resumed = await resume_project_subtree(
                    slug, sessions_dir, agent_session)
                all_resumed.extend(resumed)
            except Exception:
                _log.exception('resume failed for agent_session')
        self._paused_projects.discard(slug)
        project_path = self._lookup_project_path(slug)
        if project_path:
            self._remove_paused_marker(project_path)
        payload = json.dumps({
            'type': 'project_resumed',
            'project': slug,
            'session_ids': sorted(set(all_resumed)),
        })
        for ws in list(self._ws_clients):
            try:
                await ws.send_str(payload)
            except Exception:
                pass
        return web.json_response(
            {'ok': True, 'resumed': sorted(set(all_resumed))})

    async def _handle_project_remove(self, request: web.Request) -> web.Response:
        """POST /api/projects/{slug}/remove — shut down all running jobs,
        unregister the project from the registry, and purge its telemetry.
        The project directory itself is left untouched.
        """
        from teaparty.config.config_reader import (
            remove_project, load_management_team, discover_projects,
        )
        from teaparty.workspace.pause_resume import pause_project_subtree
        from teaparty.telemetry.record import delete_scope

        slug = request.match_info['slug']

        # Resolve slug → registered name (they differ when the project name
        # differs from the directory basename).
        project_name: str | None = None
        try:
            team = load_management_team(teaparty_home=self.teaparty_home)
            for entry in discover_projects(team):
                if (os.path.basename(entry['path'].rstrip('/')) == slug
                        or entry['name'] == slug):
                    project_name = entry['name']
                    break
        except Exception:
            pass
        if project_name is None:
            return web.json_response(
                {'error': f'project not found: {slug}'}, status=404)

        # 1. Cancel all running jobs (best-effort — proceed regardless).
        sessions_dir = self._sessions_dir_for_project(slug)
        if sessions_dir is not None:
            for agent_session in self._project_owner_sessions(slug):
                try:
                    await pause_project_subtree(slug, sessions_dir, agent_session)
                except Exception:
                    _log.exception('remove: pause failed for %s', slug)
        self._paused_projects.discard(slug)

        # 2. Unregister from the project registry.
        try:
            remove_project(project_name, teaparty_home=self.teaparty_home)
        except ValueError as exc:
            return web.json_response({'error': str(exc)}, status=404)

        # 3. Purge telemetry for this scope.
        delete_scope(slug)

        return web.json_response({'ok': True})

    # ── Action handlers ───────────────────────────────────────────────────────

    async def _handle_withdraw(self, request: web.Request) -> web.Response:
        """Withdraw a job: kill processes, remove worktrees, preserve stats.

        Operates directly on the job directory — no engine socket required.
        """
        session_id = request.match_info['session_id']

        # Find the job's infra_dir
        infra_dir = self._resolve_session_infra(session_id)
        if not infra_dir:
            return web.json_response(
                {'error': f'session not found: {session_id}'}, status=404)

        # Derive project_root from job_dir path
        from teaparty.workspace.job_store import withdraw_job, project_root_from_job_dir
        if '/.teaparty/jobs/' not in infra_dir:
            return web.json_response(
                {'error': 'withdrawal requires .teaparty/jobs/ layout; '
                          'run migration first'}, status=400)
        project_root = project_root_from_job_dir(infra_dir)

        try:
            result = await withdraw_job(
                project_root=project_root, job_dir=infra_dir)
        except Exception as exc:
            _log.exception('Withdrawal failed for session %s', session_id)
            return web.json_response({'error': str(exc)}, status=502)

        # Broadcast withdrawal to connected WebSocket clients
        payload = json.dumps({
            'type': 'session_completed',
            'session_id': session_id,
            'terminal_state': 'WITHDRAWN',
        })
        for ws in list(self._ws_clients):
            try:
                await ws.send_str(payload)
            except Exception:
                pass

        # Telemetry — withdraw_clicked + session_withdrawn (Issue #405).
        try:
            from teaparty import telemetry
            from teaparty.telemetry import events as _telem_events
            project_slug = result.get('project_slug') or 'management'
            telemetry.record_event(
                _telem_events.WITHDRAW_CLICKED,
                scope=project_slug,
                session_id=session_id,
            )
            telemetry.record_event(
                _telem_events.SESSION_WITHDRAWN,
                scope=project_slug,
                session_id=session_id,
                data={
                    'phase_at_withdrawal': result.get('phase_at_withdrawal', ''),
                    'reason_len':          len(str(result.get('reason', '') or '')),
                },
            )
        except Exception:
            pass

        return web.json_response(result)

    async def _handle_job_status(self, request: web.Request) -> web.Response:
        """GET /api/jobs/{slug}/{session_id}/status — report liveness.

        Returns ``{status: 'running'|'sleeping'|'terminal'}``.
          - running:  the asyncio task is active in _active_job_tasks.
          - sleeping: no task is running, but the CfA state is non-terminal
                      (resumable — a POST or explicit wake will restart it).
          - terminal: the CfA state is globally terminal (COMPLETED_WORK,
                      WITHDRAWN, etc. — wake is a no-op).
        """
        slug = request.match_info['slug']
        session_id = request.match_info['session_id']
        key = f'{slug}:{session_id}'

        # Terminal wins: don't report 'running' for a finished session even
        # if the task is briefly still in the dict.
        infra_dir = self._resolve_session_infra(session_id)
        cfa_state = ''
        if infra_dir:
            from teaparty.cfa.statemachine.cfa_state import (
                load_state as _load_cfa, is_globally_terminal,
            )
            cfa_path = os.path.join(infra_dir, '.cfa-state.json')
            if os.path.isfile(cfa_path):
                try:
                    cfa = _load_cfa(cfa_path)
                    cfa_state = cfa.state
                    if is_globally_terminal(cfa_state):
                        return web.json_response(
                            {'status': 'terminal', 'cfa_state': cfa_state})
                except Exception:
                    pass

        task = self._active_job_tasks.get(key)
        if task is not None and not task.done():
            return web.json_response(
                {'status': 'running', 'cfa_state': cfa_state})

        return web.json_response(
            {'status': 'sleeping', 'cfa_state': cfa_state})

    async def _handle_job_wake(self, request: web.Request) -> web.Response:
        """POST /api/jobs/{slug}/{session_id}/wake — resume a sleeping session.

        Calls _resume_job_session without writing any message to the
        conversation.  The caller is expected to use this when they want
        to kick a session awake without bundling a chat message.  (Sending
        a message via POST /api/conversations/{id} already kicks — this
        endpoint is for the 'just wake it' case.)
        """
        slug = request.match_info['slug']
        session_id = request.match_info['session_id']
        await self._resume_job_session(slug, session_id)
        return web.json_response({'ok': True})

    async def _handle_escalation_get(self, request: web.Request) -> web.Response:
        """GET /api/projects/{slug}/escalation — per-gate escalation modes.

        Returns {gates: [...], modes: {state: mode}} where `gates` is the
        fixed list of CfA states that accept modes and `modes` is the
        project's configured overrides (absent keys use the default
        'when_unsure').
        """
        slug = request.match_info['slug']
        if not self._lookup_project_path(slug):
            return web.json_response(
                {'error': f'project not found: {slug}'}, status=404)
        return web.json_response({
            'gates': list(self._ESCALATION_GATES),
            'default': 'when_unsure',
            'valid_modes': sorted(self._ESCALATION_VALID_MODES),
            'modes': self._load_escalation_modes(slug),
        })

    async def _handle_escalation_patch(self, request: web.Request) -> web.Response:
        """PATCH /api/projects/{slug}/escalation — update one gate's mode.

        Body: {"state": "INTENT_ASSERT", "mode": "always"}.  Rewrites the
        `escalation` section of project.yaml; in-flight sessions are
        unaffected until they resume (escalation mode is read at session
        construction time).
        """
        slug = request.match_info['slug']
        project_path = self._lookup_project_path(slug)
        if not project_path:
            return web.json_response(
                {'error': f'project not found: {slug}'}, status=404)
        try:
            body = await request.json()
        except Exception:
            return web.json_response({'error': 'invalid JSON'}, status=400)
        state = body.get('state', '')
        mode = body.get('mode', '')
        if state not in self._ESCALATION_GATES:
            return web.json_response(
                {'error': f'unknown gate: {state}'}, status=400)
        if mode not in self._ESCALATION_VALID_MODES:
            return web.json_response(
                {'error': f'invalid mode: {mode}'}, status=400)

        # Rewrite project.yaml in place, preserving everything else.
        import yaml
        from teaparty.config.config_reader import project_config_path
        yaml_path = project_config_path(project_path)
        if not os.path.isfile(yaml_path):
            return web.json_response(
                {'error': f'project.yaml not found: {yaml_path}'}, status=404)
        with open(yaml_path) as f:
            data = yaml.safe_load(f) or {}
        escalation = dict(data.get('escalation') or {})
        # 'when_unsure' is the default; drop the key rather than write it.
        if mode == 'when_unsure':
            escalation.pop(state, None)
        else:
            escalation[state] = mode
        if escalation:
            data['escalation'] = escalation
        else:
            data.pop('escalation', None)
        with open(yaml_path, 'w') as f:
            yaml.safe_dump(data, f, sort_keys=False)
        return web.json_response({
            'ok': True,
            'modes': self._load_escalation_modes(slug),
        })

    async def _handle_session_tasks(self, request: web.Request) -> web.Response:
        """List dispatched tasks for a session (issue #389).

        GET /api/sessions/{session_id}/tasks?project={slug}
        Returns a tree of task objects with: dispatch_id, team, task,
        status, subtasks (recursive).
        """
        session_id = request.match_info['session_id']
        project_slug = request.rel_url.query.get('project', '')
        if not project_slug:
            return web.json_response(
                {'error': 'project query parameter required'}, status=400)
        project_path = self._lookup_project_path(project_slug)
        if not project_path:
            return web.json_response(
                {'error': f'project not found: {project_slug}'}, status=404)
        tasks = self._list_session_tasks(project_path, session_id)
        return web.json_response(tasks)

    async def _handle_dispatch_tree(self, request: web.Request) -> web.Response:
        """Return the dispatch tree rooted at a session.

        GET /api/dispatch-tree/{session_id}
        Returns a nested tree of dispatched conversations with their status.

        Sessions live in multiple scopes:
          - OM sessions:              {teaparty_home}/management/sessions/
          - Project lead sessions:    {project_path}/.teaparty/project/sessions/
          - Proxy escalation sessions always live at management scope,
            regardless of which caller (project or management) spawned
            them — so a project-scope root can have a management-scope
            child via conversation_map.

        Pass every candidate sessions_dir to the walker so it can cross
        scopes when resolving a child session id.
        """
        session_id = request.match_info['session_id']
        conv_id = request.query.get('conv', '')
        from teaparty.bridge.state.dispatch_tree import build_dispatch_tree

        sessions_dirs = self._all_sessions_dirs()
        tree = build_dispatch_tree(sessions_dirs, session_id, conv_id=conv_id)
        _log.debug('dispatch-tree %s: %d children, sessions_dirs=%s',
                   session_id, len(tree.get('children', [])), sessions_dirs)
        return web.json_response(tree)

    def _find_sessions_dir(self, session_id: str) -> str:
        """Return the sessions directory that contains the given session_id.

        Tries management/sessions first (OM), then each registered project's
        project/sessions dir. Falls back to management/sessions if not found.
        """
        candidates = self._all_sessions_dirs()
        for candidate in candidates:
            meta_path = os.path.join(candidate, session_id, 'metadata.json')
            if os.path.isfile(meta_path):
                return candidate
        return candidates[0]  # management/sessions as fallback

    def _all_sessions_dirs(self) -> list[str]:
        """Return all sessions directories: management first, then each project."""
        mgmt_sessions = os.path.join(self.teaparty_home, 'management', 'sessions')
        dirs = [mgmt_sessions]
        try:
            team = load_management_team(teaparty_home=self.teaparty_home)
            repo_root = os.path.dirname(self.teaparty_home)
            for project_name in (team.members_projects or []):
                for p in (team.projects or []):
                    if p.get('name') != project_name:
                        continue
                    project_path = p.get('path', '')
                    if not os.path.isabs(project_path):
                        project_path = os.path.join(repo_root, project_path)
                    project_sessions = os.path.join(
                        project_path, '.teaparty', 'project', 'sessions')
                    dirs.append(project_sessions)
                    break
        except Exception:
            _log.debug('_all_sessions_dirs: could not enumerate projects', exc_info=True)
        return dirs

    async def _handle_create_job(self, request: web.Request) -> web.Response:
        """Create a new CfA session for a project.

        POST /api/jobs  { "project": "pybayes", "task": "Build a ..." }
        Returns { "session_id": "...", "conversation_id": "job:pybayes:..." }
        """
        try:
            body = await request.json()
        except Exception:
            return web.json_response({'error': 'invalid JSON'}, status=400)

        project_slug = body.get('project', '').strip()
        task = body.get('task', '').strip()
        if not project_slug or not task:
            return web.json_response(
                {'error': 'project and task are required'}, status=400,
            )

        # Generate session_id upfront so we can return it immediately.
        # Include microseconds to guarantee uniqueness within a second.
        from datetime import datetime
        session_id = datetime.now().strftime('%Y%m%d-%H%M%S-%f')
        conversation_id = f'job:{project_slug}:{session_id}'

        # Create and launch the CfA session as a background task.
        from teaparty.cfa.session import Session
        from teaparty.messaging.conversations import MessageBusInputProvider

        escalation_modes = self._load_escalation_modes(project_slug)

        session = Session(
            task,
            poc_root=self._repo_root,
            project_override=project_slug,
            session_id=session_id,
            escalation_modes=escalation_modes,
            # Hooks for the unified /escalation skill path — CfA job
            # escalations now route through the same mechanism as
            # chat-tier AgentSession (proxy + skill + accordion blade).
            proxy_invoker_fn=self._invoke_proxy,
            on_dispatch=self._broadcast_dispatch,
        )

        async def _run_session():
            try:
                await session.run()
            except Exception:
                _log.exception(
                    'CfA session failed: project=%r session_id=%r',
                    project_slug, session_id,
                )

        task = asyncio.create_task(_run_session())
        self._active_job_tasks[f'{project_slug}:{session_id}'] = task
        self._attach_session_status_callbacks(task, project_slug, session_id)

        return web.json_response({
            'session_id': session_id,
            'conversation_id': conversation_id,
        })

    # CfA gate states that accept a per-gate escalation mode.
    _ESCALATION_GATES: tuple[str, ...] = (
        'EXECUTE',
    )
    _ESCALATION_VALID_MODES: frozenset[str] = frozenset(
        {'always', 'when_unsure', 'never'}
    )
    # Minimum gap between successive auto-resume attempts on the same
    # session (seconds). Prevents a crash loop from hammering resume
    # indefinitely; if the session dies again within this window, it
    # flips to sleeping and the human must wake it explicitly.
    _AUTO_RESUME_COOLDOWN_SECONDS: float = 30.0

    def _load_escalation_modes(self, project_slug: str) -> dict[str, str]:
        """Read per-gate escalation modes from the project's project.yaml.

        Returns a dict mapping CfA state → mode string.  Absent states use
        the default ('when_unsure') and are omitted from the dict.
        """
        project_path = self._lookup_project_path(project_slug)
        if not project_path:
            return {}
        try:
            from teaparty.config.config_reader import load_project_team
            team = load_project_team(project_path)
            # Only include recognized gates with valid modes; silently drop
            # the rest so a stale config can't wedge a session.
            return {
                state: mode
                for state, mode in (team.escalation or {}).items()
                if state in self._ESCALATION_GATES
                and mode in self._ESCALATION_VALID_MODES
            }
        except Exception:
            _log.debug('failed to load escalation modes for %s', project_slug, exc_info=True)
            return {}

    async def _resume_job_session(self, project_slug: str, session_id: str) -> None:
        """Resume a CfA session when the human posts to a job conversation.

        If the session is already running (an active asyncio task exists),
        the message was already written to the bus and the running
        MessageBusInputProvider will pick it up — nothing to do.

        If the session is NOT running (process exited, bridge restarted),
        call Session.resume_from_disk to restart orchestration.
        """
        key = f'{project_slug}:{session_id}'

        # Already running — the bus input provider will pick up the message.
        if key in self._active_job_tasks and not self._active_job_tasks[key].done():
            return

        # Find infra_dir for this session.
        infra_dir = self._resolve_session_infra(session_id)
        if not infra_dir:
            _log.warning('Cannot resume session %s: infra_dir not found', session_id)
            return

        # Check if session is terminal — don't resume completed/withdrawn sessions.
        from teaparty.cfa.statemachine.cfa_state import load_state as _load_cfa, is_globally_terminal
        cfa_path = os.path.join(infra_dir, '.cfa-state.json')
        if os.path.isfile(cfa_path):
            cfa = _load_cfa(cfa_path)
            if is_globally_terminal(cfa.state):
                _log.info('Session %s is terminal (%s), not resuming', session_id, cfa.state)
                return

        from teaparty.cfa.session import Session

        escalation_modes = self._load_escalation_modes(project_slug)

        async def _run_resume():
            try:
                await Session.resume_from_disk(
                    infra_dir,
                    poc_root=self._repo_root,
                    escalation_modes=escalation_modes,
                )
            except Exception:
                _log.exception(
                    'CfA session resume failed: project=%r session_id=%r',
                    project_slug, session_id,
                )

        task = asyncio.create_task(_run_resume())
        self._active_job_tasks[key] = task
        self._attach_session_status_callbacks(task, project_slug, session_id)

    # ── Index handler ─────────────────────────────────────────────────────────

    def _broadcast_session_status(
        self, project_slug: str, session_id: str, status: str,
    ) -> None:
        """Broadcast a session-status change to WebSocket clients.

        Emitted when the session task in _active_job_tasks is created
        (status='running') or exits without the session reaching a
        terminal CfA state (status='sleeping').  Terminal transitions
        are already covered by 'session_completed' events elsewhere.

        Listeners in the chat UI use this to flip the Send button
        label between 'Send', 'Wake', and 'Done' without waiting for
        heartbeat staleness or CfA state transitions.
        """
        self._broadcast_dispatch({
            'type': 'session_status',
            'slug': project_slug,
            'session_id': session_id,
            'status': status,
        })

    def _attach_session_status_callbacks(
        self, task: 'asyncio.Task', project_slug: str, session_id: str,
    ) -> None:
        """Emit session_status='running' now and 'sleeping' on task exit.

        'sleeping' is only emitted if the CfA state is non-terminal when
        the task finishes — a clean completion reports via
        session_completed already, and we don't want to race with that.

        If the task dies (normally or with exception) and the bus has
        trailing unconsumed human messages, auto-fire a single resume
        via ``_resume_job_session``. This is level-triggered recovery
        for the POST-arrives-before-crash race: the human's input is
        already on the bus; we shouldn't require them to click Wake.
        Subject to ``_AUTO_RESUME_COOLDOWN_SECONDS`` to prevent a crash
        loop from re-triggering resume indefinitely.
        """
        self._broadcast_session_status(project_slug, session_id, 'running')

        def _on_done(_t: 'asyncio.Task') -> None:
            try:
                from teaparty.cfa.statemachine.cfa_state import (
                    load_state as _load_cfa, is_globally_terminal,
                )
                infra_dir = self._resolve_session_infra(session_id)
                cfa_state = ''
                if infra_dir:
                    cfa_path = os.path.join(infra_dir, '.cfa-state.json')
                    if os.path.isfile(cfa_path):
                        cfa = _load_cfa(cfa_path)
                        cfa_state = cfa.state
                        if is_globally_terminal(cfa_state):
                            return  # session_completed handles this
                self._broadcast_session_status(
                    project_slug, session_id, 'sleeping')
                self._maybe_auto_resume(project_slug, session_id)
            except Exception:
                _log.debug(
                    'session_status done-callback failed for %s:%s',
                    project_slug, session_id, exc_info=True)

        task.add_done_callback(_on_done)

    def _maybe_auto_resume(
        self, project_slug: str, session_id: str,
    ) -> None:
        """Trigger an auto-resume if unconsumed human input is waiting.

        Called from the job task's done-callback. Reads the session's
        message bus; if there are trailing ``human`` messages after the
        last non-human message, kicks ``_resume_job_session``. Honours
        ``_AUTO_RESUME_COOLDOWN_SECONDS`` so a session that crashes on
        every resume doesn't loop — after the first attempt fails the
        user must wake manually.
        """
        import time
        key = f'{project_slug}:{session_id}'
        now = time.time()
        last = self._last_auto_resume.get(key, 0.0)
        if now - last < self._AUTO_RESUME_COOLDOWN_SECONDS:
            return
        if not self._has_trailing_human_messages(project_slug, session_id):
            return
        self._last_auto_resume[key] = now
        _log.info(
            'auto-resume: unconsumed human input on %s — '
            'restarting session without explicit Wake', key,
        )
        asyncio.create_task(
            self._resume_job_session(project_slug, session_id),
        )

    def _has_trailing_human_messages(
        self, project_slug: str, session_id: str,
    ) -> bool:
        """True iff the last message in the session's bus is from a human.

        A trailing human message means the user's input was posted but
        the session died (or never got) around to consuming it. Used by
        the auto-resume path to distinguish "session just finished its
        turn" from "session crashed with user input unread."
        """
        bus = self._bus_for_conversation(f'job:{project_slug}:{session_id}')
        if bus is None:
            return False
        try:
            msgs = bus.receive(f'job:{project_slug}:{session_id}')
        except Exception:
            return False
        if not msgs:
            return False
        return msgs[-1].sender == 'human'

    def _broadcast_dispatch(self, event: dict) -> None:
        """Broadcast dispatch lifecycle events to WebSocket clients."""
        import asyncio
        payload = json.dumps(event)
        for ws in list(self._ws_clients):
            try:
                asyncio.ensure_future(ws.send_str(payload))
            except Exception:
                pass

    async def _handle_index(self, request: web.Request) -> web.Response:
        index_path = os.path.join(self.static_dir, 'index.html')
        return web.FileResponse(index_path)

    # ── WebSocket handler ─────────────────────────────────────────────────────

    async def _handle_websocket(self, request: web.Request) -> web.WebSocketResponse:
        """WebSocket endpoint for live chat subscriptions (issue #398).

        The connection carries two kinds of traffic:

        - Global broadcast events (state, input_requested, escalation_cleared,
          etc.) are pushed to every connected client via the bridge's
          broadcast callback.
        - ``message`` events are scoped to (connection, conversation) and only
          flow after the client sends a ``subscribe`` frame with an opaque
          cursor from the most recent ``GET /api/conversations/{id}``.

        Accepted client frames (JSON):
            {"type": "subscribe",   "conversation_id": "...", "since_cursor": "..."}
            {"type": "unsubscribe", "conversation_id": "..."}
            {"type": "ping"}
        """
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        self._ws_clients.add(ws)
        relay = getattr(self, '_message_relay', None)
        if relay is not None:
            relay.register_connection(ws)
        try:
            async for raw in ws:
                if raw.type != web.WSMsgType.TEXT:
                    continue
                try:
                    frame = json.loads(raw.data)
                except Exception:
                    continue
                if not isinstance(frame, dict):
                    continue
                kind = frame.get('type')
                if kind == 'subscribe' and relay is not None:
                    cid = frame.get('conversation_id')
                    if not cid:
                        continue
                    # Open the per-task/per-job bus lazily if it hasn't been
                    # touched by an HTTP handler yet; the relay only sees buses
                    # that are in self._buses.
                    self._bus_for_conversation(cid)
                    bus_cid = cid
                    if cid.startswith('task:'):
                        parts = cid.split(':')
                        if len(parts) >= 4:
                            project_slug = parts[1]
                            dispatch_id = ':'.join(parts[3:])
                            bus_cid = f'job:{project_slug}:{dispatch_id}'
                    await relay.subscribe(
                        ws, bus_cid,
                        since_cursor=str(frame.get('since_cursor', '')),
                    )
                elif kind == 'unsubscribe' and relay is not None:
                    cid = frame.get('conversation_id')
                    if not cid:
                        continue
                    bus_cid = cid
                    if cid.startswith('task:'):
                        parts = cid.split(':')
                        if len(parts) >= 4:
                            project_slug = parts[1]
                            dispatch_id = ':'.join(parts[3:])
                            bus_cid = f'job:{project_slug}:{dispatch_id}'
                    await relay.unsubscribe(ws, bus_cid)
                elif kind == 'ping':
                    await ws.send_json({'type': 'pong'})
        except asyncio.CancelledError:
            # Server is shutting down — return cleanly so aiohttp can
            # complete its _handler_waiter bookkeeping without InvalidStateError.
            pass
        finally:
            if relay is not None:
                relay.unregister_connection(ws)
            self._ws_clients.discard(ws)
        return ws

    # ── Internal helpers ──────────────────────────────────────────────────────

    # Conversation-ID prefix → agent name whose bus owns those conversations.
    _CONV_PREFIX_TO_AGENT: dict[str, str] = {
        'om':        'office-manager',
        'pm:':       'project-manager',
        'proxy:':    'proxy',
        'config:':   'configuration-lead',
        'dispatch:': 'office-manager',
    }

    def _get_agent_bus(self, agent_name: str) -> SqliteMessageBus:
        """Return the persistent bus for *agent_name*, creating it if needed.

        Also registers the bus in ``self._buses`` so MessageRelay polls it.
        """
        bus = self._agent_buses.get(agent_name)
        if bus is None:
            if agent_name == 'proxy':
                path = proxy_bus_path(self.teaparty_home)
            else:
                path = agent_bus_path(self.teaparty_home, agent_name)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            bus = SqliteMessageBus(path)
            self._agent_buses[agent_name] = bus
            self._buses[agent_name] = bus
        return bus

    def _get_lead_bus(self, lead_name: str) -> SqliteMessageBus:
        """Return the bus for a project lead, using the lead's project-specific teaparty_home.

        Project leads for external projects (e.g. pybayes) run with a different
        teaparty_home than the bridge server itself.  Using ``_get_agent_bus``
        for them would open the wrong database — the one under the bridge's own
        ``self.teaparty_home`` — while the AgentSession writes to and reads from
        the project's ``.teaparty/``.  This method resolves the correct home so
        messages posted by the bridge land in the same file the agent monitors.
        """
        bus = self._agent_buses.get(lead_name)
        if bus is None:
            from teaparty.config.roster import resolve_lead_project_path
            project_path = resolve_lead_project_path(lead_name, self.teaparty_home)
            home = os.path.join(project_path, '.teaparty') if project_path else self.teaparty_home
            path = agent_bus_path(home, lead_name)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            bus = SqliteMessageBus(path)
            self._agent_buses[lead_name] = bus
            self._buses[lead_name] = bus
        return bus

    def _bus_for_conversation(self, conv_id: str) -> SqliteMessageBus | None:
        """Find the bus that owns a conversation.

        Persistent agent conversations are routed by conv_id prefix.
        All other conversations are searched across active session buses.
        """
        # Dynamic prefix: lead:{lead-name}:{qualifier}
        if conv_id.startswith('lead:'):
            parts = conv_id.split(':', 2)
            if len(parts) >= 2:
                return self._get_lead_bus(parts[1])

        # Job conversations live in per-session databases.
        # Open the bus on demand so the human can post to any session.
        if conv_id.startswith('job:'):
            parts = conv_id.split(':')
            if len(parts) >= 3:
                session_id = parts[2]
                infra_dir = self._resolve_session_infra(session_id)
                if infra_dir:
                    bus_path = os.path.join(infra_dir, 'messages.db')
                    if os.path.isfile(bus_path):
                        bus = self._buses.get(session_id)
                        if bus is None:
                            bus = SqliteMessageBus(bus_path)
                            self._buses[session_id] = bus
                        return bus

        # Task conversations live in per-task databases (issue #389).
        # Conv ID format: task:{project}:{session_id}:{dispatch_id}
        if conv_id.startswith('task:'):
            parts = conv_id.split(':')
            if len(parts) >= 4:
                project_slug = parts[1]
                session_id = parts[2]
                dispatch_id = ':'.join(parts[3:])
                project_path = self._lookup_project_path(project_slug)
                if project_path:
                    job_dir = self._resolve_job_infra(project_path, session_id)
                    if job_dir:
                        infra_dir = self._resolve_dispatch_infra(
                            job_dir, dispatch_id)
                        if infra_dir:
                            bus_key = f'task:{session_id}:{dispatch_id}'
                            bus = self._buses.get(bus_key)
                            if bus is None:
                                bus_path = os.path.join(infra_dir, 'messages.db')
                                if os.path.isfile(bus_path):
                                    bus = SqliteMessageBus(bus_path)
                                    self._buses[bus_key] = bus
                            return bus

        for prefix, agent_name in self._CONV_PREFIX_TO_AGENT.items():
            if conv_id.startswith(prefix):
                return self._get_agent_bus(agent_name)
        for bus in self._buses.values():
            try:
                if bus.get_conversation(conv_id) is not None:
                    return bus
            except Exception:
                pass
        return None

    def _slug_for_lead(self, lead_name: str) -> str:
        """Return the project slug whose lead is ``lead_name``, or ''.

        Used by pause/resume wiring so a project-lead AgentSession can
        refuse new dispatches while its project is paused (issue #403).
        """
        from teaparty.config.roster import resolve_lead_project_path
        try:
            project_path = resolve_lead_project_path(
                lead_name, self.teaparty_home)
        except Exception:
            return ''
        if not project_path:
            return ''
        return os.path.basename(project_path.rstrip('/'))

    def _lookup_project_path(self, slug: str) -> str | None:
        """Return the project directory for a given slug, or None if not found.

        Matches by the basename of the project path in the registry.
        A _project_path_cache dict attribute may be set to override lookup (used in tests).
        """
        cache = getattr(self, '_project_path_cache', None)
        if cache and slug in cache:
            return cache[slug]
        try:
            team = load_management_team(teaparty_home=self.teaparty_home)
            for entry in discover_projects(team):
                if (os.path.basename(entry['path'].rstrip('/')) == slug
                        or entry['name'] == slug):
                    return entry['path']
        except Exception:
            pass
        return None

    def _resolve_session_infra(self, session_id: str) -> str | None:
        """Find the infra_dir for a session by scanning registry projects."""
        try:
            team = load_management_team(teaparty_home=self.teaparty_home)
            project_entries = discover_projects(team)
        except Exception:
            return None
        for entry in project_entries:
            # Check new layout: .teaparty/jobs/job-{session_id}--{slug}/
            job_dir = self._resolve_job_infra(entry['path'], session_id)
            if job_dir:
                return job_dir
            # Legacy: .sessions/{session_id}/
            candidate = os.path.join(entry['path'], '.sessions', session_id)
            if os.path.isdir(candidate):
                return candidate
        return None

    def _resolve_job_infra(self, project_path: str, session_id: str) -> str | None:
        """Find a job_dir by session_id under {project_path}/.teaparty/jobs/.

        Scans job directories matching ``job-{session_id}--*``.
        """
        jobs_dir = os.path.join(project_path, '.teaparty', 'jobs')
        if not os.path.isdir(jobs_dir):
            return None
        prefix = f'job-{session_id}--'
        try:
            for name in os.listdir(jobs_dir):
                if name.startswith(prefix):
                    candidate = os.path.join(jobs_dir, name)
                    if os.path.isfile(os.path.join(candidate, 'job.json')):
                        return candidate
        except OSError:
            pass
        return None

    def _resolve_dispatch_infra(self, job_dir: str, dispatch_id: str) -> str | None:
        """Find the infra_dir for any dispatch type (worktree or direct model).

        Checks worktree-model tasks (under tasks/) first, then falls back
        to .children registry for direct-model dispatches.
        """
        # 1. Worktree-model: task-{dispatch_id}--* under tasks/
        result = self._resolve_task_infra(job_dir, dispatch_id)
        if result:
            return result

        # 2. Direct-model: find via .children registry
        children_path = os.path.join(job_dir, '.children')
        if os.path.isfile(children_path):
            try:
                from teaparty.bridge.state.heartbeat import read_children
                for child in read_children(children_path):
                    hb_path = child.get('heartbeat', '')
                    if not hb_path:
                        continue
                    infra_dir = os.path.dirname(hb_path)
                    if os.path.basename(infra_dir) == dispatch_id:
                        if os.path.isdir(infra_dir):
                            return infra_dir
            except (ImportError, OSError):
                pass
        return None

    def _resolve_task_infra(self, parent_dir: str, dispatch_id: str) -> str | None:
        """Find a task_dir by dispatch_id, searching recursively.

        Scans task directories matching ``task-{dispatch_id}--*`` under
        parent_dir/tasks/, then recurses into each task's own tasks/
        subdirectory to support nested dispatches.
        """
        tasks_dir = os.path.join(parent_dir, 'tasks')
        if not os.path.isdir(tasks_dir):
            return None
        prefix = f'task-{dispatch_id}--'
        try:
            for name in sorted(os.listdir(tasks_dir)):
                candidate = os.path.join(tasks_dir, name)
                if name.startswith(prefix):
                    if os.path.isfile(os.path.join(candidate, 'task.json')):
                        return candidate
                # Recurse into child tasks to find nested dispatches
                if os.path.isfile(os.path.join(candidate, 'task.json')):
                    nested = self._resolve_task_infra(candidate, dispatch_id)
                    if nested:
                        return nested
        except OSError:
            pass
        return None

    def _list_session_tasks(self, project_path: str, session_id: str) -> list[dict]:
        """List all tasks for a session, with recursive subtask nesting.

        Returns a tree of task dicts, each with: dispatch_id, team, task,
        status, subtasks (recursive).
        """
        job_dir = self._resolve_job_infra(project_path, session_id)
        if not job_dir:
            return []
        return self._scan_tasks(job_dir)

    def _scan_tasks(self, parent_dir: str) -> list[dict]:
        """Scan tasks/ and .children for all dispatches under parent_dir.

        Discovers both worktree-model dispatches (under tasks/) and
        direct-model dispatches (registered in .children, stored under
        {parent_dir}/{team}/{dispatch_id}/).
        """
        result = []
        seen_infra_dirs: set[str] = set()

        # 1. Worktree-model tasks from tasks/ directory
        tasks_dir = os.path.join(parent_dir, 'tasks')
        if os.path.isdir(tasks_dir):
            try:
                for name in sorted(os.listdir(tasks_dir)):
                    task_dir = os.path.join(tasks_dir, name)
                    task_json = os.path.join(task_dir, 'task.json')
                    if not os.path.isfile(task_json):
                        continue
                    try:
                        with open(task_json) as f:
                            state = json.load(f)
                    except (json.JSONDecodeError, OSError):
                        continue

                    task_id = state.get('task_id', '')
                    dispatch_id = task_id[5:] if task_id.startswith('task-') else task_id
                    status = self._resolve_task_status(
                        task_dir, state.get('status', 'active'))

                    task_desc = self._read_task_description(task_dir, state)
                    subtasks = self._scan_tasks(task_dir)
                    seen_infra_dirs.add(os.path.abspath(task_dir))
                    result.append({
                        'dispatch_id': dispatch_id,
                        'team': state.get('team', ''),
                        'task': task_desc,
                        'status': status,
                        'subtasks': subtasks,
                    })
            except OSError:
                pass

        # 2. Direct-model dispatches from .children registry
        children_path = os.path.join(parent_dir, '.children')
        if os.path.isfile(children_path):
            try:
                from teaparty.bridge.state.heartbeat import read_children
                for child in read_children(children_path):
                    hb_path = child.get('heartbeat', '')
                    if not hb_path:
                        continue
                    infra_dir = os.path.dirname(hb_path)
                    if os.path.abspath(infra_dir) in seen_infra_dirs:
                        continue
                    if not os.path.isdir(infra_dir):
                        continue

                    team = child.get('team', '')
                    dispatch_id = os.path.basename(infra_dir)
                    status = self._resolve_task_status(infra_dir, 'active')
                    task_desc = self._read_task_description(infra_dir, {})
                    subtasks = self._scan_tasks(infra_dir)
                    result.append({
                        'dispatch_id': dispatch_id,
                        'team': team,
                        'task': task_desc,
                        'status': status,
                        'subtasks': subtasks,
                    })
            except (ImportError, OSError):
                pass

        return result

    @staticmethod
    def _resolve_task_status(infra_dir: str, json_status: str) -> str:
        """Determine task status by checking heartbeat liveness.

        If the heartbeat indicates terminal (completed/withdrawn) or the
        process is dead, return 'complete'. Otherwise return the json_status.
        """
        from teaparty.bridge.state.reader import (
            _is_heartbeat_alive, _is_heartbeat_terminal,
        )
        if _is_heartbeat_terminal(infra_dir):
            return 'complete'
        if json_status == 'active' and not _is_heartbeat_alive(infra_dir):
            # No live heartbeat — check if heartbeat file exists at all
            hb_path = os.path.join(infra_dir, '.heartbeat')
            if os.path.exists(hb_path):
                return 'complete'
        return json_status

    @staticmethod
    def _read_task_description(infra_dir: str, state: dict) -> str:
        """Read task description from PROMPT.txt, falling back to slug."""
        prompt_path = os.path.join(infra_dir, 'PROMPT.txt')
        try:
            with open(prompt_path) as f:
                desc = f.read().strip()
                if desc:
                    return desc
        except (FileNotFoundError, OSError):
            pass
        # Fall back to slug from task.json
        slug = state.get('slug', '')
        if slug:
            return slug
        # Fall back to team name
        return state.get('team', '')

    # ── Serializers ───────────────────────────────────────────────────────────

    def _serialize_project(self, p) -> dict:
        return {
            'slug': p.slug,
            'name': p.name,
            'path': p.path,
            'active_count': p.active_count,
            'attention_count': p.attention_count,
            'sessions': [self._serialize_session(s) for s in p.sessions],
        }

    def _serialize_session(self, s) -> dict:
        # Resolve the conversation_id that is currently awaiting human input,
        # so the home page can build the correct escalation click URL at render time.
        input_conv_id = ''
        if s.needs_input:
            bus = self._buses.get(s.session_id)
            if bus is not None:
                try:
                    waiting = bus.conversations_awaiting_input()
                    if waiting:
                        input_conv_id = waiting[0].id
                except Exception:
                    pass
        return {
            'session_id': s.session_id,
            'project': s.project,
            'status': s.status,
            'cfa_phase': s.cfa_phase,
            'cfa_state': s.cfa_state,
            'cfa_actor': s.cfa_actor,
            'needs_input': s.needs_input,
            'input_conv_id': input_conv_id,
            'task': s.task,
            'heartbeat_status': s.heartbeat_status,
            'total_cost_usd': s.total_cost_usd,
            'backtrack_count': s.backtrack_count,
            'infra_dir': s.infra_dir,
            'worktree_path': s.worktree_path,
        }

    def _serialize_conversation(self, c) -> dict:
        return {
            'id': c.id,
            'type': c.type.value,
            'state': c.state.value,
            'created_at': c.created_at,
            'awaiting_input': c.awaiting_input,
        }

    def _serialize_message(self, m) -> dict:
        return {
            'id': m.id,
            'conversation': m.conversation,
            'sender': m.sender,
            'content': m.content,
            'timestamp': m.timestamp,
        }

    def _serialize_management_team(
        self, t,
        discovered_agents: list[str] | None = None,
        discovered_skills: list[str] | None = None,
        teaparty_home: str | None = None,
    ) -> dict:
        home = teaparty_home or self.teaparty_home
        repo_root = os.path.dirname(home)
        agents_dir = management_agents_dir(home)
        skills_dir = management_skills_dir(home)
        config_yaml = os.path.join(home, 'management', 'teaparty.yaml')

        def _agent_file(name: str) -> str | None:
            path = os.path.join(agents_dir, name, 'agent.md')
            return path if os.path.isfile(path) else None

        def _skill_file(name: str) -> str | None:
            path = os.path.join(skills_dir, name, 'SKILL.md')
            return path if os.path.isfile(path) else None

        def _hook_file(hook: dict) -> str:
            cmd = hook.get('command', '')
            if cmd and os.path.isabs(cmd) and os.path.isfile(cmd):
                return cmd
            # Resolve relative command paths against the repo root.
            if cmd:
                resolved = os.path.join(repo_root, cmd)
                if os.path.isfile(resolved):
                    return resolved
            return config_yaml

        def _task_file(skill_name: str) -> str | None:
            path = os.path.join(skills_dir, skill_name, 'SKILL.md')
            return path if os.path.isfile(path) else None

        settings_hooks = discover_hooks(management_settings_path(home))
        yaml_hooks = [
            {**h, 'active': h.get('active', True), 'source': 'yaml'}
            for h in t.hooks
        ]
        sys_hooks = [{**h, 'active': True, 'source': 'settings'} for h in settings_hooks]
        all_hooks = yaml_hooks + sys_hooks

        # Full agent catalog: all agents discovered, with active: bool.
        # Auto-discover from filesystem when not given an explicit list.
        active_agents_set = set(t.members_agents)
        all_catalog_agents: list[str] = (
            discovered_agents if discovered_agents is not None
            else discover_agents(agents_dir)
        )
        # Include any active agents not found on disk (e.g. missing / not yet created)
        for name in t.members_agents:
            if name not in all_catalog_agents:
                all_catalog_agents = all_catalog_agents + [name]
        agents_result = [
            {'name': n, 'file': _agent_file(n), 'active': n in active_agents_set}
            for n in all_catalog_agents
        ]

        # Full skill catalog: all discovered skills with active: bool
        active_skills_set = set(t.members_skills or [])
        skills_result = [
            {'name': n, 'file': _skill_file(n), 'active': n in active_skills_set}
            for n in (discovered_skills or [])
        ]

        # Build the OM's roster — project leads and management agents
        roster_items: list[dict] = []
        for project_entry in (t.projects or []):
            project_name = project_entry.get('name', '')
            p_path = project_entry.get('path', '')
            if not os.path.isabs(p_path):
                p_path = os.path.join(repo_root, p_path)
            p_config = project_entry.get('config', '')
            full_config = os.path.join(p_path, p_config) if p_config else None
            try:
                pt = load_project_team(p_path, config_path=full_config)
                roster_items.append({
                    'name': pt.lead or project_name,
                    'role': 'project-lead',
                    'description': pt.description or project_name,
                    'project': project_name,
                })
            except FileNotFoundError:
                roster_items.append({
                    'name': project_name,
                    'role': 'project-lead',
                    'description': project_name,
                    'project': project_name,
                })
        for agent_name in (t.members_agents or []):
            desc = ''
            agent_path = os.path.join(agents_dir, agent_name, 'agent.md')
            if not os.path.isfile(agent_path):
                agent_path = os.path.join(agents_dir, f'{agent_name}.md')
            if os.path.isfile(agent_path):
                fm = read_agent_frontmatter(agent_path)
                desc = fm.get('description', '')
            roster_items.append({
                'name': agent_name,
                'role': 'management-agent',
                'description': desc or agent_name,
            })

        decider = next((h.name for h in t.humans if h.role == 'decider'), '')
        return {
            'name': t.name,
            'description': t.description,
            'lead': t.lead,
            'decider': decider,
            'roster': roster_items,
            'agents': agents_result,
            'humans': [{'name': h.name, 'role': h.role} for h in t.humans],
            'skills': skills_result,
            'hooks': [{**h, 'file': _hook_file(h)} for h in all_hooks],
            'scheduled': [
                {'name': s.name, 'schedule': s.schedule, 'skill': s.skill, 'enabled': s.enabled,
                 'file': _task_file(s.skill)}
                for s in t.scheduled
            ],
        }

    def _serialize_project_team(
        self, t,
        org_agents: list[str] | None = None,
        org_catalog_agents: list[str] | None = None,
        local_skills: list[str] | None = None,
        org_catalog_skills: list[str] | None = None,
        teaparty_home: str | None = None,
        project_dir: str | None = None,
        catalog_hooks: list[dict] | None = None,
    ) -> dict:
        org_agents_set = set(org_agents or [])
        local_skills_set = set(local_skills or [])
        home = teaparty_home or self.teaparty_home
        proj = project_dir or ''

        _org_agents = management_agents_dir(home)
        _proj_agents = project_agents_dir(proj) if proj else ''
        _org_skills = management_skills_dir(home)
        _proj_skills = project_skills_dir(proj) if proj else ''
        proj_config = os.path.join(proj, '.teaparty', 'project', 'project.yaml') if proj else ''

        def _agent_source(name: str) -> str:
            if name == t.lead:
                return 'generated'
            return 'shared' if name in org_agents_set else 'local'

        def _agent_file(name: str) -> str | None:
            source = _agent_source(name)
            if source == 'shared':
                path = os.path.join(_org_agents, name, 'agent.md')
            elif _proj_agents:
                path = os.path.join(_proj_agents, name, 'agent.md')
            else:
                return None
            return path if os.path.isfile(path) else None

        def _skill_file(name: str, source: str) -> str | None:
            if source == 'local':
                path = os.path.join(_proj_skills, name, 'SKILL.md') if _proj_skills else None
            elif source == 'shared':
                path = os.path.join(_org_skills, name, 'SKILL.md')
            else:
                return None  # missing
            return path if path and os.path.isfile(path) else None

        def _hook_file(hook: dict) -> str:
            cmd = hook.get('command', '')
            if cmd and os.path.isabs(cmd) and os.path.isfile(cmd):
                return cmd
            # Resolve relative command paths against the project directory.
            if cmd and proj:
                resolved = os.path.join(proj, cmd)
                if os.path.isfile(resolved):
                    return resolved
            return proj_config

        def _task_file(skill_name: str) -> str | None:
            # Local skills take precedence over org skills.
            if _proj_skills and skill_name in local_skills_set:
                path = os.path.join(_proj_skills, skill_name, 'SKILL.md')
                return path if os.path.isfile(path) else None
            path = os.path.join(_org_skills, skill_name, 'SKILL.md')
            return path if os.path.isfile(path) else None

        # Agent catalog: local project agents + shared org agents.
        # active reflects explicit team membership, not catalog presence.
        active_agents_set = set(getattr(t, 'members_agents', None) or [])
        agents_result = []
        seen_agents: set[str] = set()
        local_agent_names = discover_agents(_proj_agents) if _proj_agents else []
        for name in sorted(local_agent_names):
            agents_result.append({
                'name': name, 'source': 'local',
                'active': name in active_agents_set,
            })
            seen_agents.add(name)
        for name in (org_catalog_agents or []):
            if name in seen_agents:
                continue
            agents_result.append({
                'name': name, 'source': 'shared',
                'active': name in active_agents_set,
            })
            seen_agents.add(name)

        # Build merged skill list: local first, then shared org skills.
        # Active state: None = all active (not configured yet), list = explicit membership.
        all_active = t.members_skills is None
        active_skills_set = set(t.members_skills) if t.members_skills is not None else set()
        skills_result = []
        seen_skills: set[str] = set()
        for name in sorted(local_skills or []):
            source = 'local'
            skills_result.append({
                'name': name, 'source': source,
                'file': _skill_file(name, source),
                'active': all_active or name in active_skills_set,
            })
            seen_skills.add(name)
        # All org catalog skills not already shown as local
        for name in (org_catalog_skills or []):
            if name in seen_skills:
                continue
            source = 'shared'
            skills_result.append({
                'name': name, 'source': source,
                'file': _skill_file(name, source),
                'active': all_active or name in active_skills_set,
            })
            seen_skills.add(name)

        if catalog_hooks is not None:
            settings_hooks = catalog_hooks
        else:
            proj_settings = project_settings_path(proj) if proj else ''
            settings_hooks = discover_hooks(proj_settings) if proj_settings else []
        yaml_hooks = [
            {**h, 'active': h.get('active', True), 'source': 'yaml'}
            for h in t.hooks
        ]
        sys_hooks = [{**h, 'active': True, 'source': 'settings'} for h in settings_hooks]
        all_hooks = yaml_hooks + sys_hooks

        decider = next((h.name for h in t.humans if h.role == 'decider'), '')
        return {
            'name': t.name,
            'description': t.description,
            'lead': t.lead,
            'decider': decider,
            'agents': agents_result,
            'humans': [{'name': h.name, 'role': h.role} for h in t.humans],
            'skills': skills_result,
            'hooks': [{**h, 'file': _hook_file(h)} for h in all_hooks],
            'scheduled': [
                {'name': s.name, 'schedule': s.schedule, 'skill': s.skill, 'enabled': s.enabled,
                 'file': _task_file(s.skill)}
                for s in t.scheduled
            ],
        }

    def _serialize_workgroup(
        self, w, source: str | None = None, overrides: list[str] | None = None,
        detail: bool = False,
        org_agents: set | list | None = None,
        org_catalog_agents: list[str] | None = None,
        org_catalog_skills: list[str] | None = None,
        org_hooks_catalog: list[dict] | None = None,
        active: bool | None = None,
        parent_humans: list | None = None,
    ) -> dict:
        result = {
            'name': w.name,
            'description': w.description,
            'lead': w.lead,
            'agents_count': len(w.members_agents),
            'source': source,
            'overrides': overrides or [],
        }
        if active is not None:
            result['active'] = active
        if detail:
            active_agent_names: set[str] = set(w.members_agents)
            org_agents_set: set[str] = set(org_agents or [])
            # Full agent catalog: all org filesystem agents, mark active if in workgroup
            catalog = list(org_catalog_agents or [])
            for name in active_agent_names:
                if name not in catalog:
                    catalog = catalog + [name]
            _wg_agents_dir = management_agents_dir(self.teaparty_home)

            def _wg_agent_file(n: str) -> str | None:
                path = os.path.join(_wg_agents_dir, n, 'agent.md')
                return path if os.path.isfile(path) else None

            result['agents'] = [
                {
                    'name': n,
                    'source': 'shared' if n in org_agents_set else 'local',
                    'active': n in active_agent_names,
                    'file': _wg_agent_file(n) if n in org_agents_set else None,
                }
                for n in catalog
            ]
            # Workgroups have no skills (issue #362/#367); skills key is omitted.
            # Full hooks catalog: org settings.json hooks with active flag from w.members_hooks
            active_hook_events: set[str] = set(w.members_hooks)
            result['hooks'] = [
                {**h, 'active': h.get('event', '') in active_hook_events}
                for h in (org_hooks_catalog or [])
            ]
            result['norms'] = dict(w.norms)
            result['budget'] = dict(w.budget)
            # Merge parent team humans (inherited) with workgroup-specific overrides.
            # Workgroup-explicit entries win; parent fills in the rest.
            wg_human_names = {h.name for h in w.humans}
            merged_humans = list(w.humans) + [
                h for h in (parent_humans or []) if h.name not in wg_human_names
            ]
            result['humans'] = [
                {'name': h.name, 'role': h.role} for h in merged_humans
            ]
            result['artifacts'] = list(w.artifacts)
        return result
