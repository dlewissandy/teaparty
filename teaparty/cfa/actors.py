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
from typing import TYPE_CHECKING, Any, Callable, Protocol

from teaparty.runners.claude import ClaudeResult
from teaparty.messaging.bus import (
    Event, EventBus, EventType, InputRequest,
)
from teaparty.cfa.gates.queue import GateQueue
from teaparty.cfa.statemachine.cfa_state import TRANSITIONS
from teaparty.proxy.approval_gate import (
    _extract_question_patterns,
    load_model,
    record_outcome,
    resolve_team_model_path,
    save_model,
)

if TYPE_CHECKING:
    from teaparty.cfa.phase_config import PhaseConfig, PhaseSpec


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

    @property
    def teaparty_home(self) -> str:
        """Management-scope .teaparty/ directory.

        ``poc_root`` is the repo root (from ``find_poc_root()``).  The
        bridge's session walker, the CfA engine's session records, and
        every agent config path are rooted under ``{repo_root}/.teaparty/``.
        This property is the single derived expression — never build the
        path ad-hoc.
        """
        return os.path.join(self.poc_root, '.teaparty')

    session_id: str = ''
    resume_session: str | None = None
    env_vars: dict[str, str] = field(default_factory=dict)
    add_dirs: list[str] = field(default_factory=list)
    backtrack_context: str = ''
    phase_start_time: float = 0.0  # monotonic timestamp when phase started
    # MCPRoutes bundle (spawn_fn, close_fn, escalation) the engine
    # builds once at listener setup; launch() installs it for each
    # agent it spawns so Send / CloseConversation / AskQuestion are
    # reachable — issue #422.
    mcp_routes: Any = None
    data: dict[str, Any] = field(default_factory=dict)
    # Heartbeat liveness (issue #149)
    heartbeat_file: str = ''
    parent_heartbeat: str = ''
    children_file: str = ''


_actor_log = _logging.getLogger('teaparty.cfa.actors')


def _stage_jail_hook(session_worktree: str, hook_script: str) -> None:
    """Copy the CfA jail hook script into the worktree at *hook_script*.

    The hook script lives in the teaparty package at
    ``teaparty/workspace/worktree_hook.py``.  It is copied into the
    worktree so the PreToolUse ``command`` (which references the path
    relative to cwd) resolves without requiring the external project's
    git tree to contain teaparty source.

    Idempotent — overwrites any existing copy.
    """
    src = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        'workspace', 'worktree_hook.py',
    )
    if not os.path.isfile(src):
        raise RuntimeError(
            f'Jail hook source missing from teaparty package: {src}. '
            f'Install is broken.'
        )
    dst = os.path.join(session_worktree, hook_script)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.copy2(src, dst)


def _check_jail_hook(session_worktree: str, hook_script: str) -> None:
    """Raise RuntimeError if the jail hook script is absent from the worktree.

    The hook runs as a subprocess relative to the worktree CWD. If the file is
    missing the subprocess fails silently and agents run without restriction.
    Raising here makes the failure loud and immediate rather than invisible.
    """
    hook_path = os.path.join(session_worktree, hook_script)
    if not os.path.isfile(hook_path):
        raise RuntimeError(
            f'Jail hook script missing: {hook_path}. '
            f'Cannot launch agent without filesystem restriction. '
            f'Ensure {hook_script} exists in the worktree checkout.'
        )


# ── AgentRunner ──────────────────────────────────────────────────────────────

# Actions that indicate failure or regression — never auto-selected as the
# "forward-advancing" action when mapping generic success signals.
_NEGATIVE_ACTIONS = frozenset({
    'withdraw', 'escalate', 'backtrack', 'failed', 'reject',
    'refine-intent', 'revise-plan',
})


