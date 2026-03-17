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
import logging as _logging
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

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

_actor_log = _logging.getLogger('orchestrator.actors')


async def _generate_work_summary(worktree: str, *, infra_dir: str = '') -> None:
    """Generate .work-summary.md from dispatch merge commits in the worktree.

    Called before _interpret_output() during the execution phase so that
    the artifact exists for the approval gate (WORK_ASSERT) to review.
    Regenerated on every pass so correction rounds accumulate.

    The summary is written to infra_dir (session infrastructure) rather than
    the worktree, so it doesn't pollute the git branch or leak into future
    sessions.  Issue #147.
    """
    from projects.POC.orchestrator.merge import git_output

    target_dir = infra_dir or worktree

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

    summary_path = os.path.join(target_dir, '.work-summary.md')
    with open(summary_path, 'w') as f:
        f.write(content)
    _actor_log.info('Generated work summary: %s', summary_path)


# ── AgentRunner ──────────────────────────────────────────────────────────────

# Actions that indicate failure or regression — never auto-selected as the
# "forward-advancing" action when mapping generic success signals.
_NEGATIVE_ACTIONS = frozenset({
    'withdraw', 'escalate', 'backtrack', 'failed', 'reject',
    'refine-intent', 'revise-plan',
})

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

        # On resume, all previous task/agent handles are dead.  The
        # orchestrator process that owned them is gone — TaskOutput on
        # any prior task ID will return "No task found".  Tell the agent
        # so it doesn't burn budget polling phantom handles.
        if ctx.resume_session:
            prompt = (
                '[SESSION RESUMED — STALE TASK HANDLES]\n'
                'This conversation is being resumed after a restart. '
                'All background task and agent handles from the previous '
                'run are dead — calling TaskOutput or checking on prior '
                'task IDs will fail with "No task found". Do not poll '
                'them. Instead, assess progress from what is on disk '
                '(files already written) and re-dispatch any incomplete '
                'work.\n\n'
                + prompt
            )

        # Resolve agent definition file
        agents_path = os.path.join(ctx.poc_root, ctx.phase_spec.agent_file)

        # Build settings — do NOT inject env_vars into settings env.
        # Issue #150: absolute paths in settings leak into agent context,
        # causing agents to write to wrong locations.  Env vars are still
        # available to subprocesses (dispatch_cli.py) via ClaudeRunner._build_env().
        settings = dict(ctx.phase_spec.settings_overlay)

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
        # Claude stores plans internally when running with --permission-mode plan.
        if ctx.phase_spec.artifact and getattr(ctx.phase_spec, "permission_mode", None) == "plan":
            artifact_path = os.path.join(ctx.infra_dir, ctx.phase_spec.artifact)
            if not os.path.exists(artifact_path):
                _relocate_plan_file(artifact_path, result.start_time)

        # Relocate misplaced artifacts: agents sometimes write to arbitrary
        # absolute paths instead of the infra dir.  They may write to their
        # cwd (the worktree), to ~/.claude/plans/, or elsewhere.  Parse
        # the stream JSONL to find where the agent actually wrote, and move
        # the file to infra_dir so session artifacts don't pollute the
        # worktree.  Issue #147.
        stream_path = os.path.join(ctx.infra_dir, ctx.phase_spec.stream_file)
        if ctx.phase_spec.artifact:
            _relocate_misplaced_artifact(
                ctx.infra_dir, stream_path,
                ctx.phase_spec.artifact,
            )

        # Generate work summary for execution phase (Issue #116).
        # Only at WORK_IN_PROGRESS — this is where the lead has finished
        # delegating and the summary should reflect all dispatch merges.
        # Other execution states (TASK_IN_PROGRESS, COMPLETED_TASK) don't
        # need the summary and would produce stale content.
        if ctx.state == 'WORK_IN_PROGRESS':
            await _generate_work_summary(ctx.session_worktree, infra_dir=ctx.infra_dir)

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

        # Check for expected artifact — look in infra_dir (Issue #147).
        if ctx.phase_spec.artifact:
            artifact_path = _find_artifact(
                ctx.infra_dir, ctx.phase_spec.artifact,
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
            for action, _, _ in edges:
                if action not in _NEGATIVE_ACTIONS:
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
    target_dir: str, stream_file: str, artifact_name: str,
) -> bool:
    """Copy an artifact to target_dir, refreshing if the source is newer.

    Parses the stream JSONL to find the actual path the agent used in its
    Write or Edit tool calls.  If the file was written elsewhere (e.g., the
    agent's cwd / worktree), copies it to target_dir/<artifact_name>.

    Always refreshes the target — after corrections at approval gates, the
    agent edits the artifact in the worktree but the infra_dir copy was
    stale.  Issue #157.

    The source file is left in place — the worktree copy is needed for git
    commits (dispatch worktree inheritance) while the infra_dir copy is the
    orchestrator's live read path.  Issue #147.

    Returns True if a file was copied.
    """
    # Find where the agent actually wrote/edited the artifact
    actual_path = _find_artifact_path_in_stream(stream_file, artifact_name)
    if not actual_path:
        return False

    if not os.path.isfile(actual_path):
        return False  # agent wrote it but file is gone (shouldn't happen)

    expected = os.path.join(target_dir, artifact_name)

    # Skip if the source IS the target (agent wrote directly to infra_dir)
    if os.path.abspath(actual_path) == os.path.abspath(expected):
        return False

    try:
        shutil.copy2(actual_path, expected)
        _actor_log.info(
            'Copied artifact to infra: %s → %s', actual_path, expected,
        )
        return True
    except OSError:
        _actor_log.warning(
            'Failed to copy artifact: %s → %s', actual_path, expected,
            exc_info=True,
        )
        return False


