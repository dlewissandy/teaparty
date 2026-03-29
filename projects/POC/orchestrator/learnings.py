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

  In-flight signal generation (Issue #199):
    write_assumption_checkpoint() — appends structured JSONL at phase transitions
    write_premortem()             — generates .premortem.md from PLAN.md before execution
"""
from __future__ import annotations

import asyncio
import json as _json_mod
import logging
import os
import sys
import time as _time_mod

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

    # ── Intervention learning chunks (Issue #276) ──────────────────────────────

    await _run_scope(
        'interventions', _promote_interventions,
        infra_dir=infra_dir, project_dir=project_dir, scripts_dir=scripts_dir,
    )

    # ── Promotion evaluation (issue #217) ──────────────────────────────────────

    await _run_scope(
        'promotion-evaluation', _evaluate_promotions,
        infra_dir=infra_dir, project_dir=project_dir,
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

    # ── Friction event detection and sidecar (Issue #229) ──────────────────

    await _run_scope(
        'friction-detect', _detect_and_write_friction,
        infra_dir=infra_dir,
    )

    # ── Unified skill refinement: gate corrections + friction (Issue #229) ──
    # Replaces the separate skill-reflect (#146) and skill-friction-refine
    # steps with a single unified refinement that sends all signals
    # (corrections AND friction) to one LLM call.

    sidecar_path = os.path.join(infra_dir, '.active-skill.json')
    if os.path.isfile(sidecar_path):
        await _run_scope(
            'skill-refine', _refine_skill_unified,
            infra_dir=infra_dir,
            project_dir=project_dir,
        )

    # ── Within-scope learning consolidation (#245) ──────────────────────────

    await _run_scope(
        'task-consolidation', _consolidate_task_learnings,
        project_dir=project_dir,
    )

    # ── Proxy correction entry compaction (#198) ────────────────────────────

    await _run_scope(
        'proxy-correction-compact', _compact_proxy_correction_entries,
        project_dir=project_dir,
    )

    # ── Task and institutional contradiction consolidation (#244) ────────────

    await _run_scope(
        'learning-consolidation', _consolidate_task_and_institutional,
        project_dir=project_dir,
    )

    # ── Proxy contradiction consolidation (#228) ──────────────────────────────

    await _run_scope(
        'proxy-consolidation', _consolidate_proxy_memory,
        project_dir=project_dir,
    )

    # ── Proxy pattern compaction (#11) ────────────────────────────────────────

    await _run_scope(
        'proxy-patterns', _compact_proxy_patterns,
        project_dir=project_dir,
        log_path=os.path.join(project_dir, '.proxy-interactions.jsonl'),
        embed_fn=_make_embed_fn(),
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


def _promote_interventions(
    *,
    infra_dir: str,
    project_dir: str,
    scripts_dir: str,
) -> None:
    """Intervention chunks → project/proxy-tasks/<ts>-interventions.md.

    Reads .interventions.jsonl written in-flight by _deliver_intervention()
    and _check_interrupt_propagation(). Passes it as context to the
    interventions scope prompt so the LLM can extract proxy behavioral
    learnings about when the human intervened and what the agent did next.

    Issue #276.
    """
    interventions_file = os.path.join(infra_dir, '.interventions.jsonl')
    if not os.path.isfile(interventions_file) or os.path.getsize(interventions_file) == 0:
        return
    _call_promote(
        scripts_dir,
        'interventions',
        session_dir=infra_dir,
        project_dir=project_dir,
        output_dir='',
    )


# ── Promotion evaluation (issue #217) ─────────────────────────────────────────

def _evaluate_promotions(*, infra_dir: str, project_dir: str) -> None:
    """Evaluate session-scope learnings for promotion to project scope.

    Walks .sessions/*/tasks/ and .sessions/*/institutional.md under
    project_dir, finds learnings that recur across 3+ distinct sessions
    (via semantic similarity), excludes proxy learnings, and either:
    - promotes new entries to project/tasks/ with promotion metadata, or
    - reinforces existing project entries that match recurring patterns.
    """
    from pathlib import Path
    from datetime import date as _date
    from projects.POC.orchestrator.promotion import find_recurring_learnings
    from projects.POC.scripts.memory_entry import (
        serialize_entry, parse_memory_file, serialize_memory_file,
    )

    # Build similarity function: use embeddings if available, else exact match
    embed_fn = _make_embed_fn()
    if embed_fn is not None:
        from projects.POC.orchestrator.proxy_memory import cosine_similarity

        def _sim(a: str, b: str) -> float:
            va = embed_fn(a)
            vb = embed_fn(b)
            if va is None or vb is None:
                return 1.0 if a.strip().lower() == b.strip().lower() else 0.0
            return cosine_similarity(va, vb)

        similarity_fn = _sim
    else:
        similarity_fn = None  # use default exact match

    result = find_recurring_learnings(
        project_dir,
        min_recurrences=3,
        similarity_fn=similarity_fn,
    )

    from filelock import FileLock
    today = _date.today().isoformat()

    # Reinforce existing project entries that match recurring session patterns
    for reinforce_path in result.to_reinforce:
        lock = FileLock(reinforce_path + '.lock', timeout=10)
        with lock:
            try:
                text = Path(reinforce_path).read_text(errors='replace')
            except OSError:
                continue
            entries = parse_memory_file(text)
            if not entries:
                continue
            for entry in entries:
                entry.reinforcement_count += 1
                entry.last_reinforced = today
            try:
                Path(reinforce_path).write_text(serialize_memory_file(entries))
            except OSError:
                pass

    if result.to_reinforce:
        _log.info('Reinforced %d existing project entries.', len(result.to_reinforce))

    # Write promoted entries to project/tasks/
    if not result.to_promote:
        return

    tasks_dir = os.path.join(project_dir, 'tasks')
    os.makedirs(tasks_dir, exist_ok=True)

    for entry in result.to_promote:
        entry.promoted_from = 'session'
        entry.promoted_at = today
        fname = f'promoted-{entry.id}.md'
        fpath = os.path.join(tasks_dir, fname)
        lock = FileLock(fpath + '.lock', timeout=10)
        with lock:
            Path(fpath).write_text(serialize_entry(entry))

    _log.info('Promoted %d session learnings to project scope.', len(result.to_promote))


# ── Reinforcement tracking ────────────────────────────────────────────────────

def _reinforce_retrieved(*, infra_dir: str, project_dir: str) -> None:
    """Accuracy-aware reinforcement for entries retrieved at session start.

    Reads the .retrieved-ids.txt sidecar file (written by memory_indexer.retrieve)
    and compares each retrieved entry against the exec stream.  Entries whose
    content aligns with what the session actually did get reinforced (count +1);
    entries that were retrieved but show no alignment are left unchanged.

    Issue #199: upgraded from blind reinforcement to accuracy-aware.
    """
    from pathlib import Path
    from dataclasses import replace as _replace

    ids_path = os.path.join(infra_dir, '.retrieved-ids.txt')
    if not os.path.exists(ids_path):
        return

    from projects.POC.scripts.track_reinforcement import load_ids
    from projects.POC.scripts.memory_entry import parse_memory_file, serialize_memory_file

    retrieved_ids = load_ids(ids_path)
    if not retrieved_ids:
        return

    # Extract session outcome text from exec stream for alignment checking
    exec_stream_path = os.path.join(infra_dir, '.exec-stream.jsonl')
    session_text = _extract_session_text(exec_stream_path)

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
    from datetime import date as _date

    today = _date.today().isoformat()
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

            updated = []
            changed = False
            count = 0
            for entry in entries:
                if entry.id not in retrieved_ids or entry.status != 'active':
                    updated.append(entry)
                    continue

                # Accuracy check: does the entry's content align with what
                # the session actually did?
                if _is_aligned(entry.content, session_text):
                    updated.append(_replace(
                        entry,
                        reinforcement_count=entry.reinforcement_count + 1,
                        last_reinforced=today,
                    ))
                    count += 1
                    changed = True
                else:
                    # Not aligned — decrement with floor at 0 (Issue #199)
                    new_count = max(0, entry.reinforcement_count - 1)
                    if new_count != entry.reinforcement_count:
                        changed = True
                    updated.append(_replace(
                        entry,
                        reinforcement_count=new_count,
                    ))

            if changed:
                try:
                    Path(mem_path).write_text(serialize_memory_file(updated))
                    total_reinforced += count
                except OSError:
                    pass


def _extract_session_text(exec_stream_path: str) -> str:
    """Extract assistant text from the exec stream for alignment comparison.

    Returns a single string of all assistant text content, lowercased.
    Returns empty string if the stream doesn't exist or is empty.
    """
    if not os.path.isfile(exec_stream_path):
        return ''

    parts = []
    try:
        with open(exec_stream_path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    ev = _json_mod.loads(line)
                except (ValueError, _json_mod.JSONDecodeError):
                    continue
                if ev.get('type') != 'assistant':
                    continue
                for block in ev.get('message', {}).get('content', []):
                    if isinstance(block, dict) and block.get('type') == 'text':
                        text = block.get('text', '').strip()
                        if text:
                            parts.append(text)
    except OSError:
        return ''

    return '\n'.join(parts).lower()


def _is_aligned(entry_content: str, session_text: str) -> bool:
    """Check if a learning entry's content aligns with the session's work.

    Uses keyword overlap: extracts significant words (4+ chars) from the
    entry and checks if enough of them appear in the session text.
    A threshold of 30% keyword overlap indicates alignment.

    If there's no session text (empty exec stream), returns True to
    preserve backward compatibility (all retrieved entries reinforced).
    """
    if not session_text:
        # No exec stream — can't determine alignment; reinforce all
        return True

    # Extract significant words from the entry
    import re
    words = set(re.findall(r'[a-z]{4,}', entry_content.lower()))
    if not words:
        return True  # entry has no significant words — can't judge

    # Count how many appear in session text
    matches = sum(1 for w in words if w in session_text)
    overlap = matches / len(words)

    return overlap >= 0.3


# ── Procedural learning: skill candidate archival ────────────────────────────

def _archive_skill_candidate(
    *,
    infra_dir: str = '',
    session_worktree: str = '',
    project_dir: str,
    task: str,
    session_id: str,
) -> None:
    """Archive the session's PLAN.md as a skill candidate for procedural learning.

    If the session used a warm-start skill (.active-skill.json exists),
    reads the skill file's category and passes it through so the candidate
    inherits the seeding skill's category (Issue #239).
    """
    import json as _json

    # Read category from the active skill's file if available (Issue #239)
    category = ''
    sidecar_path = os.path.join(infra_dir, '.active-skill.json') if infra_dir else ''
    if sidecar_path and os.path.isfile(sidecar_path):
        try:
            with open(sidecar_path) as f:
                skill_info = _json.load(f)
            skill_path = skill_info.get('path', '')
            if skill_path and os.path.isfile(skill_path):
                from pathlib import Path as _Path
                from projects.POC.orchestrator.procedural_learning import _parse_candidate_frontmatter
                skill_content = _Path(skill_path).read_text(errors='replace')
                meta, _ = _parse_candidate_frontmatter(skill_content)
                category = meta.get('category', '')
        except (OSError, _json.JSONDecodeError, ValueError):
            pass

    from projects.POC.orchestrator.procedural_learning import archive_skill_candidate
    archive_skill_candidate(
        infra_dir=infra_dir,
        session_worktree=session_worktree,
        project_dir=project_dir,
        task=task,
        session_id=session_id,
        category=category,
    )


# ── Procedural learning: skill crystallization ────────────────────────────────

def _crystallize_skills(*, project_dir: str) -> None:
    """Attempt to crystallize accumulated skill candidates into reusable skills."""
    from projects.POC.orchestrator.procedural_learning import crystallize_skills
    crystallize_skills(project_dir=project_dir)


# ── Unified skill refinement: gate corrections + friction (Issue #229) ────────

def _reflect_on_skill_outcomes(*, infra_dir: str, project_dir: str) -> None:
    """Legacy entry point — delegates to _refine_skill_unified."""
    _refine_skill_unified(infra_dir=infra_dir, project_dir=project_dir)


def _refine_skill_unified(*, infra_dir: str, project_dir: str) -> None:
    """Unified skill refinement: gate corrections + friction events.

    Issue #229: Replaces the separate skill-reflect (#146) and
    skill-friction-refine steps.  Reads all available signals (gate
    outcomes from .proxy-interactions.jsonl AND friction events from
    .friction-events.json) and sends them to a single reflect_on_skill
    call.  Updates skill stats with all metrics (approval rate, friction
    counts, correction themes, sessions_since_refinement).
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
    session_id = skill_info.get('session_id', '')
    if not skill_name or not skill_path or not os.path.isfile(skill_path):
        return

    # ── Collect gate outcomes ─────────────────────────────────────────────
    corrections = []
    outcomes = []
    correction_deltas = []

    log_path = os.path.join(project_dir, '.proxy-interactions.jsonl')
    if os.path.isfile(log_path):
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
                    if session_id and entry.get('session_id') != session_id:
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
                        correction_deltas.append(entry['delta'])
        except OSError:
            pass

    # ── Collect friction events ───────────────────────────────────────────
    friction_events = []
    friction_path = os.path.join(infra_dir, '.friction-events.json')
    if os.path.isfile(friction_path):
        try:
            with open(friction_path) as f:
                friction_events = json.load(f)
        except (OSError, json.JSONDecodeError):
            pass

    # ── Unified refinement: single LLM call with all signals ─────────────
    was_refined = False
    if corrections or friction_events:
        was_refined = reflect_on_skill(
            skill_path=skill_path,
            corrections=corrections,
            friction_events=friction_events,
        )

    # ── Update all quality metrics ────────────────────────────────────────
    if outcomes or friction_events or was_refined:
        update_skill_stats(
            skill_path=skill_path,
            outcomes=outcomes,
            friction_events=friction_events,
            correction_deltas=correction_deltas,
            was_refined=was_refined,
        )


# ── Task and institutional contradiction consolidation (#244) ─────────────────

def _read_already_decayed(log_path: str) -> set[str]:
    """Read prior consolidation log to find entry IDs already decayed.

    Prevents compounding importance reduction across sessions.
    """
    import json as _json

    already_decayed: set[str] = set()
    if not os.path.isfile(log_path):
        return already_decayed
    try:
        with open(log_path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    d = _json.loads(line)
                except _json.JSONDecodeError:
                    continue
                if d.get('action') == 'PRESERVE_BOTH_DECAYED':
                    already_decayed.add(d.get('entry_a', ''))
                    already_decayed.add(d.get('entry_b', ''))
    except OSError:
        pass
    already_decayed.discard('')
    return already_decayed


def _consolidate_scope(
    scope_dir: str,
    *,
    already_decayed: set[str],
) -> tuple[int, list[dict]]:
    """Consolidate task and institutional learnings at a single scope directory.

    Returns (total_removed, all_decisions).
    """
    from projects.POC.orchestrator.learning_consolidation import (
        consolidate_learning_file,
        consolidate_institutional_file,
    )

    total_removed = 0
    all_decisions: list[dict] = []

    # Consolidate task learnings
    tasks_dir = os.path.join(scope_dir, 'tasks')
    if os.path.isdir(tasks_dir):
        removed, decisions = consolidate_learning_file(
            tasks_dir, already_decayed_ids=already_decayed,
        )
        total_removed += removed
        all_decisions.extend(decisions)

    # Consolidate institutional learnings
    inst_path = os.path.join(scope_dir, 'institutional.md')
    if os.path.isfile(inst_path):
        removed, decisions = consolidate_institutional_file(
            inst_path, already_decayed_ids=already_decayed,
        )
        total_removed += removed
        all_decisions.extend(decisions)

    return total_removed, all_decisions


def _consolidate_task_and_institutional(*, project_dir: str) -> None:
    """Run contradiction consolidation on task and institutional learnings.

    Consolidates at two scopes:
    - Project scope: project_dir/tasks/ and project_dir/institutional.md
    - Global scope: projects_dir/tasks/ and projects_dir/institutional.md

    Reads prior consolidation log to avoid compounding importance reduction
    across sessions. Writes new decisions to the log for auditability.
    """
    import json as _json

    log_path = os.path.join(project_dir, '.learning-consolidation-log.jsonl')
    already_decayed = _read_already_decayed(log_path)

    total_removed = 0
    all_decisions: list[dict] = []

    # ── Project scope ──────────────────────────────────────────────────────
    removed, decisions = _consolidate_scope(
        project_dir, already_decayed=already_decayed,
    )
    total_removed += removed
    all_decisions.extend(decisions)

    # ── Global scope ───────────────────────────────────────────────────────
    # Global learnings are promoted to the parent of project_dir (projects/).
    global_dir = os.path.dirname(project_dir)
    if global_dir and os.path.isdir(global_dir) and global_dir != project_dir:
        # Read global-scope log separately (different scope, different log)
        global_log = os.path.join(global_dir, '.learning-consolidation-log.jsonl')
        global_decayed = _read_already_decayed(global_log)

        g_removed, g_decisions = _consolidate_scope(
            global_dir, already_decayed=global_decayed,
        )
        total_removed += g_removed

        if g_decisions:
            from filelock import FileLock
            lock = FileLock(global_log + '.lock', timeout=10)
            with lock:
                try:
                    with open(global_log, 'a') as f:
                        for d in g_decisions:
                            f.write(_json.dumps(d) + '\n')
                except OSError:
                    pass

    # Write project-scope decisions
    if all_decisions:
        from filelock import FileLock
        lock = FileLock(log_path + '.lock', timeout=10)
        with lock:
            try:
                with open(log_path, 'a') as f:
                    for d in all_decisions:
                        f.write(_json.dumps(d) + '\n')
            except OSError:
                pass

    if total_removed:
        _log.info(
            'Learning consolidation: removed %d entries (%d decisions)',
            total_removed, len(all_decisions),
        )


# ── Proxy contradiction consolidation (#228) ─────────────────────────────────

def _consolidate_proxy_memory(*, project_dir: str) -> None:
    """Run contradiction consolidation on proxy.md (the always-loaded
    preferential store) and on the ACT-R memory DB.

    Two targets:

    1. proxy.md — YAML-frontmattered MemoryEntry objects containing human
       preference observations. Parsed, consolidated via
       consolidate_proxy_file() with ADD/UPDATE/DELETE/SKIP taxonomy,
       and rewritten atomically.

    2. ACT-R chunk DB — episodic gate interaction chunks. Consolidated
       via consolidate_proxy_entries() to remove superseded chunks
       (preference_drift → DELETE older).

    This is separate from compact_entries() and does not modify the
    existing compaction pipeline.
    """
    from filelock import FileLock
    from pathlib import Path

    # ── Stage 2a: proxy.md consolidation ────────────────────────────────────

    proxy_md_path = os.path.join(project_dir, 'proxy.md')
    if os.path.isfile(proxy_md_path):
        try:
            from projects.POC.scripts.memory_entry import (
                parse_memory_file,
                serialize_memory_file,
            )
            from projects.POC.orchestrator.proxy_memory import consolidate_proxy_file
            from projects.POC.orchestrator.proxy_agent import (
                _classify_conflict_llm_for_entries,
            )

            lock = FileLock(proxy_md_path + '.lock', timeout=30)
            with lock:
                text = Path(proxy_md_path).read_text(errors='replace')
                entries = parse_memory_file(text)
                if len(entries) >= 2:
                    # Use LLM classifier for proxy.md consolidation.
                    # Falls back to ADD (preserve both) on any failure.
                    consolidated, decisions = consolidate_proxy_file(
                        entries,
                        classifier=_classify_conflict_llm_for_entries,
                    )
                    if len(consolidated) < len(entries):
                        output = serialize_memory_file(consolidated)
                        # Atomic write
                        import tempfile
                        fd, tmp = tempfile.mkstemp(
                            dir=os.path.dirname(os.path.abspath(proxy_md_path)),
                            suffix='.tmp',
                        )
                        try:
                            with os.fdopen(fd, 'w') as f:
                                f.write(output)
                                if output and not output.endswith('\n'):
                                    f.write('\n')
                            os.replace(tmp, proxy_md_path)
                        except Exception:
                            try:
                                os.unlink(tmp)
                            except OSError:
                                pass
                            raise
                        _log.info(
                            'Proxy consolidation: proxy.md %d → %d entries (%d decisions)',
                            len(entries), len(consolidated), len(decisions),
                        )

                        # Write consolidation log for auditability
                        if decisions:
                            import json as _json
                            log_path = os.path.join(project_dir, '.proxy-consolidation-log.jsonl')
                            with open(log_path, 'a') as f:
                                for d in decisions:
                                    f.write(_json.dumps(d) + '\n')
        except Exception:
            _log.debug('proxy.md consolidation failed', exc_info=True)

    # ── Stage 2b: ACT-R chunk DB consolidation ──────────────────────────────

    from projects.POC.orchestrator.proxy_memory import (
        open_proxy_db,
        consolidate_proxy_entries,
        get_interaction_counter,
        soft_delete_chunk,
        purge_deleted_chunks,
    )
    import glob as glob_mod

    db_pattern = os.path.join(project_dir, '.proxy-memory*.db')
    db_paths = glob_mod.glob(db_pattern)

    for db_path in db_paths:
        try:
            conn = open_proxy_db(db_path)
        except Exception:
            continue
        try:
            current = get_interaction_counter(conn)

            # Purge chunks that were soft-deleted long enough ago (issue #236)
            purged = purge_deleted_chunks(conn, current_interaction=current)
            if purged:
                _log.info(
                    'Proxy consolidation: purged %d old soft-deleted chunks from %s',
                    purged, db_path,
                )

            rows = conn.execute(
                'SELECT id, type, state, task_type, outcome, traces, '
                'posterior_confidence FROM proxy_chunks '
                'WHERE deleted_at IS NULL'
            ).fetchall()
            if len(rows) < 2:
                continue

            from projects.POC.orchestrator.proxy_memory import MemoryChunk
            import json as _json

            chunks = []
            for row in rows:
                chunks.append(MemoryChunk(
                    id=row[0], type=row[1], state=row[2],
                    task_type=row[3], outcome=row[4],
                    traces=_json.loads(row[5]) if row[5] else [],
                    posterior_confidence=row[6] or 0.0,
                    content='',
                ))

            consolidated = consolidate_proxy_entries(chunks, current_interaction=current)
            consolidated_ids = {c.id for c in consolidated}
            deleted_ids = {c.id for c in chunks} - consolidated_ids

            if deleted_ids:
                for chunk_id in deleted_ids:
                    soft_delete_chunk(conn, chunk_id, interaction=current)
                _log.info(
                    'Proxy consolidation: soft-deleted %d superseded chunks from %s',
                    len(deleted_ids), db_path,
                )
        except Exception:
            _log.debug('Proxy consolidation failed for %s', db_path, exc_info=True)
        finally:
            conn.close()


# ── Within-scope learning consolidation (#245) ──────────────────────────────

def _consolidate_task_learnings(*, project_dir: str) -> None:
    """Consolidate duplicate/overlapping entries in task-based stores.

    Runs consolidate_task_store() on both tasks/ and proxy-tasks/ directories
    under project_dir.  Uses embeddings when available, falls back to Jaccard
    token similarity.
    """
    from projects.POC.orchestrator.consolidate_learnings import (
        consolidate_task_store,
        lexical_similarity,
    )

    embed_fn = _make_embed_fn()
    if embed_fn is not None:
        from projects.POC.orchestrator.proxy_memory import cosine_similarity

        def _sim(a: str, b: str) -> float:
            va = embed_fn(a)
            vb = embed_fn(b)
            if va is None or vb is None:
                return lexical_similarity(a, b)
            return cosine_similarity(va, vb)

        similarity_fn = _sim
    else:
        _log.info(
            'No embedding provider available; consolidation will use '
            'lexical similarity only (degraded mode)',
        )
        similarity_fn = None  # use default lexical_similarity

    for subdir in ('tasks', 'proxy-tasks'):
        store_dir = os.path.join(project_dir, subdir)
        if os.path.isdir(store_dir):
            result = consolidate_task_store(store_dir, similarity_fn=similarity_fn)
            if result.merged_count > 0:
                _log.info(
                    'Consolidated %s: %d → %d entries',
                    subdir, result.original_count, result.final_count,
                )


# ── Proxy correction entry compaction (#198) ─────────────────────────────────

def _compact_proxy_correction_entries(*, project_dir: str) -> None:
    """Compact proxy correction entries in proxy-tasks/.

    Proxy corrections are emitted inline during approval gates (_proxy_record
    in actors.py) as individual YAML-frontmattered markdown files. Over time,
    these accumulate.  This step applies the standard compaction pipeline
    (dedup by ID, merge similar entries, drop retired) to keep the directory
    manageable and retrieval quality high.
    """
    proxy_tasks_dir = os.path.join(project_dir, 'proxy-tasks')
    if not os.path.isdir(proxy_tasks_dir):
        return

    from pathlib import Path
    from filelock import FileLock

    # Only compact correction entries (not other proxy-tasks files)
    correction_files = sorted(
        f for f in os.listdir(proxy_tasks_dir)
        if f.startswith('correction-') and f.endswith('.md')
    )
    if len(correction_files) < 2:
        return  # nothing to compact

    from projects.POC.scripts.memory_entry import parse_memory_file, serialize_memory_file
    from projects.POC.scripts.compact_memory import compact_entries

    # Read all correction entries
    all_entries = []
    for fname in correction_files:
        fpath = os.path.join(proxy_tasks_dir, fname)
        lock = FileLock(fpath + '.lock', timeout=10)
        with lock:
            try:
                text = Path(fpath).read_text(errors='replace')
            except OSError:
                continue
            entries = parse_memory_file(text)
            all_entries.extend(entries)

    if not all_entries:
        return

    # Compact
    compacted = compact_entries(all_entries)
    if len(compacted) >= len(all_entries):
        return  # nothing was removed

    # Remove old correction files (and their lock files) and write compacted entries
    for fname in correction_files:
        fpath = os.path.join(proxy_tasks_dir, fname)
        try:
            os.remove(fpath)
        except OSError:
            pass
        lock_path = fpath + '.lock'
        try:
            os.remove(lock_path)
        except OSError:
            pass

    for entry in compacted:
        fname = f'correction-{entry.id}.md'
        fpath = os.path.join(proxy_tasks_dir, fname)
        from projects.POC.scripts.memory_entry import serialize_entry
        Path(fpath).write_text(serialize_entry(entry))


# ── Proxy pattern compaction (#11) ────────────────────────────────────────────


def _make_embed_fn():
    """Build an embedding function from memory_indexer, or return None if unavailable."""
    try:
        from projects.POC.scripts.memory_indexer import try_embed, detect_provider
        provider, model = detect_provider()
        if provider == 'none':
            return None

        def _embed(text: str) -> list[float] | None:
            return try_embed(text, provider=provider, model=model)
        return _embed
    except Exception:
        return None


# ── Friction event detection and sidecar (Issue #229) ─────────────────────────

def _detect_and_write_friction(*, infra_dir: str) -> None:
    """Detect friction events from the execution stream and write sidecar.

    Scans .exec-stream.jsonl for operational friction patterns and writes
    the results to .friction-events.json in the infra dir.
    """
    import json

    stream_path = os.path.join(infra_dir, '.exec-stream.jsonl')
    if not os.path.isfile(stream_path):
        return

    from projects.POC.orchestrator.procedural_learning import detect_friction_events
    events = detect_friction_events(stream_path)

    if not events:
        return

    sidecar_path = os.path.join(infra_dir, '.friction-events.json')
    try:
        with open(sidecar_path, 'w') as f:
            json.dump(events, f)
        _log.info('Wrote %d friction events to %s', len(events), sidecar_path)
    except OSError as exc:
        _log.warning('Failed to write friction events sidecar: %s', exc)


CLUSTER_SIMILARITY_THRESHOLD = 0.85


def _cluster_deltas_semantic(
    deltas: list[str],
    embed_fn,
) -> list[tuple[str, int]]:
    """Cluster deltas by embedding similarity, return (representative, count) pairs.

    Uses single-linkage clustering: a delta joins an existing cluster if its
    cosine similarity to any member exceeds CLUSTER_SIMILARITY_THRESHOLD.
    The longest delta in each cluster is chosen as the representative.
    """
    from projects.POC.orchestrator.proxy_memory import cosine_similarity

    # Embed all deltas; pair each with its vector
    embedded: list[tuple[str, list[float] | None]] = []
    for d in deltas:
        vec = embed_fn(d.strip())
        embedded.append((d.strip(), vec))

    # clusters: list of (members, vectors)
    clusters: list[tuple[list[str], list[list[float] | None]]] = []

    for text, vec in embedded:
        if vec is None:
            # Can't compare — treat as its own cluster
            clusters.append(([text], [vec]))
            continue

        merged = False
        for members, vecs in clusters:
            for existing_vec in vecs:
                if existing_vec is None:
                    continue
                if cosine_similarity(vec, existing_vec) >= CLUSTER_SIMILARITY_THRESHOLD:
                    members.append(text)
                    vecs.append(vec)
                    merged = True
                    break
            if merged:
                break

        if not merged:
            clusters.append(([text], [vec]))

    # For each cluster: longest member as representative, len as frequency
    results = []
    for members, _ in clusters:
        representative = max(members, key=len)
        results.append((representative, len(members)))
    return results


def _cluster_deltas_exact(deltas: list[str]) -> list[tuple[str, int]]:
    """Cluster deltas by case-insensitive exact match, return (representative, count) pairs."""
    groups: dict[str, list[str]] = {}
    order: list[str] = []
    for d in deltas:
        key = d.strip().lower()
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(d.strip())

    results = []
    for key in order:
        members = groups[key]
        representative = max(members, key=len)
        results.append((representative, len(members)))
    return results


def _compact_proxy_patterns(
    *,
    project_dir: str,
    log_path: str,
    embed_fn=None,
) -> None:
    """Extract recurring proxy correction patterns from the interaction log.

    Groups interactions by state, clusters semantically equivalent deltas
    (using embedding similarity when embed_fn is provided, falling back to
    case-insensitive exact match otherwise), tracks frequency, and writes
    distilled patterns to proxy-patterns.md.
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
        if embed_fn is not None:
            clusters = _cluster_deltas_semantic(deltas, embed_fn)
        else:
            clusters = _cluster_deltas_exact(deltas)
        for representative, count in clusters:
            lines.append(f'- {representative} (×{count})\n')
        lines.append('\n')

    patterns_path = os.path.join(project_dir, 'proxy-patterns.md')
    from filelock import FileLock
    lock = FileLock(patterns_path + '.lock', timeout=30)
    with lock:
        Path(patterns_path).write_text(''.join(lines))


# ── In-flight signal generation (Issue #199) ─────────────────────────────────

def write_assumption_checkpoint(
    *,
    infra_dir: str,
    phase: str,
    cfa_state: str,
    artifact_summary: str,
) -> None:
    """Append a structured assumption checkpoint to .assumptions.jsonl.

    Called at CfA phase transitions.  The post-session ``_promote_in_flight``
    pipeline reads this file as context and passes it to Haiku via the
    ``in-flight`` prompt template, which expects entries shaped like::

        {"milestone": "...", "timestamp": "...",
         "assumptions": {"complexity": "...", "approach_viability": "...",
                         "preference_model": "...", "scope": "..."},
         "recommendation": "..."}

    The ``artifact_summary`` should contain the actual artifact content
    (INTENT.md or PLAN.md text) so the downstream LLM has real signal.
    Assumptions are inferred from the phase boundary context.
    """
    from datetime import datetime as _dt

    entry = {
        'milestone': f'{phase} phase completed ({cfa_state})',
        'timestamp': _dt.now().isoformat(),
        'assumptions': {
            'complexity': (artifact_summary[:500] if artifact_summary
                          else f'{phase} completed'),
            'approach_viability': (
                f'{phase} approach approved at gate'
                if cfa_state in ('INTENT', 'PLAN')
                else 'in progress'
            ),
            'preference_model': (
                'human-approved'
                if cfa_state in ('INTENT', 'PLAN')
                else 'proxy-predicted'
            ),
            'scope': artifact_summary[:200] if artifact_summary else 'not captured',
        },
        'recommendation': 'continue',
    }

    path = os.path.join(infra_dir, '.assumptions.jsonl')
    with open(path, 'a') as f:
        f.write(_json_mod.dumps(entry) + '\n')


def write_premortem(
    *,
    infra_dir: str,
    task: str,
) -> None:
    """Generate .premortem.md from PLAN.md content before execution begins.

    The premortem captures assumptions the plan rests on and risks that
    could cause it to fail.  The post-session ``_promote_prospective``
    pipeline reads this file and promotes it into project-level task learnings.

    Overwrites any existing .premortem.md (handles plan correction/backtrack).
    """
    from pathlib import Path

    plan_path = os.path.join(infra_dir, 'PLAN.md')
    if not os.path.isfile(plan_path):
        return

    try:
        plan_content = Path(plan_path).read_text(errors='replace')
    except OSError:
        return

    if not plan_content.strip():
        return

    # The premortem is the plan content framed as a pre-execution snapshot.
    # The downstream ``prospective`` prompt template compares this against
    # the exec stream to identify which risks materialized, which were
    # missed, and which were false alarms.  No LLM call here — the plan
    # content IS the primary input; the analysis happens post-session.
    from datetime import date as _date

    premortem = (
        f'# Pre-Mortem: {task}\n\n'
        f'Generated: {_date.today().isoformat()}\n\n'
        f'## Plan\n\n'
        f'{plan_content}\n'
    )

    premortem_path = os.path.join(infra_dir, '.premortem.md')
    Path(premortem_path).write_text(premortem)


# ── Intervention learning chunk I/O (Issue #276) ──────────────────────────────

def write_intervention_chunk(
    *,
    infra_dir: str,
    content: str,
    senders: list,
    cfa_state: str,
    phase: str,
) -> None:
    """Append a structured intervention chunk to .interventions.jsonl.

    Called by _deliver_intervention() at turn boundaries immediately after
    draining the intervention queue. The chunk captures the intervention
    content plus the CfA context at the moment of delivery.

    A matching outcome record is appended later by write_intervention_outcome()
    once _check_interrupt_propagation() determines how the agent responded.

    Issue #276.
    """
    from datetime import datetime as _dt

    entry = {
        'type': 'intervention',
        'timestamp': _dt.now().isoformat(),
        'content': content,
        'senders': list(senders),
        'cfa_state': cfa_state,
        'phase': phase,
        'outcome': 'pending',
    }
    path = os.path.join(infra_dir, '.interventions.jsonl')
    with open(path, 'a') as f:
        f.write(_json_mod.dumps(entry) + '\n')


def write_intervention_outcome(
    *,
    infra_dir: str,
    outcome: str,
    backtrack_phase: str = '',
) -> None:
    """Append an outcome record to .interventions.jsonl.

    Called by _check_interrupt_propagation() once the orchestrator has
    determined how the agent responded to the most recently delivered
    intervention: continue, backtrack, or withdraw.

    The outcome record is paired with the preceding intervention chunk
    by sequential ordering in the file. The post-session
    _promote_interventions() pipeline reads both records together to
    extract proxy behavioral learnings about human intervention signals.

    Issue #276.
    """
    from datetime import datetime as _dt

    entry: dict = {
        'type': 'intervention_outcome',
        'timestamp': _dt.now().isoformat(),
        'outcome': outcome,
    }
    if backtrack_phase:
        entry['backtrack_phase'] = backtrack_phase

    path = os.path.join(infra_dir, '.interventions.jsonl')
    with open(path, 'a') as f:
        f.write(_json_mod.dumps(entry) + '\n')