class AgentRunner:
    """Invokes Claude CLI as a subprocess, streams output."""

    def __init__(self, stall_timeout: int = 1800, llm_backend: str = 'claude',
                 on_stream_event: Callable[[dict], None] | None = None,
                 llm_caller: Callable | None = None):
        self.stall_timeout = stall_timeout
        self.llm_backend = llm_backend
        self.on_stream_event = on_stream_event
        self._llm_caller = llm_caller  # explicit injection; overrides llm_backend when set

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

        # Resolve agent definitions — try .teaparty/ workgroup format first
        from teaparty.cfa.phase_config import PhaseConfig
        agents_json = ''
        agents_path = ''
        wg_name = ctx.phase_spec.agent_file
        wg_yaml = os.path.join(ctx.teaparty_home, 'project', 'workgroups', f'{wg_name}.yaml')
        if os.path.isfile(wg_yaml):
            config = PhaseConfig(ctx.poc_root)
            agents_json = config.resolve_agents_json(wg_name)
        if not agents_json:
            agents_path = os.path.join(ctx.poc_root, ctx.phase_spec.agent_file)

        # Build settings from the agent's own configuration.  No hidden
        # per-phase overlay — the agent's ``settings.yaml`` (folder
        # permissions) plus its frontmatter ``tools:`` whitelist (what
        # the config UI writes) are the complete source of truth.
        # Issue #150: absolute paths in settings leak into agent context;
        # env vars reach subprocesses via ClaudeRunner._build_env().
        from teaparty.runners.launcher import _merge_settings as _lm
        _teaparty_home_for_agent = os.path.join(ctx.project_workdir, '.teaparty')
        try:
            settings = _lm(ctx.phase_spec.lead, 'project', _teaparty_home_for_agent)
        except Exception:
            settings = {}

        # Issue #150: worktree jail hook — reject Read/Edit/Write calls
        # that use absolute paths or target files outside the worktree.
        # The hook script is staged into the worktree by
        # compose_launch_worktree (runners/launcher.py); the path here
        # must match the staged destination.
        #
        # Schema must match Claude Code's documented hook shape: hooks
        # is a dict keyed by event name, each entry is
        # ``{matcher: "Tool|Tool", hooks: [{type, command}, ...]}``.
        # An ad-hoc shape (event/matchers/handler) silently invalidates
        # the entire settings file — Claude Code falls back to defaults
        # and ``permissions.allow`` is ignored, which manifests as
        # every tool prompting for permission.
        _JAIL_HOOK_SCRIPT = '.claude/hooks/worktree_hook.py'
        _stage_jail_hook(ctx.session_worktree, _JAIL_HOOK_SCRIPT)
        _check_jail_hook(ctx.session_worktree, _JAIL_HOOK_SCRIPT)
        jail_hook = {
            'type': 'command',
            'command': f'python3 {_JAIL_HOOK_SCRIPT}',
        }
        hooks_section = settings.setdefault('hooks', {})
        if not isinstance(hooks_section, dict):
            hooks_section = {}
            settings['hooks'] = hooks_section
        pre = hooks_section.setdefault('PreToolUse', [])
        pre.append({
            'matcher': 'Read|Edit|Write|Glob|Grep',
            'hooks': [jail_hook],
        })

        from teaparty.runners.launcher import launch, _default_ollama_caller
        _caller: Callable | None = self._llm_caller
        if _caller is None and self.llm_backend == 'ollama':
            _caller = _default_ollama_caller
        launch_kwargs: dict = {}
        if _caller is not None:
            launch_kwargs['llm_caller'] = _caller
        # Point the agent's claude -p at the bridge's MCP HTTP endpoint
        # so ``mcp__teaparty-config__*`` tools (Send, CloseConversation,
        # AskQuestion, ...) are actually reachable.  Without this the
        # allowlist still contains them but claude -p sees no such server
        # and the agent cannot delegate.  Env var matches the dispatch
        # paths in engine.py.
        _mcp_port = int(os.environ.get('TEAPARTY_BRIDGE_PORT', '9000'))
        result = await launch(
            agent_name=ctx.phase_spec.lead,
            message=prompt,
            scope='project',
            telemetry_scope=ctx.env_vars.get('POC_PROJECT', 'project'),
            mcp_port=_mcp_port,
            # Agent definitions live in the project's own .teaparty/project/agents/
            # directory; the org management catalog is the fallback (Issue #408).
            teaparty_home=os.path.join(ctx.project_workdir, '.teaparty'),
            org_home=ctx.teaparty_home,
            worktree=ctx.session_worktree,
            resume_session=ctx.resume_session or '',
            on_stream_event=self.on_stream_event,
            event_bus=ctx.event_bus,
            session_id=ctx.session_id,
            heartbeat_file=ctx.heartbeat_file,
            parent_heartbeat=ctx.parent_heartbeat,
            children_file=ctx.children_file,
            stall_timeout=self.stall_timeout,
            settings_override=settings,
            add_dirs=ctx.add_dirs,
            agents_json=agents_json or None,
            agents_file=agents_path or None,
            stream_file=os.path.join(ctx.infra_dir, ctx.phase_spec.stream_file),
            env_vars=ctx.env_vars,
            permission_mode_override=ctx.phase_spec.permission_mode,
            mcp_routes=ctx.mcp_routes,
            # The lead's own conv_id — the JOB conv.  MCP middleware
            # uses this to set ``current_conversation_id`` so any Send
            # the lead makes is parented under the JOB conv (which is
            # what the job page's dispatch tree walks from).  Without
            # this the lead's dispatches would be parented under the
            # wrong conv_id and their blades never render.
            caller_conversation_id=(
                f'job:{ctx.env_vars.get("POC_PROJECT", "")}:{ctx.session_id}'
                if ctx.env_vars.get('POC_PROJECT') and ctx.session_id
                else ''
            ),
            **launch_kwargs,
        )

        if result.stall_killed:
            return ActorResult(action='failed', data={
                'reason': 'stall_timeout',
                'exit_code': result.exit_code,
                'stderr_lines': result.stderr_lines,
            })

        if result.exit_code != 0:
            reason = 'api_overloaded' if result.api_overloaded else 'nonzero_exit'
            return ActorResult(action='failed', data={
                'reason': reason,
                'exit_code': result.exit_code,
                'stderr_lines': result.stderr_lines,
            })

        # Relocate plan files from ~/.claude/plans/ if needed.
        # Claude stores plans internally when running with --permission-mode plan.
        if ctx.phase_spec.artifact and getattr(ctx.phase_spec, "permission_mode", None) == "plan":
            artifact_path = os.path.join(ctx.session_worktree, ctx.phase_spec.artifact)
            if not os.path.exists(artifact_path):
                _relocate_plan_file(artifact_path, result.start_time)

        # Relocate misplaced artifacts: agents sometimes write to arbitrary
        # absolute paths.  Parse the stream JSONL to find where the agent
        # actually wrote, and move the file to session_worktree so it is
        # visible to the reviewer and to subagents.
        stream_path = os.path.join(ctx.infra_dir, ctx.phase_spec.stream_file)
        if ctx.phase_spec.artifact:
            _relocate_misplaced_artifact(
                ctx.session_worktree, stream_path,
                ctx.phase_spec.artifact,
            )

        # Detect what the agent produced
        actor_result = self._interpret_output(ctx, result)

        # Carry cost data for budget tracking (Issue #262)
        if result.cost_usd:
            actor_result.data['cost_usd'] = result.cost_usd
        if result.cost_per_model:
            actor_result.data['cost_per_model'] = result.cost_per_model
        # Carry turn stats for job chat cost sender (Issue #341)
        if result.input_tokens:
            actor_result.data['input_tokens'] = result.input_tokens
        if result.output_tokens:
            actor_result.data['output_tokens'] = result.output_tokens
        if result.duration_ms:
            actor_result.data['duration_ms'] = result.duration_ms

        # Emit artifact detection for --verbose tracing
        await ctx.event_bus.publish(Event(
            type=EventType.LOG,
            data={
                'category': 'artifact_detection',
                'state': ctx.state,
                'action': actor_result.action,
                'artifact_path': actor_result.data.get('artifact_path', ''),
            },
            session_id=ctx.session_id,
        ))

        return actor_result

    def _interpret_output(self, ctx: ActorContext, result: ClaudeResult) -> ActorResult:
        """Check for artifacts to determine the action."""
        data: dict = {'claude_session_id': result.session_id}
        if result.stderr_lines:
            data['stderr_lines'] = result.stderr_lines
        # Pass context budget to the engine for turn-boundary decisions (Issue #260)
        data['context_budget'] = result.context_budget

        # Carry the actor's last assistant text so the next gate can use it
        # as the triggering message — what the agent said as they hit the
        # gate. The gate then composes a self-contained bridge to the
        # proxy/human instead of substituting a canonical template.
        actor_message = _last_assistant_text(result.stream_file)
        if actor_message:
            data['actor_message'] = actor_message

        # Skill-driven phases terminate by writing .phase-outcome.json with
        # an explicit {outcome, reason} payload. When present, trust it as
        # the authoritative signal — the skill has self-terminated, no
        # artifact-presence inference needed.
        outcome_action = self._read_phase_outcome(ctx)
        if outcome_action is not None:
            action, reason = outcome_action
            if reason:
                data['outcome_reason'] = reason
            return ActorResult(action=action, data=data)

        # Check for expected artifact in the session worktree.
        if ctx.phase_spec.artifact:
            artifact_path = _find_artifact(
                ctx.session_worktree, ctx.phase_spec.artifact,
            )
            if artifact_path:
                data['artifact_path'] = artifact_path
                action = self._resolve_action(ctx.state, 'assert')
                return ActorResult(action=action, data=data)

            # Artifact not produced — pick the safest loop-back action.
            # The ASSERT gate must never be entered without the artifact.
            action = self._no_artifact_action_for_state(ctx.state)
            return ActorResult(action=action, data=data)

        # No artifact configured — agent produced output, advance normally
        action = self._resolve_action(ctx.state, 'auto-approve')
        return ActorResult(action=action, data=data)

    def _read_phase_outcome(
        self, ctx: ActorContext,
    ) -> tuple[str, str] | None:
        """Return (action, reason) when the skill wrote .phase-outcome.json.

        The file is consumed (deleted) on read so a subsequent phase run
        cannot pick up a stale outcome. Unknown outcomes are treated as
        absent so the caller falls back to artifact inference.
        """
        path = os.path.join(ctx.session_worktree, '.phase-outcome.json')
        if not os.path.isfile(path):
            return None
        try:
            with open(path) as f:
                payload = json.load(f)
        except (json.JSONDecodeError, OSError):
            return None
        try:
            os.unlink(path)
        except OSError:
            pass
        outcome = str(payload.get('outcome', '')).upper()
        reason = str(payload.get('reason', ''))

        # Each skill outcome names the *target state* the skill wants to
        # advance or backtrack to.  Resolve to the actual state-machine
        # action by finding the edge from the current state that leads
        # there.  Returns None if the target isn't reachable from
        # ctx.state — strict rejection, not silent misrouting.
        edges = TRANSITIONS.get(ctx.state, [])
        action: str | None = None
        if outcome == 'APPROVE':
            # Forward advance — 'approve' (intent/planning/WORK_ASSERT)
            # or 'auto-approve' (WORK_IN_PROGRESS).
            for a, _, _ in edges:
                if a in ('approve', 'auto-approve'):
                    action = a
                    break
        elif outcome == 'REALIGN':
            for a, to, _ in edges:
                if to == 'INTENT':
                    action = a
                    break
        elif outcome == 'REPLAN':
            for a, to, _ in edges:
                if to == 'PLAN':
                    action = a
                    break
        elif outcome == 'WITHDRAW':
            for a, to, _ in edges:
                if to == 'WITHDRAWN':
                    action = a
                    break

        if action is None:
            return None
        return action, reason

    @staticmethod
    def _no_artifact_action_for_state(state: str) -> str:
        """Return the action to take when the expected artifact was not produced.

        Skills terminate by writing .phase-outcome.json; this fallback is
        only reached when a skill exited without both the outcome and the
        expected artifact. Withdraw is the safe terminal — anything else
        would advance the phase without evidence the work was done.
        """
        edges = TRANSITIONS.get(state, [])
        valid = {a for a, _, _ in edges}
        if 'withdraw' in valid:
            return 'withdraw'
        return edges[0][0] if edges else 'withdraw'

    @staticmethod
    def _resolve_action(state: str, tentative: str) -> str:
        """Validate tentative action against CfA transitions; map to a valid action if needed.

        When the agent returns a generic success signal (assert/auto-approve) but the
        state expects a specific advancing action, pick the first non-negative
        valid action from the transition table.
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
    """Move an artifact to target_dir so it exists in exactly one location.

    Parses the stream JSONL to find the actual path the agent used in its
    Write or Edit tool calls.  If the file was written elsewhere, moves it
    to target_dir/<artifact_name>.

    Always refreshes the target — after corrections at approval gates, the
    agent re-edits the artifact and the existing copy becomes stale.
    Issue #157.

    Returns True if a file was moved.
    """
    # Find where the agent actually wrote/edited the artifact
    actual_path = _find_artifact_path_in_stream(stream_file, artifact_name)
    if not actual_path:
        return False

    if not os.path.isfile(actual_path):
        return False  # agent wrote it but file is gone (shouldn't happen)

    expected = os.path.join(target_dir, artifact_name)

    # Skip if the source IS the target (agent wrote directly to the right place)
    if os.path.abspath(actual_path) == os.path.abspath(expected):
        return False

    try:
        shutil.move(actual_path, expected)
        _actor_log.info(
            'Moved artifact to worktree: %s → %s', actual_path, expected,
        )
        return True
    except OSError:
        _actor_log.warning(
            'Failed to move artifact: %s → %s', actual_path, expected,
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


def _last_assistant_text(stream_file: str) -> str:
    """Return the last assistant text block in *stream_file*.

    The gate uses this as the actor's self-contained triggering message —
    what the agent wrote as they hit the gate.  Empty when the stream
    file is missing, unreadable, or the turn produced no text blocks.
    """
    if not stream_file or not os.path.isfile(stream_file):
        return ''
    last_text = ''
    try:
        with open(stream_file) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except (json.JSONDecodeError, ValueError):
                    continue
                if event.get('type') != 'assistant':
                    continue
                content = event.get('message', {}).get('content', [])
                buf: list[str] = []
                for item in content:
                    if not isinstance(item, dict):
                        continue
                    if item.get('type') != 'text':
                        continue
                    text = item.get('text', '').strip()
                    if text:
                        buf.append(text)
                if buf:
                    last_text = '\n'.join(buf)
    except OSError:
        return ''
    return last_text


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


# ── CfA state → learning phase mapping ───────────────────────────────────────

_CFA_STATE_TO_PHASE: dict[str, str] = {
    'EXECUTE': 'implementation',
}


# ── ApprovalGate ─────────────────────────────────────────────────────────────


# Gate templates: per-state (decision, doc_specs) pairs.  The gate
# composes a three-slot bridge to the proxy/human — the decision being
# asked, the documents available, and the actor's own triggering message.
# The gate does not substitute a canonical question for what the actor
# actually said; it makes the request actionable by naming the decision
# and the resources, then carries the actor's message through unchanged.
#
# doc_specs is an ordered list of (filename, one-line-purpose) pairs.
# Files that don't exist at review time are silently skipped.
_GATE_TEMPLATES: dict[str, tuple[str, list[tuple[str, str]]]] = {
    'EXECUTE': (
        'Approve or revise the overall deliverable.',
        [
            ('WORK_SUMMARY.md', "the lead's completion summary"),
            ('PLAN.md', 'the approved plan'),
            ('INTENT.md', 'the approved intent'),
        ],
    ),
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
        never_escalate: bool = False,
        escalation_modes: dict[str, str] | None = None,
        gate_queue: GateQueue | None = None,
    ):
        self.proxy_model_path = proxy_model_path
        self.input_provider = input_provider
        self.poc_root = poc_root
        self.proxy_enabled = proxy_enabled
        self.never_escalate = never_escalate
        # Per-state override of the escalation decision.  Keys are CfA state
        # names; values are 'always' (force human escalation), 'when_unsure'
        # (default; use proxy's confidence), or 'never' (force proxy answer).
        self.escalation_modes = escalation_modes or {}
        self.gate_queue = gate_queue
        self._gate_lock = asyncio.Lock()  # Serializes concurrent gate processing (#202)
        self._last_proxy_result = None  # Most recent ProxyResult for memory recording
        # Set by engine when a skill-based plan is active (Issue #146).
        # Used by _log_interaction to tag gate outcomes with the skill name.
        self._active_skill: dict[str, str] | None = None

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

        # Telemetry: gate_opened (Issue #405)
        try:
            from teaparty.telemetry import record_event
            from teaparty.telemetry import events as _telem_events
            record_event(
                _telem_events.GATE_OPENED,
                scope=project_slug or 'management',
                session_id=ctx.session_id,
                data={'gate_type': ctx.state, 'phase_entering': ctx.state},
            )
        except Exception:
            pass

        from teaparty.proxy.agent import consult_proxy
        actor_message = ctx.data.get('actor_message', '')
        gate_question = self._generate_bridge(
            artifact_path, ctx.state, ctx.task,
            session_worktree=ctx.session_worktree,
            infra_dir=ctx.infra_dir,
            actor_message=actor_message,
        )
        dialog_history = ''
        next_bridge = ''  # set after dialog turns to show the agent's reply

        # NOTE on gate-question publishing:  Do NOT publish the gate question
        # up front.  Publishing before we're ready to listen creates a race:
        # the user sees the prompt and responds during the long consult_proxy
        # call, but MessageBusInputProvider captures its `since` timestamp
        # only when it starts polling — so the human's reply predates `since`
        # and is lost.  Instead, the gate question is published at the point
        # where the answer will actually be acted on: inside
        # _ask_human_through_proxy_inner for the proxy-answer paths, and via
        # MessageBusInputProvider's bridge_text write for the human-asked
        # paths.  Both happen after consult_proxy returns.

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

            # Classify the response (offloaded to executor — Issue #180).
            loop = asyncio.get_running_loop()
            action, feedback = await loop.run_in_executor(
                None, self._classify_review,
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

            team = ctx.env_vars.get('POC_TEAM', '')
            if action != 'dialog':
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

                # Telemetry: gate_passed / gate_failed (Issue #405)
                try:
                    from teaparty.telemetry import record_event
                    from teaparty.telemetry import events as _telem_events
                    if action == 'approve':
                        record_event(
                            _telem_events.GATE_PASSED,
                            scope=project_slug or 'management',
                            session_id=ctx.session_id,
                            data={'gate_type': ctx.state},
                        )
                    else:
                        record_event(
                            _telem_events.GATE_FAILED,
                            scope=project_slug or 'management',
                            session_id=ctx.session_id,
                            data={
                                'gate_type': ctx.state,
                                'reason_len': len(feedback or ''),
                                'resulted_in_backtrack': action in (
                                    'correct', 'reject', 'backtrack',
                                ),
                            },
                        )
                except Exception:
                    pass

                return ActorResult(
                    action=action, feedback=feedback,
                    dialog_history=dialog_history,
                )

            # Dialog — generate a reply, then loop back.  The reply becomes
            # the bridge text for the next turn so the human sees the answer.
            dialog_history += f'{speaker}: {response_text}\n'
            stream_path = (
                os.path.join(ctx.infra_dir, ctx.phase_spec.stream_file)
                if ctx.phase_spec and ctx.infra_dir
                else ''
            )
            try:
                agent_reply = await loop.run_in_executor(
                    None, lambda: self._generate_dialog_response(
                        ctx.state, response_text, artifact_path,
                        stream_path,
                        ctx.task, dialog_history,
                        session_worktree=ctx.session_worktree,
                    ),
                )
            except Exception:
                _actor_log.warning(
                    'Dialog response generation failed at %s — using fallback',
                    ctx.state, exc_info=True,
                )
                agent_reply = (
                    "I'm not sure I can answer that right now. "
                    "Could you rephrase, or let me know your decision?"
                )
            _actor_log.info(
                'Gate dialog reply at %s: action=%s agent_reply=%r',
                ctx.state, action, agent_reply[:120] if agent_reply else '',
            )
            dialog_history += f'AGENT: {agent_reply}\n'
            next_bridge = agent_reply
            # Publish the agent's dialog reply to the job conversation so it
            # appears in the accordion alongside the proxy's probe.  This
            # response is generated by a blocking LLM call (not streamed
            # through the Claude CLI handler), so it would otherwise be
            # invisible.  Use the phase's configured lead (e.g.
            # ``joke-book-lead``) so the chat attribution matches the
            # streamed agent text; a hardcoded ``'agent'`` would produce
            # a second persona for the same speaker.
            lead_sender = (
                ctx.phase_spec.lead if ctx.phase_spec and ctx.phase_spec.lead
                else 'agent'
            )
            self._publish_to_job_conversation(
                ctx, project_slug, lead_sender, agent_reply,
            )

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

        Gate processing is serialized via _gate_lock with FIFO ordering through
        the GateQueue so concurrent gates from parallel dispatches are handled
        one at a time in arrival order (Issue #202).
        """
        from teaparty.cfa.gates.queue import GateRequest
        if self.gate_queue is not None:
            self.gate_queue.enqueue(GateRequest(
                state=ctx.state, team=ctx.env_vars.get('POC_TEAM', ''),
            ))
        async with self._gate_lock:
            if self.gate_queue is not None:
                self.gate_queue.dequeue()
            return await self._ask_human_through_proxy_inner(
                ctx, question, artifact_path, project_slug, team,
                dialog_history, bridge_override,
            )

    def _check_pending_human_input(
        self, ctx: ActorContext, project_slug: str,
    ) -> str:
        """Return the most recent un-consumed human message, or empty string.

        A human message is "pending" if it is the most recent message in
        the job conversation AND nothing from the orchestrator/agent/proxy
        has been written after it.  This catches the post-resume case:
        the user's message triggers `_resume_job_session`, the session
        resumes and re-enters the gate, but if we ran consult_proxy first
        (~30s) the triggering message would be skipped because
        MessageBusInputProvider captures its `since` cutoff only after
        consult_proxy returns.
        """
        if not project_slug or not ctx.session_id or not ctx.infra_dir:
            return ''
        bus_path = os.path.join(ctx.infra_dir, 'messages.db')
        if not os.path.exists(bus_path):
            return ''
        try:
            from teaparty.messaging.conversations import SqliteMessageBus
            conv_id = f'job:{project_slug}:{ctx.session_id}'
            bus = SqliteMessageBus(bus_path)
            try:
                messages = bus.receive(conv_id, since_timestamp=0)
            finally:
                bus.close()
        except Exception:
            _actor_log.debug('pending-input check failed', exc_info=True)
            return ''
        # Walk backwards: find the latest human message that has no
        # non-human message after it.  The initial task is sent as
        # sender='human' on session start, but it's always followed by
        # orchestrator output before reaching a gate — so it won't be
        # mistaken for a pending reply.
        for msg in reversed(messages):
            if msg.sender == 'human':
                return msg.content
            # Found a non-human message first → no pending human input.
            return ''
        return ''

    async def _ask_human_through_proxy_inner(
        self, ctx: ActorContext, question: str, artifact_path: str,
        project_slug: str, team: str, dialog_history: str,
        bridge_override: str = '',
    ) -> tuple[str, bool]:
        """Inner implementation of _ask_human_through_proxy (runs under _gate_lock)."""
        from teaparty.proxy.agent import (
            consult_proxy, PROXY_AGENT_CONFIDENCE_THRESHOLD,
        )

        # Fast path 1: if the human has already posted a response waiting
        # for this gate (typical after a session resume that was triggered
        # by the user's POST), consume it directly.  Skipping consult_proxy
        # avoids a ~30s detour and a race where the triggering message is
        # filtered out by the listener's `since` cutoff.
        pending = self._check_pending_human_input(ctx, project_slug)
        if pending:
            return pending, False

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
        self._last_proxy_result = proxy_result

        # Fast path 2: during the 15-30s consult_proxy call, the human may
        # have posted a reply of their own.  Human input always wins over
        # the proxy's observation — use it directly instead of acting on
        # the proxy's answer.  Without this check, the user's feedback is
        # silently ignored when the proxy is confident.
        pending = self._check_pending_human_input(ctx, project_slug)
        if pending:
            return pending, False

        # Per-gate escalation mode.  Inputs to the decision are exactly
        # (gate_mode, proxy_confidence) — no presence check.
        #
        #   always        → skip proxy, ask the human.
        #   never         → proxy answers unconditionally.
        #   when_unsure   → proxy answers if confident, else escalate
        #                    to the human.
        gate_mode = self.escalation_modes.get(ctx.state, 'when_unsure')
        force_human = (gate_mode == 'always')
        force_proxy = (gate_mode == 'never')

        team = ctx.env_vars.get('POC_TEAM', '')
        actor_message = ctx.data.get('actor_message', '')
        if force_human:
            # Skip the proxy entirely — escalation config says this gate
            # always goes to the human.
            bridge_text = bridge_override or self._generate_bridge(
                artifact_path, ctx.state, ctx.task,
                session_worktree=ctx.session_worktree, infra_dir=ctx.infra_dir,
                actor_message=actor_message,
            )
            response_text = await self.input_provider(InputRequest(
                type='approval', state=ctx.state,
                artifact=artifact_path, bridge_text=bridge_text,
            ))
            # Learning signal: the delta between what the proxy would
            # have said and what the human actually said.
            pr = self._last_proxy_result
            self._proxy_record(
                ctx.state, project_slug, 'approve',
                artifact_path=artifact_path, team=team,
                feedback=response_text,
                conversation=response_text,
                prediction=pr.text if pr else '',
                predicted_response=pr.text if pr else '',
            )
            self._log_interaction(
                ctx, project_slug,
                prediction=pr.text if pr else '',
                outcome='human_direct',
                delta=response_text,
            )
            return response_text, False

        proxy_confident = (
            proxy_result.from_agent
            and proxy_result.confidence >= PROXY_AGENT_CONFIDENCE_THRESHOLD
            and proxy_result.text
        )

        # Publish the canonical gate question (sender 'gate') only on the
        # first turn of this gate — the first time the proxy is being asked
        # about the current artifact.  On subsequent turns, bridge_override
        # carries the agent's reply to the proxy's prior probe, and that
        # reply has already been published (by the dialog-reply write above)
        # under the phase lead's name — re-publishing here would duplicate it.
        first_turn = not bridge_override

        def _gate_bridge() -> str:
            return self._generate_bridge(
                artifact_path, ctx.state, ctx.task,
                session_worktree=ctx.session_worktree,
                infra_dir=ctx.infra_dir,
                actor_message=actor_message,
            )

        if proxy_confident:
            if first_turn:
                self._publish_to_job_conversation(
                    ctx, project_slug, 'gate',
                    f'[{ctx.state}] {_gate_bridge()}',
                )
            self._publish_to_job_conversation(
                ctx, project_slug, 'proxy', proxy_result.text,
            )
            return proxy_result.text, True

        # Never-escalate: per-gate mode or ApprovalGate flag.  With
        # task-level gates gone, the only sources of never-escalate are
        # explicit config ('never' in escalation_modes) or the
        # engine-level flag.
        if force_proxy or self.never_escalate:
            if first_turn:
                self._publish_to_job_conversation(
                    ctx, project_slug, 'gate',
                    f'[{ctx.state}] {_gate_bridge()}',
                )
            self._publish_to_job_conversation(
                ctx, project_slug, 'proxy', proxy_result.text,
            )
            return proxy_result.text, True

        # Proxy can't answer — escalate to the actual human.
        # If there's a bridge override (e.g., the agent's reply to a prior
        # question), show that instead of the composed gate bridge.
        bridge_text = bridge_override or _gate_bridge()
        # Surface the proxy's low-confidence attempt (if any) before the
        # human is asked, so their dialog is preserved in the accordion.
        self._publish_to_job_conversation(
            ctx, project_slug, 'proxy', proxy_result.text,
        )
        response_text = await self.input_provider(InputRequest(
            type='approval', state=ctx.state,
            artifact=artifact_path, bridge_text=bridge_text,
        ))
        return response_text, False

    def _publish_to_job_conversation(
        self, ctx: 'ActorContext', project_slug: str,
        sender: str, content: str,
    ) -> None:
        """Write a single message to the job conversation for accordion visibility.

        Used to surface gate-loop interactions (gate questions, proxy replies,
        agent dialog responses) that don't flow through the Claude CLI stream
        handler and would otherwise be invisible.
        """
        if not content:
            return
        bus_path = os.path.join(ctx.infra_dir, 'messages.db')
        if not os.path.exists(bus_path) or not project_slug or not ctx.session_id:
            return
        try:
            from teaparty.messaging.conversations import SqliteMessageBus
            conv_id = f'job:{project_slug}:{ctx.session_id}'
            bus = SqliteMessageBus(bus_path)
            try:
                bus.send(conv_id, sender, content)
            finally:
                bus.close()
        except Exception:
            _actor_log.debug('job-conversation publish failed', exc_info=True)

    def _proxy_record(
        self, state: str, project_slug: str, outcome: str,
        artifact_path: str = '', feedback: str = '', conversation: str = '',
        team: str = '', prediction: str = '', predicted_response: str = '',
    ) -> None:
        """Record human decision for proxy learning (EMA + ACT-R memory)."""
        # EMA recording (existing)
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
            _actor_log.warning('EMA recording failed', exc_info=True)

        # ACT-R memory chunk recording
        pr = self._last_proxy_result
        try:
            from teaparty.proxy.memory import (
                open_proxy_db,
                resolve_memory_db_path,
                record_interaction,
            )
            db_path = resolve_memory_db_path(self.proxy_model_path, team)
            conn = open_proxy_db(db_path)
            try:
                # Read artifact summary for embedding (truncated)
                artifact_text = ''
                if artifact_path and os.path.isfile(artifact_path):
                    try:
                        with open(artifact_path) as f:
                            artifact_text = f.read(4000)
                    except OSError:
                        pass

                record_interaction(
                    conn,
                    interaction_type='gate_outcome',
                    state=state,
                    task_type=project_slug,
                    outcome=outcome,
                    content=conversation or feedback or '',
                    delta=feedback if outcome == 'correct' else '',
                    human_response=feedback or predicted_response or '',
                    prior_confidence=pr.prior_confidence if pr else 0.0,
                    posterior_confidence=pr.posterior_confidence if pr else 0.0,
                    prediction_delta=pr.prediction_delta if pr else '',
                    salient_percepts=pr.salient_percepts if pr else [],
                    situation_text=f'{state} {project_slug}',
                    artifact_text=artifact_text,
                    stimulus_text=conversation[:500] if conversation else '',
                )
            finally:
                conn.close()
        except Exception:
            _actor_log.debug('ACT-R memory recording failed', exc_info=True)

        # Emit structured learning entry to proxy-tasks/ on corrections.
        # This integrates proxy corrections with the broader learning system:
        # entries are YAML-frontmattered markdown indexed by memory_indexer.py,
        # retrievable by agents via retrieve(learning_type='proxy').
        if outcome in ('correct', 'reject') and feedback:
            try:
                self._emit_proxy_learning_entry(
                    state=state,
                    project_slug=project_slug,
                    outcome=outcome,
                    feedback=feedback,
                    conversation=conversation,
                    artifact_path=artifact_path,
                )
            except Exception:
                _actor_log.debug('Proxy learning entry emission failed', exc_info=True)

    def _emit_proxy_learning_entry(
        self, state: str, project_slug: str, outcome: str,
        feedback: str, conversation: str, artifact_path: str = '',
    ) -> None:
        """Write a structured learning entry to proxy-tasks/ for a correction.

        The entry uses the same YAML frontmatter format as other learning
        entries (memory_entry.py), so it can be indexed by memory_indexer.py
        and retrieved via retrieve(learning_type='proxy').

        The entry carries the full correction signal: what CfA state, what
        artifact type, what the proxy predicted, what the human actually said,
        and the delta between them.  This is the highest-value learning signal
        in the system — it reveals where the proxy's model diverges from reality.
        """
        from teaparty.learning.episodic.entry import make_entry, serialize_entry

        phase = _CFA_STATE_TO_PHASE.get(state, 'unknown')

        # Extract the artifact type from the path (e.g., PLAN.md, INTENT.md)
        artifact_type = os.path.basename(artifact_path) if artifact_path else 'unknown'

        # Include the proxy's confidence trajectory if available — the delta
        # between prediction and reality is the highest-value learning signal.
        # Categorical action classification was removed in 583cccd8; actions
        # are now classified downstream from the final human response via
        # _classify_review, so the proxy-side fields here are confidence-only.
        pr = self._last_proxy_result
        prediction_block = ''
        if pr:
            prediction_block = (
                f"**Proxy prior confidence:** {pr.prior_confidence:.2f}\n"
                f"**Proxy posterior confidence:** {pr.posterior_confidence:.2f}\n"
            )
            if pr.prediction_delta:
                prediction_block += f"**Prediction delta:** {pr.prediction_delta}\n"
            if pr.salient_percepts:
                prediction_block += (
                    f"**Salient percepts:** {', '.join(pr.salient_percepts)}\n"
                )

        entry = make_entry(
            content=(
                f"## Proxy Correction at {state}\n"
                f"**State:** {state}\n"
                f"**Project:** {project_slug}\n"
                f"**Artifact type:** {artifact_type}\n"
                f"**Correction:** {feedback}\n"
                f"{prediction_block}"
            ),
            type='corrective',
            domain='task',
            importance=0.8,
            phase=phase,
        )

        project_dir = os.path.dirname(self.proxy_model_path)
        proxy_tasks_dir = os.path.join(project_dir, 'proxy-tasks')
        os.makedirs(proxy_tasks_dir, exist_ok=True)

        filename = f'correction-{entry.id}.md'
        filepath = os.path.join(proxy_tasks_dir, filename)
        with open(filepath, 'w') as f:
            f.write(serialize_entry(entry))

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
        # Tag with skill name when a skill-based plan is active (Issue #146)
        if self._active_skill:
            entry['skill_name'] = self._active_skill['name']
        try:
            with open(log_path, 'a') as f:
                f.write(json.dumps(entry) + '\n')
        except OSError:
            pass

    def _classify_review(
        self, state: str, response: str, dialog_history: str = '',
        intent_summary: str = '', plan_summary: str = '',
    ) -> tuple[str, str]:
        """Classify human review response into (action, feedback).

        On classifier failure or an unparseable response, returns
        ('dialog', '') so the gate loop re-prompts rather than silently
        committing to an action.  'dialog' is not a CfA state-machine
        edge; it is the gate's internal signal to loop back and ask again.
        """
        try:
            from teaparty.scripts.classify_review import classify
            raw = classify(
                state, response,
                intent_summary=intent_summary,
                plan_summary=plan_summary,
                dialog_history=dialog_history,
            )
            parts = raw.split('\t', 1)
            action = parts[0]
            feedback = parts[1] if len(parts) > 1 else ''
            # classify_review emits '__fallback__' when it can't parse its
            # own output — map to 'dialog' so the gate re-prompts instead
            # of driving the CfA with a sentinel that is not a valid edge.
            if action == '__fallback__':
                return 'dialog', ''
            return action, feedback
        except Exception:
            _actor_log.warning('Classification failed — re-prompting', exc_info=True)
            return 'dialog', ''

    def _generate_bridge(
        self, artifact_path: str, state: str, task: str,
        session_worktree: str = '', infra_dir: str = '',
        actor_message: str = '',
    ) -> str:
        """Compose the gate's bridge — a self-contained Send to the reviewer.

        Three slots, same across every gate:
          1. ``Decide: <decision>`` — what the reviewer is being asked to do.
          2. ``Available:`` — a list of files that may help, with a one-line
             purpose for each. Files that don't exist right now are skipped.
          3. The actor's own triggering message — what the agent wrote as
             they hit the gate. The gate never fabricates a substitute.

        Slot 1 and slot 2 come from the per-state ``_GATE_TEMPLATES`` table;
        slot 3 comes from the caller (plumbed from the previous actor's
        ``ActorResult.data['actor_message']``).
        """
        template = _GATE_TEMPLATES.get(state)
        if template is None:
            parts = [f'Decide: review state {state}.']
            if actor_message:
                parts.extend(['', actor_message.strip()])
            return '\n'.join(parts)

        decision, doc_specs = template
        lines = [f'Decide: {decision}', '', 'Available:']

        if artifact_path and os.path.isfile(artifact_path):
            lines.append(f'  {artifact_path} — the artifact under review')

        for filename, desc in doc_specs:
            for search_dir in (session_worktree, infra_dir):
                if not search_dir:
                    continue
                candidate = os.path.join(search_dir, filename)
                if os.path.isfile(candidate):
                    lines.append(f'  {candidate} — {desc}')
                    break

        if actor_message:
            lines.extend(['', actor_message.strip()])

        return '\n'.join(lines)

    def _generate_dialog_response(
        self, state: str, question: str, artifact_path: str,
        exec_stream_path: str, task: str, dialog_history: str,
        session_worktree: str = '',
    ) -> str:
        """Generate agent-voice response to human question."""
        try:
            from teaparty.scripts.generate_dialog_response import generate
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
        response = await self.input_provider(InputRequest(
            type='failure_decision',
            state='INFRASTRUCTURE_FAILURE',
            artifact='',
            bridge_text=bridge_text,
        ))
        action, _feedback = self._classify_review('FAILURE', response)
        if action in ('backtrack', 'withdraw'):
            return action
        return 'retry'


