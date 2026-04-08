"""Intervention handlers — WithdrawSession, PauseDispatch, ResumeDispatch, ReprioritizeDispatch."""
from __future__ import annotations

import asyncio
import json
import os


async def intervention_handler(request_type: str, **kwargs) -> str:
    """Core handler for intervention tools.

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
        from teaparty.cfa.gates.intervention_listener import make_intervention_request
        request = json.dumps(make_intervention_request(request_type, **kwargs))
        writer.write(request.encode() + b'\n')
        await writer.drain()
        response_line = await reader.readline()
        response = json.loads(response_line.decode())
        return json.dumps(response)
    finally:
        writer.close()
        await writer.wait_closed()
