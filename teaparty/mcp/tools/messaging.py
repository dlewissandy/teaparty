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


async def send_handler(
    member: str,
    message: str,
    context_id: str = '',
    *,
    scratch_path: str = '',
    post_fn: SendPostFn | None = None,
) -> str:
    """Core handler logic for Send.

    Thread continuation (``context_id='dispatch:<sid>'``) is handled
    entirely by the tier's ``spawn_fn`` — it consults the bus for
    any open dispatch with the caller and the recipient, and when
    one exists re-launches that child with ``--resume``.  There is
    no separate session-lookup or history-inject step at this layer;
    those were bits of the old SessionRegistry path (dead code, never
    populated) that silently fell through to ``spawn_fn`` anyway.
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

    The MCP server runs in the same process as the bridge.  Each launched
    agent's spawn_fn is installed in the in-process registry by
    ``launch()`` (via ``MCPRoutes`` — issue #422), keyed by agent name,
    with the current agent name supplied per-request via contextvars.

    Before invoking ``spawn_fn`` we authorize the post against the
    session's ``BusDispatcher`` (also installed by ``launch()`` via the
    same ``MCPRoutes`` bundle).  Authorization is the single transport-
    level enforcement point: an agent whose prompt is broken or hostile
    cannot reach a recipient outside its permitted set.  When no
    dispatcher is registered (bootstrap, scripted tests, projects
    without YAML) we fall through with no enforcement — same default as
    pre-#422.
    """
    import time as _time
    import logging as _logging
    _send_log = _logging.getLogger('teaparty.mcp.tools.messaging.send')

    from teaparty.mcp.registry import (
        get_spawn_fn, get_dispatcher, current_agent_name,
    )
    from teaparty.messaging.dispatcher import RoutingError

    spawn_fn = get_spawn_fn()
    if spawn_fn is None:
        raise RuntimeError(
            'No spawn_fn in registry — launch() did not install MCPRoutes '
            'for this agent.',
        )

    # Routing authorization.  When the session registered a dispatcher
    # we enforce; otherwise (bootstrap / scripted tests) we let the post
    # through.  Routing tables key directly on agent names — same
    # identifiers used everywhere else.  No translation map.
    dispatcher = get_dispatcher()
    if dispatcher is not None:
        sender = current_agent_name.get('')
        try:
            dispatcher.authorize(sender, member)
        except RoutingError as exc:
            _send_log.warning(
                'send_registry: %r → %r refused by dispatcher: %s',
                sender, member, exc,
            )
            return json.dumps({
                'status': 'failed',
                'reason': (
                    f'Routing refused: {sender!r} cannot post to '
                    f'{member!r}.  Cross-workgroup posts must go '
                    f'through your project lead; cross-project posts '
                    f'must go through the OM.'
                ),
            })

    t0 = _time.monotonic()
    try:
        session_id, worktree, result_text = await spawn_fn(
            member, composite, context_id)
    except Exception as exc:
        _send_log.warning('send_registry failed for %r: %s', member, exc)
        return json.dumps({'status': 'error', 'reason': str(exc)})

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
        'message': (
            f'Dispatched to {member!r}.  '
            f'The child has its own worktree on branch '
            f'``session/{session_id}``; nothing it writes is visible in '
            f'your worktree until you call CloseConversation.\n'
            f'\n'
            f'To continue this thread: call Send again with '
            f'``context_id={conv_id!r}`` — the handle stays valid '
            f'(the child is re-entered, not recreated) until you close it.\n'
            f'\n'
            f'When you judge the work acceptable: '
            f'CloseConversation(conversation_id={conv_id!r}).  '
            f'That squash-merges the child into your branch and ends '
            f'the thread.  Leaving it open strands the work — '
            f'uncommitted, unmerged, waiting on you.\n'
            f'\n'
            f'Before your phase can approve, every dispatch you '
            f'opened must be closed.'
        ),
    })


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
