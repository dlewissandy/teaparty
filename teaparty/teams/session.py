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
        self._bus_listener_sockets: tuple[str, str, str] | None = None
        self._bus_context_id: str | None = None
        self._dispatch_session = None

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
        meta = {
            'session_id': session.id,
            'agent_name': session.agent_name,
            'scope': session.scope,
            'claude_session_id': self.claude_session_id or '',
            'conversation_map': session.conversation_map,
            'conversation_title': self.conversation_title or '',
            'qualifier': self.qualifier,
            'conversation_id': self.conversation_id,
        }
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
        """Start the BusEventListener for agents that dispatch via Send."""
        if self._bus_listener is not None:
            send, reply, close = self._bus_listener_sockets
            return {
                'SEND_SOCKET': send,
                'REPLY_SOCKET': reply,
                'CLOSE_CONV_SOCKET': close,
                'AGENT_ID': self.agent_name,
                'PYTHONPATH': cwd,
            }

        from teaparty.messaging.listener import BusEventListener
        from teaparty.runners.launcher import (
            launch as _launch,
            create_session as _create_session,
            record_child_session as _record_child,
            remove_child_session as _remove_child,
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
            stable_id = f'{self.agent_name}-{self.qualifier}'
            try:
                self._dispatch_session = _load_session(
                    agent_name=self.agent_name, scope=self.scope,
                    teaparty_home=self.teaparty_home,
                    session_id=stable_id,
                )
            except Exception:
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

        async def spawn_fn(member, composite, context_id):
            import time as _time
            import asyncio as _asyncio
            from teaparty.teams.stream import _classify_event
            from teaparty.config.roster import (
                resolve_launch_cwd, LaunchCwdNotResolved,
            )
            from teaparty.workspace.worktree import (
                default_branch_of, current_branch_of, head_commit_of,
                create_subchat_worktree,
            )
            from teaparty.mcp.registry import (
                register_spawn_fn as _register,
                current_session_id as _current_session_var,
            )

            # Determine which session is dispatching.
            caller_sid = _current_session_var.get('')
            dispatcher_session = session_registry.get(
                caller_sid, self._dispatch_session)

            if not _check_slot(dispatcher_session):
                _log.warning(
                    '%s spawn_fn: at conversation limit, dispatch to %s blocked',
                    self.agent_name, member,
                )
                return ('', '', '')

            # Refuse new dispatches while the project is paused (issue #403).
            if self._paused_check is not None and self._paused_check():
                _log.warning(
                    '%s spawn_fn: project %s paused, dispatch to %s refused',
                    self.agent_name, self.project_slug, member,
                )
                return ('', '', '')

            # Resolve the member's natural repo (the repo whose
            # configuration places this agent). Unknown members are a
            # configuration error — refuse the dispatch.
            try:
                member_natural_repo = resolve_launch_cwd(
                    member, self.teaparty_home,
                )
            except LaunchCwdNotResolved as exc:
                _log.error(
                    '%s spawn_fn: refusing dispatch to %s — %s',
                    self.agent_name, member, exc,
                )
                return ('', '', '')

            # The dispatcher's current working state is the integration
            # branch for same-repo dispatches. For a privileged top-level
            # (OM or a project lead at top), the dispatcher works
            # directly in the real repo; for a nested dispatcher it
            # works inside its own session worktree.
            if dispatcher_session.worktree_path:
                dispatcher_worktree = dispatcher_session.worktree_path
                dispatcher_repo = (
                    dispatcher_session.merge_target_repo or repo_root
                )
            else:
                dispatcher_worktree = (
                    dispatcher_session.launch_cwd or repo_root
                )
                dispatcher_repo = dispatcher_worktree

            is_cross_repo = (
                os.path.realpath(member_natural_repo)
                != os.path.realpath(dispatcher_repo)
            )

            # Pick the fork source and the merge-back target.
            if is_cross_repo:
                source_repo = member_natural_repo
                source_ref = await default_branch_of(source_repo)
                merge_target_repo = source_repo
                merge_target_branch = source_ref
                merge_target_worktree = source_repo
            else:
                source_repo = dispatcher_repo
                # Fork from the dispatcher's current HEAD — parent's
                # committed state is the integration point. Uncommitted
                # edits in the dispatcher's worktree are intentionally
                # invisible to the child.
                source_ref = await head_commit_of(dispatcher_worktree) or 'HEAD'
                merge_target_repo = dispatcher_repo
                merge_target_worktree = dispatcher_worktree
                merge_target_branch = (
                    await current_branch_of(dispatcher_worktree)
                )

            # Create the child session record first so the worktree can
            # live under its directory.
            child_session = _create_session(
                agent_name=member, scope=self.scope,
                teaparty_home=self.teaparty_home,
            )

            if is_cross_repo:
                # Cross-repo dispatch (e.g. OM → project lead): the project
                # lead works directly at its own repo root — no worktree.
                # Config files are composed under the dispatcher's teaparty
                # home just like a top-level invoke().
                worktree_path = ''
                session_branch = ''
                child_session.launch_cwd = member_natural_repo
                child_session.worktree_path = ''
                child_session.worktree_branch = ''
                child_session.merge_target_repo = ''
                child_session.merge_target_branch = ''
                child_session.merge_target_worktree = ''
                member_launch_cwd = member_natural_repo
            else:
                worktree_path = os.path.join(child_session.path, 'worktree')
                session_branch = f'session/{child_session.id}'
                try:
                    await create_subchat_worktree(
                        source_repo=source_repo,
                        source_ref=source_ref,
                        dest_path=worktree_path,
                        branch_name=session_branch,
                    )
                except Exception:
                    _log.exception(
                        '%s spawn_fn: git worktree add failed for %s',
                        self.agent_name, member,
                    )
                    return ('', '', '')
                child_session.launch_cwd = worktree_path
                child_session.worktree_path = worktree_path
                child_session.worktree_branch = session_branch
                child_session.merge_target_repo = merge_target_repo
                child_session.merge_target_branch = merge_target_branch
                child_session.merge_target_worktree = merge_target_worktree
                member_launch_cwd = worktree_path

            _save_meta(child_session)

            # Record parent/project on the child so the pause walker can
            # reconstruct the tree from disk (issue #403).
            child_session.parent_session_id = dispatcher_session.id
            child_session.project_slug = getattr(
                self, 'project_slug', '') or ''
            child_session.initial_message = composite
            # phase and current_message are set by mark_launching on
            # every loop iteration — do not pre-seed them here.
            _save_meta(child_session)

            # Register the child's session so its dispatches are recorded
            # in its own conversation_map.
            session_registry[child_session.id] = child_session

            # Record in dispatcher's conversation_map so the accordion
            # shows the child while running.
            child_conv_id = f'dispatch:{child_session.id}'
            _record_child(dispatcher_session,
                          request_id=context_id,
                          child_session_id=child_session.id)

            if self._on_dispatch:
                self._on_dispatch({
                    'type': 'dispatch_started',
                    'parent_session_id': dispatcher_session.id,
                    'child_session_id': child_session.id,
                    'agent_name': member,
                })

            # If the child can dispatch, register the same spawn_fn.
            try:
                from teaparty.config.roster import has_sub_roster
                if has_sub_roster(member, self.teaparty_home):
                    _register(member, spawn_fn)
            except Exception:
                _log.debug('Sub-roster check failed for %s', member, exc_info=True)

            # Write the parent's request to the bus (visible in child chat).
            self._bus.send(child_conv_id, self.agent_name, composite)

            # ── Launch the child as a background task ────────────────────
            # Send returns immediately with the conversation handle.
            # The child runs asynchronously; its response is written to
            # the parent's bus when it completes.

            async def _run_child(
                start_at_phase: str = 'launching',
                initial_gc_task_ids: list[str] | None = None,
                resume_claude_session: str = '',
            ) -> str:
                return await self._child_lifecycle_loop(
                    member=member,
                    child_session=child_session,
                    worktree_path=worktree_path,
                    composite=composite,
                    child_conv_id=child_conv_id,
                    dispatcher_session=dispatcher_session,
                    repo_root=repo_root,
                    start_at_phase=start_at_phase,
                    initial_gc_task_ids=initial_gc_task_ids,
                    resume_claude_session=resume_claude_session,
                )

            self._run_child_factories[child_session.id] = _run_child
            task = _asyncio.create_task(_run_child())
            self._background_tasks.add(task)
            self._tasks_by_child[child_session.id] = task
            # Only discard from _background_tasks on done; keep the
            # entry in _tasks_by_child so a parent _run_child's loop
            # can still find the (already completed) grandchild task
            # and collect its result via `await task`. The race here
            # is: a grandchild often completes while its parent is
            # still inside its first _launch call (they run concurrently
            # on the event loop), so by the time the parent's loop gets
            # to gc_tasks the grandchild's task may already be done.
            # Popping eagerly dropped the task reference and broke the
            # resume chain — the parent thought there was nothing to
            # wait for and finalized with stale first-turn text.
            # close_fn / _cancel_background_tasks clean up the dict on
            # explicit teardown; /clear clears it at session reset.
            task.add_done_callback(self._background_tasks.discard)

            # Return immediately — child runs in background. The second
            # element used to be a worktree path; chat tier returns the
            # launch_cwd instead (the agent's real repo). Callers that
            # stored this as ``agent_worktree_path`` use it only as an
            # opaque cwd handle for resume.
            _log.info('%s spawn_fn: dispatched to %s (async)',
                      self.agent_name, member)
            return (child_session.id, member_launch_cwd, '')

        async def resume_fn(member, composite, session_id, context_id):
            # Resume path: a peer Send landed on an existing open
            # subchat. The child session is still alive in its
            # per-session worktree; re-launch at that same worktree
            # with --resume so claude picks the conversation up.
            child_session_id = ''
            if context_id and context_id.startswith('dispatch:'):
                child_session_id = context_id[len('dispatch:'):]

            existing = None
            if child_session_id:
                existing = _load_session(
                    agent_name=member, scope=self.scope,
                    teaparty_home=self.teaparty_home,
                    session_id=child_session_id,
                )
            if existing is None or not existing.worktree_path:
                _log.error(
                    '%s resume_fn: no live worktree for child session '
                    '%s — cannot resume %s',
                    self.agent_name, child_session_id, member,
                )
                return ''

            mcp_port = int(os.environ.get('TEAPARTY_BRIDGE_PORT', '9000'))
            result = await _launch(
                agent_name=member, message=composite,
                scope=self.scope, teaparty_home=self.teaparty_home,
                telemetry_scope=self._telemetry_scope,
                worktree=existing.worktree_path,
                resume_session=session_id, mcp_port=mcp_port,
                session_id=child_session_id,
            )
            return result.session_id

        async def reply_fn(context_id, session_id, message):
            _log.info('%s reply_fn: delivering reply for context %s',
                      self.agent_name, context_id)
            self._bus.send(self.conversation_id, self.agent_role, message)
            _remove_child(dispatch_session, request_id=context_id)

        async def reinvoke_fn(context_id, session_id, message):
            _log.info('%s reinvoke_fn: fan-in complete for context %s',
                      self.agent_name, context_id)

        async def cleanup_fn(worktree_path):
            # Chat tier no longer creates git worktrees for dispatched
            # children — the cwd is the real repo and must not be
            # removed. Session dir teardown is handled separately by
            # close_conversation. This function is a no-op for chat,
            # retained so the bus listener contract stays stable.
            return

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
            spawn_fn=spawn_fn,
            resume_fn=resume_fn,
            reply_fn=reply_fn,
            reinvoke_fn=reinvoke_fn,
            cleanup_fn=cleanup_fn,
        )
        sockets = await self._bus_listener.start()
        self._bus_listener_sockets = sockets

        from teaparty.mcp.registry import register_spawn_fn, register_close_fn
        register_spawn_fn(self.agent_name, spawn_fn)

        async def close_fn(conversation_id):
            from teaparty.workspace.close_conversation import (
                close_conversation, collect_descendants_with_parents,
            )
            # Collect every (session, parent) pair in the subtree rooted
            # at this conversation (walks metadata on disk, depth-first).
            # Needed to (a) cancel every in-flight _run_child task before
            # close_conversation rmtrees the dirs and (b) emit one
            # dispatch_completed event per removed session so the UI
            # accordion auto-activates the parent of whatever the user
            # is currently viewing.
            subtree: list[tuple[str, str]] = []
            if conversation_id.startswith('dispatch:'):
                root_csid = conversation_id[len('dispatch:'):]
                sessions_dir = os.path.join(
                    self.teaparty_home, self.scope, 'sessions')
                subtree = collect_descendants_with_parents(
                    sessions_dir, root_csid,
                    root_parent=self._dispatch_session.id)
                tasks = []
                for csid, _parent in subtree:
                    task = self._tasks_by_child.pop(csid, None)
                    if task is not None and not task.done():
                        task.cancel()
                        tasks.append(task)
                if tasks:
                    try:
                        await asyncio.wait_for(
                            asyncio.shield(
                                asyncio.gather(*tasks, return_exceptions=True)),
                            timeout=2.0)
                    except asyncio.TimeoutError:
                        _log.warning(
                            '%s close_fn: tasks did not cancel within 2s',
                            self.agent_name)

            # Read each descendant's agent_name from metadata BEFORE
            # close_conversation removes the session dirs — we need the
            # label for the UI event payload.
            agent_names: dict[str, str] = {}
            if subtree:
                import json as _json
                sessions_dir = os.path.join(
                    self.teaparty_home, self.scope, 'sessions')
                for csid, _parent in subtree:
                    meta_path = os.path.join(
                        sessions_dir, csid, 'metadata.json')
                    try:
                        with open(meta_path) as f:
                            agent_names[csid] = _json.load(f).get(
                                'agent_name', '')
                    except (OSError, _json.JSONDecodeError):
                        agent_names[csid] = ''

            close_result = await close_conversation(
                self._dispatch_session, conversation_id,
                teaparty_home=self.teaparty_home, scope=self.scope,
            )
            # If the merge failed, return the structured result so the
            # calling agent's CloseConversation tool surface can show
            # the conflict details. Do NOT emit dispatch_completed
            # events — the subchat is still open, its worktree is
            # still on disk, and the accordion must keep it visible.
            if close_result.get('status') not in ('ok', 'noop'):
                return close_result

            # Notify the UI so the accordion re-renders and auto-expands
            # the parent of each removed session (in particular, the
            # parent of whichever subtree node the user is viewing).
            # Depth-first order means leaves first — the UI receives
            # each removal before the ancestor that would override it.
            if self._on_dispatch:
                for csid, parent_sid in reversed(subtree):
                    self._on_dispatch({
                        'type': 'dispatch_completed',
                        'parent_session_id': parent_sid,
                        'child_session_id': csid,
                        'agent_name': agent_names.get(csid, ''),
                    })
            return close_result

        register_close_fn(self.agent_name, close_fn)

        send, reply, close = sockets
        return {
            'SEND_SOCKET': send,
            'REPLY_SOCKET': reply,
            'CLOSE_CONV_SOCKET': close,
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
            close_conversation, collect_descendants_with_parents,
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

        if dispatch_session is not None and dispatch_session.conversation_map:
            sessions_dir = os.path.join(
                self.teaparty_home, self.scope, 'sessions')
            top_level_ids = list(
                dispatch_session.conversation_map.values())

            for child_sid in top_level_ids:
                # Walk subtree to enumerate every descendant that
                # needs a dispatch_completed event.
                subtree = collect_descendants_with_parents(
                    sessions_dir, child_sid,
                    root_parent=dispatch_session.id)

                # Read agent_name from each descendant's metadata
                # before close_conversation removes the dir.
                agent_names: dict[str, str] = {}
                for csid, _parent in subtree:
                    meta_path = os.path.join(
                        sessions_dir, csid, 'metadata.json')
                    try:
                        import json as _json
                        with open(meta_path) as f:
                            agent_names[csid] = _json.load(f).get(
                                'agent_name', '')
                    except (OSError, ValueError):
                        agent_names[csid] = ''

                # Cancel any live tasks in this subtree (fresh-server
                # case has no live tasks; re-invocation case might).
                for csid, _parent in subtree:
                    t = self._tasks_by_child.pop(csid, None)
                    if t is not None and not t.done():
                        t.cancel()

                # Filesystem teardown: rmtree session dirs, remove
                # entry from parent's conversation_map on disk.
                try:
                    await close_conversation(
                        dispatch_session, f'dispatch:{child_sid}',
                        teaparty_home=self.teaparty_home,
                        scope=self.scope)
                except Exception:
                    _log.exception(
                        '%s _clear: close_conversation failed for %s',
                        self.agent_name, child_sid)

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

    async def stop(self):
        """Stop the session: cancel background dispatches, stop bus listener.

        Call on session teardown. Ensures no orphan asyncio tasks
        continue running after the session is torn down.
        """
        await self._cancel_background_tasks()
        if self._bus_listener is not None:
            await self._bus_listener.stop()
            self._bus_listener = None
            self._bus_listener_sockets = None

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
        start_at_phase: str = 'launching',
        initial_gc_task_ids: list[str] | None = None,
        resume_claude_session: str = '',
    ) -> str:
        """Run a dispatched child through its full subtree lifecycle.

        Shared by spawn_fn's newly-spawned children and by the cross-
        restart resume walker (issue #403). Caller supplies everything
        that would normally live in spawn_fn's closure.

        Loop:
          1. Launch — writes phase='launching' + current_message before
             the await so a pause cancellation lands accurately.
          2. If new grandchildren spawned, writes phase='awaiting' with
             their ids and gathers on their tasks.
          3. Re-enters launch with --resume and the integrated replies.
          4. Repeats until a turn produces no new dispatches.

        ``start_at_phase='awaiting'`` skips the initial _launch and
        enters directly at gather — the path that avoids re-running an
        already-completed turn on awaiting-phase resume.
        """
        import asyncio as _asyncio
        import time as _time
        from teaparty.teams.stream import _classify_event
        from teaparty.runners.launcher import (
            launch as _launch,
            _save_session_metadata as _save_meta,
            mark_launching as _mark_launching,
            mark_awaiting as _mark_awaiting,
            mark_complete as _mark_complete,
        )

        t0 = _time.monotonic()
        seen_tu: set[str] = set()
        seen_tr: set[str] = set()
        response_parts: list[str] = []

        def on_event(ev: dict) -> None:
            for sender, content in _classify_event(ev, member, seen_tu, seen_tr):
                if content and sender != 'tool_result':
                    self._bus.send(child_conv_id, sender, content)
                if sender == member and content:
                    response_parts.append(content)

        mcp_port = int(os.environ.get('TEAPARTY_BRIDGE_PORT', '9000'))
        current_claude_session = resume_claude_session or ''
        current_message = composite

        if start_at_phase == 'awaiting':
            gc_tasks = [
                self._tasks_by_child[g]
                for g in (initial_gc_task_ids or [])
                if g in self._tasks_by_child
            ]
            if gc_tasks:
                _mark_awaiting(
                    child_session, list(initial_gc_task_ids or []))
                gc_results = await _asyncio.gather(
                    *gc_tasks, return_exceptions=True)
                gc_replies: list[str] = []
                for gid, r in zip(initial_gc_task_ids or [], gc_results):
                    if isinstance(r, str) and r:
                        gc_replies.append(f'[dispatch:{gid}] {r}')
                if gc_replies:
                    current_message = '\n'.join(gc_replies)

        while True:
            before_ids = set(child_session.conversation_map.values())
            response_parts.clear()

            if worktree_path:
                # Same-repo dispatch: child runs inside its own
                # per-session git worktree (job tier).
                launch_kwargs = dict(
                    agent_name=member, message=current_message,
                    scope=self.scope, teaparty_home=self.teaparty_home,
                    telemetry_scope=self._telemetry_scope,
                    worktree=worktree_path,
                    mcp_port=mcp_port,
                    session_id=child_session.id,
                    stream_file=os.path.join(child_session.path, 'stream.jsonl'),
                    on_stream_event=on_event,
                )
            else:
                # Cross-repo dispatch: child is a project lead running
                # directly at its own repo root (chat tier). Config
                # files are composed under the dispatcher's teaparty
                # home, same as a top-level invoke().
                from teaparty.runners.launcher import chat_config_dir as _chat_cfg_dir
                child_config_dir = _chat_cfg_dir(
                    self.teaparty_home, self.scope,
                    member, child_session.id,
                )
                launch_kwargs = dict(
                    agent_name=member, message=current_message,
                    scope=self.scope, teaparty_home=self.teaparty_home,
                    telemetry_scope=self._telemetry_scope,
                    tier='chat',
                    launch_cwd=child_session.launch_cwd,
                    config_dir=child_config_dir,
                    mcp_port=mcp_port,
                    session_id=child_session.id,
                    stream_file=os.path.join(child_session.path, 'stream.jsonl'),
                    on_stream_event=on_event,
                )
            if current_claude_session:
                launch_kwargs['resume_session'] = current_claude_session
            if self._llm_caller is not None:
                launch_kwargs['llm_caller'] = self._llm_caller

            try:
                _mark_launching(child_session, current_message)
                result = await _launch(**launch_kwargs)
                if result.session_id:
                    child_session.claude_session_id = result.session_id
                    current_claude_session = result.session_id
                    _save_meta(child_session)
            except Exception:
                _log.exception('Child %s failed', member)
                break

            after_ids = set(child_session.conversation_map.values())
            new_gc_ids = after_ids - before_ids
            if not new_gc_ids:
                break

            gc_tasks = [
                self._tasks_by_child[g] for g in new_gc_ids
                if g in self._tasks_by_child
            ]
            if not gc_tasks:
                break
            _mark_awaiting(child_session, list(new_gc_ids))
            gc_results = await _asyncio.gather(
                *gc_tasks, return_exceptions=True)
            gc_replies: list[str] = []
            for gid, r in zip(new_gc_ids, gc_results):
                if isinstance(r, str) and r:
                    gc_replies.append(f'[dispatch:{gid}] {r}')
                elif isinstance(r, Exception) and not isinstance(
                        r, _asyncio.CancelledError):
                    _log.warning('Grandchild %s raised: %s', gid, r)
            if not gc_replies:
                break
            current_message = '\n'.join(gc_replies)

        _log.info('%s subtree: %s completed in %.2fs',
                  self.agent_name, member, _time.monotonic() - t0)

        response_text = '\n'.join(response_parts)
        _mark_complete(child_session, response_text)
        if not response_text:
            return ''

        if dispatcher_session is self._dispatch_session:
            reply = f'[{child_conv_id}] {member}: {response_text}'
            try:
                await self.invoke(cwd=repo_root, resume_message=reply)
            except Exception:
                _log.exception('Failed to resume %s after %s reply',
                               self.agent_name, member)
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

            def _make_factory(
                cs=child_session, wt=worktree_path, cv=child_conv_id,
                co=composite, ds=dispatcher_session,
                mem=child_session.agent_name,
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
                        start_at_phase=start_at_phase,
                        initial_gc_task_ids=initial_gc_task_ids,
                        resume_claude_session=resume_claude_session,
                    )
                return _factory

            self._run_child_factories[sid] = _make_factory()
            registered.append(sid)

        return registered

    # ── Invoke ───────────────────────────────────────────────────────────

    async def invoke(self, *, cwd: str, resume_message: str = '') -> str:
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
        """
        if self._invoke_lock is None:
            self._invoke_lock = asyncio.Lock()
        async with self._invoke_lock:
            return await self._invoke_inner(
                cwd=cwd, resume_message=resume_message)

    async def _invoke_inner(self, *, cwd: str, resume_message: str = '') -> str:
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

        # Start bus listener for agents that dispatch
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
