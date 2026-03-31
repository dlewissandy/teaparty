"""MCP server for agent escalation, dispatch, intervention, and config tools.

The agent calls AskQuestion(question, context).  The handler routes
through the proxy: confident → return proxy answer; not confident →
escalate to human, record the differential, return human's answer.

The agent calls Send(member, message) to initiate a conversation with a
roster member.  Before posting, the handler reads the caller's scratch
file ({worktree}/.context/scratch.md) and wraps the message in a composite
envelope (## Task / ## Context) so the recipient has full job context.
SEND_SOCKET is the transport env var.

The agent calls Reply(message) to respond in the current thread and close
it.  No context injection — the context is already established.
REPLY_SOCKET is the transport env var.

The agent calls AskTeam(team, task) to dispatch work to a specialist
subteam.  The handler sends the request to the DispatchListener via
a Unix domain socket (ASK_TEAM_SOCKET env var) and returns the result.

The office manager calls WithdrawSession, PauseDispatch, ResumeDispatch,
or ReprioritizeDispatch to exercise team-lead authority.  These route
through the InterventionListener via INTERVENTION_SOCKET.

Config tools (CreateAgent, CreateSkill, CreateHook, etc.) operate directly
on the filesystem.  They validate required fields and return a structured
JSON result dict (success, error/message).  Each handler function is
synchronous and testable in isolation.  The MCP tool wrapper calls the
handler and JSON-encodes the result.

All config tools accept an optional project_root / teaparty_home argument.
When omitted, project_root defaults to os.getcwd() and teaparty_home
defaults to os.path.join(os.getcwd(), '.teaparty').

The MCP server communicates with the orchestrator via Unix domain
sockets whose paths are passed in the ASK_QUESTION_SOCKET,
ASK_TEAM_SOCKET, SEND_SOCKET, REPLY_SOCKET, and INTERVENTION_SOCKET
env vars.  The worktree path for scratch file access is read from
TEAPARTY_WORKTREE (defaults to os.getcwd() when unset).
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
from typing import Any, Awaitable, Callable

import yaml
from mcp.server import FastMCP

# Type aliases for the pluggable functions
ProxyFn = Callable[[str, str], Awaitable[dict[str, Any]]]
HumanFn = Callable[[str], Awaitable[str]]
RecordDifferentialFn = Callable[[str, str, str, str], None]
SendPostFn = Callable[[str, str, str], Awaitable[str]]
ReplyPostFn = Callable[[str], Awaitable[str]]

# Maximum lines of scratch file content to include in the Context section.
# Oldest lines are dropped first when the file exceeds this limit.
CONTEXT_BUDGET_LINES = 200


async def ask_question_handler(
    question: str,
    context: str = '',
    *,
    scratch_path: str = '',
    proxy_fn: ProxyFn | None = None,
    human_fn: HumanFn | None = None,
    record_differential_fn: RecordDifferentialFn | None = None,
) -> str:
    """Core handler logic for AskQuestion.

    Routes through the proxy first.  If the proxy is confident, returns
    its answer directly.  Otherwise escalates to the human, records the
    differential (proxy prediction vs. human actual), and returns the
    human's answer.

    When scratch_path is given, the handler builds a composite envelope
    (## Task / ## Context) identical to Send's envelope before passing
    the question to the proxy.  This ensures the escalation recipient
    has full job context without the calling agent constructing a brief.

    Args:
        question: The question the agent is asking.
        context: Optional extra context (ignored when scratch_path is set).
        scratch_path: Path to the caller's scratch file.  When set, the
            handler reads the file, truncates to CONTEXT_BUDGET_LINES,
            and wraps question in the standard Task/Context envelope.
        proxy_fn: Async function that returns a dict with keys:
            confident (bool), answer (str), prediction (str).
        human_fn: Async function that takes a question and returns the
            human's answer.  Only called when proxy is not confident.
        record_differential_fn: Sync function to record the differential
            between proxy prediction and human actual.
    """
    if not question or not question.strip():
        raise ValueError('AskQuestion requires a non-empty question')

    # Build composite envelope when a scratch file is available.
    if scratch_path:
        question = _build_composite(question, _read_scratch(scratch_path))
        context = ''

    # Route through proxy
    if proxy_fn is None:
        proxy_fn = _default_proxy
    proxy_result = await proxy_fn(question, context)

    confident = proxy_result.get('confident', False)
    prediction = proxy_result.get('prediction', '')
    answer = proxy_result.get('answer', '')

    if confident and answer:
        return answer

    # Not confident — escalate to human
    if human_fn is None:
        human_fn = _default_human
    human_answer = await human_fn(question)

    # Record the differential: proxy prediction vs. human actual
    if record_differential_fn is not None and prediction:
        record_differential_fn(prediction, human_answer, question, context)

    return human_answer


async def _default_proxy(question: str, context: str) -> dict[str, Any]:
    """Default proxy: always escalate (cold start)."""
    return {'confident': False, 'answer': '', 'prediction': ''}


async def _default_human(question: str) -> str:
    """Default human input: communicate via the orchestrator socket.

    In production, this is always called because _default_proxy returns
    confident=False.  The actual proxy routing happens in the
    EscalationListener on the orchestrator side of the socket.
    """
    socket_path = os.environ.get('ASK_QUESTION_SOCKET', '')
    if not socket_path:
        raise RuntimeError(
            'ASK_QUESTION_SOCKET not set — cannot escalate to human'
        )
    reader, writer = await asyncio.open_unix_connection(socket_path)
    try:
        request = json.dumps({'type': 'ask_human', 'question': question})
        writer.write(request.encode() + b'\n')
        await writer.drain()
        response_line = await reader.readline()
        response = json.loads(response_line.decode())
        return response.get('answer', '')
    finally:
        writer.close()
        await writer.wait_closed()


# ── Scratch file helpers ─────────────────────────────────────────────��────────

def _read_scratch(scratch_path: str) -> str:
    """Read the scratch file and return its contents, truncated to CONTEXT_BUDGET_LINES.

    When the file has more than CONTEXT_BUDGET_LINES lines, the oldest
    (first) lines are dropped so the newest state is preserved.
    Returns an empty string when the file does not exist.
    """
    try:
        with open(scratch_path) as f:
            lines = f.readlines()
    except FileNotFoundError:
        return ''
    if len(lines) > CONTEXT_BUDGET_LINES:
        lines = lines[-CONTEXT_BUDGET_LINES:]
    return ''.join(lines)


def _build_composite(message: str, scratch: str) -> str:
    """Build the Task/Context composite envelope.

    The composite structure per the agent-dispatch invocation model:

        ## Task
        [message]

        ## Context
        [scratch file contents]
    """
    return f'## Task\n{message}\n\n## Context\n{scratch}'


def _scratch_path_from_env() -> str:
    """Resolve the scratch file path from TEAPARTY_WORKTREE env var."""
    worktree = os.environ.get('TEAPARTY_WORKTREE', os.getcwd())
    return os.path.join(worktree, '.context', 'scratch.md')


# ── Send / Reply handlers ────────────────────────────────���────────────────────

async def send_handler(
    member: str,
    message: str,
    context_id: str = '',
    *,
    scratch_path: str = '',
    post_fn: SendPostFn | None = None,
) -> str:
    """Core handler logic for Send.

    Reads the caller's scratch file, builds the composite Task/Context
    envelope, and posts it to the named roster member.

    The scratch file is read from scratch_path when given; otherwise
    from {TEAPARTY_WORKTREE}/.context/scratch.md.  A missing scratch
    file yields an empty Context section — the Task section is always
    present.

    Args:
        member: Name of the roster member to send to.
        message: The agent's message (becomes the Task section).
        context_id: Optional existing context ID for continuing a thread.
        scratch_path: Override path to the scratch file (for testing).
        post_fn: Async function that posts (member, composite, context_id)
            and returns a result string.  Defaults to the SEND_SOCKET
            transport.
    """
    if not member or not member.strip():
        raise ValueError('Send requires a non-empty member')
    if not message or not message.strip():
        raise ValueError('Send requires a non-empty message')

    resolved = scratch_path or _scratch_path_from_env()
    scratch = _read_scratch(resolved)
    composite = _build_composite(message, scratch)

    if post_fn is None:
        post_fn = _default_send_post
    return await post_fn(member, composite, context_id)


async def _default_send_post(member: str, composite: str, context_id: str) -> str:
    """Default Send transport: post via SEND_SOCKET Unix domain socket."""
    socket_path = os.environ.get('SEND_SOCKET', '')
    if not socket_path:
        raise RuntimeError('SEND_SOCKET not set — cannot send to member')
    reader, writer = await asyncio.open_unix_connection(socket_path)
    try:
        request = json.dumps({
            'type': 'send', 'member': member,
            'composite': composite, 'context_id': context_id,
        })
        writer.write(request.encode() + b'\n')
        await writer.drain()
        response_line = await reader.readline()
        response = json.loads(response_line.decode())
        return json.dumps(response)
    finally:
        writer.close()
        await writer.wait_closed()


async def reply_handler(
    message: str,
    *,
    post_fn: ReplyPostFn | None = None,
) -> str:
    """Core handler logic for Reply.

    Posts the message unchanged to close the current conversation thread.
    No context injection — the context is already established in the thread.

    Args:
        message: The reply message.
        post_fn: Async function that posts the message and returns a result
            string.  Defaults to the REPLY_SOCKET transport.
    """
    if not message or not message.strip():
        raise ValueError('Reply requires a non-empty message')

    if post_fn is None:
        post_fn = _default_reply_post
    return await post_fn(message)


async def _default_reply_post(message: str) -> str:
    """Default Reply transport: post via REPLY_SOCKET Unix domain socket."""
    socket_path = os.environ.get('REPLY_SOCKET', '')
    if not socket_path:
        raise RuntimeError('REPLY_SOCKET not set — cannot reply')
    reader, writer = await asyncio.open_unix_connection(socket_path)
    try:
        request = json.dumps({'type': 'reply', 'message': message})
        writer.write(request.encode() + b'\n')
        await writer.drain()
        response_line = await reader.readline()
        response = json.loads(response_line.decode())
        return json.dumps(response)
    finally:
        writer.close()
        await writer.wait_closed()


async def intervention_handler(request_type: str, **kwargs) -> str:
    """Core handler for intervention tools (WithdrawSession, PauseDispatch, etc.).

    Sends the request to the InterventionListener via the Unix socket
    at INTERVENTION_SOCKET and returns the result JSON as a string.

    Args:
        request_type: One of withdraw_session, pause_dispatch,
            resume_dispatch, reprioritize_dispatch.
        **kwargs: Additional fields for the request (session_id,
            dispatch_id, priority).
    """
    socket_path = os.environ.get('INTERVENTION_SOCKET', '')
    if not socket_path:
        raise RuntimeError(
            'INTERVENTION_SOCKET not set — cannot execute intervention'
        )
    reader, writer = await asyncio.open_unix_connection(socket_path)
    try:
        request = json.dumps({'type': request_type, **kwargs})
        writer.write(request.encode() + b'\n')
        await writer.drain()
        response_line = await reader.readline()
        response = json.loads(response_line.decode())
        return json.dumps(response)
    finally:
        writer.close()
        await writer.wait_closed()


async def ask_team_handler(team: str, task: str) -> str:
    """Core handler logic for AskTeam.

    Sends the dispatch request to the DispatchListener via the Unix socket
    at ASK_TEAM_SOCKET and returns the result JSON as a string.

    Args:
        team: The team to dispatch to (art, writing, editorial, research, coding).
        task: The task description for the subteam.
    """
    if not team or not team.strip():
        raise ValueError('AskTeam requires a non-empty team')
    if not task or not task.strip():
        raise ValueError('AskTeam requires a non-empty task')

    socket_path = os.environ.get('ASK_TEAM_SOCKET', '')
    if not socket_path:
        raise RuntimeError(
            'ASK_TEAM_SOCKET not set — cannot dispatch to team'
        )
    reader, writer = await asyncio.open_unix_connection(socket_path)
    try:
        request = json.dumps({'type': 'ask_team', 'team': team, 'task': task})
        writer.write(request.encode() + b'\n')
        await writer.drain()
        response_line = await reader.readline()
        response = json.loads(response_line.decode())
        return json.dumps(response)
    finally:
        writer.close()
        await writer.wait_closed()


# ── Config tool helpers ───────────────────────────────────────────────────────

def _ok(message: str, **extra) -> str:
    return json.dumps({'success': True, 'message': message, **extra})


def _err(error: str) -> str:
    return json.dumps({'success': False, 'error': error})


def _project_root(override: str) -> str:
    return override if override else os.getcwd()


def _teaparty_home(override: str) -> str:
    return override if override else os.path.join(os.getcwd(), '.teaparty')


def _claude_dir(project_root: str) -> str:
    return os.path.join(project_root, '.claude')


def _agents_dir(project_root: str) -> str:
    return os.path.join(_claude_dir(project_root), 'agents')


def _skills_dir(project_root: str) -> str:
    return os.path.join(_claude_dir(project_root), 'skills')


def _settings_json(project_root: str) -> str:
    return os.path.join(_claude_dir(project_root), 'settings.json')


def _workgroups_dir(teaparty_home: str) -> str:
    return os.path.join(teaparty_home, 'workgroups')


def _parse_agent_file(path: str) -> tuple[dict, str]:
    """Parse a .claude/agents/{name}.md file.

    Returns (frontmatter_dict, body_text).
    """
    with open(path) as f:
        content = f.read()
    m = re.match(r'^---\n(.*?\n)---\n(.*)', content, re.DOTALL)
    if not m:
        return {}, content
    return yaml.safe_load(m.group(1)) or {}, m.group(2)


def _write_agent_file(path: str, fm: dict, body: str) -> None:
    """Write a .claude/agents/{name}.md file."""
    # Render frontmatter preserving field order
    fm_str = yaml.dump(fm, default_flow_style=False, sort_keys=False).rstrip()
    content = f'---\n{fm_str}\n---\n{body}'
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        f.write(content)


def _parse_skill_file(path: str) -> tuple[dict, str]:
    """Parse a SKILL.md file.  Returns (frontmatter_dict, body_text)."""
    with open(path) as f:
        content = f.read()
    m = re.match(r'^---\n(.*?\n)---\n(.*)', content, re.DOTALL)
    if not m:
        return {}, content
    return yaml.safe_load(m.group(1)) or {}, m.group(2)


def _write_skill_file(path: str, fm: dict, body: str) -> None:
    """Write a SKILL.md file."""
    fm_str = yaml.dump(fm, default_flow_style=False, sort_keys=False).rstrip()
    content = f'---\n{fm_str}\n---\n{body}'
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        f.write(content)


def _load_settings(project_root: str) -> dict:
    """Load .claude/settings.json, creating it if missing."""
    path = _settings_json(project_root)
    if os.path.exists(path):
        with open(path) as f:
            try:
                return json.load(f)
            except json.JSONDecodeError:
                return {'hooks': {}}
    return {'hooks': {}}


def _save_settings(project_root: str, data: dict) -> None:
    path = _settings_json(project_root)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        json.dump(data, f, indent=2)


def _load_teaparty_yaml(teaparty_home: str) -> dict:
    path = os.path.join(teaparty_home, 'teaparty.yaml')
    if not os.path.exists(path):
        raise FileNotFoundError(f'teaparty.yaml not found: {path}')
    with open(path) as f:
        return yaml.safe_load(f) or {}


def _save_teaparty_yaml(teaparty_home: str, data: dict) -> None:
    path = os.path.join(teaparty_home, 'teaparty.yaml')
    with open(path, 'w') as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)


# ── Project tools ─────────────────────────────────────────────────────────────

def add_project_handler(
    name: str,
    path: str,
    description: str = '',
    lead: str = '',
    decider: str = '',
    agents: list | None = None,
    humans: list | None = None,
    workgroups: list | None = None,
    skills: list | None = None,
    teaparty_home: str = '',
) -> str:
    """Add an existing directory as a TeaParty project.

    Registers it in teaparty.yaml and creates .teaparty.local/project.yaml
    with the provided fields.  Returns JSON result.
    """
    if not name or not name.strip():
        return _err('AddProject requires a non-empty name')
    if not path or not path.strip():
        return _err('AddProject requires a non-empty path')

    home = _teaparty_home(teaparty_home)
    from orchestrator.config_reader import add_project
    try:
        add_project(
            name=name,
            path=path,
            teaparty_home=home,
            description=description,
            lead=lead,
            decider=decider,
            agents=agents,
            humans=humans,
            workgroups=workgroups,
            skills=skills,
        )
    except ValueError as e:
        return _err(str(e))
    return _ok(f"Project '{name}' added at {path}")


def create_project_handler(
    name: str,
    path: str,
    description: str = '',
    lead: str = '',
    decider: str = '',
    agents: list | None = None,
    humans: list | None = None,
    workgroups: list | None = None,
    skills: list | None = None,
    teaparty_home: str = '',
) -> str:
    """Create a new project directory with full scaffolding (git init, .claude/, etc.)."""
    if not name or not name.strip():
        return _err('CreateProject requires a non-empty name')
    if not path or not path.strip():
        return _err('CreateProject requires a non-empty path')

    home = _teaparty_home(teaparty_home)
    from orchestrator.config_reader import create_project
    try:
        create_project(
            name=name,
            path=path,
            teaparty_home=home,
            description=description,
            lead=lead,
            decider=decider,
            agents=agents,
            humans=humans,
            workgroups=workgroups,
            skills=skills,
        )
    except ValueError as e:
        return _err(str(e))
    return _ok(f"Project '{name}' created at {path}")


def remove_project_handler(name: str, teaparty_home: str = '') -> str:
    """Remove a project from teaparty.yaml (directory untouched)."""
    if not name or not name.strip():
        return _err('RemoveProject requires a non-empty name')

    home = _teaparty_home(teaparty_home)
    from orchestrator.config_reader import remove_project
    try:
        remove_project(name=name, teaparty_home=home)
    except ValueError as e:
        return _err(str(e))
    return _ok(f"Project '{name}' removed from registry")


def scaffold_project_yaml_handler(
    project_path: str,
    name: str,
    description: str = '',
    lead: str = '',
    decider: str = '',
    agents: list | None = None,
    humans: list | None = None,
    workgroups: list | None = None,
    skills: list | None = None,
) -> str:
    """Create or overwrite .teaparty.local/project.yaml for an existing project.

    Unlike _scaffold_project_yaml, this always writes (retroactive fix for
    projects with missing or empty fields).
    """
    if not project_path or not project_path.strip():
        return _err('ScaffoldProjectYaml requires a non-empty project_path')
    if not name or not name.strip():
        return _err('ScaffoldProjectYaml requires a non-empty name')

    tp_dir = os.path.join(project_path, '.teaparty.local')
    os.makedirs(tp_dir, exist_ok=True)
    data = {
        'name': name,
        'description': description,
        'lead': lead,
        'decider': decider,
        'agents': agents or [],
        'humans': humans or [],
        'workgroups': workgroups or [],
        'skills': skills or [],
    }
    yaml_path = os.path.join(tp_dir, 'project.yaml')
    with open(yaml_path, 'w') as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)
    return _ok(f'Scaffolded {yaml_path}', path=yaml_path)


# ── Artifact pin tools ────────────────────────────────────────────────────────

def _find_project_path(name: str, teaparty_home: str) -> str | None:
    """Return the project directory for a given project name, or None if not found."""
    data = _load_teaparty_yaml(teaparty_home)
    for team in data.get('teams', []):
        if team.get('name') == name:
            return team.get('path')
    return None


def _load_project_yaml(project_dir: str) -> dict:
    """Load .teaparty.local/project.yaml, returning an empty dict if missing."""
    path = os.path.join(project_dir, '.teaparty.local', 'project.yaml')
    if not os.path.exists(path):
        return {}
    with open(path) as f:
        return yaml.safe_load(f) or {}


def _save_project_yaml(project_dir: str, data: dict) -> None:
    """Write data to .teaparty.local/project.yaml."""
    tp_dir = os.path.join(project_dir, '.teaparty.local')
    os.makedirs(tp_dir, exist_ok=True)
    path = os.path.join(tp_dir, 'project.yaml')
    with open(path, 'w') as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)


def pin_artifact_handler(
    project: str,
    path: str,
    label: str = '',
    teaparty_home: str = '',
) -> str:
    """Add or update an artifact pin in a project's artifact_pins list.

    If a pin with the same path already exists, its label is updated.
    Path is relative to the project root.
    """
    if not project or not project.strip():
        return _err('PinArtifact requires a non-empty project')
    if not path or not path.strip():
        return _err('PinArtifact requires a non-empty path')

    home = _teaparty_home(teaparty_home)
    project_dir = _find_project_path(project, home)
    if project_dir is None:
        return _err(f"Project '{project}' not found in registry")

    data = _load_project_yaml(project_dir)
    pins = data.get('artifact_pins', [])

    # Update existing or append new
    for pin in pins:
        if pin.get('path') == path:
            if label:
                pin['label'] = label
            data['artifact_pins'] = pins
            _save_project_yaml(project_dir, data)
            return _ok(f"Updated pin '{path}' in project '{project}'")

    entry: dict[str, str] = {'path': path}
    if label:
        entry['label'] = label
    pins.append(entry)
    data['artifact_pins'] = pins
    _save_project_yaml(project_dir, data)
    return _ok(f"Pinned '{path}' in project '{project}'")


def unpin_artifact_handler(
    project: str,
    path: str,
    teaparty_home: str = '',
) -> str:
    """Remove an artifact pin from a project's artifact_pins list by path."""
    if not project or not project.strip():
        return _err('UnpinArtifact requires a non-empty project')
    if not path or not path.strip():
        return _err('UnpinArtifact requires a non-empty path')

    home = _teaparty_home(teaparty_home)
    project_dir = _find_project_path(project, home)
    if project_dir is None:
        return _err(f"Project '{project}' not found in registry")

    data = _load_project_yaml(project_dir)
    pins = data.get('artifact_pins', [])
    original_len = len(pins)
    pins = [p for p in pins if p.get('path') != path]

    if len(pins) == original_len:
        return _err(f"Pin '{path}' not found in project '{project}'")

    data['artifact_pins'] = pins
    _save_project_yaml(project_dir, data)
    return _ok(f"Unpinned '{path}' from project '{project}'")


# ── Agent tools ───────────────────────────────────────────────────────────────

def create_agent_handler(
    name: str,
    description: str,
    model: str,
    tools: str,
    body: str,
    skills: str = '',
    max_turns: int = 20,
    project_root: str = '',
) -> str:
    """Create .claude/agents/{name}.md with validated frontmatter."""
    if not name or not name.strip():
        return _err('CreateAgent requires a non-empty name')
    if not description or not description.strip():
        return _err('CreateAgent requires a non-empty description')
    if not model or not model.strip():
        return _err('CreateAgent requires a non-empty model')

    root = _project_root(project_root)
    path = os.path.join(_agents_dir(root), f'{name}.md')

    fm: dict[str, Any] = {
        'name': name,
        'description': description,
        'tools': tools,
        'model': model,
        'maxTurns': max_turns,
    }
    if skills and skills.strip():
        skill_list = [s.strip() for s in skills.split(',') if s.strip()]
        if skill_list:
            fm['skills'] = skill_list

    body_text = body if body.startswith('\n') else f'\n{body}'
    _write_agent_file(path, fm, body_text)
    return _ok(f"Agent '{name}' created at {path}", path=path)


def edit_agent_handler(
    name: str,
    field: str,
    value: str,
    project_root: str = '',
) -> str:
    """Edit a single frontmatter field (or body) in an existing agent definition."""
    if not name or not name.strip():
        return _err('EditAgent requires a non-empty name')

    root = _project_root(project_root)
    path = os.path.join(_agents_dir(root), f'{name}.md')
    if not os.path.exists(path):
        return _err(f"Agent '{name}' not found at {path}")

    fm, body = _parse_agent_file(path)
    if field == 'body':
        body = value if value.startswith('\n') else f'\n{value}'
    elif field == 'maxTurns':
        try:
            fm['maxTurns'] = int(value)
        except ValueError:
            return _err(f'maxTurns must be an integer, got: {value!r}')
    elif field == 'skills':
        fm['skills'] = [s.strip() for s in value.split(',') if s.strip()]
    else:
        fm[field] = value

    _write_agent_file(path, fm, body)
    return _ok(f"Agent '{name}' field '{field}' updated")


def remove_agent_handler(name: str, project_root: str = '') -> str:
    """Delete .claude/agents/{name}.md."""
    if not name or not name.strip():
        return _err('RemoveAgent requires a non-empty name')

    root = _project_root(project_root)
    path = os.path.join(_agents_dir(root), f'{name}.md')
    if not os.path.exists(path):
        return _err(f"Agent '{name}' not found at {path}")

    os.remove(path)
    return _ok(f"Agent '{name}' removed")


# ── Skill tools ───────────────────────────────────────────────────────────────

def create_skill_handler(
    name: str,
    description: str,
    body: str,
    allowed_tools: str = '',
    argument_hint: str = '',
    user_invocable: bool = False,
    project_root: str = '',
) -> str:
    """Create .claude/skills/{name}/SKILL.md with validated frontmatter."""
    if not name or not name.strip():
        return _err('CreateSkill requires a non-empty name')
    if not description or not description.strip():
        return _err('CreateSkill requires a non-empty description')

    root = _project_root(project_root)
    skill_dir = os.path.join(_skills_dir(root), name)
    path = os.path.join(skill_dir, 'SKILL.md')

    fm: dict[str, Any] = {
        'name': name,
        'description': description,
    }
    if argument_hint:
        fm['argument-hint'] = argument_hint
    fm['user-invocable'] = user_invocable
    if allowed_tools:
        fm['allowed-tools'] = allowed_tools

    body_text = body if body.startswith('\n') else f'\n{body}'
    _write_skill_file(path, fm, body_text)
    return _ok(f"Skill '{name}' created at {path}", path=path)


def edit_skill_handler(
    name: str,
    field: str,
    value: str,
    project_root: str = '',
) -> str:
    """Edit a single frontmatter field (or body) in an existing skill's SKILL.md.

    field may be 'body', 'description', 'allowed-tools', 'argument-hint',
    'user-invocable', or any other frontmatter key.
    """
    if not name or not name.strip():
        return _err('EditSkill requires a non-empty name')

    root = _project_root(project_root)
    path = os.path.join(_skills_dir(root), name, 'SKILL.md')
    if not os.path.exists(path):
        return _err(f"Skill '{name}' not found at {path}")

    fm, body = _parse_skill_file(path)
    if field == 'body':
        body = value if value.startswith('\n') else f'\n{value}'
    elif field == 'allowed-tools':
        fm['allowed-tools'] = value
    else:
        fm[field] = value

    _write_skill_file(path, fm, body)
    return _ok(f"Skill '{name}' field '{field}' updated")


def remove_skill_handler(name: str, project_root: str = '') -> str:
    """Remove .claude/skills/{name}/ directory."""
    if not name or not name.strip():
        return _err('RemoveSkill requires a non-empty name')

    root = _project_root(project_root)
    skill_dir = os.path.join(_skills_dir(root), name)
    if not os.path.isdir(skill_dir):
        return _err(f"Skill '{name}' not found at {skill_dir}")

    shutil.rmtree(skill_dir)
    return _ok(f"Skill '{name}' removed")


# ── Workgroup tools ───────────────────────────────────────────────────────────

def create_workgroup_handler(
    name: str,
    description: str = '',
    lead: str = '',
    agents_yaml: str = '',
    skills: str = '',
    norms_yaml: str = '',
    teaparty_home: str = '',
) -> str:
    """Create a workgroup YAML in .teaparty/workgroups/{name}.yaml."""
    if not name or not name.strip():
        return _err('CreateWorkgroup requires a non-empty name')

    home = _teaparty_home(teaparty_home)
    wg_dir = _workgroups_dir(home)
    os.makedirs(wg_dir, exist_ok=True)
    path = os.path.join(wg_dir, f'{name}.yaml')

    agents_list: list = []
    if agents_yaml:
        try:
            agents_list = yaml.safe_load(agents_yaml) or []
        except yaml.YAMLError:
            agents_list = []

    skills_list: list = []
    if skills:
        skills_list = [s.strip() for s in skills.split(',') if s.strip()]

    norms_dict: dict = {}
    if norms_yaml:
        try:
            norms_dict = yaml.safe_load(norms_yaml) or {}
        except yaml.YAMLError:
            norms_dict = {}

    data = {
        'name': name,
        'description': description,
        'lead': lead,
        'agents': agents_list,
        'skills': skills_list,
        'norms': norms_dict,
    }
    with open(path, 'w') as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)
    return _ok(f"Workgroup '{name}' created at {path}", path=path)


