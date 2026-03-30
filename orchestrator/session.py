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

from scripts.cfa_state import (
    CfaState,
    load_state,
    is_globally_terminal,
    make_initial_state,
    phase_for_state,
    save_state,
)
from orchestrator.actors import InputProvider
from orchestrator.engine import Orchestrator, OrchestratorResult
from orchestrator.events import Event, EventBus, EventType
from orchestrator.human_presence import HumanPresence
from orchestrator.learnings import extract_learnings
from orchestrator.merge import (
    commit_deliverables, squash_merge, MergeConflictEscalation,
)
from orchestrator.messaging import (
    ConversationType, MessageBusInputProvider, SqliteMessageBus,
    make_conversation_id,
)
from orchestrator.config_reader import (
    load_project_team, load_management_team, resolve_norms,
    resolve_budget, resolve_workgroups,
)
from orchestrator.cost_tracker import CostTracker
from orchestrator.intervention import InterventionQueue
from orchestrator.phase_config import PhaseConfig
from orchestrator.role_enforcer import RoleEnforcer
from orchestrator.state_writer import StateWriter
from orchestrator.worktree import (
    create_session_worktree, cleanup_worktree,
)

_log = logging.getLogger('orchestrator')


def _resolve_cost_tracker_impl(project_dir: str) -> CostTracker | None:
    """Create a CostTracker from the resolved budget configuration.

    Shared by both Session._resolve_cost_tracker and the static resume path.
    """
    org_budget: dict[str, float] = {}
    workgroup_budget: dict[str, float] = {}
    project_budget: dict[str, float] = {}

    try:
        mgmt = load_management_team()
        org_budget = mgmt.budget
    except (FileNotFoundError, OSError):
        pass

    try:
        proj = load_project_team(project_dir)
        project_budget = proj.budget
        try:
            workgroups = resolve_workgroups(proj.workgroups, project_dir)
            for wg in workgroups:
                workgroup_budget.update(wg.budget)
        except (FileNotFoundError, OSError):
            pass
    except (FileNotFoundError, OSError):
        pass

    budget = resolve_budget(
        org_budget=org_budget,
        workgroup_budget=workgroup_budget,
        project_budget=project_budget,
    )
    if not budget:
        return None
    return CostTracker(budget=budget)


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
        skip_intent: bool = False,
        intent_file: str | None = None,
        plan_file: str | None = None,
        intent_only: bool = False,
        plan_only: bool = False,
        execute_only: bool = False,
        show_memory: bool = False,
        show_proxy: bool = False,
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
        human_presence: HumanPresence | None = None,
    ):
        self.task = task
        self.poc_root = poc_root
        self.projects_dir = projects_dir or os.path.dirname(poc_root)
        self.project_override = project_override
        self.skip_intent = skip_intent
        self.intent_file = intent_file
        self.plan_file = plan_file
        self.intent_only = intent_only
        self.plan_only = plan_only
        self.execute_only = execute_only
        self.show_memory = show_memory
        self.show_proxy = show_proxy
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
        self.human_presence = human_presence

        # Resolved during run
        self.project_slug = ''
        self.session_id = ''
        self.session_info: dict = {}
        self.config = PhaseConfig(poc_root)  # re-created with project_dir in run()

    async def run(self) -> SessionResult:
        """Execute the full session lifecycle."""
        # 1. Classify task → project slug + task mode
        self.project_slug, task_mode = self._classify_task()
        self.session_id = datetime.now().strftime('%Y%m%d-%H%M%S')

        # Short-circuit for conversational tasks (no orchestration needed)
        if task_mode == 'conversational':
            self.skip_intent = True

        # 2. Ensure project directory exists
        project_dir = os.path.join(self.projects_dir, self.project_slug)
        os.makedirs(project_dir, exist_ok=True)
        os.makedirs(os.path.join(project_dir, '.sessions'), exist_ok=True)

        # 2b. Re-create config with project-scoped overrides (issue #10)
        self.config = PhaseConfig(self.poc_root, project_dir=project_dir)

        # 3. Find repo root (project may have its own .git)
        repo_root = self._find_repo_root(project_dir)

        # 4. Create session worktree
        self.session_info = await create_session_worktree(
            project_slug=self.project_slug,
            task=self.task,
            repo_root=repo_root,
            projects_dir=self.projects_dir,
            session_id=self.session_id,
        )

        infra_dir = self.session_info['infra_dir']
        worktree_path = self.session_info['worktree_path']

        # 4a. Create message bus for persistent human-agent communication (Issue #200).
        bus_path = os.path.join(infra_dir, 'messages.db')
        self._message_bus = SqliteMessageBus(bus_path)
        if self._role_enforcer:
            self._message_bus.role_enforcer = self._role_enforcer
        self._conversation_id = make_conversation_id(
            ConversationType.PROJECT_SESSION, self.session_id,
        )
        self._message_bus.create_conversation(
            ConversationType.PROJECT_SESSION, self.session_id,
        )
        if self.input_provider is not None:
            self._bus_input_provider = MessageBusInputProvider(
                bus=self._message_bus,
                conversation_id=self._conversation_id,
            )
        else:
            self._bus_input_provider = None

        # 4b. Copy pre-written artifacts into infra_dir (Issue #147).
        # Session artifacts live in the session folder, not the worktree.
        if self.intent_file:
            shutil.copy2(self.intent_file, os.path.join(infra_dir, 'INTENT.md'))
        if self.plan_file:
            shutil.copy2(self.plan_file, os.path.join(infra_dir, 'PLAN.md'))

        # Persist the full prompt so it's never lost to truncation
        with open(os.path.join(infra_dir, 'PROMPT.txt'), 'w') as f:
            f.write(self.task)

        # 5. Start state writer (filesystem persistence)
        state_writer = StateWriter(infra_dir, self.event_bus)
        await state_writer.start()

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

        # 7. Initialize CfA state at the correct starting point
        from scripts.cfa_state import transition, set_state_direct
        cfa = make_initial_state(task_id=self.session_id)

        if self.execute_only or self.plan_file:
            # Skip intent + planning: jump directly to TASK (execution start)
            cfa = set_state_direct(cfa, 'TASK')
        elif self.intent_file or self.skip_intent:
            # Skip intent: set state to INTENT (planning entry point)
            # _auto_bridge() in Orchestrator will apply INTENT → DRAFT
            cfa = set_state_direct(cfa, 'INTENT')
        else:
            # Normal path: IDEA → PROPOSAL (agent's first turn)
            cfa = transition(cfa, 'propose')

        save_state(cfa, os.path.join(infra_dir, '.cfa-state.json'))

        # 8. Retrieve memory context
        memory_context = self._retrieve_memory(project_dir)

        # 8b. Show memory context if requested
        if self.show_memory or self.dry_run:
            self._print_memory_context(memory_context)

        # 8c. Show proxy confidence model if requested
        if self.show_proxy or self.dry_run:
            self._print_proxy_model(project_dir)

        if self.dry_run:
            await self.event_bus.publish(Event(
                type=EventType.SESSION_COMPLETED,
                data={'terminal_state': 'DRY_RUN', 'backtrack_count': 0},
                session_id=self.session_id,
            ))
            await state_writer.stop()
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
        proxy_model_path = os.path.join(project_dir, '.proxy-confidence.json')
        effective_input = self._bus_input_provider or self.input_provider

        # Create intervention queue for human INTERVENE delivery (Issue #246).
        self._intervention_queue = InterventionQueue(
            message_bus=self._message_bus,
            conversation_id=self._conversation_id,
        )
        if self._role_enforcer:
            self._intervention_queue.role_enforcer = self._role_enforcer

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
            skip_intent=self.skip_intent,
            intent_only=self.intent_only,
            plan_only=self.plan_only,
            execute_only=self.execute_only,
            flat=self.flat,
            suppress_backtracks=self.suppress_backtracks,
            proxy_enabled=self.proxy_enabled,
            project_dir=project_dir,
            role_enforcer=self._role_enforcer,
            human_presence=self.human_presence,
            cost_tracker=self._resolve_cost_tracker(project_dir),
            intervention_queue=self._intervention_queue,
        )

        result = await orchestrator.run()

        # 11. Commit deliverables
        await commit_deliverables(worktree_path, f'Session {self.session_id}: {self.task[:80]}')

        # 12. Squash-merge session into main — the work is done, get it merged.
        if result.terminal_state == 'COMPLETED_WORK':
            callback = self._make_conflict_callback() if effective_input else None
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

        # 13. Extract learnings (skippable for test runs)
        if result.terminal_state == 'COMPLETED_WORK' and not self.skip_learnings:
            await extract_learnings(
                infra_dir=infra_dir,
                project_dir=project_dir,
                session_worktree=worktree_path,
                task=self.task,
                poc_root=self.poc_root,
            )

        # 14. Clean up session worktree (after learnings, before publish)
        await cleanup_worktree(worktree_path)

        # 15. Publish session complete
        await self.event_bus.publish(Event(
            type=EventType.SESSION_COMPLETED,
            data={
                'terminal_state': result.terminal_state,
                'backtrack_count': result.backtrack_count,
            },
            session_id=self.session_id,
        ))

        # 16. Stop state writer
        await state_writer.stop()

        return SessionResult(
            terminal_state=result.terminal_state,
            project=self.project_slug,
            session_id=self.session_id,
            backtrack_count=result.backtrack_count,
        )

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
            await self.event_bus.publish(Event(
                type=EventType.INPUT_REQUESTED,
                data={
                    'state': 'MERGE_CONFLICT',
                    'bridge_text': bridge_text,
                    'conflicted_files': conflicted_files,
                },
                session_id=self.session_id,
            ))
            from orchestrator.events import InputRequest
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

    def _resolve_cost_tracker(self, project_dir: str) -> CostTracker | None:
        """Create a CostTracker from the resolved budget configuration."""
        return _resolve_cost_tracker_impl(project_dir)

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
                from scripts.memory_indexer import retrieve
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

    @staticmethod
    def _print_proxy_model(project_dir: str) -> None:
        """Print proxy confidence model state to stderr for debugging."""
        from scripts.approval_gate import (
            load_model, compute_confidence, is_generative_state,
            ConfidenceEntry, COLD_START_THRESHOLD,
        )
        print('\n── PROXY CONFIDENCE MODEL ──', file=sys.stderr)
        model_path = os.path.join(project_dir, '.proxy-confidence.json')
        if not os.path.exists(model_path):
            print(f'  (no model file at {model_path})', file=sys.stderr)
            print('── END PROXY MODEL ──\n', file=sys.stderr)
            return

        model = load_model(model_path)
        if not model.entries:
            print('  (model exists but has no entries)', file=sys.stderr)
            print('── END PROXY MODEL ──\n', file=sys.stderr)
            return

        header = f"  {'STATE':<22} {'TASK_TYPE':<20} {'CONF':>6} {'APP':>4} {'TOT':>4} {'DIFFS':>5} {'UPDATED'}"
        print(header, file=sys.stderr)
        print('  ' + '-' * (len(header) - 2), file=sys.stderr)

        for key, raw in sorted(model.entries.items()):
            if isinstance(raw, dict):
                if 'differentials' not in raw:
                    raw['differentials'] = []
                if 'artifact_lengths' not in raw:
                    raw['artifact_lengths'] = []
                if 'question_patterns' not in raw:
                    raw['question_patterns'] = []
                entry = ConfidenceEntry(**raw)
            else:
                entry = raw
            conf = compute_confidence(entry)
            threshold = (
                model.generative_threshold
                if is_generative_state(entry.state)
                else model.global_threshold
            )
            diff_count = len(entry.differentials)
            marker = '*' if conf >= threshold and entry.total_count >= COLD_START_THRESHOLD else ' '
            print(
                f'  {entry.state:<22} {entry.task_type:<20} {conf:>6.3f} '
                f'{entry.approve_count:>4} {entry.total_count:>4} {diff_count:>5}  '
                f'{entry.last_updated} {marker}',
                file=sys.stderr,
            )
        print(
            f'\n  thresholds: binary={model.global_threshold}  '
            f'generative={model.generative_threshold}  (* = would auto-approve)',
            file=sys.stderr,
        )
        print('── END PROXY MODEL ──\n', file=sys.stderr)

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
        human_presence: HumanPresence | None = None,
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

        # 3. Derive session_id from directory name
        #    infra_dir = {projects_dir}/{slug}/.sessions/{session_id}
        session_id = os.path.basename(infra_dir)

        # 4. Derive project_slug from path
        #    .../projects/{slug}/.sessions/{id}
        sessions_parent = os.path.dirname(infra_dir)        # .sessions/
        project_dir = os.path.dirname(sessions_parent)       # projects/{slug}
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
        if role_enforcer:
            message_bus.role_enforcer = role_enforcer
        conversation_id = make_conversation_id(
            ConversationType.PROJECT_SESSION, session_id,
        )
        message_bus.create_conversation(ConversationType.PROJECT_SESSION, session_id)
        if input_provider is not None:
            bus_input_provider = MessageBusInputProvider(
                bus=message_bus,
                conversation_id=conversation_id,
            )
        else:
            bus_input_provider = None

        # 6. Start state writer + publish SESSION_STARTED with resumed flag
        # Note: don't delete .running first — _write_running() overwrites it
        # atomically, avoiding a race where StateReader sees no .running file
        # and flags the session as orphaned.
        event_bus = event_bus or EventBus()
        state_writer = StateWriter(infra_dir, event_bus)
        await state_writer.start()

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

        # 9. Derive skip_intent — True if we're past the intent phase
        current_phase = phase_for_state(cfa.state)
        skip_intent = current_phase != 'intent'

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
        proxy_model_path = os.path.join(project_dir, '.proxy-confidence.json')

        # Create intervention queue for human INTERVENE delivery (Issue #246).
        intervention_queue = InterventionQueue(
            message_bus=message_bus,
            conversation_id=conversation_id,
        )
        if role_enforcer:
            intervention_queue.role_enforcer = role_enforcer

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
            skip_intent=skip_intent,
            phase_session_ids=phase_session_ids,
            last_actor_data=last_actor_data,
            project_dir=project_dir,
            role_enforcer=role_enforcer,
            human_presence=human_presence,
            cost_tracker=_resolve_cost_tracker_impl(project_dir),
            intervention_queue=intervention_queue,
        )

        result = await orchestrator.run()

        # 14. Post-run: commit, merge, learnings
        if worktree_path:
            await commit_deliverables(
                worktree_path,
                f'Session {session_id} (resumed): {task[:80]}',
            )

        if result.terminal_state == 'COMPLETED_WORK' and worktree_path:
            repo_root = _ensure_project_repo(project_dir)
            conflict_cb = _make_conflict_callback_static(
                effective_input, event_bus, session_id,
            ) if effective_input else None
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

        if result.terminal_state == 'COMPLETED_WORK' and worktree_path:
            await extract_learnings(
                infra_dir=infra_dir,
                project_dir=project_dir,
                session_worktree=worktree_path,
                task=task,
                poc_root=poc_root,
            )

        # Clean up session worktree (after learnings extraction)
        if worktree_path:
            await cleanup_worktree(worktree_path)

        # 15. Publish session complete + stop writer
        await event_bus.publish(Event(
            type=EventType.SESSION_COMPLETED,
            data={
                'terminal_state': result.terminal_state,
                'backtrack_count': result.backtrack_count,
            },
            session_id=session_id,
        ))
        await state_writer.stop()

        return SessionResult(
            terminal_state=result.terminal_state,
            project=project_slug,
            session_id=session_id,
            backtrack_count=result.backtrack_count,
        )

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
                from scripts.memory_indexer import retrieve
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
        await event_bus.publish(Event(
            type=EventType.INPUT_REQUESTED,
            data={
                'state': 'MERGE_CONFLICT',
                'bridge_text': bridge_text,
                'conflicted_files': conflicted_files,
            },
            session_id=session_id,
        ))
        from orchestrator.events import InputRequest
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

    Strategy:
    1. Check worktrees.json manifest in repo root for a matching session_id.
    2. Scan {project_dir}/.worktrees/ for directories starting with
       ``session-{short_id}--``.
    """
    # Strategy 1: worktrees.json manifest
    repo_root = _find_repo_root_from(project_dir)
    manifest_path = os.path.join(repo_root, 'worktrees.json')
    if os.path.exists(manifest_path):
        try:
            with open(manifest_path) as f:
                manifest = json.load(f)
            for entry in manifest.get('worktrees', []):
                if entry.get('session_id') == session_id:
                    wt_path = entry.get('path', '')
                    if wt_path and os.path.isdir(wt_path):
                        return wt_path
        except (OSError, json.JSONDecodeError):
            pass

    # Strategy 2: scan .worktrees/ directory
    short_id = session_id[-6:]
    worktrees_dir = os.path.join(project_dir, '.worktrees')
    if os.path.isdir(worktrees_dir):
        prefix = f'session-{short_id}--'
        try:
            for name in os.listdir(worktrees_dir):
                if name.startswith(prefix):
                    candidate = os.path.join(worktrees_dir, name)
                    if os.path.isdir(candidate):
                        return candidate
        except OSError:
            pass

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

    # If the CfA state is at an approval gate (*_ASSERT), reconstruct the
    # artifact path the gate would need.
    current_phase = phase_for_state(cfa.state)
    try:
        spec = config.phase(current_phase)
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
    from orchestrator.heartbeat import (
        read_heartbeat, finalize_heartbeat, is_heartbeat_stale,
    )
    from orchestrator.phase_config import get_team_names
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
