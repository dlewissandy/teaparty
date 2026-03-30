"""MCP server for agent escalation, dispatch, and intervention tools.

The agent calls AskQuestion(question, context).  The handler routes
through the proxy: confident → return proxy answer; not confident →
escalate to human, record the differential, return human's answer.

The agent calls AskTeam(team, task) to dispatch work to a specialist
subteam.  The handler sends the request to the DispatchListener via
a Unix domain socket (ASK_TEAM_SOCKET env var) and returns the result.

The office manager calls WithdrawSession, PauseDispatch, ResumeDispatch,
or ReprioritizeDispatch to exercise team-lead authority.  These route
through the InterventionListener via INTERVENTION_SOCKET.

The MCP server communicates with the orchestrator via Unix domain
sockets whose paths are passed in the ASK_QUESTION_SOCKET,
ASK_TEAM_SOCKET, and INTERVENTION_SOCKET env vars.
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


async def ask_team_handler(team: str, task: str) -> str:
    """Core handler logic for AskTeam.

    Sends the dispatch request to the DispatchListener via the Unix socket
    at ASK_TEAM_SOCKET and returns the result JSON as a string.

    Args:
        team: The team to dispatch to (art, writing, editorial, research, coding).
        task: The task description for the subteam.
    """
    if not team or not team.strip():
        raise ValueError('AskTeam requires a non-empty team')
    if not task or not task.strip():
        raise ValueError('AskTeam requires a non-empty task')

    socket_path = os.environ.get('ASK_TEAM_SOCKET', '')
    if not socket_path:
        raise RuntimeError(
            'ASK_TEAM_SOCKET not set — cannot dispatch to team'
        )
    reader, writer = await asyncio.open_unix_connection(socket_path)
    try:
        request = json.dumps({'type': 'ask_team', 'team': team, 'task': task})
        writer.write(request.encode() + b'\n')
        await writer.drain()
        response_line = await reader.readline()
        response = json.loads(response_line.decode())
        return json.dumps(response)
    finally:
        writer.close()
        await writer.wait_closed()


def create_server() -> FastMCP:
    """Create the MCP server with the AskQuestion and AskTeam tools registered."""
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

    @server.tool()
    async def AskTeam(team: str, task: str) -> str:
        """Dispatch work to a specialist subteam and return the result.

        Use this tool to delegate a task to a subteam (art, writing,
        editorial, research, or coding).  The subteam runs a full CfA
        session and merges its deliverables into the shared worktree.

        Args:
            team: The team to dispatch to. One of: art, writing,
                editorial, research, coding.
            task: The specific task description for the subteam.
                Include relevant context, constraints, and success
                criteria so the team can work autonomously.
        """
        return await ask_team_handler(team=team, task=task)

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

    return server


def main():
    """Run the MCP server on stdio."""
    server = create_server()
    server.run(transport='stdio')


if __name__ == '__main__':
    main()
