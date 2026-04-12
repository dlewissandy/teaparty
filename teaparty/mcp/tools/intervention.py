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
    finally:
        writer.close()
        await writer.wait_closed()

    # Telemetry (Issue #405) — pause_all / resume_all / withdraw_clicked /
    # reprioritize_dispatch_clicked, depending on the request type.
    try:
        from teaparty import telemetry
        from teaparty.telemetry import events as _telem_events
        _type_map = {
            'pause_dispatch':         _telem_events.PAUSE_ALL,
            'resume_dispatch':        _telem_events.RESUME_ALL,
            'withdraw_session':       _telem_events.WITHDRAW_CLICKED,
            'reprioritize_dispatch':  _telem_events.REPRIORITIZE_DISPATCH_CLICKED,
        }
        et = _type_map.get(request_type)
        if et:
            telemetry.record_event(
                et,
                scope=kwargs.get('project_slug') or 'management',
                session_id=kwargs.get('session_id'),
                data={
                    'request_type': request_type,
                    'dispatch_id':  kwargs.get('dispatch_id'),
                    'priority':     kwargs.get('priority'),
                    'result_status': response.get('status') if isinstance(response, dict) else None,
                },
            )
    except Exception:
        pass

    return json.dumps(response)
