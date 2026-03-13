"""Async wrapper around the Claude CLI subprocess.

Replaces the run_claude() / run_orchestrated() bash functions in
plan-execute.sh and the run_turn() function in intent.sh.

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
from typing import Any

from projects.POC.orchestrator.events import Event, EventBus, EventType


@dataclass
class ClaudeResult:
    exit_code: int
    session_id: str = ''
    stream_file: str = ''
    stall_killed: bool = False


class ClaudeRunner:
    """Manages a single Claude CLI invocation."""

    def __init__(
        self,
        prompt: str,
        *,
        cwd: str,
        stream_file: str,
        agents_file: str | None = None,
        lead: str | None = None,
        settings: dict[str, Any] | None = None,
        permission_mode: str = 'default',
        add_dirs: list[str] | None = None,
        resume_session: str | None = None,
        env_vars: dict[str, str] | None = None,
        event_bus: EventBus | None = None,
        stall_timeout: int = 1800,
        session_id: str = '',
    ):
        self.prompt = prompt
        self.cwd = cwd
        self.stream_file = stream_file
        self.agents_file = agents_file
        self.lead = lead
        self.settings = settings or {}
        self.permission_mode = permission_mode
        self.add_dirs = add_dirs or []
        self.resume_session = resume_session
        self.env_vars = env_vars or {}
        self.event_bus = event_bus
        self.stall_timeout = stall_timeout
        self.session_id = session_id
        self._process: asyncio.subprocess.Process | None = None
        self._extracted_session_id: str = ''

    async def run(self) -> ClaudeResult:
        """Run the Claude CLI and stream output. Returns result."""
        # Write settings to temp file
        settings_file = None
        if self.settings:
            settings_file = tempfile.NamedTemporaryFile(
                mode='w', suffix='.json', delete=False,
            )
            json.dump(self.settings, settings_file)
            settings_file.close()

        try:
            args = self._build_args(settings_file.name if settings_file else None)
            env = self._build_env()

            self._process = await asyncio.create_subprocess_exec(
                *args,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
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
            try:
                exit_code = await self._stream_with_watchdog()
            except _StallTimeout:
                stall_killed = True
                exit_code = -1

            return ClaudeResult(
                exit_code=exit_code,
                session_id=self._extracted_session_id,
                stream_file=self.stream_file,
                stall_killed=stall_killed,
            )
        finally:
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
            '--setting-sources', 'user',
        ]
        if self.permission_mode != 'default':
            args.extend(['--permission-mode', self.permission_mode])
        if self.agents_file:
            # --agents takes a JSON string, not a file path.
            # Read the agents definition file and pass its contents.
            try:
                with open(self.agents_file) as f:
                    agents_json = f.read()
                # Gaps 12/67: apply placeholder substitution (mirrors run.sh / dispatch.sh sed)
                poc_root = self.env_vars.get('SCRIPT_DIR', '')
                session_dir = self.env_vars.get('POC_SESSION_DIR', '')
                if poc_root:
                    agents_json = agents_json.replace('__POC_DIR__', poc_root)
                if session_dir:
                    agents_json = agents_json.replace('__SESSION_DIR__', session_dir)
                args.extend(['--agents', agents_json])
            except OSError:
                pass  # File not found — skip agents flag
        if self.lead:
            args.extend(['--agent', self.lead])
        if settings_path:
            args.extend(['--settings', settings_path])
        for d in self.add_dirs:
            if d and os.path.isdir(d):
                args.extend(['--add-dir', d])
        if self.resume_session:
            args.extend(['--resume', self.resume_session])
        return args

    def _build_env(self) -> dict[str, str]:
        env = dict(os.environ)
        env['CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS'] = '1'
        env['CLAUDE_CODE_MAX_OUTPUT_TOKENS'] = '128000'
        env.update(self.env_vars)
        return env

    async def _stream_with_watchdog(self) -> int:
        """Stream stdout while monitoring for stalls."""
        proc = self._process
        assert proc and proc.stdout

        last_output_time = time.time()

        async def read_stream():
            nonlocal last_output_time
            with open(self.stream_file, 'a') as f:
                async for line in proc.stdout:
                    line_str = line.decode().rstrip()
                    if not line_str:
                        continue
                    last_output_time = time.time()

                    # Persist to stream file
                    f.write(line_str + '\n')
                    f.flush()

                    # Parse and extract session ID
                    try:
                        event_data = json.loads(line_str)
                        self._maybe_extract_session_id(event_data)

                        # Publish to event bus
                        if self.event_bus:
                            await self.event_bus.publish(Event(
                                type=EventType.STREAM_DATA,
                                data=event_data,
                                session_id=self.session_id,
                            ))
                    except json.JSONDecodeError:
                        pass

        async def watchdog():
            nonlocal last_output_time
            while proc.returncode is None:
                await asyncio.sleep(30)
                age = time.time() - last_output_time
                if age >= self.stall_timeout:
                    _kill_process_tree(proc.pid)
                    raise _StallTimeout()

        # Run reader and watchdog concurrently
        reader_task = asyncio.create_task(read_stream())
        watchdog_task = asyncio.create_task(watchdog())

        try:
            await reader_task
            exit_code = await proc.wait()
        finally:
            watchdog_task.cancel()
            try:
                await watchdog_task
            except (asyncio.CancelledError, _StallTimeout):
                pass

        return exit_code

    def _kill_subprocess(self) -> None:
        """Kill the child subprocess and its process tree if still running."""
        if self._process and self._process.returncode is None:
            _kill_process_tree(self._process.pid)

    def _maybe_extract_session_id(self, event: dict) -> None:
        if (event.get('type') == 'system'
                and event.get('subtype') == 'init'
                and not self._extracted_session_id):
            self._extracted_session_id = event.get('session_id', '')


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
