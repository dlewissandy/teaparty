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
    event_bus=None,
) -> None:
    """Run the full learning extraction pipeline for a completed session.

    Each extraction step calls synchronous code that blocks on subprocess.run()
    (claude CLI invocations).  We run each step via asyncio.to_thread() so the
    event loop stays responsive — the TUI can render, process input, and show
    progress while extraction proceeds in background threads.

    If event_bus is provided, per-scope results and a summary diagnostic are
    published as LOG events so they appear in the session log.
    """
    from projects.POC.orchestrator.events import EventType, Event

    scripts_dir = os.path.join(poc_root, 'scripts')
    succeeded = 0
    failed = 0
    failed_scopes = []

    async def _run_scope(scope_name: str, fn, *args, **kwargs):
        """Run a scope function, track and emit its result."""
        nonlocal succeeded, failed
        try:
            await asyncio.to_thread(fn, *args, **kwargs)
            succeeded += 1
            if event_bus:
                await event_bus.publish(Event(
                    type=EventType.LOG,
                    data={'category': 'LEARN', 'scope': scope_name,
                          'status': 'success',
                          'message': f'{scope_name} learning extraction succeeded'},
                ))
        except Exception as exc:
            failed += 1
            failed_scopes.append(scope_name)
            if event_bus:
                await event_bus.publish(Event(
                    type=EventType.LOG,
                    data={'category': 'LEARN', 'scope': scope_name,
                          'status': 'failed',
                          'message': f'{scope_name} learning extraction failed: {exc}'},
                ))

    # ── Intent-stream scopes (original 3) ─────────────────────────────────────

    await _run_scope(
        'observations', _run_summarize, scripts_dir, infra_dir,
        scope='observations',
        output=os.path.join(project_dir, 'proxy.md'),
    )
    await _run_scope(
        'escalation', _run_summarize, scripts_dir, infra_dir,
        scope='escalation',
        output=os.path.join(project_dir, 'proxy-tasks'),
    )
    await _run_scope(
        'intent-alignment', _run_summarize, scripts_dir, infra_dir,
        scope='intent-alignment',
        output=os.path.join(project_dir, 'tasks'),
    )

    # ── Rollup scopes ─────────────────────────────────────────────────────────

    await _run_scope('team', _promote_team, infra_dir=infra_dir, scripts_dir=scripts_dir)
    await _run_scope('session', _promote_session, infra_dir=infra_dir, scripts_dir=scripts_dir)
    await _run_scope(
        'project', _promote_project,
        infra_dir=infra_dir, project_dir=project_dir, scripts_dir=scripts_dir,
    )
    await _run_scope(
        'global', _promote_global,
        project_dir=project_dir, scripts_dir=scripts_dir, session_dir=infra_dir,
    )

    # ── Temporal scopes ───────────────────────────────────────────────────────

    await _run_scope(
        'prospective', _promote_prospective,
        infra_dir=infra_dir, project_dir=project_dir, scripts_dir=scripts_dir,
    )
    await _run_scope(
        'in-flight', _promote_in_flight,
        infra_dir=infra_dir, project_dir=project_dir, scripts_dir=scripts_dir,
    )
    await _run_scope(
        'corrective', _promote_corrective,
        infra_dir=infra_dir, project_dir=project_dir, scripts_dir=scripts_dir,
    )

    # ── Reinforcement tracking ─────────────────────────────────────────────────

    await _run_scope(
        'reinforcement', _reinforce_retrieved,
        infra_dir=infra_dir, project_dir=project_dir,
    )

    # ── Summary diagnostic ────────────────────────────────────────────────────

    total = succeeded + failed
    if event_bus:
        failed_list = f' ({", ".join(failed_scopes)})' if failed_scopes else ''
        await event_bus.publish(Event(
            type=EventType.LOG,
            data={
                'category': 'LEARN',
                'scope': 'summary',
                'message': (
                    f'Learning extraction complete: '
                    f'{succeeded}/{total} scopes succeeded, '
                    f'{failed} failed{failed_list}'
                ),
                'succeeded': succeeded,
                'failed': failed,
                'failed_scopes': failed_scopes,
            },
        ))


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


# ── Reinforcement tracking ────────────────────────────────────────────────────

def _reinforce_retrieved(*, infra_dir: str, project_dir: str) -> None:
    """Increment reinforcement_count for entries retrieved at session start.

    Reads the .retrieved-ids.txt sidecar file (written by memory_indexer.retrieve)
    and updates matching entries in the project's memory files.  Implements the
    "use it or lose it" memory strengthening signal.
    """
    from pathlib import Path

    ids_path = os.path.join(infra_dir, '.retrieved-ids.txt')
    if not os.path.exists(ids_path):
        return

    from projects.POC.scripts.track_reinforcement import reinforce_entries, load_ids
    from projects.POC.scripts.memory_entry import parse_memory_file, serialize_memory_file

    retrieved_ids = load_ids(ids_path)
    if not retrieved_ids:
        return

    # Collect memory files to scan
    memory_files = []
    for name in ('institutional.md', 'proxy.md'):
        p = os.path.join(project_dir, name)
        if os.path.isfile(p):
            memory_files.append(p)

    tasks_dir = os.path.join(project_dir, 'tasks')
    if os.path.isdir(tasks_dir):
        for f in sorted(os.listdir(tasks_dir)):
            if f.endswith('.md'):
                memory_files.append(os.path.join(tasks_dir, f))

    proxy_tasks_dir = os.path.join(project_dir, 'proxy-tasks')
    if os.path.isdir(proxy_tasks_dir):
        for f in sorted(os.listdir(proxy_tasks_dir)):
            if f.endswith('.md'):
                memory_files.append(os.path.join(proxy_tasks_dir, f))

    total_reinforced = 0
    for mem_path in memory_files:
        try:
            text = Path(mem_path).read_text(errors='replace')
        except OSError:
            continue

        entries = parse_memory_file(text)
        if not entries:
            continue

        updated, count = reinforce_entries(entries, retrieved_ids)
        if count > 0:
            try:
                Path(mem_path).write_text(serialize_memory_file(updated))
                total_reinforced += count
            except OSError:
                pass
