"""Procedural learning — successful plans become reusable skills.

Implements the lifecycle described in docs/learning-system.md (Procedural
Learning) and docs/strategic-planning.md (Warm Start):

  1. archive_skill_candidate() — after a successful session, save the
     approved PLAN.md as a skill candidate with metadata.
  2. crystallize_skills() — periodically scan accumulated candidates,
     identify recurring patterns, and generalize them into reusable
     skill templates in the project's skills/ directory.

Skills produced by crystallization are consumed by skill_lookup.py
during the planning phase (System 1 warm-start fast path).

See: #101, #96
"""
from __future__ import annotations

import logging
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

_log = logging.getLogger('orchestrator')


# ── Skill candidate archival ─────────────────────────────────────────────────

def archive_skill_candidate(
    *,
    infra_dir: str = '',
    session_worktree: str = '',
    project_dir: str,
    task: str,
    session_id: str,
) -> bool:
    """Archive a successful session's PLAN.md as a skill candidate.

    Writes a copy of PLAN.md with YAML frontmatter to
    {project_dir}/skill-candidates/{session_id}.md.

    Returns True if a candidate was written, False if skipped (no PLAN.md).

    Reads PLAN.md from infra_dir (Issue #147).  Falls back to
    session_worktree for backward compatibility.
    """
    plan_path = os.path.join(infra_dir, 'PLAN.md') if infra_dir else ''
    if not plan_path or not os.path.isfile(plan_path):
        # Fallback to worktree for backward compat
        plan_path = os.path.join(session_worktree, 'PLAN.md') if session_worktree else ''
    if not os.path.isfile(plan_path):
        return False

    try:
        plan_content = Path(plan_path).read_text(errors='replace')
    except OSError:
        return False

    if not plan_content.strip():
        return False

    candidates_dir = os.path.join(project_dir, 'skill-candidates')
    os.makedirs(candidates_dir, exist_ok=True)

    timestamp = datetime.now().isoformat(timespec='seconds')

    # Build candidate with frontmatter
    candidate = (
        f'---\n'
        f'task: {task}\n'
        f'session_id: {session_id}\n'
        f'timestamp: {timestamp}\n'
        f'status: pending\n'
        f'---\n\n'
        f'{plan_content}'
    )

    out_path = os.path.join(candidates_dir, f'{session_id}.md')
    try:
        Path(out_path).write_text(candidate)
        _log.info('Archived skill candidate: %s', out_path)
        return True
    except OSError as exc:
        _log.warning('Failed to archive skill candidate: %s', exc)
        return False


# ── Skill crystallization ────────────────────────────────────────────────────

def crystallize_skills(
    *,
    project_dir: str,
    min_candidates: int = 3,
) -> int:
    """Identify recurring patterns across skill candidates and produce skill templates.

    Scans {project_dir}/skill-candidates/ for files with status=pending,
    groups them, and if enough similar candidates exist (>= min_candidates),
    calls _generalize_candidates() to produce a parameterized skill template.

    Writes produced skills to {project_dir}/skills/.
    Marks source candidates as status=processed.

    Returns the number of skills produced.
    """
    candidates_dir = os.path.join(project_dir, 'skill-candidates')
    if not os.path.isdir(candidates_dir):
        return 0

    # Load pending candidates
    pending = []
    for filename in sorted(os.listdir(candidates_dir)):
        if not filename.endswith('.md'):
            continue
        path = os.path.join(candidates_dir, filename)
        try:
            content = Path(path).read_text(errors='replace')
        except OSError:
            continue

        meta, body = _parse_candidate_frontmatter(content)
        if meta.get('status', '') != 'pending':
            continue

        pending.append({
            'path': path,
            'filename': filename,
            'meta': meta,
            'body': body,
            'content': content,
        })

    if len(pending) < min_candidates:
        return 0

    # For MVP, treat all pending candidates as one group.
    # Future: cluster by category/similarity before generalizing.
    candidates_text = '\n\n---\n\n'.join(
        f'### Candidate: {c["meta"].get("task", "unknown")}\n\n{c["body"]}'
        for c in pending
    )

    try:
        skill_content = _generalize_candidates(candidates_text)
    except Exception as exc:
        _log.warning('Skill crystallization failed: %s', exc)
        return 0

    if not skill_content or not skill_content.strip():
        return 0

    # Extract skill name from the generated content
    meta, _ = _parse_candidate_frontmatter(skill_content)
    skill_name = meta.get('name', f'skill-{datetime.now().strftime("%Y%m%d-%H%M%S")}')

    # Write the skill
    skills_dir = os.path.join(project_dir, 'skills')
    os.makedirs(skills_dir, exist_ok=True)

    # Sanitize filename
    safe_name = re.sub(r'[^a-z0-9-]', '-', skill_name.lower()).strip('-')
    skill_path = os.path.join(skills_dir, f'{safe_name}.md')
    try:
        Path(skill_path).write_text(skill_content)
        _log.info('Crystallized skill: %s', skill_path)
    except OSError as exc:
        _log.warning('Failed to write skill: %s', exc)
        return 0

    # Mark source candidates as processed
    for c in pending:
        _mark_candidate_processed(c['path'])

    return 1


def _generalize_candidates(candidates_text: str) -> str:
    """Call an LLM to generalize multiple plan candidates into a skill template.

    This is the LLM-dependent function — isolated for easy mocking in tests.

    Args:
        candidates_text: Concatenated plan candidates with metadata.

    Returns:
        A skill file with YAML frontmatter (name, description, category)
        and a parameterized workflow body.
    """
    prompt = (
        'You are analyzing multiple successful project plans that share a similar structure. '
        'Your task is to generalize them into a single reusable skill template.\n\n'
        'The output must be a markdown file with YAML frontmatter containing:\n'
        '- name: a short kebab-case identifier\n'
        '- description: one sentence describing the skill\n'
        '- category: the type of work (e.g., writing, coding, debugging)\n\n'
        'The body should be the generalized workflow with {parameter} placeholders '
        'for parts that vary between instances.\n\n'
        'Here are the successful plans to generalize:\n\n'
        f'{candidates_text}'
    )

    # Use the same subprocess pattern as summarize_session.py
    try:
        result = subprocess.run(
            ['claude', '--print', '-p', prompt],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as exc:
        _log.warning('LLM call for skill crystallization failed: %s', exc)

    return ''


# ── Internal helpers ─────────────────────────────────────────────────────────

def _parse_candidate_frontmatter(content: str) -> tuple[dict[str, str], str]:
    """Parse YAML-style frontmatter from a candidate file.

    Returns (metadata_dict, body_text). Same simple parsing as skill_lookup.py.
    """
    if not content.startswith('---'):
        return {}, content

    end = content.find('---', 3)
    if end == -1:
        return {}, content

    fm_text = content[3:end].strip()
    body = content[end + 3:].strip()

    meta: dict[str, str] = {}
    for line in fm_text.split('\n'):
        if ':' in line:
            key, _, value = line.partition(':')
            meta[key.strip()] = value.strip()

    return meta, body


def _mark_candidate_processed(path: str) -> None:
    """Update a candidate file's status from pending to processed."""
    try:
        content = Path(path).read_text(errors='replace')
    except OSError:
        return

    updated = content.replace('status: pending', 'status: processed', 1)
    if updated != content:
        try:
            Path(path).write_text(updated)
        except OSError:
            pass
