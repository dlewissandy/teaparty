"""Send and CloseConversation handlers."""
from __future__ import annotations

import asyncio
import json
import os
from typing import Awaitable, Callable

from teaparty.mcp.tools.escalation import (
    _build_composite,
    _read_scratch,
    _scratch_path_from_env,
)

SendPostFn = Callable[[str, str, str], Awaitable[str]]
CloseConvPostFn = Callable[[str], Awaitable[str]]
InjectFn = Callable[[str, str, str, str], Awaitable[None]]
SessionLookupFn = Callable[[str, str], tuple[str, str, str] | None]


def _default_session_lookup(member: str, context_id: str) -> tuple[str, str, str] | None:
    """Look up session info for (member, context_id) from SESSION_REGISTRY_PATH."""
    from teaparty.messaging.conversations import SessionRegistry
    registry_path = os.environ.get('SESSION_REGISTRY_PATH', '')
    if not registry_path:
        return None
    return SessionRegistry(registry_path).lookup(member, context_id)


async def _default_inject(
    session_file: str, composite: str, session_id: str, cwd: str,
) -> None:
    """Inject composite into the recipient's JSONL conversation history."""
    from teaparty.messaging.conversations import inject_composite_into_history
    inject_composite_into_history(session_file, composite, session_id, cwd)


async def send_handler(
    member: str,
    message: str,
    context_id: str = '',
    *,
    scratch_path: str = '',
    post_fn: SendPostFn | None = None,
    session_lookup_fn: SessionLookupFn | None = None,
    inject_fn: InjectFn | None = None,
) -> str:
    """Core handler logic for Send."""
    if not member or not member.strip():
        raise ValueError('Send requires a non-empty member')
    if not message or not message.strip():
        raise ValueError('Send requires a non-empty message')

    resolved = scratch_path or _scratch_path_from_env()
    scratch = _read_scratch(resolved)
    composite = _build_composite(message, scratch)

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


def _spawn_refusal_reason(reason_code: str, member: str) -> str:
    """Translate spawn_fn's refusal reason into agent-facing text.

    spawn_fn returns ``('', '', reason)`` when it declines to dispatch.
    The reason codes are emitted by the chat-tier spawn_fn in
    ``teaparty/teams/session.py``:

    - ``slot_limit``         — dispatcher already has MAX open children
    - ``paused``             — project is paused; new dispatches refused
    - ``unresolved_member:…``— member not in any roster
    - ``worktree_failed``    — git worktree add failed for same-repo dispatch

    Unrecognized or empty reasons fall back to a generic refusal
    message; agents shouldn't see that in practice.
    """
    if reason_code == 'slot_limit':
        return (
            'You already have three open conversations. '
            'Wait for them to complete or use CloseConversation.'
        )
    if reason_code == 'paused':
        return (
            'The project is paused; new dispatches are refused '
            'until it resumes.'
        )
    if reason_code.startswith('unresolved_member:'):
        name = reason_code.split(':', 1)[1] or member
        return (
            f'{name!r} is not registered in any team or workgroup. '
            f'Check with ListTeamMembers or ListWorkgroups before '
            f'sending.'
        )
    if reason_code == 'worktree_failed':
        return (
            f'Could not create a worktree for {member!r}. '
            f'See the bridge log for the git error.'
        )
    return f'Dispatch to {member!r} was refused.'


