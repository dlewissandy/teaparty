"""AskQuestion MCP server for agent escalation.

Replaces the file-based escalation mechanism (.intent-escalation.md,
stream-offset detection) with a proper tool the agent calls directly.

The agent calls AskQuestion(question, context).  The handler routes
through the proxy: confident → return proxy answer; not confident →
escalate to human, record the differential, return human's answer.

The MCP server communicates with the orchestrator via a Unix domain
socket whose path is passed in the ASK_QUESTION_SOCKET env var.
"""
from __future__ import annotations

import asyncio
import json
import os
from typing import Any, Awaitable, Callable

from mcp.server import FastMCP

# Type aliases for the pluggable functions
ProxyFn = Callable[[str, str], Awaitable[dict[str, Any]]]
HumanFn = Callable[[str], Awaitable[str]]
RecordDifferentialFn = Callable[[str, str, str, str], None]


async def ask_question_handler(
    question: str,
    context: str = '',
    *,
    proxy_fn: ProxyFn | None = None,
    human_fn: HumanFn | None = None,
    record_differential_fn: RecordDifferentialFn | None = None,
) -> str:
    """Core handler logic for AskQuestion.

    Routes through the proxy first.  If the proxy is confident, returns
    its answer directly.  Otherwise escalates to the human, records the
    differential (proxy prediction vs. human actual), and returns the
    human's answer.

    Args:
        question: The question the agent is asking.
        context: Optional context about what the agent is working on.
        proxy_fn: Async function that returns a dict with keys:
            confident (bool), answer (str), prediction (str).
        human_fn: Async function that takes a question and returns the
            human's answer.  Only called when proxy is not confident.
        record_differential_fn: Sync function to record the differential
            between proxy prediction and human actual.
    """
    if not question or not question.strip():
        raise ValueError('AskQuestion requires a non-empty question')

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


def create_server() -> FastMCP:
    """Create the MCP server with the AskQuestion tool registered."""
    server = FastMCP('teaparty-escalation')

    @server.tool()
    async def AskQuestion(question: str, context: str = '') -> str:
        """Ask a question that will be routed to the appropriate responder.

        Use this tool when you need clarification, have a question about
        intent, or need human input before proceeding.  The question will
        be answered — you do not need to write escalation files.

        Args:
            question: Your question. Be specific and concise.
            context: Optional context about what you're working on and
                why this question matters for your task.
        """
        return await ask_question_handler(question=question, context=context)

    return server


def main():
    """Run the MCP server on stdio."""
    server = create_server()
    server.run(transport='stdio')


if __name__ == '__main__':
    main()
