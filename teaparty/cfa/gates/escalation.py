"""Bus-backed listener for AskQuestion MCP tool IPC.

The orchestrator starts this listener before launching Claude Code.
The MCP server (running as a Claude Code subprocess) writes a question
message to the configured bus conversation; this listener polls the
same conversation, invokes the proxy running the `/escalation` skill,
and writes the answer back.

One codepath — chat-tier AgentSession and CfA Orchestrator both go
through ``_route_through_escalation_skill``.  The listener requires a
``proxy_invoker_fn`` (bridge's ``_invoke_proxy``) and a
``dispatcher_session`` (launcher.Session) so each escalation becomes a
real proxy child session under the caller, renderable as an accordion
blade.

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
    EventBus, InputRequest,
)
from teaparty.messaging.conversations import (
    ConversationType,
    SqliteMessageBus,
    make_conversation_id,
)
from teaparty.proxy.hooks import proxy_bus_path

_log = logging.getLogger('teaparty.cfa.gates.escalation')

# Type for the input provider (same as actors.InputProvider).
# Retained for constructor compat with existing callers; unused by the
# skill path.
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
        input_provider: InputProvider | None,
        bus_db_path: str,
        conv_id: str,
        session_id: str = '',
        proxy_model_path: str = '',
        project_slug: str = '',
        cfa_state: str = '',
        session_worktree: str = '',
        infra_dir: str = '',
        team: str = '',
        proxy_invoker_fn: ProxyInvoker | None = None,
        on_dispatch: DispatchHook | None = None,
        dispatcher_session: Any = None,
        teaparty_home: str = '',
        scope: str = 'management',
    ):
        self.event_bus = event_bus
        self.input_provider = input_provider  # unused; kept for compat
        self.bus_db_path = bus_db_path
        self.conv_id = conv_id
        self.session_id = session_id
        self.proxy_model_path = proxy_model_path
        self.project_slug = project_slug
        self.cfa_state = cfa_state
        self.session_worktree = session_worktree
        self.infra_dir = infra_dir
        self.team = team
        # Bridge-supplied hook that runs the proxy agent via the
        # ``/escalation`` skill.  Required — the legacy consult_proxy
        # fallback is gone.  The only route for AskQuestion is the
        # proxy skill path (#420, chat-tier and CfA unified).
        self._proxy_invoker_fn = proxy_invoker_fn
        # Dispatch-event hook so the escalation appears as a child
        # accordion node under the caller's session.
        self._on_dispatch = on_dispatch
        # The escalation must appear as a real child session under the
        # caller's dispatch session so ``build_dispatch_tree`` can walk
        # to it via the caller's ``conversation_map``.  Required
        # whenever ``proxy_invoker_fn`` is set.
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
        self._rehydrate_active_escalations()
        since = time.time()
        self._task = asyncio.create_task(self._poll_loop(since))
        _log.info(
            'Escalation listener started on bus %s conv %s',
            self.bus_db_path, self.conv_id,
        )

    def _rehydrate_active_escalations(self) -> None:
        """Re-register in-flight escalations from the dispatcher's
        conversation_map.

        The ``_active_escalations`` registry is in-memory and is lost
        across bridge restarts, but the escalation's on-disk state
        (proxy session dir, dispatcher's conversation_map entry) is
        preserved on cancellation — so the next listener startup can
        repopulate the registry by scanning what's already there.
        Without this, the workflow-bar dot and the
        ``is_escalation_active`` guard in the bridge's HTTP auto-invoke
        would be blank for escalations that survived a restart.
        """
        if self._dispatcher_session is None:
            return
        from teaparty.mcp.registry import mark_escalation_active as _mark
        conv_map = getattr(self._dispatcher_session, 'conversation_map', {}) or {}
        for request_id, child_session_id in conv_map.items():
            if not isinstance(child_session_id, str):
                continue
            if not child_session_id.startswith('proxy-'):
                continue
            qualifier = f'{self._dispatcher_session.id}:{request_id}'
            _mark(qualifier)

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
            answer = await self._route_through_escalation_skill(
                question, context,
            )
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

        # Write ``conversation_id`` into metadata.json upfront so
        # build_dispatch_tree returns the real proxy conversation id from
        # the first fetch.  Without this, the tree walker falls back to
        # ``dispatch:{session_id}`` (an id with no messages on any bus)
        # and the accordion iframe renders that stale URL — it fetches 0
        # messages and never re-fetches even after the proxy's
        # AgentSession.save_state() later writes the real conversation_id
        # to disk.  ``Session`` has no conversation_id field, so this is
        # a read-modify-write on the JSON; launcher.save_state and
        # AgentSession.save_state both preserve fields they don't own.
        _meta_path = os.path.join(child_session.path, 'metadata.json')
        with open(_meta_path) as fh:
            _meta = json.load(fh)
        _meta['conversation_id'] = proxy_conv_id
        _tmp = _meta_path + '.tmp'
        with open(_tmp, 'w') as fh:
            json.dump(_meta, fh, indent=2)
        os.replace(_tmp, _meta_path)

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

        # Post the question as a message from the requesting agent so the
        # accordion iframe shows *what the teammate actually asked*, not
        # just the ``/escalation`` slash command.  proxy_build_prompt
        # preserves the sender name for non-human / non-proxy messages,
        # so Claude reads this as a third-party turn (not the proxy's
        # own prior output) on first invocation.
        requestor = self._dispatcher_session.agent_name or 'caller'
        proxy_bus.send(proxy_conv_id, requestor, question)

        # Seed the conversation with the /escalation slash command as the
        # initial "human" message.  Claude Code's skill dispatcher picks
        # this up on the proxy's first turn and loads the skill.  The
        # argument is the project's escalation policy for the caller's
        # current CfA state — the /escalation SKILL.md dispatches on it
        # to delegate.md / collaborate.md / escalate.md (or unknown.md
        # when empty / unrecognized).
        policy = self._resolve_escalation_policy()
        seed = f'/escalation {policy}' if policy else '/escalation'
        proxy_bus.send(proxy_conv_id, 'human', seed)

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
        # Distinguish a terminal exit (RESPONSE / WITHDRAW — the
        # escalation is done) from a cancellation (bridge shutdown,
        # engine stop) so the finally block only cleans up when the
        # escalation genuinely finished.  On cancellation we leave the
        # proxy session directory, the dispatcher's conversation_map
        # entry, and the registry entry in place so the next engine
        # startup can reconstitute the in-flight state from disk.
        terminal = False
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
                    terminal = True
                    break
                if status == 'WITHDRAW':
                    final_answer = f'[WITHDRAW]\n{message}'
                    terminal = True
                    break
                # Anything else — no JSON status, DIALOG marker, or an
                # unrecognised status value — is an in-dialog turn: the
                # proxy asked the human a clarifying question and is
                # waiting for the reply.  Block on a ``human`` message
                # on the proxy conversation, then re-invoke so the proxy
                # resumes with the human's input.  RESPONSE / WITHDRAW
                # are the only signals that terminate the loop.
                await self._wait_for_human_reply(
                    proxy_bus, proxy_conv_id, since=invocation_start,
                )
        finally:
            if terminal:
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
            # On non-terminal exit (cancellation) the registry entry is
            # in-memory and is about to be lost with the process; the
            # next engine startup repopulates it by scanning disk state.

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

    def _resolve_escalation_policy(self) -> str:
        """Return the project's escalation policy for the caller's CfA state.

        Walks two files:
          - ``{infra_dir}/.cfa-state.json`` — the CfA engine's current
            state machine position for the caller.  Read ``state`` to
            find out which gate we're at (INTENT / PLAN / EXECUTE).
          - ``{project_root}/.teaparty/project/project.yaml`` — the
            project's ``escalation:`` map from CfA state → mode.

        Returns the mode string for the current state (``always`` /
        ``when_unsure`` / ``never``) or ``''`` when either file is
        missing or has no entry for this state.  Chat-tier callers
        (AgentSession, not a CfA job) have no ``.cfa-state.json`` and
        get ``''`` — the skill's dispatcher treats that as the fallback
        policy.
        """
        if not self.infra_dir:
            return ''
        cfa_path = os.path.join(self.infra_dir, '.cfa-state.json')
        try:
            with open(cfa_path) as fh:
                cfa = json.load(fh)
        except (OSError, json.JSONDecodeError):
            return ''
        state = cfa.get('state', '')
        if not state:
            return ''
        # ``infra_dir`` is {project_root}/.teaparty/jobs/{job-dir}.
        # Walk up three levels to reach {project_root}.
        project_root = os.path.dirname(
            os.path.dirname(os.path.dirname(self.infra_dir))
        )
        project_yaml = os.path.join(
            project_root, '.teaparty', 'project', 'project.yaml',
        )
        try:
            import yaml  # noqa: PLC0415
            with open(project_yaml) as fh:
                config = yaml.safe_load(fh) or {}
        except (OSError, Exception):
            return ''
        escalation = config.get('escalation') or {}
        value = escalation.get(state, '')
        return value if isinstance(value, str) else ''

    def _resolve_proxy_bus(self) -> SqliteMessageBus:
        """Open the proxy's message bus at its canonical location.

        The proxy bus lives at ``{management_teaparty_home}/proxy/
        proxy-messages.db``.  ``self._teaparty_home`` is the proxy's
        home — always management — set by the caller when constructing
        the listener.  No path-walking from the caller's ``infra_dir``;
        that was an artifact of the old chat-tier layout assumption
        (``.teaparty/{scope}/agents/{agent}``) that doesn't hold for
        CfA-engine-hosted listeners whose infra_dir is the job dir.
        """
        if not self._teaparty_home:
            raise RuntimeError(
                'EscalationListener needs teaparty_home to locate the proxy bus'
            )
        bus_path = proxy_bus_path(self._teaparty_home)
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
