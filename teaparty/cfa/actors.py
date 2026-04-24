"""Actor runner — invokes Claude CLI, streams output, detects artifacts.

The orchestrator calls this for every CfA phase (intent, planning,
execution).  The agent itself is always the project lead running
the phase skill; the skill writes ``./.phase-outcome.json`` and halts.
Human approval happens inside the skill's ASSERT step via
``AskQuestion → proxy``, not in a separate actor.

(Historical note: a sibling ``ApprovalGate`` class used to run a
proxy+human review loop as its own actor.  It was dead code after
the 5-state + skill-based redesign — the transition table has no
actor named ``human`` or ``approval_gate`` — and was removed.)
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
from teaparty.cfa.statemachine.cfa_state import TRANSITIONS

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
    project_slug: str = ''
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
            telemetry_scope=ctx.project_slug or 'project',
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
                f'job:{ctx.project_slug}:{ctx.session_id}'
                if ctx.project_slug and ctx.session_id
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

        # No artifact configured AND no ``.phase-outcome.json`` — the
        # skill ended its turn without declaring an outcome.  This is
        # the normal mid-execute state: the lead dispatched via Send
        # and its turn ended; fan-in must re-invoke the lead so it can
        # synthesize the workers' replies and run its ASSERT gate
        # before declaring APPROVE.
        #
        # Return ``action=''`` as the "no outcome" sentinel.  The
        # outer ``_run_phase`` loop decides what to do:
        #   - workers in flight → fan-in wait, re-invoke, try again
        #   - no workers + no outcome → the skill is genuinely broken
        #     and the engine must raise (no silent approvals).
        #
        # Previously this path returned ``action='auto-approve'`` —
        # a silent approval that let EXECUTE → DONE whenever the
        # lead's turn ended, even if it was just after a Send.  The
        # skill's ASSERT gate never ran, the dispatched work never
        # got reviewed.  That is the bug; this is the kill.
        return ActorResult(action='', data=data)

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
            for a, _ in edges:
                if a in ('approve', 'auto-approve'):
                    action = a
                    break
        elif outcome == 'REALIGN':
            for a, to in edges:
                if to == 'INTENT':
                    action = a
                    break
        elif outcome == 'REPLAN':
            for a, to in edges:
                if to == 'PLAN':
                    action = a
                    break
        elif outcome == 'WITHDRAW':
            for a, to in edges:
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
        valid = {a for a, _ in edges}
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
        valid = {a for a, _ in edges}

        if tentative in valid:
            return tentative

        # Map generic success signals to the first forward-advancing action
        if tentative in ('assert', 'auto-approve'):
            for action, _ in edges:
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

