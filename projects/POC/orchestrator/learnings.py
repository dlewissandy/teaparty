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
import logging
import os
import sys

_log = logging.getLogger('orchestrator.learnings')


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

    # ── Procedural learning: archive successful plan as skill candidate ──────

    await _run_scope(
        'skill-archive', _archive_skill_candidate,
        infra_dir=infra_dir,
        session_worktree=session_worktree,
        project_dir=project_dir,
        task=task,
        session_id=os.path.basename(infra_dir),
    )

    # ── Procedural learning: crystallize accumulated candidates into skills ──

    await _run_scope(
        'skill-crystallize', _crystallize_skills,
        project_dir=project_dir,
    )

    # ── Skill reflection: apply gate corrections to skill template (#146) ───

    sidecar_path = os.path.join(infra_dir, '.active-skill.json')
    if os.path.isfile(sidecar_path):
        await _run_scope(
            'skill-reflect', _reflect_on_skill_outcomes,
            infra_dir=infra_dir,
            project_dir=project_dir,
        )

    # ── Proxy pattern compaction (#11) ────────────────────────────────────────

    await _run_scope(
        'proxy-patterns', _compact_proxy_patterns,
        project_dir=project_dir,
        log_path=os.path.join(project_dir, '.proxy-interactions.jsonl'),
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

    from filelock import FileLock

    lock = FileLock(output + '.lock', timeout=30)
    added_to_path = False
    try:
        if scripts_dir and scripts_dir not in sys.path:
            sys.path.insert(0, scripts_dir)
            added_to_path = True
        from summarize_session import summarize
        with lock:
            summarize(stream_path, output, [], scope)
    except Exception as exc:
        _log.warning('%s extraction failed: %s', scope, exc)
    finally:
        if added_to_path:
            try:
                sys.path.remove(scripts_dir)
            except ValueError:
                pass


# ── Rollup scope helpers ───────────────────────────────────────────────────────

def _call_promote(scripts_dir: str, scope: str, **kwargs) -> None:
    """Call summarize_session.promote() directly (importable API)."""
    from filelock import FileLock

    # Determine the output directory to lock on. promote() writes to
    # institutional.md and tasks/ within the target directory.
    lock_dir = kwargs.get('output_dir') or kwargs.get('project_dir') or kwargs.get('session_dir', '')
    lock_path = os.path.join(lock_dir, f'.promote-{scope}.lock') if lock_dir else ''

    added_to_path = False
    try:
        if scripts_dir and scripts_dir not in sys.path:
            sys.path.insert(0, scripts_dir)
            added_to_path = True
        from summarize_session import promote
        if lock_path:
            lock = FileLock(lock_path, timeout=30)
            with lock:
                promote(scope, **kwargs)
        else:
            promote(scope, **kwargs)
    except Exception as exc:
        _log.warning('promote %s failed: %s', scope, exc)
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

    from filelock import FileLock

    total_reinforced = 0
    for mem_path in memory_files:
        lock = FileLock(mem_path + '.lock', timeout=30)
        with lock:
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


# ── Procedural learning: skill candidate archival ────────────────────────────

def _archive_skill_candidate(
    *,
    infra_dir: str = '',
    session_worktree: str = '',
    project_dir: str,
    task: str,
    session_id: str,
) -> None:
    """Archive the session's PLAN.md as a skill candidate for procedural learning."""
    from projects.POC.orchestrator.procedural_learning import archive_skill_candidate
    archive_skill_candidate(
        infra_dir=infra_dir,
        session_worktree=session_worktree,
        project_dir=project_dir,
        task=task,
        session_id=session_id,
    )


# ── Procedural learning: skill crystallization ────────────────────────────────

def _crystallize_skills(*, project_dir: str) -> None:
    """Attempt to crystallize accumulated skill candidates into reusable skills."""
    from projects.POC.orchestrator.procedural_learning import crystallize_skills
    crystallize_skills(project_dir=project_dir)


# ── Skill reflection: gate outcomes as reward signal (#146) ──────────────────

def _reflect_on_skill_outcomes(*, infra_dir: str, project_dir: str) -> None:
    """Apply gate correction deltas to the skill that produced the plan.

    Reads .active-skill.json (written by engine on skill match) and
    .proxy-interactions.jsonl to find gate outcomes scoped to that skill.
    Calls reflect_on_skill() to apply corrections and update_skill_stats()
    to track approval rates.
    """
    import json
    from projects.POC.orchestrator.procedural_learning import (
        reflect_on_skill,
        update_skill_stats,
    )

    sidecar_path = os.path.join(infra_dir, '.active-skill.json')
    try:
        with open(sidecar_path) as f:
            skill_info = json.load(f)
    except (OSError, json.JSONDecodeError):
        return

    skill_name = skill_info.get('name', '')
    skill_path = skill_info.get('path', '')
    if not skill_name or not skill_path or not os.path.isfile(skill_path):
        return

    # Read gate outcomes from the interaction log, scoped to this skill
    log_path = os.path.join(project_dir, '.proxy-interactions.jsonl')
    if not os.path.isfile(log_path):
        return

    corrections = []
    outcomes = []
    try:
        with open(log_path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if entry.get('skill_name') != skill_name:
                    continue
                outcome = entry.get('outcome', '')
                if outcome:
                    outcomes.append(outcome)
                if outcome == 'correct' and entry.get('delta'):
                    corrections.append({
                        'state': entry.get('state', ''),
                        'outcome': outcome,
                        'delta': entry['delta'],
                    })
    except OSError:
        return

    # Apply corrections to skill template (if any)
    if corrections:
        reflect_on_skill(skill_path=skill_path, corrections=corrections)

    # Update skill stats with all outcomes
    if outcomes:
        update_skill_stats(skill_path=skill_path, outcomes=outcomes)


# ── Proxy pattern compaction (#11) ────────────────────────────────────────────

def _compact_proxy_patterns(*, project_dir: str, log_path: str) -> None:
    """Extract recurring proxy correction patterns from the interaction log.

    Groups interactions by state, identifies recurring deltas (corrections
    the human makes repeatedly), and writes distilled patterns to
    proxy-patterns.md.  This is the compaction step that converts raw
    interaction history into actionable proxy behavioral knowledge.
    """
    from pathlib import Path
    import json
    from collections import defaultdict

    if not os.path.isfile(log_path):
        return

    # Read all interactions
    interactions = []
    try:
        with open(log_path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    interactions.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except OSError:
        return

    if not interactions:
        return

    # Group corrections by state
    corrections_by_state = defaultdict(list)
    for entry in interactions:
        if entry.get('outcome') in ('correct', 'reject') and entry.get('delta'):
            corrections_by_state[entry.get('state', 'unknown')].append(entry['delta'])

    if not corrections_by_state:
        return

    # Build patterns file — recurring corrections become proxy patterns
    lines = ['# Proxy Behavioral Patterns\n']
    lines.append('Extracted from proxy interaction history. These represent\n')
    lines.append('recurring human corrections that the proxy should anticipate.\n\n')

    for state, deltas in sorted(corrections_by_state.items()):
        lines.append(f'## {state}\n\n')
        # Deduplicate similar deltas (simple exact match for now)
        seen = []
        for d in deltas:
            d_lower = d.strip().lower()
            if d_lower not in [s.lower() for s in seen]:
                seen.append(d.strip())
        for d in seen:
            lines.append(f'- {d}\n')
        lines.append('\n')

    patterns_path = os.path.join(project_dir, 'proxy-patterns.md')
    from filelock import FileLock
    lock = FileLock(patterns_path + '.lock', timeout=30)
    with lock:
        Path(patterns_path).write_text(''.join(lines))
