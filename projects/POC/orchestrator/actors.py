"""Actor runners — pluggable handlers for each CfA actor type.

The orchestrator calls the right actor based on the `actor` field from
the CfA transition table.  Each actor returns an ActorResult describing
which CfA action to take next.

Actor types:
  AgentRunner    — invokes Claude CLI, streams output, detects artifacts
  ApprovalGate   — proxy decision + human review loop
"""
from __future__ import annotations

import asyncio
import json
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
    _extract_question_patterns,
    load_model,
    record_outcome,
    resolve_team_model_path,
    save_model,
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
    phase_start_time: float = 0.0  # monotonic timestamp when phase started
    mcp_config: dict[str, Any] | None = None
    data: dict[str, Any] = field(default_factory=dict)


# ── Work summary generation ──────────────────────────────────────────────────

import logging as _logging

_actor_log = _logging.getLogger('orchestrator.actors')


async def _generate_work_summary(worktree: str) -> None:
    """Generate .work-summary.md from dispatch merge commits in the worktree.

    Called before _interpret_output() during the execution phase so that
    the artifact exists for the approval gate (WORK_ASSERT) to review.
    Regenerated on every pass so correction rounds accumulate.
    """
    from projects.POC.orchestrator.merge import git_output

    # Scope the log to session-only commits by finding where the branch
    # diverged from main.  Without this, the entire main history leaks
    # into the work summary (Issue #127).
    merge_base = (await git_output(worktree, 'merge-base', 'HEAD', 'main')).strip()
    range_spec = f'{merge_base}..HEAD' if merge_base else 'HEAD'

    # Get dispatch merge commits with per-commit file stats,
    # filtering out WIP infrastructure commits from merge.py.
    log_output = await git_output(
        worktree, 'log',
        range_spec,
        '--format=### %s%n%n%b',
        '--stat',
        '--reverse',
        '--grep=^WIP:', '--invert-grep',
    )

    if not log_output.strip():
        # No work to summarize — write a minimal placeholder so the
        # artifact still exists for the approval gate.
        content = '# Work Summary\n\nNo dispatch work recorded.\n'
    else:
        content = '# Work Summary\n\n' + log_output.strip() + '\n'

    summary_path = os.path.join(worktree, '.work-summary.md')
    with open(summary_path, 'w') as f:
        f.write(content)
    _actor_log.info('Generated work summary: %s', summary_path)


# ── AgentRunner ──────────────────────────────────────────────────────────────

# Minimum seconds an execution phase must run before the proxy can auto-approve.
# If TASK_ASSERT or WORK_ASSERT fires faster than this, always escalate — the
# elapsed time is too short relative to any non-trivial plan.  (Issue #122)
MIN_EXECUTION_SECONDS = 120


class AgentRunner:
    """Invokes Claude CLI as a subprocess, streams output."""

    def __init__(self, stall_timeout: int = 1800):
        self.stall_timeout = stall_timeout

    async def run(self, ctx: ActorContext) -> ActorResult:
        """Run a Claude agent turn and interpret the result."""
        # Build prompt
        prompt = ctx.task
        if ctx.backtrack_context:
            # Distinguish escalation responses from downstream backtracks
            has_human_feedback = '[human feedback]' in ctx.backtrack_context
            if has_human_feedback:
                header = '[CfA RESPONSE: The human has responded to your escalation.]'
            else:
                header = '[CfA BACKTRACK: Re-entering from a downstream phase.]'
            prompt = (
                f"{header}\n\n"
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
            mcp_config=ctx.mcp_config,
        )

        result = await runner.run()

        if result.stall_killed:
            return ActorResult(action='failed', data={
                'reason': 'stall_timeout',
                'exit_code': result.exit_code,
                'stderr_lines': result.stderr_lines,
            })

        if result.exit_code != 0:
            return ActorResult(action='failed', data={
                'reason': 'nonzero_exit',
                'exit_code': result.exit_code,
                'stderr_lines': result.stderr_lines,
            })

        # Relocate plan files from ~/.claude/plans/ if needed.
        # Claude stores plans internally when running with --permission-mode plan;
        # the shell version's relocate_new_plans() detected and moved them.
        if ctx.phase_spec.artifact and getattr(ctx.phase_spec, "permission_mode", None) == "plan":
            artifact_path = os.path.join(ctx.session_worktree, ctx.phase_spec.artifact)
            if not os.path.exists(artifact_path):
                _relocate_plan_file(artifact_path, result.start_time)

        # Relocate misplaced artifacts: agents sometimes write to arbitrary
        # absolute paths instead of the session worktree (their cwd).  Parse
        # the stream JSONL to find where the agent actually wrote, and move
        # the file to the worktree so the approval gate and TUI always find it.
        stream_path = os.path.join(ctx.infra_dir, ctx.phase_spec.stream_file)
        if ctx.phase_spec.artifact:
            _relocate_misplaced_artifact(
                ctx.session_worktree, stream_path,
                ctx.phase_spec.artifact,
            )

        # Generate work summary for execution phase (Issue #116).
        # Only at WORK_IN_PROGRESS — this is where the lead has finished
        # delegating and the summary should reflect all dispatch merges.
        # Other execution states (TASK_IN_PROGRESS, COMPLETED_TASK) don't
        # need the summary and would produce stale content.
        if ctx.state == 'WORK_IN_PROGRESS':
            await _generate_work_summary(ctx.session_worktree)

        # Detect what the agent produced
        actor_result = self._interpret_output(ctx, result)

        # Emit artifact detection for --verbose tracing
        await ctx.event_bus.publish(Event(
            type=EventType.LOG,
            data={
                'category': 'artifact_detection',
                'state': ctx.state,
                'action': actor_result.action,
                'artifact_path': actor_result.data.get('artifact_path', ''),
                'artifact_missing': actor_result.data.get('artifact_missing', False),
                'artifact_expected': actor_result.data.get('artifact_expected', ''),
            },
            session_id=ctx.session_id,
        ))

        return actor_result

    def _interpret_output(self, ctx: ActorContext, result: ClaudeResult) -> ActorResult:
        """Check for artifacts to determine the action."""
        data: dict = {'claude_session_id': result.session_id}
        if result.stderr_lines:
            data['stderr_lines'] = result.stderr_lines

        # Check for expected artifact
        if ctx.phase_spec.artifact:
            artifact_path = _find_artifact(
                ctx.session_worktree, ctx.phase_spec.artifact,
            )
            if artifact_path:
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


