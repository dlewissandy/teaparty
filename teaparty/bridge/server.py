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

from teaparty.cfa.gates.intervention_listener import make_intervention_request
from teaparty.messaging.conversations import ConversationType, SqliteMessageBus, agent_bus_path
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


def _withdrawal_socket_path(teaparty_home: str, session_id: str) -> str:
    """Return the stable Unix socket path for a session's intervention channel.

    Path: {teaparty_home}/sockets/{session_id}.sock
    The bridge constructs this from the session ID alone — no file read required.
    Socket presence is the readiness signal.  Decision record: issue #278 option B.
    """
    return os.path.join(teaparty_home, 'sockets', f'{session_id}.sock')


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


# ── Bridge class ──────────────────────────────────────────────────────────────

class TeaPartyBridge:
    """aiohttp bridge server exposing TeaParty data via REST and WebSocket.

    Project discovery is registry-based: reads ~/.teaparty/teaparty.yaml.
    No projects_dir argument — all project paths come from the registry.

    Args:
        teaparty_home: Path to the .teaparty config directory (~ is expanded).
        static_dir:    Path to the directory containing static HTML files.
    """

    # Repo root: bridge/ is at repo root, so dirname(dirname(__file__)) = repo root
    _repo_root: str = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    def __init__(self, teaparty_home: str, static_dir: str):
        self.teaparty_home = os.path.expanduser(teaparty_home)
        self.static_dir = os.path.expanduser(static_dir)
        self._llm_backend = os.environ.get('TEAPARTY_LLM_BACKEND', 'claude')
        self._mcp_asgi_app = None  # Set in _on_startup
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
        # StateReader uses registry-based project discovery.
        self._state_reader = StateReader(
            repo_root=self._repo_root,
            teaparty_home=self.teaparty_home,
        )

        # Migrate legacy .sessions/ data to .teaparty/jobs/ (issue #387).
        # One-time on startup so compute_stats stays read-only.
        self._migrate_legacy_sessions()

    def _migrate_legacy_sessions(self) -> None:
        """Migrate .sessions/ data to .teaparty/jobs/ for all registered projects."""
        from teaparty.workspace.job_store import migrate_legacy_sessions
        try:
            team = load_management_team(teaparty_home=self.teaparty_home)
            for entry in discover_projects(team):
                migrate_legacy_sessions(entry['path'])
        except Exception:
            _log.warning('Legacy session migration failed', exc_info=True)

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

        # ── Filesystem navigation endpoint ────────────────────────────────────
        app.router.add_get('/api/fs/list', self._handle_fs_list)

        # ── Project management endpoints ──────────────────────────────────────
        app.router.add_post('/api/projects/add', self._handle_projects_add)
        app.router.add_post('/api/projects/create', self._handle_projects_create)

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
        # Start the session manager via its lifespan
        self._mcp_session_mgr = mcp_server.session_manager
        self._mcp_session_ctx = self._mcp_session_mgr.run()
        await self._mcp_session_ctx.__aenter__()
        _log.info('MCP server started (in-process, same event loop)')

        async def broadcast(event: dict) -> None:
            payload = json.dumps(event)
            for ws in list(self._ws_clients):
                try:
                    await ws.send_str(payload)
                except Exception:
                    pass

        def bus_factory(infra_dir: str) -> SqliteMessageBus:
            db_path = os.path.join(infra_dir, 'messages.db')
            bus = SqliteMessageBus(db_path)
            # Key by session_id (last path component) so MessageRelay emits the
            # correct session_id in WebSocket events, not a filesystem path.
            self._buses[os.path.basename(infra_dir)] = bus
            return bus

        poller = StatePoller(self._state_reader, broadcast, bus_factory=bus_factory)
        relay = MessageRelay(self._buses, broadcast)

        app['_poller_task'] = asyncio.create_task(poller.run())
        app['_relay_task'] = asyncio.create_task(relay.run())

        # Open persistent agent buses and register them for MessageRelay polling.
        # Agent-name keys are stable and will never collide with a session_id.
        for agent_name in ('office-manager', 'project-manager', 'proxy-review', 'configuration-lead'):
            self._get_agent_bus(agent_name)

    async def _on_cleanup(self, app: web.Application) -> None:
        # Shut down MCP session manager
        if hasattr(self, '_mcp_session_ctx') and self._mcp_session_ctx:
            try:
                await self._mcp_session_ctx.__aexit__(None, None, None)
            except Exception:
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
            except FileNotFoundError:
                _log.warning('Workgroup not found, skipping: %s', entry)

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
            toggle_project_membership(project_dir, kind, name, active, catalog=catalog)
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
        write_agent_frontmatter(path, body)
        fm = read_agent_frontmatter(path)
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
                qualifier = c.id[len('om:'):] if c.id.startswith('om:') else ''
                if qualifier:
                    session = self._agent_sessions.get(f'om:{qualifier}')
                    title = (
                        (session.conversation_title if session else None)
                        or read_session_title(self.teaparty_home, 'office-manager', qualifier)
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

        # Route proxy_review type to the persistent proxy bus (issue #331)
        if conv_type == ConversationType.PROXY_REVIEW:
            bus = self._get_agent_bus('proxy-review')
            convs = bus.active_conversations(conv_type)
            result = []
            for c in convs:
                d = self._serialize_conversation(c)
                qualifier = c.id[len('proxy:'):] if c.id.startswith('proxy:') else ''
                if qualifier:
                    session = self._agent_sessions.get(f'proxy:{qualifier}')
                    title = (
                        (session.conversation_title if session else None)
                        or read_session_title(self.teaparty_home, 'proxy-review', qualifier)
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
        conv_id = request.match_info['id']
        since_str = request.rel_url.query.get('since', '0')
        try:
            since_ts = float(since_str)
        except ValueError:
            since_ts = 0.0

        bus = self._bus_for_conversation(conv_id)
        if bus is None:
            return web.json_response([], status=200)

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

        messages = bus.receive(bus_conv_id, since_timestamp=since_ts)
        return web.json_response([self._serialize_message(m) for m in messages])

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
        if conv_id.startswith('om:'):
            qualifier = conv_id[len('om:'):]
            bus.create_conversation(ConversationType.OFFICE_MANAGER, qualifier)
        elif conv_id.startswith('pm:'):
            qualifier = conv_id[len('pm:'):]
            bus.create_conversation(ConversationType.PROJECT_MANAGER, qualifier)
        elif conv_id.startswith('proxy:'):
            qualifier = conv_id[len('proxy:'):]
            bus.create_conversation(ConversationType.PROXY_REVIEW, qualifier)
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

        # Invoke the agent asynchronously; reply will appear in the bus and
        # be broadcast by MessageRelay.
        if conv_id.startswith('om:'):
            asyncio.create_task(self._invoke_om(qualifier))
        elif conv_id.startswith('pm:'):
            asyncio.create_task(self._invoke_pm(qualifier))
        elif conv_id.startswith('proxy:'):
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

        Finds the interjection socket for the session that owns this conversation
        and posts {context_id, message} to trigger --resume on the active session.
        """
        import asyncio
        import json

        socket_path = self._find_interjection_socket(conv_id)
        if not socket_path:
            return web.json_response(
                {'error': f'No active session found for conversation: {conv_id}'},
                status=404,
            )

        try:
            reader, writer = await asyncio.open_unix_connection(socket_path)
            try:
                request_payload = json.dumps({
                    'type': 'interject',
                    'context_id': conv_id,
                    'message': content,
                })
                writer.write(request_payload.encode() + b'\n')
                await writer.drain()
                response_line = await reader.readline()
                response = json.loads(response_line.decode())
            finally:
                writer.close()
                try:
                    await writer.wait_closed()
                except Exception:
                    pass
        except Exception as exc:
            return web.json_response(
                {'error': f'Failed to reach interjection socket: {exc}'},
                status=502,
            )

        if response.get('status') == 'error':
            return web.json_response({'error': response.get('reason', 'unknown error')}, status=409)
        return web.json_response({'status': 'ok'})

    def _find_interjection_socket(self, conv_id: str) -> str:
        """Find the interjection socket path for the session that owns conv_id.

        Searches active session buses for one that has an agent_contexts record
        matching conv_id, then resolves the session's infra_dir and reads the
        interjection_socket file written by the engine at startup.
        """
        for session_id, bus in self._buses.items():
            try:
                ctx = bus.get_agent_context(conv_id)
                if ctx is None:
                    continue
                infra_dir = self._resolve_session_infra(session_id)
                if infra_dir is None:
                    continue
                socket_file = os.path.join(infra_dir, 'interjection_socket')
                if os.path.exists(socket_file):
                    with open(socket_file) as f:
                        return f.read().strip()
            except Exception:
                pass
        return ''

    async def _invoke_agent(
        self,
        *,
        session_key: str,
        agent_name: str,
        qualifier: str,
        conversation_type: ConversationType,
        cwd: str,
        teaparty_home: str = '',
        scope: str = 'management',
        agent_role: str = '',
        dispatches: bool = False,
        post_invoke_hook=None,
        build_prompt_hook=None,
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
                )
            session = self._agent_sessions[session_key]
            try:
                await session.invoke(cwd=cwd)
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

    async def _invoke_om(self, qualifier: str) -> None:
        """Invoke the office manager agent for the given conversation qualifier.

        Runs as a fire-and-forget asyncio task. The OM agent reads the conversation
        history, responds, and writes its reply to the OM bus. MessageRelay picks
        up the reply and broadcasts it to WebSocket clients.

        Concurrent invocations for the same qualifier queue via an asyncio.Lock —
        the second message begins only after the first completes, ensuring the
        --resume session ID from the first turn is available to the second.

        On runner failure, writes an error message to the bus so the human sees
        feedback rather than silence.
        """
        await self._invoke_agent(
            session_key=f'om:{qualifier}',
            agent_name='office-manager',
            qualifier=qualifier,
            conversation_type=ConversationType.OFFICE_MANAGER,
            dispatches=True,
            cwd=self._repo_root,
        )

    async def _invoke_pm(self, qualifier: str) -> None:
        """Invoke the project manager agent for the given conversation qualifier.

        qualifier is '{project_slug}:{user_id}' e.g. 'jainai:darrell'.
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
        )

    async def _invoke_proxy(self, qualifier: str) -> None:
        """Invoke the proxy review agent for the given conversation qualifier.

        Runs as a fire-and-forget asyncio task. The proxy agent reads the
        conversation history and ACT-R memory, responds, processes any
        [CORRECTION:...] signals, and writes its reply to the proxy bus.
        MessageRelay picks up the reply and broadcasts it to WebSocket clients.

        Concurrent invocations for the same qualifier queue via an asyncio.Lock —
        the second message begins only after the first completes, ensuring the
        --resume session ID from the first turn is available to the second.

        On runner failure, writes an error message to the bus so the human sees
        feedback rather than silence.
        """
        from teaparty.proxy.hooks import proxy_post_invoke, proxy_build_prompt
        await self._invoke_agent(
            session_key=f'proxy:{qualifier}',
            agent_name='proxy-review',
            agent_role='proxy',
            qualifier=qualifier,
            conversation_type=ConversationType.PROXY_REVIEW,
            cwd=self._repo_root,
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
            scope='project',
            cwd=cwd,
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

    async def _handle_fs_list(self, request: web.Request) -> web.Response:
        """GET /api/fs/list?path=<p> or ?project=<slug> — list directory contents.

        Accepts either an explicit ``path`` query parameter (absolute directory path)
        or a ``project`` slug that is resolved to the project directory.  Returns
        ``{path, entries}`` where *path* is the resolved absolute directory path.
        """
        path = request.rel_url.query.get('path', '')
        project = request.rel_url.query.get('project', '')
        if not path and project:
            proj_path = self._lookup_project_path(project)
            if proj_path is None:
                return web.json_response({'error': f'project not found: {project}'}, status=404)
            path = proj_path
        if not path:
            return web.json_response({'error': 'path or project parameter required'}, status=400)
        try:
            entries = _list_directory(path)
        except FileNotFoundError as exc:
            return web.json_response({'error': str(exc)}, status=404)
        return web.json_response({'path': path, 'entries': entries})

    # ── Project management handlers ───────────────────────────────────────────

    async def _handle_projects_add(self, request: web.Request) -> web.Response:
        """POST /api/projects/add — register an existing directory as a project.

        Body: {"name": str, "path": str, "description": str, "lead": str,
               "decider": str, "agents": list, "humans": list, "skills": list}
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
                lead=body.get('lead', ''),
                decider=body.get('decider', ''),
                agents=body.get('agents') or [],
                humans=body.get('humans') or [],
                workgroups=body.get('workgroups') or [],
                skills=body.get('skills') or [],
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

        Body: {"name": str, "path": str, "description": str, "lead": str,
               "decider": str, "agents": list, "humans": list, "skills": list}
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
                lead=body.get('lead', ''),
                decider=body.get('decider', ''),
                agents=body.get('agents') or [],
                humans=body.get('humans') or [],
                workgroups=body.get('workgroups') or [],
                skills=body.get('skills') or [],
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

        status = result.get('status', '')
        if status == 'already_terminal':
            return web.json_response(result, status=409)

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

        return web.json_response(result)

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
        """
        session_id = request.match_info['session_id']
        from teaparty.bridge.state.dispatch_tree import build_dispatch_tree
        # _repo_root is the teaparty/ package; .teaparty/ is one level up
        repo_root = os.path.dirname(self._repo_root)
        sessions_dir = os.path.join(
            repo_root, '.teaparty', 'management', 'sessions')
        tree = build_dispatch_tree(sessions_dir, session_id)
        _log.debug('dispatch-tree %s: %d children, sessions_dir=%s',
                   session_id, len(tree.get('children', [])), sessions_dir)
        return web.json_response(tree)

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
        from datetime import datetime
        session_id = datetime.now().strftime('%Y%m%d-%H%M%S')
        conversation_id = f'job:{project_slug}:{session_id}'

        # Create and launch the CfA session as a background task.
        from teaparty.cfa.session import Session
        from teaparty.messaging.conversations import MessageBusInputProvider

        session = Session(
            task,
            poc_root=self._repo_root,
            project_override=project_slug,
            session_id=session_id,
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

        return web.json_response({
            'session_id': session_id,
            'conversation_id': conversation_id,
        })

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

        async def _run_resume():
            try:
                await Session.resume_from_disk(
                    infra_dir,
                    poc_root=self._repo_root,
                )
            except Exception:
                _log.exception(
                    'CfA session resume failed: project=%r session_id=%r',
                    project_slug, session_id,
                )

        task = asyncio.create_task(_run_resume())
        self._active_job_tasks[key] = task

    # ── Index handler ─────────────────────────────────────────────────────────

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
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        self._ws_clients.add(ws)
        try:
            async for msg in ws:
                pass  # Clients send no messages; all traffic is server-push
        finally:
            self._ws_clients.discard(ws)
        return ws

    # ── Internal helpers ──────────────────────────────────────────────────────

    # Conversation-ID prefix → agent name whose bus owns those conversations.
    _CONV_PREFIX_TO_AGENT: dict[str, str] = {
        'om:':     'office-manager',
        'pm:':     'project-manager',
        'proxy:':  'proxy-review',
        'config:': 'configuration-lead',
    }

    def _get_agent_bus(self, agent_name: str) -> SqliteMessageBus:
        """Return the persistent bus for *agent_name*, creating it if needed.

        Also registers the bus in ``self._buses`` so MessageRelay polls it.
        """
        bus = self._agent_buses.get(agent_name)
        if bus is None:
            path = agent_bus_path(self.teaparty_home, agent_name)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            bus = SqliteMessageBus(path)
            self._agent_buses[agent_name] = bus
            self._buses[agent_name] = bus
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
                return self._get_agent_bus(parts[1])

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
            result['humans'] = [
                {'name': h.name, 'role': h.role} for h in w.humans
            ]
            result['artifacts'] = list(w.artifacts)
        return result
