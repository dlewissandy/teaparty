"""Async wrapper around the Claude CLI subprocess.

All agent turns are invoked via `claude -p --output-format stream-json`.
Stream output is tailed line-by-line, persisted to the JSONL file, and
published as STREAM_DATA events.
"""
from __future__ import annotations

import asyncio
import json
import os
import signal
import tempfile
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol

from teaparty.util.context_budget import ContextBudget
from teaparty.messaging.bus import Event, EventBus, EventType
from teaparty.runners.machine import RunnerSM
from teaparty.bridge.state.heartbeat import _process_create_time


@dataclass
class ClaudeResult:
    exit_code: int
    session_id: str = ''
    stream_file: str = ''
    stall_killed: bool = False
    start_time: float = 0.0
    cost_usd: float = 0.0
    cost_per_model: dict[str, float] = field(default_factory=dict)
    input_tokens: int = 0
    output_tokens: int = 0
    duration_ms: int = 0
    stderr_lines: list[str] = field(default_factory=list)
    context_budget: ContextBudget = field(default_factory=ContextBudget)
    # ── Issue #431: additive SDK result fields ─────────────────────────
    # These are captured from the orchestrator stream's `result` records
    # so TURN_COMPLETE can include them without re-parsing the stream.
    cache_read_tokens: int = 0
    cache_create_tokens: int = 0
    cache_5m_tokens: int = 0
    cache_1h_tokens: int = 0
    num_turns: int = 0
    duration_api_ms: int = 0
    stop_reason: str = ''
    is_error: bool = False
    api_error_status: str = ''
    model: str = ''
    # The Claude SDK uuid from `system/init`. Distinct from the
    # teaparty-side session_id (which is the dispatch hex / job id);
    # this is what the analysis script uses to cross-link to claude-home
    # JSONL files.
    claude_session_uuid: str = ''
    # Per-tool-use counts. Populated by the streamer as tool_use blocks
    # arrive; emitted into TURN_COMPLETE.tools_called.
    tools_called: dict[str, int] = field(default_factory=dict)
    # Concatenated text-block content from assistant events. Used only
    # for response_text_len in TURN_COMPLETE; the full text is not
    # stored in telemetry.
    response_text: str = ''

    @property
    def had_errors(self) -> bool:
        return bool(self.stderr_lines)

    @property
    def api_overloaded(self) -> bool:
        """True when stderr indicates the Anthropic API returned 529 (overloaded).

        Checks for multiple indicators to be resilient against CLI wording changes:
        - 'overloaded_error' (API error type in JSON responses)
        - '529' (HTTP status code)
        """
        return _stderr_indicates_overload(self.stderr_lines)


class LLMRunner(Protocol):
    """Minimal interface for any LLM backend."""

    async def run(self) -> ClaudeResult: ...



