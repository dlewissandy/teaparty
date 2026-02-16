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
import time
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


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
    num_turns: int = 0
    is_error: bool = False
    error: str | None = None


async def run_claude(
    *,
    system_prompt: str,
    user_message: str,
    model: str = "sonnet",
    cwd: str | None = None,
    allowed_tools: list[str] | None = None,
    disallowed_tools: list[str] | None = None,
    max_turns: int = 3,
    timeout_seconds: int = 120,
) -> ClaudeResult:
    """Run ``claude -p`` as a subprocess and return the parsed result.

    *user_message* is piped via **stdin** to avoid shell-escaping issues.
    """

    cmd: list[str] = [
        "claude",
        "-p",
        "--output-format", "json",
        "--model", model,
        "--max-turns", str(max_turns),
        "--verbose",
    ]

    if system_prompt:
        cmd.extend(["--system-prompt", system_prompt])

    if allowed_tools:
        cmd.extend(["--allowedTools", ",".join(allowed_tools)])
    elif disallowed_tools:
        cmd.extend(["--disallowedTools", ",".join(disallowed_tools)])
    else:
        # Default: no tools (pure conversation)
        cmd.extend(["--allowedTools", ""])

    # Build a clean environment: inherit the parent env but remove
    # CLAUDE_CODE_ENTRYPOINT (prevents nested-session errors).
    env = {**os.environ}
    env.pop("CLAUDE_CODE_ENTRYPOINT", None)

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
        stdout, stderr = await asyncio.wait_for(
            process.communicate(input=user_message.encode()),
            timeout=timeout_seconds,
        )
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
    """Parse the JSON emitted by ``claude -p --output-format json``."""
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        # Fall back to treating stdout as plain text.
        logger.warning("Failed to parse claude JSON output; treating as plain text")
        return ClaudeResult(text=raw.strip(), duration_ms=elapsed_ms)

    usage = data.get("usage") or {}
    return ClaudeResult(
        text=data.get("result", ""),
        cost_usd=data.get("cost_usd", 0.0) or data.get("total_cost_usd", 0.0),
        input_tokens=usage.get("input_tokens", 0),
        output_tokens=usage.get("output_tokens", 0),
        duration_ms=elapsed_ms,
        model=data.get("model", ""),
        session_id=data.get("session_id", ""),
        num_turns=data.get("num_turns", 0),
        is_error=bool(data.get("is_error")),
        error=data.get("result") if data.get("is_error") else None,
    )
