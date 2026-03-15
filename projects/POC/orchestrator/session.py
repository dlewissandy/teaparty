"""Session lifecycle — the top-level entry point.

Replaces run.sh: task classification, worktree setup, memory retrieval,
confidence posture, pre-mortem, orchestration, merge, and learning extraction.
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

from projects.POC.scripts.cfa_state import (
    CfaState,
    load_state,
    is_globally_terminal,
    make_initial_state,
    phase_for_state,
    save_state,
)
from projects.POC.orchestrator.actors import InputProvider
from projects.POC.orchestrator.engine import Orchestrator, OrchestratorResult
from projects.POC.orchestrator.events import Event, EventBus, EventType
from projects.POC.orchestrator.learnings import extract_learnings
from projects.POC.orchestrator.merge import (
    commit_deliverables, squash_merge, MergeConflictEscalation,
)
from projects.POC.orchestrator.phase_config import PhaseConfig
from projects.POC.orchestrator.state_writer import StateWriter
from projects.POC.orchestrator.worktree import (
    create_session_worktree, cleanup_worktree,
)

_log = logging.getLogger('orchestrator')


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

        # Resolved during run
        self.project_slug = ''
        self.session_id = ''
        self.session_info: dict = {}
        self.config = PhaseConfig(poc_root)

    async def run(self) -> SessionResult:
        """Execute the full session lifecycle."""
        # 1. Classify task → project slug + task mode (Gap 5)
        self.project_slug, task_mode = self._classify_task()
        self.session_id = datetime.now().strftime('%Y%m%d-%H%M%S')

        # Short-circuit for conversational tasks (no orchestration needed)
        if task_mode == 'conversational':
            self.skip_intent = True

        # 2. Ensure project directory exists
        project_dir = os.path.join(self.projects_dir, self.project_slug)
        os.makedirs(project_dir, exist_ok=True)
        os.makedirs(os.path.join(project_dir, '.sessions'), exist_ok=True)

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

        # 4b. Copy pre-written artifacts into worktree (context injection)
        if self.intent_file:
            shutil.copy2(self.intent_file, os.path.join(worktree_path, 'INTENT.md'))
        if self.plan_file:
            shutil.copy2(self.plan_file, os.path.join(worktree_path, 'PLAN.md'))

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
            },
            session_id=self.session_id,
        ))

        # 7. Initialize CfA state at the correct starting point
        from projects.POC.scripts.cfa_state import transition, set_state_direct
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

        # 10. Run orchestrator
        proxy_model_path = os.path.join(project_dir, '.proxy-confidence.json')
        orchestrator = Orchestrator(
            cfa_state=cfa,
            phase_config=self.config,
            event_bus=self.event_bus,
            input_provider=self.input_provider,
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
        )

        result = await orchestrator.run()

        # 11. Commit deliverables
        await commit_deliverables(worktree_path, f'Session {self.session_id}: {self.task[:80]}')

        # 12. Squash-merge session into main — the work is done, get it merged.
        if result.terminal_state == 'COMPLETED_WORK':
            callback = self._make_conflict_callback() if self.input_provider else None
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

        # 14. Publish session complete
        await self.event_bus.publish(Event(
            type=EventType.SESSION_COMPLETED,
            data={
                'terminal_state': result.terminal_state,
                'backtrack_count': result.backtrack_count,
            },
            session_id=self.session_id,
        ))

        # 15. Stop state writer
        await state_writer.stop()

        return SessionResult(
            terminal_state=result.terminal_state,
            project=self.project_slug,
            session_id=self.session_id,
            backtrack_count=result.backtrack_count,
        )

    def _make_conflict_callback(self):
        """Build a merge conflict callback that asks the human via input_provider."""
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
            from projects.POC.orchestrator.events import InputRequest
            response = await self.input_provider(InputRequest(
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

        If the project has its own .git (e.g. hierarchical-memory-paper),
        use that so worktrees are created from the project's repo, not
        the outer teaparty repo.
        """
        if project_dir and os.path.exists(os.path.join(project_dir, '.git')):
            return _find_repo_root_from(project_dir)
        return _find_repo_root_from(self.poc_root)

    def _retrieve_memory(self, project_dir: str) -> str:
        """Retrieve relevant memory entries for the task."""
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

        # Fuzzy memory retrieval (Gap 14: use correct memory_indexer.py flags)
        import tempfile
        script = os.path.join(self.poc_root, 'scripts', 'memory_indexer.py')
        db_path = os.path.join(project_dir, '.memory.db')
        if os.path.exists(script) and os.path.exists(db_path):
            output_path = None
            try:
                with tempfile.NamedTemporaryFile(
                    mode='w', suffix='.md', delete=False,
                ) as out_f:
                    output_path = out_f.name
                mem_result = subprocess.run(
                    ['python3', script,
                     '--db', db_path,
                     '--task', self.task,
                     '--top-k', '10',
                     '--output', output_path,
                     '--scope-base-dir', project_dir,
                    ],
                    capture_output=True, text=True, timeout=15,
                )
                if mem_result.returncode == 0 and os.path.exists(output_path):
                    with open(output_path) as f:
                        mem_content = f.read().strip()
                    if mem_content:
                        parts.append(f'--- Retrieved Memory ---\n{mem_content}\n--- end ---')
            except Exception:
                pass
            finally:
                if output_path:
                    try:
                        os.unlink(output_path)
                    except OSError:
                        pass

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
        from projects.POC.scripts.approval_gate import (
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
            },
            session_id=session_id,
        ))

        # 8. Extract phase session IDs from stream JSONLs
        phase_session_ids = _extract_phase_session_ids(infra_dir)

        # 9. Derive skip_intent — True if we're past the intent phase
        current_phase = phase_for_state(cfa.state)
        skip_intent = current_phase != 'intent'

        # 10. Reconstruct _last_actor_data
        config = PhaseConfig(poc_root)
        last_actor_data = _reconstruct_last_actor_data(
            cfa, config, worktree_path, infra_dir,
        )

        # 11. Retrieve memory
        memory_context = cls._retrieve_memory_static(task, poc_root, project_dir)

        # 12. Build task prompt
        task_prompt = task
        if memory_context:
            task_prompt = f'{task}\n\n{memory_context}'

        # 13. Construct and run orchestrator
        proxy_model_path = os.path.join(project_dir, '.proxy-confidence.json')
        orchestrator = Orchestrator(
            cfa_state=cfa,
            phase_config=config,
            event_bus=event_bus,
            input_provider=input_provider,
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
        )

        result = await orchestrator.run()

        # 14. Post-run: commit, merge, learnings
        if worktree_path:
            await commit_deliverables(
                worktree_path,
                f'Session {session_id} (resumed): {task[:80]}',
            )

        if result.terminal_state == 'COMPLETED_WORK' and worktree_path:
            repo_root = _find_repo_root_from(project_dir)
            conflict_cb = _make_conflict_callback_static(
                input_provider, event_bus, session_id,
            ) if input_provider else None
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
    def _retrieve_memory_static(task: str, poc_root: str, project_dir: str) -> str:
        """Retrieve memory without requiring a Session instance."""
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

        import tempfile
        script = os.path.join(poc_root, 'scripts', 'memory_indexer.py')
        db_path = os.path.join(project_dir, '.memory.db')
        if os.path.exists(script) and os.path.exists(db_path):
            output_path = None
            try:
                with tempfile.NamedTemporaryFile(
                    mode='w', suffix='.md', delete=False,
                ) as out_f:
                    output_path = out_f.name
                mem_result = subprocess.run(
                    ['python3', script,
                     '--db', db_path,
                     '--task', task,
                     '--top-k', '10',
                     '--output', output_path,
                     '--scope-base-dir', project_dir,
                    ],
                    capture_output=True, text=True, timeout=15,
                )
                if mem_result.returncode == 0 and os.path.exists(output_path):
                    with open(output_path) as f:
                        mem_content = f.read().strip()
                    if mem_content:
                        parts.append(f'--- Retrieved Memory ---\n{mem_content}\n--- end ---')
            except Exception:
                pass
            finally:
                if output_path:
                    try:
                        os.unlink(output_path)
                    except OSError:
                        pass

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
        from projects.POC.orchestrator.events import InputRequest
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
        artifact_path = os.path.join(worktree_path, spec.artifact)
        if os.path.exists(artifact_path):
            data['artifact_path'] = artifact_path

    return data


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