# ── Artifact search ─────────────────────────────────────────────────────────


def _relocate_misplaced_artifact(
    worktree: str, stream_file: str, artifact_name: str,
) -> bool:
    """Move an artifact to the worktree if the agent wrote it elsewhere.

    Parses the stream JSONL to find the actual path the agent used in its
    Write tool call.  If the file was written outside the worktree, moves
    it to worktree/<artifact_name>.

    This is deterministic and location-agnostic — it doesn't guess where
    the agent might have written; it reads where it actually did write.

    Returns True if a file was relocated.
    """
    expected = os.path.join(worktree, artifact_name)
    if os.path.exists(expected):
        return False  # already in the right place

    # Parse stream JSONL for Write tool calls matching the artifact name
    actual_path = _find_write_path_in_stream(stream_file, artifact_name)
    if not actual_path:
        return False

    if not os.path.isfile(actual_path):
        return False  # agent wrote it but file is gone (shouldn't happen)

    try:
        shutil.move(actual_path, expected)
        _actor_log.info(
            'Relocated misplaced artifact: %s → %s', actual_path, expected,
        )
        return True
    except OSError:
        _actor_log.warning(
            'Failed to relocate artifact: %s → %s', actual_path, expected,
            exc_info=True,
        )
        return False


def _find_write_path_in_stream(stream_file: str, artifact_name: str) -> str:
    """Scan a stream JSONL file for the last Write tool call that wrote artifact_name.

    Returns the absolute file_path from the Write tool input, or '' if not found.
    """
    import json as _json

    if not stream_file or not os.path.isfile(stream_file):
        return ''

    last_path = ''
    try:
        with open(stream_file) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    evt = _json.loads(line)
                except ValueError:
                    continue
                for block in evt.get('message', {}).get('content', []):
                    if not isinstance(block, dict):
                        continue
                    if block.get('name') != 'Write':
                        continue
                    file_path = block.get('input', {}).get('file_path', '')
                    if file_path and os.path.basename(file_path) == artifact_name:
                        last_path = file_path
    except OSError:
        pass

    return last_path


def _find_artifact(worktree: str, artifact_name: str) -> str:
    """Find an artifact in the worktree.  Checks the root first, then
    searches up to one level deep.  Returns the path or '' if not found.

    Agents sometimes write artifacts to subdirectories or with slightly
    different casing.  This search ensures the approval gate always gets
    the artifact if the agent produced it anywhere in the worktree.
    """
    # 1. Check the expected location (worktree root)
    expected = os.path.join(worktree, artifact_name)
    if os.path.exists(expected):
        return expected

    # 2. Case-insensitive check at root
    name_lower = artifact_name.lower()
    try:
        for entry in os.listdir(worktree):
            if entry.lower() == name_lower and os.path.isfile(os.path.join(worktree, entry)):
                found = os.path.join(worktree, entry)
                _actor_log.info('Artifact found with different casing: %s', found)
                return found
    except OSError:
        pass

    # 3. Search one level of subdirectories
    try:
        for entry in os.listdir(worktree):
            subdir = os.path.join(worktree, entry)
            if not os.path.isdir(subdir) or entry.startswith('.'):
                continue
            candidate = os.path.join(subdir, artifact_name)
            if os.path.exists(candidate):
                _actor_log.info('Artifact found in subdirectory: %s', candidate)
                return candidate
    except OSError:
        pass

    return ''


