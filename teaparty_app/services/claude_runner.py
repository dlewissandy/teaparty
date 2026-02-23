"""Subprocess wrapper for the ``claude`` CLI.

Every LLM interaction in Teaparty is a single ``claude -p`` invocation.
This module provides the async helper that builds the command, runs
the subprocess, and parses the structured JSON result.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
import time
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Running process tracking (for cancellation)
# ---------------------------------------------------------------------------
_running_processes: dict[str, asyncio.subprocess.Process] = {}
_process_lock = threading.Lock()


def _register_process(conversation_id: str, process: asyncio.subprocess.Process) -> None:
    with _process_lock:
        _running_processes[conversation_id] = process


def _unregister_process(conversation_id: str) -> None:
    with _process_lock:
        _running_processes.pop(conversation_id, None)


def kill_conversation_process(conversation_id: str) -> None:
    """Kill a running ``claude -p`` subprocess for the given conversation."""
    with _process_lock:
        process = _running_processes.pop(conversation_id, None)
    if process:
        try:
            process.kill()
        except Exception:
            pass


@dataclass
class ClaudeResult:
    """Parsed output from a ``claude -p`` invocation."""

    text: str = ""
    cost_usd: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    duration_ms: int = 0
    model: str = ""
    session_id: str = ""
    slug: str = ""
    num_turns: int = 0
    is_error: bool = False
    error: str | None = None
    events: list[dict] = field(default_factory=list)


async def run_claude(
    *,
    system_prompt: str = "",
    user_message: str,
    model: str = "sonnet",
    agent_name: str | None = None,
    agents_json: str | None = None,
    permission_mode: str = "acceptEdits",
    settings_json: str | None = None,
    cwd: str | None = None,
    allowed_tools: list[str] | None = None,
    disallowed_tools: list[str] | None = None,
    max_turns: int = 3,
    timeout_seconds: int = 120,
    conversation_id: str | None = None,
    resume_session_id: str | None = None,
    extra_env: dict[str, str] | None = None,
) -> ClaudeResult:
    """Run ``claude -p`` as a subprocess and return the parsed result.

    *user_message* is piped via **stdin** to avoid shell-escaping issues.

    When *agent_name* + *agents_json* are provided, the command uses
    ``--agent <name> --agents '<json>'`` instead of ``--system-prompt``
    and ``--model`` (the agent definition carries the model).
    """

    cmd: list[str] = [
        "claude",
        "-p",
        "--output-format", "stream-json",
        "--max-turns", str(max_turns),
        "--verbose",
    ]

    if agent_name and agents_json:
        # Agent-based invocation: --agent + --agents (no --system-prompt, no --model)
        cmd.extend(["--agent", agent_name])
        cmd.extend(["--agents", agents_json])
    else:
        # Legacy invocation: --system-prompt + --model
        cmd.extend(["--model", model])
        if system_prompt:
            cmd.extend(["--system-prompt", system_prompt])

    if resume_session_id:
        cmd.extend(["--resume", resume_session_id])

    cmd.extend(["--permission-mode", permission_mode])

    if settings_json:
        cmd.extend(["--settings", settings_json])

    if allowed_tools:
        cmd.extend(["--allowedTools", ",".join(allowed_tools)])
    elif disallowed_tools:
        cmd.extend(["--disallowedTools", ",".join(disallowed_tools)])
    elif not agent_name:
        # Default for non-agent mode: no tools (pure conversation).
        # Agent mode needs the Task tool for delegation, so skip this.
        cmd.extend(["--allowedTools", ""])

    # Build a clean environment: inherit the parent env but remove
    # vars that trigger nested-session detection in Claude Code.
    env = {**os.environ}
    env.pop("CLAUDE_CODE_ENTRYPOINT", None)
    env.pop("CLAUDECODE", None)
    if extra_env:
        env.update(extra_env)

    t0 = time.monotonic()
    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
            env=env,
        )
        if conversation_id:
            _register_process(conversation_id, process)
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(input=user_message.encode()),
                timeout=timeout_seconds,
            )
        finally:
            if conversation_id:
                _unregister_process(conversation_id)
    except asyncio.TimeoutError:
        logger.warning("claude subprocess timed out after %ds", timeout_seconds)
        try:
            process.kill()  # type: ignore[union-attr]
        except Exception:
            pass
        return ClaudeResult(
            error=f"Timed out after {timeout_seconds}s",
            is_error=True,
            duration_ms=int((time.monotonic() - t0) * 1000),
        )
    except FileNotFoundError:
        return ClaudeResult(
            error="claude CLI not found on PATH",
            is_error=True,
            duration_ms=int((time.monotonic() - t0) * 1000),
        )

    elapsed_ms = int((time.monotonic() - t0) * 1000)
    raw = stdout.decode(errors="replace")

    if process.returncode != 0:
        err_text = stderr.decode(errors="replace").strip() or raw.strip()
        logger.warning("claude exited %d: %s", process.returncode, err_text[:500])
        return ClaudeResult(
            error=err_text[:2000],
            is_error=True,
            duration_ms=elapsed_ms,
        )

    return _parse_json_output(raw, elapsed_ms)


def _parse_json_output(raw: str, elapsed_ms: int) -> ClaudeResult:
    """Parse NDJSON from ``claude -p --output-format stream-json --verbose``.

    Each line of output is a separate JSON event.  We collect all events
    and extract the ``result`` entry for the final ClaudeResult.
    """
    events: list[dict] = []
    result_entry: dict = {}

    for line in raw.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            events.append(data)
            if data.get("type") == "result":
                result_entry = data

    if not result_entry and not events:
        logger.warning("No parseable JSON in claude output; treating as plain text")
        return ClaudeResult(text=raw.strip(), duration_ms=elapsed_ms)

    usage = result_entry.get("usage") or {}
    return ClaudeResult(
        text=result_entry.get("result", ""),
        cost_usd=result_entry.get("cost_usd", 0.0) or result_entry.get("total_cost_usd", 0.0),
        input_tokens=usage.get("input_tokens", 0),
        output_tokens=usage.get("output_tokens", 0),
        duration_ms=elapsed_ms,
        model=result_entry.get("model", ""),
        session_id=result_entry.get("session_id", ""),
        slug=result_entry.get("slug", ""),
        num_turns=result_entry.get("num_turns", 0),
        is_error=bool(result_entry.get("is_error")),
        error=result_entry.get("result") if result_entry.get("is_error") else None,
        events=events,
    )