def edit_workgroup_handler(
    name: str,
    field: str,
    value: str,
    teaparty_home: str = '',
) -> str:
    """Edit a single field in an existing workgroup YAML."""
    home = _teaparty_home(teaparty_home)
    path = os.path.join(_workgroups_dir(home), f'{name}.yaml')
    if not os.path.exists(path):
        return _err(f"Workgroup '{name}' not found at {path}")

    with open(path) as f:
        data = yaml.safe_load(f) or {}

    # For list/dict fields, try to parse as YAML; fall back to plain string
    if field in ('agents', 'skills', 'norms'):
        try:
            data[field] = yaml.safe_load(value)
        except yaml.YAMLError:
            data[field] = value
    else:
        data[field] = value

    with open(path, 'w') as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)
    return _ok(f"Workgroup '{name}' field '{field}' updated")


def remove_workgroup_handler(name: str, teaparty_home: str = '') -> str:
    """Remove .teaparty/workgroups/{name}.yaml."""
    home = _teaparty_home(teaparty_home)
    path = os.path.join(_workgroups_dir(home), f'{name}.yaml')
    if not os.path.exists(path):
        return _err(f"Workgroup '{name}' not found at {path}")

    os.remove(path)
    return _ok(f"Workgroup '{name}' removed")


# ── Hook tools ────────────────────────────────────────────────────────────────

