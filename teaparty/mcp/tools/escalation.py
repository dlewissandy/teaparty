"""AskQuestion handler — proxy routing and human escalation."""
from __future__ import annotations

import asyncio
import json
import os
from typing import Any, Awaitable, Callable

# Type aliases
ProxyFn = Callable[[str, str], Awaitable[dict[str, Any]]]
HumanFn = Callable[[str], Awaitable[str]]
RecordDifferentialFn = Callable[[str, str, str, str], None]

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
    """
    if not question or not question.strip():
        raise ValueError('AskQuestion requires a non-empty question')

    if scratch_path:
        question = _build_composite(question, _read_scratch(scratch_path))
        context = ''

    if proxy_fn is None:
        proxy_fn = _default_proxy
    proxy_result = await proxy_fn(question, context)

    confident = proxy_result.get('confident', False)
    prediction = proxy_result.get('prediction', '')
    answer = proxy_result.get('answer', '')

    if confident and answer:
        return answer

    if human_fn is None:
        human_fn = _default_human
    human_answer = await human_fn(question)

    if record_differential_fn is not None and prediction:
        record_differential_fn(prediction, human_answer, question, context)

    return human_answer


async def _default_proxy(question: str, context: str) -> dict[str, Any]:
    """Default proxy: always escalate (cold start)."""
    return {'confident': False, 'answer': '', 'prediction': ''}


async def _default_human(question: str) -> str:
    """Default human input: communicate via the orchestrator over the message bus.

    Posts an ``{"type":"ask_human","question":...}`` message from sender
    ``agent`` onto ``ASK_QUESTION_CONV_ID`` in the bus at ``ASK_QUESTION_BUS_DB``,
    then polls the same conversation for an ``{"answer":...}`` message from
    sender ``orchestrator`` and returns its ``answer`` field.
    """
    bus_db = os.environ.get('ASK_QUESTION_BUS_DB', '')
    conv_id = os.environ.get('ASK_QUESTION_CONV_ID', '')
    if not bus_db or not conv_id:
        raise RuntimeError(
            'ASK_QUESTION_BUS_DB / ASK_QUESTION_CONV_ID not set — '
            'cannot escalate to human'
        )

    # Import lazily so the MCP tool module doesn't pull in the whole
    # teaparty package at import time.
    from teaparty.messaging.conversations import SqliteMessageBus  # noqa: PLC0415

    import time as _time  # noqa: PLC0415

    bus = SqliteMessageBus(bus_db)
    since = _time.time()
    bus.send(conv_id, 'agent', json.dumps({
        'type': 'ask_human',
        'question': question,
    }))

    while True:
        messages = bus.receive(conv_id, since_timestamp=since)
        for msg in messages:
            if msg.sender == 'orchestrator':
                try:
                    payload = json.loads(msg.content)
                except json.JSONDecodeError:
                    return msg.content
                return payload.get('answer', '')
        await asyncio.sleep(0.1)


# ── Scratch file helpers ────────────────────────────────────────────────

def _read_scratch(scratch_path: str) -> str:
    """Read the scratch file, truncated to CONTEXT_BUDGET_LINES."""
    try:
        with open(scratch_path) as f:
            lines = f.readlines()
    except FileNotFoundError:
        return ''
    if len(lines) > CONTEXT_BUDGET_LINES:
        lines = lines[-CONTEXT_BUDGET_LINES:]
    return ''.join(lines)


def _build_composite(message: str, scratch: str) -> str:
    """Build the Task/Context composite envelope."""
    return f'## Task\n{message}\n\n## Context\n{scratch}'


def _scratch_path_from_env() -> str:
    """Resolve the scratch file path from TEAPARTY_WORKTREE env var."""
    worktree = os.environ.get('TEAPARTY_WORKTREE', os.getcwd())
    return os.path.join(worktree, '.context', 'scratch.md')


