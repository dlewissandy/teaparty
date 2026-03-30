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

from aiohttp import web

from orchestrator.messaging import ConversationType, SqliteMessageBus
from orchestrator.office_manager import om_bus_path as _om_bus_path, OfficeManagerSession
from orchestrator.state_reader import StateReader
from orchestrator.heartbeat import _heartbeat_three_state
from orchestrator.config_reader import (
    load_management_team,
    load_project_team,
    load_workgroup,
    discover_projects,
    discover_skills,
    load_management_workgroups,
    resolve_workgroups,
    WorkgroupRef,
    WorkgroupEntry,
)
from scripts.cfa_state import load_state as _load_cfa_file
from bridge.poller import StatePoller
from bridge.message_relay import MessageRelay

_log = logging.getLogger('bridge.server')


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

    Delegates to _heartbeat_three_state() from orchestrator.heartbeat.
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

    Compares norms, budget, lead, agents, and skills.  Returns names of
    overridden categories, e.g. ['norms', 'budget'].
    """
    overrides: list[str] = []
    if project_workgroup.norms != org_workgroup.norms:
        overrides.append('norms')
    if project_workgroup.budget != org_workgroup.budget:
        overrides.append('budget')
    if project_workgroup.lead != org_workgroup.lead:
        overrides.append('lead')
    if project_workgroup.agents != org_workgroup.agents:
        overrides.append('agents')
    if project_workgroup.skills != org_workgroup.skills:
        overrides.append('skills')
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
        self._ws_clients: Set[web.WebSocketResponse] = set()
        # Shared bus registry: session_id -> SqliteMessageBus.
        # Populated by the StatePoller; consumed by MessageRelay.
        self._buses: dict[str, SqliteMessageBus] = {}
        # Office manager bus (persistent, not session-scoped).
        self._om_bus: SqliteMessageBus | None = None
        # In-flight OM invocation qualifiers (prevents concurrent invocations per conversation).
        self._om_in_flight: set[str] = set()
        # StateReader uses registry-based project discovery.
        self._state_reader = StateReader(
            repo_root=self._repo_root,
            teaparty_home=self.teaparty_home,
        )

    def run(self, port: int = 8081) -> None:
        """Start the bridge server and block until interrupted."""
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
        app.router.add_get('/api/config/{project}', self._handle_config_project)
        app.router.add_get('/api/workgroups', self._handle_workgroups)

        # ── Message endpoints ─────────────────────────────────────────────────
        app.router.add_get('/api/conversations', self._handle_conversations_list)
        app.router.add_get('/api/conversations/{id}', self._handle_conversation_get)
        app.router.add_post('/api/conversations/{id}', self._handle_conversation_post)

        # ── Artifact endpoints ────────────────────────────────────────────────
        app.router.add_get('/api/artifacts/{project}', self._handle_artifacts)
        app.router.add_get('/api/file', self._handle_file)

        # ── Action endpoints ──────────────────────────────────────────────────
        app.router.add_post('/api/withdraw/{session_id}', self._handle_withdraw)

        # ── Filesystem navigation endpoint ────────────────────────────────────
        app.router.add_get('/api/fs/list', self._handle_fs_list)

        # ── Project management endpoints ──────────────────────────────────────
        app.router.add_post('/api/projects/add', self._handle_projects_add)
        app.router.add_post('/api/projects/create', self._handle_projects_create)

        # ── WebSocket ─────────────────────────────────────────────────────────
        app.router.add_get('/ws', self._handle_websocket)

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

    async def _on_startup(self, app: web.Application) -> None:
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

        # Open the office manager bus (persistent, not session-scoped).
        # Add to self._buses so MessageRelay polls it alongside per-session buses.
        # The 'om' key is stable and will never collide with a session_id.
        om_path = _om_bus_path(self.teaparty_home)
        os.makedirs(os.path.dirname(om_path), exist_ok=True)
        self._om_bus = SqliteMessageBus(om_path)
        self._buses['om'] = self._om_bus

    async def _on_cleanup(self, app: web.Application) -> None:
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
        # self._om_bus is in self._buses['om'] and closed above

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
        from bridge.stats import compute_stats
        data = compute_stats(self.teaparty_home)
        return web.json_response(data)

    # ── Config handlers ───────────────────────────────────────────────────────

    async def _handle_config(self, request: web.Request) -> web.Response:
        try:
            team = load_management_team(teaparty_home=self.teaparty_home)
            projects = discover_projects(team)
            for p in projects:
                p['slug'] = os.path.basename(p['path'])
            org_skills_dir = os.path.join(self.teaparty_home, '.claude', 'skills')
            discovered_skills = discover_skills(org_skills_dir)
            return web.json_response({
                'management_team': self._serialize_management_team(
                    team, discovered_skills=discovered_skills,
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
            org_agents: list[str] = mgmt.agents
            org_catalog_skills: list[str] = discover_skills(
                os.path.join(self.teaparty_home, '.claude', 'skills')
            )
        except FileNotFoundError:
            org_agents = []
            org_catalog_skills = []

        local_skills: list[str] = discover_skills(
            os.path.join(project_dir, '.claude', 'skills')
        )

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
                    workgroups.append(
                        self._serialize_workgroup(w, source=source, overrides=overrides)
                    )
            except FileNotFoundError:
                _log.warning('Workgroup not found, skipping: %s', entry)

        return web.json_response({
            'project': slug,
            'team': self._serialize_project_team(
                team,
                org_agents=org_agents,
                local_skills=local_skills,
                registered_org_skills=team.skills,
                org_catalog_skills=org_catalog_skills,
            ),
            'workgroups': workgroups,
        })

    async def _handle_workgroups(self, request: web.Request) -> web.Response:
        try:
            team = load_management_team(teaparty_home=self.teaparty_home)
            workgroups = load_management_workgroups(team, teaparty_home=self.teaparty_home)
            return web.json_response([self._serialize_workgroup(w) for w in workgroups])
        except Exception:
            return web.json_response([])

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
            bus = self._get_om_bus()
            convs = bus.active_conversations(conv_type)
        else:
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

        messages = bus.receive(conv_id, since_timestamp=since_ts)
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

        bus = self._bus_for_conversation(conv_id)
        if bus is None:
            return web.json_response({'error': f'conversation not found: {conv_id}'}, status=404)

        try:
            msg_id = bus.send(conv_id, 'human', content)
        except ValueError as exc:
            return web.json_response({'error': str(exc)}, status=409)

        # Invoke the OM agent asynchronously for any om: conversation.
        # The response will appear in the bus and be broadcast by MessageRelay.
        if conv_id.startswith('om:'):
            qualifier = conv_id[len('om:'):]
            asyncio.create_task(self._invoke_om(qualifier))

        return web.json_response({'id': msg_id})

    async def _invoke_om(self, qualifier: str) -> None:
        """Invoke the office manager agent for the given conversation qualifier.

        Runs as a fire-and-forget asyncio task. The OM agent reads the conversation
        history, responds, and writes its reply to the OM bus. MessageRelay picks
        up the reply and broadcasts it to WebSocket clients.

        If an invocation is already in flight for this qualifier, this call is a
        no-op to prevent concurrent invocations against the same conversation.
        """
        if qualifier in self._om_in_flight:
            return
        self._om_in_flight.add(qualifier)
        try:
            session = OfficeManagerSession(self.teaparty_home, qualifier)
            await session.invoke(cwd=self._repo_root)
        except Exception:
            _log.exception('OM invocation failed for qualifier %r', qualifier)
        finally:
            self._om_in_flight.discard(qualifier)

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

    async def _handle_file(self, request: web.Request) -> web.Response:
        path = request.rel_url.query.get('path', '')
        if not path:
            return web.json_response({'error': 'path parameter required'}, status=400)
        path = os.path.expanduser(path)
        try:
            with open(path) as f:
                content = f.read()
        except FileNotFoundError:
            return web.json_response({'error': f'file not found: {path}'}, status=404)
        except PermissionError:
            return web.json_response({'error': 'permission denied'}, status=403)
        return web.Response(text=content, content_type='text/plain')

    # ── Filesystem navigation handler ─────────────────────────────────────────

    async def _handle_fs_list(self, request: web.Request) -> web.Response:
        """GET /api/fs/list?path=<p> — list directory contents for OM filesystem navigation."""
        path = request.rel_url.query.get('path', '')
        if not path:
            return web.json_response({'error': 'path parameter required'}, status=400)
        try:
            entries = _list_directory(path)
        except FileNotFoundError as exc:
            return web.json_response({'error': str(exc)}, status=404)
        return web.json_response({'entries': entries})

    # ── Project management handlers ───────────────────────────────────────────

    async def _handle_projects_add(self, request: web.Request) -> web.Response:
        """POST /api/projects/add — register an existing directory as a project.

        Body: {"name": str, "path": str, "description": str, "lead": str,
               "decider": str, "agents": list, "humans": list, "skills": list}
        Response: updated management team serialization.
        """
        from orchestrator.config_reader import add_project
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

        return web.json_response({
            'ok': True,
            'management_team': self._serialize_management_team(team),
        })

    async def _handle_projects_create(self, request: web.Request) -> web.Response:
        """POST /api/projects/create — scaffold a new project directory and register it.

        Body: {"name": str, "path": str, "description": str, "lead": str,
               "decider": str, "agents": list, "humans": list, "skills": list}
        Response: updated management team serialization.
        """
        from orchestrator.config_reader import create_project
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

        return web.json_response({
            'ok': True,
            'management_team': self._serialize_management_team(team),
        })

    # ── Action handlers ───────────────────────────────────────────────────────

    async def _handle_withdraw(self, request: web.Request) -> web.Response:
        session_id = request.match_info['session_id']
        sock_path = _withdrawal_socket_path(self.teaparty_home, session_id)

        if not os.path.exists(sock_path):
            return web.json_response(
                {'error': 'intervention socket not available for this session'},
                status=503,
            )

        payload = json.dumps({'type': 'withdraw_session', 'session_id': session_id})
        try:
            reader, writer = await asyncio.open_unix_connection(sock_path)
            writer.write(payload.encode() + b'\n')
            await writer.drain()
            line = await reader.readline()
            writer.close()
            await writer.wait_closed()
            response = json.loads(line.decode())
        except Exception as exc:
            return web.json_response({'error': str(exc)}, status=502)

        return web.json_response(response)

    # ── Index handler ─────────────────────────────────────────────────────────

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

    def _get_om_bus(self) -> SqliteMessageBus:
        """Return the office manager bus, creating it if needed."""
        if self._om_bus is None:
            om_path = _om_bus_path(self.teaparty_home)
            os.makedirs(os.path.dirname(om_path), exist_ok=True)
            self._om_bus = SqliteMessageBus(om_path)
        return self._om_bus

    def _bus_for_conversation(self, conv_id: str) -> SqliteMessageBus | None:
        """Find the bus that owns a conversation.

        Office manager conversations (om:*) go to the OM bus.
        All other conversations are searched across active session buses.
        """
        if conv_id.startswith('om:'):
            return self._get_om_bus()
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
        """
        try:
            team = load_management_team(teaparty_home=self.teaparty_home)
            for entry in discover_projects(team):
                if os.path.basename(entry['path'].rstrip('/')) == slug:
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
            candidate = os.path.join(entry['path'], '.sessions', session_id)
            if os.path.isdir(candidate):
                return candidate
        return None

    # ── Serializers ───────────────────────────────────────────────────────────

    def _serialize_project(self, p) -> dict:
        return {
            'slug': p.slug,
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
        self, t, discovered_skills: list[str] | None = None
    ) -> dict:
        return {
            'name': t.name,
            'description': t.description,
            'lead': t.lead,
            'decider': t.decider,
            'agents': t.agents,
            'humans': [{'name': h.name, 'role': h.role} for h in t.humans],
            'skills': discovered_skills if discovered_skills is not None else t.skills,
            'hooks': t.hooks,
            'scheduled': [
                {'name': s.name, 'schedule': s.schedule, 'enabled': s.enabled}
                for s in t.scheduled
            ],
        }

    def _serialize_project_team(
        self, t,
        org_agents: list[str] | None = None,
        local_skills: list[str] | None = None,
        registered_org_skills: list[str] | None = None,
        org_catalog_skills: list[str] | None = None,
    ) -> dict:
        org_agents_set = set(org_agents or [])
        local_skills_set = set(local_skills or [])
        org_catalog_set = set(org_catalog_skills or [])

        def _agent_source(name: str) -> str:
            if name == t.lead:
                return 'generated'
            return 'shared' if name in org_agents_set else 'local'

        # Build merged skill list: local first, then registered org skills.
        # Local takes precedence on name collision.
        # Registered org skills absent from the org catalog are flagged as 'missing'.
        skills_result = []
        for name in sorted(local_skills or []):
            skills_result.append({'name': name, 'source': 'local'})
        for name in (registered_org_skills or []):
            if name not in local_skills_set:
                source = 'shared' if name in org_catalog_set else 'missing'
                skills_result.append({'name': name, 'source': source})

        return {
            'name': t.name,
            'description': t.description,
            'lead': t.lead,
            'decider': t.decider,
            'agents': [{'name': n, 'source': _agent_source(n)} for n in t.agents],
            'humans': [{'name': h.name, 'role': h.role} for h in t.humans],
            'skills': skills_result,
            'hooks': t.hooks,
            'scheduled': [
                {'name': s.name, 'schedule': s.schedule, 'enabled': s.enabled}
                for s in t.scheduled
            ],
        }

    def _serialize_workgroup(
        self, w, source: str | None = None, overrides: list[str] | None = None
    ) -> dict:
        return {
            'name': w.name,
            'description': w.description,
            'lead': w.lead,
            'agents_count': len(w.agents),
            'source': source,
            'overrides': overrides or [],
        }
