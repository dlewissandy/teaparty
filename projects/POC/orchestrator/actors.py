"""Actor runners — pluggable handlers for each CfA actor type.

The orchestrator calls the right actor based on the `actor` field from
the CfA transition table.  Each actor returns an ActorResult describing
which CfA action to take next.

Actor types:
  AgentRunner    — invokes Claude CLI, streams output, detects artifacts
  ApprovalGate   — proxy decision + human review loop
  DispatchRunner — creates child orchestrator for subteam delegation
"""
from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Awaitable, Callable, Protocol

from projects.POC.orchestrator.claude_runner import ClaudeRunner, ClaudeResult
from projects.POC.orchestrator.events import (
    Event, EventBus, EventType, InputRequest,
)
from projects.POC.scripts.cfa_state import TRANSITIONS
from projects.POC.scripts.approval_gate import (
    GenerativeResponse,
    _extract_question_patterns,
    generate_response,
    load_model,
    record_outcome,
    resolve_team_model_path,
    save_model,
    should_escalate,
)

if TYPE_CHECKING:
    from projects.POC.orchestrator.phase_config import PhaseConfig, PhaseSpec


# ── Protocols ────────────────────────────────────────────────────────────────

class InputProvider(Protocol):
    """Async callable that returns human input text."""
    async def __call__(self, request: InputRequest) -> str: ...


# ── Result types ─────────────────────────────────────────────────────────────

@dataclass
class ActorResult:
    """What the actor decided — maps to a CfA transition action."""
    action: str           # CfA action name (approve, correct, withdraw, etc.)
    feedback: str = ''    # Human feedback text (for correct/clarify)
    dialog_history: str = ''  # Review dialog transcript
    data: dict[str, Any] = field(default_factory=dict)


@dataclass
class ActorContext:
    """Everything an actor needs to do its work."""
    state: str
    phase: str
    task: str
    infra_dir: str
    project_workdir: str
    session_worktree: str
    stream_file: str
    phase_spec: 'PhaseSpec'
    poc_root: str
    event_bus: EventBus
    session_id: str = ''
    resume_session: str | None = None
    env_vars: dict[str, str] = field(default_factory=dict)
    add_dirs: list[str] = field(default_factory=list)
    backtrack_context: str = ''


# ── AgentRunner ──────────────────────────────────────────────────────────────

