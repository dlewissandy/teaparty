"""Intervention handlers — WithdrawSession, PauseDispatch, ResumeDispatch, ReprioritizeDispatch."""
from __future__ import annotations

import asyncio
import json
import os


async def intervention_handler(request_type: str, **kwargs) -> str:
    """Core handler for intervention tools.

    Posts the request to the orchestrator over the message bus, then
    polls the same conversation for the reply.  Env vars
    ``INTERVENTION_BUS_DB`` + ``INTERVENTION_CONV_ID`` tell the tool
    which bus/conversation to use; they are set by the orchestrator
    before launching Claude Code.

    Args:
        request_type: One of withdraw_session, pause_dispatch,
            resume_dispatch, reprioritize_dispatch.
        **kwargs: Additional fields for the request (session_id,
            dispatch_id, priority).
    """
    bus_db = os.environ.get('INTERVENTION_BUS_DB', '')
    conv_id = os.environ.get('INTERVENTION_CONV_ID', '')
    if not bus_db or not conv_id:
        raise RuntimeError(
            'INTERVENTION_BUS_DB / INTERVENTION_CONV_ID not set — '
            'cannot execute intervention'
        )

    # Import lazily so the MCP tool module doesn't pull in the whole
    # teaparty package at import time.
    from teaparty.cfa.gates.intervention_listener import make_intervention_request
    from teaparty.messaging.conversations import SqliteMessageBus
    import time as _time

    bus = SqliteMessageBus(bus_db)
    since = _time.time()
    bus.send(conv_id, 'agent', json.dumps(make_intervention_request(
        request_type, **kwargs,
    )))

    response: dict | None = None
    while response is None:
        messages = bus.receive(conv_id, since_timestamp=since)
        for msg in messages:
            if msg.sender == 'orchestrator':
                try:
                    response = json.loads(msg.content)
                except json.JSONDecodeError:
                    response = {'status': 'error', 'reason': 'malformed reply'}
                break
        if response is None:
            await asyncio.sleep(0.1)

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
