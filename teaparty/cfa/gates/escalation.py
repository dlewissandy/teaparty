"""Bus-backed listener for AskQuestion MCP tool IPC.

The orchestrator starts this listener before launching Claude Code.
The MCP server (running as a Claude Code subprocess) writes a question
message to the configured bus conversation; this listener polls the
same conversation, routes each question through the proxy and (if
needed) the human input_provider, and writes the answer back.

Flow:
  1. Agent calls AskQuestion → MCP server writes {"type":"ask_human", ...}
     to the bus with sender='agent'
  2. Listener picks it up, runs consult_proxy for a prediction
  3. If proxy is confident → returns prediction directly (human never asked)
  4. If not confident → asks human via input_provider, records differential
  5. Listener writes {"answer": ...} back with sender='orchestrator';
     MCP tool returns it to the agent.

Protocol (JSON in the ``content`` field of each bus message):

  agent → orchestrator:
    {"type": "ask_human", "question": "Who is the audience?"}

  orchestrator → agent:
    {"answer": "Ages 5-8"}
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Awaitable, Callable

from teaparty.messaging.bus import (
    Event, EventBus, EventType, InputRequest,
)
from teaparty.messaging.conversations import SqliteMessageBus

_log = logging.getLogger('teaparty.cfa.gates.escalation')

# Type for the input provider (same as actors.InputProvider)
InputProvider = Callable[[InputRequest], Awaitable[str]]

# How often the listener polls the bus for new agent messages.
_POLL_INTERVAL = 0.1


class EscalationListener:
    """Bus consumer that bridges MCP AskQuestion to the proxy and human.

    The listener is the proxy's entry point for agent questions.  Every
    question goes through the proxy first:
    - Proxy always generates a predicted answer (even on cold start)
    - If confident → returns proxy answer, human never consulted
    - If not confident → asks human, records the differential
      (proxy prediction vs. human actual) for learning

    Lifecycle:
      listener = EscalationListener(
          event_bus, input_provider,
          bus_db_path=..., conv_id='escalation:{session_id}',
      )
      await listener.start()
      # ... run Claude Code with
      #   ASK_QUESTION_BUS_DB=bus_db_path
      #   ASK_QUESTION_CONV_ID=conv_id
      await listener.stop()
    """

    def __init__(
        self,
        event_bus: EventBus | None,
        input_provider: InputProvider,
        bus_db_path: str,
        conv_id: str,
        session_id: str = '',
        proxy_model_path: str = '',
        project_slug: str = '',
        cfa_state: str = '',
        session_worktree: str = '',
        infra_dir: str = '',
        team: str = '',
        proxy_enabled: bool = True,
    ):
        self.event_bus = event_bus
        self.input_provider = input_provider
        self.bus_db_path = bus_db_path
        self.conv_id = conv_id
        self.session_id = session_id
        self.proxy_model_path = proxy_model_path
        self.project_slug = project_slug
        self.cfa_state = cfa_state
        self.session_worktree = session_worktree
        self.infra_dir = infra_dir
        self.team = team
        self.proxy_enabled = proxy_enabled
        self._task: asyncio.Task | None = None
        self._bus: SqliteMessageBus | None = None
        self._last_escalation_source: str = ''

        # Make the bridge-path degradation visible. When event_bus is None
        # the listener still runs, but gate/input LOG events silently drop.
        # That's a deliberate choice (the bridge doesn't own an EventBus
        # here), but we surface it once at construction so the gap is
        # observable rather than invisible.
        if event_bus is None:
            _log.warning(
                'EscalationListener constructed with event_bus=None — '
                'gate/input LOG events will not be published '
                '(telemetry via record_event still fires).'
            )

    async def start(self) -> None:
        """Open the bus and start the background polling task.

        ``since`` is captured here (not inside the task body) so messages
        written between create_task() and the task's first tick are not
        silently dropped.
        """
        self._bus = SqliteMessageBus(self.bus_db_path)
        since = time.time()
        self._task = asyncio.create_task(self._poll_loop(since))
        _log.info(
            'Escalation listener started on bus %s conv %s',
            self.bus_db_path, self.conv_id,
        )

    async def stop(self) -> None:
        """Cancel the polling task."""
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
            self._task = None
        self._bus = None

    async def _poll_loop(self, since: float) -> None:
        """Poll the bus for new 'agent' messages and handle each one.

        ``since`` is the initial watermark, captured by ``start()`` before
        the task was scheduled. This prevents dropping messages that arrive
        between create_task() and this coroutine's first execution.
        """
        while True:
            try:
                if self._bus is None:
                    return
                messages = self._bus.receive(self.conv_id, since_timestamp=since)
                for msg in messages:
                    # Advance watermark past every message we see so we
                    # don't re-process them — including our own replies.
                    since = max(since, msg.timestamp)
                    if msg.sender != 'agent':
                        continue
                    await self._handle_message(msg.content)
            except asyncio.CancelledError:
                raise
            except Exception:
                _log.exception('Error polling bus for escalation messages')
            await asyncio.sleep(_POLL_INTERVAL)

    async def _handle_message(self, raw_content: str) -> None:
        """Parse one agent message, route it, write the reply back to the bus."""
        try:
            request = json.loads(raw_content)
        except json.JSONDecodeError:
            _log.warning('Escalation message is not JSON: %r', raw_content[:120])
            return

        question = request.get('question', '')
        context = request.get('context', '')

        if not question:
            self._send_reply({'answer': ''})
            return

        # Telemetry: escalation_requested (Issue #405)
        try:
            from teaparty.telemetry import record_event
            from teaparty.telemetry import events as _telem_events
            record_event(
                _telem_events.ESCALATION_REQUESTED,
                scope=self.project_slug or 'management',
                session_id=self.session_id,
                data={
                    'source': 'ask_question_tool',
                    'question_len': len(question),
                    'initiating_session_id': self.session_id,
                },
            )
        except Exception:
            pass

        try:
            answer = await self._route_through_proxy(question, context)
        except Exception:
            _log.exception('Error routing escalation through proxy')
            answer = ''

        self._send_reply({'answer': answer})

        # Telemetry: escalation_resolved (Issue #405)
        try:
            from teaparty.telemetry import record_event
            from teaparty.telemetry import events as _telem_events
            record_event(
                _telem_events.ESCALATION_RESOLVED,
                scope=self.project_slug or 'management',
                session_id=self.session_id,
                data={
                    'final_answer_source': self._last_escalation_source,
                    'total_latency_ms': 0,
                },
            )
        except Exception:
            pass

    def _send_reply(self, payload: dict) -> None:
        """Post the orchestrator's reply back onto the bus."""
        if self._bus is None:
            return
        self._bus.send(self.conv_id, 'orchestrator', json.dumps(payload))

    async def _publish_event(self, event: Event) -> None:
        """Publish a LOG/INPUT event if an EventBus is attached, else no-op.

        The CfA-engine path attaches a real EventBus so phase logs flow.
        The bridge/teams path has no EventBus — the listener still runs
        but its log/input-event publishes silently drop.
        """
        if self.event_bus is None:
            return
        await self.event_bus.publish(event)

    async def _route_through_proxy(self, question: str, context: str = '') -> str:
        """Route a question through the proxy, escalating to human if needed.

        Uses the same proxy agent path as the approval gate — consult_proxy
        runs the statistical pre-filters, invokes the Claude agent if they
        pass, and returns (text, confidence).  If confident, the agent's text
        is the answer.  If not, the human is asked and the differential is
        recorded.

        When ``self.proxy_enabled`` is False, skip the proxy entirely and
        go straight to the human — the proxy path is only useful when there
        is a real proxy_model_path / cfa_state / project_slug to feed it.
        """
        if not self.proxy_enabled:
            self._last_escalation_source = 'human'
            return await self._ask_human(question)

        from teaparty.proxy.agent import (
            consult_proxy, PROXY_AGENT_CONFIDENCE_THRESHOLD,
        )
        from teaparty.proxy.approval_gate import (
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

        await self._publish_event(Event(
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

        # Telemetry: proxy_considered (Issue #405)
        try:
            from teaparty.telemetry import record_event
            from teaparty.telemetry import events as _telem_events
            record_event(
                _telem_events.PROXY_CONSIDERED,
                scope=self.project_slug or 'management',
                session_id=self.session_id,
                data={'proxy_name': 'proxy', 'wait_ms': 0},
            )
        except Exception:
            pass

        # Confident → return proxy answer directly
        if confident and prediction:
            _log.info('Proxy answered question confidently: %s', question[:80])
            self._last_escalation_source = 'proxy'
            # Telemetry: proxy_answered (Issue #405)
            try:
                record_event(
                    _telem_events.PROXY_ANSWERED,
                    scope=self.project_slug or 'management',
                    session_id=self.session_id,
                    data={
                        'proxy_name': 'proxy',
                        'response_len': len(prediction),
                    },
                )
            except Exception:
                pass
            return prediction

        # Not confident → ask human
        # Telemetry: proxy_escalated_to_human (Issue #405)
        try:
            record_event(
                _telem_events.PROXY_ESCALATED_TO_HUMAN,
                scope=self.project_slug or 'management',
                session_id=self.session_id,
                data={
                    'proxy_name': 'proxy',
                    'reason_for_escalation': 'not_confident',
                },
            )
        except Exception:
            pass
        human_answer = await self._ask_human(question)
        self._last_escalation_source = 'human'
        # Telemetry: human_answered (Issue #405)
        try:
            record_event(
                _telem_events.HUMAN_ANSWERED,
                scope=self.project_slug or 'management',
                session_id=self.session_id,
                data={'response_len': len(human_answer)},
            )
        except Exception:
            pass

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
        """Surface a question to the human via the input_provider."""
        await self._publish_event(Event(
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

        await self._publish_event(Event(
            type=EventType.INPUT_RECEIVED,
            data={'response': response},
            session_id=self.session_id,
        ))

        return response