class AgentRunner:
    """Invokes Claude CLI as a subprocess, streams output."""

    def __init__(self, stall_timeout: int = 1800):
        self.stall_timeout = stall_timeout

    async def run(self, ctx: ActorContext) -> ActorResult:
        """Run a Claude agent turn and interpret the result."""
        # Build prompt
        prompt = ctx.task
        if ctx.backtrack_context:
            prompt = (
                f"[CfA BACKTRACK: Re-entering from a downstream phase.]\n\n"
                f"Feedback:\n{ctx.backtrack_context}\n\n"
                f"Original task: {ctx.task}"
            )

        # Resolve agent definition file
        agents_path = os.path.join(ctx.poc_root, ctx.phase_spec.agent_file)

        # Build settings with env vars and permissions
        settings = dict(ctx.phase_spec.settings_overlay)
        if ctx.env_vars:
            settings.setdefault('env', {}).update(ctx.env_vars)

        runner = ClaudeRunner(
            prompt=prompt,
            cwd=ctx.session_worktree,
            stream_file=os.path.join(ctx.infra_dir, ctx.phase_spec.stream_file),
            agents_file=agents_path,
            lead=ctx.phase_spec.lead,
            settings=settings,
            permission_mode=ctx.phase_spec.permission_mode,
            add_dirs=ctx.add_dirs,
            resume_session=ctx.resume_session,
            env_vars=ctx.env_vars,
            event_bus=ctx.event_bus,
            stall_timeout=self.stall_timeout,
            session_id=ctx.session_id,
        )

        result = await runner.run()

        if result.stall_killed:
            return ActorResult(action='failed', data={
                'reason': 'stall_timeout',
                'exit_code': result.exit_code,
            })

        if result.exit_code != 0:
            return ActorResult(action='failed', data={
                'reason': 'nonzero_exit',
                'exit_code': result.exit_code,
            })

        # Relocate plan files from ~/.claude/plans/ if needed.
        # Claude stores plans internally when running with --permission-mode plan;
        # the shell version's relocate_new_plans() detected and moved them.
        if ctx.phase_spec.artifact and getattr(ctx.phase_spec, "permission_mode", None) == "plan":
            artifact_path = os.path.join(ctx.session_worktree, ctx.phase_spec.artifact)
            if not os.path.exists(artifact_path) and artifact_path.endswith('.plan'):
                _relocate_plan_file(artifact_path, result.start_time)

        # Detect what the agent produced
        return self._interpret_output(ctx, result)

    def _interpret_output(self, ctx: ActorContext, result: ClaudeResult) -> ActorResult:
        """Check for artifacts and escalation files to determine the action."""
        data: dict = {'claude_session_id': result.session_id}

        # Check for escalation file
        if ctx.phase_spec.escalation_file:
            esc_path = os.path.join(ctx.session_worktree, ctx.phase_spec.escalation_file)
            if os.path.exists(esc_path):
                data['escalation_file'] = esc_path
                action = self._resolve_action(ctx.state, 'escalate')
                return ActorResult(action=action, data=data)

        # Check for expected artifact
        if ctx.phase_spec.artifact:
            artifact_path = os.path.join(ctx.session_worktree, ctx.phase_spec.artifact)
            if os.path.exists(artifact_path):
                data['artifact_path'] = artifact_path
                action = self._resolve_action(ctx.state, 'assert')
                return ActorResult(action=action, data=data)

            # Artifact was expected but not produced — escalate to approval gate.
            # Auto-approve here would bypass the gate entirely; instead, assert
            # into the approval state so the human proxy can decide whether to
            # correct (ask the agent to retry), withdraw, or approve anyway.
            data['artifact_missing'] = True
            data['artifact_expected'] = ctx.phase_spec.artifact
            action = self._resolve_action(ctx.state, 'assert')
            return ActorResult(action=action, data=data)

        # No artifact configured — agent produced output, advance normally
        action = self._resolve_action(ctx.state, 'auto-approve')
        return ActorResult(action=action, data=data)

    @staticmethod
    def _resolve_action(state: str, tentative: str) -> str:
        """Validate tentative action against CfA transitions; map to a valid action if needed.

        When the agent returns a generic success signal (assert/auto-approve) but the
        state expects a specific advancing action (accept, plan, synthesize, delegate),
        pick the first non-negative valid action from the transition table.
        """
        edges = TRANSITIONS.get(state, [])
        valid = {a for a, _, _ in edges}

        if tentative in valid:
            return tentative

        # Map generic success signals to the first forward-advancing action
        if tentative in ('assert', 'auto-approve'):
            _NEGATIVE = frozenset({'withdraw', 'escalate', 'backtrack', 'failed', 'reject',
                                   'refine-intent', 'revise-plan'})
            for action, _, _ in edges:
                if action not in _NEGATIVE:
                    return action

        # Fallback: first available action (shouldn't normally reach here)
        if edges:
            return edges[0][0]
        return tentative


# ── Plan relocation ──────────────────────────────────────────────────────────

def _relocate_plan_file(target_path: str, start_time: float) -> bool:
    """Detect a newly created plan in ~/.claude/plans/ and copy it to target_path.

    Claude stores plans in ~/.claude/plans/ when using --permission-mode plan.
    The shell version (plan-execute.sh) snapshots the directory before/after and
    moves the newest file. This is the Python equivalent.

    Returns True if a plan was successfully relocated.
    """
    plans_dir = Path.home() / '.claude' / 'plans'
    if not plans_dir.is_dir():
        return False

    # Find plan files created after start_time (newest first)
    candidates = []
    for f in plans_dir.iterdir():
        if not f.is_file() or f.suffix != '.md':
            continue
        try:
            mtime = f.stat().st_mtime
        except OSError:
            continue
        if mtime >= start_time:
            candidates.append((mtime, f))

    if not candidates:
        return False

    # Pick the newest
    candidates.sort(reverse=True)
    _, best = candidates[0]

    try:
        shutil.copy2(str(best), target_path)
        return True
    except OSError:
        return False


# ── ApprovalGate ─────────────────────────────────────────────────────────────

_ESCALATION_STATES = frozenset({'INTENT_ESCALATE', 'PLANNING_ESCALATE', 'TASK_REVIEW_ESCALATE'})


