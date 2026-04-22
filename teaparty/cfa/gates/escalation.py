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
import os
import re
import shutil
import time
import uuid
from typing import Any, Awaitable, Callable

from teaparty.messaging.bus import (
    Event, EventBus, EventType, InputRequest,
)
from teaparty.messaging.conversations import (
    ConversationType,
    SqliteMessageBus,
    make_conversation_id,
)
from teaparty.proxy.hooks import proxy_bus_path

_log = logging.getLogger('teaparty.cfa.gates.escalation')

# Type for the input provider (same as actors.InputProvider)
InputProvider = Callable[[InputRequest], Awaitable[str]]

# Type for the proxy invoker hook supplied by the bridge.
# Signature: async invoker(
#     qualifier: str, cwd: str,
#     teaparty_home: str = '', scope: str = 'management',
# ) -> None
ProxyInvoker = Callable[..., Awaitable[None]]

# Type for the dispatch-event hook used to surface the escalation as a
# child node in the accordion.  Matches bridge._broadcast_dispatch.
DispatchHook = Callable[[dict], Any]

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
        proxy_invoker_fn: ProxyInvoker | None = None,
        on_dispatch: DispatchHook | None = None,
        dispatcher_session: Any = None,
        teaparty_home: str = '',
        scope: str = 'management',
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
        # Issue #420: bridge-supplied hook that runs the proxy agent via the
        # `/escalation` skill.  When set, every AskQuestion routes through
        # the proxy; when None, the listener falls back to the legacy
        # consult_proxy path (retired in #421).
        self._proxy_invoker_fn = proxy_invoker_fn
        # Issue #420: dispatch-event hook so the escalation appears as a
        # child accordion node under the caller's session.
        self._on_dispatch = on_dispatch
        # Accordion wiring (issue #420 follow-up): the escalation must
        # appear as a real child session under the caller's dispatch
        # session so ``build_dispatch_tree`` can walk to it via the
        # caller's ``conversation_map``.  Required whenever
        # ``proxy_invoker_fn`` is set.
        self._dispatcher_session = dispatcher_session
        self._teaparty_home = teaparty_home
        self._scope = scope
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
            if self._proxy_invoker_fn is not None:
                answer = await self._route_through_escalation_skill(
                    question, context,
                )
            else:
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
        return await self.input_provider(InputRequest(
            type='agent_question',
            state='AGENT_QUESTION',
            artifact='',
            bridge_text=question,
        ))

    # ── Escalation-skill path (issue #420) ───────────────────────────────

    async def _route_through_escalation_skill(
        self, question: str, context: str,
    ) -> str:
        """Run one escalation through the proxy + `/escalation` skill.

        The escalation runs as a real proxy child session under the
        caller's dispatch session so the accordion renders it.  Without
        this the proxy dialog would open in a temp directory that the
        dispatch-tree walker could never reach — the human would see
        the question land in the bus but no chat blade to respond in.

        Flow:
          1. Create a proxy Session via the launcher's session
             machinery, with ``parent_session_id = dispatcher.id``.
          2. Write ``QUESTION.md`` into that session's directory.
          3. Record the session in the dispatcher's ``conversation_map``
             so ``build_dispatch_tree`` walks into it.
          4. Emit ``dispatch_started`` with real session IDs — the
             dashboard uses these as the accordion key.
          5. Seed the proxy conversation with ``/escalation`` so the
             skill loads on the first turn.
          6. Invoke the proxy with ``launch_cwd_override = session.path``
             so its cwd contains ``QUESTION.md``.
          7. Parse the skill's JSON output:
               RESPONSE  → return message as the answer.
               WITHDRAW  → return ``[WITHDRAW]\\n<reason>``.
               DIALOG    → wait for a human reply on the proxy bus,
                           then re-invoke.
          8. On termination, remove the session from the dispatcher's
             conversation map, emit ``dispatch_completed``, and rmtree
             the session directory.
        """
        if self._proxy_invoker_fn is None:
            raise RuntimeError(
                'escalation-skill path requires proxy_invoker_fn to be set'
            )
        if self._dispatcher_session is None or not self._teaparty_home:
            raise RuntimeError(
                'escalation-skill path requires dispatcher_session and '
                'teaparty_home so the accordion can render the escalation '
                'as a child of the caller'
            )

        from teaparty.runners.launcher import (
            create_session as _create_session,
            record_child_session as _record_child,
            remove_child_session as _remove_child,
            _save_session_metadata as _save_meta,
        )

        escalation_id = uuid.uuid4().hex
        qualifier = f'{self.session_id}:{escalation_id}'
        proxy_conv_id = make_conversation_id(
            ConversationType.PROXY, qualifier,
        )

        # The proxy AgentSession keys its on-disk session by
        # ``f"{agent_name}-{safe_qualifier}"``.  We pre-create that exact
        # session so the proxy invocation loads it (rather than creating
        # a sibling), and so parent_session_id survives the first
        # save_state().
        safe_qualifier = (
            qualifier.replace('/', '-').replace(':', '-').replace(' ', '-')
        )
        proxy_session_key = f'proxy-{safe_qualifier}'
        child_session = _create_session(
            agent_name='proxy',
            scope=self._scope,
            teaparty_home=self._teaparty_home,
            session_id=proxy_session_key,
        )
        child_session.parent_session_id = self._dispatcher_session.id
        child_session.launch_cwd = child_session.path
        child_session.initial_message = question
        _save_meta(child_session)

        # Write QUESTION.md into the session dir.  The proxy launches
        # with cwd = session.path, so the skill's ``Read ./QUESTION.md``
        # resolves here.
        question_md = os.path.join(child_session.path, 'QUESTION.md')
        body = question
        if context:
            body = f'{question}\n\n## Context\n\n{context}'
        with open(question_md, 'w') as fh:
            fh.write(body)

        # Link the child into the caller's conversation_map so
        # ``build_dispatch_tree`` walks into it.  Using escalation_id as
        # the request_id keeps multiple concurrent escalations distinct.
        _record_child(
            self._dispatcher_session,
            request_id=escalation_id,
            child_session_id=child_session.id,
        )

        # Emit dispatch_started so the dashboard animates the new blade.
        # Parent = dispatcher.id so the event agrees with the tree-walker
        # view (which reads parent_session_id off disk).
        self._emit_dispatch(
            'dispatch_started',
            parent_sid=self._dispatcher_session.id,
            child_sid=child_session.id,
        )

        # The proxy bus is where the accordion reads dialog messages from.
        proxy_bus = self._resolve_proxy_bus()

        # Register the conversation in the bus's conversations table so it
        # shows up in GET /api/conversations?type=proxy (which is how the
        # chat-list sidebar and some frontend paths discover
        # conversations).  Writing messages alone populates the messages
        # table but not the conversations table — the accordion iframe's
        # participant chat logic then sees a ``match``-less fetch and may
        # leave the UI in an unhydrated state.
        proxy_bus.create_conversation(ConversationType.PROXY, qualifier)

        # Seed the conversation with the /escalation slash command as the
        # initial "human" message.  Claude Code's skill dispatcher picks
        # this up on the proxy's first turn.
        proxy_bus.send(proxy_conv_id, 'human', '/escalation')

        # Take ownership of this proxy qualifier so the bridge's HTTP
        # handler stops auto-invoking the proxy while the escalation
        # loop is running.  Without this, every DIALOG reply the human
        # types into the accordion would fire two proxy invocations
        # (one from the HTTP handler, one from this loop's re-fire).
        from teaparty.mcp.registry import (
            mark_escalation_active as _mark_active,
            mark_escalation_done as _mark_done,
        )
        _mark_active(qualifier)

        final_answer = ''
        try:
            while True:
                # Capture the pre-invocation watermark so we can find the
                # proxy's reply produced by *this* turn.
                invocation_start = time.time()

                await self._proxy_invoker_fn(
                    qualifier=qualifier,
                    cwd=child_session.path,
                    teaparty_home=self._teaparty_home,
                    scope=self._scope,
                )

                # Pull the proxy's last turn output from the conversation.
                proxy_text = self._read_last_proxy_message(
                    proxy_bus, proxy_conv_id, since=invocation_start,
                )
                status, message = _parse_skill_output(proxy_text)

                if status == 'RESPONSE':
                    final_answer = message
                    break
                if status == 'WITHDRAW':
                    final_answer = f'[WITHDRAW]\n{message}'
                    break
                if status == 'DIALOG':
                    # Wait for a new human message on the proxy conversation
                    # before re-invoking.  The human replies through the
                    # accordion chat widget.
                    await self._wait_for_human_reply(
                        proxy_bus, proxy_conv_id, since=invocation_start,
                    )
                    continue
                # Status unrecognised — treat as a malformed turn and
                # return an empty answer.  The caller will surface this
                # as an escalation failure rather than silently retry.
                _log.error(
                    'Escalation skill emitted unrecognised status; '
                    'conv=%s text=%r',
                    proxy_conv_id, proxy_text[:200],
                )
                final_answer = ''
                break
        finally:
            _mark_done(qualifier)
            _remove_child(
                self._dispatcher_session, request_id=escalation_id,
            )
            self._emit_dispatch(
                'dispatch_completed',
                parent_sid=self._dispatcher_session.id,
                child_sid=child_session.id,
            )
            shutil.rmtree(child_session.path, ignore_errors=True)

        self._last_escalation_source = 'proxy_skill'
        return final_answer

    def _emit_dispatch(
        self, event_type: str, *, parent_sid: str, child_sid: str,
    ) -> None:
        """Fire a dispatch_started / dispatch_completed event.

        ``parent_sid``/``child_sid`` are real session IDs that match the
        on-disk metadata, so the dispatch-tree walker and the event
        stream agree.  No-op when the hook is not attached.
        """
        if self._on_dispatch is None:
            return
        try:
            self._on_dispatch({
                'type': event_type,
                'parent_session_id': parent_sid,
                'child_session_id': child_sid,
                'agent_name': 'proxy',
            })
        except Exception:
            _log.debug(
                'on_dispatch hook raised for %s', event_type, exc_info=True,
            )

    def _resolve_proxy_bus(self) -> SqliteMessageBus:
        """Open the proxy's message bus at its canonical location.

        ``infra_dir`` points at ``.teaparty/{scope}/agents/{agent}``.  The
        proxy bus lives at ``.teaparty/proxy/proxy-messages.db``.  We walk
        up to the ``.teaparty/`` root and resolve from there.
        """
        if not self.infra_dir:
            raise RuntimeError(
                'EscalationListener needs infra_dir to locate the proxy bus'
            )
        # .teaparty/{scope}/agents/{agent} → .teaparty/
        teaparty_home = os.path.dirname(
            os.path.dirname(os.path.dirname(self.infra_dir))
        )
        bus_path = proxy_bus_path(teaparty_home)
        os.makedirs(os.path.dirname(bus_path), exist_ok=True)
        return SqliteMessageBus(bus_path)

    def _read_last_proxy_message(
        self, bus: SqliteMessageBus, conv_id: str, since: float,
    ) -> str:
        """Return the content of the proxy's most recent message, or ''.

        Scans messages posted since ``since`` and returns the last one
        whose sender is ``proxy``.  The synthesized ``/escalation`` seed
        is a ``human`` message and never matches.
        """
        try:
            messages = bus.receive(conv_id, since_timestamp=since)
        except Exception:
            _log.debug('failed to read proxy bus %s', conv_id, exc_info=True)
            return ''
        for msg in reversed(messages):
            if msg.sender == 'proxy':
                return msg.content
        return ''

    async def _wait_for_human_reply(
        self,
        bus: SqliteMessageBus,
        conv_id: str,
        since: float,
        poll_interval: float = _POLL_INTERVAL,
    ) -> None:
        """Block until a sender='human' message appears since ``since``."""
        while True:
            try:
                messages = bus.receive(conv_id, since_timestamp=since)
            except Exception:
                messages = []
            for msg in messages:
                if msg.sender == 'human':
                    return
            await asyncio.sleep(poll_interval)