# ── ApprovalGate ─────────────────────────────────────────────────────────────


# Canonical alignment questions for each approval gate.  These are the
# questions the proxy and human both see — no LLM rephrasing.
_GATE_QUESTIONS: dict[str, str] = {
    'INTENT_ASSERT': 'Do you recognize this as your idea, completely and accurately articulated?',
    'PLAN_ASSERT': 'Do you recognize this as a strategic plan to operationalize your idea well?',
    'WORK_ASSERT': 'Do you recognize the deliverables and project files as your idea, completely and well implemented?',
}


class ApprovalGate:
    """Proxy agent + human review loop.

    The proxy is a Claude agent that generates the same kind of text response
    a human would give.  When confident, the agent's text IS the answer.
    When not confident, the same question goes to the human.  Both the
    agent's predicted text and the actual answer feed into learning.
    The final text (from either source) is classified by _classify_review.
    """

    def __init__(
        self,
        proxy_model_path: str,
        input_provider: InputProvider,
        poc_root: str,
        proxy_enabled: bool = True,
    ):
        self.proxy_model_path = proxy_model_path
        self.input_provider = input_provider
        self.poc_root = poc_root
        self.proxy_enabled = proxy_enabled

    async def run(self, ctx: ActorContext) -> ActorResult:
        """Run the approval gate for the current state."""
        artifact_path = ctx.data.get('artifact_path', '')
        project_slug = ctx.env_vars.get('POC_PROJECT', 'default')
        team = ctx.env_vars.get('POC_TEAM', '')

        # ONE path: consult the proxy agent.  proxy_enabled=False skips the
        # agent inside consult_proxy and goes straight to the human.
        from projects.POC.orchestrator.proxy_agent import (
            consult_proxy, run_proxy_agent, PROXY_AGENT_CONFIDENCE_THRESHOLD,
        )
        gate_question = _GATE_QUESTIONS.get(ctx.state, f'Please review: {artifact_path}')

        proxy_result = await consult_proxy(
            question=gate_question,
            state=ctx.state,
            project_slug=project_slug,
            artifact_path=artifact_path,
            session_worktree=ctx.session_worktree,
            infra_dir=ctx.infra_dir,
            proxy_model_path=self.proxy_model_path,
            team=team,
            phase_start_time=ctx.phase_start_time,
            proxy_enabled=self.proxy_enabled,
        )

        await ctx.event_bus.publish(Event(
            type=EventType.LOG,
            data={
                'category': 'proxy_decision',
                'state': ctx.state,
                'decision': 'agent' if proxy_result.from_agent else 'escalate',
                'confidence': proxy_result.confidence,
                'reasoning': f'Proxy agent confidence: {proxy_result.confidence:.2f}' if proxy_result.from_agent else 'Escalated to human',
            },
            session_id=ctx.session_id,
        ))

        if proxy_result.from_agent and proxy_result.confidence >= PROXY_AGENT_CONFIDENCE_THRESHOLD:
            # The proxy agent generated text.  Run the dialog loop:
            # classify the text, and if it's a question, get a reply
            # from the requester and give the proxy another turn.
            agent_text = proxy_result.text
            proxy_dialog_history = ''
            max_proxy_turns = 5

            for _turn in range(max_proxy_turns):
                action, feedback = self._classify_review(
                    ctx.state, agent_text,
                    intent_summary='', plan_summary='',
                    dialog_history=proxy_dialog_history,
                )

                if action not in ('dialog', '__fallback__'):
                    self._proxy_record(
                        ctx.state, project_slug, action,
                        artifact_path=artifact_path, team=team,
                        prediction='approve',
                        predicted_response=agent_text,
                        conversation=proxy_dialog_history,
                    )
                    self._log_interaction(
                        ctx, project_slug, prediction='approve', outcome=action,
                        delta=feedback if action != 'approve' else '',
                        exploration=False,
                    )
                    return ActorResult(
                        action=action, feedback=feedback,
                        dialog_history=proxy_dialog_history,
                    )

                # Proxy asked a question — get requester's answer
                proxy_dialog_history += f'PROXY: {agent_text}\n'
                requester_reply = self._generate_dialog_response(
                    ctx.state, agent_text, artifact_path,
                    os.path.join(ctx.infra_dir, ctx.phase_spec.stream_file),
                    ctx.task, proxy_dialog_history,
                    session_worktree=ctx.session_worktree,
                )
                proxy_dialog_history += f'REQUESTER: {requester_reply}\n'

                await ctx.event_bus.publish(Event(
                    type=EventType.LOG,
                    data={
                        'category': 'proxy_dialog',
                        'state': ctx.state,
                        'proxy_question': agent_text,
                        'requester_reply': requester_reply,
                        'turn': _turn,
                    },
                    session_id=ctx.session_id,
                ))

                agent_text, agent_confidence = await run_proxy_agent(
                    question=gate_question,
                    state=ctx.state,
                    artifact_path=artifact_path,
                    session_worktree=ctx.session_worktree,
                    infra_dir=ctx.infra_dir,
                    dialog_history=proxy_dialog_history,
                )

                if agent_confidence < PROXY_AGENT_CONFIDENCE_THRESHOLD:
                    break

        # Falls through to human review.
        bridge_text = self._generate_bridge(
            artifact_path, ctx.state, ctx.task,
            session_worktree=ctx.session_worktree, infra_dir=ctx.infra_dir,
        )

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
                # Both dialog and __fallback__ mean the human said something
                # that isn't a clear decision.  Generate a contextual reply
                # so the human can refine or ask follow-up questions.
                dialog_history += f'HUMAN: {response}\n'
                agent_reply = self._generate_dialog_response(
                    ctx.state, response, artifact_path,
                    os.path.join(ctx.infra_dir, ctx.phase_spec.stream_file),
                    ctx.task, dialog_history,
                    session_worktree=ctx.session_worktree,
                )
                dialog_history += f'AGENT: {agent_reply}\n'
                bridge_text = agent_reply  # Show the reply as the next bridge

                # Log the dialog exchange for post-hoc debugging (#120)
                await ctx.event_bus.publish(Event(
                    type=EventType.LOG,
                    data={
                        'category': 'approval_dialog',
                        'state': ctx.state,
                        'human_input': response,
                        'classification': action,
                        'agent_reply': agent_reply,
                    },
                    session_id=ctx.session_id,
                ))
                continue

            # Non-dialog action — record and return.
            # Pass the proxy's predicted response text so the differential
            # captures predicted vs. actual (#138).
            prediction = 'escalate'
            predicted_text = getattr(proxy_result, 'text', '') \
                if 'proxy_result' in dir() else ''
            self._proxy_record(
                ctx.state, project_slug, action,
                artifact_path=artifact_path,
                feedback=feedback,
                conversation=dialog_history + f'HUMAN: {response}\n' if dialog_history else response,
                team=team,
                prediction=prediction,
                predicted_response=predicted_text,
            )
            self._log_interaction(
                ctx, project_slug,
                prediction=prediction,
                outcome=action,
                delta=feedback if action != 'approve' else '',
                exploration=False,
            )

            return ActorResult(
                action=action,
                feedback=feedback,
                dialog_history=dialog_history,
            )

    def _proxy_record(
        self, state: str, project_slug: str, outcome: str,
        artifact_path: str = '', feedback: str = '', conversation: str = '',
        team: str = '', prediction: str = '', predicted_response: str = '',
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
                prediction=prediction,
                predicted_response=predicted_response,
            )
            save_model(model, model_path)
        except Exception:
            pass

    def _log_interaction(
        self, ctx: ActorContext, project_slug: str,
        prediction: str, outcome: str, delta: str,
        exploration: bool = False,
    ) -> None:
        """Append a proxy interaction log entry (JSONL) for learning.

        Each entry records: what the proxy predicted, what actually happened,
        and the delta between them.  This is the foundation for prediction
        accuracy tracking and retrospective learning (#11).
        """
        from datetime import datetime, timezone
        log_path = os.path.join(
            os.path.dirname(self.proxy_model_path),
            '.proxy-interactions.jsonl',
        )
        entry = {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'session_id': ctx.session_id,
            'project': project_slug,
            'state': ctx.state,
            'prediction': prediction,
            'outcome': outcome,
            'delta': delta,
            'exploration': exploration,
        }
        try:
            with open(log_path, 'a') as f:
                f.write(json.dumps(entry) + '\n')
        except OSError:
            pass

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
            _actor_log.warning('Classification failed — falling back to re-prompt', exc_info=True)
            return '__fallback__', ''

    def _generate_bridge(
        self, artifact_path: str, state: str, task: str,
        artifact_missing: bool = False,
        session_worktree: str = '', infra_dir: str = '',
    ) -> str:
        """Generate alignment validation bridge for review.

        Reads upstream context files (INTENT.md, PLAN.md) so the reviewer
        can compare the artifact under review against its source of truth.
        """
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

        # Use canonical gate question if one exists for this state.
        if state in _GATE_QUESTIONS:
            return _GATE_QUESTIONS[state]

        return f'Please review: {artifact_path}'

    def _generate_dialog_response(
        self, state: str, question: str, artifact_path: str,
        exec_stream_path: str, task: str, dialog_history: str,
        session_worktree: str = '',
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
                worktree=session_worktree,
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


