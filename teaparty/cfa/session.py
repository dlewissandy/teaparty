"""Session lifecycle — the top-level entry point.

Task classification, worktree setup, memory retrieval, orchestration,
merge, and learning extraction.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from teaparty.cfa.statemachine.cfa_state import (
    CfaState,
    load_state,
    is_globally_terminal,
    make_initial_state,
    save_state,
)
from teaparty.cfa.actors import InputProvider
from teaparty.cfa.engine import Orchestrator, OrchestratorResult
from teaparty.messaging.bus import Event, EventBus, EventType
from teaparty.proxy.hooks import proxy_home
from teaparty.learning.extract import extract_learnings
from teaparty.workspace.merge import (
    commit_deliverables, squash_merge, MergeConflictEscalation,
    MergeVerificationError,
)
from teaparty.messaging.conversations import (
    ConversationType, MessageBusInputProvider, SqliteMessageBus,
    make_conversation_id,
)
from teaparty.config.config_reader import (
    load_project_team, load_management_team, resolve_norms,
    resolve_workgroups,
)
from teaparty.cfa.phase_config import PhaseConfig
from teaparty.util.role_enforcer import RoleEnforcer
from teaparty.bridge.state.writer import StateWriter
from teaparty.workspace.job_store import create_job, release_worktree

_log = logging.getLogger('teaparty')


def _make_stream_bus_writer(bus: SqliteMessageBus, conversation_id: str, session_id: str):
    """Return an async event callback that writes typed stream events to the message bus.

    Writes to conversation_id with senders:
      state — from STATE_CHANGED events (CfA state transitions)
      log   — from LOG events (diagnostic messages)
      cost  — from TURN_COST events (per-actor-turn stats: total_cost_usd, input_tokens, output_tokens, duration_ms)

    Events from a different session_id are ignored.
    """
    async def _on_event(event: Event) -> None:
        if event.session_id and event.session_id != session_id:
            return
        if event.type == EventType.STATE_CHANGED:
            prev = event.data.get('previous_state', '')
            state = event.data.get('state', '')
            action = event.data.get('action', '')
            bus.send(conversation_id, 'state', f'{prev} → {state} [{action}]')
        elif event.type == EventType.LOG:
            msg = event.data.get('message', '')
            if msg:
                bus.send(conversation_id, 'log', msg)
        elif event.type == EventType.TURN_COST:
            stats = {}
            for key in ('total_cost_usd', 'input_tokens', 'output_tokens', 'duration_ms'):
                val = event.data.get(key)
                if val is not None:
                    stats[key] = val
            if stats:
                bus.send(conversation_id, 'cost', json.dumps(stats))
    return _on_event


def _resolve_project_lead_sender(project_dir: str) -> str:
    """Return the project lead name for gate-prompt sender attribution.

    Reads project.yaml and returns its 'lead' field, or 'orchestrator' if
    no lead is configured or the file cannot be read.  Used by the resume
    path to match the fresh-run sender resolution in Session.run().
    """
    try:
        return load_project_team(project_dir).lead or 'orchestrator'
    except (FileNotFoundError, OSError):
        return 'orchestrator'


# ── Per-type retrieval budget allocation (characters) ─────────────────────────
# Institutional learnings are loaded in full (uncapped, like CLAUDE.md).
# Task-based and proxy-task learnings are fuzzy-retrieved with these budgets.
# Values are character counts (≈ tokens × 4). Tune empirically.
TASK_LEARNING_BUDGET_CHARS = 8000     # ~2000 tokens of task learnings
PROXY_LEARNING_BUDGET_CHARS = 4000    # ~1000 tokens of proxy task patterns


@dataclass
class SessionResult:
    terminal_state: str
    project: str
    session_id: str
    backtrack_count: int = 0


class Session:
    """Complete session lifecycle: classify → worktree → orchestrate → merge → learn."""

    def __init__(
        self,
        task: str,
        *,
        poc_root: str,
        projects_dir: str | None = None,
        project_override: str | None = None,
        session_id: str | None = None,
        intent_file: str | None = None,
        plan_file: str | None = None,
        show_memory: bool = False,
        dry_run: bool = False,
        skip_learnings: bool = False,
        verbose: bool = False,
        flat: bool = False,
        suppress_backtracks: bool = False,
        proxy_enabled: bool = True,
        event_bus: EventBus | None = None,
        input_provider: InputProvider | None = None,
        learning_retrieval_mode: str = 'flat',
        skip_learning_retrieval: bool = False,
        humans: list | None = None,
        escalation_modes: dict[str, str] | None = None,
        llm_caller: Any = None,
        proxy_invoker_fn: Any = None,
        on_dispatch: Any = None,
        paused_check: Any = None,
    ):
        self.task = task
        self.poc_root = poc_root
        self.projects_dir = projects_dir or os.path.dirname(poc_root)
        self.project_override = project_override
        self._preset_session_id = session_id
        self.intent_file = intent_file
        self.plan_file = plan_file
        self.show_memory = show_memory
        self.dry_run = dry_run
        self.skip_learnings = skip_learnings
        self.verbose = verbose
        self.flat = flat
        self.suppress_backtracks = suppress_backtracks
        self.proxy_enabled = proxy_enabled
        self.event_bus = event_bus or EventBus()
        self.input_provider = input_provider
        self.learning_retrieval_mode = learning_retrieval_mode
        self.skip_learning_retrieval = skip_learning_retrieval
        self._role_enforcer = RoleEnforcer.from_humans(humans) if humans else None
        self.escalation_modes = escalation_modes or {}
        self._llm_caller = llm_caller
        # Bridge-supplied hooks used by the CfA engine's AskQuestionRunner
        # so AskQuestion from a job agent routes through the same
        # /escalation skill + accordion path as chat-tier AgentSession.
        self._proxy_invoker_fn = proxy_invoker_fn
        self._on_dispatch = on_dispatch
        self._paused_check = paused_check

        # Resolved during run
        self.project_slug = ''
        self.session_id = ''
        self.session_info: dict = {}
        self.config = PhaseConfig(poc_root)  # re-created with project_dir in run()

    async def run(self) -> SessionResult:
        """Execute the full session lifecycle."""
        # 1. Classify task → project slug + task mode
        self.project_slug, task_mode = self._classify_task()
        self.session_id = self._preset_session_id or datetime.now().strftime('%Y%m%d-%H%M%S')

        # Conversational tasks skip intent alignment — there's no
        # idea to align on, just a request to respond to.  Recorded
        # here and consumed at cfa-state initialization below.
        self._conversational = (task_mode == 'conversational')

        # 2. Ensure project directory exists
        project_dir = os.path.join(self.projects_dir, self.project_slug)
        os.makedirs(project_dir, exist_ok=True)

        # 2b. Re-create config with project-scoped overrides (issue #10)
        self.config = PhaseConfig(self.poc_root, project_dir=project_dir)

        # 3. Find repo root (project may have its own .git)
        repo_root = self._find_repo_root(project_dir)

        # 4. Create job worktree — job_dir serves as infra_dir
        self.session_info = await create_job(
            project_root=repo_root,
            task=self.task,
            session_id=self.session_id,
        )

        infra_dir = self.session_info['job_dir']
        worktree_path = self.session_info['worktree_path']

        # 4a. Create message bus for persistent human-agent communication (Issue #200).
        bus_path = os.path.join(infra_dir, 'messages.db')
        self._message_bus = SqliteMessageBus(bus_path)
        try:
            if self._role_enforcer:
                self._message_bus.role_enforcer = self._role_enforcer
            # Use JOB conversation type so the job chat URL (job:{project}:{session_id})
            # matches the conversation in the DB (Issue #341).
            self._conversation_id = make_conversation_id(
                ConversationType.JOB, f'{self.project_slug}:{self.session_id}',
            )
            # Writer-side single source of truth (#422): the JOB row
            # carries the project lead's agent_name so the accordion
            # blade displays it without prefix-derivation guesswork.
            _lead_name = (
                self.config.project_lead
                or f'{self.project_slug}-lead'
            )
            self._message_bus.create_conversation(
                ConversationType.JOB,
                f'{self.project_slug}:{self.session_id}',
                agent_name=_lead_name,
                project_slug=self.project_slug,
            )
            # Post the initial task as the first human message so it appears in
            # the chat window immediately.
            self._message_bus.send(self._conversation_id, 'human', self.task)
            self._bus_input_provider = MessageBusInputProvider(
                bus=self._message_bus,
                conversation_id=self._conversation_id,
                sender=self.config.project_lead or 'orchestrator',
            )

            # 4b. Copy pre-written artifacts into the worktree so they are
            # visible in the file tree and accessible to the agent.
            if self.intent_file:
                shutil.copy2(self.intent_file, os.path.join(worktree_path, 'INTENT.md'))
            if self.plan_file:
                shutil.copy2(self.plan_file, os.path.join(worktree_path, 'PLAN.md'))

            # Persist the full prompt so it's never lost to truncation.
            with open(os.path.join(infra_dir, 'PROMPT.txt'), 'w') as f:
                f.write(self.task)

            # IDEA.md is the artifact the intent-alignment skill reads as
            # its starting point. The raw task string IS the user's idea;
            # seeding it into the worktree lets the skill run verbatim
            # from its START → ALIGN/DRAFT branch without a separate
            # engine-side transformation. Gitignored alongside INTENT.md.
            with open(os.path.join(worktree_path, 'IDEA.md'), 'w') as f:
                f.write(self.task)

            # 5. Start state writer (filesystem persistence)
            state_writer = StateWriter(infra_dir, self.event_bus)
            await state_writer.start()

            # 5a. Start stream bus writer (typed senders → message bus)
            bus_writer = _make_stream_bus_writer(
                self._message_bus, self._conversation_id, self.session_id,
            )
            self.event_bus.subscribe(bus_writer)

            # 6. Publish session start
            await self.event_bus.publish(Event(
                type=EventType.SESSION_STARTED,
                data={
                    'task': self.task,
                    'project': self.project_slug,
                    'session_id': self.session_id,
                    'worktree': worktree_path,
                    'message_bus_path': bus_path,
                    'conversation_id': self._conversation_id,
                },
                session_id=self.session_id,
            ))

            # Telemetry: session_create (Issue #405)
            try:
                from teaparty.telemetry import record_event
                from teaparty.telemetry import events as _telem_events
                record_event(
                    _telem_events.SESSION_CREATE,
                    scope=self.project_slug or 'management',
                    session_id=self.session_id,
                    data={
                        'qualifier': self._conversation_id,
                        'parent_session_id': '',
                        'dispatch_message_len': len(self.task),
                        'purpose': 'normal',
                    },
                )
            except Exception:
                pass

            # 7. Initialize CfA state at the correct starting point.
            # Pre-supplied artifacts shift the start phase; otherwise
            # we begin at INTENT.  No phase-control flags — context
            # (file presence) IS the signal.
            from teaparty.cfa.statemachine.cfa_state import State, set_state_direct
            cfa = make_initial_state(task_id=self.session_id)

            if self.plan_file:
                # Pre-written PLAN.md: skip to execution.
                cfa = set_state_direct(cfa, State.EXECUTE)
            elif self.intent_file or self._conversational:
                # Pre-written INTENT.md, or conversational task with
                # nothing to align on: skip to planning.
                cfa = set_state_direct(cfa, State.PLAN)

            save_state(cfa, os.path.join(infra_dir, '.cfa-state.json'))

            # 8. Retrieve memory context
            memory_context = self._retrieve_memory(project_dir)

            # 8b. Show memory context if requested
            if self.show_memory or self.dry_run:
                self._print_memory_context(memory_context)

            if self.dry_run:
                await self.event_bus.publish(Event(
                    type=EventType.SESSION_COMPLETED,
                    data={'terminal_state': 'DRY_RUN', 'backtrack_count': 0},
                    session_id=self.session_id,
                ))
                await state_writer.stop()
                self.event_bus.unsubscribe(bus_writer)
                return SessionResult(
                    terminal_state='DRY_RUN',
                    project=self.project_slug,
                    session_id=self.session_id,
                )

            # 9. Build task prompt with context
            task_prompt = self.task
            if memory_context:
                task_prompt = f"{self.task}\n\n{memory_context}"

            # 9b. Inject norms from configuration tree (Issue #257)
            norms_text = self._resolve_norms(project_dir)
            if norms_text:
                task_prompt = f"{task_prompt}\n\n{norms_text}"

            # 10. Run orchestrator — use message bus input provider for persistent
            # communication (Issue #200).  Falls back to the original input_provider
            # if the bus provider is unavailable (e.g., no-human mode).
            proxy_model_path = os.path.join(proxy_home(os.path.join(self.poc_root, '.teaparty')), '.proxy-confidence.json')
            # An explicitly-set input_provider (e.g. in tests) takes precedence over
            # the message-bus provider.  In production the input_provider is None and
            # the bus provider handles all gate interactions.
            effective_input = self.input_provider or self._bus_input_provider

            # Cut 29: human INTERVENE delivery reads bus messages
            # directly at turn boundary; no separate queue.

            from teaparty.cfa.run_options import RunOptions
            orchestrator = Orchestrator(
                cfa_state=cfa,
                phase_config=self.config,
                event_bus=self.event_bus,
                input_provider=effective_input,
                infra_dir=infra_dir,
                project_workdir=project_dir,
                session_worktree=worktree_path,
                proxy_model_path=proxy_model_path,
                project_slug=self.project_slug,
                poc_root=self.poc_root,
                task=task_prompt,
                session_id=self.session_id,
                options=RunOptions(
                    flat=self.flat,
                    suppress_backtracks=self.suppress_backtracks,
                    proxy_enabled=self.proxy_enabled,
                    project_dir=project_dir,
                    role_enforcer=self._role_enforcer,
                    escalation_modes=self.escalation_modes,
                    llm_backend=os.environ.get(
                        'TEAPARTY_LLM_BACKEND', 'claude',
                    ),
                    llm_caller=self._llm_caller,
                    proxy_invoker_fn=self._proxy_invoker_fn,
                    on_dispatch=self._on_dispatch,
                    paused_check=self._paused_check,
                ),
            )

            result = await orchestrator.run()

            # 11. Commit deliverables
            await commit_deliverables(worktree_path, f'Session {self.session_id}: {self.task[:80]}')

            # 12. Squash-merge session into main — the work is done, get it merged.
            merge_verification_failed = False
            if result.terminal_state == 'DONE':
                callback = self._make_conflict_callback() if effective_input else None
                try:
                    try:
                        await squash_merge(
                            source=worktree_path,
                            target=repo_root,
                            message=f'Session {self.session_id}: {self.task[:80]}',
                            conflict_callback=callback,
                        )
                    except MergeConflictEscalation as exc:
                        _log.warning(
                            'Merge conflict escalated to human: %s',
                            ', '.join(exc.conflicted_files[:5]),
                        )
                        # Fall back to -X theirs after human sees the conflict
                        await squash_merge(
                            source=worktree_path,
                            target=repo_root,
                            message=f'Session {self.session_id}: {self.task[:80]}',
                        )
                except MergeVerificationError as exc:
                    merge_verification_failed = True
                    _log.error('Merge verification failed for session %s: %s', self.session_id, exc)
                    await self.event_bus.publish(Event(
                        type=EventType.FAILURE,
                        data={
                            'reason': (
                                f'Merge completed but deliverables are missing or truncated: {exc}. '
                                'Check .teaparty/logs/merge-verification.log for details.'
                            ),
                        },
                        session_id=self.session_id,
                    ))

            # 13. Extract learnings (skippable for test runs)
            if result.terminal_state == 'DONE' and not merge_verification_failed and not self.skip_learnings:
                await extract_learnings(
                    infra_dir=infra_dir,
                    project_dir=project_dir,
                    session_worktree=worktree_path,
                    task=self.task,
                    poc_root=self.poc_root,
                )

            # 14. Clean up session worktree (after learnings, before publish)
            await release_worktree(worktree_path)

            effective_terminal_state = (
                'MERGE_VERIFICATION_FAILED' if merge_verification_failed
                else result.terminal_state
            )

            # Telemetry: session_complete (Issue #405)
            try:
                from teaparty.telemetry import record_event
                from teaparty.telemetry import events as _telem_events
                record_event(
                    _telem_events.SESSION_COMPLETE,
                    scope=self.project_slug or 'management',
                    session_id=self.session_id,
                    data={
                        'final_phase': effective_terminal_state,
                        'total_turns': 0,
                        'total_cost_usd': 0.0,
                        'response_text_len': 0,
                    },
                )
            except Exception:
                pass

            # 15. Publish session complete
            await self.event_bus.publish(Event(
                type=EventType.SESSION_COMPLETED,
                data={
                    'terminal_state': effective_terminal_state,
                    'backtrack_count': result.backtrack_count,
                },
                session_id=self.session_id,
            ))

            # 16. Stop state writer and bus writer
            await state_writer.stop()
            self.event_bus.unsubscribe(bus_writer)

            return SessionResult(
                terminal_state=effective_terminal_state,
                project=self.project_slug,
                session_id=self.session_id,
                backtrack_count=result.backtrack_count,
            )
        finally:
            self._message_bus.close()

    def _make_conflict_callback(self):
        """Build a merge conflict callback that asks the human via message bus."""
        provider = self._bus_input_provider or self.input_provider
        async def _callback(conflicted_files, source, target):
            bridge_text = (
                f'Merge conflict in {len(conflicted_files)} file(s):\n'
                + '\n'.join(f'  - {f}' for f in conflicted_files[:10])
                + '\n\nOptions:\n'
                '  approve — resolve by taking the session version (theirs)\n'
                '  escalate — stop and review the conflicts manually\n'
            )
            from teaparty.messaging.bus import InputRequest
            response = await provider(InputRequest(
                type='merge_conflict',
                state='MERGE_CONFLICT',
                artifact='',
                bridge_text=bridge_text,
            ))
            r = response.strip().lower()
            if 'escalate' in r or 'stop' in r or 'review' in r:
                return 'escalate'
            return 'theirs'
        return _callback

    def _classify_task(self) -> tuple[str, str]:
        """Classify task to determine (project_slug, task_mode).

        task_mode is 'conversational' for simple Q&A tasks that bypass orchestration,
        or 'normal' for full plan-execute sessions.
        """
        if self.project_override:
            return self.project_override, 'normal'

        script = os.path.join(self.poc_root, 'scripts', 'classify_task.py')
        if os.path.exists(script):
            try:
                result = subprocess.run(
                    ['python3', script, '--task', self.task,
                     '--projects-dir', self.projects_dir],
                    capture_output=True, text=True, timeout=30,
                )
                if result.returncode == 0 and result.stdout.strip():
                    parts = result.stdout.strip().split('\t')
                    slug = parts[0]
                    mode = parts[1] if len(parts) > 1 else 'normal'
                    return slug, mode
            except Exception:
                pass

        return 'default', 'normal'

    def _find_repo_root(self, project_dir: str = '') -> str:
        """Find the git repo root for worktree creation.

        If the project has its own .git, use that.  Otherwise, initialize
        a new empty git repo so the project is isolated from the outer
        teaparty repo.
        """
        if project_dir:
            return _ensure_project_repo(project_dir)
        return _find_repo_root_from(self.poc_root)

    def _resolve_norms(self, project_dir: str) -> str:
        """Load and resolve norms from the configuration tree.

        Reads org-level norms from .teaparty/teaparty.yaml, workgroup
        norms from the project's workgroup definitions, and project-level
        norms from {project_dir}/.teaparty.local/project.yaml.
        Applies precedence (org < workgroup < project) and returns
        formatted text.  Returns empty string if no config tree exists.
        """
        org_norms: dict[str, list[str]] = {}
        workgroup_norms: dict[str, list[str]] = {}
        project_norms: dict[str, list[str]] = {}

        try:
            mgmt = load_management_team()
            org_norms = mgmt.norms
        except (FileNotFoundError, OSError):
            pass

        try:
            proj = load_project_team(project_dir)
            project_norms = proj.norms
            try:
                workgroups = resolve_workgroups(proj.workgroups, project_dir)
                for wg in workgroups:
                    workgroup_norms.update(wg.norms)
            except (FileNotFoundError, OSError):
                pass
        except (FileNotFoundError, OSError):
            pass

        text = resolve_norms(
            org_norms=org_norms,
            workgroup_norms=workgroup_norms,
            project_norms=project_norms,
        )
        if not text:
            return ''
        return f'--- Norms (advisory) ---\n{text}\n--- end ---'

    def _retrieve_memory(self, project_dir: str) -> str:
        """Retrieve relevant memory entries for the task."""
        if self.skip_learning_retrieval or self.learning_retrieval_mode == 'disabled':
            return ''

        parts = []

        # Institutional memory
        inst_path = os.path.join(project_dir, 'institutional.md')
        if os.path.exists(inst_path):
            try:
                with open(inst_path) as f:
                    content = f.read().strip()
                if content:
                    parts.append(f'--- Institutional Memory ---\n{content}\n--- end ---')
            except OSError:
                pass

        # Proxy preferences
        proxy_path = os.path.join(project_dir, 'proxy.md')
        if os.path.exists(proxy_path):
            try:
                with open(proxy_path) as f:
                    content = f.read().strip()
                if content:
                    parts.append(f'--- Human Preferences ---\n{content}\n--- end ---')
            except OSError:
                pass

        # Fuzzy memory retrieval via importable retrieve()
        # institutional.md and proxy.md are already loaded unconditionally above.
        # Only task-based and proxy-task learnings are fuzzy-retrieved here,
        # each with its own type and budget allocation.
        db_path = os.path.join(project_dir, '.memory.db')
        if os.path.exists(db_path):
            try:
                from teaparty.learning.episodic.indexer import retrieve
                ids_path = ''
                if hasattr(self, 'session_info') and self.session_info.get('infra_dir'):
                    ids_path = os.path.join(self.session_info['infra_dir'], '.retrieved-ids.txt')
                scope_dir = project_dir if self.learning_retrieval_mode == 'scoped' else ''

                # Task-based learnings — fuzzy-retrieved with budget
                task_sources = [os.path.join(project_dir, 'tasks')]
                mem_content = retrieve(
                    task=self.task,
                    db_path=db_path,
                    source_paths=task_sources,
                    top_k=10,
                    scope_base_dir=scope_dir,
                    ids_output_path=ids_path,
                    learning_type='task',
                    max_chars=TASK_LEARNING_BUDGET_CHARS,
                )
                if mem_content and mem_content.strip():
                    parts.append(f'--- Retrieved Memory ---\n{mem_content}\n--- end ---')

                # Proxy task-based learnings — fuzzy-retrieved with separate budget
                proxy_task_dir = os.path.join(project_dir, 'proxy-tasks')
                if os.path.isdir(proxy_task_dir):
                    proxy_content = retrieve(
                        task=self.task,
                        db_path=db_path,
                        source_paths=[proxy_task_dir],
                        top_k=5,
                        scope_base_dir=scope_dir,
                        learning_type='proxy',
                        max_chars=PROXY_LEARNING_BUDGET_CHARS,
                    )
                    if proxy_content and proxy_content.strip():
                        parts.append(f'--- Proxy Task Patterns ---\n{proxy_content}\n--- end ---')
            except Exception as exc:
                print(f'[session] memory retrieval failed: {exc}', file=sys.stderr)

        return '\n\n'.join(parts)

    @staticmethod
    def _print_memory_context(memory_context: str) -> None:
        """Print memory context to stderr for debugging."""
        print('\n── MEMORY CONTEXT ──', file=sys.stderr)
        if memory_context:
            print(memory_context, file=sys.stderr)
        else:
            print('  (no memory context retrieved)', file=sys.stderr)
        print('── END MEMORY CONTEXT ──\n', file=sys.stderr)

    # ── Resume from disk ─────────────────────────────────────────────────────

    @classmethod
    async def resume_from_disk(
        cls,
        infra_dir: str,
        *,
        poc_root: str,
        projects_dir: str | None = None,
        event_bus: EventBus | None = None,
        input_provider: InputProvider | None = None,
        humans: list | None = None,
        escalation_modes: dict[str, str] | None = None,
        proxy_invoker_fn: Any = None,
        on_dispatch: Any = None,
        paused_check: Any = None,
    ) -> SessionResult:
        """Reconstruct a session from persisted disk state and resume orchestration.

        All meaningful state survives a crash:
          - .cfa-state.json  → CfA state machine position
          - PROMPT.txt       → original task
          - stream JSONLs    → Claude session IDs for --resume
          - worktree         → work-in-progress files
          - .running         → stale sentinel (cleaned up here)

        Raises:
            FileNotFoundError: if infra_dir or .cfa-state.json doesn't exist
            ValueError: if the session is already in a terminal state
        """
        if not os.path.isdir(infra_dir):
            raise FileNotFoundError(f'Session infra directory not found: {infra_dir}')

        # 1. Load CfA state
        cfa_path = os.path.join(infra_dir, '.cfa-state.json')
        cfa = load_state(cfa_path)

        if is_globally_terminal(cfa.state):
            raise ValueError(
                f'Session is already terminal (state={cfa.state}). Nothing to resume.'
            )

        # 2. Read task from PROMPT.txt
        prompt_path = os.path.join(infra_dir, 'PROMPT.txt')
        task = ''
        if os.path.exists(prompt_path):
            with open(prompt_path) as f:
                task = f.read()

        # 3. Derive session_id from job.json or directory name
        # infra_dir is .teaparty/jobs/job-{session_id}--{slug}/
        job_json_path = os.path.join(infra_dir, 'job.json')
        with open(job_json_path) as f:
            job_state = json.load(f)
        job_id = job_state['job_id']
        session_id = job_id[4:] if job_id.startswith('job-') else job_id
        from teaparty.workspace.job_store import project_root_from_job_dir
        project_dir = project_root_from_job_dir(infra_dir)
        project_slug = os.path.basename(project_dir)

        projects_dir = projects_dir or os.path.dirname(project_dir)

        # 5. Resolve session worktree
        worktree_path = _resolve_worktree_path(infra_dir, session_id, project_dir)
        if not worktree_path:
            _log.warning('Could not resolve worktree for session %s', session_id)
            worktree_path = ''

        # 5b. Create message bus for persistent communication (Issue #200).
        role_enforcer = RoleEnforcer.from_humans(humans) if humans else None
        bus_path = os.path.join(infra_dir, 'messages.db')
        message_bus = SqliteMessageBus(bus_path)
        try:
            if role_enforcer:
                message_bus.role_enforcer = role_enforcer
            # Use JOB conversation type to match the job chat URL (Issue #341).
            conversation_id = make_conversation_id(
                ConversationType.JOB, f'{project_slug}:{session_id}',
            )
            # Writer-side single source of truth (#422).
            _resume_sender = _resolve_project_lead_sender(project_dir)
            message_bus.create_conversation(
                ConversationType.JOB,
                f'{project_slug}:{session_id}',
                agent_name=_resume_sender or f'{project_slug}-lead',
                project_slug=project_slug,
            )
            bus_input_provider = MessageBusInputProvider(
                bus=message_bus,
                conversation_id=conversation_id,
                sender=_resume_sender,
            )

            # 6. Start state writer + publish SESSION_STARTED with resumed flag
            # Note: don't delete .running first — _write_running() overwrites it
            # atomically, avoiding a race where StateReader sees no .running file
            # and flags the session as orphaned.
            event_bus = event_bus or EventBus()
            state_writer = StateWriter(infra_dir, event_bus)
            await state_writer.start()

            resume_bus_writer = _make_stream_bus_writer(message_bus, conversation_id, session_id)
            event_bus.subscribe(resume_bus_writer)

            await event_bus.publish(Event(
                type=EventType.SESSION_STARTED,
                data={
                    'task': task,
                    'project': project_slug,
                    'session_id': session_id,
                    'worktree': worktree_path,
                    'resumed': True,
                    'message_bus_path': bus_path,
                    'conversation_id': conversation_id,
                },
                session_id=session_id,
            ))

            # 8. Extract phase session IDs from stream JSONLs
            phase_session_ids = _extract_phase_session_ids(infra_dir)

            # 8b. Clean up stale dispatch .running sentinels.
            # All dispatches from the previous process are dead — their PIDs
            # are gone and Claude's in-memory task handles are lost.  Remove
            # the .running files so the bridge doesn't show them as active.
            _cleanup_stale_dispatch_sentinels(infra_dir)

            # 10. Reconstruct _last_actor_data
            config = PhaseConfig(poc_root, project_dir=project_dir)
            last_actor_data = _reconstruct_last_actor_data(
                cfa, config, worktree_path, infra_dir,
            )

            # 11. Retrieve memory
            memory_context = cls._retrieve_memory_static(task, poc_root, project_dir, infra_dir)

            # 12. Build task prompt
            task_prompt = task
            if memory_context:
                task_prompt = f'{task}\n\n{memory_context}'

            # 12b. Inject norms from configuration tree (Issue #257)
            norms_text = cls._resolve_norms_static(project_dir)
            if norms_text:
                task_prompt = f'{task_prompt}\n\n{norms_text}'

            # 13. Construct and run orchestrator — use message bus input provider
            # for persistent communication (Issue #200).
            effective_input = bus_input_provider or input_provider
            proxy_model_path = os.path.join(proxy_home(os.path.join(poc_root, '.teaparty')), '.proxy-confidence.json')

            # Cut 29: human INTERVENE delivery reads bus messages
            # directly at turn boundary; trailing human messages on
            # resume are picked up by the orchestrator's
            # _last_intervention_ts watermark (initialized from the
            # bus on construction) without any seeding here.

            from teaparty.cfa.run_options import RunOptions
            orchestrator = Orchestrator(
                cfa_state=cfa,
                phase_config=config,
                event_bus=event_bus,
                input_provider=effective_input,
                infra_dir=infra_dir,
                project_workdir=project_dir,
                session_worktree=worktree_path,
                proxy_model_path=proxy_model_path,
                project_slug=project_slug,
                poc_root=poc_root,
                task=task_prompt,
                session_id=session_id,
                options=RunOptions(
                    phase_session_ids=phase_session_ids,
                    last_actor_data=last_actor_data,
                    project_dir=project_dir,
                    role_enforcer=role_enforcer,
                    escalation_modes=escalation_modes,
                    proxy_invoker_fn=proxy_invoker_fn,
                    on_dispatch=on_dispatch,
                    paused_check=paused_check,
                ),
            )

            result = await orchestrator.run()

            # 14. Post-run: commit, merge, learnings
            if worktree_path:
                await commit_deliverables(
                    worktree_path,
                    f'Session {session_id} (resumed): {task[:80]}',
                )

            merge_verification_failed = False
            if result.terminal_state == 'DONE' and worktree_path:
                repo_root = _ensure_project_repo(project_dir)
                conflict_cb = _make_conflict_callback_static(
                    effective_input, event_bus, session_id,
                ) if effective_input else None
                try:
                    try:
                        await squash_merge(
                            source=worktree_path,
                            target=repo_root,
                            message=f'Session {session_id} (resumed): {task[:80]}',
                            conflict_callback=conflict_cb,
                        )
                    except MergeConflictEscalation as exc:
                        _log.warning(
                            'Merge conflict escalated to human: %s',
                            ', '.join(exc.conflicted_files[:5]),
                        )
                        await squash_merge(
                            source=worktree_path,
                            target=repo_root,
                            message=f'Session {session_id} (resumed): {task[:80]}',
                        )
                except MergeVerificationError as exc:
                    merge_verification_failed = True
                    _log.error('Merge verification failed for session %s: %s', session_id, exc)
                    await event_bus.publish(Event(
                        type=EventType.FAILURE,
                        data={
                            'reason': (
                                f'Merge completed but deliverables are missing or truncated: {exc}. '
                                'Check .teaparty/logs/merge-verification.log for details.'
                            ),
                        },
                        session_id=session_id,
                    ))

            if result.terminal_state == 'DONE' and not merge_verification_failed and worktree_path:
                await extract_learnings(
                    infra_dir=infra_dir,
                    project_dir=project_dir,
                    session_worktree=worktree_path,
                    task=task,
                    poc_root=poc_root,
                )

            # Clean up session worktree (after learnings extraction)
            if worktree_path:
                await release_worktree(worktree_path)

            effective_terminal_state = (
                'MERGE_VERIFICATION_FAILED' if merge_verification_failed
                else result.terminal_state
            )

            # 15. Publish session complete + stop writer
            await event_bus.publish(Event(
                type=EventType.SESSION_COMPLETED,
                data={
                    'terminal_state': effective_terminal_state,
                    'backtrack_count': result.backtrack_count,
                },
                session_id=session_id,
            ))
            await state_writer.stop()
            event_bus.unsubscribe(resume_bus_writer)

            return SessionResult(
                terminal_state=effective_terminal_state,
                project=project_slug,
                session_id=session_id,
                backtrack_count=result.backtrack_count,
            )
        finally:
            message_bus.close()

    @staticmethod
    def _resolve_norms_static(project_dir: str) -> str:
        """Load and resolve norms without requiring a Session instance."""
        org_norms: dict[str, list[str]] = {}
        workgroup_norms: dict[str, list[str]] = {}
        project_norms: dict[str, list[str]] = {}

        try:
            mgmt = load_management_team()
            org_norms = mgmt.norms
        except (FileNotFoundError, OSError):
            pass

        try:
            proj = load_project_team(project_dir)
            project_norms = proj.norms
            try:
                workgroups = resolve_workgroups(proj.workgroups, project_dir)
                for wg in workgroups:
                    workgroup_norms.update(wg.norms)
            except (FileNotFoundError, OSError):
                pass
        except (FileNotFoundError, OSError):
            pass

        text = resolve_norms(
            org_norms=org_norms,
            workgroup_norms=workgroup_norms,
            project_norms=project_norms,
        )
        if not text:
            return ''
        return f'--- Norms (advisory) ---\n{text}\n--- end ---'

    @staticmethod
    def _retrieve_memory_static(
        task: str,
        poc_root: str,
        project_dir: str,
        infra_dir: str = '',
        learning_retrieval_mode: str = 'flat',
        skip_learning_retrieval: bool = False,
    ) -> str:
        """Retrieve memory without requiring a Session instance."""
        if skip_learning_retrieval or learning_retrieval_mode == 'disabled':
            return ''

        parts = []

        for filename, label in [
            ('institutional.md', 'Institutional Memory'),
            ('proxy.md', 'Human Preferences'),
        ]:
            path = os.path.join(project_dir, filename)
            if os.path.exists(path):
                try:
                    with open(path) as f:
                        content = f.read().strip()
                    if content:
                        parts.append(f'--- {label} ---\n{content}\n--- end ---')
                except OSError:
                    pass

        # Fuzzy memory retrieval via importable retrieve()
        # institutional.md and proxy.md already loaded unconditionally above.
        # Task-based and proxy-task learnings are fuzzy-retrieved with type budgets.
        db_path = os.path.join(project_dir, '.memory.db')
        if os.path.exists(db_path):
            try:
                from teaparty.learning.episodic.indexer import retrieve
                ids_path = os.path.join(infra_dir, '.retrieved-ids.txt') if infra_dir else ''
                scope_dir = project_dir if learning_retrieval_mode == 'scoped' else ''

                # Task-based learnings — fuzzy-retrieved with budget
                task_sources = [os.path.join(project_dir, 'tasks')]
                mem_content = retrieve(
                    task=task,
                    db_path=db_path,
                    source_paths=task_sources,
                    top_k=10,
                    scope_base_dir=scope_dir,
                    ids_output_path=ids_path,
                    learning_type='task',
                    max_chars=TASK_LEARNING_BUDGET_CHARS,
                )
                if mem_content and mem_content.strip():
                    parts.append(f'--- Retrieved Memory ---\n{mem_content}\n--- end ---')

                # Proxy task-based learnings — fuzzy-retrieved with separate budget
                proxy_task_dir = os.path.join(project_dir, 'proxy-tasks')
                if os.path.isdir(proxy_task_dir):
                    proxy_content = retrieve(
                        task=task,
                        db_path=db_path,
                        source_paths=[proxy_task_dir],
                        top_k=5,
                        scope_base_dir=scope_dir,
                        learning_type='proxy',
                        max_chars=PROXY_LEARNING_BUDGET_CHARS,
                    )
                    if proxy_content and proxy_content.strip():
                        parts.append(f'--- Proxy Task Patterns ---\n{proxy_content}\n--- end ---')
            except Exception as exc:
                print(f'[session] memory retrieval failed: {exc}', file=sys.stderr)

        return '\n\n'.join(parts)


# ── Module-level helpers ──────────────────────────────────────────────────────


def _make_conflict_callback_static(input_provider, event_bus, session_id):
    """Build a merge conflict callback for the static resume path."""
    async def _callback(conflicted_files, source, target):
        bridge_text = (
            f'Merge conflict in {len(conflicted_files)} file(s):\n'
            + '\n'.join(f'  - {f}' for f in conflicted_files[:10])
            + '\n\nOptions:\n'
            '  approve — resolve by taking the session version (theirs)\n'
            '  escalate — stop and review the conflicts manually\n'
        )
        from teaparty.messaging.bus import InputRequest
        response = await input_provider(InputRequest(
            type='merge_conflict',
            state='MERGE_CONFLICT',
            artifact='',
            bridge_text=bridge_text,
        ))
        r = response.strip().lower()
        if 'escalate' in r or 'stop' in r or 'review' in r:
            return 'escalate'
        return 'theirs'
    return _callback


def _extract_phase_session_ids(infra_dir: str) -> dict[str, str]:
    """Scan stream JSONL files for the last Claude session ID in each phase.

    Each stream file can contain ``{"type":"system","subtype":"init","session_id":"..."}``
    lines emitted by ClaudeRunner.  We want the *last* such line per file so that
    a resumed agent picks up the most recent conversation.
    """
    stream_map = {
        'intent':    '.intent-stream.jsonl',
        'planning':  '.plan-stream.jsonl',
        'execution': '.exec-stream.jsonl',
    }
    result: dict[str, str] = {}

    for phase, filename in stream_map.items():
        path = os.path.join(infra_dir, filename)
        if not os.path.exists(path):
            continue
        last_sid = ''
        try:
            with open(path) as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        evt = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if (evt.get('type') == 'system'
                            and evt.get('subtype') == 'init'
                            and evt.get('session_id')):
                        last_sid = evt['session_id']
        except OSError:
            continue
        if last_sid:
            result[phase] = last_sid

    return result


def _resolve_worktree_path(
    infra_dir: str, session_id: str, project_dir: str,
) -> str:
    """Resolve the git worktree path for a session.

    In the job store layout, infra_dir IS the job_dir, and the worktree
    is at {job_dir}/worktree/.  Falls back to scanning .teaparty/jobs/
    by session_id prefix.
    """
    # Strategy 1: job_dir/worktree/ (infra_dir is the job_dir)
    candidate = os.path.join(infra_dir, 'worktree')
    if os.path.isdir(candidate):
        return candidate

    # Strategy 2: scan .teaparty/jobs/ for matching job_id
    repo_root = _find_repo_root_from(project_dir)
    from teaparty.workspace.job_store import find_job
    job = find_job(repo_root, job_id=f'job-{session_id}')
    if job and '_job_dir' in job:
        candidate = os.path.join(job['_job_dir'], 'worktree')
        if os.path.isdir(candidate):
            return candidate

    return ''


def _reconstruct_last_actor_data(
    cfa: CfaState,
    config: PhaseConfig,
    worktree_path: str,
    infra_dir: str,
) -> dict[str, Any]:
    """Best-effort reconstruction of _last_actor_data from disk state.

    The most important piece is the artifact path (e.g., INTENT.md path in the
    worktree) that the approval gate needs to locate the deliverable.
    """
    data: dict[str, Any] = {}
    if not worktree_path:
        return data

    # Reconstruct the artifact path the current state's skill expects.
    try:
        spec = config.phase(cfa.state)
    except KeyError:
        return data

    if spec.artifact:
        # Check infra_dir first — Issue #147 moved session artifacts there.
        # Fall back to worktree_path for backward compatibility.
        infra_artifact = os.path.join(infra_dir, spec.artifact)
        worktree_artifact = os.path.join(worktree_path, spec.artifact)
        if os.path.exists(infra_artifact):
            data['artifact_path'] = infra_artifact
        elif os.path.exists(worktree_artifact):
            data['artifact_path'] = worktree_artifact

    return data


def _ensure_project_repo(project_dir: str) -> str:
    """Ensure project_dir has a git repo for worktree creation.

    Returns the repo root to use.  Three cases:

    1. ``.linked-repo`` sentinel exists — return the parent repo root
       (the project shares the enclosing repository).
    2. ``.git`` exists (and no ``.linked-repo``) — return the existing repo root.
    3. Neither — initialize a new empty repo with a seed commit.
    """
    # 1. Linked-repo: use the parent repository
    if os.path.exists(os.path.join(project_dir, '.linked-repo')):
        parent = os.path.dirname(os.path.abspath(project_dir))
        try:
            result = subprocess.run(
                ['git', 'rev-parse', '--show-toplevel'],
                cwd=parent, capture_output=True, text=True,
            )
            if result.returncode == 0 and result.stdout.strip():
                _log.info(
                    'Linked-repo detected at %s — using parent repo %s',
                    project_dir, result.stdout.strip(),
                )
                return result.stdout.strip()
        except Exception:
            pass
        raise RuntimeError(
            f'.linked-repo found in {project_dir} but no parent git repo '
            f'could be resolved from {parent}'
        )

    # 2. Existing repo
    if os.path.exists(os.path.join(project_dir, '.git')):
        return _find_repo_root_from(project_dir)

    # 3. New standalone project — initialize
    os.makedirs(project_dir, exist_ok=True)
    subprocess.run(
        ['git', 'init'],
        cwd=project_dir, capture_output=True, check=True,
    )
    subprocess.run(
        ['git', 'commit', '--allow-empty', '-m', 'init'],
        cwd=project_dir, capture_output=True, check=True,
    )
    _log.info('Initialized new project repo at %s', project_dir)
    return project_dir


def _cleanup_stale_dispatch_sentinels(infra_dir: str) -> int:
    """Finalize stale dispatch heartbeats under infra_dir (issue #149).

    On resume, dispatches from the previous process are dead.  Their
    heartbeats (or .running files) are stale.  Finalize heartbeats as
    'withdrawn' so the bridge shows them as complete.  For legacy .running
    files, delete them.

    Returns the number of sentinels cleaned up.
    """
    from teaparty.bridge.state.heartbeat import (
        read_heartbeat, finalize_heartbeat, is_heartbeat_stale,
    )
    from teaparty.cfa.phase_config import get_team_names
    teams = get_team_names()
    cleaned = 0
    for team in teams:
        team_dir = os.path.join(infra_dir, team)
        if not os.path.isdir(team_dir):
            continue
        try:
            for entry in os.listdir(team_dir):
                dispatch_dir = os.path.join(team_dir, entry)
                if not os.path.isdir(dispatch_dir):
                    continue

                # Check .heartbeat first (issue #149)
                hb_path = os.path.join(dispatch_dir, '.heartbeat')
                if os.path.exists(hb_path):
                    data = read_heartbeat(hb_path)
                    if data.get('status') in ('completed', 'withdrawn'):
                        continue  # Already terminal
                    if is_heartbeat_stale(hb_path):
                        try:
                            finalize_heartbeat(hb_path, 'withdrawn')
                            cleaned += 1
                            _log.info('Finalized stale dispatch heartbeat: %s', hb_path)
                        except OSError:
                            pass
                    continue

                # Legacy .running fallback
                running_path = os.path.join(dispatch_dir, '.running')
                if os.path.exists(running_path):
                    try:
                        os.unlink(running_path)
                        cleaned += 1
                        _log.info('Removed stale dispatch sentinel: %s', running_path)
                    except OSError:
                        pass
        except OSError:
            continue
    return cleaned


def _find_repo_root_from(start_dir: str) -> str:
    """Find the git repo root starting from start_dir."""
    try:
        result = subprocess.run(
            ['git', 'rev-parse', '--show-toplevel'],
            cwd=start_dir,
            capture_output=True, text=True,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    # Fallback: walk up until we find .git
    d = os.path.abspath(start_dir)
    while d != '/':
        if os.path.isdir(os.path.join(d, '.git')):
            return d
        d = os.path.dirname(d)
    return start_dir