def _find_artifact_path_in_stream(stream_file: str, artifact_name: str) -> str:
    """Scan a stream JSONL file for the last Write or Edit tool call that
    touched artifact_name.

    Returns the absolute file_path from the tool input, or '' if not found.
    Detects both Write and Edit calls so that post-correction edits are
    found.  Issue #157.
    """
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
                    evt = json.loads(line)
                except ValueError:
                    continue
                for block in evt.get('message', {}).get('content', []):
                    if not isinstance(block, dict):
                        continue
                    if block.get('name') not in ('Write', 'Edit'):
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
    'TASK_ASSERT': 'Does this work look like your task, correctly executed?',
    'WORK_ASSERT': 'Do you recognize the deliverables and project files as your idea, completely and well implemented?',
}

# States where the proxy runs but never escalates to the human.
# The proxy still reads deliverables, asks questions, and uses learned
# patterns — but if it's not confident, it goes with its best guess.
_NEVER_ESCALATE_STATES: frozenset[str] = frozenset({
    'TASK_ASSERT',
    'TASK_ESCALATE',
})

# Max consecutive __fallback__ retries at _NEVER_ESCALATE states before
# auto-approving.  At these states the proxy is the sole decision-maker;
# retrying the same empty proxy call is pointless.  WORK_ASSERT downstream
# will catch real problems.  Issue #155.
_MAX_FALLBACK_RETRIES = 3


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
        never_escalate: bool = False,
    ):
        self.proxy_model_path = proxy_model_path
        self.input_provider = input_provider
        self.poc_root = poc_root
        self.proxy_enabled = proxy_enabled
        self.never_escalate = never_escalate

    async def run(self, ctx: ActorContext) -> ActorResult:
        """Run the approval gate for the current state.

        ONE loop.  Every turn: ask the human through the proxy.  Classify
        the response.  If terminal, done.  If dialog, loop.

        "Ask the human through the proxy" means: call consult_proxy, which
        either returns the proxy agent's text (if confident) or escalates
        to the actual human (if not).  The approval gate does not know or
        care which source produced the text.
        """
        artifact_path = ctx.data.get('artifact_path', '')
        project_slug = ctx.env_vars.get('POC_PROJECT', 'default')
        team = ctx.env_vars.get('POC_TEAM', '')

        from projects.POC.orchestrator.proxy_agent import consult_proxy
        gate_question = _GATE_QUESTIONS.get(ctx.state, f'Please review: {artifact_path}')
        dialog_history = ''
        next_bridge = ''  # set after dialog turns to show the agent's reply
        fallback_count = 0

        while True:
            # Ask the human — through the proxy.
            response_text, from_proxy = await self._ask_human_through_proxy(
                ctx=ctx,
                question=gate_question,
                artifact_path=artifact_path,
                project_slug=project_slug,
                team=team,
                dialog_history=dialog_history,
                bridge_override=next_bridge,
            )
            next_bridge = ''  # consumed
            # Label for dialog history — Issue #151
            speaker = 'PROXY' if from_proxy else 'HUMAN'

            # Classify the response.
            action, feedback = self._classify_review(
                ctx.state, response_text, dialog_history,
            )

            await ctx.event_bus.publish(Event(
                type=EventType.LOG,
                data={
                    'category': 'approval_dialog',
                    'state': ctx.state,
                    'response': response_text[:200],
                    'classification': action,
                },
                session_id=ctx.session_id,
            ))

            # At _NEVER_ESCALATE states the proxy is the sole decision-maker.
            # If it consistently fails (returns empty → __fallback__), retrying
            # is pointless.  Auto-approve so WORK_ASSERT can catch real problems
            # downstream.  Issue #155.
            if action == '__fallback__' and ctx.state in _NEVER_ESCALATE_STATES:
                fallback_count += 1
                if fallback_count >= _MAX_FALLBACK_RETRIES:
                    _actor_log.warning(
                        'Proxy failed %d times at %s — auto-approving',
                        fallback_count, ctx.state,
                    )
                    action = 'approve'
                    feedback = ''
                    # Clear dialog_history — the "dialog" entries are just
                    # empty proxy responses, not real human conversation.
                    # Without this, the approve→correct conversion below
                    # would fire and send stale empty text as feedback.
                    dialog_history = ''

            if action not in ('dialog', '__fallback__'):
                # Terminal action.  But if there was dialog, the human was
                # providing clarification — feed that back to the agent phase
                # as "correct" so the agent gets another pass with context.
                if dialog_history and action == 'approve':
                    action = 'correct'
                    feedback = dialog_history + f'{speaker}: {response_text}\n'

                self._proxy_record(
                    ctx.state, project_slug, action,
                    artifact_path=artifact_path, team=team,
                    feedback=feedback,
                    conversation=dialog_history + response_text,
                )
                self._log_interaction(
                    ctx, project_slug,
                    prediction='proxy', outcome=action,
                    delta=feedback if action != 'approve' else '',
                )
                return ActorResult(
                    action=action, feedback=feedback,
                    dialog_history=dialog_history,
                )

            # Dialog — generate a reply, then loop back.  The reply becomes
            # the bridge text for the next turn so the human sees the answer.
            dialog_history += f'{speaker}: {response_text}\n'
            agent_reply = self._generate_dialog_response(
                ctx.state, response_text, artifact_path,
                os.path.join(ctx.infra_dir, ctx.phase_spec.stream_file),
                ctx.task, dialog_history,
                session_worktree=ctx.session_worktree,
            )
            dialog_history += f'AGENT: {agent_reply}\n'
            next_bridge = agent_reply

    async def _ask_human_through_proxy(
        self, ctx: ActorContext, question: str, artifact_path: str,
        project_slug: str, team: str, dialog_history: str,
        bridge_override: str = '',
    ) -> tuple[str, bool]:
        """Ask the human through the proxy.  Returns (response_text, from_proxy).

        from_proxy is True when the proxy answered (confident or never-escalate),
        False when the actual human was asked.  Callers use this to label
        dialog entries PROXY: vs HUMAN: so downstream agents can distinguish
        the source.  Issue #151.

        consult_proxy handles everything: statistical pre-filters, agent
        invocation, confidence check, and escalation to the actual human
        if the proxy can't answer.  This method is the single interface
        between the approval gate and the proxy system.
        """
        from projects.POC.orchestrator.proxy_agent import (
            consult_proxy, PROXY_AGENT_CONFIDENCE_THRESHOLD,
        )

        proxy_result = await consult_proxy(
            question=question,
            state=ctx.state,
            project_slug=project_slug,
            artifact_path=artifact_path,
            session_worktree=ctx.session_worktree,
            infra_dir=ctx.infra_dir,
            proxy_model_path=self.proxy_model_path,
            team=team,
            phase_start_time=ctx.phase_start_time,
            proxy_enabled=self.proxy_enabled,
            dialog_history=dialog_history,
        )

        proxy_confident = (
            proxy_result.from_agent
            and proxy_result.confidence >= PROXY_AGENT_CONFIDENCE_THRESHOLD
            and proxy_result.text
        )

        if proxy_confident:
            return proxy_result.text, True

        # Never-escalate: the proxy's text is always the answer.
        if self.never_escalate or ctx.state in _NEVER_ESCALATE_STATES:
            return proxy_result.text, True

        # Proxy can't answer — escalate to the actual human.
        # If there's a bridge override (e.g., the agent's reply to a prior
        # question), show that instead of the generic gate question.
        bridge_text = bridge_override or self._generate_bridge(
            artifact_path, ctx.state, ctx.task,
            session_worktree=ctx.session_worktree, infra_dir=ctx.infra_dir,
        )
        await ctx.event_bus.publish(Event(
            type=EventType.INPUT_REQUESTED,
            data={'state': ctx.state, 'artifact': artifact_path, 'bridge_text': bridge_text},
            session_id=ctx.session_id,
        ))
        response_text = await self.input_provider(InputRequest(
            type='approval', state=ctx.state,
            artifact=artifact_path, bridge_text=bridge_text,
        ))
        await ctx.event_bus.publish(Event(
            type=EventType.INPUT_RECEIVED,
            data={'response': response_text},
            session_id=ctx.session_id,
        ))
        return response_text, False

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


