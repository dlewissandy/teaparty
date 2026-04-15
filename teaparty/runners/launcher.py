"""Unified agent launcher — one codepath, config-driven, SLA-compliant.

Every agent in TeaParty launches through the functions in this module.
The launcher reads .teaparty/ config and produces the correct ``claude -p``
invocation.  No special cases, no alternative paths.

Design: docs/detailed-design/unified-agent-launch.md
Issue: #394
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

import yaml

from teaparty.runners.claude import ClaudeResult
from teaparty.telemetry import events as _telem_events
from teaparty.telemetry import record_event


# ── Data ─────────────────────────────────────────────────────────────────────

@dataclass
class Session:
    """An agent session — 1:1 with a Claude session ID.

    Three launch modes live in this dataclass:

    - **Privileged top-level chat** (OM, a project lead as top-level of
      its project's chat): ``launch_cwd`` is the real repo root; no
      worktree fields are set; no merge target.

    - **Dispatched chat** (everyone else that runs in a subchat):
      ``worktree_path`` is the per-session worktree dir on branch
      ``worktree_branch`` (``session/{session_id}``). The merge_target_*
      fields record where ``CloseConversation`` must squash-merge the
      session branch back to. For same-repo dispatches the target is
      the dispatcher's worktree/branch (the dispatcher's working state
      is the integration branch). For the cross-repo exception (OM
      dispatches a project lead whose repo differs) the target is the
      project repo's **default branch**, in the project's main checkout.

    - **CfA job**: ``launch_cwd`` holds the worktree path (legacy field
      name); merge_target fields empty. The CfA engine owns its
      worktree lifecycle separately from CloseConversation.
    """
    id: str
    path: str
    agent_name: str
    scope: str
    claude_session_id: str = ''
    conversation_map: dict[str, str] = field(default_factory=dict)
    launch_cwd: str = ''
    worktree_path: str = ''
    worktree_branch: str = ''
    merge_target_repo: str = ''
    merge_target_branch: str = ''
    merge_target_worktree: str = ''
    # Execution phase — written continuously by the subtree loop so that
    # a pause (task cancellation) lands with an accurate snapshot.
    # One of 'launching', 'awaiting', 'complete'.
    phase: str = 'launching'
    # Final integrated reply text — populated on normal loop exit so a
    # resumed parent can collect a 'complete' child's answer without
    # re-running any LLM work.
    response_text: str = ''
    # The project this session belongs to (slug). Empty for management
    # sessions. Used by pause/resume to scope subtree walks.
    project_slug: str = ''
    # Parent session id for on-disk tree walking. Empty at the root.
    parent_session_id: str = ''
    # The message currently being processed. Persisted at the start of
    # each turn so a launching-phase resume can re-run that turn via
    # --resume with the same input. The in-flight grandchild ids at the
    # time the session entered 'awaiting' are needed by the resume
    # walker to rebuild the task chain.
    current_message: str = ''
    in_flight_gc_ids: list[str] = field(default_factory=list)
    # Dispatcher's initial input to this session (the `composite` used
    # on the first _launch). Retained so a launching-phase resume of
    # the very first turn has the original prompt to re-run.
    initial_message: str = ''


# ── Agent definition resolution ──────────────────────────────────────────────

def resolve_agent_definition(
    agent_name: str,
    scope: str,
    teaparty_home: str,
    *,
    org_home: str | None = None,
) -> str:
    """Resolve the agent definition path: scope-first, fall back to management.

    Search order:
      1. {teaparty_home}/{scope}/agents/{agent_name}/agent.md
      2. {teaparty_home}/management/agents/{agent_name}/agent.md
      3. {org_home}/management/agents/{agent_name}/agent.md  (if org_home differs)

    The org_home parameter supports CfA project jobs, where teaparty_home is
    the project's .teaparty/ directory and the org-level management catalog
    lives at {poc_root}/.teaparty/ (Issue #408).

    Returns the absolute path to the agent.md file.

    Raises:
        FileNotFoundError: If no agent definition exists in any search location.
    """
    # 1. Scope-specific path in primary home
    scope_path = os.path.join(
        teaparty_home, scope, 'agents', agent_name, 'agent.md',
    )
    if os.path.isfile(scope_path):
        return scope_path

    # 2. Management fallback in primary home (unless already looking there)
    if scope != 'management':
        mgmt_path = os.path.join(
            teaparty_home, 'management', 'agents', agent_name, 'agent.md',
        )
        if os.path.isfile(mgmt_path):
            return mgmt_path

    # 3. Org management catalog (CfA project jobs: project home ≠ org home)
    if org_home and os.path.normpath(org_home) != os.path.normpath(teaparty_home):
        org_mgmt_path = os.path.join(
            org_home, 'management', 'agents', agent_name, 'agent.md',
        )
        if os.path.isfile(org_mgmt_path):
            return org_mgmt_path

    raise FileNotFoundError(
        f'No agent definition for {agent_name!r} in scope {scope!r} '
        f'at {teaparty_home!r}'
        + (f' or org management at {org_home!r}' if org_home else '')
    )


# ── Worktree composition ────────────────────────────────────────────────────

def compose_launch_worktree(
    *,
    worktree: str,
    agent_name: str,
    scope: str,
    teaparty_home: str,
    org_home: str | None = None,
    mcp_port: int = 0,
    session_id: str = '',
) -> None:
    """Compose the .claude/ directory in a worktree for an agent launch.

    Writes into the existing .claude/ directory without overwriting CLAUDE.md.
    The repo's CLAUDE.md is the project-level instruction file and must not
    be replaced.

    Composes:
    - .claude/agents/{name}.md — the agent's own definition
    - .claude/skills/{name}/ — filtered by agent's skills: frontmatter
    - .claude/settings.json — scope settings merged with agent settings
    - .mcp.json — HTTP MCP endpoint scoped to the agent

    org_home: when set, the org-level .teaparty/ directory used as a
    management-catalog fallback for agent definitions and skills that
    are not found in teaparty_home (Issue #408).
    """
    from teaparty.config.config_reader import read_agent_frontmatter

    try:
        agent_def_path = resolve_agent_definition(
            agent_name, scope, teaparty_home, org_home=org_home,
        )
        fm = read_agent_frontmatter(agent_def_path)
    except FileNotFoundError:
        # Agent definition not in .teaparty/ — compose what we can
        # (settings, MCP config) without the agent-specific parts.
        agent_def_path = ''
        fm = {}

    claude_dir = os.path.join(worktree, '.claude')
    os.makedirs(claude_dir, exist_ok=True)

    # ── Agent definition ─────────────────────────────────────────────────
    agents_dir = os.path.join(claude_dir, 'agents')
    os.makedirs(agents_dir, exist_ok=True)
    # Clean old agent definitions
    for entry in os.scandir(agents_dir):
        if entry.is_symlink() or entry.name.endswith('.md'):
            os.unlink(entry.path)
    if agent_def_path:
        dest_md = os.path.join(agents_dir, f'{agent_name}.md')
        shutil.copy2(agent_def_path, dest_md)

    # ── Skills (filtered by agent allowlist) ─────────────────────────────
    allowed_skills = fm.get('skills') or []
    skills_dest = os.path.join(claude_dir, 'skills')
    # Clean old skills
    if os.path.isdir(skills_dest):
        shutil.rmtree(skills_dest)
    if allowed_skills:
        os.makedirs(skills_dest, exist_ok=True)
        # Search order: scope in primary home → management in primary home
        # → management in org home (Issue #408 fallback for project jobs)
        for skill_name in allowed_skills:
            skill_src = os.path.join(
                teaparty_home, scope, 'skills', skill_name,
            )
            if not os.path.isdir(skill_src) and scope != 'management':
                skill_src = os.path.join(
                    teaparty_home, 'management', 'skills', skill_name,
                )
            if not os.path.isdir(skill_src) and org_home:
                skill_src = os.path.join(
                    org_home, 'management', 'skills', skill_name,
                )
            if os.path.isdir(skill_src):
                os.symlink(
                    os.path.abspath(skill_src),
                    os.path.join(skills_dest, skill_name),
                )

    # ── Settings (scope base + agent override) ───────────────────────────
    settings = _merge_settings(agent_name, scope, teaparty_home)
    settings_path = os.path.join(claude_dir, 'settings.json')
    with open(settings_path, 'w') as f:
        json.dump(settings, f, indent=2)

    # ── MCP config ───────────────────────────────────────────────────────
    if mcp_port:
        if session_id:
            mcp_url = f'http://localhost:{mcp_port}/mcp/{scope}/{agent_name}/{session_id}'
        else:
            mcp_url = f'http://localhost:{mcp_port}/mcp/{scope}/{agent_name}'
        mcp_data = {
            'mcpServers': {
                'teaparty-config': {
                    'type': 'http',
                    'url': mcp_url,
                },
            },
        }
        mcp_path = os.path.join(worktree, '.mcp.json')
        with open(mcp_path, 'w') as f:
            json.dump(mcp_data, f, indent=2)


def chat_config_dir(
    teaparty_home: str,
    scope: str,
    agent_name: str,
    qualifier: str,
) -> str:
    """Return the per-launch config directory for a chat-tier agent.

    Issue #397 fixes the location at
    ``{teaparty_home}/{scope}/agents/{agent_name}/{qualifier}/config/``.
    Parallel instances of the same agent use different *qualifier*
    strings (child session id for dispatches, ``AgentSession.qualifier``
    for top-level invokes) so they do not clobber each other.

    When *qualifier* is empty (singleton agents like the office manager)
    the qualifier segment is omitted:
    ``{teaparty_home}/{scope}/agents/{agent_name}/config/``.
    """
    if qualifier:
        safe_qualifier = qualifier.replace('/', '-').replace(':', '-').replace(' ', '-')
        return os.path.join(
            teaparty_home, scope, 'agents', agent_name, safe_qualifier, 'config',
        )
    return os.path.join(teaparty_home, scope, 'agents', agent_name, 'config')


def compose_launch_config(
    *,
    config_dir: str,
    agent_name: str,
    scope: str,
    teaparty_home: str,
    mcp_port: int = 0,
    session_id: str = '',
) -> dict[str, str]:
    """Compose per-launch config files for a chat-tier agent launch.

    Writes three files into *config_dir* (the spec'd location under
    ``{teaparty_home}/{scope}/agents/{agent_name}/{qualifier}/config/``):

    - ``settings.json`` — merged scope + agent settings with tool allow list.
    - ``mcp.json`` — scoped HTTP MCP endpoint.
    - ``agent.json`` — the persona as a ``--agents`` JSON payload.

    Does NOT write into the launch cwd. The real repo's ``.claude/`` and
    ``.mcp.json`` are never touched.

    Returns a dict with:
        settings_path: absolute path to the composed settings.json
        mcp_path: absolute path to the composed mcp.json (or '')
        agents_file: absolute path to the on-disk agent.json (or '')
        agents_json: the same agents payload as an inline JSON string
    """
    from teaparty.config.config_reader import read_agent_frontmatter

    os.makedirs(config_dir, exist_ok=True)

    # Settings: scope base + agent override (same merge as worktree path).
    settings = _merge_settings(agent_name, scope, teaparty_home)
    try:
        agent_def_path = resolve_agent_definition(agent_name, scope, teaparty_home)
        fm = read_agent_frontmatter(agent_def_path)
    except FileNotFoundError:
        agent_def_path = ''
        fm = {}

    tools_str = fm.get('tools', '')
    if tools_str:
        all_tools_list = [t.strip() for t in tools_str.split(',') if t.strip()]
        perms = settings.get('permissions') or {}
        perms['allow'] = all_tools_list
        settings['permissions'] = perms

    settings_path = os.path.join(config_dir, 'settings.json')
    with open(settings_path, 'w') as f:
        json.dump(settings, f, indent=2)

    # MCP endpoint — scoped to this agent/session so tools can route.
    mcp_path = ''
    if mcp_port:
        if session_id:
            mcp_url = f'http://localhost:{mcp_port}/mcp/{scope}/{agent_name}/{session_id}'
        else:
            mcp_url = f'http://localhost:{mcp_port}/mcp/{scope}/{agent_name}'
        mcp_data = {
            'mcpServers': {
                'teaparty-config': {
                    'type': 'http',
                    'url': mcp_url,
                },
            },
        }
        mcp_path = os.path.join(config_dir, 'mcp.json')
        with open(mcp_path, 'w') as f:
            json.dump(mcp_data, f, indent=2)

    # Agent definition. Pulls the agent.md body as the system prompt so
    # Claude Code loads the persona without needing a .claude/agents/
    # file in the cwd. Written to disk as agent.json AND returned as an
    # inline JSON string so the caller can choose --agents-file or
    # --agents (both are wired through ClaudeRunner).
    agents_json = ''
    agents_file = ''
    if agent_def_path:
        try:
            with open(agent_def_path) as f:
                raw = f.read()
        except OSError:
            raw = ''
        body = raw
        if raw.startswith('---'):
            parts = raw.split('---', 2)
            if len(parts) == 3:
                body = parts[2].lstrip('\n')
        entry: dict[str, Any] = {
            'description': fm.get('description', '') or agent_name,
            'prompt': body,
        }
        model = fm.get('model')
        if model:
            entry['model'] = model
        max_turns = fm.get('maxTurns')
        if max_turns:
            entry['maxTurns'] = max_turns
        disallowed = fm.get('disallowedTools')
        if disallowed:
            entry['disallowedTools'] = disallowed
        payload = {agent_name: entry}
        agents_json = json.dumps(payload)
        agents_file = os.path.join(config_dir, 'agent.json')
        with open(agents_file, 'w') as f:
            json.dump(payload, f, indent=2)

    return {
        'settings_path': settings_path,
        'mcp_path': mcp_path,
        'agents_json': agents_json,
        'agents_file': agents_file,
    }


def _merge_settings(
    agent_name: str,
    scope: str,
    teaparty_home: str,
) -> dict:
    """Merge scope-level settings with agent-level settings (agent wins)."""
    base_path = os.path.join(teaparty_home, scope, 'settings.yaml')
    base = _load_yaml(base_path) or {}

    agent_settings_path = os.path.join(
        teaparty_home, scope, 'agents', agent_name, 'settings.yaml',
    )
    override = _load_yaml(agent_settings_path) or {}
    if override:
        base = _deep_merge(base, override)
    return base


def _load_yaml(path: str) -> dict | None:
    if not os.path.isfile(path):
        return None
    with open(path) as f:
        return yaml.safe_load(f) or None


def _deep_merge(base: dict, override: dict) -> dict:
    result = dict(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result




# ── Session lifecycle ────────────────────────────────────────────────────────

MAX_CONVERSATIONS_PER_AGENT = 3


def create_session(
    *,
    agent_name: str,
    scope: str,
    teaparty_home: str,
    session_id: str = '',
) -> Session:
    """Create a new session under {scope}/sessions/{session-id}/.

    Writes metadata.json with the agent name and empty conversation map.
    If session_id is provided, uses it (for stable session keying);
    otherwise generates a random ID.
    """
    if not session_id:
        session_id = uuid.uuid4().hex[:12]
    sessions_dir = os.path.join(teaparty_home, scope, 'sessions')
    session_path = os.path.join(sessions_dir, session_id)
    os.makedirs(session_path, exist_ok=True)

    session = Session(
        id=session_id,
        path=session_path,
        agent_name=agent_name,
        scope=scope,
    )
    _save_session_metadata(session)
    return session


def load_session(
    *,
    agent_name: str,
    scope: str,
    teaparty_home: str,
    session_id: str,
) -> Session | None:
    """Load an existing session from {scope}/sessions/{session-id}/.

    Returns None if the session directory or metadata.json doesn't exist.
    """
    sessions_dir = os.path.join(teaparty_home, scope, 'sessions')
    session_path = os.path.join(sessions_dir, session_id)
    meta_path = os.path.join(session_path, 'metadata.json')
    if not os.path.isfile(meta_path):
        return None
    try:
        with open(meta_path) as f:
            meta = json.load(f)
        return Session(
            id=session_id,
            path=session_path,
            agent_name=meta.get('agent_name', agent_name),
            scope=meta.get('scope', scope),
            claude_session_id=meta.get('claude_session_id', ''),
            conversation_map=meta.get('conversation_map', {}),
            launch_cwd=meta.get('launch_cwd', ''),
            worktree_path=meta.get('worktree_path', ''),
            worktree_branch=meta.get('worktree_branch', ''),
            merge_target_repo=meta.get('merge_target_repo', ''),
            merge_target_branch=meta.get('merge_target_branch', ''),
            merge_target_worktree=meta.get('merge_target_worktree', ''),
            phase=meta.get('phase', 'launching'),
            response_text=meta.get('response_text', ''),
            project_slug=meta.get('project_slug', ''),
            parent_session_id=meta.get('parent_session_id', ''),
            current_message=meta.get('current_message', ''),
            in_flight_gc_ids=list(meta.get('in_flight_gc_ids', [])),
            initial_message=meta.get('initial_message', ''),
        )
    except (json.JSONDecodeError, OSError):
        return None


def _save_session_metadata(session: Session) -> None:
    """Write metadata.json for a session."""
    meta = {
        'session_id': session.id,
        'agent_name': session.agent_name,
        'scope': session.scope,
        'claude_session_id': session.claude_session_id,
        'conversation_map': session.conversation_map,
        'launch_cwd': session.launch_cwd,
        'worktree_path': session.worktree_path,
        'worktree_branch': session.worktree_branch,
        'merge_target_repo': session.merge_target_repo,
        'merge_target_branch': session.merge_target_branch,
        'merge_target_worktree': session.merge_target_worktree,
        'phase': session.phase,
        'response_text': session.response_text,
        'project_slug': session.project_slug,
        'parent_session_id': session.parent_session_id,
        'current_message': session.current_message,
        'in_flight_gc_ids': session.in_flight_gc_ids,
        'initial_message': session.initial_message,
    }
    meta_path = os.path.join(session.path, 'metadata.json')
    tmp = meta_path + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(meta, f, indent=2)
    os.replace(tmp, meta_path)


# ── Phase transitions (pause/resume plumbing, issue #403) ───────────────────

def _update_phase_fields(session: Session, fields: dict[str, Any]) -> None:
    """Read-modify-write only the named phase fields in metadata.json.

    Other fields (claude_session_id, conversation_map, etc.) are preserved
    from disk so a concurrent update from a different codepath is not
    clobbered. Same pattern as _update_conversation_map.
    """
    meta_path = os.path.join(session.path, 'metadata.json')
    try:
        with open(meta_path) as f:
            meta = json.load(f)
    except (json.JSONDecodeError, OSError):
        meta = {}
    meta.update(fields)
    tmp = meta_path + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(meta, f, indent=2)
    os.replace(tmp, meta_path)


def mark_launching(session: Session, current_message: str) -> None:
    """Record that the session is about to enter ``await _launch(...)``.

    The current_message is persisted so a launching-phase resume can
    re-send the same turn input under --resume. Cancellation between
    this call and the next transition lands in the launching await
    with phase='launching' and the correct input already on disk.
    """
    session.phase = 'launching'
    session.current_message = current_message
    _update_phase_fields(
        session,
        {'phase': 'launching', 'current_message': current_message},
    )


def mark_awaiting(session: Session, in_flight_gc_ids: list[str]) -> None:
    """Record that the session is about to enter ``await gather(...)``.

    The grandchild ids being awaited are persisted so the resume walker
    can locate those sessions on disk and rebuild the gather target set.
    """
    session.phase = 'awaiting'
    session.in_flight_gc_ids = list(in_flight_gc_ids)
    _update_phase_fields(
        session,
        {'phase': 'awaiting', 'in_flight_gc_ids': list(in_flight_gc_ids)},
    )


def mark_complete(session: Session, response_text: str) -> None:
    """Record that the subtree loop exited normally with a final reply.

    The stored response_text lets a resumed parent collect this session's
    answer without re-running any LLM work.
    """
    session.phase = 'complete'
    session.response_text = response_text
    _update_phase_fields(
        session, {'phase': 'complete', 'response_text': response_text},
    )


def record_child_session(
    session: Session,
    *,
    request_id: str,
    child_session_id: str,
) -> None:
    """Record a child session in the dispatching agent's conversation map.

    Uses read-modify-write on just the conversation_map field to avoid
    overwriting claude_session_id or other fields that may have been
    updated by a concurrent invoke.
    """
    session.conversation_map[request_id] = child_session_id
    _update_conversation_map(session)


def remove_child_session(session: Session, *, request_id: str) -> None:
    """Remove a child session from the conversation map (free a slot)."""
    session.conversation_map.pop(request_id, None)
    _update_conversation_map(session)


def _update_conversation_map(session: Session) -> None:
    """Read-modify-write only the conversation_map in metadata.json.

    Other fields (claude_session_id, etc.) are preserved from disk,
    not from the in-memory Session object which may be stale.
    """
    meta_path = os.path.join(session.path, 'metadata.json')
    try:
        with open(meta_path) as f:
            meta = json.load(f)
    except (json.JSONDecodeError, OSError):
        meta = {}
    meta['conversation_map'] = session.conversation_map
    tmp = meta_path + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(meta, f, indent=2)
    os.replace(tmp, meta_path)


def check_slot_available(session: Session) -> bool:
    """Check whether the agent has a free conversation slot."""
    return len(session.conversation_map) < MAX_CONVERSATIONS_PER_AGENT


# ── Session health ───────────────────────────────────────────────────────────

def detect_poisoned_session(events: list[dict]) -> bool:
    """Detect a poisoned session from stream events.

    A session is poisoned when the MCP server fails to start —
    --resume on that session silently fails forever.
    """
    for ev in events:
        if ev.get('type') != 'system':
            continue
        for srv in ev.get('mcp_servers', []):
            if srv.get('status') == 'failed':
                return True
    return False


def should_clear_session(*, response_text: str, session_id: str) -> bool:
    """Determine whether the session ID should be cleared.

    An empty response means the session is dead — clear it so the next
    invocation starts fresh.
    """
    return not response_text and bool(session_id)


# ── LLM caller type and default implementation ──────────────────────────────

# An llm_caller is an async function that takes the launch parameters and
# returns a ClaudeResult. launch() delegates to it after composing the
# worktree and resolving settings. The default wraps ClaudeRunner.
#
# Tests can pass a scripted caller (see teaparty.runners.scripted) to
# exercise the dispatch machinery without real claude subprocesses.
LLMCaller = Callable[..., Any]  # async (**kwargs) -> ClaudeResult


async def _default_claude_caller(**kwargs) -> ClaudeResult:
    """Default llm_caller: runs ClaudeRunner on the given parameters."""
    from teaparty.runners.claude import ClaudeRunner
    # agent_name is informational for scripted callers; ClaudeRunner
    # doesn't take it — the message parameter carries the prompt.
    kwargs.pop('agent_name', None)
    message = kwargs.pop('message')
    runner = ClaudeRunner(message, **kwargs)
    return await runner.run()


async def _default_ollama_caller(**kwargs) -> ClaudeResult:
    """llm_caller: runs OllamaRunner on the given parameters."""
    from teaparty.runners.ollama import OllamaRunner
    _sanitize_caller_kwargs(kwargs)
    kwargs.pop('agent_name', None)
    message = kwargs.pop('message')
    runner = OllamaRunner(message, **kwargs)
    return await runner.run()


def _sanitize_caller_kwargs(kwargs: dict) -> dict:
    """Strip chat-tier-only kwargs that scripted/legacy callers don't accept.

    The unified launcher passes settings_path/mcp_config_path/strict_mcp_config
    so the real ClaudeRunner can wire up per-launch config, but scripted
    test callers and older adapters don't accept them — drop them here.
    """
    for k in ('settings_path', 'mcp_config_path', 'strict_mcp_config'):
        kwargs.pop(k, None)
    return kwargs


# ── The launcher ─────────────────────────────────────────────────────────────

async def launch(
    *,
    agent_name: str,
    message: str,
    scope: str,
    teaparty_home: str,
    org_home: str | None = None,
    worktree: str = '',
    tier: str = 'job',
    launch_cwd: str = '',
    config_dir: str = '',
    resume_session: str = '',
    mcp_port: int = 0,
    on_stream_event: Callable[[dict], None] | None = None,
    event_bus: Any = None,
    session_id: str = '',
    telemetry_scope: str = '',
    heartbeat_file: str = '',
    parent_heartbeat: str = '',
    children_file: str = '',
    stall_timeout: int = 1800,
    # Optional overrides — callers that derive config from other sources
    # (e.g. CfA PhaseConfig) can bypass the standard .teaparty/ derivation.
    settings_override: dict[str, Any] | None = None,
    add_dirs: list[str] | None = None,
    agents_json: str | None = None,
    agents_file: str | None = None,
    stream_file: str = '',
    env_vars: dict[str, str] | None = None,
    permission_mode_override: str = '',
    tools_override: str | None = None,
    # LLM backend — default is real claude, tests inject scripted caller.
    llm_caller: LLMCaller = _default_claude_caller,
) -> ClaudeResult:
    """Launch an agent through the unified codepath.

    1. Composes the worktree .claude/ from .teaparty/ config
    2. Reads agent frontmatter for tools and permissions
    3. Builds a sanitized environment
    4. Runs the subprocess via ClaudeRunner, streams events, returns result

    This is the only function that spawns agent subprocesses.

    The *_override parameters allow callers to layer additional settings
    (e.g. CfA jail hooks) on top of the config-derived baseline.
    """
    from teaparty.config.config_reader import read_agent_frontmatter
    from teaparty.runners.claude import ClaudeRunner

    # Two launch tiers:
    #   job:  CfA jobs — compose a worktree, run subprocess inside it.
    #   chat: management chat — run at the real repo, config via CLI flags.
    is_chat = (tier == 'chat')
    chat_settings_path = ''
    chat_mcp_path = ''
    chat_agents_json = ''
    chat_agents_file = ''
    if is_chat:
        if not launch_cwd:
            raise ValueError('launch(tier="chat") requires launch_cwd')
        if not config_dir:
            raise ValueError('launch(tier="chat") requires config_dir')
        os.makedirs(config_dir, exist_ok=True)
        cfg = compose_launch_config(
            config_dir=config_dir,
            agent_name=agent_name,
            scope=scope,
            teaparty_home=teaparty_home,
            mcp_port=mcp_port,
            session_id=session_id,
        )
        chat_settings_path = cfg['settings_path']
        chat_mcp_path = cfg['mcp_path']
        chat_agents_json = cfg['agents_json']
        chat_agents_file = cfg.get('agents_file', '')
    else:
        compose_launch_worktree(
            worktree=worktree,
            agent_name=agent_name,
            scope=scope,
            teaparty_home=teaparty_home,
            org_home=org_home,
            mcp_port=mcp_port,
            session_id=session_id,
        )

    # Read agent frontmatter for tools and permission mode
    try:
        agent_def_path = resolve_agent_definition(
            agent_name, scope, teaparty_home, org_home=org_home,
        )
        fm = read_agent_frontmatter(agent_def_path)
    except FileNotFoundError:
        fm = {}

    # Derive tools from frontmatter (unless overridden)
    tools = tools_override
    if tools is None:
        tools_str = fm.get('tools', '')
        if tools_str:
            all_tools = [t.strip() for t in tools_str.split(',') if t.strip()]
            if 'ToolSearch' not in all_tools:
                all_tools.append('ToolSearch')
            tools = ','.join(all_tools)

    # Permission mode
    permission_mode = permission_mode_override or fm.get('permissionMode', 'default') or 'default'

    # Settings
    if settings_override is not None:
        settings = dict(settings_override)
    else:
        settings = _merge_settings(agent_name, scope, teaparty_home)
        tools_str = fm.get('tools', '')
        if tools_str:
            all_tools_list = [t.strip() for t in tools_str.split(',') if t.strip()]
            perms = settings.get('permissions', {})
            perms['allow'] = all_tools_list
            settings['permissions'] = perms

    if is_chat:
        effective_cwd = launch_cwd
        effective_stream = stream_file or os.path.join(config_dir, 'stream.jsonl')
        # Prefer inline --agents JSON composed into the config dir over
        # whatever the caller passed; chat tier owns the agent definition.
        effective_agents_json = agents_json or chat_agents_json
        effective_settings_path = chat_settings_path
        effective_mcp_path = chat_mcp_path
        strict_mcp = True
    else:
        effective_cwd = worktree
        effective_stream = stream_file or os.path.join(worktree, '.stream.jsonl')
        effective_agents_json = agents_json
        effective_settings_path = ''
        effective_mcp_path = ''
        strict_mcp = False

    # Point telemetry at this teaparty_home (idempotent) and emit
    # turn_start before the subprocess runs.
    try:
        from teaparty.telemetry import set_teaparty_home
        set_teaparty_home(teaparty_home)
    except Exception:
        pass

    _tscope = telemetry_scope or scope
    record_event(
        _telem_events.TURN_START,
        scope=_tscope,
        agent_name=agent_name,
        session_id=session_id,
        data={
            'trigger': 'dispatch' if resume_session else 'new',
            'claude_session': resume_session or '',
            'model': '',
            'resume_from_phase': None,
        },
    )
    _turn_start_wall = time.time()

    # Delegate to the llm_caller. Default is _default_claude_caller
    # which wraps ClaudeRunner. Tests inject a scripted caller.
    result = await llm_caller(
        agent_name=agent_name,
        message=message,
        cwd=effective_cwd,
        stream_file=effective_stream,
        lead=agent_name,
        settings=settings,
        settings_path=effective_settings_path,
        mcp_config_path=effective_mcp_path,
        strict_mcp_config=strict_mcp,
        permission_mode=permission_mode,
        tools=tools,
        add_dirs=add_dirs or [],
        resume_session=resume_session or None,
        on_stream_event=on_stream_event,
        event_bus=event_bus,
        session_id=session_id,
        heartbeat_file=heartbeat_file,
        parent_heartbeat=parent_heartbeat,
        children_file=children_file,
        stall_timeout=stall_timeout,
        agents_json=effective_agents_json,
        agents_file=agents_file,
        env_vars=env_vars or {},
    )

    # Emit turn_complete with per-turn cost, tokens, and duration.
    record_event(
        _telem_events.TURN_COMPLETE,
        scope=_tscope,
        agent_name=agent_name,
        session_id=session_id or result.session_id,
        data={
            'duration_ms':          result.duration_ms,
            'exit_code':            result.exit_code,
            'cost_usd':             result.cost_usd,
            'input_tokens':         result.input_tokens,
            'output_tokens':        result.output_tokens,
            'cache_read_tokens':    getattr(result, 'cache_read_tokens', 0),
            'cache_create_tokens':  getattr(result, 'cache_create_tokens', 0),
            'response_text_len':    len(getattr(result, 'response_text', '') or ''),
            'tools_called':         getattr(result, 'tools_called', {}) or {},
            'wall_duration_ms':     int((time.time() - _turn_start_wall) * 1000),
        },
    )

    return result
