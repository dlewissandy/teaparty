"""Session lifecycle — the top-level entry point.

Replaces run.sh: task classification, worktree setup, memory retrieval,
confidence posture, pre-mortem, orchestration, merge, and learning extraction.
"""
from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from datetime import datetime

from projects.POC.scripts.cfa_state import make_initial_state, save_state
from projects.POC.orchestrator.actors import InputProvider
from projects.POC.orchestrator.engine import Orchestrator, OrchestratorResult
from projects.POC.orchestrator.events import Event, EventBus, EventType
from projects.POC.orchestrator.learnings import extract_learnings
from projects.POC.orchestrator.merge import commit_deliverables, squash_merge
from projects.POC.orchestrator.phase_config import PhaseConfig
from projects.POC.orchestrator.state_writer import StateWriter
from projects.POC.orchestrator.worktree import (
    create_session_worktree, cleanup_worktree,
)


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
        event_bus: EventBus | None = None,
        input_provider: InputProvider | None = None,
    ):
        self.task = task
        self.poc_root = poc_root
        self.projects_dir = projects_dir or os.path.dirname(poc_root)
        self.project_override = project_override
        self.skip_intent = skip_intent
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

        # 3. Find repo root
        repo_root = self._find_repo_root()

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

        # 7. Initialize CfA state
        cfa = make_initial_state(task_id=self.session_id)
        # Advance to PROPOSAL (the agent's first turn)
        from projects.POC.scripts.cfa_state import transition
        cfa = transition(cfa, 'propose')
        save_state(cfa, os.path.join(infra_dir, '.cfa-state.json'))

        # 8. Retrieve memory context
        memory_context = self._retrieve_memory(project_dir)

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
        )

        result = await orchestrator.run()

        # 11. Commit deliverables
        await commit_deliverables(worktree_path, f'Session {self.session_id}: {self.task[:80]}')

        # 12. Squash-merge session into main
        if result.terminal_state == 'COMPLETED_WORK':
            try:
                main_worktree = repo_root
                await squash_merge(
                    source=worktree_path,
                    target=main_worktree,
                    message=f'Session {self.session_id}: {self.task[:80]}',
                )
            except Exception:
                pass

        # 13. Extract learnings
        if result.terminal_state == 'COMPLETED_WORK':
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

    def _find_repo_root(self) -> str:
        """Find the git repo root."""
        try:
            result = subprocess.run(
                ['git', 'rev-parse', '--show-toplevel'],
                cwd=self.poc_root,
                capture_output=True, text=True,
            )
            if result.returncode == 0:
                return result.stdout.strip()
        except Exception:
            pass
        # Fall back to two levels up from poc_root
        return os.path.dirname(os.path.dirname(self.poc_root))

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
