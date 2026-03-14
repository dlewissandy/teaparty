"""Post-session learning extraction.

Extracts learnings from session streams and archives them to the project
memory stores. Implements all 10 scopes of the promote_learnings.sh pipeline:

  Original 3 (intent-stream scopes):
    observations     — human preference signals → project/proxy.md
    escalation       — autonomy calibration signals → project/proxy-tasks/
    intent-alignment — intent vs execution gaps → project/tasks/

  Rollup scopes (promote upward through the hierarchy):
    team    — dispatch MEMORYs → team institutional.md + team/tasks/
    session — team files → session institutional.md + session/tasks/
    project — session files → project institutional.md + project/tasks/
    global  — project institutional.md → projects/ institutional.md + projects/tasks/

  Temporal scopes (different perspectives on the work):
    prospective — pre-mortem → project/tasks/<ts>-prospective.md
    in-flight   — assumption checkpoints → project/tasks/<ts>-inflight.md
    corrective  — exec stream errors → project/tasks/<ts>-corrective.md
"""
from __future__ import annotations

import asyncio
import os
import sys


async def extract_learnings(
    *,
    infra_dir: str,
    project_dir: str,
    session_worktree: str,
    task: str,
    poc_root: str,
) -> None:
    """Run the full learning extraction pipeline for a completed session.

    Each extraction step calls synchronous code that blocks on subprocess.run()
    (claude CLI invocations).  We run each step via asyncio.to_thread() so the
    event loop stays responsive — the TUI can render, process input, and show
    progress while extraction proceeds in background threads.
    """
    scripts_dir = os.path.join(poc_root, 'scripts')

    # ── Intent-stream scopes (original 3) ─────────────────────────────────────

    # Extract observations → proxy.md
    await asyncio.to_thread(
        _run_summarize,
        scripts_dir, infra_dir,
        scope='observations',
        output=os.path.join(project_dir, 'proxy.md'),
    )

    # Extract escalation → proxy-tasks/
    await asyncio.to_thread(
        _run_summarize,
        scripts_dir, infra_dir,
        scope='escalation',
        output=os.path.join(project_dir, 'proxy-tasks'),
    )

    # Extract intent-alignment → tasks/
    await asyncio.to_thread(
        _run_summarize,
        scripts_dir, infra_dir,
        scope='intent-alignment',
        output=os.path.join(project_dir, 'tasks'),
    )

    # ── Rollup scopes ─────────────────────────────────────────────────────────

    await asyncio.to_thread(_promote_team, infra_dir=infra_dir, scripts_dir=scripts_dir)
    await asyncio.to_thread(_promote_session, infra_dir=infra_dir, scripts_dir=scripts_dir)
    await asyncio.to_thread(
        _promote_project,
        infra_dir=infra_dir,
        project_dir=project_dir,
        scripts_dir=scripts_dir,
    )
    await asyncio.to_thread(
        _promote_global,
        project_dir=project_dir,
        scripts_dir=scripts_dir,
        session_dir=infra_dir,
    )

    # ── Temporal scopes ───────────────────────────────────────────────────────

    await asyncio.to_thread(
        _promote_prospective,
        infra_dir=infra_dir,
        project_dir=project_dir,
        scripts_dir=scripts_dir,
    )
    await asyncio.to_thread(
        _promote_in_flight,
        infra_dir=infra_dir,
        project_dir=project_dir,
        scripts_dir=scripts_dir,
    )
    await asyncio.to_thread(
        _promote_corrective,
        infra_dir=infra_dir,
        project_dir=project_dir,
        scripts_dir=scripts_dir,
    )


# ── Original 3 scopes (intent-stream via summarize_session.py subprocess) ─────