def create_hook_handler(
    event: str,
    matcher: str,
    handler_type: str,
    command: str,
    project_root: str = '',
) -> str:
    """Add a hook entry to .claude/settings.json."""
    if not event or not event.strip():
        return _err('CreateHook requires a non-empty event')
    if not command or not command.strip():
        return _err('CreateHook requires a non-empty command')

    root = _project_root(project_root)
    data = _load_settings(root)
    hooks = data.setdefault('hooks', {})
    event_hooks = hooks.setdefault(event, [])

    new_entry = {
        'matcher': matcher,
        'hooks': [{'type': handler_type, 'command': command}],
    }
    event_hooks.append(new_entry)
    _save_settings(root, data)
    return _ok(f"Hook added: {event}/{matcher}")


def edit_hook_handler(
    event: str,
    matcher: str,
    field: str,
    value: str,
    project_root: str = '',
) -> str:
    """Edit a field in an existing hook entry."""
    root = _project_root(project_root)
    data = _load_settings(root)
    event_hooks = data.get('hooks', {}).get(event, [])

    for entry in event_hooks:
        if entry.get('matcher') == matcher:
            if field == 'matcher':
                entry['matcher'] = value
            elif field in ('command', 'type'):
                for h in entry.get('hooks', []):
                    h[field] = value
            else:
                entry[field] = value
            _save_settings(root, data)
            return _ok(f"Hook {event}/{matcher} field '{field}' updated")

    return _err(f"Hook not found: {event}/{matcher}")


