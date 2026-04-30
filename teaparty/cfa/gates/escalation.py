"""AskQuestion runner — routes an agent's question to the proxy skill.

The MCP ``AskQuestion`` tool handler, the CfA engine, and the chat-tier
AgentSession all live in the bridge process.  There is no cross-process
boundary between the tool handler and this runner — previous iterations
used a bus-polling ``EscalationListener`` to span a boundary that never
existed.  That ping-pong is gone (Cut 10).

Flow:
  1. The tool handler looks up the caller's ``AskQuestionRunner`` from
     the in-process registry (keyed by the current agent name).
  2. It calls ``await runner.run(question, context)``.
  3. The runner spawns the proxy under the caller's dispatcher session,
     seeds the ``/escalation`` skill with the project's policy for the
     current CfA state, and loops on the proxy's output:
       RESPONSE  → return the answer.
       WITHDRAW  → return ``[WITHDRAW]\\n<reason>``.
       DIALOG    → wait for a human reply on the proxy bus, re-invoke.
  4. On termination: close the bus row, emit ``dispatch_completed``,
     rmtree the proxy session directory.

The proxy's conversation lives on the bus for durable rendering — the
accordion reads from the same bus, and ``rehydrate()`` repopulates the
``_active_escalations`` registry after a bridge restart.
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

from teaparty.messaging.conversations import (
    ConversationState,
    ConversationType,
    SqliteMessageBus,
    make_conversation_id,
)
from teaparty.proxy.hooks import proxy_bus_path

_log = logging.getLogger('teaparty.cfa.gates.escalation')

# Type for the proxy invoker hook supplied by the bridge.
# Signature: async invoker(
#     qualifier: str, cwd: str,
#     teaparty_home: str = '', scope: str = 'management',
# ) -> None
ProxyInvoker = Callable[..., Awaitable[None]]

# Type for the dispatch-event hook used to surface the escalation as a
# child node in the accordion.  Matches bridge._broadcast_dispatch.
DispatchHook = Callable[[dict], Any]

# How often we poll the proxy bus for human dialog replies.
_POLL_INTERVAL = 0.1

# Default escalation policy used whenever the project's ``escalation:``
# map omits an entry for the current state.  Must match the bridge's
# convention at ``_handle_escalation_get`` / ``_handle_escalation_patch``:
# the PATCH handler deletes a state's entry when the user picks
# ``when_unsure``, encoding "default = absent".  The skill's dispatcher,
# meanwhile, treats an empty argument as ``UNKNOWN POLICY``.  Returning
# the default here bridges the two contracts so a project that uses the
# default everywhere doesn't trip the skill's error path.
_DEFAULT_ESCALATION_POLICY = 'when_unsure'


class AskQuestionRunner:
    """Per-caller runner for the AskQuestion MCP tool.

    One instance per agent that can receive AskQuestion calls.  Captures
    the per-caller state (dispatcher session, conv_id, proxy invoker,
    accordion hook) that the proxy-dialog loop needs.  The MCP tool
    handler finds the right instance via
    ``teaparty.mcp.registry.get_ask_question_runner()``.
    """

    def __init__(
        self,
        bus_db_path: str,
        session_id: str = '',
        project_slug: str = '',
        cfa_state: str = '',
        infra_dir: str = '',
        team: str = '',
        proxy_invoker_fn: ProxyInvoker | None = None,
        on_dispatch: DispatchHook | None = None,
        dispatcher_session: Any = None,
        dispatcher_conv_id: str = '',
        teaparty_home: str = '',
        scope: str = 'management',
    ):
        self.bus_db_path = bus_db_path
        self.session_id = session_id
        self.project_slug = project_slug
        # ``cfa_state`` is updated by the CfA engine at each transition
        # so ``/escalation`` gets the current-state policy.  Not
        # meaningful in chat-tier (no CfA machine); stays empty.
        self.cfa_state = cfa_state
        self.infra_dir = infra_dir
        self.team = team
        self._proxy_invoker_fn = proxy_invoker_fn
        self._on_dispatch = on_dispatch
        # The caller's dispatch session + bus conv_id.  The escalation
        # attaches to this conv as a child so the accordion walker
        # resolves it.  Different tiers use different conv_id forms —
        # CfA uses ``job:{project_slug}:{sid}``; chat uses the session's
        # own conv (``lead:{name}:{q}`` / ``om:...`` / etc.) — so the
        # caller must supply it explicitly.
        self._dispatcher_session = dispatcher_session
        self._dispatcher_conv_id = dispatcher_conv_id
        self._teaparty_home = teaparty_home
        self._scope = scope
        self._last_escalation_source: str = ''

    def rehydrate(self) -> None:
        """Re-register in-flight escalations from the bus (#422, #426).

        The ``_active_escalations`` registry is in-memory and is lost
        across bridge restarts, but the bus record for each escalation
        is durable — so startup repopulates the registry by querying
        ``children_of`` the dispatcher's conversation and filtering for
        ``agent_name='proxy'`` rows in an in-flight state.  Without this
        the workflow-bar dot and the ``is_escalation_active`` guard in
        the bridge's HTTP auto-invoke would be blank for escalations
        that survived a restart.

        Only ACTIVE and PAUSED rows are re-marked.  CLOSED / WITHDRAWN
        rows are no longer in flight; re-marking them would leak the
        sentinel that the watchdog reads for stall suppression (#426),
        permanently exempting the caller's session from stall detection
        for any future non-AskQuestion stall.
        """
        if self._dispatcher_session is None:
            return
        from teaparty.mcp.registry import mark_escalation_active as _mark
        try:
            bus = SqliteMessageBus(self.bus_db_path)
        except Exception:
            return
        try:
            parent_conv_id = self._resolve_parent_conv_id()
            for child in bus.children_of(parent_conv_id):
                if child.agent_name != 'proxy':
                    continue
                if child.state not in (
                    ConversationState.ACTIVE, ConversationState.PAUSED,
                ):
                    continue
                qualifier = f'{self._dispatcher_session.id}:{child.request_id}'
                _mark(qualifier)
        finally:
            bus.close()

    async def run(
        self,
        question: str,
        context: str = '',
    ) -> str:
        """Run one AskQuestion through the proxy + ``/escalation`` skill.

        The escalation runs as a real proxy child session under the
        caller's dispatch session so the accordion renders it.  Flow:

          1. Create a proxy Session via the launcher's session machinery,
             with ``parent_session_id = dispatcher.id``.
          2. Write ``QUESTION.md`` into that session's directory.
          3. Record the session in the dispatcher's ``conversation_map``
             so ``build_dispatch_tree`` walks into it.
          4. Emit ``dispatch_started`` with real session IDs.
          5. Seed the proxy conversation with ``/escalation {policy}``
             so the skill loads on the first turn.
          6. Invoke the proxy and loop on its output:
               RESPONSE  → break with final_answer.
               WITHDRAW  → break with ``[WITHDRAW]\\n<reason>``.
               DIALOG    → wait for a human reply on the proxy bus,
                           then re-invoke.
          7. On termination, close the bus row, emit ``dispatch_completed``,
             and rmtree the session directory.
        """
        if not question:
            return ''
        if self._proxy_invoker_fn is None:
            raise RuntimeError(
                'AskQuestionRunner requires proxy_invoker_fn to be set'
            )
        if self._dispatcher_session is None or not self._teaparty_home:
            raise RuntimeError(
                'AskQuestionRunner requires dispatcher_session and '
                'teaparty_home so the accordion can render the escalation '
                'as a child of the caller'
            )

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
            answer = await self._route(question, context)
        except Exception:
            _log.exception('Error routing AskQuestion through proxy')
            answer = ''

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

        return answer

    # ── Skill loop ───────────────────────────────────────────────────────

    def _prepare_proxy_workspace(
        self,
        child_session: Any,
        *,
        question: str,
        context: str,
    ) -> str:
        """Materialize the caller's worktree, write the question, set cwd.

        Lays out the proxy session directory as:

          <session.path>/                 (== launch_cwd)
            QUESTION.md                   # the agent's question + context
            worktree/                     # real-file clone of caller's worktree

        ``child_session.launch_cwd`` is set to ``session.path`` — that
        is the proxy's cwd.  The clone of the caller's worktree lives
        inside it as ``worktree/`` so every file the caller had is
        reachable to the proxy at ``./worktree/<relpath>`` during its
        diligence pass.  The question stays at ``./QUESTION.md`` (the
        existing convention).  The worktree-jail hook constrains reads
        to this subtree, which covers both the question and the clone.

        Returns the absolute path to ``QUESTION.md``.
        """
        from teaparty.workspace.materialize import materialize_worktree

        clone_dir = os.path.join(child_session.path, 'worktree')
        caller_worktree = self._resolve_caller_worktree()
        if caller_worktree and os.path.isdir(caller_worktree):
            materialize_worktree(caller_worktree, clone_dir)
        else:
            # No caller worktree to clone — still create the empty dir
            # so the diligence walk has something to descend into.  This
            # path is exercised by management-tier callers whose "worktree"
            # is the management repo (handled differently up the stack)
            # and by tests with no infra_dir.
            os.makedirs(clone_dir, exist_ok=True)

        child_session.launch_cwd = child_session.path

        question_md = os.path.join(child_session.path, 'QUESTION.md')
        body = question
        if context:
            body = f'{body}\n\n## Context\n\n{context}'
        with open(question_md, 'w') as fh:
            fh.write(body)
        return question_md

    async def _route(
        self, question: str, context: str,
    ) -> str:
        """Run the proxy skill loop and return the final answer."""
        # #426: if the caller was killed mid-wait and is re-firing the
        # same AskQuestion on ``--resume``, the proxy may have already
        # answered.  Pick up the existing reply rather than spawning a
        # duplicate escalation.
        pickup = self._find_resumable_reply(question)
        if pickup is not None:
            existing_conv_id, reply = pickup
            self._close_resumed_conversation(existing_conv_id)
            self._last_escalation_source = 'resume_pickup'
            return reply

        from teaparty.runners.launcher import (
            create_session as _create_session,
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
        child_session.initial_message = question
        # Materialize the caller's worktree into the proxy's cwd (#425).
        # ``_prepare_proxy_workspace`` clones the caller's tree under
        # ``child_session.path/worktree/`` and sets ``launch_cwd`` there;
        # the proxy launches inside the caller's snapshot and reads the
        # deliverables directly during its diligence pass.
        question_path = self._prepare_proxy_workspace(
            child_session, question=question, context=context,
        )
        _save_meta(child_session)

        # Write ``conversation_id`` into metadata.json upfront so
        # build_dispatch_tree returns the real proxy conversation id from
        # the first fetch.  Without this, the tree walker falls back to
        # ``dispatch:{session_id}`` (an id with no messages on any bus)
        # and the accordion iframe renders that stale URL — it fetches 0
        # messages and never re-fetches even after the proxy's
        # AgentSession.save_state() later writes the real conversation_id
        # to disk.
        _meta_path = os.path.join(child_session.path, 'metadata.json')
        with open(_meta_path) as fh:
            _meta = json.load(fh)
        _meta['conversation_id'] = proxy_conv_id
        _tmp = _meta_path + '.tmp'
        with open(_tmp, 'w') as fh:
            json.dump(_meta, fh, indent=2)
        os.replace(_tmp, _meta_path)

        # Register the escalation in the caller's bus — single source of
        # truth for tree / name / state (#422).  Row id MUST equal
        # ``proxy_conv_id``; messages live in the proxy bus at
        # ``proxy:{qualifier}``, and one logical conversation with two
        # ids is exactly the class of bug #422 killed.
        try:
            _esc_bus = SqliteMessageBus(self.bus_db_path)
            try:
                _esc_bus.create_conversation(
                    ConversationType.PROXY, qualifier,
                    agent_name='proxy',
                    parent_conversation_id=self._resolve_parent_conv_id(),
                    request_id=escalation_id,
                    project_slug=self.project_slug or '',
                    state=ConversationState.ACTIVE,
                )
            finally:
                _esc_bus.close()
        except Exception:
            _log.debug(
                'escalation: failed to register PROXY row for %s',
                proxy_conv_id, exc_info=True,
            )

        # Emit dispatch_started so the dashboard animates the new blade.
        # The accordion auto-expands by matching event.child_session_id
        # against the tree node's session_id, which build_dispatch_tree
        # derives from ``conv.id.partition(':')[2]`` — so we emit
        # ``qualifier`` (matches for ``proxy:{qualifier}``).
        self._emit_dispatch(
            'dispatch_started',
            parent_sid=self._dispatcher_session.id,
            child_sid=qualifier,
        )

        # The proxy bus is where the accordion reads dialog messages from.
        proxy_bus = self._resolve_proxy_bus()
        proxy_bus.create_conversation(ConversationType.PROXY, qualifier)

        # Post the question as a message from the requesting agent so
        # the accordion iframe shows what the teammate actually asked.
        requestor = self._dispatcher_session.agent_name or 'caller'
        proxy_bus.send(proxy_conv_id, requestor, question)

        # Seed with /escalation so the skill loads on the proxy's first
        # turn.  The argument is the project's escalation policy for the
        # caller's current CfA state; the skill's SKILL.md dispatches on
        # it to delegate.md / collaborate.md / escalate.md.
        policy = self._resolve_escalation_policy()
        seed = f'/escalation {policy}' if policy else '/escalation'
        proxy_bus.send(proxy_conv_id, 'human', seed)

        # Take ownership of this proxy qualifier so the bridge's HTTP
        # handler stops auto-invoking the proxy while this loop drives
        # it — otherwise every DIALOG reply the human types fires two
        # proxy invocations.
        from teaparty.mcp.registry import (
            mark_escalation_active as _mark_active,
            mark_escalation_done as _mark_done,
        )
        _mark_active(qualifier)

        final_answer = ''
        terminal = False
        try:
            while True:
                invocation_start = time.time()

                # The cwd handed to the proxy invoker is whatever
                # ``_prepare_proxy_workspace`` set as the session's
                # ``launch_cwd``.  Reading it back from the session
                # rather than re-deriving here keeps the two in lock
                # step — if the workspace layout changes, only the
                # preparer knows the new cwd, and ``_route`` follows.
                await self._proxy_invoker_fn(
                    qualifier=qualifier,
                    cwd=child_session.launch_cwd,
                    teaparty_home=self._teaparty_home,
                    scope=self._scope,
                )

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
                # Anything else — DIALOG marker or unrecognised status —
                # is an in-dialog turn: wait for the human, then re-fire.
                await self._wait_for_human_reply(
                    proxy_bus, proxy_conv_id, since=invocation_start,
                )
        finally:
            # #426: clear the in-memory escalation marker on EVERY exit
            # path.  Leaking the marker permanently exempts this session
            # from stall detection — a leaked sentinel deadlocks the
            # watchdog for any future stall on the same session.
            _mark_done(qualifier)
            if terminal:
                try:
                    _term_bus = SqliteMessageBus(self.bus_db_path)
                    try:
                        _term_bus.update_conversation_state(
                            proxy_conv_id,
                            ConversationState.CLOSED,
                        )
                    finally:
                        _term_bus.close()
                except Exception:
                    _log.debug(
                        'escalation: failed to close bus record for %s',
                        proxy_conv_id, exc_info=True,
                    )
                self._emit_dispatch(
                    'dispatch_completed',
                    parent_sid=self._dispatcher_session.id,
                    child_sid=qualifier,
                )
                shutil.rmtree(child_session.path, ignore_errors=True)
            # On non-terminal exit (cancellation) the bus record stays
            # active; the next startup's recovery sweep marks it paused
            # so the user can resume or withdraw.

        self._last_escalation_source = 'proxy_skill'
        return final_answer

    def _emit_dispatch(
        self, event_type: str, *, parent_sid: str, child_sid: str,
    ) -> None:
        """Fire a dispatch_started / dispatch_completed event."""
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

    def _find_resumable_reply(
        self, question: str,
    ) -> tuple[str, str] | None:
        """Look for an in-flight escalation under this caller whose
        question matches and whose proxy reply is already on the bus.

        Matching rule (#426): a PROXY conversation whose parent is
        ``dispatcher_conv_id``, whose state is ACTIVE or PAUSED, whose
        proxy bus has a requestor message byte-identical to ``question``,
        and whose latest proxy message parses as a terminal status
        (RESPONSE or WITHDRAW).  The byte-identical match defends
        against cross-delivery between distinct outstanding questions —
        ``--resume`` re-fires the buffered tool call with the original
        payload, so an exact-match check is both necessary and
        sufficient.

        Returns ``(proxy_conv_id, answer)`` where ``answer`` is the
        already-formatted return value (RESPONSE message verbatim, or
        ``[WITHDRAW]\\n<reason>`` for WITHDRAW).  Returns None when no
        candidate matches — the runner falls through to the normal
        spawn path.
        """
        try:
            parent_conv_id = self._resolve_parent_conv_id()
        except RuntimeError:
            return None

        try:
            caller_bus = SqliteMessageBus(self.bus_db_path)
        except Exception:
            return None
        try:
            children = caller_bus.children_of(parent_conv_id)
        finally:
            caller_bus.close()

        candidates = [
            c for c in children
            if c.agent_name == 'proxy'
            and c.state in (
                ConversationState.ACTIVE, ConversationState.PAUSED,
            )
        ]
        if not candidates:
            return None

        try:
            proxy_bus = self._resolve_proxy_bus()
        except Exception:
            return None
        try:
            for conv in candidates:
                try:
                    messages = proxy_bus.receive(conv.id)
                except Exception:
                    continue
                # Requestor's question is the first message that isn't
                # the ``human`` /escalation seed and isn't from the
                # proxy itself.
                requestor_msg = next(
                    (
                        m for m in messages
                        if m.sender not in ('human', 'proxy')
                    ),
                    None,
                )
                if requestor_msg is None or requestor_msg.content != question:
                    continue
                proxy_msgs = [m for m in messages if m.sender == 'proxy']
                if not proxy_msgs:
                    continue
                status, body = _parse_skill_output(proxy_msgs[-1].content)
                if status == 'RESPONSE':
                    return conv.id, body
                if status == 'WITHDRAW':
                    return conv.id, f'[WITHDRAW]\n{body}'
        finally:
            proxy_bus.close()
        return None

    def _close_resumed_conversation(self, conv_id: str) -> None:
        """Transition a resumed PROXY conversation to CLOSED on delivery (#426).

        Also clears the in-memory escalation marker for the resumed
        qualifier.  ``rehydrate()`` re-marks every ACTIVE/PAUSED proxy
        child on bridge startup; without an explicit clear here, a
        session whose escalation was satisfied via resume-pickup would
        keep that qualifier in ``_active_escalations`` for the lifetime
        of the bridge, deadlocking the watchdog for any future stall.
        """
        # Conv ids for proxy escalations have the form
        # ``proxy:{caller_session_id}:{escalation_id}``; the qualifier
        # is everything after the first ``:``.
        prefix, sep, qualifier = conv_id.partition(':')
        if sep and qualifier:
            from teaparty.mcp.registry import (
                mark_escalation_done as _mark_done,
            )
            _mark_done(qualifier)

        try:
            bus = SqliteMessageBus(self.bus_db_path)
            try:
                bus.update_conversation_state(
                    conv_id, ConversationState.CLOSED,
                )
            finally:
                bus.close()
        except Exception:
            _log.debug(
                'escalation: failed to close resumed PROXY row %s',
                conv_id, exc_info=True,
            )

    def _resolve_parent_conv_id(self) -> str:
        """Return the bus conv_id the escalation's PROXY row attaches to.

        The caller MUST supply ``dispatcher_conv_id`` at construction
        time — the parent conv_id varies by tier and we can't
        reconstruct it safely.  Silent fallbacks here are how CfA-job
        escalations kept disappearing from the accordion before #422.
        """
        if not self._dispatcher_conv_id:
            raise RuntimeError(
                'AskQuestionRunner: dispatcher_conv_id was not supplied '
                'at construction time.  Empty would silently misroute '
                'the accordion.',
            )
        return self._dispatcher_conv_id

    def _resolve_escalation_policy(self) -> str:
        """Return the project's escalation policy for the caller's CfA state.

        Reads ``.cfa-state.json`` from ``infra_dir`` for the current
        state, then ``{project_root}/.teaparty/project/project.yaml``
        for its ``escalation:`` map.  Returns the mode string
        (``always`` / ``when_unsure`` / ``never``).

        When the file, key, or value is missing, returns
        ``_DEFAULT_ESCALATION_POLICY``.  This matches the bridge UI's
        convention: the PATCH handler treats ``when_unsure`` as the
        default by deleting the entry rather than writing it, so a
        project where every state is ``when_unsure`` ends up with no
        ``escalation:`` map at all.  Returning the default here keeps
        that representation working end-to-end; otherwise the skill's
        dispatcher would reject the empty argument as ``UNKNOWN POLICY``.
        """
        if not self.infra_dir:
            return _DEFAULT_ESCALATION_POLICY
        cfa_path = os.path.join(self.infra_dir, '.cfa-state.json')
        try:
            with open(cfa_path) as fh:
                cfa = json.load(fh)
        except (OSError, json.JSONDecodeError):
            return _DEFAULT_ESCALATION_POLICY
        state = cfa.get('state', '')
        if not state:
            return _DEFAULT_ESCALATION_POLICY
        # infra_dir is {project_root}/.teaparty/jobs/{job-dir}.  Walk
        # up three levels to reach {project_root}.
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
            return _DEFAULT_ESCALATION_POLICY
        escalation = config.get('escalation') or {}
        value = escalation.get(state)
        if isinstance(value, str) and value:
            return value
        return _DEFAULT_ESCALATION_POLICY

    def _resolve_caller_worktree(self) -> str:
        """Find the worktree of the agent currently calling AskQuestion.

        The MCP middleware sets ``current_session_id`` per request.
        For the project lead's calls — where the lead lives in the
        job's worktree — this maps to the engine's session_id, and
        the worktree is ``{infra_dir}/worktree``.  For dispatched
        workers, the worker's session_id appears as the contextvar's
        value, and the bus's DISPATCH row stores the actual
        ``worktree_path`` (correct at any depth).  Falls back to the
        job's worktree when neither lookup succeeds.
        """
        from teaparty.mcp.registry import (  # noqa: PLC0415
            current_session_id,
        )
        job_worktree = (
            os.path.join(self.infra_dir, 'worktree')
            if self.infra_dir else ''
        )
        caller_sid = current_session_id.get('') or ''
        if not caller_sid or caller_sid == self.session_id:
            return job_worktree
        if not self.bus_db_path:
            return job_worktree
        try:
            bus = SqliteMessageBus(self.bus_db_path)
            try:
                conv = bus.get_conversation(f'dispatch:{caller_sid}')
            finally:
                bus.close()
        except Exception:
            return job_worktree
        bus_worktree = getattr(conv, 'worktree_path', '') if conv else ''
        return bus_worktree or job_worktree

    def _resolve_proxy_bus(self) -> SqliteMessageBus:
        """Open the proxy's message bus at its canonical location."""
        if not self._teaparty_home:
            raise RuntimeError(
                'AskQuestionRunner needs teaparty_home to locate the proxy bus'
            )
        bus_path = proxy_bus_path(self._teaparty_home)
        os.makedirs(os.path.dirname(bus_path), exist_ok=True)
        return SqliteMessageBus(bus_path)

    def _read_last_proxy_message(
        self, bus: SqliteMessageBus, conv_id: str, since: float,
    ) -> str:
        """Return the content of the proxy's most recent message, or ''."""
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
    ``json.loads`` on the slice.  The last successfully-parsed object
    that carries a recognised status wins — per DD6 the skill's terminal
    turn is the one that matters when the model produces intermediate
    thinking that also contains a JSON-looking fragment.

    Returns ``(status, message)`` or ``('', '')`` if no object parses.
    """
    if not text:
        return '', ''

    results: list[tuple[str, str]] = []
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
    return results[-1]


def _extract_json_object(text: str, start: int) -> dict | None:
    """Return the dict parsed from the JSON object starting at ``text[start]``."""
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