async def _default_send_post(member: str, composite: str, context_id: str) -> str:
    """Default Send transport: direct call to bus listener via registry.

    The MCP server runs in the same process as the bridge. The bus
    listener's spawn_fn is registered in the registry, keyed by agent
    name. The current agent name is set per-request via contextvars.

    Falls back to the dispatch bus (DISPATCH_BUS_PATH / DISPATCH_CONV_ID)
    for paths that run the MCP server as a separate subprocess.
    """
    import time as _time
    import logging as _logging
    _send_log = _logging.getLogger('teaparty.mcp.tools.messaging.send')

    # Try the in-process registry first (bridge path)
    from teaparty.mcp.registry import get_spawn_fn
    spawn_fn = get_spawn_fn()
    if spawn_fn is not None:
        t0 = _time.monotonic()
        try:
            session_id, worktree, result_text = await spawn_fn(member, composite, context_id)
            if not session_id:
                # spawn_fn reports why it refused in the third slot. Surface
                # that reason to the agent faithfully — reporting every
                # failure as "slot limit" hides roster errors and pause
                # state behind a message that suggests the fix is to
                # close a conversation.
                reason = _spawn_refusal_reason(result_text, member)
                _send_log.warning(
                    'send_registry: member=%r refused (%s)',
                    member, result_text or 'unknown')
                return json.dumps({'status': 'failed', 'reason': reason})
            conv_id = f'dispatch:{session_id}'
            _send_log.info('send_registry: member=%r conv=%s elapsed=%.2fs',
                           member, conv_id, _time.monotonic() - t0)
            return json.dumps({
                'status': 'message_sent',
                'conversation_id': conv_id,
                'message': 'Any changes the recipient makes to the codebase '
                           'will not take effect until you close this '
                           'conversation. When the work is complete and you '
                           'are satisfied with the result, use '
                           'CloseConversation to merge their changes.',
            })
        except Exception as exc:
            _send_log.warning('send_registry failed for %r: %s', member, exc)
            return json.dumps({'status': 'error', 'reason': str(exc)})

    # Fallback: dispatch bus (CfA engine path).  The engine's dispatch
    # poller consumes agent-sender 'send' messages and writes back with
    # sender 'orchestrator'.
    bus_path = os.environ.get('DISPATCH_BUS_PATH', '')
    dispatch_conv = os.environ.get('DISPATCH_CONV_ID', '')
    if not bus_path or not dispatch_conv:
        raise RuntimeError(
            'No spawn_fn in registry and DISPATCH_BUS_PATH/DISPATCH_CONV_ID '
            'not set — cannot send',
        )

    from teaparty.messaging.conversations import SqliteMessageBus
    import uuid as _uuid
    bus = SqliteMessageBus(bus_path)
    request_id = _uuid.uuid4().hex
    t0 = _time.monotonic()
    since = _time.time()
    bus.send(dispatch_conv, 'agent', json.dumps({
        'type': 'send',
        'member': member,
        'composite': composite,
        'context_id': context_id,
        'request_id': request_id,
    }))

    while True:
        messages = bus.receive(dispatch_conv, since_timestamp=since)
        for msg in messages:
            if msg.sender != 'orchestrator':
                continue
            try:
                resp = json.loads(msg.content)
            except (json.JSONDecodeError, ValueError):
                continue
            if resp.get('request_id') == request_id:
                _send_log.info('send_bus: member=%r total=%.2fs',
                               member, _time.monotonic() - t0)
                return json.dumps(resp)
        await asyncio.sleep(0.1)


async def close_conversation_handler(
    context_id: str,
    *,
    post_fn: CloseConvPostFn | None = None,
) -> str:
    """Core handler logic for CloseConversation."""
    if not context_id or not context_id.strip():
        raise ValueError('CloseConversation requires a non-empty context_id')

    if post_fn is None:
        post_fn = _default_close_conv_post
    return await post_fn(context_id)


async def _default_close_conv_post(context_id: str) -> str:
    """Default CloseConversation transport.

    For ``dispatch:`` conversations, uses the in-process close_fn
    registry.  Falls back to the dispatch bus (DISPATCH_BUS_PATH /
    DISPATCH_CONV_ID) for paths that run the MCP server as a separate
    subprocess.
    """
    import logging as _logging
    _close_log = _logging.getLogger('teaparty.mcp.tools.messaging.close')

    # Dispatch conversations: route through in-process registry.
    # Only the agent that initiated the dispatch may close it.
    if context_id.startswith('dispatch:'):
        from teaparty.mcp.registry import get_close_fn
        close_fn = get_close_fn()
        if close_fn is None:
            return json.dumps({
                'status': 'failed',
                'conversation_id': context_id,
                'message': 'You cannot close that conversation. '
                           'You did not initiate it.',
            })
        if close_fn is not None:
            try:
                fn_result = await close_fn(context_id)
                _close_log.info('close_registry: conv=%s', context_id)
            except Exception as exc:
                _close_log.warning('close_registry failed: %s', exc)
                return json.dumps({'status': 'error', 'reason': str(exc)})

            # close_fn may return a structured merge result when a
            # subchat's worktree fails to merge back into its parent.
            # Surface the status + message to the calling agent so it
            # can resolve the conflict via git and retry.
            if isinstance(fn_result, dict):
                status = fn_result.get('status', 'closed')
                if status == 'ok':
                    return json.dumps({
                        'status': 'closed',
                        'conversation_id': context_id,
                        'message': fn_result.get('message', ''),
                    })
                if status == 'noop':
                    return json.dumps({
                        'status': 'closed',
                        'conversation_id': context_id,
                    })
                return json.dumps({
                    'status': status,
                    'conversation_id': context_id,
                    'message': fn_result.get('message', ''),
                    'conflicts': fn_result.get('conflicts', []),
                    'worktree_path': fn_result.get('worktree_path', ''),
                    'target_worktree': fn_result.get('target_worktree', ''),
                    'target_branch': fn_result.get('target_branch', ''),
                })
            return json.dumps({
                'status': 'closed',
                'conversation_id': context_id,
            })

    # Both chat tier and CfA now register close_fn in the in-process
    # registry (#422), so the dispatch-bus fallback is unreachable for
    # any dispatch: conversation.  The only way to get here is a
    # non-dispatch context_id, which is a bug in the caller.
    raise RuntimeError(
        f'No close_fn in registry for context_id={context_id!r} — '
        'caller did not initiate this conversation.',
    )
