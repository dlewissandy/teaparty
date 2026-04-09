"""Async wrapper around the Claude CLI subprocess.

All agent turns are invoked via `claude -p --output-format stream-json`.
Stream output is tailed line-by-line, persisted to the JSONL file, and
published as STREAM_DATA events.
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import signal
import tempfile
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol

from teaparty.util.context_budget import ContextBudget
from teaparty.messaging.bus import Event, EventBus, EventType
from teaparty.runners.machine import RunnerSM


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


def create_runner(
    prompt: str,
    *,
    cwd: str,
    stream_file: str,
    backend: str = 'claude',
    **kwargs: Any,
) -> LLMRunner:
    """Create an LLM runner for the given backend.

    Backends:
      'claude' — ClaudeRunner (default, production)
      'ollama' — OllamaRunner (cheap local model)
      'deterministic' — DeterministicRunner (scripted responses for tests)
    """
    if backend == 'claude':
        return ClaudeRunner(prompt, cwd=cwd, stream_file=stream_file, **kwargs)
    elif backend == 'ollama':
        from teaparty.runners.ollama import OllamaRunner
        return OllamaRunner(prompt, cwd=cwd, stream_file=stream_file, **kwargs)
    elif backend == 'deterministic':
        from teaparty.runners.deterministic import DeterministicRunner
        return DeterministicRunner(prompt, cwd=cwd, stream_file=stream_file, **kwargs)
    else:
        raise ValueError(f"Unknown LLM backend: {backend!r}")


def populate_scoped_claude_dir(
    target_dir: str,
    agent_name: str,
    source_claude_dir: str,
    *,
    agent_source_override: str = '',
) -> None:
    """Populate a ``.claude/`` directory scoped to an agent's skill allowlist.

    Replaces *target_dir* with a fresh directory containing only:

    - ``agents/{agent_name}.md`` — the lead agent's definition
    - ``skills/{name}/`` — symlinks to only the skills named in the agent's
      ``skills:`` frontmatter (omitted entirely when the allowlist is empty)
    - ``CLAUDE.md`` — project instructions (if present in source)

    Thread-safe: each call operates on its own *target_dir* path, and only
    reads from *source_claude_dir* (no shared mutable state).

    Args:
        target_dir: Path to the ``.claude/`` directory to create/replace
            (e.g. ``{worktree}/.claude/``).
        agent_name: Agent name matching ``source_claude_dir/agents/{name}.md``.
        source_claude_dir: Path to the canonical ``.claude/`` directory
            containing the full set of agents and skills.
        agent_source_override: If set, use this path as the agent definition
            instead of ``source_claude_dir/agents/{name}.md``.  Allows
            reading from ``.teaparty/`` while placing the result as a
            ``.claude/agents/{name}.md`` file for Claude Code resolution.
    """
    from teaparty.config.config_reader import read_agent_frontmatter

    # Start fresh so stale content from a previous invocation is gone.
    if os.path.exists(target_dir):
        shutil.rmtree(target_dir)
    os.makedirs(target_dir)

    # ── Agent definition (for --agent resolution) ────────────────────────
    agent_src = agent_source_override or os.path.join(
        source_claude_dir, 'agents', f'{agent_name}.md',
    )
    allowed_skills: list[str] = []
    if os.path.isfile(agent_src):
        agents_dir = os.path.join(target_dir, 'agents')
        os.makedirs(agents_dir)
        # Copy (not symlink) when using an override source so Claude Code
        # finds a regular .md file at the expected path regardless of origin.
        dest = os.path.join(agents_dir, f'{agent_name}.md')
        if agent_source_override:
            shutil.copy2(agent_src, dest)
        else:
            os.symlink(os.path.abspath(agent_src), dest)
        fm = read_agent_frontmatter(agent_src)
        allowed_skills = fm.get('skills') or []

    # ── Skills — only those in the agent's allowlist ─────────────────────
    source_skills = os.path.join(source_claude_dir, 'skills')
    if allowed_skills and os.path.isdir(source_skills):
        skills_dir = os.path.join(target_dir, 'skills')
        os.makedirs(skills_dir)
        for skill_name in allowed_skills:
            skill_src = os.path.join(source_skills, skill_name)
            if os.path.isdir(skill_src):
                os.symlink(os.path.abspath(skill_src),
                           os.path.join(skills_dir, skill_name))

    # ── Project instructions apply to all agents ─────────────────────────
    claude_md = os.path.join(source_claude_dir, 'CLAUDE.md')
    if os.path.isfile(claude_md):
        os.symlink(os.path.abspath(claude_md),
                   os.path.join(target_dir, 'CLAUDE.md'))


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
        add_dirs: list[str] | None = None,
        resume_session: str | None = None,
        env_vars: dict[str, str] | None = None,
        event_bus: EventBus | None = None,
        stall_timeout: int = 1800,
        session_id: str = '',
        heartbeat_file: str = '',
        parent_heartbeat: str = '',
        children_file: str = '',
        tools: str | None = None,
        mcp_config: dict[str, Any] | None = None,  # Ignored — kept for CfA engine compat
        on_stream_event: Callable[[dict], None] | None = None,
    ):
        self.prompt = prompt
        self.cwd = cwd
        self.stream_file = stream_file
        self.agents_file = agents_file
        self.agents_json = agents_json
        self.tools = tools
        self.on_stream_event = on_stream_event
        self.lead = lead
        self.settings = settings or {}
        self.permission_mode = permission_mode
        self.add_dirs = add_dirs or []
        self.resume_session = resume_session
        self.env_vars = env_vars or {}
        self._mcp_config_file: str | None = None
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

    async def run(self) -> ClaudeResult:
        """Run the Claude CLI and stream output. Returns result."""
        # Configure tools from agent frontmatter (single source of truth).
        # Builtins → --tools flag. MCP → HTTP server with ASGI filter.
        if self.lead and self.tools is None:
            from teaparty.mcp.server.main import _load_agent_tools
            agent_tools = _load_agent_tools(self.lead)
            if agent_tools:
                mcp_prefix = 'mcp__'
                builtins = [t for t in agent_tools if not t.startswith(mcp_prefix)]
                if 'ToolSearch' not in builtins:
                    builtins.append('ToolSearch')
                self.tools = ','.join(builtins)

        # Write MCP config pointing to the shared HTTP server.
        # The URL encodes the agent scope for per-agent tool filtering.
        if self.lead:
            mcp_port = int(os.environ.get('TEAPARTY_MCP_PORT', '8082'))
            # TODO: support project scope — for now all agents are management
            mcp_url = f'http://localhost:{mcp_port}/mcp/management/{self.lead}'
            mcp_data = {'mcpServers': {'teaparty-config': {'type': 'http', 'url': mcp_url}}}
            mcp_file = tempfile.NamedTemporaryFile(
                mode='w', suffix='.json', prefix='mcp-', delete=False,
            )
            json.dump(mcp_data, mcp_file)
            mcp_file.close()
            self._mcp_config_file = mcp_file.name

        # Write settings to temp file
        settings_file = None
        settings = dict(self.settings) if self.settings else {}
        if settings:
            settings_file = tempfile.NamedTemporaryFile(
                mode='w', suffix='.json', delete=False,
            )
            json.dump(settings, settings_file)
            settings_file.close()

        try:
            args = self._build_args(settings_file.name if settings_file else None)
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
            )

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
            if self._mcp_config_file:
                try:
                    os.unlink(self._mcp_config_file)
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
            # Pre-composed JSON string from PhaseConfig
            agents_str = self.agents_json
            poc_root = self.env_vars.get('SCRIPT_DIR', '')
            session_dir = self.env_vars.get('POC_SESSION_DIR', '')
            if poc_root:
                agents_str = agents_str.replace('__POC_DIR__', poc_root)
            if session_dir:
                agents_str = agents_str.replace('__SESSION_DIR__', session_dir)
            args.extend(['--agents', agents_str])
        elif self.agents_file:
            # Legacy path: read agents from a JSON file
            try:
                with open(self.agents_file) as f:
                    agents_json = f.read()
                poc_root = self.env_vars.get('SCRIPT_DIR', '')
                session_dir = self.env_vars.get('POC_SESSION_DIR', '')
                if poc_root:
                    agents_json = agents_json.replace('__POC_DIR__', poc_root)
                if session_dir:
                    agents_json = agents_json.replace('__SESSION_DIR__', session_dir)
                args.extend(['--agents', agents_json])
            except OSError:
                pass
        if self.lead:
            args.extend(['--agent', self.lead])
        if settings_path:
            args.extend(['--settings', settings_path])
        for d in self.add_dirs:
            if d and os.path.isdir(d):
                args.extend(['--add-dir', d])
        if self.resume_session:
            args.extend(['--resume', self.resume_session])
        if self._mcp_config_file:
            args.extend(['--mcp-config', self._mcp_config_file, '--strict-mcp-config'])
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
                        etype = event_data.get('type', '')
                        if etype == 'tool_use':
                            tool_id = event_data.get('tool_use_id', '')
                            if tool_id:
                                open_tool_calls[tool_id] = now
                        elif etype == 'tool_result':
                            tool_id = event_data.get('tool_use_id', '')
                            open_tool_calls.pop(tool_id, None)

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
            """Priority cascade stall detection (issue #149).

            1. Mid-tool-call? (non-stale open tool_use → alive)
            2. Recent lead events? (within STALE_THRESHOLD → alive)
            3. Recent child stream events? (within STALE_THRESHOLD → alive)
            4. Children heartbeats fresh on disk? (via .children → alive)
            Only when all four fail: kill stale children, then declare stall.
            """
            while proc.returncode is None:
                await asyncio.sleep(self.BEAT_INTERVAL)
                if proc.returncode is not None:
                    break

                now = time.time()

                # Check 1: Active (non-stale) tool call
                has_active_tool = any(
                    (now - ts) < self.STALE_THRESHOLD
                    for ts in open_tool_calls.values()
                )
                if has_active_tool:
                    continue

                # Check 2: Recent lead events
                if (now - last_lead_event_time) < self.STALE_THRESHOLD:
                    continue

                # Check 3: Recent child stream events
                if last_child_event_time > 0 and (now - last_child_event_time) < self.STALE_THRESHOLD:
                    continue

                # Check 4: Children heartbeats on disk
                if self.children_file and os.path.exists(self.children_file):
                    from teaparty.bridge.state.heartbeat import read_children, is_heartbeat_stale
                    children = read_children(self.children_file)
                    any_child_alive = any(
                        os.path.exists(c.get('heartbeat', ''))
                        and not is_heartbeat_stale(c['heartbeat'], self.STALE_THRESHOLD)
                        for c in children
                    )
                    if any_child_alive:
                        continue

                # All checks failed — stall detected
                # Kill stale children before declaring the lead stalled
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

                # Now check if the lead itself is stalled
                age = now - last_output_time
                effective_timeout = self.stall_timeout
                if running_agent_count > 0:
                    effective_timeout = max(self.stall_timeout, 7200)
                if age >= effective_timeout:
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
        if (event.get('type') == 'system'
                and event.get('subtype') == 'init'
                and not self._extracted_session_id):
            self._extracted_session_id = event.get('session_id', '')

    def _maybe_extract_cost(self, event: dict) -> None:
        """Accumulate cost and turn stats from result events (Issues #262, #341)."""
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
        input_tokens = event.get('input_tokens', 0)
        if input_tokens:
            self._accumulated_input_tokens += input_tokens
        output_tokens = event.get('output_tokens', 0)
        if output_tokens:
            self._accumulated_output_tokens += output_tokens
        duration_ms = event.get('duration_ms', 0)
        if duration_ms:
            self._last_duration_ms = duration_ms


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
    """Kill a process and all its children."""
    try:
        os.killpg(os.getpgid(pid), signal.SIGTERM)
    except (ProcessLookupError, PermissionError, OSError):
        try:
            os.kill(pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            pass
