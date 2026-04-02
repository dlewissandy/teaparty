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

from orchestrator.messaging import ConversationType, SqliteMessageBus
from orchestrator.office_manager import om_bus_path as _om_bus_path, OfficeManagerSession, read_om_session_title
from orchestrator.project_manager import pm_bus_path as _pm_bus_path, ProjectManagerSession, read_pm_session_title
from orchestrator.proxy_review import (
    proxy_bus_path as _proxy_bus_path,
    ProxyReviewSession,
    read_proxy_session_title,
)
from orchestrator.state_reader import StateReader
from orchestrator.heartbeat import _heartbeat_three_state
from orchestrator.config_reader import (
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
        self._ws_clients: Set[web.WebSocketResponse] = set()
        # Shared bus registry: session_id -> SqliteMessageBus.
        # Populated by the StatePoller; consumed by MessageRelay.
        self._buses: dict[str, SqliteMessageBus] = {}
        # Office manager bus (persistent, not session-scoped).
        self._om_bus: SqliteMessageBus | None = None
        # Per-qualifier asyncio locks: queues concurrent OM invocations rather than dropping them.
        self._om_locks: dict[str, asyncio.Lock] = {}
        # Per-qualifier OM session cache: keeps the OfficeManagerSession alive across invocations
        # so the --resume session ID is available in memory between turns.
        self._om_sessions: dict[str, OfficeManagerSession] = {}
        # Project manager bus (persistent, not session-scoped).
        self._pm_bus: SqliteMessageBus | None = None
        # Per-qualifier (project_slug:user_id) asyncio locks for PM invocations.
        self._pm_locks: dict[str, asyncio.Lock] = {}
        # Per-qualifier PM session cache.
        self._pm_sessions: dict[str, ProjectManagerSession] = {}
        # Proxy review bus (persistent, not session-scoped).
        self._proxy_bus: SqliteMessageBus | None = None
        # Per-qualifier asyncio locks for proxy review: queues concurrent invocations.
        self._proxy_locks: dict[str, asyncio.Lock] = {}
        # Per-qualifier proxy session cache: keeps ProxyReviewSession alive across invocations.
        self._proxy_sessions: dict[str, ProxyReviewSession] = {}
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
        app.router.add_get('/api/artifacts/{project}', self._handle_artifacts)
        app.router.add_get('/api/artifacts/{project}/pins', self._handle_artifact_pins)
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

        # Open the project manager bus (persistent, not session-scoped).
        # The 'pm' key is stable and will never collide with a session_id.
        pm_path = _pm_bus_path(self.teaparty_home)
        os.makedirs(os.path.dirname(pm_path), exist_ok=True)
        self._pm_bus = SqliteMessageBus(pm_path)
        self._buses['pm'] = self._pm_bus

        # Open the proxy review bus (persistent, not session-scoped).
        # The 'proxy' key is stable and will never collide with a session_id.
        proxy_path = _proxy_bus_path(self.teaparty_home)
        os.makedirs(os.path.dirname(proxy_path), exist_ok=True)
        self._proxy_bus = SqliteMessageBus(proxy_path)
        self._buses['proxy'] = self._proxy_bus

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
        # self._proxy_bus is in self._buses['proxy'] and closed above

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
            active_projects = set(team.members_projects)
            for p in projects:
                p['slug'] = os.path.basename(p['path'])
                p['active'] = p['name'] in active_projects
            claude_base = os.path.dirname(self.teaparty_home)
            org_agents_dir = os.path.join(claude_base, '.claude', 'agents')
            org_skills_dir = os.path.join(claude_base, '.claude', 'skills')
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

        claude_base = os.path.dirname(self.teaparty_home)
        try:
            mgmt = load_management_team(teaparty_home=self.teaparty_home)
            org_agents: list[str] = mgmt.members_agents
            org_catalog_skills: list[str] = discover_skills(
                os.path.join(claude_base, '.claude', 'skills')
            )
        except FileNotFoundError:
            org_agents = []
            org_catalog_skills = []

        org_catalog_agents: list[str] = discover_agents(
            os.path.join(claude_base, '.claude', 'agents')
        )

        local_skills: list[str] = discover_skills(
            os.path.join(project_dir, '.claude', 'skills')
        )

        project_catalog = merge_catalog(
            os.path.join(claude_base, '.claude'),
            os.path.join(project_dir, '.claude'),
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
                registered_org_skills=org_catalog_skills,
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
        if kind not in ('agent', 'project', 'workgroup', 'skill', 'hook', 'scheduled_task') or not name or not isinstance(active, bool):
            return web.json_response(
                {'error': 'body must include type (agent|project|workgroup|skill|hook|scheduled_task), name, and active (bool)'},
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
        try:
            toggle_project_membership(project_dir, kind, name, active)
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
        claude_base = os.path.dirname(self.teaparty_home)
        if project_slug:
            project_dir = self._lookup_project_path(project_slug)
            if project_dir is None:
                return web.json_response({'error': f'project not found: {project_slug}'}, status=404)
            yaml_path = os.path.join(project_dir, '.teaparty.local', 'workgroups', f'{wg_name}.yaml')
            if not os.path.exists(yaml_path):
                yaml_path = os.path.join(self.teaparty_home, 'workgroups', f'{wg_name}.yaml')
        else:
            yaml_path = os.path.join(self.teaparty_home, 'workgroups', f'{wg_name}.yaml')
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
        claude_base = os.path.dirname(self.teaparty_home)
        if project_slug:
            project_dir = self._lookup_project_path(project_slug)
            if project_dir is None:
                return web.json_response({'error': f'project not found: {project_slug}'}, status=404)
            yaml_path = os.path.join(project_dir, '.teaparty.local', 'workgroups', f'{wg_name}.yaml')
            if not os.path.exists(yaml_path):
                yaml_path = os.path.join(self.teaparty_home, 'workgroups', f'{wg_name}.yaml')
        else:
            yaml_path = os.path.join(self.teaparty_home, 'workgroups', f'{wg_name}.yaml')
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

        claude_base = os.path.dirname(self.teaparty_home)
        catalog = merge_catalog(
            os.path.join(claude_base, '.claude'),
            os.path.join(project_dir, '.claude') if project_dir else None,
        )
        org_catalog_agents: list[str] = catalog.agents
        org_hooks: list[dict] = catalog.hooks
        # Management-only set for 'shared' vs 'local' source tagging in the serializer.
        org_agents_set: set[str] = set(
            discover_agents(os.path.join(claude_base, '.claude', 'agents'))
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
        claude_base = os.path.dirname(self.teaparty_home)
        if project_slug:
            project_dir = self._lookup_project_path(project_slug)
            if project_dir is None:
                return web.json_response({'error': f'project not found: {project_slug}'}, status=404)
            yaml_path = os.path.join(project_dir, '.teaparty.local', 'workgroups', f'{name}.yaml')
            if not os.path.exists(yaml_path):
                yaml_path = os.path.join(self.teaparty_home, 'workgroups', f'{name}.yaml')
        else:
            yaml_path = os.path.join(self.teaparty_home, 'workgroups', f'{name}.yaml')
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
            os.path.join(claude_base, '.claude'),
            os.path.join(project_dir, '.claude') if project_dir else None,
        )
        return web.json_response(
            self._serialize_workgroup(
                wg, detail=True,
                org_agents=set(discover_agents(os.path.join(claude_base, '.claude', 'agents'))),
                org_catalog_agents=catalog.agents,
                org_hooks_catalog=catalog.hooks,
            )
        )

    async def _handle_agent_detail(self, request: web.Request) -> web.Response:
        name = request.match_info['name']
        project_slug = request.rel_url.query.get('project')
        claude_base = os.path.dirname(self.teaparty_home)
        path: str | None = None
        if project_slug:
            project_dir = self._lookup_project_path(project_slug)
            if project_dir is None:
                return web.json_response({'error': f'project not found: {project_slug}'}, status=404)
            proj_path = os.path.join(project_dir, '.claude', 'agents', f'{name}.md')
            if os.path.exists(proj_path):
                path = proj_path
        if path is None:
            org_path = os.path.join(claude_base, '.claude', 'agents', f'{name}.md')
            if os.path.exists(org_path):
                path = org_path
        if path is None:
            return web.json_response({'error': f'agent not found: {name}'}, status=404)
        fm = read_agent_frontmatter(path)
        return web.json_response(fm)

    async def _handle_agent_patch(self, request: web.Request) -> web.Response:
        name = request.match_info['name']
        project_slug = request.rel_url.query.get('project')
        claude_base = os.path.dirname(self.teaparty_home)
        path: str | None = None
        if project_slug:
            project_dir = self._lookup_project_path(project_slug)
            if project_dir is None:
                return web.json_response({'error': f'project not found: {project_slug}'}, status=404)
            proj_path = os.path.join(project_dir, '.claude', 'agents', f'{name}.md')
            if os.path.exists(proj_path):
                path = proj_path
        if path is None:
            org_path = os.path.join(claude_base, '.claude', 'agents', f'{name}.md')
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
        claude_base = os.path.dirname(self.teaparty_home)
        catalog = merge_catalog(
            os.path.join(claude_base, '.claude'),
            os.path.join(project_dir, '.claude'),
        )
        return web.json_response({
            'agents': catalog.agents,
            'skills': catalog.skills,
            'hooks': catalog.hooks,
        })

    async def _handle_catalog_org(self, request: web.Request) -> web.Response:
        claude_base = os.path.dirname(self.teaparty_home)
        catalog = merge_catalog(os.path.join(claude_base, '.claude'))
        return web.json_response({
            'agents': catalog.agents,
            'skills': catalog.skills,
            'hooks': catalog.hooks,
        })

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
            result = []
            for c in convs:
                d = self._serialize_conversation(c)
                qualifier = c.id[len('om:'):] if c.id.startswith('om:') else ''
                if qualifier:
                    session = self._om_sessions.get(qualifier)
                    title = (
                        (session.conversation_title if session else None)
                        or read_om_session_title(self.teaparty_home, qualifier)
                    )
                    if title:
                        d['title'] = title
                result.append(d)
            return web.json_response(result)

        # Route project_manager type to the persistent PM bus
        if conv_type == ConversationType.PROJECT_MANAGER:
            bus = self._get_pm_bus()
            convs = bus.active_conversations(conv_type)
            result = []
            for c in convs:
                d = self._serialize_conversation(c)
                # qualifier is '{slug}:{user}' — strip the 'pm:' prefix
                qualifier = c.id[len('pm:'):] if c.id.startswith('pm:') else ''
                if qualifier:
                    session = self._pm_sessions.get(qualifier)
                    parts = qualifier.split(':', 1)
                    project_slug = parts[0]
                    user_id = parts[1] if len(parts) > 1 else ''
                    title = (
                        (session.conversation_title if session else None)
                        or read_pm_session_title(self.teaparty_home, project_slug, user_id)
                    )
                    if title:
                        d['title'] = title
                result.append(d)
            return web.json_response(result)

        # Route proxy_review type to the persistent proxy bus (issue #331)
        if conv_type == ConversationType.PROXY_REVIEW:
            bus = self._get_proxy_bus()
            convs = bus.active_conversations(conv_type)
            result = []
            for c in convs:
                d = self._serialize_conversation(c)
                qualifier = c.id[len('proxy:'):] if c.id.startswith('proxy:') else ''
                if qualifier:
                    session = self._proxy_sessions.get(qualifier)
                    title = (
                        (session.conversation_title if session else None)
                        or read_proxy_session_title(self.teaparty_home, qualifier)
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
        if qualifier not in self._om_locks:
            self._om_locks[qualifier] = asyncio.Lock()
        lock = self._om_locks[qualifier]

        async with lock:
            if qualifier not in self._om_sessions:
                self._om_sessions[qualifier] = OfficeManagerSession(self.teaparty_home, qualifier)
            session = self._om_sessions[qualifier]
            try:
                await session.invoke(cwd=self._repo_root)
            except Exception:
                _log.exception('OM invocation failed for qualifier %r', qualifier)
                try:
                    session.send_agent_message(
                        'Sorry, I encountered an error and could not respond. '
                        'Please try again.'
                    )
                except Exception:
                    _log.exception('Failed to write error message to OM bus for %r', qualifier)

    async def _invoke_pm(self, qualifier: str) -> None:
        """Invoke the project manager agent for the given conversation qualifier.

        qualifier is '{project_slug}:{user_id}' e.g. 'jainai:darrell'.
        Runs as a fire-and-forget asyncio task. Concurrent invocations for the
        same qualifier queue via an asyncio.Lock.
        """
        if qualifier not in self._pm_locks:
            self._pm_locks[qualifier] = asyncio.Lock()
        lock = self._pm_locks[qualifier]

        async with lock:
            if qualifier not in self._pm_sessions:
                parts = qualifier.split(':', 1)
                project_slug = parts[0]
                user_id = parts[1] if len(parts) > 1 else qualifier
                self._pm_sessions[qualifier] = ProjectManagerSession(
                    self.teaparty_home, project_slug, user_id,
                )
            session = self._pm_sessions[qualifier]
            try:
                project_path = self._lookup_project_path(session.project_slug)
                cwd = project_path if project_path is not None else self._repo_root
                await session.invoke(cwd=cwd)
            except Exception:
                _log.exception('PM invocation failed for qualifier %r', qualifier)
                try:
                    session.send_agent_message(
                        'Sorry, I encountered an error and could not respond. '
                        'Please try again.'
                    )
                except Exception:
                    _log.exception('Failed to write error message to PM bus for %r', qualifier)

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
        if qualifier not in self._proxy_locks:
            self._proxy_locks[qualifier] = asyncio.Lock()
        lock = self._proxy_locks[qualifier]

        async with lock:
            if qualifier not in self._proxy_sessions:
                self._proxy_sessions[qualifier] = ProxyReviewSession(self.teaparty_home, qualifier)
            session = self._proxy_sessions[qualifier]
            try:
                await session.invoke(cwd=self._repo_root)
            except Exception:
                _log.exception('Proxy invocation failed for qualifier %r', qualifier)
                try:
                    session.send_agent_message(
                        'Sorry, I encountered an error and could not respond. '
                        'Please try again.'
                    )
                except Exception:
                    _log.exception('Failed to write error message to proxy bus for %r', qualifier)

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

    async def _handle_artifact_pins(self, request: web.Request) -> web.Response:
        """GET /api/artifacts/{project}/pins — return artifact_pins with absolute paths and is_dir."""
        from orchestrator.config_reader import load_project_team
        project = request.match_info['project']
        proj_path = self._lookup_project_path(project)
        if proj_path is None:
            return web.json_response({'error': f'project not found: {project}'}, status=404)

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
                'label': label,
                'is_dir': os.path.isdir(abs_path),
            })
        return web.json_response(result)

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

        discovered_skills = discover_skills(
            os.path.join(os.path.dirname(self.teaparty_home), '.claude', 'skills')
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

        discovered_skills = discover_skills(
            os.path.join(os.path.dirname(self.teaparty_home), '.claude', 'skills')
        )
        return web.json_response({
            'ok': True,
            'management_team': self._serialize_management_team(
                team, discovered_skills=discovered_skills,
            ),
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

    def _get_pm_bus(self) -> SqliteMessageBus:
        """Return the project manager bus, creating it if needed."""
        if self._pm_bus is None:
            pm_path = _pm_bus_path(self.teaparty_home)
            os.makedirs(os.path.dirname(pm_path), exist_ok=True)
            self._pm_bus = SqliteMessageBus(pm_path)
        return self._pm_bus

    def _get_proxy_bus(self) -> SqliteMessageBus:
        """Return the proxy review bus, creating it if needed."""
        if self._proxy_bus is None:
            proxy_path = _proxy_bus_path(self.teaparty_home)
            os.makedirs(os.path.dirname(proxy_path), exist_ok=True)
            self._proxy_bus = SqliteMessageBus(proxy_path)
        return self._proxy_bus

    def _bus_for_conversation(self, conv_id: str) -> SqliteMessageBus | None:
        """Find the bus that owns a conversation.

        Office manager conversations (om:*) go to the OM bus.
        Proxy review conversations (proxy:*) go to the proxy bus.
        All other conversations are searched across active session buses.
        """
        if conv_id.startswith('om:'):
            return self._get_om_bus()
        if conv_id.startswith('pm:'):
            return self._get_pm_bus()
        if conv_id.startswith('proxy:'):
            return self._get_proxy_bus()
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
        claude_base = os.path.dirname(home)  # .teaparty/ parent = repo root
        agents_dir = os.path.join(claude_base, '.claude', 'agents')
        skills_dir = os.path.join(claude_base, '.claude', 'skills')
        config_yaml = os.path.join(home, 'teaparty.yaml')

        def _agent_file(name: str) -> str | None:
            path = os.path.join(agents_dir, f'{name}.md')
            return path if os.path.isfile(path) else None

        def _skill_file(name: str) -> str | None:
            path = os.path.join(skills_dir, name, 'SKILL.md')
            return path if os.path.isfile(path) else None

        def _hook_file(hook: dict) -> str:
            cmd = hook.get('command', '')
            if cmd and os.path.isabs(cmd) and os.path.isfile(cmd):
                return cmd
            # Resolve relative command paths against the claude_base directory.
            if cmd:
                resolved = os.path.join(claude_base, cmd)
                if os.path.isfile(resolved):
                    return resolved
            return config_yaml

        def _task_file(skill_name: str) -> str | None:
            path = os.path.join(skills_dir, skill_name, 'SKILL.md')
            return path if os.path.isfile(path) else None

        settings_hooks = discover_hooks(os.path.join(claude_base, '.claude', 'settings.json'))
        yaml_hooks = [
            {**h, 'active': h.get('active', True), 'source': 'yaml'}
            for h in t.hooks
        ]
        sys_hooks = [{**h, 'active': True, 'source': 'settings'} for h in settings_hooks]
        all_hooks = yaml_hooks + sys_hooks

        # Full agent catalog: all agents in .claude/agents/, with active: bool.
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

    def _serialize_project_team(
        self, t,
        org_agents: list[str] | None = None,
        org_catalog_agents: list[str] | None = None,
        local_skills: list[str] | None = None,
        registered_org_skills: list[str] | None = None,
        org_catalog_skills: list[str] | None = None,
        teaparty_home: str | None = None,
        project_dir: str | None = None,
        catalog_hooks: list[dict] | None = None,
    ) -> dict:
        org_agents_set = set(org_agents or [])
        local_skills_set = set(local_skills or [])
        org_catalog_set = set(org_catalog_skills or [])
        home = teaparty_home or self.teaparty_home
        claude_base = os.path.dirname(home)  # .teaparty/ parent = repo root
        proj = project_dir or ''

        org_agents_dir = os.path.join(claude_base, '.claude', 'agents')
        proj_agents_dir = os.path.join(proj, '.claude', 'agents') if proj else ''
        org_skills_dir = os.path.join(claude_base, '.claude', 'skills')
        proj_skills_dir = os.path.join(proj, '.claude', 'skills') if proj else ''
        proj_config = os.path.join(proj, '.teaparty.local', 'project.yaml') if proj else ''

        def _agent_source(name: str) -> str:
            if name == t.lead:
                return 'generated'
            return 'shared' if name in org_agents_set else 'local'

        def _agent_file(name: str) -> str | None:
            source = _agent_source(name)
            if source == 'shared':
                path = os.path.join(org_agents_dir, f'{name}.md')
            elif proj_agents_dir:
                path = os.path.join(proj_agents_dir, f'{name}.md')
            else:
                return None
            return path if os.path.isfile(path) else None

        def _skill_file(name: str, source: str) -> str | None:
            if source == 'local':
                path = os.path.join(proj_skills_dir, name, 'SKILL.md') if proj_skills_dir else None
            elif source == 'shared':
                path = os.path.join(org_skills_dir, name, 'SKILL.md')
            else:
                return None  # missing
            return path if path and os.path.isfile(path) else None

        def _hook_file(hook: dict) -> str:
            cmd = hook.get('command', '')
            if cmd and os.path.isabs(cmd) and os.path.isfile(cmd):
                return cmd
            # Resolve relative command paths against the project's .claude/ directory.
            if cmd and proj:
                resolved = os.path.join(proj, cmd)
                if os.path.isfile(resolved):
                    return resolved
            return proj_config

        def _task_file(skill_name: str) -> str | None:
            # Local skills take precedence over org skills.
            if proj_skills_dir and skill_name in local_skills_set:
                path = os.path.join(proj_skills_dir, skill_name, 'SKILL.md')
                return path if os.path.isfile(path) else None
            path = os.path.join(org_skills_dir, skill_name, 'SKILL.md')
            return path if os.path.isfile(path) else None

        # Project teams dispatch to workgroups, not individual agents.
        agents_result = []

        # Build merged skill list: local first, then any explicitly passed org skills.
        # Project-level registered_org_skills no longer come from the YAML schema
        # (removed in issue #362) but the parameter is kept for backward compatibility.
        registered_set = set(registered_org_skills or [])
        skills_result = []
        seen_skills: set[str] = set()
        for name in sorted(local_skills or []):
            source = 'local'
            skills_result.append({
                'name': name, 'source': source,
                'file': _skill_file(name, source), 'active': name in registered_set,
            })
            seen_skills.add(name)
        # All org catalog skills (registered active ones first, then inactive)
        active_org_skills = [n for n in (registered_org_skills or []) if n not in seen_skills]
        inactive_org_skills = [n for n in (org_catalog_skills or []) if n not in seen_skills and n not in registered_set]
        for name in active_org_skills:
            source = 'shared' if name in org_catalog_set else 'missing'
            skills_result.append({
                'name': name, 'source': source,
                'file': _skill_file(name, source), 'active': True,
            })
            seen_skills.add(name)
        for name in inactive_org_skills:
            source = 'shared'
            skills_result.append({
                'name': name, 'source': source,
                'file': _skill_file(name, source), 'active': False,
            })
            seen_skills.add(name)

        if catalog_hooks is not None:
            settings_hooks = catalog_hooks
        else:
            proj_settings = os.path.join(proj, '.claude', 'settings.json') if proj else ''
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
            _wg_claude_base = os.path.dirname(self.teaparty_home)
            _wg_agents_dir = os.path.join(_wg_claude_base, '.claude', 'agents')

            def _wg_agent_file(n: str) -> str | None:
                path = os.path.join(_wg_agents_dir, f'{n}.md')
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
