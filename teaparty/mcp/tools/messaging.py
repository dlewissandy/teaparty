"""Send, Reply, and CloseConversation handlers."""
from __future__ import annotations

import asyncio
import json
import os
from typing import Awaitable, Callable

from teaparty.mcp.tools.escalation import (
    _build_composite,
    _default_flush,
    _read_scratch,
    _scratch_path_from_env,
    FlushFn,
)

SendPostFn = Callable[[str, str, str], Awaitable[str]]
ReplyPostFn = Callable[[str], Awaitable[str]]
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
    flush_fn: FlushFn | None = None,
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

    if flush_fn is None:
        flush_fn = _default_flush
    await flush_fn(resolved)

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


async def _default_send_post(member: str, composite: str, context_id: str) -> str:
    """Default Send transport: bus message or SEND_SOCKET fallback."""
    import time as _time
    import logging as _logging
    _send_log = _logging.getLogger('teaparty.mcp.tools.messaging.send')

    bus_path = os.environ.get('DISPATCH_BUS_PATH', '')
    dispatch_conv = os.environ.get('DISPATCH_CONV_ID', '')

    if bus_path and dispatch_conv:
        from teaparty.messaging.conversations import SqliteMessageBus
        t0 = _time.monotonic()
        bus = SqliteMessageBus(bus_path)
        request_id = str(__import__('uuid').uuid4())
        request = json.dumps({
            'type': 'send', 'member': member,
            'composite': composite, 'context_id': context_id,
            'request_id': request_id,
        })
        bus.send(dispatch_conv, 'agent', request)

        since = _time.time()
        while True:
            messages = bus.receive(dispatch_conv, since_timestamp=since)
            for msg in messages:
                if msg.sender == 'orchestrator':
                    try:
                        resp = json.loads(msg.content)
                        if resp.get('request_id') == request_id:
                            _send_log.info(
                                'send_post_bus: member=%r total=%.2fs',
                                member, _time.monotonic() - t0,
                            )
                            return json.dumps(resp)
                    except (json.JSONDecodeError, ValueError):
                        pass
            await asyncio.sleep(0.1)

    socket_path = os.environ.get('SEND_SOCKET', '')
    if not socket_path:
        raise RuntimeError(
            'Neither DISPATCH_BUS_PATH nor SEND_SOCKET set — cannot send',
        )

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
    """Core handler logic for Reply."""
    if not message or not message.strip():
        raise ValueError('Reply requires a non-empty message')

    if post_fn is None:
        post_fn = _default_reply_post
    return await post_fn(message)


async def _default_reply_post(message: str) -> str:
    """Default Reply transport: bus message or REPLY_SOCKET fallback."""
    bus_path = os.environ.get('DISPATCH_BUS_PATH', '')
    dispatch_conv = os.environ.get('DISPATCH_CONV_ID', '')

    if bus_path and dispatch_conv:
        from teaparty.messaging.conversations import SqliteMessageBus
        bus = SqliteMessageBus(bus_path)
        context_id = os.environ.get('CONTEXT_ID', '')
        request_id = str(__import__('uuid').uuid4())
        request = json.dumps({
            'type': 'reply', 'message': message,
            'context_id': context_id,
            'request_id': request_id,
        })
        bus.send(dispatch_conv, 'agent', request)

        import time as _time
        since = _time.time()
        while True:
            messages = bus.receive(dispatch_conv, since_timestamp=since)
            for msg in messages:
                if msg.sender == 'orchestrator':
                    try:
                        resp = json.loads(msg.content)
                        if resp.get('request_id') == request_id:
                            return json.dumps(resp)
                    except (json.JSONDecodeError, ValueError):
                        pass
            await asyncio.sleep(0.1)

    socket_path = os.environ.get('REPLY_SOCKET', '')
    if not socket_path:
        raise RuntimeError(
            'Neither DISPATCH_BUS_PATH nor REPLY_SOCKET set — cannot reply',
        )
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
    """Default CloseConversation transport: bus or CLOSE_CONV_SOCKET fallback."""
    bus_path = os.environ.get('DISPATCH_BUS_PATH', '')
    dispatch_conv = os.environ.get('DISPATCH_CONV_ID', '')

    if bus_path and dispatch_conv:
        from teaparty.messaging.conversations import SqliteMessageBus
        bus = SqliteMessageBus(bus_path)
        request_id = str(__import__('uuid').uuid4())
        request = json.dumps({
            'type': 'close_conversation',
            'context_id': context_id,
            'request_id': request_id,
        })
        bus.send(dispatch_conv, 'agent', request)

        import time as _time
        since = _time.time()
        while True:
            messages = bus.receive(dispatch_conv, since_timestamp=since)
            for msg in messages:
                if msg.sender == 'orchestrator':
                    try:
                        resp = json.loads(msg.content)
                        if resp.get('request_id') == request_id:
                            return json.dumps(resp)
                    except (json.JSONDecodeError, ValueError):
                        pass
            await asyncio.sleep(0.1)

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
