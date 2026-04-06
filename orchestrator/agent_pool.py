"""Persistent agent process pool for eliminating cold-start overhead.

Keeps long-lived `claude -p --input-format stream-json` processes alive
per agent role. First dispatch to a role pays the cold start (~3s).
Subsequent dispatches reuse the warm process (~2s).

The pool is owned by the OfficeManagerSession and lives for the
duration of the session.  Processes are cleaned up on session stop.

Protocol:
  stdin  → {"type": "user", "message": {"role": "user", "content": "..."}}
  stdout ← NDJSON events ending with {"type": "result", ...}
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import tempfile
import time
from typing import Any

_log = logging.getLogger('orchestrator.agent_pool')


class AgentProcess:
    """A single persistent claude -p process."""

    def __init__(
        self,
        role: str,
        proc: asyncio.subprocess.Process,
        session_id: str = '',
    ):
        self.role = role
        self.proc = proc
        self.session_id = session_id
        self.busy = False
        self._started_at = time.monotonic()

    @property
    def alive(self) -> bool:
        return self.proc.returncode is None

    async def send(self, message: str) -> tuple[str, str]:
        """Send a message and wait for the result.

        Returns (session_id, result_text).
        """
        if not self.alive:
            raise RuntimeError(f'Process for {self.role} is dead (rc={self.proc.returncode})')
        if self.busy:
            raise RuntimeError(f'Process for {self.role} is busy')

        self.busy = True
        t0 = time.monotonic()
        try:
            payload = json.dumps({
                'type': 'user',
                'message': {'role': 'user', 'content': message},
            }) + '\n'
            self.proc.stdin.write(payload.encode())
            await self.proc.stdin.drain()

            # Read NDJSON events until we get a result.
            # On the first call, the system/init event appears first.
            result_text = ''
            session_id = self.session_id
            while True:
                line = await asyncio.wait_for(
                    self.proc.stdout.readline(), timeout=600,
                )
                if not line:
                    _log.warning('agent_pool: EOF from %s process', self.role)
                    break
                line_str = line.decode().strip()
                if not line_str:
                    continue
                try:
                    obj = json.loads(line_str)
                except (json.JSONDecodeError, ValueError):
                    continue
                event_type = obj.get('type', '')

                if event_type == 'system':
                    sid = obj.get('session_id', '')
                    if sid:
                        session_id = sid
                        self.session_id = sid

                elif event_type == 'result':
                    result_text = obj.get('result', '')
                    session_id = obj.get('session_id', session_id)
                    self.session_id = session_id
                    break
                # Skip other events (assistant, rate_limit, etc.)

            elapsed = time.monotonic() - t0
            _log.info(
                'agent_pool_send: role=%r elapsed=%.2fs result_len=%d',
                self.role, elapsed, len(result_text),
            )
            return session_id, result_text

        finally:
            self.busy = False

    async def stop(self) -> None:
        """Terminate the process."""
        if self.alive:
            try:
                self.proc.stdin.close()
            except Exception:
                pass
            try:
                self.proc.terminate()
                await asyncio.wait_for(self.proc.wait(), timeout=5)
            except Exception:
                self.proc.kill()


class AgentPool:
    """Pool of persistent agent processes keyed by role.

    Usage:
        pool = AgentPool(teaparty_home='.teaparty')
        session_id, result = await pool.dispatch('configuration-lead', 'do something', ...)
        await pool.stop()
    """

    def __init__(self, teaparty_home: str):
        self.teaparty_home = teaparty_home
        self._processes: dict[str, AgentProcess] = {}

    async def dispatch(
        self,
        role: str,
        message: str,
        *,
        worktree: str,
        mcp_config: dict[str, Any] | None = None,
        agents_json: dict[str, Any] | None = None,
        settings_dict: dict[str, Any] | None = None,
    ) -> tuple[str, str]:
        """Dispatch a message to an agent, reusing a warm process if available.

        Returns (session_id, result_text).
        """
        agent = self._processes.get(role)

        if agent and agent.alive and not agent.busy:
            _log.info('agent_pool: reusing warm process for %s', role)
            return await agent.send(message)

        if agent and agent.alive and agent.busy:
            # Process is busy — spawn a fresh one-shot process instead
            # of waiting.  This handles parallel fan-out to the same role.
            _log.info('agent_pool: %s busy, spawning one-shot', role)
            from orchestrator.agent_spawner import AgentSpawner
            spawner = AgentSpawner(teaparty_home=self.teaparty_home)
            return await spawner.spawn(
                message, worktree=worktree, role=role,
                is_management=True,
                mcp_config=mcp_config, agents_json=agents_json,
            )

        if agent and not agent.alive:
            _log.info('agent_pool: process for %s died, respawning', role)
            del self._processes[role]

        # Cold start — create a new persistent process
        _log.info('agent_pool: cold start for %s', role)
        agent = await self._start_process(
            role, worktree=worktree,
            mcp_config=mcp_config,
            agents_json=agents_json,
            settings_dict=settings_dict,
        )
        self._processes[role] = agent
        return await agent.send(message)

    async def _start_process(
        self,
        role: str,
        *,
        worktree: str,
        mcp_config: dict[str, Any] | None = None,
        agents_json: dict[str, Any] | None = None,
        settings_dict: dict[str, Any] | None = None,
    ) -> AgentProcess:
        """Start a new persistent claude -p process."""
        repo_root = os.path.dirname(self.teaparty_home)
        api_key_helper = os.path.join(repo_root, 'scripts', 'get-api-key.sh')
        use_bare = os.path.isfile(api_key_helper)

        settings = dict(settings_dict or {})
        if use_bare and api_key_helper:
            settings['apiKeyHelper'] = api_key_helper

        # Build command
        cmd = [
            'claude', '-p',
            '--output-format', 'stream-json',
            '--input-format', 'stream-json',
            '--verbose',
            '--agent', role,
        ]

        if use_bare:
            cmd.append('--bare')
        else:
            cmd.extend(['--setting-sources', 'user'])

        # Dispatching leads: no builtins (MCP Send only).
        # Leaf specialists: default builtins for real work.
        builtin_tools = '' if agents_json else 'default'
        cmd.extend(['--tools', builtin_tools])

        if agents_json:
            cmd.extend(['--agents', json.dumps(agents_json)])

        if settings:
            cmd.extend(['--settings', json.dumps(settings)])

        mcp_config_file = None
        if mcp_config:
            mcp_config_file = tempfile.NamedTemporaryFile(
                mode='w', suffix='.json', prefix='mcp-pool-', delete=False,
            )
            json.dump({'mcpServers': mcp_config}, mcp_config_file)
            mcp_config_file.close()
            cmd.extend([
                '--mcp-config', mcp_config_file.name,
                '--strict-mcp-config',
            ])

        env = dict(os.environ)
        env.pop('AGENT_TOOL_SCOPE', None)
        env['DISABLE_NONESSENTIAL_TRAFFIC'] = '1'
        env['MCP_TIMEOUT'] = '5000'

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=worktree,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )

        return AgentProcess(role, proc)

    async def stop(self) -> None:
        """Stop all processes."""
        for agent in self._processes.values():
            await agent.stop()
        self._processes.clear()
