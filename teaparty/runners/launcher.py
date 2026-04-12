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
    """An agent session — 1:1 with a worktree and a Claude session ID."""
    id: str
    path: str
    agent_name: str
    scope: str
    claude_session_id: str = ''
    conversation_map: dict[str, str] = field(default_factory=dict)


# ── Agent definition resolution ──────────────────────────────────────────────

def resolve_agent_definition(
    agent_name: str,
    scope: str,
    teaparty_home: str,
) -> str:
    """Resolve the agent definition path: scope-first, fall back to management.

    Returns the absolute path to the agent.md file.

    Raises:
        FileNotFoundError: If no agent definition exists in either scope.
    """
    # Scope-specific path
    scope_path = os.path.join(
        teaparty_home, scope, 'agents', agent_name, 'agent.md',
    )
    if os.path.isfile(scope_path):
        return scope_path

    # Fall back to management (unless already looking there)
    if scope != 'management':
        mgmt_path = os.path.join(
            teaparty_home, 'management', 'agents', agent_name, 'agent.md',
        )
        if os.path.isfile(mgmt_path):
            return mgmt_path

    raise FileNotFoundError(
        f'No agent definition for {agent_name!r} in scope {scope!r} '
        f'or management at {teaparty_home}'
    )


# ── Worktree composition ────────────────────────────────────────────────────

def compose_launch_worktree(
    *,
    worktree: str,
    agent_name: str,
    scope: str,
    teaparty_home: str,
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
    """
    from teaparty.config.config_reader import read_agent_frontmatter

    try:
        agent_def_path = resolve_agent_definition(agent_name, scope, teaparty_home)
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
        # Look in scope first, then management
        for skill_name in allowed_skills:
            skill_src = os.path.join(
                teaparty_home, scope, 'skills', skill_name,
            )
            if not os.path.isdir(skill_src) and scope != 'management':
                skill_src = os.path.join(
                    teaparty_home, 'management', 'skills', skill_name,
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
    }
    meta_path = os.path.join(session.path, 'metadata.json')
    tmp = meta_path + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(meta, f, indent=2)
    os.replace(tmp, meta_path)


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


# ── The launcher ─────────────────────────────────────────────────────────────

async def launch(
    *,
    agent_name: str,
    message: str,
    scope: str,
    teaparty_home: str,
    worktree: str,
    resume_session: str = '',
    mcp_port: int = 0,
    on_stream_event: Callable[[dict], None] | None = None,
    event_bus: Any = None,
    session_id: str = '',
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

    # Compose worktree from .teaparty/ config
    compose_launch_worktree(
            worktree=worktree,
            agent_name=agent_name,
            scope=scope,
            teaparty_home=teaparty_home,
            mcp_port=mcp_port,
            session_id=session_id,
        )

    # Read agent frontmatter for tools and permission mode
    try:
        agent_def_path = resolve_agent_definition(agent_name, scope, teaparty_home)
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

    effective_stream = stream_file or os.path.join(worktree, '.stream.jsonl')

    # Point telemetry at this teaparty_home (idempotent) and emit
    # turn_start before the subprocess runs.
    try:
        from teaparty.telemetry import set_teaparty_home
        set_teaparty_home(teaparty_home)
    except Exception:
        pass

    record_event(
        _telem_events.TURN_START,
        scope=scope,
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
        cwd=worktree,
        stream_file=effective_stream,
        lead=agent_name,
        settings=settings,
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
        agents_json=agents_json,
        agents_file=agents_file,
        env_vars=env_vars or {},
    )

    # Emit turn_complete — replaces the old per-scope metrics.db write.
    record_event(
        _telem_events.TURN_COMPLETE,
        scope=scope,
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
