"""AskQuestion handler — looks up the caller's runner and delegates.

Before Cut 10 this module also held a bus ping-pong: the handler
``send``-ed a message on the bus, then polled for an ``orchestrator``
reply written by ``EscalationListener`` in the same process.  Both
ends of that dance ran in the bridge process, so the bus hop served
no transport purpose.  It's gone.  The handler now calls the runner
directly.
"""
from __future__ import annotations

import os


CONTEXT_BUDGET_LINES = 200


async def ask_question_handler(
    question: str,
    context: str = '',
    *,
    scratch_path: str = '',
) -> str:
    """Delegate the AskQuestion tool call to the caller's runner.

    The in-process registry holds an ``AskQuestionRunner`` per agent
    that can receive questions.  The runner drives the proxy + skill
    loop and returns the answer; this handler is a thin lookup.

    The proxy launches inside a real-file clone of the caller's
    worktree (#425), so any file the caller could read is reachable
    by the proxy at the same relative path under ``worktree/``.  No
    attachment hand-off is needed; the proxy walks the clone itself
    during its diligence pass.
    """
    if not question or not question.strip():
        raise ValueError('AskQuestion requires a non-empty question')

    if scratch_path:
        question = _build_composite(question, _read_scratch(scratch_path))
        context = ''

    # Import lazily so the MCP tool module doesn't pull in the whole
    # teaparty package at import time.
    from teaparty.mcp.registry import get_ask_question_runner  # noqa: PLC0415

    runner = get_ask_question_runner()
    if runner is None:
        raise RuntimeError(
            'No AskQuestionRunner registered for the calling agent — '
            'the agent session must register one before AskQuestion '
            'becomes callable.',
        )
    return await runner.run(question, context)


# ── Scratch file helpers ────────────────────────────────────────────────

def _read_scratch(scratch_path: str) -> str:
    """Read the scratch file, truncated to CONTEXT_BUDGET_LINES."""
    try:
        with open(scratch_path) as f:
            lines = f.readlines()
    except FileNotFoundError:
        return ''
    if len(lines) > CONTEXT_BUDGET_LINES:
        lines = lines[-CONTEXT_BUDGET_LINES:]
    return ''.join(lines)


def _build_composite(message: str, scratch: str) -> str:
    """Build the Task/Context composite envelope."""
    return f'## Task\n{message}\n\n## Context\n{scratch}'


def _scratch_path_from_env() -> str:
    """Resolve the scratch file path from TEAPARTY_WORKTREE env var."""
    worktree = os.environ.get('TEAPARTY_WORKTREE', os.getcwd())
    return os.path.join(worktree, '.context', 'scratch.md')