def remove_hook_handler(event: str, matcher: str, project_root: str = '') -> str:
    """Remove a hook entry from .claude/settings.json."""
    root = _project_root(project_root)
    data = _load_settings(root)
    event_hooks = data.get('hooks', {}).get(event, [])

    original_len = len(event_hooks)
    data['hooks'][event] = [
        e for e in event_hooks if e.get('matcher') != matcher
    ]

    if len(data['hooks'][event]) == original_len:
        return _err(f"Hook not found: {event}/{matcher}")

    _save_settings(root, data)
    return _ok(f"Hook removed: {event}/{matcher}")


# ── Scheduled task tools ──────────────────────────────────────────────────────

def create_scheduled_task_handler(
    name: str,
    schedule: str,
    skill: str,
    args: str = '',
    teaparty_home: str = '',
) -> str:
    """Add a scheduled task entry to teaparty.yaml."""
    if not name or not name.strip():
        return _err('CreateScheduledTask requires a non-empty name')
    if not schedule or not schedule.strip():
        return _err('CreateScheduledTask requires a non-empty schedule')
    if not skill or not skill.strip():
        return _err('CreateScheduledTask requires a non-empty skill')

    home = _teaparty_home(teaparty_home)
    try:
        data = _load_teaparty_yaml(home)
    except FileNotFoundError as e:
        return _err(str(e))

    scheduled = data.setdefault('scheduled', [])
    entry = {'name': name, 'schedule': schedule, 'skill': skill,
             'args': args, 'enabled': True}
    scheduled.append(entry)
    _save_teaparty_yaml(home, data)
    return _ok(f"Scheduled task '{name}' created")