def _run_summarize(
    scripts_dir: str,
    infra_dir: str,
    *,
    scope: str,
    output: str,
) -> None:
    """Call summarize_session.summarize() directly for an intent-stream scope.

    Previous implementation shelled out via subprocess with CLI args that
    didn't match summarize_session.py's argparser (--task doesn't exist,
    multiple --stream flags but CLI expects one). Errors were swallowed by
    a bare ``except Exception: pass``.

    Now calls the Python function directly, picking the right stream file
    for the scope.
    """
    # Pick the correct stream for the scope
    # observations and escalation use the intent stream;
    # intent-alignment uses the exec stream
    if scope in ('observations', 'escalation'):
        stream_name = '.intent-stream.jsonl'
    else:
        stream_name = '.exec-stream.jsonl'

    stream_path = os.path.join(infra_dir, stream_name)
    if not os.path.exists(stream_path) or os.path.getsize(stream_path) == 0:
        return

    added_to_path = False
    try:
        if scripts_dir and scripts_dir not in sys.path:
            sys.path.insert(0, scripts_dir)
            added_to_path = True
        from summarize_session import summarize
        summarize(stream_path, output, [], scope)
    except Exception as exc:
        print(
            f'[learnings] {scope} extraction failed: {exc}',
            file=sys.stderr,
        )
    finally:
        if added_to_path:
            try:
                sys.path.remove(scripts_dir)
            except ValueError:
                pass


# ── Rollup scope helpers ───────────────────────────────────────────────────────

def _call_promote(scripts_dir: str, scope: str, **kwargs) -> None:
    """Call summarize_session.promote() directly (importable API)."""
    added_to_path = False
    try:
        if scripts_dir and scripts_dir not in sys.path:
            sys.path.insert(0, scripts_dir)
            added_to_path = True
        from summarize_session import promote
        promote(scope, **kwargs)
    except Exception as exc:
        print(
            f'[learnings] promote {scope} failed: {exc}',
            file=sys.stderr,
        )
    finally:
        if added_to_path:
            try:
                if sys.path and sys.path[0] == scripts_dir:
                    sys.path.pop(0)
                else:
                    sys.path.remove(scripts_dir)
            except ValueError:
                # scripts_dir was not found in sys.path; nothing to clean up.
                pass


def _promote_team(*, infra_dir: str, scripts_dir: str) -> None:
    """Dispatch MEMORY.md files → per-team institutional.md + tasks/<ts>.md."""
    _call_promote(
        scripts_dir,
        'team',
        session_dir=infra_dir,
        project_dir='',
        output_dir='',
    )


def _promote_session(*, infra_dir: str, scripts_dir: str) -> None:
    """Team typed files → session institutional.md + session/tasks/<ts>.md."""
    _call_promote(
        scripts_dir,
        'session',
        session_dir=infra_dir,
        project_dir='',
        output_dir='',
    )


def _promote_project(
    *,
    infra_dir: str,
    project_dir: str,
    scripts_dir: str,
) -> None:
    """Session typed files → project institutional.md + project/tasks/<ts>.md."""
    _call_promote(
        scripts_dir,
        'project',
        session_dir=infra_dir,
        project_dir=project_dir,
        output_dir='',
    )


def _promote_global(
    *,
    project_dir: str,
    scripts_dir: str,
    session_dir: str,
) -> None:
    """Project institutional.md → projects/ institutional.md + projects/tasks/<ts>.md."""
    projects_dir = os.path.dirname(project_dir)
    _call_promote(
        scripts_dir,
        'global',
        session_dir=session_dir,
        project_dir=project_dir,
        output_dir=projects_dir,
    )


# ── Temporal scope helpers ─────────────────────────────────────────────────────

def _promote_prospective(
    *,
    infra_dir: str,
    project_dir: str,
    scripts_dir: str,
) -> None:
    """Pre-mortem file + exec stream → project/tasks/<ts>-prospective.md."""
    _call_promote(
        scripts_dir,
        'prospective',
        session_dir=infra_dir,
        project_dir=project_dir,
        output_dir='',
    )


def _promote_in_flight(
    *,
    infra_dir: str,
    project_dir: str,
    scripts_dir: str,
) -> None:
    """Assumption checkpoints + exec stream → project/tasks/<ts>-inflight.md."""
    _call_promote(
        scripts_dir,
        'in-flight',
        session_dir=infra_dir,
        project_dir=project_dir,
        output_dir='',
    )


def _promote_corrective(
    *,
    infra_dir: str,
    project_dir: str,
    scripts_dir: str,
) -> None:
    """Exec stream errors → project/tasks/<ts>-corrective.md."""
    _call_promote(
        scripts_dir,
        'corrective',
        session_dir=infra_dir,
        project_dir=project_dir,
        output_dir='',
    )
