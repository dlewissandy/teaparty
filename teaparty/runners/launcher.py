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

    agent_def_path = resolve_agent_definition(agent_name, scope, teaparty_home)
    fm = read_agent_frontmatter(agent_def_path)

    claude_dir = os.path.join(worktree, '.claude')
    os.makedirs(claude_dir, exist_ok=True)

    # ── Agent definition ─────────────────────────────────────────────────
    agents_dir = os.path.join(claude_dir, 'agents')
    os.makedirs(agents_dir, exist_ok=True)
    # Clean old agent definitions
    for entry in os.scandir(agents_dir):
        if entry.is_symlink() or entry.name.endswith('.md'):
            os.unlink(entry.path)
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


# ── Command composition ──────────────────────────────────────────────────────

def build_launch_command(
    *,
    agent_name: str,
    scope: str,
    teaparty_home: str,
    resume_session: str = '',
    mcp_port: int = 0,
) -> list[str]:
    """Build the ``claude -p`` command for an agent launch.

    Always includes: --agent, --output-format stream-json, --verbose,
    --setting-sources user, --settings.
    Conditionally: --resume, --mcp-config.

    Returns the command as a list of strings suitable for subprocess.
    """
    settings = _merge_settings(agent_name, scope, teaparty_home)

    # Write settings to a temp file so --settings can reference it
    settings_file = tempfile.NamedTemporaryFile(
        mode='w', suffix='.json', prefix='launch-settings-', delete=False,
    )
    json.dump(settings, settings_file)
    settings_file.close()

    cmd = [
        'claude', '-p',
        '--agent', agent_name,
        '--output-format', 'stream-json',
        '--verbose',
        '--setting-sources', 'user',
        '--settings', settings_file.name,
    ]

    if resume_session:
        cmd.extend(['--resume', resume_session])

    if mcp_port:
        mcp_url = f'http://localhost:{mcp_port}/mcp/{scope}/{agent_name}'
        mcp_data = {
            'mcpServers': {
                'teaparty-config': {
                    'type': 'http',
                    'url': mcp_url,
                },
            },
        }
        mcp_file = tempfile.NamedTemporaryFile(
            mode='w', suffix='.json', prefix='launch-mcp-', delete=False,
        )
        json.dump(mcp_data, mcp_file)
        mcp_file.close()
        cmd.extend(['--mcp-config', mcp_file.name, '--strict-mcp-config'])

    return cmd


# ── Environment ──────────────────────────────────────────────────────────────

_ENV_ALLOWLIST = frozenset({
    'PATH', 'HOME', 'TMPDIR', 'SHELL', 'USER', 'LOGNAME',
    'LANG', 'TERM',
    'ANTHROPIC_API_KEY',
    'VIRTUAL_ENV', 'PYENV_ROOT',
})

_ENV_PREFIX_ALLOWLIST = ('CLAUDE_', 'POC_', 'LC_')


def build_launch_env(extra_vars: dict[str, str] | None = None) -> dict[str, str]:
    """Build a sanitized environment for agent subprocesses.

    Strips to allowlist so agents don't inherit orchestrator credentials.
    """
    env: dict[str, str] = {}
    for key, value in os.environ.items():
        if key in _ENV_ALLOWLIST:
            env[key] = value
        elif key.startswith(_ENV_PREFIX_ALLOWLIST):
            env[key] = value
    env['CLAUDE_CODE_MAX_OUTPUT_TOKENS'] = '128000'
    env.pop('CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS', None)
    if extra_vars:
        env.update(extra_vars)
    return env


# ── Session lifecycle ────────────────────────────────────────────────────────

MAX_CONVERSATIONS_PER_AGENT = 3


def create_session(
    *,
    agent_name: str,
    scope: str,
    teaparty_home: str,
) -> Session:
    """Create a new session under {scope}/sessions/{session-id}/.

    Writes metadata.json with the agent name and empty conversation map.
    """
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
    """Record a child session in the dispatching agent's conversation map."""
    session.conversation_map[request_id] = child_session_id
    _save_session_metadata(session)


def remove_child_session(session: Session, *, request_id: str) -> None:
    """Remove a child session from the conversation map (free a slot)."""
    session.conversation_map.pop(request_id, None)
    _save_session_metadata(session)


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
) -> ClaudeResult:
    """Launch an agent through the unified codepath.

    1. Composes the worktree .claude/ from .teaparty/ config
    2. Builds the claude -p command
    3. Builds a sanitized environment
    4. Runs the subprocess, streams events, returns result

    This is the only function that spawns agent subprocesses.
    """
    from teaparty.config.config_reader import read_agent_frontmatter
    from teaparty.runners.claude import ClaudeRunner

    # Compose worktree
    compose_launch_worktree(
        worktree=worktree,
        agent_name=agent_name,
        scope=scope,
        teaparty_home=teaparty_home,
        mcp_port=mcp_port,
    )

    # Read agent frontmatter for tools and permission mode
    agent_def_path = resolve_agent_definition(agent_name, scope, teaparty_home)
    fm = read_agent_frontmatter(agent_def_path)

    # Derive tools from frontmatter
    tools = None
    tools_str = fm.get('tools', '')
    if tools_str:
        all_tools = {t.strip() for t in tools_str.split(',') if t.strip()}
        mcp_prefix = 'mcp__'
        builtins = [t for t in all_tools if not t.startswith(mcp_prefix)]
        if 'ToolSearch' not in builtins:
            builtins.append('ToolSearch')
        tools = ','.join(builtins)

    # Permission mode from frontmatter
    permission_mode = fm.get('permissionMode', 'default') or 'default'

    # Settings
    settings = _merge_settings(agent_name, scope, teaparty_home)
    if tools_str:
        all_tools_list = [t.strip() for t in tools_str.split(',') if t.strip()]
        perms = settings.get('permissions', {})
        perms['allow'] = all_tools_list
        settings['permissions'] = perms

    # MCP config
    mcp_config = None  # Handled by compose_launch_worktree via .mcp.json in worktree

    # Build the runner — delegate to ClaudeRunner for streaming, watchdog, etc.
    runner = ClaudeRunner(
        message,
        cwd=worktree,
        stream_file=os.path.join(worktree, '.stream.jsonl'),
        lead=agent_name,
        settings=settings,
        permission_mode=permission_mode,
        tools=tools,
        resume_session=resume_session or None,
        on_stream_event=on_stream_event,
        event_bus=event_bus,
        session_id=session_id,
        heartbeat_file=heartbeat_file,
        parent_heartbeat=parent_heartbeat,
        children_file=children_file,
        stall_timeout=stall_timeout,
    )

    return await runner.run()
