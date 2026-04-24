"""Phase-completion learning hooks — what the engine fires at phase boundaries.

The CfA engine triggers learning at two specific moments:

1. **After a planning phase completes normally** — if the plan came
   from a skill template and the planner / proxy diverged from it,
   archive the corrected plan as a skill-correction candidate so the
   procedural-learning pipeline can promote good corrections.
2. **At the planning → execution boundary** — generate a premortem
   from the freshly-approved PLAN.md so the post-session prospective-
   extraction pipeline has input.

Both used to live as private methods on ``Orchestrator``.  The engine's
job is to *fire* the hook at the right moment; *what to write*, *where
to write it*, *which frontmatter to read* are learning-system concerns
and live here.

Each function is best-effort by design: a learning failure must not
abort a CfA session.  Errors are caught + logged + swallowed.  The
boolean return on ``archive_skill_correction`` lets the engine clear
its ``_active_skill`` state when the skill has been consumed.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

_log = logging.getLogger('teaparty.learning.phase_hooks')


def archive_skill_correction(
    *,
    active_skill: dict | None,
    session_worktree: str,
    infra_dir: str,
    project_workdir: str,
    task: str,
    session_id: str,
) -> bool:
    """Archive a corrected skill-derived plan when one is detected.

    The CfA engine calls this after a planning phase completes normally
    (not on backtrack, not on infra-failure).  When the plan came from
    a skill template — recorded in ``active_skill`` at planning entry
    — and the current ``PLAN.md`` differs from that template, the
    correction is archived as a candidate the procedural-learning
    pipeline can later promote into an updated skill.

    Returns ``True`` when an archive was attempted (regardless of
    outcome).  The engine uses this to know whether to clear its
    ``_active_skill`` slot — a consumed skill should not influence
    later phases.

    Returns ``False`` when there was nothing to do — no active skill,
    no PLAN.md on disk, or the plan still matches the template.

    Args:
        active_skill: The engine's recorded active skill, populated
            when planning starts from a skill template.  Must contain
            ``name``, ``template``, and (optionally) ``path``.  Pass
            ``None`` when no skill was active — the function returns
            ``False`` immediately.
        session_worktree: Where ``PLAN.md`` lives.
        infra_dir: Session infra dir (passed through to the candidate
            archiver as the source of session state).
        project_workdir: Project repo root (used by the candidate
            archiver to locate the project's skill registry).
        task: The original session task (archived alongside the
            candidate so the curator has context).
        session_id: Tagged onto the candidate id with a
            ``-correction`` suffix to distinguish corrections from
            ordinary skill candidates.
    """
    if not active_skill:
        return False

    plan_path = os.path.join(session_worktree, 'PLAN.md')
    if not os.path.isfile(plan_path):
        return False

    try:
        with open(plan_path) as f:
            current_plan = f.read()
    except OSError:
        return False

    original_template = active_skill.get('template', '')
    if current_plan.strip() == original_template.strip():
        # Plan unchanged from the skill template — no correction.
        # Leave ``active_skill`` alone (caller decides), nothing to
        # archive.
        return False

    skill_name = active_skill['name']
    skill_path = active_skill.get('path', '')

    skill_category = ''
    if skill_path and os.path.isfile(skill_path):
        try:
            from teaparty.learning.procedural.learning import (
                _parse_candidate_frontmatter,
            )
            skill_content = Path(skill_path).read_text(errors='replace')
            skill_meta, _ = _parse_candidate_frontmatter(skill_content)
            skill_category = skill_meta.get('category', '')
        except OSError:
            pass

    try:
        from teaparty.learning.procedural.learning import (
            archive_skill_candidate,
        )
        archived = archive_skill_candidate(
            infra_dir=infra_dir,
            project_dir=project_workdir,
            task=task,
            session_id=f'{session_id}-correction',
            corrects_skill=skill_name,
            category=skill_category,
        )
        if archived:
            _log.info(
                'Archived corrected plan as skill correction candidate '
                'for skill %s', skill_name,
            )
    except Exception as exc:
        _log.warning('Failed to archive skill correction: %s', exc)

    # The skill has been consumed — caller should clear its
    # ``active_skill`` slot regardless of archive success.  An archive
    # failure is logged but doesn't change the fact that the plan
    # diverged from the template.
    return True


def try_write_premortem(*, infra_dir: str, task: str) -> None:
    """Write a premortem for the next phase, swallowing errors.

    Called at the planning → execution boundary so the prospective-
    extraction pipeline has a premortem to work with.  Any failure
    (missing PLAN.md, LLM unreachable, write error) is logged and
    swallowed — premortem generation must not abort a CfA session.
    """
    try:
        from teaparty.learning.extract import write_premortem
        write_premortem(infra_dir=infra_dir, task=task)
    except Exception as exc:
        _log.warning('Premortem generation failed (non-fatal): %s', exc)
