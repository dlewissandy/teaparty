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
FlushFn = Callable[[str], Awaitable[None]]

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
    """
    if not question or not question.strip():
        raise ValueError('AskQuestion requires a non-empty question')

    if scratch_path:
        if flush_fn is None:
            flush_fn = _default_flush
        await flush_fn(scratch_path)
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
    """Default human input: communicate via the orchestrator socket."""
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


async def _default_flush(scratch_path: str) -> None:
    """Request the orchestrator to flush its current job state to the scratch file."""
    socket_path = os.environ.get('FLUSH_SOCKET', '')
    if not socket_path:
        return
    reader, writer = await asyncio.open_unix_connection(socket_path)
    try:
        request = json.dumps({'type': 'flush', 'scratch_path': scratch_path})
        writer.write(request.encode() + b'\n')
        await writer.drain()
        await reader.readline()
    finally:
        writer.close()
        await writer.wait_closed()
