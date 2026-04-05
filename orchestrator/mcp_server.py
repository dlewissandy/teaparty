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
SEND_SOCKET, REPLY_SOCKET, and INTERVENTION_SOCKET
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
FlushFn = Callable[[str], Awaitable[None]]
InjectFn = Callable[[str, str, str, str], Awaitable[None]]
# (session_file, composite, session_id, cwd) -> None
SessionLookupFn = Callable[[str, str], tuple[str, str, str] | None]
# (member, context_id) -> (session_id, session_file, cwd) | None

# Maximum lines of scratch file content to include in the Context section.
# Oldest lines are dropped first when the file exceeds this limit.
CONTEXT_BUDGET_LINES = 200


async def ask_question_handler(
    question: str,
    context: str = '',
    *,
    scratch_path: str = '',
    flush_fn: FlushFn | None = None,
    proxy_fn: ProxyFn | None = None,
    human_fn: HumanFn | None = None,
    record_differential_fn: RecordDifferentialFn | None = None,
) -> str:
    """Core handler logic for AskQuestion.

    Routes through the proxy first.  If the proxy is confident, returns
    its answer directly.  Otherwise escalates to the human, records the
    differential (proxy prediction vs. human actual), and returns the
    human's answer.

    When scratch_path is given, the handler requests a flush via flush_fn
    (so the orchestrator writes its current in-memory state to disk), then
    reads the file and builds a composite envelope (## Task / ## Context)
    identical to Send's envelope before passing the question to the proxy.

    Args:
        question: The question the agent is asking.
        context: Optional extra context (ignored when scratch_path is set).
        scratch_path: Path to the caller's scratch file.  When set, the
            handler flushes, reads, truncates to CONTEXT_BUDGET_LINES,
            and wraps question in the standard Task/Context envelope.
        flush_fn: Async function called with the scratch_path before the
            file is read.  The orchestrator uses this to write its current
            in-memory ScratchModel to disk so the composite reflects the
            full current turn.  Defaults to _default_flush.
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
        if flush_fn is None:
            flush_fn = _default_flush
        await flush_fn(scratch_path)
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


# ── Scratch file helpers ────────────────────────────────────────────────

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


async def _default_flush(scratch_path: str) -> None:
    """Request the orchestrator to flush its current job state to the scratch file.

    Sends a synchronous flush request to the orchestrator via FLUSH_SOCKET
    and waits for acknowledgement before returning.  The orchestrator's
    FlushListener writes the current in-memory ScratchModel to disk so the
    composite reflects everything up to and including the current turn.

    If FLUSH_SOCKET is not set (e.g. in environments without the orchestrator
    running), the flush is skipped and the scratch file is read as-is.
    """
    socket_path = os.environ.get('FLUSH_SOCKET', '')
    if not socket_path:
        return
    reader, writer = await asyncio.open_unix_connection(socket_path)
    try:
        request = json.dumps({'type': 'flush', 'scratch_path': scratch_path})
        writer.write(request.encode() + b'\n')
        await writer.drain()
        await reader.readline()  # wait for ack
    finally:
        writer.close()
        await writer.wait_closed()


def _default_session_lookup(member: str, context_id: str) -> tuple[str, str, str] | None:
    """Look up session info for (member, context_id) from SESSION_REGISTRY_PATH.

    Returns (session_id, session_file, cwd) when a matching entry exists,
    or None when no session has been registered for this context.
    """
    from orchestrator.messaging import SessionRegistry
    registry_path = os.environ.get('SESSION_REGISTRY_PATH', '')
    if not registry_path:
        return None
    return SessionRegistry(registry_path).lookup(member, context_id)


async def _default_inject(
    session_file: str, composite: str, session_id: str, cwd: str,
) -> None:
    """Inject composite into the recipient's JSONL conversation history.

    Delegates to inject_composite_into_history in orchestrator.messaging.
    """
    from orchestrator.messaging import inject_composite_into_history
    inject_composite_into_history(session_file, composite, session_id, cwd)


# ── Send / Reply handlers ───────────────────────────────────────────────

async def send_handler(
    member: str,
    message: str,
    context_id: str = '',
    *,
    scratch_path: str = '',
    flush_fn: FlushFn | None = None,
    post_fn: SendPostFn | None = None,
    session_lookup_fn: SessionLookupFn | None = None,
    inject_fn: InjectFn | None = None,
) -> str:
    """Core handler logic for Send.

    Before assembling the composite, calls flush_fn so the orchestrator
    writes its current in-memory job state to the scratch file.  Then reads
    the scratch file, builds the composite Task/Context envelope.

    For continuation sends (context_id provided), looks up the recipient's
    session via session_lookup_fn and injects the composite into their
    conversation history (JSONL file) before posting.  This satisfies SC3:
    the recipient's spawned conversation history contains the composite.
    For first sends (context_id=''), no session exists yet — the composite
    is delivered as $TASK by the bus listener at spawn time.

    Finally posts the composite to the named roster member via post_fn.

    Args:
        member: Name of the roster member to send to.
        message: The agent's message (becomes the Task section).
        context_id: Optional existing context ID for continuing a thread.
        scratch_path: Override path to the scratch file (for testing).
        flush_fn: Async function called with the scratch_path before the
            file is read.  Triggers the orchestrator to write its current
            in-memory ScratchModel to disk so the composite is current.
            Defaults to _default_flush.
        post_fn: Async function that posts (member, composite, context_id)
            and returns a result string.  Defaults to the SEND_SOCKET
            transport.
        session_lookup_fn: Sync function that returns (session_id,
            session_file, cwd) for (member, context_id), or None if no
            session exists.  Defaults to the SESSION_REGISTRY_PATH lookup.
        inject_fn: Async function that injects (session_file, composite,
            session_id, cwd) into the recipient's JSONL history.  Only
            called when session_lookup_fn returns a result.  Defaults to
            _default_inject.
    """
    if not member or not member.strip():
        raise ValueError('Send requires a non-empty member')
    if not message or not message.strip():
        raise ValueError('Send requires a non-empty message')

    resolved = scratch_path or _scratch_path_from_env()

    if flush_fn is None:
        flush_fn = _default_flush
    await flush_fn(resolved)

    scratch = _read_scratch(resolved)
    composite = _build_composite(message, scratch)

    # Inject into existing session when continuing a thread (context_id set).
    # For first sends, composite is delivered as $TASK at spawn time.
    if session_lookup_fn is not None:
        session_info = session_lookup_fn(member, context_id)
    elif context_id:
        session_info = _default_session_lookup(member, context_id)
    else:
        session_info = None

    if session_info is not None:
        session_id, session_file, cwd = session_info
        if inject_fn is None:
            inject_fn = _default_inject
        await inject_fn(session_file, composite, session_id, cwd)

    if post_fn is None:
        post_fn = _default_send_post
    return await post_fn(member, composite, context_id)


async def _default_send_post(member: str, composite: str, context_id: str) -> str:
    """Default Send transport: post via SEND_SOCKET Unix domain socket."""
    import time as _time
    import logging as _logging
    _send_log = _logging.getLogger('orchestrator.mcp_server.send')

    socket_path = os.environ.get('SEND_SOCKET', '')
    if not socket_path:
        raise RuntimeError('SEND_SOCKET not set — cannot send to member')

    t0 = _time.monotonic()
    reader, writer = await asyncio.open_unix_connection(socket_path)
    t_connect = _time.monotonic()
    try:
        request = json.dumps({
            'type': 'send', 'member': member,
            'composite': composite, 'context_id': context_id,
        })
        writer.write(request.encode() + b'\n')
        await writer.drain()
        t_sent = _time.monotonic()

        response_line = await reader.readline()
        t_response = _time.monotonic()

        response = json.loads(response_line.decode())
        _send_log.info(
            'send_post_timing: member=%r connect=%.3fs write=%.3fs '
            'wait=%.2fs total=%.2fs',
            member, t_connect - t0, t_sent - t_connect,
            t_response - t_sent, t_response - t0,
        )
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
        context_id = os.environ.get('CONTEXT_ID', '')
        request = json.dumps({'type': 'reply', 'message': message, 'context_id': context_id})
        writer.write(request.encode() + b'\n')
        await writer.drain()
        response_line = await reader.readline()
        response = json.loads(response_line.decode())
        return json.dumps(response)
    finally:
        writer.close()
        await writer.wait_closed()


CloseConvPostFn = Callable[[str], Awaitable[str]]


async def close_conversation_handler(
    context_id: str,
    *,
    post_fn: CloseConvPostFn | None = None,
) -> str:
    """Core handler logic for CloseConversation.

    Posts the context_id to the close socket so BusEventListener can set
    conversation_status='closed'.  Only the originator may close a
    conversation — BusEventListener enforces this by checking caller_agent_id
    against the context record's initiator_agent_id.

    Args:
        context_id: The conversation context ID to close.
        post_fn: Async function that posts context_id and returns a result
            string.  Defaults to the CLOSE_CONV_SOCKET transport.
    """
    if not context_id or not context_id.strip():
        raise ValueError('CloseConversation requires a non-empty context_id')

    if post_fn is None:
        post_fn = _default_close_conv_post
    return await post_fn(context_id)


async def _default_close_conv_post(context_id: str) -> str:
    """Default CloseConversation transport: post via CLOSE_CONV_SOCKET."""
    socket_path = os.environ.get('CLOSE_CONV_SOCKET', '')
    if not socket_path:
        raise RuntimeError('CLOSE_CONV_SOCKET not set — cannot close conversation')
    reader, writer = await asyncio.open_unix_connection(socket_path)
    try:
        request = json.dumps({
            'type': 'close_conversation',
            'context_id': context_id,
            'caller_agent_id': os.environ.get('AGENT_ID', ''),
        })
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


# ── Config tool helpers ───────────────────────────────────────────────────────

def _ok(message: str, **extra) -> str:
    return json.dumps({'success': True, 'message': message, **extra})


def _err(error: str) -> str:
    return json.dumps({'success': False, 'error': error})


def _project_root(override: str) -> str:
    return override if override else os.getcwd()


def _teaparty_home(override: str) -> str:
    return override if override else os.path.join(os.getcwd(), '.teaparty')


def _mgmt_agents_dir(teaparty_home: str) -> str:
    return os.path.join(teaparty_home, 'management', 'agents')


def _mgmt_skills_dir(teaparty_home: str) -> str:
    return os.path.join(teaparty_home, 'management', 'skills')


def _mgmt_settings_yaml(teaparty_home: str) -> str:
    return os.path.join(teaparty_home, 'management', 'settings.yaml')


def _mgmt_workgroups_dir(teaparty_home: str) -> str:
    return os.path.join(teaparty_home, 'management', 'workgroups')


def _proj_agents_dir(project_root: str) -> str:
    return os.path.join(project_root, '.teaparty', 'project', 'agents')


def _proj_skills_dir(project_root: str) -> str:
    return os.path.join(project_root, '.teaparty', 'project', 'skills')


def _proj_settings_yaml(project_root: str) -> str:
    return os.path.join(project_root, '.teaparty', 'project', 'settings.yaml')


def _proj_workgroups_dir(project_root: str) -> str:
    return os.path.join(project_root, '.teaparty', 'project', 'workgroups')


def _parse_agent_file(path: str) -> tuple[dict, str]:
    """Parse an agents/{name}/agent.md file.

    Returns (frontmatter_dict, body_text).
    """
    with open(path) as f:
        content = f.read()
    m = re.match(r'^---\n(.*?\n)---\n(.*)', content, re.DOTALL)
    if not m:
        return {}, content
    return yaml.safe_load(m.group(1)) or {}, m.group(2)


def _write_agent_file(path: str, fm: dict, body: str) -> None:
    """Write an agents/{name}/agent.md file."""
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


def _load_settings(settings_path: str) -> dict:
    """Load a settings.yaml file, returning default if missing."""
    if os.path.exists(settings_path):
        with open(settings_path) as f:
            try:
                return yaml.safe_load(f) or {'hooks': {}}
            except yaml.YAMLError:
                return {'hooks': {}}
    return {'hooks': {}}


def _save_settings(settings_path: str, data: dict) -> None:
    os.makedirs(os.path.dirname(settings_path), exist_ok=True)
    with open(settings_path, 'w') as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)


def _load_teaparty_yaml(teaparty_home: str) -> dict:
    path = os.path.join(teaparty_home, 'management', 'teaparty.yaml')
    if not os.path.exists(path):
        raise FileNotFoundError(f'teaparty.yaml not found: {path}')
    with open(path) as f:
        return yaml.safe_load(f) or {}


def _save_teaparty_yaml(teaparty_home: str, data: dict) -> None:
    path = os.path.join(teaparty_home, 'management', 'teaparty.yaml')
    os.makedirs(os.path.dirname(path), exist_ok=True)
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

    Registers it in management/teaparty.yaml and creates
    .teaparty/project/project.yaml with the provided fields.  Returns JSON result.
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
            workgroups=workgroups,
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
    """Create a new project directory with full scaffolding (git init, .teaparty/, etc.)."""
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
            workgroups=workgroups,
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
    """Create or overwrite .teaparty/project/project.yaml for an existing project.

    Unlike _scaffold_project_yaml, this always writes (retroactive fix for
    projects with missing or empty fields).
    """
    if not project_path or not project_path.strip():
        return _err('ScaffoldProjectYaml requires a non-empty project_path')
    if not name or not name.strip():
        return _err('ScaffoldProjectYaml requires a non-empty name')

    tp_dir = os.path.join(project_path, '.teaparty', 'project')
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

def _load_project_registry(teaparty_home: str) -> dict:
    """Load the root teaparty.yaml (canonical project registry).

    Falls back to management/teaparty.yaml if the root file doesn't exist.
    """
    root_yaml = os.path.join(teaparty_home, 'teaparty.yaml')
    if os.path.exists(root_yaml):
        with open(root_yaml) as f:
            return yaml.safe_load(f) or {}
    return _load_teaparty_yaml(teaparty_home)


def _find_project_path(name: str, teaparty_home: str) -> str | None:
    """Return the project directory for a given project name, or None if not found."""
    data = _load_project_registry(teaparty_home)
    for team in data.get('projects', []):
        if team.get('name') == name:
            return team.get('path')
    return None


def _load_project_yaml(project_dir: str) -> dict:
    """Load .teaparty/project/project.yaml, returning an empty dict if missing."""
    path = os.path.join(project_dir, '.teaparty', 'project', 'project.yaml')
    if not os.path.exists(path):
        # Legacy fallback
        legacy = os.path.join(project_dir, '.teaparty.local', 'project.yaml')
        if os.path.exists(legacy):
            with open(legacy) as f:
                return yaml.safe_load(f) or {}
        return {}
    with open(path) as f:
        return yaml.safe_load(f) or {}


def _save_project_yaml(project_dir: str, data: dict) -> None:
    """Write data to .teaparty/project/project.yaml."""
    tp_dir = os.path.join(project_dir, '.teaparty', 'project')
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


# ── Read/list tools ──────────────────────────────────────────────────────────


def list_projects_handler(teaparty_home: str = '') -> str:
    """List all registered projects from the root teaparty.yaml."""
    home = _teaparty_home(teaparty_home)
    try:
        data = _load_project_registry(home)
    except FileNotFoundError as e:
        return _err(str(e))
    projects = data.get('projects', [])
    items = [{'name': p.get('name', ''), 'path': p.get('path', '')}
             for p in projects]
    return json.dumps({'success': True, 'projects': items})


def get_project_handler(name: str, teaparty_home: str = '') -> str:
    """Get full details for a single project."""
    if not name or not name.strip():
        return _err('GetProject requires a non-empty name')
    home = _teaparty_home(teaparty_home)
    project_dir = _find_project_path(name, home)
    if project_dir is None:
        return _err(f"Project '{name}' not found in registry")
    data = _load_project_yaml(project_dir)
    data['path'] = project_dir
    return json.dumps({'success': True, 'project': data})


def list_team_members_handler(teaparty_home: str = '') -> str:
    """List the team members for the calling agent's team.

    Membership is derived from config, not from agent definitions:
    - Proxy agents implied by humans: entries
    - Project leads implied by members.projects
    - Workgroup leads implied by members.workgroups
    """
    from orchestrator.config_reader import (
        load_management_team,
        load_management_workgroups,
        load_project_team,
        read_agent_frontmatter,
    )

    home = _teaparty_home(teaparty_home)
    try:
        team = load_management_team(teaparty_home=home)
    except FileNotFoundError as e:
        return _err(str(e))

    repo_root = os.path.dirname(home)
    mgmt_agents_dir = os.path.join(home, 'management', 'agents')
    members: list[dict] = []

    def _read_desc(agent_name: str) -> str:
        for candidate in (
            os.path.join(mgmt_agents_dir, agent_name, 'agent.md'),
        ):
            if os.path.isfile(candidate):
                fm, _ = _parse_agent_file(candidate)
                return fm.get('description', '')
        return ''

    # Project leads
    for project_name in team.members_projects:
        project_entry = None
        for p in team.projects:
            if p.get('name') == project_name:
                project_entry = p
                break
        if project_entry is None:
            continue
        project_path = project_entry.get('path', '')
        if not os.path.isabs(project_path):
            project_path = os.path.join(repo_root, project_path)
        config_path = project_entry.get('config', '')
        full_config = os.path.join(project_path, config_path) if config_path else None
        try:
            pt = load_project_team(project_path, config_path=full_config)
        except FileNotFoundError:
            continue
        if pt.lead:
            members.append({
                'name': pt.lead,
                'role': 'project-lead',
                'project': project_name,
                'description': _read_desc(pt.lead) or pt.description or project_name,
            })

    # Workgroup leads
    try:
        workgroups = load_management_workgroups(team, teaparty_home=home)
        for wg in workgroups:
            if wg.lead:
                members.append({
                    'name': wg.lead,
                    'role': 'workgroup-lead',
                    'workgroup': wg.name,
                    'description': _read_desc(wg.lead) or wg.description or wg.name,
                })
    except Exception:
        pass

    # Proxy agents
    for human in team.humans:
        proxy_name = 'proxy-review'
        members.append({
            'name': proxy_name,
            'role': 'proxy',
            'human': human.name,
            'description': _read_desc(proxy_name) or f'Human proxy for {human.name}',
        })

    return json.dumps({'success': True, 'members': members})


def list_agents_handler(project_root: str = '') -> str:
    """List all agent definitions with summary info."""
    root = _project_root(project_root)
    agents_dir = _mgmt_agents_dir(os.path.join(root, '.teaparty'))
    items = []
    if os.path.isdir(agents_dir):
        for name in sorted(os.listdir(agents_dir)):
            path = os.path.join(agents_dir, name, 'agent.md')
            if os.path.isfile(path):
                fm, _ = _parse_agent_file(path)
                items.append({
                    'name': name,
                    'description': fm.get('description', ''),
                    'model': fm.get('model', ''),
                })
    return json.dumps({'success': True, 'agents': items})


def get_agent_handler(name: str, project_root: str = '') -> str:
    """Get full details for a single agent definition."""
    if not name or not name.strip():
        return _err('GetAgent requires a non-empty name')
    root = _project_root(project_root)
    agents_dir = _mgmt_agents_dir(os.path.join(root, '.teaparty'))
    path = os.path.join(agents_dir, name, 'agent.md')
    if not os.path.isfile(path):
        return _err(f"Agent '{name}' not found at {path}")
    fm, body = _parse_agent_file(path)
    return json.dumps({'success': True, 'agent': {
        'name': name, 'path': path, **fm, 'body': body,
    }})


def list_skills_handler(project_root: str = '') -> str:
    """List all skill definitions with summary info."""
    root = _project_root(project_root)
    skills_dir = _mgmt_skills_dir(os.path.join(root, '.teaparty'))
    items = []
    if os.path.isdir(skills_dir):
        for name in sorted(os.listdir(skills_dir)):
            path = os.path.join(skills_dir, name, 'SKILL.md')
            if os.path.isfile(path):
                fm, _ = _parse_skill_file(path)
                items.append({
                    'name': name,
                    'description': fm.get('description', ''),
                    'user-invocable': fm.get('user-invocable', False),
                })
    return json.dumps({'success': True, 'skills': items})


def get_skill_handler(name: str, project_root: str = '') -> str:
    """Get full details for a single skill definition."""
    if not name or not name.strip():
        return _err('GetSkill requires a non-empty name')
    root = _project_root(project_root)
    skills_dir = _mgmt_skills_dir(os.path.join(root, '.teaparty'))
    path = os.path.join(skills_dir, name, 'SKILL.md')
    if not os.path.isfile(path):
        return _err(f"Skill '{name}' not found at {path}")
    fm, body = _parse_skill_file(path)
    return json.dumps({'success': True, 'skill': {
        'name': name, 'path': path, **fm, 'body': body,
    }})


def list_workgroups_handler(teaparty_home: str = '') -> str:
    """List all workgroup definitions."""
    home = _teaparty_home(teaparty_home)
    wg_dir = _mgmt_workgroups_dir(home)
    items = []
    if os.path.isdir(wg_dir):
        for fname in sorted(os.listdir(wg_dir)):
            if fname.endswith('.yaml'):
                path = os.path.join(wg_dir, fname)
                with open(path) as f:
                    data = yaml.safe_load(f) or {}
                items.append({
                    'name': data.get('name', fname[:-5]),
                    'description': data.get('description', ''),
                    'lead': data.get('lead', ''),
                })
    return json.dumps({'success': True, 'workgroups': items})


def get_workgroup_handler(name: str, teaparty_home: str = '') -> str:
    """Get full details for a single workgroup."""
    if not name or not name.strip():
        return _err('GetWorkgroup requires a non-empty name')
    home = _teaparty_home(teaparty_home)
    path = os.path.join(_mgmt_workgroups_dir(home), f'{name}.yaml')
    if not os.path.exists(path):
        return _err(f"Workgroup '{name}' not found at {path}")
    with open(path) as f:
        data = yaml.safe_load(f) or {}
    return json.dumps({'success': True, 'workgroup': data})


def list_hooks_handler(project_root: str = '') -> str:
    """List all hooks grouped by event."""
    root = _project_root(project_root)
    settings_path = _mgmt_settings_yaml(os.path.join(root, '.teaparty'))
    data = _load_settings(settings_path)
    hooks = data.get('hooks', {})
    items = []
    for event, entries in hooks.items():
        for entry in entries:
            items.append({
                'event': event,
                'matcher': entry.get('matcher', ''),
                'hooks': entry.get('hooks', []),
            })
    return json.dumps({'success': True, 'hooks': items})


def list_scheduled_tasks_handler(teaparty_home: str = '') -> str:
    """List all scheduled tasks."""
    home = _teaparty_home(teaparty_home)
    try:
        data = _load_teaparty_yaml(home)
    except FileNotFoundError as e:
        return _err(str(e))
    scheduled = data.get('scheduled', [])
    return json.dumps({'success': True, 'scheduled_tasks': scheduled})


def list_pins_handler(project: str, teaparty_home: str = '') -> str:
    """List all artifact pins for a project."""
    if not project or not project.strip():
        return _err('ListPins requires a non-empty project')
    home = _teaparty_home(teaparty_home)
    project_dir = _find_project_path(project, home)
    if project_dir is None:
        return _err(f"Project '{project}' not found in registry")
    data = _load_project_yaml(project_dir)
    pins = data.get('artifact_pins', [])
    return json.dumps({'success': True, 'pins': pins})


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
    """Create agents/{name}/agent.md with validated frontmatter."""
    if not name or not name.strip():
        return _err('CreateAgent requires a non-empty name')
    if not description or not description.strip():
        return _err('CreateAgent requires a non-empty description')
    if not model or not model.strip():
        return _err('CreateAgent requires a non-empty model')

    root = _project_root(project_root)
    agents_dir = _mgmt_agents_dir(os.path.join(root, '.teaparty'))
    path = os.path.join(agents_dir, name, 'agent.md')

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

    # Write default settings.yaml with message bus dispatch permissions.
    agent_dir = os.path.dirname(path)
    settings_path = os.path.join(agent_dir, 'settings.yaml')
    if not os.path.exists(settings_path):
        import yaml as _yaml
        default_settings = {
            'permissions': {
                'allow': [
                    'mcp__teaparty-config__Send',
                    'mcp__teaparty-config__Reply',
                    'mcp__teaparty-config__ListAgents',
                    'mcp__teaparty-config__GetAgent',
                    'mcp__teaparty-config__ListSkills',
                    'mcp__teaparty-config__GetSkill',
                    'mcp__teaparty-config__ListWorkgroups',
                    'mcp__teaparty-config__GetWorkgroup',
                    'mcp__teaparty-config__ListProjects',
                    'mcp__teaparty-config__GetProject',
                ],
            },
        }
        with open(settings_path, 'w') as f:
            _yaml.dump(default_settings, f, default_flow_style=False)

    # Write default pins.yaml so every agent has prompt and settings pinned.
    from orchestrator.config_reader import write_pins
    pins_dir = agent_dir
    pins_path = os.path.join(pins_dir, 'pins.yaml')
    if not os.path.exists(pins_path):
        write_pins(pins_dir, [
            {'path': 'agent.md', 'label': 'Prompt & Identity'},
            {'path': 'settings.yaml', 'label': 'Tool & File Permissions'},
        ])

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
    agents_dir = _mgmt_agents_dir(os.path.join(root, '.teaparty'))
    path = os.path.join(agents_dir, name, 'agent.md')
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
    """Delete agents/{name}/ directory."""
    if not name or not name.strip():
        return _err('RemoveAgent requires a non-empty name')

    root = _project_root(project_root)
    agents_dir = _mgmt_agents_dir(os.path.join(root, '.teaparty'))
    agent_dir = os.path.join(agents_dir, name)
    if not os.path.isdir(agent_dir):
        return _err(f"Agent '{name}' not found at {agent_dir}")

    shutil.rmtree(agent_dir)
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
    """Create skills/{name}/SKILL.md with validated frontmatter."""
    if not name or not name.strip():
        return _err('CreateSkill requires a non-empty name')
    if not description or not description.strip():
        return _err('CreateSkill requires a non-empty description')

    root = _project_root(project_root)
    skills_dir = _mgmt_skills_dir(os.path.join(root, '.teaparty'))
    skill_dir = os.path.join(skills_dir, name)
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
    skills_dir = _mgmt_skills_dir(os.path.join(root, '.teaparty'))
    path = os.path.join(skills_dir, name, 'SKILL.md')
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
    """Remove skills/{name}/ directory."""
    if not name or not name.strip():
        return _err('RemoveSkill requires a non-empty name')

    root = _project_root(project_root)
    skills_dir = _mgmt_skills_dir(os.path.join(root, '.teaparty'))
    skill_dir = os.path.join(skills_dir, name)
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
    """Create a workgroup YAML in management/workgroups/{name}.yaml."""
    if not name or not name.strip():
        return _err('CreateWorkgroup requires a non-empty name')

    home = _teaparty_home(teaparty_home)
    wg_dir = _mgmt_workgroups_dir(home)
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
    path = os.path.join(_mgmt_workgroups_dir(home), f'{name}.yaml')
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
    path = os.path.join(_mgmt_workgroups_dir(home), f'{name}.yaml')
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
    """Add a hook entry to settings.yaml."""
    if not event or not event.strip():
        return _err('CreateHook requires a non-empty event')
    if not command or not command.strip():
        return _err('CreateHook requires a non-empty command')

    root = _project_root(project_root)
    settings_path = _mgmt_settings_yaml(os.path.join(root, '.teaparty'))
    data = _load_settings(settings_path)
    hooks = data.setdefault('hooks', {})
    event_hooks = hooks.setdefault(event, [])

    new_entry = {
        'matcher': matcher,
        'hooks': [{'type': handler_type, 'command': command}],
    }
    event_hooks.append(new_entry)
    _save_settings(settings_path, data)
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
    settings_path = _mgmt_settings_yaml(os.path.join(root, '.teaparty'))
    data = _load_settings(settings_path)
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
            _save_settings(settings_path, data)
            return _ok(f"Hook {event}/{matcher} field '{field}' updated")

    return _err(f"Hook not found: {event}/{matcher}")


def remove_hook_handler(event: str, matcher: str, project_root: str = '') -> str:
    """Remove a hook entry from settings.yaml."""
    root = _project_root(project_root)
    settings_path = _mgmt_settings_yaml(os.path.join(root, '.teaparty'))
    data = _load_settings(settings_path)
    event_hooks = data.get('hooks', {}).get(event, [])

    original_len = len(event_hooks)
    data['hooks'][event] = [
        e for e in event_hooks if e.get('matcher') != matcher
    ]

    if len(data['hooks'][event]) == original_len:
        return _err(f"Hook not found: {event}/{matcher}")

    _save_settings(settings_path, data)
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


MCP_SERVER_NAME = 'teaparty-config'


def list_mcp_tool_names() -> list[str]:
    """Return the namespaced tool names exposed by the teaparty-config MCP server.

    Used by the bridge catalog API so the config UI can display all
    available tools without hardcoding them.  The names use Claude Code's
    ``mcp__{server}__{tool}`` convention.
    """
    server = create_server()
    prefix = f'mcp__{MCP_SERVER_NAME}__'
    return [prefix + name for name in sorted(server._tool_manager._tools)]


def _agent_tool_scope() -> str:
    """Determine tool scope for this MCP server instance.

    Checked in order:
    1. AGENT_TOOL_SCOPE env var (set by mcp_server_dispatch entry point)
    2. .tool-scope file in cwd (written by compose_worktree)
    3. '' (full tool set — interactive session)
    """
    scope = os.environ.get('AGENT_TOOL_SCOPE', '')
    if scope:
        return scope
    scope_file = os.path.join(os.getcwd(), '.tool-scope')
    try:
        with open(scope_file) as f:
            return f.read().strip()
    except FileNotFoundError:
        return ''


def create_server() -> FastMCP:
    """Create the MCP server with tools scoped to the agent's role."""
    import logging as _logging
    _cs_log = _logging.getLogger('orchestrator.mcp_server.create')

    server = FastMCP('teaparty-escalation')
    scope = _agent_tool_scope()
    _cs_log.info('create_server: AGENT_TOOL_SCOPE=%r', scope)

    # Leaf agents need no MCP tools — they just answer and exit.
    if scope == 'leaf':
        _cs_log.info('create_server: leaf scope — returning empty server')
        return server

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
            flush_fn=_default_flush,
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
            flush_fn=_default_flush,
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
    async def CloseConversation(context_id: str) -> str:
        """Close a conversation thread you opened.

        Marks the conversation as closed so no further follow-up Sends
        are accepted on this thread.  Only the originator of the thread
        should call this.  Does not affect the session turn — use Reply
        to close the current session turn.

        Args:
            context_id: The conversation context ID returned by the
                original Send call.
        """
        return await close_conversation_handler(context_id=context_id)

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

    # ── Read/list tools ──────────────────────────────────────────────────────

    @server.tool()
    async def ListProjects(teaparty_home: str = '') -> str:
        """List all registered projects.

        Returns project names and paths for all projects registered in
        teaparty.yaml (both inline and external-projects).

        Args:
            teaparty_home: Override for .teaparty/ directory path.
        """
        return list_projects_handler(teaparty_home=teaparty_home)

    @server.tool()
    async def GetProject(name: str, teaparty_home: str = '') -> str:
        """Get full configuration for a registered project.

        Returns the project's project.yaml contents including lead,
        decider, humans, workgroups, and artifact pins.

        Args:
            name: Project name as registered in teaparty.yaml.
            teaparty_home: Override for .teaparty/ directory path.
        """
        return get_project_handler(name=name, teaparty_home=teaparty_home)

    @server.tool()
    async def ListTeamMembers(teaparty_home: str = '') -> str:
        """List the members of your team.

        Returns your direct reports derived from the team config:
        project leads, workgroup leads, and proxy agents. This is
        your team — use it to answer "who is on my team?".

        Args:
            teaparty_home: Override for .teaparty/ directory path.
        """
        return list_team_members_handler(teaparty_home=teaparty_home)

    @server.tool()
    async def ListAgents(project_root: str = '') -> str:
        """List all agent definitions with summary info.

        Returns name, description, and model for each agent found in
        the agents/ directory. Note: this lists all definitions across
        the hierarchy, not just your team members.

        Args:
            project_root: Override for project root directory.
        """
        return list_agents_handler(project_root=project_root)

    @server.tool()
    async def GetAgent(name: str, project_root: str = '') -> str:
        """Get full definition for a single agent.

        Returns all frontmatter fields (name, description, model, tools,
        maxTurns, skills) and the body text.

        Args:
            name: Agent name.
            project_root: Override for project root directory.
        """
        return get_agent_handler(name=name, project_root=project_root)

    @server.tool()
    async def ListSkills(project_root: str = '') -> str:
        """List all skill definitions with summary info.

        Returns name, description, and user-invocable flag for each
        skill found in the skills/ directory.

        Args:
            project_root: Override for project root directory.
        """
        return list_skills_handler(project_root=project_root)

    @server.tool()
    async def GetSkill(name: str, project_root: str = '') -> str:
        """Get full definition for a single skill.

        Returns all frontmatter fields and the body text.

        Args:
            name: Skill name.
            project_root: Override for project root directory.
        """
        return get_skill_handler(name=name, project_root=project_root)

    @server.tool()
    async def ListWorkgroups(teaparty_home: str = '') -> str:
        """List all workgroup definitions with summary info.

        Returns name, description, and lead for each workgroup YAML
        found in the workgroups/ directory.

        Args:
            teaparty_home: Override for .teaparty/ directory path.
        """
        return list_workgroups_handler(teaparty_home=teaparty_home)

    @server.tool()
    async def GetWorkgroup(name: str, teaparty_home: str = '') -> str:
        """Get full configuration for a single workgroup.

        Returns all fields: name, description, lead, agents, skills, norms.

        Args:
            name: Workgroup name.
            teaparty_home: Override for .teaparty/ directory path.
        """
        return get_workgroup_handler(name=name, teaparty_home=teaparty_home)

    @server.tool()
    async def ListHooks(project_root: str = '') -> str:
        """List all hooks from settings.yaml.

        Returns each hook entry with its event, matcher, and handler
        configuration.

        Args:
            project_root: Override for project root directory.
        """
        return list_hooks_handler(project_root=project_root)

    @server.tool()
    async def ListScheduledTasks(teaparty_home: str = '') -> str:
        """List all scheduled tasks from teaparty.yaml.

        Returns each task with name, schedule, skill, args, and
        enabled status.

        Args:
            teaparty_home: Override for .teaparty/ directory path.
        """
        return list_scheduled_tasks_handler(teaparty_home=teaparty_home)

    @server.tool()
    async def ListPins(project: str, teaparty_home: str = '') -> str:
        """List all artifact pins for a project.

        Returns each pin's path and label from the project's
        artifact_pins list.

        Args:
            project: Project name as registered in teaparty.yaml.
            teaparty_home: Override for .teaparty/ directory path.
        """
        return list_pins_handler(project=project, teaparty_home=teaparty_home)

    # ── Config tools ──────────────────────────────────────────────────────────
    # Dispatching agents only need Send/Reply + read tools above.
    # Skip the 25+ config CRUD tools to stay below the deferral threshold.
    if scope == 'dispatch':
        return server

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

        Creates a projects: entry in management/teaparty.yaml and scaffolds
        .teaparty/project/project.yaml with the provided fields.

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

        Runs git init, scaffolds .teaparty/project/project.yaml,
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
        """Create or overwrite .teaparty/project/project.yaml for an existing project.

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
        """Create a new agent definition at agents/{name}/agent.md.

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
        """Delete agents/{name}/ directory.

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
        """Create a new skill at skills/{name}/SKILL.md.

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
        """Remove skills/{name}/ directory and all its contents.

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
        """Add a hook entry to settings.yaml.

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
        """Remove a hook entry from settings.yaml.

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
    """Run the MCP server on stdio.

    Logging goes to a file under .teaparty/ (not stderr — stdio is the
    MCP transport and some runtimes read stderr as protocol data).
    """
    import logging

    teaparty_home = os.environ.get('TEAPARTY_HOME', '')
    if not teaparty_home:
        # Fall back: walk up from cwd looking for .teaparty/
        d = os.getcwd()
        while d != os.path.dirname(d):
            candidate = os.path.join(d, '.teaparty')
            if os.path.isdir(candidate):
                teaparty_home = candidate
                break
            d = os.path.dirname(d)

    if teaparty_home:
        log_dir = os.path.join(teaparty_home, 'logs')
        os.makedirs(log_dir, exist_ok=True)
        log_file = os.path.join(log_dir, 'mcp-server.log')
        logging.basicConfig(
            level=logging.DEBUG,
            format='%(asctime)s %(name)s %(levelname)s %(message)s',
            filename=log_file,
        )

    _mlog = logging.getLogger('orchestrator.mcp_server')
    _mlog.info(
        'main: SEND_SOCKET=%r AGENT_ID=%r CONTEXT_ID=%r',
        os.environ.get('SEND_SOCKET', ''),
        os.environ.get('AGENT_ID', ''),
        os.environ.get('CONTEXT_ID', ''),
    )
    server = create_server()
    _mlog.info('main: registered %d tools', len(server._tool_manager._tools))
    server.run(transport='stdio')


if __name__ == '__main__':
    main()
