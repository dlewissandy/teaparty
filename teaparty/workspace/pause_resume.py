"""Project-scoped pause / resume for dispatched session trees (issue #403).

Pause All and Resume All on the project card are direct operational controls,
not agent-interpreted requests. This module implements the mechanics.

Fidelity invariant: sessions that are in ``awaiting`` or ``complete`` phase
at pause time resume without re-running any LLM work; only ``launching``
leaves (whose claude turn was actually killed) pay the cost of re-running
one turn via ``--resume``.

The subtree loop in ``teams.session._run_child`` writes the session's
phase continuously (see ``runners.launcher.mark_launching/awaiting/complete``),
so at any cancellation point each session on disk is unambiguously in one
of the three phases. The walker here relies on that invariant.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from teaparty.teams.session import AgentSession

_log = logging.getLogger('teaparty.workspace.pause_resume')


# ── Disk walk ───────────────────────────────────────────────────────────────

def collect_project_subtree(
    sessions_dir: str,
    project_slug: str,
) -> list[tuple[str, str]]:
    """Return (session_id, parent_id) pairs for every session in a project.

    Depth-first, roots first. A root is any session whose metadata has
    ``project_slug == project_slug`` and whose ``parent_session_id`` is
    empty *or* points to a session outside the project (i.e. the
    dispatcher that owns the top-level job).
    """
    result: list[tuple[str, str]] = []
    if not os.path.isdir(sessions_dir):
        return result

    # First pass: read every session's metadata once.
    meta_by_sid: dict[str, dict] = {}
    for entry in os.scandir(sessions_dir):
        if not entry.is_dir():
            continue
        meta_path = os.path.join(entry.path, 'metadata.json')
        if not os.path.isfile(meta_path):
            continue
        try:
            with open(meta_path) as f:
                meta_by_sid[entry.name] = json.load(f)
        except (json.JSONDecodeError, OSError):
            continue

    # Find roots: in-project sessions whose parent is not in-project.
    def _is_root(sid: str) -> bool:
        meta = meta_by_sid.get(sid, {})
        if meta.get('project_slug') != project_slug:
            return False
        parent = meta.get('parent_session_id', '')
        if not parent:
            return True
        parent_meta = meta_by_sid.get(parent)
        if parent_meta is None:
            return True
        return parent_meta.get('project_slug') != project_slug

    def _walk(sid: str, parent: str) -> None:
        meta = meta_by_sid.get(sid)
        if meta is None or meta.get('project_slug') != project_slug:
            return
        result.append((sid, parent))
        for grandchild in meta.get('conversation_map', {}).values():
            _walk(grandchild, sid)

    for sid, meta in meta_by_sid.items():
        if _is_root(sid):
            _walk(sid, meta.get('parent_session_id', ''))
    return result


# ── Pause ───────────────────────────────────────────────────────────────────

async def pause_project_subtree(
    project_slug: str,
    sessions_dir: str,
    agent_session: 'AgentSession',
    *,
    cancel_timeout: float = 2.0,
) -> list[str]:
    """Cancel every in-flight _run_child task in the project subtree.

    The phase field on disk was already written before each await by the
    subtree loop, so cancelling now leaves the recorded phase accurate.
    Claude subprocesses die as a side-effect of their enclosing tasks
    being cancelled.

    Returns the list of session ids that were found in the project.
    """
    subtree = collect_project_subtree(sessions_dir, project_slug)
    session_ids = [sid for sid, _ in subtree]
    tasks: list[asyncio.Task] = []
    for sid in session_ids:
        task = agent_session._tasks_by_child.get(sid)
        if task is not None and not task.done():
            task.cancel()
            tasks.append(task)
    if tasks:
        try:
            await asyncio.wait_for(
                asyncio.gather(*tasks, return_exceptions=True),
                timeout=cancel_timeout,
            )
        except asyncio.TimeoutError:
            _log.warning(
                'pause_project_subtree: tasks did not cancel within %ss',
                cancel_timeout,
            )
    # Drop cancelled tasks from the dispatcher's task map so a subsequent
    # resume can register fresh ones. Factories are retained — the resume
    # walker needs them to re-enter the loop.
    for sid in session_ids:
        t = agent_session._tasks_by_child.get(sid)
        if t is None or t.done():
            agent_session._tasks_by_child.pop(sid, None)
    return session_ids


def collect_session_subtree(
    sessions_dir: str,
    root_session_id: str,
) -> list[tuple[str, str]]:
    """Walk a single session's subtree on disk and return (sid, parent) pairs.

    Depth-first, root first. Used by the implicit-resume-on-message path
    to resume just the smallest subtree containing the message target,
    rather than the entire project (issue #403).
    """
    result: list[tuple[str, str]] = []

    def _walk(sid: str, parent: str) -> None:
        meta_path = os.path.join(sessions_dir, sid, 'metadata.json')
        if not os.path.isfile(meta_path):
            return
        try:
            with open(meta_path) as f:
                meta = json.load(f)
        except (json.JSONDecodeError, OSError):
            return
        result.append((sid, parent))
        for gc in meta.get('conversation_map', {}).values():
            _walk(gc, sid)

    # Look up the root's parent from its metadata so callers don't have
    # to pass it in.
    root_meta_path = os.path.join(
        sessions_dir, root_session_id, 'metadata.json')
    root_parent = ''
    if os.path.isfile(root_meta_path):
        try:
            with open(root_meta_path) as f:
                root_parent = json.load(f).get('parent_session_id', '')
        except (json.JSONDecodeError, OSError):
            pass
    _walk(root_session_id, root_parent)
    return result


# ── Resume ──────────────────────────────────────────────────────────────────

def _rebuild_task_for_session(
    sid: str,
    sessions_dir: str,
    agent_session: 'AgentSession',
) -> bool:
    """Rebuild a single session's task from its persisted phase.

    Returns True if a task was scheduled, False if skipped (missing
    metadata or no factory available for non-complete phase).
    """
    meta_path = os.path.join(sessions_dir, sid, 'metadata.json')
    try:
        with open(meta_path) as f:
            meta = json.load(f)
    except (json.JSONDecodeError, OSError):
        _log.warning('resume: cannot read metadata for %s', sid)
        return False
    phase = meta.get('phase', 'launching')

    if phase == 'complete':
        stored = meta.get('response_text', '')

        async def _completed_stub(text: str = stored) -> str:
            return text

        task = asyncio.create_task(_completed_stub())
        agent_session._tasks_by_child[sid] = task
        return True

    factory = agent_session._run_child_factories.get(sid)
    if factory is None:
        _log.warning(
            'resume: no factory for %s (phase=%s) — cross-restart '
            'resume is not implemented', sid, phase,
        )
        return False

    if phase == 'awaiting':
        gc_ids = list(meta.get('in_flight_gc_ids', []))
        coro = factory(
            start_at_phase='awaiting',
            initial_gc_task_ids=gc_ids,
            resume_claude_session=meta.get('claude_session_id', ''),
        )
    else:  # launching
        coro = factory(
            start_at_phase='launching',
            initial_gc_task_ids=None,
            resume_claude_session=meta.get('claude_session_id', ''),
        )
    task = asyncio.create_task(coro)
    agent_session._background_tasks.add(task)
    agent_session._tasks_by_child[sid] = task
    task.add_done_callback(agent_session._background_tasks.discard)
    return True


async def resume_session_subtree(
    root_session_id: str,
    sessions_dir: str,
    agent_session: 'AgentSession',
) -> list[str]:
    """Rebuild tasks for a single session and its descendants.

    Walks the subtree depth-first leaves-first so that when a parent's
    gather task runs, its grandchildren's tasks are already in
    ``_tasks_by_child``. Used by implicit-resume-on-message to resume
    only the smallest subtree containing the message target.
    """
    subtree = collect_session_subtree(sessions_dir, root_session_id)
    leaves_first = list(reversed(subtree))
    resumed: list[str] = []
    for sid, _parent in leaves_first:
        if _rebuild_task_for_session(sid, sessions_dir, agent_session):
            resumed.append(sid)
    return resumed


async def resume_project_subtree(
    project_slug: str,
    sessions_dir: str,
    agent_session: 'AgentSession',
) -> list[str]:
    """Rebuild tasks for every session in a paused project subtree.

    Walks depth-first leaves-first. For each session:
      - ``complete``: wrap a coroutine that returns the stored response_text.
        No LLM work.
      - ``awaiting``: re-enter the subtree loop at the gather step with the
        previously-captured grandchild ids. Skips _launch for this turn.
      - ``launching``: re-enter the loop from the top with the
        claude_session_id passed as resume_session. Claude replays via
        --resume; one turn regenerates.

    Returns the session ids whose tasks were re-scheduled.
    """
    subtree = collect_project_subtree(sessions_dir, project_slug)
    leaves_first = list(reversed(subtree))
    resumed: list[str] = []
    for sid, _parent in leaves_first:
        if _rebuild_task_for_session(sid, sessions_dir, agent_session):
            resumed.append(sid)
    return resumed
