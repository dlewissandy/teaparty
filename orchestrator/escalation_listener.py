"""Unix socket listener for AskQuestion MCP tool IPC.

The orchestrator starts this listener before launching Claude Code.
The MCP server (running as a Claude Code subprocess) connects to
the socket and sends questions.  The listener routes through the
proxy and, if needed, the human input_provider.

Flow:
  1. Agent calls AskQuestion → MCP server connects to this socket
  2. Listener loads proxy model, calls generate_response for a prediction
  3. If proxy is confident → returns prediction directly (human never asked)
  4. If not confident → asks human via input_provider, records differential
  5. Returns the answer (proxy or human) to the MCP server → agent

Protocol (newline-delimited JSON over Unix socket):

  MCP server → listener:
    {"type": "ask_human", "question": "Who is the audience?"}

  listener → MCP server:
    {"answer": "Ages 5-8"}
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import tempfile
from typing import Awaitable, Callable

from orchestrator.events import (
    Event, EventBus, EventType, InputRequest,
)

_log = logging.getLogger('orchestrator.escalation')

# Type for the input provider (same as actors.InputProvider)
InputProvider = Callable[[InputRequest], Awaitable[str]]


class EscalationListener:
    """Unix socket server that bridges MCP AskQuestion to the proxy and human.

    The listener is the proxy's entry point for agent questions.  Every
    question goes through the proxy first:
    - Proxy always generates a predicted answer (even on cold start)
    - If confident → returns proxy answer, human never consulted
    - If not confident → asks human, records the differential
      (proxy prediction vs. human actual) for learning

    Lifecycle:
      listener = EscalationListener(event_bus, input_provider, ...)
      await listener.start()
      # ... run Claude Code with ASK_QUESTION_SOCKET=listener.socket_path ...
      await listener.stop()
    """

    def __init__(
        self,
        event_bus: EventBus,
        input_provider: InputProvider,
        session_id: str = '',
        proxy_model_path: str = '',
        project_slug: str = '',
        cfa_state: str = '',
        session_worktree: str = '',
        infra_dir: str = '',
        team: str = '',
    ):
        self.event_bus = event_bus
        self.input_provider = input_provider
        self.session_id = session_id
        self.proxy_model_path = proxy_model_path
        self.project_slug = project_slug
        self.cfa_state = cfa_state
        self.session_worktree = session_worktree
        self.infra_dir = infra_dir
        self.team = team
        self.socket_path = ''
        self._server: asyncio.AbstractServer | None = None

    async def start(self) -> str:
        """Start listening.  Returns the socket path."""
        sock_dir = tempfile.mkdtemp(prefix='teaparty-mcp-')
        self.socket_path = os.path.join(sock_dir, 'ask.sock')

        self._server = await asyncio.start_unix_server(
            self._handle_connection, path=self.socket_path,
        )
        _log.info('Escalation listener started at %s', self.socket_path)
        return self.socket_path

    async def stop(self) -> None:
        """Stop listening and clean up."""
        if self._server:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
        if self.socket_path:
            try:
                os.unlink(self.socket_path)
                os.rmdir(os.path.dirname(self.socket_path))
            except OSError:
                pass
            self.socket_path = ''

    async def _handle_connection(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        """Handle a single connection from the MCP server."""
        try:
            line = await reader.readline()
            if not line:
                return
            request = json.loads(line.decode())
            question = request.get('question', '')
            context = request.get('context', '')

            if not question:
                response = {'answer': ''}
            else:
                answer = await self._route_through_proxy(question, context)
                response = {'answer': answer}

            writer.write(json.dumps(response).encode() + b'\n')
            await writer.drain()
        except Exception:
            _log.exception('Error handling escalation connection')
            try:
                writer.write(json.dumps({'answer': ''}).encode() + b'\n')
                await writer.drain()
            except Exception:
                pass
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass

    async def _route_through_proxy(self, question: str, context: str = '') -> str:
        """Route a question through the proxy, escalating to human if needed.

        Uses the same proxy agent path as the approval gate — consult_proxy
        runs the statistical pre-filters, invokes the Claude agent if they
        pass, and returns (text, confidence).  If confident, the agent's text
        is the answer.  If not, the human is asked and the differential is
        recorded.
        """
        from orchestrator.proxy_agent import (
            consult_proxy, PROXY_AGENT_CONFIDENCE_THRESHOLD,
        )
        from scripts.approval_gate import (
            load_model,
            record_outcome,
            save_model,
        )

        proxy_result = await consult_proxy(
            question=question,
            state=self.cfa_state,
            project_slug=self.project_slug,
            proxy_model_path=self.proxy_model_path,
            session_worktree=self.session_worktree,
            infra_dir=self.infra_dir,
            team=self.team,
        )

        prediction = proxy_result.text
        confident = (
            proxy_result.from_agent
            and proxy_result.confidence >= PROXY_AGENT_CONFIDENCE_THRESHOLD
        )

        await self.event_bus.publish(Event(
            type=EventType.LOG,
            data={
                'category': 'ask_question_proxy',
                'question': question,
                'prediction': prediction[:200] if prediction else '',
                'confident': confident,
                'state': self.cfa_state,
            },
            session_id=self.session_id,
        ))

        # Confident → return proxy answer directly
        if confident and prediction:
            _log.info('Proxy answered question confidently: %s', question[:80])
            return prediction

        # Not confident → ask human
        human_answer = await self._ask_human(question)

        # Record the differential for learning
        if self.proxy_model_path:
            try:
                model = load_model(self.proxy_model_path)
                model = record_outcome(
                    model,
                    state=self.cfa_state,
                    task_type=self.project_slug,
                    outcome='clarify',
                    differential_summary=human_answer[:500],
                    differential_reasoning=question,
                    prediction=prediction or '(no prediction)',
                    predicted_response=prediction,
                )
                save_model(model, self.proxy_model_path)
                _log.info('Recorded escalation differential for %s', self.cfa_state)
            except Exception:
                _log.debug('Failed to record differential', exc_info=True)

        return human_answer

    async def _ask_human(self, question: str) -> str:
        """Surface a question to the human via the input_provider (TUI)."""
        await self.event_bus.publish(Event(
            type=EventType.INPUT_REQUESTED,
            data={
                'state': 'AGENT_QUESTION',
                'bridge_text': question,
            },
            session_id=self.session_id,
        ))

        response = await self.input_provider(InputRequest(
            type='agent_question',
            state='AGENT_QUESTION',
            artifact='',
            bridge_text=question,
        ))

        await self.event_bus.publish(Event(
            type=EventType.INPUT_RECEIVED,
            data={'response': response},
            session_id=self.session_id,
        ))

        return response