def edit_scheduled_task_handler(
    name: str,
    field: str,
    value: str,
    teaparty_home: str = '',
) -> str:
    """Edit a field in an existing scheduled task entry."""
    home = _teaparty_home(teaparty_home)
    try:
        data = _load_teaparty_yaml(home)
    except FileNotFoundError as e:
        return _err(str(e))

    scheduled = data.get('scheduled', [])
    for entry in scheduled:
        if entry.get('name') == name:
            if field == 'enabled':
                entry[field] = value.lower() in ('true', '1', 'yes')
            else:
                entry[field] = value
            _save_teaparty_yaml(home, data)
            return _ok(f"Scheduled task '{name}' field '{field}' updated")

    return _err(f"Scheduled task '{name}' not found")


def remove_scheduled_task_handler(name: str, teaparty_home: str = '') -> str:
    """Remove a scheduled task entry from teaparty.yaml."""
    home = _teaparty_home(teaparty_home)
    try:
        data = _load_teaparty_yaml(home)
    except FileNotFoundError as e:
        return _err(str(e))

    scheduled = data.get('scheduled', [])
    original_len = len(scheduled)
    data['scheduled'] = [e for e in scheduled if e.get('name') != name]

    if len(data['scheduled']) == original_len:
        return _err(f"Scheduled task '{name}' not found")

    _save_teaparty_yaml(home, data)
    return _ok(f"Scheduled task '{name}' removed")