class ApprovalGate:
    """Proxy decision + human review loop.

    Consults the human proxy model first.  If confident, auto-approves.
    Otherwise, generates a conversational bridge and asks the human.
    The human's response is classified into a CfA action.
    """

    def __init__(
        self,
        proxy_model_path: str,
        input_provider: InputProvider,
        poc_root: str,
    ):
        self.proxy_model_path = proxy_model_path
        self.input_provider = input_provider
        self.poc_root = poc_root

    async def run(self, ctx: ActorContext) -> ActorResult:
        """Run the approval gate for the current state."""
        artifact_path = ctx.data.get('artifact_path', '')
        escalation_file = ctx.data.get('escalation_file', '')
        artifact_missing = ctx.data.get('artifact_missing', False)
        project_slug = ctx.env_vars.get('POC_PROJECT', 'default')
        team = ctx.env_vars.get('POC_TEAM', '')

        # For escalation states: try generative response first, then human.
        if ctx.state in _ESCALATION_STATES or ctx.state == 'TASK_ESCALATE':
            # Try proxy auto-response from learned patterns
            gen = self._try_generate_response(project_slug, ctx.state, team)
            if gen is not None:
                return ActorResult(
                    action='clarify',
                    feedback=gen.text,
                    data={'generative': True, 'confidence': gen.confidence},
                )

            # Fall through to human with escalation file as bridge
            if escalation_file and os.path.exists(escalation_file):
                try:
                    with open(escalation_file) as _f:
                        bridge_text = _f.read().strip()
                except OSError:
                    bridge_text = f'Agent requested clarification at state: {ctx.state}'
            else:
                bridge_text = f'Agent requested clarification at state: {ctx.state}'
        elif artifact_missing:
            # Agent failed to produce the expected artifact — always escalate to
            # the human. The proxy cannot auto-approve a missing artifact; that
            # would advance the session with no work product to review.
            bridge_text = self._generate_bridge(
                artifact_path, ctx.state, ctx.task, artifact_missing=True,
            )
        else:
            # Step 1: Consult proxy
            proxy_decision = self._proxy_decide(ctx.state, project_slug, artifact_path, team=team)

            if proxy_decision == 'auto-approve':
                self._proxy_record(ctx.state, project_slug, 'approve', artifact_path=artifact_path, team=team)
                return ActorResult(action='approve')

            # Step 2: Generate bridge text for the human
            bridge_text = self._generate_bridge(artifact_path, ctx.state, ctx.task)

        # Step 3: Build context summaries for classification accuracy
        intent_summary = ''
        plan_summary = ''
        intent_path = os.path.join(ctx.infra_dir, 'INTENT.md')
        if not os.path.exists(intent_path):
            intent_path = os.path.join(ctx.session_worktree, 'INTENT.md')
        if os.path.exists(intent_path):
            try:
                with open(intent_path) as _f:
                    intent_summary = _f.read(500)
            except OSError:
                pass
        if artifact_path and os.path.exists(artifact_path):
            try:
                with open(artifact_path) as _f:
                    plan_summary = _f.read(500)
            except OSError:
                pass

        # Step 4: Dialog loop — ask human, classify, maybe dialog more
        dialog_history = ''
        while True:
            await ctx.event_bus.publish(Event(
                type=EventType.INPUT_REQUESTED,
                data={
                    'state': ctx.state,
                    'artifact': artifact_path,
                    'bridge_text': bridge_text,
                },
                session_id=ctx.session_id,
            ))

            response = await self.input_provider(InputRequest(
                type='approval',
                state=ctx.state,
                artifact=artifact_path,
                bridge_text=bridge_text,
            ))

            await ctx.event_bus.publish(Event(
                type=EventType.INPUT_RECEIVED,
                data={'response': response},
                session_id=ctx.session_id,
            ))

            # Classify the response
            action, feedback = self._classify_review(
                ctx.state, response, dialog_history,
                intent_summary=intent_summary, plan_summary=plan_summary,
            )

            if action in ('dialog', '__fallback__'):
                # __fallback__ means classify couldn't parse the response.
                # Treat like a dialog round — generate a contextual reply or
                # a generic re-prompt so the human can try again.
                dialog_history += f'HUMAN: {response}\n'
                if action == '__fallback__':
                    agent_reply = (
                        "I wasn't sure how to interpret that. You can:\n"
                        "  approve — accept and continue\n"
                        "  correct — reject with feedback\n"
                        "  withdraw — abandon this session\n"
                        "Or ask a question and I'll try to answer."
                    )
                else:
                    agent_reply = self._generate_dialog_response(
                        ctx.state, response, artifact_path,
                        os.path.join(ctx.infra_dir, ctx.phase_spec.stream_file),
                        ctx.task, dialog_history,
                    )
                dialog_history += f'AGENT: {agent_reply}\n'
                bridge_text = agent_reply  # Show the reply as the next bridge
                continue

            # Non-dialog action — record and return
            self._proxy_record(
                ctx.state, project_slug, action,
                artifact_path=artifact_path,
                feedback=feedback,
                conversation=dialog_history + f'HUMAN: {response}\n' if dialog_history else response,
                team=team,
            )

            return ActorResult(
                action=action,
                feedback=feedback,
                dialog_history=dialog_history,
            )

    def _proxy_decide(self, state: str, project_slug: str, artifact_path: str = '',
                       team: str = '') -> str:
        """Consult human proxy model.  Returns 'auto-approve' or 'escalate'."""
        try:
            model_path = resolve_team_model_path(self.proxy_model_path, team)
            model = load_model(model_path)
            decision = should_escalate(model, state, project_slug, artifact_path)
            return decision.action
        except Exception:
            return 'escalate'

    def _proxy_record(
        self, state: str, project_slug: str, outcome: str,
        artifact_path: str = '', feedback: str = '', conversation: str = '',
        team: str = '',
    ) -> None:
        """Record human decision for proxy learning."""
        try:
            model_path = resolve_team_model_path(self.proxy_model_path, team)
            model = load_model(model_path)
            artifact_length = 0
            if artifact_path and os.path.exists(artifact_path):
                artifact_length = os.path.getsize(artifact_path)
            patterns = _extract_question_patterns(conversation, outcome)
            model = record_outcome(
                model, state, project_slug, outcome,
                differential_summary=feedback,
                artifact_length=artifact_length,
                question_patterns=patterns,
            )
            save_model(model, model_path)
        except Exception:
            pass

    def _try_generate_response(self, project_slug: str, state: str,
                                team: str = '') -> 'GenerativeResponse | None':
        """Try to generate a proxy auto-response for escalation states."""
        try:
            model_path = resolve_team_model_path(self.proxy_model_path, team)
            model = load_model(model_path)
            return generate_response(model, state, project_slug)
        except Exception:
            return None

    def _classify_review(
        self, state: str, response: str, dialog_history: str = '',
        intent_summary: str = '', plan_summary: str = '',
    ) -> tuple[str, str]:
        """Classify human review response into (action, feedback)."""
        try:
            from projects.POC.scripts.classify_review import classify
            raw = classify(
                state, response,
                intent_summary=intent_summary,
                plan_summary=plan_summary,
                dialog_history=dialog_history,
            )
            parts = raw.split('\t', 1)
            action = parts[0]
            feedback = parts[1] if len(parts) > 1 else ''
            return action, feedback
        except Exception:
            return 'approve', ''

    def _generate_bridge(
        self, artifact_path: str, state: str, task: str, artifact_missing: bool = False,
    ) -> str:
        """Generate conversational summary of artifact for review."""
        if artifact_missing:
            expected_note = (
                f' (expected path: {artifact_path})'
                if artifact_path
                else ''
            )
            return (
                f'The agent did not produce the expected artifact at {state}{expected_note}. '
                'You can:\n'
                '  correct — ask the agent to produce the artifact\n'
                '  withdraw — abandon this session\n'
                '  approve — advance without the artifact (not recommended)'
            )
        if not artifact_path or not os.path.exists(artifact_path):
            return f'Ready for review at {state}.'
        try:
            from projects.POC.scripts.generate_review_bridge import generate
            return generate(artifact_path, state, task)
        except Exception:
            return f'Please review: {artifact_path}'

    def _generate_dialog_response(
        self, state: str, question: str, artifact_path: str,
        exec_stream_path: str, task: str, dialog_history: str,
    ) -> str:
        """Generate agent-voice response to human question."""
        try:
            from projects.POC.scripts.generate_dialog_response import generate
            return generate(
                state, question,
                artifact_path=artifact_path,
                exec_stream_path=exec_stream_path,
                task=task,
                dialog_history=dialog_history,
            )
        except Exception:
            return "I'm not sure I can answer that. Could you rephrase?"

    async def failure_dialog(self, reason: str, ctx: ActorContext) -> str:
        """Ask human what to do after infrastructure failure.

        Returns 'retry' | 'backtrack' | 'withdraw'.
        """
        bridge_text = (
            f'Infrastructure failure: {reason}\n\n'
            'Options:\n'
            '  retry — try the execution phase again\n'
            '  backtrack — return to planning with feedback\n'
            '  withdraw — mark this dispatch as withdrawn\n'
        )
        await ctx.event_bus.publish(Event(
            type=EventType.INPUT_REQUESTED,
            data={'state': 'INFRASTRUCTURE_FAILURE', 'bridge_text': bridge_text},
            session_id=ctx.session_id,
        ))
        response = await self.input_provider(InputRequest(
            type='failure_decision',
            state='INFRASTRUCTURE_FAILURE',
            artifact='',
            bridge_text=bridge_text,
        ))
        response = response.strip().lower()
        if 'backtrack' in response:
            return 'backtrack'
        if 'withdraw' in response:
            return 'withdraw'
        return 'retry'


