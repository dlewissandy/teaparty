"""Unified agent session — one codepath for all agent conversations.

Every agent conversation in TeaParty — OM, project leads, config lead,
project manager, proxy — runs through this single session class. The
session manages the conversation lifecycle: message bus, state persistence
via the launcher's session system, worktree creation, and delegation to
the unified launcher for subprocess execution.

Variable behavior is handled through configuration and hooks, not
subclasses:
- dispatch: agents with rosters get a BusEventListener for Send/Reply
- post_invoke: optional callback after launch (e.g. proxy ACT-R processing)
- build_prompt: optional override for prompt construction (e.g. proxy memory)

Issue #394.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from typing import Any, Awaitable, Callable

from teaparty.messaging.conversations import (
    ConversationType,
    SqliteMessageBus,
    agent_bus_path,
    make_conversation_id,
)
from teaparty.proxy.hooks import proxy_bus_path
from teaparty.teams.stream import (
    NON_CONVERSATIONAL_SENDERS,
    _extract_slug,
    _make_live_stream_relay,
)

_log = logging.getLogger('teaparty.teams.session')

# Type for optional hooks
PostInvokeHook = Callable[[str, 'AgentSession'], None]  # (response_text, session)
BuildPromptHook = Callable[['AgentSession', str], str]   # (session, latest_human) -> prompt


class AgentSession:
    """Unified session for any agent conversation.

    One class handles all agent types. Differences are configuration:

    - agent_name: which agent definition to use
    - scope: 'management' or 'project'
    - conversation_type: how the conversation_id is keyed
    - agent_role: the sender label on bus messages
    - dispatches: whether to start a BusEventListener for Send/Reply
    - post_invoke_hook: called after launch with the response text
    - build_prompt_hook: called to build the prompt (overrides default)
    """

    def __init__(
        self,
        teaparty_home: str,
        *,
        agent_name: str,
        scope: str = 'management',
        qualifier: str,
        conversation_type: ConversationType,
        agent_role: str = '',
        llm_backend: str = 'claude',
        dispatches: bool = False,
        post_invoke_hook: PostInvokeHook | None = None,
        build_prompt_hook: BuildPromptHook | None = None,
        on_dispatch: Callable[[dict], Any] | None = None,
        llm_caller: Callable | None = None,
        project_slug: str = '',
        paused_check: Callable[[], bool] | None = None,
        org_home: str | None = None,
        proxy_invoker_fn: Callable[..., Awaitable[None]] | None = None,
    ):
        self.teaparty_home = os.path.expanduser(teaparty_home)
        self.agent_name = agent_name
        self.scope = scope
        self.qualifier = qualifier
        self.agent_role = agent_role or agent_name
        self._llm_backend = llm_backend
        self._dispatches = dispatches
        self._post_invoke_hook = post_invoke_hook
        self._build_prompt_hook = build_prompt_hook
        self._on_dispatch = on_dispatch
        self._llm_caller = llm_caller  # None → use launcher default
        self.project_slug = project_slug
        # org_home: org-level .teaparty/ used as agent-definition fallback when
        # teaparty_home is a project-specific directory (e.g. external projects).
        self._org_home = os.path.expanduser(org_home) if org_home else None
        self._telemetry_scope = project_slug or scope
        self._paused_check = paused_check
        # Bridge-supplied callable invoked per escalation turn to run the
        # proxy agent with the escalation-skill cwd. Signature:
        #   async def invoker(qualifier: str, cwd: str) -> None
        # Required for AskQuestion; sessions without it cannot escalate.
        self._proxy_invoker_fn = proxy_invoker_fn

        self.conversation_id = make_conversation_id(conversation_type, qualifier)
        self.claude_session_id: str | None = None
        self.conversation_title: str | None = None

        # Message bus — proxy uses its own consolidated runtime directory
        if agent_name == 'proxy':
            bus_path = proxy_bus_path(self.teaparty_home)
        else:
            bus_path = agent_bus_path(self.teaparty_home, agent_name)
        os.makedirs(os.path.dirname(bus_path), exist_ok=True)
        self._bus = SqliteMessageBus(bus_path)

        # Dispatch infrastructure (lazy init)
        self._bus_listener = None
        self._bus_context_id: str | None = None
        self._dispatch_session = None
        self._ask_question_runner = None
        # MCP routes bundle installed at every launch in this session's
        # subtree (lead self-invoke, dispatched children, grandchildren).
        # Built in _ensure_bus_listener for dispatching agents; remains
        # None for leaf workers that neither dispatch nor close.
        self._mcp_routes = None

        # Serialize concurrent invocations — only one claude process per
        # agent session at a time. When multiple children reply at once,
        # each _run_child triggers a resume; the lock queues them.
        self._invoke_lock: asyncio.Lock | None = None

        # Background tasks spawned by this session (one per dispatched
        # child running _run_child). Tracked so /clear and withdraw can
        # cancel them.
        self._background_tasks: set[asyncio.Task] = set()
        # child_session_id → running _run_child task, so close_fn can
        # cancel a specific in-flight conversation.
        # In-flight child tasks, keyed by child session_id.  The
        # BusEventListener aliases this same dict on start (issue #422
        # — close_fn reads it via the listener, so both tiers share one
        # registry).  Kept accessible here for legacy callers and for
        # the non-dispatching path where no listener is built.
        self._tasks_by_child: dict[str, asyncio.Task] = {}
        # child_session_id → factory that re-creates the _run_child
        # coroutine for that child. Populated by spawn_fn; consulted by
        # the pause/resume walker (issue #403) to rebuild the task
        # chain without having to duplicate spawn_fn's closure state.
        # Signature: factory(start_at_phase, initial_gc_task_ids,
        #                    resume_claude_session) -> Coroutine
        self._run_child_factories: dict[str, Any] = {}

    # ── Message bus ──────────────────────────────────────────────────────

    def send_human_message(self, content: str) -> str:
        return self._bus.send(self.conversation_id, 'human', content)

    def send_agent_message(self, content: str) -> str:
        return self._bus.send(self.conversation_id, self.agent_role, content)

    def get_messages(self, since_timestamp: float = 0.0):
        return self._bus.receive(self.conversation_id, since_timestamp=since_timestamp)

    def build_context(self) -> str:
        messages = self.get_messages()
        if not messages:
            return ''
        lines = []
        for msg in messages:
            if (msg.sender in NON_CONVERSATIONAL_SENDERS
                    or msg.sender.startswith('unknown:')):
                continue
            role = 'Human' if msg.sender == 'human' else self.agent_role
            lines.append(f'{role}: {msg.content}')
        return '\n\n'.join(lines)

    # ── Session lifecycle (via launcher) ─────────────────────────────────

    def _session_key(self) -> str:
        if not self.qualifier:
            return self.agent_name
        safe_id = self.qualifier.replace('/', '-').replace(':', '-').replace(' ', '-')
        return f'{self.agent_name}-{safe_id}'

    def save_state(self) -> None:
        from teaparty.runners.launcher import create_session, load_session
        key = self._session_key()
        session = load_session(
            agent_name=self.agent_name, scope=self.scope,
            teaparty_home=self.teaparty_home, session_id=key,
        )
        if session is None:
            session = create_session(
                agent_name=self.agent_name, scope=self.scope,
                teaparty_home=self.teaparty_home, session_id=key,
            )
        meta_path = os.path.join(session.path, 'metadata.json')
        # Read-modify-write so fields this class does not track
        # (parent_session_id, launch_cwd, phase, etc.) are preserved.
        # The escalation path pre-creates the proxy's session with
        # parent_session_id set — a blind overwrite would clobber that
        # linkage and the accordion would lose the parent→child edge.
        try:
            with open(meta_path) as f:
                meta = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            meta = {}
        meta.update({
            'session_id': session.id,
            'agent_name': session.agent_name,
            'scope': session.scope,
            'claude_session_id': self.claude_session_id or '',
            'conversation_title': self.conversation_title or '',
            'qualifier': self.qualifier,
            'conversation_id': self.conversation_id,
        })
        tmp = meta_path + '.tmp'
        with open(tmp, 'w') as f:
            json.dump(meta, f, indent=2)
        os.replace(tmp, meta_path)

    def load_state(self) -> None:
        from teaparty.runners.launcher import load_session
        session = load_session(
            agent_name=self.agent_name, scope=self.scope,
            teaparty_home=self.teaparty_home, session_id=self._session_key(),
        )
        if session is not None:
            self.claude_session_id = session.claude_session_id or None
            meta_path = os.path.join(session.path, 'metadata.json')
            try:
                with open(meta_path) as f:
                    meta = json.load(f)
                self.conversation_title = meta.get('conversation_title') or None
            except (FileNotFoundError, json.JSONDecodeError):
                pass

    def _latest_human_message(self) -> str:
        """Return the raw content of the latest incoming message.

        Returns the content as stored in the bus, with no prefix.
        Used for /clear detection and other internal checks that need
        to match against exact content.

        The sender is not included — callers that need to know who
        sent the message should use _latest_incoming_with_sender().
        """
        messages = self.get_messages()
        for msg in reversed(messages):
            if (msg.sender != self.agent_role
                    and msg.sender not in NON_CONVERSATIONAL_SENDERS
                    and not msg.sender.startswith('unknown:')):
                return msg.content
        return ''

    def _latest_incoming_with_sender(self) -> str:
        """Return the latest direct incoming message on the parent bus.

        Used on resume to deliver a direct human (or peer) message.
        Dispatched-child replies are delivered via the explicit
        ``resume_message`` parameter to ``invoke()``, not via this
        scan — that keeps the UI accordion reading child replies from
        the nested dispatch conversation rather than the flattened
        parent conversation.
        """
        messages = self.get_messages()
        for msg in reversed(messages):
            if (msg.sender != self.agent_role
                    and msg.sender not in NON_CONVERSATIONAL_SENDERS
                    and not msg.sender.startswith('unknown:')):
                role = 'Human' if msg.sender == 'human' else msg.sender
                return f'{role}: {msg.content}'
        return ''

    # ── Dispatch (Send/Reply) ────────────────────────────────────────────

    async def _ensure_bus_listener(self, cwd: str) -> dict:
        """Start the BusEventListener and register the AskQuestion runner.

        Send / CloseConversation / AskQuestion all route through the
        in-process registry (keyed by agent name); no Unix sockets and
        no bus ping-pong.
        """
        if self._bus_listener is not None:
            return {
                'AGENT_ID': self.agent_name,
                'PYTHONPATH': cwd,
            }

        from teaparty.messaging.listener import BusEventListener
        from teaparty.runners.launcher import (
            launch as _launch,
            create_session as _create_session,
            check_slot_available as _check_slot,
            _save_session_metadata as _save_meta,
            mark_launching as _mark_launching,
            mark_awaiting as _mark_awaiting,
            mark_complete as _mark_complete,
        )

        infra_dir = os.path.join(
            self.teaparty_home, self.scope, 'agents', self.agent_name,
        )
        bus_db_path = os.path.join(infra_dir, 'messages.db')
        repo_root = os.path.dirname(self.teaparty_home)

        if self._dispatch_session is None:
            from teaparty.runners.launcher import load_session as _load_session
            stable_id = self._session_key()
            try:
                self._dispatch_session = _load_session(
                    agent_name=self.agent_name, scope=self.scope,
                    teaparty_home=self.teaparty_home,
                    session_id=stable_id,
                )
            except Exception:
                pass
            if self._dispatch_session is None:
                self._dispatch_session = _create_session(
                    agent_name=self.agent_name, scope=self.scope,
                    teaparty_home=self.teaparty_home,
                    session_id=stable_id,
                )

        # Map session_id → session for hierarchical dispatch recording.
        # When a child agent dispatches, spawn_fn looks up the child's
        # session by the session_id from the MCP contextvar (unique per
        # instance, even for parallel instances of the same agent).
        session_registry: dict[str, object] = {}

        if not self._bus_context_id:
            self._bus_context_id = f'agent:{self.agent_name}:lead:{uuid.uuid4()}'
            bus = SqliteMessageBus(bus_db_path)
            try:
                bus.create_agent_context(
                    self._bus_context_id,
                    initiator_agent_id=self.agent_name,
                    recipient_agent_id=self.agent_name,
                )
            finally:
                bus.close()

        self._bus_listener = BusEventListener(
            bus_db_path=bus_db_path,
            initiator_agent_id=self.agent_name,
            current_context_id=self._bus_context_id,
        )
        # Alias the session's tasks_by_child onto the listener so the
        # shared close_fn (workspace/close_conversation.py::build_close_fn)
        # can read the same dict — issue #422.  Same object, two names.
        self._bus_listener.tasks_by_child = self._tasks_by_child
        await self._bus_listener.start()

        from teaparty.workspace.close_conversation import build_close_fn
        close_fn = build_close_fn(
            dispatch_session=self._dispatch_session,
            teaparty_home=self.teaparty_home,
            scope=self.scope,
            tasks_by_child=self._tasks_by_child,
            on_dispatch=self._on_dispatch,
            agent_name=self.agent_name,
            bus=self._bus,
        )

        # Construct the AskQuestion runner so agents can call AskQuestion.
        # The runner spawns a proxy child session via the /escalation
        # skill.  Same-process direct call from the MCP tool handler —
        # no bus ping-pong.
        from teaparty.cfa.gates.escalation import AskQuestionRunner
        # The proxy is a management-level participant.  Its session (and
        # its agent.md) always live at management scope, independent of
        # who calls AskQuestion.  For project agents (e.g. project
        # manager, project lead) ``_org_home`` is the bridge's management
        # ``.teaparty/``; for management agents it's already their own
        # teaparty_home.  The caller's ``_dispatch_session`` stays at the
        # caller's scope — it's the conversation_map owner, which the
        # dispatch-tree walker follows cross-scope to resolve children.
        proxy_teaparty_home = self._org_home or self.teaparty_home
        self._ask_question_runner = AskQuestionRunner(
            bus_db_path=bus_db_path,
            session_id=self._dispatch_session.id,
            infra_dir=infra_dir,
            proxy_invoker_fn=self._proxy_invoker_fn,
            on_dispatch=self._on_dispatch,
            dispatcher_session=self._dispatch_session,
            # This AgentSession's bus conv_id is the parent the
            # escalation attaches to — whatever form it takes (OM's
            # ``om:{q}``, a project lead's ``lead:{name}:{q}``, or a
            # dispatched ``dispatch:{sid}``).  The dispatch-tree walker
            # is rooted at this conv, so the escalation must be keyed
            # to it or the accordion blade never materializes.
            dispatcher_conv_id=self.conversation_id,
            teaparty_home=proxy_teaparty_home,
            scope='management',
        )
        self._ask_question_runner.rehydrate()

        # Build the MCPRoutes bundle this session installs at every
        # launch — for itself, for dispatched children, for grandchildren.
        # launch() is the single registration site (issue #422); the MCP
        # server runs inside the bridge, not in the agent's subprocess, so
        # env vars don't reach the handler — the handler reads the registry
        # keyed by current_agent_name (set by ASGI middleware from the URL).
        #
        # The dispatcher enforces routing at Send time — the same
        # mechanism the CfA engine uses, derived from the same shared
        # helper.  An OM session derives the table from the management
        # roster; a project-lead session derives it from project
        # workgroups.  Grandchildren register the same bundle via
        # launch(), so an arbitrarily nested team enforces against one
        # routing table.  Routing tables key directly on agent names —
        # an agent's name is its identity.
        from teaparty.mcp.registry import (
            MCPRoutes, register_agent_mcp_routes,
        )
        from teaparty.messaging.child_dispatch import (
            build_session_dispatcher,
            ChildDispatchContext,
            make_spawn_fn,
        )
        from teaparty.config.roster import resolve_lead_project_path

        proj_dir = ''
        if self.project_slug:
            proj_dir = resolve_lead_project_path(
                self.agent_name, self.teaparty_home,
            ) or ''
        dispatcher = build_session_dispatcher(
            teaparty_home=self.teaparty_home,
            project_dir=proj_dir,
        )

        # Cut 24: build the unified spawn_fn from a shared
        # ChildDispatchContext.  Both tiers pass through the same
        # prelude (slot/paused checks, member resolution,
        # session+worktree creation, bus DISPATCH row write,
        # lifecycle scheduling); chat tier passes ``cross_repo_supported=True``
        # (an OM dispatch can land at a project's natural repo) and a
        # ``factory_registry`` for the pause/resume walker.
        async def _on_child_complete(child_session, response_text):
            """Chat-tier fan-in: re-invoke the lead with the child's
            reply when the dispatcher was the top-level session.
            Nested dispatches return their text up through the
            tasks_by_child fan-in instead."""
            if not response_text:
                return
            if child_session.parent_session_id == self._dispatch_session.id:
                child_conv_id = f'dispatch:{child_session.id}'
                reply = (
                    f'[{child_conv_id}] {child_session.agent_name}: '
                    f'{response_text}'
                )
                try:
                    await self.invoke(cwd=cwd, resume_message=reply)
                except Exception:
                    _log.exception(
                        '%s: failed to resume after %s reply',
                        self.agent_name, child_session.agent_name,
                    )

        # The dispatcher session's launch_cwd is the chat tier's cwd —
        # set it explicitly so the shared prelude can derive source_repo
        # for nested dispatchers.  (Top-level: empty worktree_path,
        # falls back to launch_cwd.)
        if not self._dispatch_session.launch_cwd:
            self._dispatch_session.launch_cwd = cwd
        if not self._dispatch_session.agent_name:
            self._dispatch_session.agent_name = self.agent_name

        repo_root = os.path.dirname(self.teaparty_home)
        self._dispatch_ctx = ChildDispatchContext(
            dispatcher_session=self._dispatch_session,
            bus=self._bus,
            bus_listener=self._bus_listener,
            session_registry=session_registry,
            tasks_by_child=self._tasks_by_child,
            factory_registry=self._run_child_factories,
            teaparty_home=self.teaparty_home,
            project_slug=self.project_slug or '',
            repo_root=repo_root,
            telemetry_scope=self._telemetry_scope,
            fixed_scope=None,                # chat: resolve via roster
            cross_repo_supported=True,
            log_tag=f'{self.agent_name} spawn_fn',
            paused_check=self._paused_check,
            on_dispatch=self._on_dispatch,
            background_tasks=self._background_tasks,
            llm_caller=self._llm_caller,
            on_child_complete=_on_child_complete,
        )
        spawn_fn = make_spawn_fn(self._dispatch_ctx)

        self._mcp_routes = MCPRoutes(
            spawn_fn=spawn_fn,
            close_fn=close_fn,
            ask_question_runner=self._ask_question_runner,
            dispatcher=dispatcher,
        )
        # mcp_routes must be on the dispatch ctx so children inherit it.
        self._dispatch_ctx.mcp_routes = self._mcp_routes
        # Register the bundle for the lead itself.  Dispatched children
        # are registered by launch() when their subprocess spawns.
        register_agent_mcp_routes(self.agent_name, self._mcp_routes)

        # Cut 19: bus-based orphan recovery — same function CfA calls.
        # Walks ``self.conversation_id``'s children, asks the OS whether
        # each child's recorded PID is still alive, merges or marks
        # closed accordingly.  The merge target is the lead's launch
        # cwd (best effort — squash_merge no-ops if cwd isn't a git
        # worktree).  Replaces the no-recovery state chat tier had
        # before; both tiers now go through the single codepath at
        # ``teaparty/workspace/recovery.py``.
        from teaparty.workspace.recovery import recover_orphaned_children
        try:
            await recover_orphaned_children(
                parent_conversation_id=self.conversation_id,
                bus=self._bus,
                session_worktree=cwd,
                task=f'{self.agent_name} session',
                session_id=self._dispatch_session.id if self._dispatch_session else '',
                event_bus=None,
                redispatch_fn=None,
            )
        except Exception:
            _log.debug(
                '%s: recover_orphaned_children raised', self.agent_name,
                exc_info=True,
            )

        return {
            'AGENT_ID': self.agent_name,
            'PYTHONPATH': cwd,
        }

    async def _cancel_background_tasks(self) -> None:
        """Cancel all background _run_child tasks this session spawned.

        Called by /clear, stop(), and withdraw. Each task is cancelled
        and awaited with a timeout so we don't block indefinitely on a
        stuck child.
        """
        if not self._background_tasks:
            return
        tasks = list(self._background_tasks)
        for t in tasks:
            t.cancel()
        try:
            await asyncio.wait_for(
                asyncio.gather(*tasks, return_exceptions=True),
                timeout=5.0)
        except asyncio.TimeoutError:
            _log.warning('%s: background tasks did not cancel within 5s',
                         self.agent_name)
        self._background_tasks.clear()
        self._tasks_by_child.clear()

    async def _clear(self, cwd: str) -> None:
        """Full reset: clear bus, stop listener, release worktrees, close contexts.

        Called by /clear. Resets all session state so the next invocation
        starts completely fresh with no stale history or orphaned resources.

        Scoped to this session's context tree — other conversations with the
        same agent are not affected.
        """
        import subprocess as _sp
        from teaparty.runners.launcher import load_session as _load_session
        from teaparty.workspace.close_conversation import (
            close_conversation,
        )

        # 0. Close every open top-level dispatch the same way the agent
        # would via CloseConversation: cancel descendant tasks, rmtree
        # session dirs, fire dispatch_completed per removed session so
        # the UI accordion tears the nested blades down. /clear is the
        # operator-initiated equivalent of "close everything you own."
        #
        # Critical: on a FRESH server process where the OM hasn't been
        # invoked yet, self._dispatch_session is None (lazy-initialized
        # in _ensure_bus_listener) and close_fn isn't even registered.
        # But the on-disk conversation_map still holds stale children
        # from a prior run. We must load the dispatch session from disk
        # here and tear down whatever it points to, independently of
        # whether the bus listener ever started.
        dispatch_session = self._dispatch_session
        if dispatch_session is None:
            try:
                dispatch_session = _load_session(
                    agent_name=self.agent_name, scope=self.scope,
                    teaparty_home=self.teaparty_home,
                    session_id=self._session_key(),
                )
            except Exception:
                dispatch_session = None

        # Enumerate the top-level dispatches from the bus (#422) — the
        # single source of truth.  The old code walked
        # dispatch_session.conversation_map (disk metadata); the bus is
        # now authoritative for the tree.
        from teaparty.workspace.close_conversation import (
            collect_descendants_with_parents_from_bus,
        )
        root_conv_id = self.conversation_id
        top_level_children = (
            self._bus.children_of(root_conv_id)
            if dispatch_session is not None else []
        )

        if dispatch_session is not None and top_level_children:
            sessions_dir = os.path.join(
                self.teaparty_home, self.scope, 'sessions')

            for child_conv in top_level_children:
                if not child_conv.id.startswith('dispatch:'):
                    continue
                child_sid = child_conv.id[len('dispatch:'):]

                # Walk subtree via the bus to enumerate every descendant
                # that needs a dispatch_completed event.
                subtree_convs = collect_descendants_with_parents_from_bus(
                    self._bus, child_conv.id,
                    root_parent_conv_id=root_conv_id,
                )
                subtree: list[tuple[str, str]] = []
                agent_names: dict[str, str] = {}
                for conv, parent_conv_id in subtree_convs:
                    _, _, csid = conv.id.partition(':')
                    # Parent session_id comes from the parent's
                    # ``dispatch:{sid}`` conv_id.  For top-level
                    # children of this root (parent_conv_id is
                    # non-dispatch, e.g. 'om:...' or 'lead:...:...'),
                    # the parent is the dispatcher's session.
                    if parent_conv_id.startswith('dispatch:'):
                        parent_sid = parent_conv_id[len('dispatch:'):]
                    else:
                        parent_sid = dispatch_session.id
                    subtree.append((csid, parent_sid))
                    agent_names[csid] = conv.agent_name

                # Cancel any live tasks in this subtree (fresh-server
                # case has no live tasks; re-invocation case might).
                for csid, _parent in subtree:
                    t = self._tasks_by_child.pop(csid, None)
                    if t is not None and not t.done():
                        t.cancel()

                # /clear is operator-initiated "throw it away" — it must
                # leave no on-disk state behind.  close_conversation
                # returns a structured result (ok/conflict/error/noop).
                # When it fails we fall through to force-teardown: drop
                # the worktree and branch without merging, rmtree the
                # session dir.
                close_ok = False
                try:
                    result = await close_conversation(
                        dispatch_session, f'dispatch:{child_sid}',
                        teaparty_home=self.teaparty_home,
                        scope=self.scope, bus=self._bus)
                    close_ok = isinstance(result, dict) and result.get(
                        'status') in ('ok', 'noop')
                    if not close_ok:
                        _log.warning(
                            '%s _clear: close_conversation returned %r '
                            'for %s; forcing teardown',
                            self.agent_name, result, child_sid)
                except Exception:
                    _log.exception(
                        '%s _clear: close_conversation failed for %s',
                        self.agent_name, child_sid)

                if not close_ok:
                    await self._force_teardown_subtree(
                        sessions_dir, subtree, dispatch_session)

                # Fire dispatch_completed per removed session,
                # leaves-first, so the UI accordion walks upward
                # cleanly (same semantics as close_fn).
                if self._on_dispatch:
                    for csid, parent_sid in reversed(subtree):
                        self._on_dispatch({
                            'type': 'dispatch_completed',
                            'parent_session_id': parent_sid,
                            'child_session_id': csid,
                            'agent_name': agent_names.get(csid, ''),
                        })

        # 1. Cancel any in-flight dispatches not covered above
        # (belt-and-suspenders).
        await self._cancel_background_tasks()

        # 2. Stop the bus listener (kills sockets, tears down dispatch infra)
        await self.stop()

        # 3. Close this session's context tree. Chat-tier children no
        # longer have git worktrees, so the previous
        # ``git worktree remove`` pass is a no-op — the cwd is the real
        # repo and must not be removed. Any remaining worktree paths from
        # a mixed-tier run (e.g. legacy sessions) are still checked, but
        # only removed if the path is actually a worktree.
        bus_context_id = self._bus_context_id
        if bus_context_id:
            infra_dir = os.path.join(
                self.teaparty_home, self.scope, 'agents', self.agent_name,
            )
            infra_db_path = os.path.join(infra_dir, 'messages.db')
            repo_root = os.path.dirname(self.teaparty_home)
            if os.path.exists(infra_db_path):
                infra_bus = SqliteMessageBus(infra_db_path)
                try:
                    for ctx in infra_bus.open_agent_contexts_for_parent(bus_context_id):
                        wt = ctx.get('agent_worktree_path', '')
                        # Only treat as a worktree if it has a .git file
                        # (worktrees have .git as a file, not a dir).
                        if wt and os.path.isfile(os.path.join(wt, '.git')):
                            _sp.run(
                                ['git', 'worktree', 'remove', '--force', wt],
                                cwd=repo_root, capture_output=True,
                            )
                    infra_bus.close_agent_context_tree(bus_context_id)
                finally:
                    infra_bus.close()

        # 4. Clear all messages from the conversation bus
        self._bus.clear_messages(self.conversation_id)

        # 5. Reset session state
        self.claude_session_id = None
        self._bus_context_id = None
        self._dispatch_session = None
        self.save_state()

    async def _force_teardown_subtree(
        self, sessions_dir: str, subtree: list[tuple[str, str]],
        dispatch_session,
    ) -> None:
        """Tear down a subtree without attempting any merges.

        Used by ``/clear`` when ``close_conversation`` refuses to merge
        (conflict, missing branch, stale worktree, etc.). /clear is a
        destructive operator action — leaving stale session dirs on
        disk would resurrect the blades on page reload because
        ``build_dispatch_tree`` walks ``conversation_map`` without
        re-validating.

        For each (session_id, parent_id) in the subtree, leaves-first:

          - force-remove the session's git worktree (if any)
          - delete the session branch
          - rmtree the session directory
          - strip the corresponding entry from the parent's
            conversation_map on disk

        All operations are best-effort; individual failures are logged
        but do not prevent the rest of the teardown.
        """
        from teaparty.workspace.worktree import (
            remove_session_worktree, delete_branch,
        )
        from teaparty.runners.launcher import (
            load_session as _load_session,
        )

        # Walk leaves-first so we remove children before parents.
        for child_sid, parent_sid in reversed(subtree):
            session_path = os.path.join(sessions_dir, child_sid)
            meta_path = os.path.join(session_path, 'metadata.json')
            meta: dict = {}
            if os.path.isfile(meta_path):
                try:
                    with open(meta_path) as f:
                        meta = json.load(f)
                except (json.JSONDecodeError, OSError):
                    meta = {}

            worktree_path = meta.get('worktree_path') or ''
            worktree_branch = meta.get('worktree_branch') or ''
            merge_target_repo = (
                meta.get('merge_target_repo')
                or meta.get('merge_target_worktree') or '')

            if worktree_path and os.path.isdir(worktree_path):
                try:
                    await remove_session_worktree(
                        merge_target_repo or worktree_path, worktree_path)
                except Exception:
                    _log.exception(
                        '%s _clear: remove_session_worktree %s',
                        self.agent_name, worktree_path)

            if worktree_branch and merge_target_repo:
                try:
                    await delete_branch(merge_target_repo, worktree_branch)
                except Exception:
                    _log.exception(
                        '%s _clear: delete_branch %s',
                        self.agent_name, worktree_branch)

            if os.path.isdir(session_path):
                import shutil as _shutil
                _shutil.rmtree(session_path, ignore_errors=True)

            # Mark the bus record withdrawn so the accordion drops the
            # blade and the force-teardown is reflected in the single
            # source of truth (#422).  No conversation_map on disk to
            # strip — that field is gone.
            try:
                from teaparty.messaging.conversations import ConversationState
                self._bus.update_conversation_state(
                    f'dispatch:{child_sid}', ConversationState.WITHDRAWN)
            except Exception:
                _log.exception(
                    '%s _clear: bus state update for %s',
                    self.agent_name, child_sid)

    async def stop(self):
        """Stop the session: cancel background dispatches, stop bus listener.

        Call on session teardown. Ensures no orphan asyncio tasks
        continue running after the session is torn down.
        """
        await self._cancel_background_tasks()
        if self._bus_listener is not None:
            await self._bus_listener.stop()
            self._bus_listener = None
        # AskQuestionRunner holds no long-running tasks — nothing to stop.
        self._ask_question_runner = None

    # ── Subtree lifecycle loop (shared by spawn_fn and resume walker) ──

    async def _child_lifecycle_loop(
        self,
        *,
        member: str,
        child_session,
        worktree_path: str,
        composite: str,
        child_conv_id: str,
        dispatcher_session,
        repo_root: str,
        member_scope: str = '',
        member_teaparty_home: str = '',
        start_at_phase: str = 'launching',
        initial_gc_task_ids: list[str] | None = None,
        resume_claude_session: str = '',
    ) -> str:
        """Run a dispatched child through its full subtree lifecycle.

        Delegates the launch / gather-grandchildren / resume loop to the
        shared ``run_child_lifecycle`` helper, then invokes the session
        lead with the child's reply when the dispatcher was the top-level
        session.  Nested dispatches return their text up through the
        ``tasks_by_child`` fan-in.
        """
        from teaparty.messaging.child_dispatch import run_child_lifecycle

        # Legacy callers may not supply the member's placement.  Fall
        # back to the dispatcher's values so old tests and any
        # unmigrated code paths keep working unchanged.
        if not member_scope:
            member_scope = self.scope
        if not member_teaparty_home:
            member_teaparty_home = self.teaparty_home

        from teaparty.runners.launcher import launch as _launch
        response_text = await run_child_lifecycle(
            member=member,
            child_session=child_session,
            worktree_path=worktree_path,
            composite=composite,
            child_conv_id=child_conv_id,
            bus=self._bus,
            tasks_by_child=self._tasks_by_child,
            launch_fn=_launch,
            mcp_routes=self._mcp_routes,
            llm_caller=self._llm_caller,
            member_scope=member_scope,
            member_teaparty_home=member_teaparty_home,
            telemetry_scope=self._telemetry_scope,
            start_at_phase=start_at_phase,
            initial_gc_task_ids=initial_gc_task_ids,
            resume_claude_session=resume_claude_session,
        )
        if not response_text:
            return ''

        if dispatcher_session is self._dispatch_session:
            reply = f'[{child_conv_id}] {member}: {response_text}'
            try:
                await self.invoke(cwd=repo_root, resume_message=reply)
            except Exception:
                _log.exception(
                    'Failed to resume %s after %s reply',
                    self.agent_name, member,
                )
        return response_text

    def rehydrate_paused_factories(
        self, project_slug: str, sessions_dir: str,
    ) -> list[str]:
        """Rebuild _run_child_factories for every session in a project
        subtree, reading state from disk.

        The cross-restart resume path (issue #403). When the bridge
        restarts with a paused project on disk, the in-memory factories
        are gone. This walker re-creates a factory for each session by
        loading its metadata and binding a closure that calls
        _child_lifecycle_loop with the reconstructed state.

        Idempotent — called again on a live pause, each factory is
        replaced with an equivalent one.
        """
        from teaparty.runners.launcher import load_session as _load_session
        from teaparty.workspace.pause_resume import collect_project_subtree

        repo_root = os.path.dirname(self.teaparty_home)
        subtree = collect_project_subtree(sessions_dir, project_slug)
        registered: list[str] = []

        for sid, _parent in subtree:
            child_session = _load_session(
                agent_name='', scope=self.scope,
                teaparty_home=self.teaparty_home, session_id=sid,
            )
            if child_session is None:
                continue
            worktree_path = os.path.join(child_session.path, 'worktree')
            child_conv_id = f'dispatch:{child_session.id}'
            composite = (
                child_session.current_message
                or child_session.initial_message
            )

            dispatcher_sid = child_session.parent_session_id
            dispatcher_session = None
            if dispatcher_sid:
                dispatcher_session = _load_session(
                    agent_name='', scope=self.scope,
                    teaparty_home=self.teaparty_home,
                    session_id=dispatcher_sid,
                )

            # Re-resolve the member's placement from the registry so
            # the paused-resume path launches against the same scope
            # (project vs management) the original dispatch did.
            try:
                from teaparty.config.roster import resolve_launch_placement
                m_cwd, m_scope = resolve_launch_placement(
                    child_session.agent_name, self.teaparty_home,
                )
                m_home = os.path.join(m_cwd, '.teaparty')
            except Exception:
                m_scope = child_session.scope or self.scope
                m_home = self.teaparty_home

            def _make_factory(
                cs=child_session, wt=worktree_path, cv=child_conv_id,
                co=composite, ds=dispatcher_session,
                mem=child_session.agent_name,
                msc=m_scope, mhm=m_home,
            ):
                async def _factory(
                    start_at_phase: str = 'launching',
                    initial_gc_task_ids: list[str] | None = None,
                    resume_claude_session: str = '',
                ) -> str:
                    return await self._child_lifecycle_loop(
                        member=mem,
                        child_session=cs,
                        worktree_path=wt,
                        composite=co,
                        child_conv_id=cv,
                        dispatcher_session=ds,
                        repo_root=repo_root,
                        member_scope=msc,
                        member_teaparty_home=mhm,
                        start_at_phase=start_at_phase,
                        initial_gc_task_ids=initial_gc_task_ids,
                        resume_claude_session=resume_claude_session,
                    )
                return _factory

            self._run_child_factories[sid] = _make_factory()
            registered.append(sid)

        return registered

    # ── Invoke ───────────────────────────────────────────────────────────

    async def invoke(
        self, *,
        cwd: str,
        resume_message: str = '',
        launch_cwd_override: str = '',
    ) -> str:
        """Invoke the agent via the unified launcher.

        Concurrent invocations are serialized via an asyncio lock. When
        multiple children complete in parallel and each triggers a resume,
        the resumes queue up and run sequentially — each sees the previous
        turn's claude_session_id for --resume continuity.

        Args:
            cwd: Working directory for the launch.
            resume_message: Explicit message to deliver on resume (e.g.
                a child's reply). When set, bypasses the bus scan and
                uses this string directly as the resume prompt. Used by
                ``_run_child`` to hand a completed reply up to the
                parent without relaying it through the parent's bus.
            launch_cwd_override: When non-empty, bypass registry-based
                launch-cwd resolution and use this path verbatim.  The
                escalation path uses this so the proxy runs inside the
                per-escalation session directory where ``QUESTION.md``
                lives.  Normal chat invocations leave this empty.
        """
        if self._invoke_lock is None:
            self._invoke_lock = asyncio.Lock()
        async with self._invoke_lock:
            return await self._invoke_inner(
                cwd=cwd,
                resume_message=resume_message,
                launch_cwd_override=launch_cwd_override,
            )

    async def _invoke_inner(
        self, *,
        cwd: str,
        resume_message: str = '',
        launch_cwd_override: str = '',
    ) -> str:
        import time as _time
        from teaparty.runners.launcher import (
            launch, detect_poisoned_session,
            create_session as _create_session, load_session as _load_session,
        )
        from teaparty.config.roster import (
            resolve_launch_cwd, LaunchCwdNotResolved,
        )
        from teaparty.runners.launcher import chat_config_dir as _chat_cfg_dir

        t_start = _time.monotonic()
        self.load_state()

        # Handle /clear — full reset: bus messages, listener, contexts, state
        latest = self._latest_human_message()
        if latest.strip() == '/clear':
            await self._clear(cwd)
            msg = 'Session cleared.'
            self._bus.send(self.conversation_id, self.agent_role, msg)
            return msg

        is_fresh_session = self.claude_session_id is None

        # Build prompt — use hook if provided, else standard pattern.
        # On resume, deliver only the latest incoming message (sender
        # prefixed). On fresh start, deliver the full conversation.
        if self._build_prompt_hook:
            prompt = self._build_prompt_hook(self, latest)
        elif resume_message:
            prompt = resume_message
        elif self.claude_session_id:
            prompt = self._latest_incoming_with_sender()
        else:
            prompt = self.build_context()

        if not prompt:
            return ''

        # Session = worktree (1:1). Create session dir, worktree inside it.
        session_key = self._session_key()
        session = _load_session(
            agent_name=self.agent_name, scope=self.scope,
            teaparty_home=self.teaparty_home, session_id=session_key,
        )
        if session is None:
            session = _create_session(
                agent_name=self.agent_name, scope=self.scope,
                teaparty_home=self.teaparty_home, session_id=session_key,
            )

        # Chat tier: launch at the real repo root (teaparty for
        # management agents, the project repo for project leads). No
        # worktree is composed — per-launch config travels via CLI flags
        # pointed at files under .teaparty/{scope}/agents/{name}/{qualifier}/config/.
        if launch_cwd_override:
            # Escalation path: the caller already knows exactly where the
            # proxy should run (the per-escalation session directory).
            # Skip registry resolution — it would send the proxy to the
            # repo root instead and the ``/escalation`` skill's
            # ``Read ./QUESTION.md`` would fail.
            launch_cwd = launch_cwd_override
        else:
            try:
                launch_cwd = resolve_launch_cwd(
                    self.agent_name, self.teaparty_home,
                )
            except LaunchCwdNotResolved:
                # Top-level AgentSessions can legitimately run before the
                # management registry is fully populated (e.g. in unit tests
                # that exercise invoke() without a management/teaparty.yaml).
                # Fall back to the caller-supplied cwd rather than crashing
                # the whole session — this is a deliberate fallback with a
                # logged reason, not a silent one.
                _log.info(
                    '%s invoke: registry resolution unavailable; '
                    'falling back to caller cwd %s', self.agent_name, cwd,
                )
                launch_cwd = cwd
        session.launch_cwd = launch_cwd
        effective_cwd = launch_cwd
        config_dir = _chat_cfg_dir(
            self.teaparty_home, self.scope, self.agent_name, self.qualifier,
        )

        # Start bus listener for agents that dispatch.  The listener
        # also registers the agent's escalation route in the in-process
        # MCP registry — the AskQuestion tool (which runs inside the
        # bridge process, not the agent's subprocess) reads the route
        # by looking up the caller's agent name via contextvars.
        if self._dispatches:
            await self._ensure_bus_listener(cwd)

        # Stream events to bus in real-time
        stream_callback, events = _make_live_stream_relay(
            self._bus, self.conversation_id, self.agent_role,
        )

        # The launcher writes stream events to {session_dir}/stream.jsonl.
        # We read the slug from that same file after launch completes.
        stream_path = os.path.join(session.path, 'stream.jsonl')

        mcp_port = int(os.environ.get('TEAPARTY_BRIDGE_PORT', '9000'))

        launch_kwargs = dict(
            agent_name=self.agent_name,
            message=prompt,
            scope=self.scope,
            telemetry_scope=self._telemetry_scope,
            teaparty_home=self.teaparty_home,
            org_home=self._org_home,
            tier='chat',
            launch_cwd=launch_cwd,
            config_dir=config_dir,
            stream_file=stream_path,
            resume_session=self.claude_session_id or '',
            mcp_port=mcp_port,
            session_id=session.id,
            on_stream_event=stream_callback,
        )
        if self._llm_caller is not None:
            launch_kwargs['llm_caller'] = self._llm_caller
        launch_kwargs['mcp_routes'] = self._mcp_routes
        # This AgentSession's own conv_id — every dispatch it makes
        # has this as parent.  Handles OM (``om:{q}``), PM, project
        # lead (``lead:{name}:{q}``), proxy, config-lead without
        # per-role special-casing: each AgentSession knows its own
        # ``conversation_id``.
        launch_kwargs['caller_conversation_id'] = self.conversation_id
        result = await launch(**launch_kwargs)

        response_text = '\n'.join(
            c for s, c in events if s == self.agent_role
        )

        # Poisoned session detection (all agents, not just OM)
        system_events = []
        for sender, content in events:
            if sender == 'system':
                try:
                    system_events.append(json.loads(content))
                except (ValueError, json.JSONDecodeError):
                    pass
        if detect_poisoned_session(system_events):
            _log.warning(
                '%s: MCP server failed — clearing session', self.agent_name,
            )
            self.claude_session_id = None
            self.save_state()

        if not response_text:
            self.claude_session_id = None
            self.save_state()
            self._bus.send(
                self.conversation_id,
                self.agent_role,
                'I was unable to produce a response (the session may have '
                'expired). Please send your message again to start a fresh '
                'session.',
            )

        # Post-invoke hook (e.g. proxy ACT-R correction processing)
        if response_text and self._post_invoke_hook:
            self._post_invoke_hook(response_text, self)

        if response_text and result.session_id:
            self.claude_session_id = result.session_id
            if is_fresh_session and not self.conversation_title:
                slug = _extract_slug(stream_path, result.session_id, cwd)
                if slug:
                    self.conversation_title = slug
            self.save_state()

        _log.info(
            '%s invoke: %.2fs response_len=%d',
            self.agent_name, _time.monotonic() - t_start, len(response_text),
        )
        return response_text


# ── Session title reader ─────────────────────────────────────────────────────

def read_session_title(
    teaparty_home: str,
    agent_name: str,
    qualifier: str,
    scope: str = 'management',
) -> str | None:
    """Read the conversation title from a saved session's metadata.json."""
    if qualifier:
        safe_id = qualifier.replace('/', '-').replace(':', '-').replace(' ', '-')
        session_key = f'{agent_name}-{safe_id}'
    else:
        session_key = agent_name
    sessions_dir = os.path.join(teaparty_home, scope, 'sessions')
    meta_path = os.path.join(sessions_dir, session_key, 'metadata.json')
    try:
        with open(meta_path) as f:
            state = json.load(f)
        return state.get('conversation_title') or None
    except (FileNotFoundError, json.JSONDecodeError):
        return None