def create_server() -> FastMCP:
    """Create the MCP server with escalation, dispatch, intervention, and config tools."""
    server = FastMCP('teaparty-escalation')

    @server.tool()
    async def AskQuestion(question: str, context: str = '') -> str:
        """Ask a question that will be routed to the appropriate responder.

        Use this tool when you need clarification, have a question about
        intent, or need human input before proceeding.  The question will
        be answered — you do not need to write escalation files.

        The tool automatically injects the caller's scratch file as context
        so the proxy or human receives the full job state alongside the
        question.

        Args:
            question: Your question. Be specific and concise.
            context: Ignored when a scratch file is present; kept for
                backward compatibility when the scratch file is absent.
        """
        return await ask_question_handler(
            question=question,
            context=context,
            scratch_path=_scratch_path_from_env(),
        )

    @server.tool()
    async def Send(member: str, message: str, context_id: str = '') -> str:
        """Send a message to a roster member, opening or continuing a thread.

        The tool automatically prepends the caller's scratch file as a
        Context section so the recipient has full job state without the
        caller constructing a manual brief.

        After Send completes, the agent's turn ends.  TeaParty re-invokes
        the caller when a response arrives on the thread.

        Args:
            member: Name key of a roster entry in your --agents object.
            message: The task or question for the recipient.
            context_id: Optional existing context ID to continue a thread.
                Omit to open a new thread.
        """
        return await send_handler(
            member=member,
            message=message,
            context_id=context_id,
            scratch_path=_scratch_path_from_env(),
        )

    @server.tool()
    async def Reply(message: str) -> str:
        """Reply to the agent that opened the current thread and close it.

        No context injection — the context is already established in the
        thread.  Calling Reply ends the agent's turn and marks the thread
        closed.  The calling agent's pending_count in the parent context
        is decremented.

        Args:
            message: Your reply — result, answer, or completion notice.
        """
        return await reply_handler(message=message)

    @server.tool()
    async def AskTeam(team: str, task: str) -> str:
        """Dispatch work to a specialist subteam and return the result.

        Use this tool to delegate a task to a subteam (art, writing,
        editorial, research, or coding).  The subteam runs a full CfA
        session and merges its deliverables into the shared worktree.

        Args:
            team: The team to dispatch to. One of: art, writing,
                editorial, research, coding.
            task: The specific task description for the subteam.
                Include relevant context, constraints, and success
                criteria so the team can work autonomously.
        """
        return await ask_team_handler(team=team, task=task)

    @server.tool()
    async def WithdrawSession(session_id: str) -> str:
        """Withdraw a session, setting its CfA state to WITHDRAWN.

        This is a team-lead authority action. It terminates the session
        and finalizes its heartbeat. Use when a session should be stopped
        entirely — the work is no longer needed or the approach is wrong.

        Args:
            session_id: The session to withdraw.
        """
        return await intervention_handler(
            'withdraw_session', session_id=session_id,
        )

    @server.tool()
    async def PauseDispatch(dispatch_id: str) -> str:
        """Pause a running dispatch.

        A paused dispatch will not launch new phases. Work already in
        progress completes but no new work starts. Use when you need
        to temporarily halt a dispatch without terminating it.

        Args:
            dispatch_id: The dispatch to pause.
        """
        return await intervention_handler(
            'pause_dispatch', dispatch_id=dispatch_id,
        )

    @server.tool()
    async def ResumeDispatch(dispatch_id: str) -> str:
        """Resume a paused dispatch.

        Restores the dispatch to running state so new phases can launch.
        Only works on dispatches that are currently paused.

        Args:
            dispatch_id: The dispatch to resume.
        """
        return await intervention_handler(
            'resume_dispatch', dispatch_id=dispatch_id,
        )

    @server.tool()
    async def ReprioritizeDispatch(dispatch_id: str, priority: str) -> str:
        """Change the priority of a dispatch.

        Updates the dispatch's priority level. Only works on dispatches
        that are currently running or paused (not terminal).

        Args:
            dispatch_id: The dispatch to reprioritize.
            priority: The new priority level (e.g. 'high', 'normal', 'low').
        """
        return await intervention_handler(
            'reprioritize_dispatch', dispatch_id=dispatch_id, priority=priority,
        )

    # ── Config tools ──────────────────────────────────────────────────────────

    @server.tool()
    async def AddProject(
        name: str,
        path: str,
        description: str = '',
        lead: str = '',
        decider: str = '',
        agents: str = '',
        humans: str = '',
        workgroups: str = '',
        skills: str = '',
        teaparty_home: str = '',
    ) -> str:
        """Register an existing directory as a TeaParty project.

        Creates a teams: entry in teaparty.yaml and scaffolds
        .teaparty.local/project.yaml with the provided fields.

        Args:
            name: Project name (must be unique in teaparty.yaml).
            path: Absolute path to the existing project directory.
            description: Short description of the project.
            lead: Agent name that leads this project.
            decider: Human name with decider role.
            agents: Comma-separated agent names.
            humans: YAML list of {name, role} dicts.
            workgroups: YAML list of workgroup refs or entries.
            skills: Comma-separated skill names.
            teaparty_home: Override for .teaparty/ directory path.
        """
        agents_list = [a.strip() for a in agents.split(',') if a.strip()] if agents else None
        humans_list = yaml.safe_load(humans) if humans else None
        workgroups_list = yaml.safe_load(workgroups) if workgroups else None
        skills_list = [s.strip() for s in skills.split(',') if s.strip()] if skills else None
        return add_project_handler(
            name=name, path=path, description=description,
            lead=lead, decider=decider,
            agents=agents_list, humans=humans_list,
            workgroups=workgroups_list, skills=skills_list,
            teaparty_home=teaparty_home,
        )

    @server.tool()
    async def CreateProject(
        name: str,
        path: str,
        description: str = '',
        lead: str = '',
        decider: str = '',
        agents: str = '',
        humans: str = '',
        workgroups: str = '',
        skills: str = '',
        teaparty_home: str = '',
    ) -> str:
        """Create a new project directory with full scaffolding.

        Runs git init, creates .claude/, scaffolds .teaparty.local/project.yaml,
        and adds a teams: entry to teaparty.yaml.

        Args:
            name: Project name (must be unique in teaparty.yaml).
            path: Path for the new project directory (must not exist yet).
            description: Short description.
            lead: Agent name for project lead.
            decider: Human decider name.
            agents: Comma-separated agent names.
            humans: YAML list of human entries.
            workgroups: YAML list of workgroup entries.
            skills: Comma-separated skill names.
            teaparty_home: Override for .teaparty/ directory path.
        """
        agents_list = [a.strip() for a in agents.split(',') if a.strip()] if agents else None
        humans_list = yaml.safe_load(humans) if humans else None
        workgroups_list = yaml.safe_load(workgroups) if workgroups else None
        skills_list = [s.strip() for s in skills.split(',') if s.strip()] if skills else None
        return create_project_handler(
            name=name, path=path, description=description,
            lead=lead, decider=decider,
            agents=agents_list, humans=humans_list,
            workgroups=workgroups_list, skills=skills_list,
            teaparty_home=teaparty_home,
        )

    @server.tool()
    async def RemoveProject(name: str, teaparty_home: str = '') -> str:
        """Remove a project from teaparty.yaml.

        The project directory is left untouched.  Only the teams: entry is removed.

        Args:
            name: Project name to remove.
            teaparty_home: Override for .teaparty/ directory path.
        """
        return remove_project_handler(name=name, teaparty_home=teaparty_home)

    @server.tool()
    async def ScaffoldProjectYaml(
        project_path: str,
        name: str,
        description: str = '',
        lead: str = '',
        decider: str = '',
        agents: str = '',
        humans: str = '',
        workgroups: str = '',
        skills: str = '',
    ) -> str:
        """Create or overwrite .teaparty.local/project.yaml for an existing project.

        Use this to retroactively fix a project.yaml that was created without
        required fields (e.g. empty lead or decider).  Always overwrites.

        Args:
            project_path: Absolute path to the project directory.
            name: Project name.
            description: Short description.
            lead: Agent name for project lead.
            decider: Human decider name.
            agents: Comma-separated agent names.
            humans: YAML list of human entries.
            workgroups: YAML list of workgroup entries.
            skills: Comma-separated skill names.
        """
        agents_list = [a.strip() for a in agents.split(',') if a.strip()] if agents else None
        humans_list = yaml.safe_load(humans) if humans else None
        workgroups_list = yaml.safe_load(workgroups) if workgroups else None
        skills_list = [s.strip() for s in skills.split(',') if s.strip()] if skills else None
        return scaffold_project_yaml_handler(
            project_path=project_path, name=name,
            description=description, lead=lead, decider=decider,
            agents=agents_list, humans=humans_list,
            workgroups=workgroups_list, skills=skills_list,
        )

    @server.tool()
    async def CreateAgent(
        name: str,
        description: str,
        model: str,
        tools: str,
        body: str,
        skills: str = '',
        max_turns: int = 20,
        project_root: str = '',
    ) -> str:
        """Create a new agent definition at .claude/agents/{name}.md.

        Args:
            name: Agent name (becomes the filename).
            description: One-line description used for auto-invocation matching.
            model: Claude model ID (e.g. claude-sonnet-4-5, claude-opus-4-5).
            tools: Comma-separated tool names (e.g. Read, Glob, Grep, Bash).
            body: Agent role description and instructions (Markdown).
            skills: Comma-separated skill names for the skills: allowlist.
            max_turns: Maximum turns before the agent stops.
            project_root: Override for project root directory.
        """
        return create_agent_handler(
            name=name, description=description, model=model,
            tools=tools, body=body, skills=skills,
            max_turns=max_turns, project_root=project_root,
        )

    @server.tool()
    async def EditAgent(
        name: str,
        field: str,
        value: str,
        project_root: str = '',
    ) -> str:
        """Edit a single field in an existing agent definition.

        Args:
            name: Agent name.
            field: Field to update (name, description, model, tools,
                maxTurns, skills, body, or any other frontmatter key).
            value: New value (for skills, use comma-separated list).
            project_root: Override for project root directory.
        """
        return edit_agent_handler(
            name=name, field=field, value=value, project_root=project_root,
        )

    @server.tool()
    async def RemoveAgent(name: str, project_root: str = '') -> str:
        """Delete .claude/agents/{name}.md.

        Args:
            name: Agent name.
            project_root: Override for project root directory.
        """
        return remove_agent_handler(name=name, project_root=project_root)

    @server.tool()
    async def CreateSkill(
        name: str,
        description: str,
        body: str,
        allowed_tools: str = '',
        argument_hint: str = '',
        user_invocable: bool = False,
        project_root: str = '',
    ) -> str:
        """Create a new skill at .claude/skills/{name}/SKILL.md.

        Args:
            name: Skill name (becomes the directory name).
            description: One-line description for auto-invocation matching.
            body: Skill instructions (Markdown).
            allowed_tools: Comma-separated tools available during skill execution.
            argument_hint: Argument syntax hint (e.g. <skill-name>).
            user_invocable: Whether the skill can be invoked with /{name}.
            project_root: Override for project root directory.
        """
        return create_skill_handler(
            name=name, description=description, body=body,
            allowed_tools=allowed_tools, argument_hint=argument_hint,
            user_invocable=user_invocable, project_root=project_root,
        )

    @server.tool()
    async def EditSkill(
        name: str,
        field: str,
        value: str,
        project_root: str = '',
    ) -> str:
        """Edit a single field of an existing skill's SKILL.md.

        Use field='body' to update the skill body.  Use field='allowed-tools',
        field='description', field='argument-hint', or field='user-invocable'
        to update frontmatter.

        Args:
            name: Skill name.
            field: Field to update ('body', 'description', 'allowed-tools', etc.).
            value: New value for the field.
            project_root: Override for project root directory.
        """
        return edit_skill_handler(name=name, field=field, value=value, project_root=project_root)

    @server.tool()
    async def RemoveSkill(name: str, project_root: str = '') -> str:
        """Remove .claude/skills/{name}/ directory and all its contents.

        Args:
            name: Skill name.
            project_root: Override for project root directory.
        """
        return remove_skill_handler(name=name, project_root=project_root)

    @server.tool()
    async def CreateWorkgroup(
        name: str,
        description: str = '',
        lead: str = '',
        agents_yaml: str = '',
        skills: str = '',
        norms_yaml: str = '',
        teaparty_home: str = '',
    ) -> str:
        """Create a workgroup YAML at .teaparty/workgroups/{name}.yaml.

        Args:
            name: Workgroup name.
            description: Short description.
            lead: Agent name for workgroup lead.
            agents_yaml: YAML list of agent entries.
            skills: Comma-separated skill names for the workgroup catalog.
            norms_yaml: YAML dict of norms categories.
            teaparty_home: Override for .teaparty/ directory path.
        """
        return create_workgroup_handler(
            name=name, description=description, lead=lead,
            agents_yaml=agents_yaml, skills=skills, norms_yaml=norms_yaml,
            teaparty_home=teaparty_home,
        )

    @server.tool()
    async def EditWorkgroup(
        name: str,
        field: str,
        value: str,
        teaparty_home: str = '',
    ) -> str:
        """Edit a single field in an existing workgroup YAML.

        Args:
            name: Workgroup name.
            field: Field to update (name, description, lead, agents, skills, norms).
            value: New value (YAML string for list/dict fields).
            teaparty_home: Override for .teaparty/ directory path.
        """
        return edit_workgroup_handler(
            name=name, field=field, value=value, teaparty_home=teaparty_home,
        )

    @server.tool()
    async def RemoveWorkgroup(name: str, teaparty_home: str = '') -> str:
        """Remove .teaparty/workgroups/{name}.yaml.

        Args:
            name: Workgroup name.
            teaparty_home: Override for .teaparty/ directory path.
        """
        return remove_workgroup_handler(name=name, teaparty_home=teaparty_home)

    @server.tool()
    async def CreateHook(
        event: str,
        matcher: str,
        handler_type: str,
        command: str,
        project_root: str = '',
    ) -> str:
        """Add a hook entry to .claude/settings.json.

        Args:
            event: Lifecycle event (PreToolUse, PostToolUse, Notification, Stop).
            matcher: Tool name or pattern to match (e.g. Edit, Write|Edit).
            handler_type: Handler type (command, agent, prompt, http).
            command: Shell command or handler expression.
            project_root: Override for project root directory.
        """
        return create_hook_handler(
            event=event, matcher=matcher,
            handler_type=handler_type, command=command,
            project_root=project_root,
        )

    @server.tool()
    async def EditHook(
        event: str,
        matcher: str,
        field: str,
        value: str,
        project_root: str = '',
    ) -> str:
        """Edit a field in an existing hook entry.

        Args:
            event: Lifecycle event of the hook to edit.
            matcher: Matcher of the hook entry to edit.
            field: Field to update (command, type, or matcher).
            value: New value.
            project_root: Override for project root directory.
        """
        return edit_hook_handler(
            event=event, matcher=matcher,
            field=field, value=value, project_root=project_root,
        )

    @server.tool()
    async def RemoveHook(event: str, matcher: str, project_root: str = '') -> str:
        """Remove a hook entry from .claude/settings.json.

        Args:
            event: Lifecycle event of the hook to remove.
            matcher: Matcher of the hook entry to remove.
            project_root: Override for project root directory.
        """
        return remove_hook_handler(
            event=event, matcher=matcher, project_root=project_root,
        )

    @server.tool()
    async def CreateScheduledTask(
        name: str,
        schedule: str,
        skill: str,
        args: str = '',
        teaparty_home: str = '',
    ) -> str:
        """Add a scheduled task entry to teaparty.yaml.

        The referenced skill must exist before calling this tool.

        Args:
            name: Task name (unique identifier).
            schedule: Cron expression (e.g. '0 2 * * *' for 2am daily).
            skill: Name of the skill to invoke on schedule.
            args: Optional arguments to pass to the skill.
            teaparty_home: Override for .teaparty/ directory path.
        """
        return create_scheduled_task_handler(
            name=name, schedule=schedule, skill=skill,
            args=args, teaparty_home=teaparty_home,
        )

    @server.tool()
    async def EditScheduledTask(
        name: str,
        field: str,
        value: str,
        teaparty_home: str = '',
    ) -> str:
        """Edit a field in an existing scheduled task entry.

        Args:
            name: Task name.
            field: Field to update (schedule, skill, args, enabled).
            value: New value.
            teaparty_home: Override for .teaparty/ directory path.
        """
        return edit_scheduled_task_handler(
            name=name, field=field, value=value, teaparty_home=teaparty_home,
        )

    @server.tool()
    async def RemoveScheduledTask(name: str, teaparty_home: str = '') -> str:
        """Remove a scheduled task entry from teaparty.yaml.

        Args:
            name: Task name.
            teaparty_home: Override for .teaparty/ directory path.
        """
        return remove_scheduled_task_handler(name=name, teaparty_home=teaparty_home)

    # ── Artifact pin tools ────────────────────────────────────────────────────

    @server.tool()
    async def PinArtifact(
        project: str,
        path: str,
        label: str = '',
        teaparty_home: str = '',
    ) -> str:
        """Add or update an artifact pin in a project's artifact viewer navigator.

        Pins a file or directory as a persistent entry in the project's artifact
        viewer. File pins open immediately on click; folder pins render as
        collapsible trees. If a pin with the same path exists, its label is updated.

        Args:
            project: Project name as registered in teaparty.yaml.
            path: Path relative to the project root (e.g. 'docs/', 'tests/test_engine.py').
            label: Display label for the navigator. Falls back to the last path component.
            teaparty_home: Override for .teaparty/ directory path.
        """
        return pin_artifact_handler(
            project=project, path=path, label=label, teaparty_home=teaparty_home,
        )

    @server.tool()
    async def UnpinArtifact(
        project: str,
        path: str,
        teaparty_home: str = '',
    ) -> str:
        """Remove an artifact pin from a project's artifact viewer navigator.

        Args:
            project: Project name as registered in teaparty.yaml.
            path: Path to remove (must match the path used when pinning).
            teaparty_home: Override for .teaparty/ directory path.
        """
        return unpin_artifact_handler(
            project=project, path=path, teaparty_home=teaparty_home,
        )

    return server


def main():
    """Run the MCP server on stdio."""
    server = create_server()
    server.run(transport='stdio')


if __name__ == '__main__':
    main()