# ── DispatchRunner ───────────────────────────────────────────────────────────

class DispatchRunner:
    """In-process dispatch path — creates a child orchestrator for subteam delegation.

    NOTE (Gap 58): This class is NOT currently wired to the engine's _invoke_actor routing.
    The live dispatch path today is subprocess-based: agents invoke dispatch.sh, which calls
    dispatch_cli.py as a subprocess. DispatchRunner is the intended future in-process path
    when the engine manages dispatch routing directly without a shell intermediary.

    Do not delete — it already uses make_child_state correctly and implements the full
    dispatch lifecycle. Wire into _invoke_actor when in-process dispatch is ready.
    """

    def __init__(
        self,
        team: str,
        task: str,
        phase_config: 'PhaseConfig',
        input_provider: InputProvider,
        parent_event_bus: EventBus,
    ):
        self.team = team
        self.task = task
        self.phase_config = phase_config
        self.input_provider = input_provider
        self.parent_event_bus = parent_event_bus

    async def run(self, ctx: ActorContext) -> ActorResult:
        """Run dispatch: create child worktree, run child orchestrator, merge."""
        from projects.POC.orchestrator.worktree import (
            create_dispatch_worktree, cleanup_worktree,
        )
        from projects.POC.orchestrator.merge import squash_merge
        from projects.POC.orchestrator.engine import Orchestrator
        from projects.POC.scripts.cfa_state import make_child_state, load_state

        team_spec = self.phase_config.team(self.team)

        # Create dispatch worktree
        dispatch_info = await create_dispatch_worktree(
            team=self.team,
            task=self.task,
            session_worktree=ctx.session_worktree,
            infra_dir=ctx.infra_dir,
        )

        # Create child CfA state
        parent_cfa = load_state(os.path.join(ctx.infra_dir, '.cfa-state.json'))
        child_cfa = make_child_state(parent_cfa, self.team)

        # Publish dispatch start
        await ctx.event_bus.publish(Event(
            type=EventType.DISPATCH_STARTED,
            data={
                'team': self.team,
                'task': self.task,
                'worktree': dispatch_info['worktree_path'],
            },
            session_id=ctx.session_id,
        ))

        # Run child orchestrator
        child_orchestrator = Orchestrator(
            cfa_state=child_cfa,
            phase_config=self.phase_config,
            event_bus=ctx.event_bus,
            input_provider=self.input_provider,
            infra_dir=dispatch_info['infra_dir'],
            project_workdir=dispatch_info['worktree_path'],
            session_worktree=dispatch_info['worktree_path'],
            proxy_model_path=ctx.env_vars.get(
                'PROXY_MODEL',
                os.path.join(ctx.project_workdir, '.proxy-confidence.json'),
            ),
            project_slug=ctx.env_vars.get('POC_PROJECT', ''),
            poc_root=ctx.poc_root,
            task=self.task,
            session_id=ctx.session_id,
            skip_intent=True,  # Dispatched tasks skip intent phase
            team_override=self.team,
        )

        retries = 0
        max_retries = self.phase_config.max_dispatch_retries

        while retries <= max_retries:
            result = await child_orchestrator.run()

            if result.terminal_state == 'COMPLETED_WORK':
                break
            if result.terminal_state == 'WITHDRAWN':
                break
            if result.backtrack_to in ('intent', 'planning') and retries < max_retries:
                retries += 1
                continue
            break

        # Merge child worktree back
        try:
            await squash_merge(
                source=dispatch_info['worktree_path'],
                target=ctx.session_worktree,
                message=f'[{self.team}] {self.task[:80]}',
            )
        except Exception:
            pass

        # Cleanup worktree
        await cleanup_worktree(dispatch_info['worktree_path'])

        # Publish dispatch complete
        await ctx.event_bus.publish(Event(
            type=EventType.DISPATCH_COMPLETED,
            data={
                'team': self.team,
                'task': self.task,
                'terminal_state': result.terminal_state,
            },
            session_id=ctx.session_id,
        ))

        if result.terminal_state == 'COMPLETED_WORK':
            return ActorResult(action='complete', data={'dispatch_result': result})
        else:
            return ActorResult(action='failed', data={'dispatch_result': result})
