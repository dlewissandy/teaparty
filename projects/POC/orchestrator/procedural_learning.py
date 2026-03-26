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
    corrects_skill: str = '',
) -> bool:
    """Archive a successful session's PLAN.md as a skill candidate.

    Writes a copy of PLAN.md with YAML frontmatter to
    {project_dir}/skill-candidates/{session_id}.md.

    Returns True if a candidate was written, False if skipped (no PLAN.md).

    Reads PLAN.md from infra_dir (Issue #147).  Falls back to
    session_worktree for backward compatibility.

    If corrects_skill is provided, the candidate is tagged as a correction
    of the named skill (Issue #142 — skill self-correction on backtrack).
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
    corrects_line = f'corrects_skill: {corrects_skill}\n' if corrects_skill else ''
    candidate = (
        f'---\n'
        f'task: {task}\n'
        f'session_id: {session_id}\n'
        f'timestamp: {timestamp}\n'
        f'status: pending\n'
        f'{corrects_line}'
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


# ── Skill reflection — gate outcomes as reward signal (Issue #146) ───────────

# Approval rate below this threshold triggers needs_review flag
_NEEDS_REVIEW_THRESHOLD = 0.5


def reflect_on_skill(
    *,
    skill_path: str,
    corrections: list[dict],
) -> bool:
    """Apply gate correction deltas to a skill template.

    Reads the current skill, sends it plus the correction deltas to an LLM,
    and writes the updated skill back.  Returns True if the skill was updated.

    If corrections is empty or the LLM returns empty, returns False and
    preserves the original skill file.
    """
    if not corrections:
        return False

    if not os.path.isfile(skill_path):
        return False

    try:
        original = Path(skill_path).read_text(errors='replace')
    except OSError:
        return False

    updated = _apply_corrections_to_skill(original, corrections)

    if not updated or not updated.strip():
        return False

    # Validate the updated skill has frontmatter
    meta, body = _parse_candidate_frontmatter(updated)
    if not meta.get('name') or not body.strip():
        _log.warning('Reflect pass produced invalid skill — preserving original')
        return False

    try:
        Path(skill_path).write_text(updated)
        _log.info('Reflected %d corrections into skill: %s',
                  len(corrections), skill_path)
        return True
    except OSError as exc:
        _log.warning('Failed to write reflected skill: %s', exc)
        return False


def update_skill_stats(
    *,
    skill_path: str,
    outcomes: list[str],
) -> None:
    """Update a skill's frontmatter with approval stats from gate outcomes.

    Tracks: uses (total), approval_rate, corrections count.
    Sets needs_review=true when approval_rate drops below threshold.
    Accumulates across calls — reads prior stats from existing frontmatter.
    """
    if not outcomes or not os.path.isfile(skill_path):
        return

    try:
        content = Path(skill_path).read_text(errors='replace')
    except OSError:
        return

    meta, body = _parse_candidate_frontmatter(content)

    # Accumulate from prior stats
    prior_uses = int(meta.get('uses', '0'))
    prior_approvals = round(float(meta.get('approval_rate', '1.0')) * prior_uses)
    prior_corrections = int(meta.get('corrections', '0'))

    new_approvals = sum(1 for o in outcomes if o == 'approve')
    new_corrections = sum(1 for o in outcomes if o == 'correct')

    total_uses = prior_uses + len(outcomes)
    total_approvals = prior_approvals + new_approvals
    total_corrections = prior_corrections + new_corrections
    approval_rate = total_approvals / total_uses if total_uses > 0 else 1.0

    # Update frontmatter
    meta['uses'] = str(total_uses)
    meta['approval_rate'] = f'{approval_rate:.2f}'
    meta['corrections'] = str(total_corrections)

    if approval_rate < _NEEDS_REVIEW_THRESHOLD:
        meta['needs_review'] = 'true'
    elif 'needs_review' in meta:
        del meta['needs_review']

    # Rebuild file
    updated = _rebuild_skill_file(meta, body)
    try:
        Path(skill_path).write_text(updated)
    except OSError:
        pass


def _apply_corrections_to_skill(
    skill_content: str,
    corrections: list[dict],
) -> str:
    """Call an LLM to apply correction deltas to a skill template.

    Isolated for easy mocking in tests (same pattern as _generalize_candidates).
    """
    corrections_text = '\n'.join(
        f'- [{c.get("state", "?")}] {c.get("delta", "")}'
        for c in corrections
        if c.get('delta')
    )

    prompt = (
        'You are updating a reusable skill template based on human corrections '
        'from approval gates. Apply the corrections to improve the template.\n\n'
        'IMPORTANT: Preserve the YAML frontmatter (name, description, category). '
        'Only modify the workflow body to incorporate the corrections. '
        'Return the complete updated skill file including frontmatter.\n\n'
        '## Current Skill Template\n\n'
        f'{skill_content}\n\n'
        '## Corrections to Apply\n\n'
        f'{corrections_text}\n'
    )

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
        _log.warning('LLM call for skill reflection failed: %s', exc)

    return ''


def _rebuild_skill_file(meta: dict[str, str], body: str) -> str:
    """Rebuild a skill file from parsed frontmatter and body."""
    fm_lines = ['---']
    for key, value in meta.items():
        fm_lines.append(f'{key}: {value}')
    fm_lines.append('---')
    fm_lines.append('')
    return '\n'.join(fm_lines) + body + '\n'


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


# ── Friction event detection (Issue #229) ─────────────────────────────────────

# Patterns that indicate operational friction in agent output
_PERMISSION_DENIED_PATTERNS = (
    'permission denied',
    'Permission denied',
    'blocked',
    'not permitted',
    'access denied',
)

_FILE_NOT_FOUND_PATTERNS = (
    'No such file or directory',
    'not found',
    'FileNotFoundError',
    'does not exist',
)

_FALLBACK_RETRY_PATTERNS = (
    'try a different approach',
    'let me try',
    'alternative approach',
    'try another',
    'instead, ',
    'falling back',
)


def detect_friction_events(stream_path: str) -> list[dict]:
    """Scan a stream JSONL file for operational friction patterns.

    Detects three categories of friction:
    - permission_denied: tool calls or commands that were blocked
    - file_not_found: searches for files that don't exist
    - fallback_retry: errors followed by the agent trying a different approach

    Returns a list of dicts with 'category' and 'detail' keys.
    """
    import json as _json

    if not os.path.isfile(stream_path):
        return []

    events: list[dict] = []
    lines: list[dict] = []

    try:
        with open(stream_path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    lines.append(_json.loads(line))
                except _json.JSONDecodeError:
                    continue
    except OSError:
        return []

    prev_was_error = False
    prev_error_detail = ''

    for entry in lines:
        text = ''
        entry_type = entry.get('type', '')

        # Extract text content from the entry
        if entry_type == 'result':
            text = str(entry.get('result', ''))
        elif entry_type == 'assistant':
            msg = entry.get('message', {})
            content = msg.get('content', [])
            if isinstance(content, list):
                text = ' '.join(
                    c.get('text', '') for c in content
                    if isinstance(c, dict) and c.get('type') == 'text'
                )

        if not text:
            prev_was_error = False
            continue

        # Check for permission denied
        if any(pat in text for pat in _PERMISSION_DENIED_PATTERNS):
            events.append({
                'category': 'permission_denied',
                'detail': text[:200],
            })
            prev_was_error = True
            prev_error_detail = text[:200]
            continue

        # Check for file not found
        if any(pat in text for pat in _FILE_NOT_FOUND_PATTERNS):
            events.append({
                'category': 'file_not_found',
                'detail': text[:200],
            })
            prev_was_error = True
            prev_error_detail = text[:200]
            continue

        # Check for fallback retry (error on previous line, retry language on this line)
        if prev_was_error and any(pat in text.lower() for pat in _FALLBACK_RETRY_PATTERNS):
            events.append({
                'category': 'fallback_retry',
                'detail': f'After error: {prev_error_detail[:100]} → {text[:100]}',
            })
            prev_was_error = False
            continue

        # Check if this line itself is an error (for next-line fallback detection)
        if entry_type == 'result' and ('error' in text.lower() or 'Error' in text):
            prev_was_error = True
            prev_error_detail = text[:200]
        else:
            prev_was_error = False

    return events


# ── Friction-aware skill refinement (Issue #229) ──────────────────────────────

# Threshold: flag skill for review when average friction per session exceeds this
_FRICTION_PER_SESSION_THRESHOLD = 3.0


def refine_skill_with_friction(
    *,
    skill_path: str,
    friction_events: list[dict],
) -> bool:
    """Refine a skill template based on friction events from execution.

    Reads the current skill, sends it plus friction event descriptions to an
    LLM, and writes the updated skill back.  Returns True if the skill was
    updated.

    Same pattern as reflect_on_skill — guards against empty input, LLM
    failure, and invalid output.
    """
    if not friction_events:
        return False

    if not os.path.isfile(skill_path):
        return False

    try:
        original = Path(skill_path).read_text(errors='replace')
    except OSError:
        return False

    updated = _apply_friction_to_skill(original, friction_events)

    if not updated or not updated.strip():
        return False

    # Validate the updated skill has frontmatter
    meta, body = _parse_candidate_frontmatter(updated)
    if not meta.get('name') or not body.strip():
        _log.warning('Friction refinement produced invalid skill — preserving original')
        return False

    try:
        Path(skill_path).write_text(updated)
        _log.info('Refined skill with %d friction events: %s',
                  len(friction_events), skill_path)
        return True
    except OSError as exc:
        _log.warning('Failed to write friction-refined skill: %s', exc)
        return False


def _apply_friction_to_skill(
    skill_content: str,
    friction_events: list[dict],
) -> str:
    """Call an LLM to apply friction event learnings to a skill template.

    Isolated for easy mocking in tests (same pattern as _apply_corrections_to_skill).
    """
    friction_text = '\n'.join(
        f'- [{e.get("category", "?")}] {e.get("detail", "")}'
        for e in friction_events
        if e.get('detail')
    )

    prompt = (
        'You are updating a reusable skill template based on operational friction '
        'observed during execution. These friction events indicate where the skill\'s '
        'instructions were incomplete — the agent had to figure things out the hard way.\n\n'
        'Improve the template to prevent recurrence:\n'
        '- Add explicit file paths so agents don\'t search blindly\n'
        '- Provide example commands so agents don\'t guess syntax\n'
        '- Specify permission requirements upfront\n'
        '- Add notes about common pitfalls\n\n'
        'IMPORTANT: Preserve the YAML frontmatter (name, description, category). '
        'Only modify the workflow body. Return the complete updated skill file.\n\n'
        '## Current Skill Template\n\n'
        f'{skill_content}\n\n'
        '## Friction Events to Address\n\n'
        f'{friction_text}\n'
    )

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
        _log.warning('LLM call for friction refinement failed: %s', exc)

    return ''


def update_skill_friction_stats(
    *,
    skill_path: str,
    friction_events: list[dict],
) -> None:
    """Update a skill's frontmatter with friction event counts.

    Tracks: friction_events_total (cumulative).
    Sets needs_review=true when average friction per session exceeds threshold.
    Accumulates across calls — reads prior stats from existing frontmatter.
    """
    if not friction_events or not os.path.isfile(skill_path):
        return

    try:
        content = Path(skill_path).read_text(errors='replace')
    except OSError:
        return

    meta, body = _parse_candidate_frontmatter(content)

    # Accumulate from prior stats
    prior_friction = int(meta.get('friction_events_total', '0'))
    total_friction = prior_friction + len(friction_events)
    total_uses = int(meta.get('uses', '1'))  # at least 1 (this session)

    meta['friction_events_total'] = str(total_friction)

    # Flag for review if average friction per session is too high
    avg_friction = total_friction / max(total_uses, 1)
    if avg_friction >= _FRICTION_PER_SESSION_THRESHOLD:
        meta['needs_review'] = 'true'

    updated = _rebuild_skill_file(meta, body)
    try:
        Path(skill_path).write_text(updated)
    except OSError:
        pass


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