# ── Skill output parsing (DD6) ───────────────────────────────────────────

_STATUS_VALUES = ('DIALOG', 'RESPONSE', 'WITHDRAW')


def _parse_skill_output(text: str) -> tuple[str, str]:
    """Extract the outermost ``{"status": ..., "message": ...}`` object.

    Tolerates surrounding prose and nested JSON inside ``message``.  We
    walk the string locating each ``"status"`` key at the top level of a
    ``{...}`` block, balance braces to find the object's end, and attempt
    ``json.loads`` on the slice.  The last successfully-parsed object that
    carries a recognised status wins — per DD6 the skill's terminal turn
    is the one that matters when the model produces intermediate thinking
    that also contains a JSON-looking fragment.

    Returns ``(status, message)`` or ``('', '')`` if no object parses.
    """
    if not text:
        return '', ''

    results: list[tuple[str, str]] = []
    # Iterate over each '{' and try to parse from there as a JSON object.
    for start in (m.start() for m in re.finditer(r'\{', text)):
        obj = _extract_json_object(text, start)
        if obj is None:
            continue
        status = obj.get('status')
        message = obj.get('message')
        if (
            isinstance(status, str)
            and status in _STATUS_VALUES
            and isinstance(message, str)
        ):
            results.append((status, message))

    if not results:
        return '', ''
    # The skill's terminal turn is the last recognised object in the text.
    return results[-1]


def _extract_json_object(text: str, start: int) -> dict | None:
    """Return the dict parsed from the JSON object starting at ``text[start]``.

    Walks forward counting braces (respecting string literals and escapes)
    until the matching ``}``, then attempts ``json.loads`` on the slice.
    Returns None on any failure — malformed or non-object JSON.
    """
    if start >= len(text) or text[start] != '{':
        return None
    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_string:
            if escape:
                escape = False
            elif ch == '\\':
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
            continue
        if ch == '{':
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0:
                try:
                    obj = json.loads(text[start:i + 1])
                except (json.JSONDecodeError, ValueError):
                    return None
                return obj if isinstance(obj, dict) else None
    return None