class ClaudeRunner:
    """Manages a single Claude CLI invocation."""

    # ── Heartbeat / watchdog parameters (issue #149) ──────────────────────
    BEAT_INTERVAL = 30        # seconds between heartbeat touches
    STALE_THRESHOLD = 120     # seconds before a heartbeat is considered stale
    KILL_THRESHOLD = 300      # seconds before killing stale children

    def __init__(
        self,
        prompt: str,
        *,
        cwd: str,
        stream_file: str,
        agents_file: str | None = None,
        agents_json: str | None = None,
        lead: str | None = None,
        settings: dict[str, Any] | None = None,
        permission_mode: str = 'default',
        resume_session: str | None = None,
        env_vars: dict[str, str] | None = None,
        event_bus: EventBus | None = None,
        stall_timeout: int = 1800,
        session_id: str = '',
        heartbeat_file: str = '',
        parent_heartbeat: str = '',
        children_file: str = '',
        tools: str | None = None,
        on_stream_event: Callable[[dict], None] | None = None,
        on_pid: Callable[[int, float], None] | None = None,
        settings_path: str = '',
        mcp_config_path: str = '',
        strict_mcp_config: bool = False,
    ):
        self.prompt = prompt
        self.cwd = cwd
        self.stream_file = stream_file
        self.agents_file = agents_file
        self.agents_json = agents_json
        self.tools = tools
        self.on_stream_event = on_stream_event
        # Cut 19: invoked once after create_subprocess_exec returns,
        # with the spawn PID and OS-reported create_time.  The launcher
        # uses this to stamp the bus's DISPATCH conversation row so
        # recovery can later check OS liveness against (pid, started).
        self.on_pid = on_pid
        self.settings_path = settings_path
        self.mcp_config_path = mcp_config_path
        self.strict_mcp_config = strict_mcp_config
        self.lead = lead
        self.settings = settings or {}
        self.permission_mode = permission_mode
        self.resume_session = resume_session
        self.env_vars = env_vars or {}
        self.event_bus = event_bus
        self.stall_timeout = stall_timeout
        self.session_id = session_id
        self.heartbeat_file = heartbeat_file
        self.parent_heartbeat = parent_heartbeat
        self.children_file = children_file
        self._process: asyncio.subprocess.Process | None = None
        self._extracted_session_id: str = ''
        self._accumulated_cost: float = 0.0
        self._accumulated_model_costs: dict[str, float] = {}
        self._accumulated_input_tokens: int = 0
        self._accumulated_output_tokens: int = 0
        self._last_duration_ms: int = 0
        self._sm = RunnerSM()
        self._context_budget = ContextBudget()
        # ── Issue #431 — additive fields for self-sufficient telemetry ─
        self._accumulated_cache_read_tokens: int = 0
        self._accumulated_cache_create_tokens: int = 0
        self._accumulated_cache_5m_tokens: int = 0
        self._accumulated_cache_1h_tokens: int = 0
        self._accumulated_num_turns: int = 0
        self._last_duration_api_ms: int = 0
        self._last_stop_reason: str = ''
        self._is_error: bool = False
        self._api_error_status: str = ''
        self._extracted_model: str = ''
        # tool_use_id → (start_ts, tool_name, mcp_server, input_size)
        # Pending entries get paired with tool_result on close to emit
        # TOOL_CALL_COMPLETE.
        self._open_tool_uses: dict[str, dict[str, Any]] = {}
        # Tool-name count rollup for TURN_COMPLETE.tools_called.
        self._tools_called: dict[str, int] = {}
        self._response_text_chunks: list[str] = []

    async def run(self) -> ClaudeResult:
        """Run the Claude CLI and stream output. Returns result.

        All config (tools, permissions, settings, MCP) is derived by the
        launcher and passed to ClaudeRunner via constructor parameters.
        ClaudeRunner is the execution engine — it uses what it's given.
        """
        # MCP config comes from the worktree's .mcp.json, written by
        # compose_launch_worktree with the correct scope. Claude Code
        # reads it from cwd automatically. No --mcp-config flag needed.

        # Settings: chat tier passes a persistent path (no tempfile).
        # Job tier still writes a tempfile from the settings dict.
        settings_file = None
        effective_settings_path = self.settings_path or None
        if not effective_settings_path:
            settings = dict(self.settings) if self.settings else {}
            if settings:
                settings_file = tempfile.NamedTemporaryFile(
                    mode='w', suffix='.json', delete=False,
                )
                json.dump(settings, settings_file)
                settings_file.close()
                effective_settings_path = settings_file.name

        try:
            args = self._build_args(effective_settings_path)
            env = self._build_env()
            start_time = time.time()

            self._lifecycle('launch')
            self._process = await asyncio.create_subprocess_exec(
                *args,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self.cwd,
                env=env,
                limit=4 * 1024 * 1024,  # 4MB — stream-json lines with large Edit tool calls exceed the 64KB default
                # Put the Claude CLI in its own process group / session.
                # Without this the subprocess inherits OUR process group.
                # Every _kill_process_tree call below does
                # ``killpg(getpgid(pid), SIGTERM)`` — and if the target
                # shares our pgid, SIGTERM fans out to the bridge server
                # too.  Result: the bridge catches SIGTERM, closes its
                # HTTP listener, hangs in cleanup, and the user sees
                # "localhost refused to connect" mid-dispatch.  Isolating
                # the subprocess into its own session makes killpg on it
                # structurally unable to reach us.  (Same fix withdraw.py
                # uses; see also issue #159.)
                start_new_session=True,
            )

            # Cut 19: hand the spawn PID + OS create_time to the
            # launcher so it can stamp the bus's DISPATCH row.
            # Recovery later checks (pid, started) against the OS to
            # decide if this child's process is still the one we
            # launched — the bus is the single source of truth.
            if self.on_pid is not None:
                try:
                    started = _process_create_time(self._process.pid)
                    self.on_pid(self._process.pid, started)
                except Exception:
                    _log.debug('on_pid callback raised', exc_info=True)

            # Feed prompt via stdin
            if self._process.stdin:
                self._process.stdin.write(self.prompt.encode())
                self._process.stdin.close()

            # Stream output with stall watchdog
            stall_killed = False
            stderr_lines: list[str] = []
            try:
                exit_code = await self._stream_with_watchdog(stderr_lines)
            except _StallTimeout:
                stall_killed = True
                exit_code = -1
                self._lifecycle('kill')

            if not stall_killed:
                if exit_code == 0:
                    self._lifecycle('finish')
                else:
                    self._lifecycle('error')

            return ClaudeResult(
                exit_code=exit_code,
                session_id=self._extracted_session_id,
                stream_file=self.stream_file,
                stall_killed=stall_killed,
                start_time=start_time,
                cost_usd=self._accumulated_cost,
                cost_per_model=dict(self._accumulated_model_costs),
                input_tokens=self._accumulated_input_tokens,
                output_tokens=self._accumulated_output_tokens,
                duration_ms=self._last_duration_ms,
                stderr_lines=stderr_lines,
                context_budget=self._context_budget,
                # Issue #431 additive fields.
                cache_read_tokens=self._accumulated_cache_read_tokens,
                cache_create_tokens=self._accumulated_cache_create_tokens,
                cache_5m_tokens=self._accumulated_cache_5m_tokens,
                cache_1h_tokens=self._accumulated_cache_1h_tokens,
                num_turns=self._accumulated_num_turns,
                duration_api_ms=self._last_duration_api_ms,
                stop_reason=self._last_stop_reason,
                is_error=self._is_error,
                api_error_status=self._api_error_status,
                model=self._extracted_model,
                claude_session_uuid=self._extracted_session_id,
                tools_called=dict(self._tools_called),
                response_text=''.join(self._response_text_chunks),
            )
        finally:
            # Kill subprocess on cancellation or exception (issue #159).
            # Without this, task cancellation (e.g. withdraw) leaves
            # orphaned Claude CLI processes running.
            self._kill_subprocess()

            if settings_file:
                try:
                    os.unlink(settings_file.name)
                except OSError:
                    pass

    def _build_args(self, settings_path: str | None) -> list[str]:
        args = [
            'claude', '-p',
            '--output-format', 'stream-json',
            '--verbose',
        ]
        args.extend(['--setting-sources', 'user'])
        args.extend(['--permission-mode', self.permission_mode])
        if self.tools is not None:
            args.extend(['--tools', self.tools])
        if self.agents_json:
            args.extend(['--agents', self.agents_json])
        elif self.agents_file:
            # Legacy path: read agents from a JSON file
            try:
                with open(self.agents_file) as f:
                    args.extend(['--agents', f.read()])
            except OSError:
                pass
        if self.lead:
            args.extend(['--agent', self.lead])
        if settings_path:
            args.extend(['--settings', settings_path])
        if self.resume_session:
            args.extend(['--resume', self.resume_session])
        # --setting-sources user prevents Claude Code from reading
        # project-level .mcp.json.  Pass it explicitly via --mcp-config.
        # Chat tier passes an explicit per-session path that lives
        # outside the cwd; job tier falls back to the worktree-composed
        # .mcp.json under cwd.
        mcp_path = self.mcp_config_path
        if not mcp_path:
            candidate = os.path.join(self.cwd, '.mcp.json')
            if os.path.isfile(candidate):
                mcp_path = candidate
        if mcp_path and os.path.isfile(mcp_path):
            args.extend(['--mcp-config', mcp_path])
            if self.strict_mcp_config:
                args.append('--strict-mcp-config')
        return args

    # Env vars the Claude CLI needs to function.  Everything else is
    # stripped so agent subprocesses don't inherit credentials, tokens,
    # or other sensitive state from the orchestrator's environment.
    _ENV_ALLOWLIST = frozenset({
        # Core POSIX / macOS
        'PATH', 'HOME', 'TMPDIR', 'SHELL', 'USER', 'LOGNAME',
        'LANG', 'TERM',
        # Locale (LC_* wildcard handled below)
        # Credentials the CLI itself needs
        'ANTHROPIC_API_KEY',
        # Python / uv
        'VIRTUAL_ENV', 'PYENV_ROOT',
        # Claude Code config redirect — set by teaparty.sh to a
        # teaparty-managed dir so subprocess agents see only the
        # commands/skills we stage and not the user's personal ones
        # under ~/.claude. Auth lives at the same redirected path
        # (created via `claude /login` against the same CLAUDE_CONFIG_DIR).
        'CLAUDE_CONFIG_DIR',
    })

    # Prefixes that are always passed through (e.g. CLAUDE_*, POC_*, LC_*).
    _ENV_PREFIX_ALLOWLIST = ('CLAUDE_', 'POC_', 'LC_')

    def _build_env(self) -> dict[str, str]:
        env: dict[str, str] = {}
        for key, value in os.environ.items():
            if key in self._ENV_ALLOWLIST:
                env[key] = value
            elif key.startswith(self._ENV_PREFIX_ALLOWLIST):
                env[key] = value
        env['CLAUDE_CODE_MAX_OUTPUT_TOKENS'] = '128000'
        # Do NOT set CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS — it enables
        # SendMessage which bypasses TeaParty's bus listener.
        env.pop('CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS', None)
        env.update(self.env_vars)
        return env

    def _should_kill_for_stall(
        self,
        *,
        now: float,
        last_output_time: float,
        last_lead_event_time: float,
        last_child_event_time: float,
        open_tool_calls: dict[str, float],
        children_file: str = '',
        running_agent_count: int = 0,
    ) -> bool:
        """Return True iff the lead should be killed for a stall.

        Returns False (alive) if any of:
          0. Caller's session is in an in-flight AskQuestion wait
             (#426 — the wait can legitimately span hours or days; the
             watchdog must not interfere)
          1. An open tool call is still active (started within
             ``STALE_THRESHOLD``)
          2. Lead emitted output recently
          3. A child emitted stream events recently
          4. Any child heartbeat is fresh on disk
        Returns True only when every alive-signal fails AND
        ``last_output_time`` is older than the effective stall timeout.
        """
        # #426: in-flight escalation pauses the kill timer.
        if self.session_id:
            from teaparty.mcp.registry import session_has_active_escalation
            if session_has_active_escalation(self.session_id):
                return False

        if any(
            (now - ts) < self.STALE_THRESHOLD
            for ts in open_tool_calls.values()
        ):
            return False

        if (now - last_lead_event_time) < self.STALE_THRESHOLD:
            return False

        if (
            last_child_event_time > 0
            and (now - last_child_event_time) < self.STALE_THRESHOLD
        ):
            return False

        if children_file and os.path.exists(children_file):
            from teaparty.bridge.state.heartbeat import (
                is_heartbeat_stale, read_children,
            )
            children = read_children(children_file)
            any_child_alive = any(
                os.path.exists(c.get('heartbeat', ''))
                and not is_heartbeat_stale(
                    c['heartbeat'], self.STALE_THRESHOLD,
                )
                for c in children
            )
            if any_child_alive:
                return False

        age = now - last_output_time
        effective_timeout = self.stall_timeout
        if running_agent_count > 0:
            effective_timeout = max(self.stall_timeout, 7200)
        return age >= effective_timeout

    async def _stream_with_watchdog(self, stderr_lines: list[str]) -> int:
        """Stream stdout while monitoring for stalls.  Captures stderr.

        Concurrent tasks (issue #149):
          - read_stdout: parse stream events, track tool calls and agents
          - read_stderr: capture CLI errors, detect 529 overload
          - heartbeat_writer: touch heartbeat file every BEAT_INTERVAL seconds
          - watchdog: priority cascade for stall detection
          - parent_watcher: detect dead parent, initiate graceful shutdown
        """
        proc = self._process
        assert proc and proc.stdout

        last_output_time = time.time()
        last_lead_event_time = time.time()
        last_child_event_time = 0.0
        running_agent_count = 0
        # Track open tool calls: tool_use_id → start_timestamp (issue #149)
        open_tool_calls: dict[str, float] = {}
        shutdown_flag = False

        async def read_stdout():
            nonlocal last_output_time, last_lead_event_time, last_child_event_time
            nonlocal running_agent_count
            first_output = True
            with open(self.stream_file, 'a') as f:
                async for line in proc.stdout:
                    line_str = line.decode().rstrip()
                    if not line_str:
                        continue
                    now = time.time()
                    last_output_time = now
                    if first_output:
                        first_output = False
                        self._lifecycle('stream')

                    f.write(line_str + '\n')
                    f.flush()

                    try:
                        event_data = json.loads(line_str)
                        if self.on_stream_event is not None:
                            try:
                                self.on_stream_event(event_data)
                            except Exception:
                                pass
                        self._maybe_extract_session_id(event_data)
                        self._maybe_extract_cost(event_data)

                        # Classify event as lead vs child based on task_id
                        task_id = event_data.get('task_id')
                        if task_id:
                            last_child_event_time = now
                        else:
                            last_lead_event_time = now

                        # Track tool call lifecycle for watchdog cascade
                        # AND emit Issue #431 TOOL_CALL_COMPLETE / capture
                        # tools_called / response_text from the same scan.
                        etype = event_data.get('type', '')
                        if etype == 'tool_use':
                            tool_id = event_data.get('tool_use_id', '')
                            if tool_id:
                                open_tool_calls[tool_id] = now
                        elif etype == 'tool_result':
                            tool_id = event_data.get('tool_use_id', '')
                            open_tool_calls.pop(tool_id, None)
                        # Inspect message content blocks for tool_use /
                        # tool_result / text and per-message usage.
                        # (Some streams put tool_use at top-level via
                        # the etype branch above; the canonical shape
                        # is inside assistant.message.content blocks.)
                        self._process_stream_event(event_data, now)

                        # Track background agent lifecycle
                        subtype = event_data.get('subtype', '')
                        if subtype == 'task_started':
                            running_agent_count += 1
                        elif subtype == 'task_notification':
                            running_agent_count = max(0, running_agent_count - 1)

                        # Context budget: track token usage from result events (Issue #260)
                        self._context_budget.update(event_data)

                        if self.event_bus:
                            await self.event_bus.publish(Event(
                                type=EventType.STREAM_DATA,
                                data=event_data,
                                session_id=self.session_id,
                            ))
                    except json.JSONDecodeError:
                        pass

        async def read_stderr():
            nonlocal last_output_time
            assert proc.stderr
            async for line in proc.stderr:
                line_str = line.decode().rstrip()
                if not line_str:
                    continue
                stderr_lines.append(line_str)

                if _line_indicates_overload(line_str):
                    last_output_time = time.time()

                if self.event_bus:
                    await self.event_bus.publish(Event(
                        type=EventType.STREAM_ERROR,
                        data={'line': line_str},
                        session_id=self.session_id,
                    ))

        async def heartbeat_writer():
            """Touch heartbeat file every BEAT_INTERVAL seconds (issue #149).

            Activates with subprocess PID once launched, then steady-state
            os.utime() beats.  Stops when the subprocess exits — touching a
            dead process's heartbeat would falsely signal liveness.
            """
            if not self.heartbeat_file:
                return

            from teaparty.bridge.state.heartbeat import activate_heartbeat, touch_heartbeat

            # Activate heartbeat with the subprocess PID
            try:
                activate_heartbeat(self.heartbeat_file, proc.pid)
            except OSError:
                return  # Can't activate — heartbeat contract broken

            while proc.returncode is None:
                await asyncio.sleep(self.BEAT_INTERVAL)
                if proc.returncode is not None:
                    break
                try:
                    touch_heartbeat(self.heartbeat_file)
                except OSError:
                    pass  # Transient disk error — tolerate

        async def watchdog():
            """Priority cascade stall detection (issues #149, #426).

            Alive-signals (any pass → not stalled):
              0. Caller is in an in-flight AskQuestion wait (#426)
              1. Mid-tool-call (non-stale open tool_use)
              2. Recent lead events (within STALE_THRESHOLD)
              3. Recent child stream events (within STALE_THRESHOLD)
              4. Children heartbeats fresh on disk (via .children)
            When all fail: kill stale children, then declare stall if
            ``last_output_time`` is older than the effective timeout.
            """
            while proc.returncode is None:
                await asyncio.sleep(self.BEAT_INTERVAL)
                if proc.returncode is not None:
                    break

                now = time.time()

                if not self._should_kill_for_stall(
                    now=now,
                    last_output_time=last_output_time,
                    last_lead_event_time=last_lead_event_time,
                    last_child_event_time=last_child_event_time,
                    open_tool_calls=open_tool_calls,
                    children_file=self.children_file,
                    running_agent_count=running_agent_count,
                ):
                    continue

                # Stall detected — kill stale children before declaring
                # the lead stalled.
                if self.children_file and os.path.exists(self.children_file):
                    from teaparty.bridge.state.heartbeat import read_children, read_heartbeat
                    for child in read_children(self.children_file):
                        hb = child.get('heartbeat', '')
                        if not hb or not os.path.exists(hb):
                            continue
                        data = read_heartbeat(hb)
                        if data.get('status') in ('completed', 'withdrawn'):
                            continue
                        hb_age = now - os.path.getmtime(hb)
                        if hb_age > self.KILL_THRESHOLD:
                            pid = data.get('pid', 0)
                            if pid:
                                try:
                                    os.kill(pid, signal.SIGTERM)
                                except (ProcessLookupError, PermissionError):
                                    pass
                                if self.event_bus:
                                    await self.event_bus.publish(Event(
                                        type=EventType.LOG,
                                        data={
                                            'category': 'watchdog_kill_child',
                                            'heartbeat': hb,
                                            'pid': pid,
                                            'stale_seconds': int(hb_age),
                                        },
                                        session_id=self.session_id,
                                    ))

                age = now - last_output_time
                effective_timeout = self.stall_timeout
                if running_agent_count > 0:
                    effective_timeout = max(self.stall_timeout, 7200)
                if self.event_bus:
                    await self.event_bus.publish(Event(
                        type=EventType.LOG,
                        data={
                            'category': 'watchdog_stall',
                            'age_seconds': int(age),
                            'effective_timeout': effective_timeout,
                        },
                        session_id=self.session_id,
                    ))
                self._lifecycle('stall')
                _kill_process_tree(proc.pid)
                raise _StallTimeout()

        async def parent_watcher():
            """Detect dead parent and initiate graceful shutdown (issue #149).

            Checks parent's heartbeat every BEAT_INTERVAL seconds.  If stale
            and PID dead, sets shutdown flag and waits for subprocess exit
            (up to 60s grace period), then commits partial work.
            """
            nonlocal shutdown_flag
            if not self.parent_heartbeat or not os.path.exists(self.parent_heartbeat):
                return

            from teaparty.bridge.state.heartbeat import is_heartbeat_stale

            while proc.returncode is None:
                await asyncio.sleep(self.BEAT_INTERVAL)
                if proc.returncode is not None:
                    break

                if not os.path.exists(self.parent_heartbeat):
                    continue

                # Two signals: heartbeat stale, or parent PID changed to 1 (launchd/init)
                parent_dead = is_heartbeat_stale(self.parent_heartbeat, self.STALE_THRESHOLD)
                if not parent_dead and os.getppid() == 1:
                    parent_dead = True  # macOS/Linux: reparented to init
                if parent_dead:
                    shutdown_flag = True

                    # Grace period: wait for subprocess to exit naturally
                    try:
                        await asyncio.wait_for(proc.wait(), timeout=60)
                    except asyncio.TimeoutError:
                        _kill_process_tree(proc.pid)

                    # Commit partial work to the worktree
                    await self._commit_partial_work()

                    # Finalize own heartbeat
                    if self.heartbeat_file:
                        from teaparty.bridge.state.heartbeat import finalize_heartbeat
                        try:
                            finalize_heartbeat(self.heartbeat_file, 'withdrawn')
                        except OSError:
                            pass
                    return

        # Run readers, heartbeat writer, watchdog, and parent watcher concurrently
        stdout_task = asyncio.create_task(read_stdout())
        stderr_task = asyncio.create_task(read_stderr())
        heartbeat_task = asyncio.create_task(heartbeat_writer())
        watchdog_task = asyncio.create_task(watchdog())
        parent_task = asyncio.create_task(parent_watcher())

        try:
            await asyncio.gather(stdout_task, stderr_task)
            exit_code = await proc.wait()
        finally:
            for task in (watchdog_task, heartbeat_task, parent_task):
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, _StallTimeout):
                    pass

        return exit_code

    async def _commit_partial_work(self) -> None:
        """Commit partial work to the worktree on parent death (issue #149).

        Best-effort: if the worktree is in a dirty merge state, the commit
        fails and we exit without committing.
        """
        try:
            add_proc = await asyncio.create_subprocess_exec(
                'git', 'add', '-A',
                cwd=self.cwd,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await add_proc.wait()
            # Unstage .claude/ — composed artifact, must not merge back
            reset_proc = await asyncio.create_subprocess_exec(
                'git', 'reset', 'HEAD', '--', '.claude/',
                cwd=self.cwd,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await reset_proc.wait()
            commit_proc = await asyncio.create_subprocess_exec(
                'git', 'commit', '-m', 'Partial work saved on parent death (issue #149)',
                '--allow-empty-message',
                cwd=self.cwd,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await commit_proc.wait()
        except Exception:
            pass

    def _kill_subprocess(self) -> None:
        """Kill the child subprocess and its process tree if still running."""
        if self._process and self._process.returncode is None:
            _kill_process_tree(self._process.pid)

    def _lifecycle(self, event_name: str) -> None:
        """Send a lifecycle event to the RunnerSM.

        Logs a warning (rather than crashing) if the transition is invalid,
        since async races in subprocess management can cause out-of-order
        lifecycle events.  Once the lifecycle is proven clean in production,
        this guard can be tightened to raise.
        """
        from statemachine.exceptions import TransitionNotAllowed
        try:
            self._sm.send(event_name)
        except TransitionNotAllowed:
            import logging
            logging.getLogger('claude_runner').warning(
                'RunnerSM: invalid lifecycle transition %r from %s',
                event_name, self._sm.current_state_value,
            )

    def _maybe_extract_session_id(self, event: dict) -> None:
        if event.get('type') == 'system' and event.get('subtype') == 'init':
            if not self._extracted_session_id:
                self._extracted_session_id = event.get('session_id', '')
            # Capture the per-call model. A single launch can record
            # turns under different models (compaction can split runs);
            # we report the most recently seen one.
            model = event.get('model')
            if model:
                self._extracted_model = model

    def _maybe_extract_cost(self, event: dict) -> None:
        """Accumulate cost / token / SDK-result stats from result records.

        Originally added in Issues #262 / #341 for cost_usd and
        in/out tokens; extended in Issue #431 to capture the additive
        fields the analysis script needs (5m/1h cache split, num_turns,
        duration_api_ms, stop_reason, is_error, api_error_status).
        """
        if event.get('type') != 'result':
            return
        cost = event.get('total_cost_usd', 0.0)
        if cost:
            self._accumulated_cost += cost
        per_model = event.get('cost_usd', {})
        if isinstance(per_model, dict):
            for model, model_cost in per_model.items():
                self._accumulated_model_costs[model] = (
                    self._accumulated_model_costs.get(model, 0.0) + model_cost
                )
        usage = event.get('usage') or {}
        # Older streams report tokens at the top level; newer streams
        # nest them under usage. Take whichever is present.
        input_tokens = (
            usage.get('input_tokens')
            if usage.get('input_tokens') is not None
            else event.get('input_tokens', 0)
        )
        if input_tokens:
            self._accumulated_input_tokens += int(input_tokens)
        output_tokens = (
            usage.get('output_tokens')
            if usage.get('output_tokens') is not None
            else event.get('output_tokens', 0)
        )
        if output_tokens:
            self._accumulated_output_tokens += int(output_tokens)
        duration_ms = event.get('duration_ms', 0)
        if duration_ms:
            self._last_duration_ms = duration_ms

        # Issue #431: additive fields from the SDK result.
        cr = usage.get('cache_read_input_tokens', 0)
        if cr:
            self._accumulated_cache_read_tokens += int(cr)
        cc = usage.get('cache_creation') or {}
        c5 = cc.get('ephemeral_5m_input_tokens', 0) or 0
        c1 = cc.get('ephemeral_1h_input_tokens', 0) or 0
        if c5:
            self._accumulated_cache_5m_tokens += int(c5)
        if c1:
            self._accumulated_cache_1h_tokens += int(c1)
        # The current cache_create rollup keeps the existing
        # TURN_COMPLETE field meaning intact (sum of 5m + 1h).
        self._accumulated_cache_create_tokens += int(c5) + int(c1)

        n_turns = event.get('num_turns', 0)
        if n_turns:
            self._accumulated_num_turns += int(n_turns)
        api_ms = event.get('duration_api_ms', 0)
        if api_ms:
            self._last_duration_api_ms = int(api_ms)
        stop_reason = event.get('stop_reason') or usage.get('stop_reason')
        if stop_reason:
            self._last_stop_reason = stop_reason
        if event.get('is_error'):
            self._is_error = True
        api_err = event.get('api_error_status')
        if api_err:
            self._api_error_status = api_err

    def _process_stream_event(self, event: dict, now: float) -> None:
        """Emit Issue #431 telemetry from a single stream event.

        - assistant events trigger record_message (dedupe-keyed on
          (session_id, message_id)) and accumulate response text.
        - tool_use blocks open a pending tool call.
        - tool_result blocks (in user events) close the pending tool
          call and emit TOOL_CALL_COMPLETE.

        The session_id used for telemetry is the teaparty-side id
        (``self.session_id``), not the SDK uuid — that keeps cost
        rollups consistent with the dispatch tree.
        """
        from teaparty.telemetry import (
            record_event as _rec, record_message as _rec_msg,
        )
        from teaparty.telemetry.events import TOOL_CALL_COMPLETE
        etype = event.get('type', '')
        if etype == 'assistant':
            msg = event.get('message') or {}
            mid = msg.get('id')
            if mid:
                usage = msg.get('usage') or {}
                cc = usage.get('cache_creation') or {}
                _rec_msg(
                    session_id=self.session_id,
                    message_id=mid,
                    ts=event.get('timestamp') or now,
                    model=msg.get('model'),
                    input_tokens=usage.get('input_tokens'),
                    output_tokens=usage.get('output_tokens'),
                    cache_read_tokens=usage.get('cache_read_input_tokens'),
                    cache_5m_tokens=cc.get('ephemeral_5m_input_tokens'),
                    cache_1h_tokens=cc.get('ephemeral_1h_input_tokens'),
                    stop_reason=msg.get('stop_reason'),
                )
            for block in (msg.get('content') or []):
                if not isinstance(block, dict):
                    continue
                btype = block.get('type')
                if btype == 'text':
                    self._response_text_chunks.append(
                        block.get('text', '') or '',
                    )
                elif btype == 'tool_use':
                    use_id = block.get('id') or ''
                    name = block.get('name') or ''
                    if use_id and name:
                        # Built-ins have no MCP server prefix; mcp tools
                        # are named ``mcp__<server>__<tool>``.
                        mcp_server = None
                        if name.startswith('mcp__'):
                            parts = name.split('__', 2)
                            if len(parts) >= 2:
                                mcp_server = parts[1]
                        input_blob = block.get('input') or {}
                        try:
                            input_size = len(json.dumps(input_blob))
                        except (TypeError, ValueError):
                            input_size = 0
                        self._open_tool_uses[use_id] = {
                            'tool_name': name,
                            'mcp_server': mcp_server,
                            'start_ts': now,
                            'input_size': input_size,
                        }
                        self._tools_called[name] = (
                            self._tools_called.get(name, 0) + 1
                        )
        elif etype == 'user':
            msg = event.get('message') or {}
            for block in (msg.get('content') or []):
                if not isinstance(block, dict):
                    continue
                if block.get('type') != 'tool_result':
                    continue
                use_id = block.get('tool_use_id') or ''
                pending = self._open_tool_uses.pop(use_id, None)
                if pending is None:
                    continue
                content = block.get('content')
                if isinstance(content, str):
                    output_size = len(content)
                else:
                    try:
                        output_size = len(json.dumps(content))
                    except (TypeError, ValueError):
                        output_size = 0
                end_ts = now
                start_ts = pending['start_ts']
                duration_ms = int((end_ts - start_ts) * 1000)
                # Resolve child_session_id from Send / Delegate /
                # AskQuestion result text. The result format is
                # ``{"conversation_id": "dispatch:<hex>"}`` or similar.
                child_sid = None
                if isinstance(content, str):
                    try:
                        parsed = json.loads(content)
                        if isinstance(parsed, dict):
                            cid = (
                                parsed.get('conversation_id')
                                or parsed.get('child_session_id')
                            )
                            if isinstance(cid, str) and ':' in cid:
                                child_sid = cid.partition(':')[2]
                            elif isinstance(cid, str):
                                child_sid = cid
                    except (ValueError, TypeError):
                        pass
                _rec(
                    TOOL_CALL_COMPLETE, scope='management',
                    session_id=self.session_id,
                    ts=end_ts,
                    data={
                        'tool_use_id': use_id,
                        'tool_name': pending['tool_name'],
                        'mcp_server': pending['mcp_server'],
                        'start_ts': start_ts,
                        'end_ts': end_ts,
                        'duration_ms': duration_ms,
                        'is_error': bool(block.get('is_error')),
                        'input_size': pending['input_size'],
                        'output_size': output_size,
                        'parent_session_id': self.session_id,
                        'child_session_id': child_sid,
                    },
                    parent_session_id=self.session_id,
                )


# ── 529 overload detection ───────────────────────────────────────────────────

# Patterns that indicate the Anthropic API returned HTTP 529 (overloaded).
# Checked against each stderr line.  Multiple indicators make detection
# resilient to CLI wording changes.
_OVERLOAD_PATTERNS = ('overloaded_error', '529')


def _stderr_indicates_overload(stderr_lines: list[str]) -> bool:
    """Return True if any stderr line contains a 529/overload indicator."""
    for line in stderr_lines:
        for pattern in _OVERLOAD_PATTERNS:
            if pattern in line:
                return True
    return False


def _line_indicates_overload(line: str) -> bool:
    """Return True if a single stderr line contains a 529/overload indicator."""
    for pattern in _OVERLOAD_PATTERNS:
        if pattern in line:
            return True
    return False


class _StallTimeout(Exception):
    pass


def _kill_process_tree(pid: int) -> None:
    """Kill a process and all its children.

    Guards against self-kill.  When we spawn the Claude CLI with
    ``start_new_session=True`` it has its own pgid, so ``killpg`` on
    the target is isolated to that tree.  But in any code path where a
    subprocess ended up in our process group (legacy callers, tests,
    or a regression that drops ``start_new_session``), ``killpg`` would
    SIGTERM the bridge too and the HTTP listener would quietly close.
    This guard makes that class of bug impossible: if the target
    shares our pgid, we signal only the single PID.  Mirrors the
    guard in ``teaparty/workspace/withdraw.py`` (issue #159).
    """
    if pid == os.getpid():
        return
    try:
        target_pgid = os.getpgid(pid)
    except (ProcessLookupError, PermissionError, OSError):
        try:
            os.kill(pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            pass
        return
    if target_pgid == os.getpgid(os.getpid()):
        # Shared process group — signaling the group would kill us.
        try:
            os.kill(pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            pass
        return
    try:
        os.killpg(target_pgid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError, OSError):
        try:
            os.kill(pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            pass
