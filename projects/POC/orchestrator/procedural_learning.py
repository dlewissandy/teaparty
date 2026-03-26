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
    category: str = '',
) -> bool:
    """Archive a successful session's PLAN.md as a skill candidate.

    Writes a copy of PLAN.md with YAML frontmatter to
    {project_dir}/skill-candidates/{session_id}.md.

    Returns True if a candidate was written, False if skipped (no PLAN.md).

    Reads PLAN.md from infra_dir (Issue #147).  Falls back to
    session_worktree for backward compatibility.

    If category is provided, it is written to frontmatter so
    _cluster_candidates() can group by category instead of falling back
    to Jaccard similarity (Issue #239).

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
    category_line = f'category: {category}\n' if category else ''
    corrects_line = f'corrects_skill: {corrects_skill}\n' if corrects_skill else ''
    candidate = (
        f'---\n'
        f'task: {task}\n'
        f'session_id: {session_id}\n'
        f'timestamp: {timestamp}\n'
        f'status: pending\n'
        f'{category_line}'
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

    # Cluster candidates by similarity before generalizing (Issue #234).
    clusters = _cluster_candidates(pending)

    skills_produced = 0
    skills_dir = os.path.join(project_dir, 'skills')

    for cluster in clusters:
        if len(cluster) < min_candidates:
            continue

        candidates_text = '\n\n---\n\n'.join(
            f'### Candidate: {c["meta"].get("task", "unknown")}\n\n{c["body"]}'
            for c in cluster
        )

        try:
            skill_content = _generalize_candidates(candidates_text)
        except Exception as exc:
            _log.warning('Skill crystallization failed for cluster: %s', exc)
            continue

        if not skill_content or not skill_content.strip():
            continue

        # Extract skill name from the generated content
        meta, _ = _parse_candidate_frontmatter(skill_content)
        skill_name = meta.get('name', f'skill-{datetime.now().strftime("%Y%m%d-%H%M%S")}')

        # Write the skill
        os.makedirs(skills_dir, exist_ok=True)

        # Sanitize filename
        safe_name = re.sub(r'[^a-z0-9-]', '-', skill_name.lower()).strip('-')
        skill_path = os.path.join(skills_dir, f'{safe_name}.md')
        try:
            Path(skill_path).write_text(skill_content)
            _log.info('Crystallized skill: %s', skill_path)
        except OSError as exc:
            _log.warning('Failed to write skill: %s', exc)
            continue

        # Mark source candidates in this cluster as processed
        for c in cluster:
            _mark_candidate_processed(c['path'])

        skills_produced += 1

    return skills_produced


def _cluster_candidates(
    candidates: list[dict],
    similarity_threshold: float = 0.2,
) -> list[list[dict]]:
    """Group candidates into coherent clusters for independent generalization.

    Clustering strategy:
    1. Candidates with a 'category' field are grouped by category.
    2. Candidates without category are clustered by task description
       similarity (Jaccard on tokens, single-linkage).

    Category is a first-class concept in the skill schema (produced by
    crystallization, used by skill_lookup scoring).  Warm-start candidates
    carry forward the seeding skill's category (Issue #239); cold-start
    candidates lack category and use the similarity fallback.

    Returns a list of clusters, where each cluster is a list of candidate dicts.
    """
    by_category: dict[str, list[dict]] = {}
    for c in candidates:
        cat = c['meta'].get('category', '').strip().lower()
        by_category.setdefault(cat, []).append(c)

    clusters: list[list[dict]] = []

    for cat, group in by_category.items():
        if cat:
            clusters.append(group)
        else:
            clusters.extend(
                _cluster_by_task_similarity(group, similarity_threshold)
            )

    return clusters


def _cluster_by_task_similarity(
    candidates: list[dict],
    threshold: float,
) -> list[list[dict]]:
    """Cluster candidates by task description similarity.

    Uses single-linkage clustering: a candidate joins an existing cluster
    if its task tokens have Jaccard similarity >= threshold with any member.
    """
    tokenized = [
        (c, set(re.findall(r'[a-z][a-z0-9]+', c['meta'].get('task', '').lower())))
        for c in candidates
    ]

    clusters: list[list[tuple[dict, set[str]]]] = []

    for candidate, tokens in tokenized:
        merged = False
        for cluster in clusters:
            for _, cluster_tokens in cluster:
                union = tokens | cluster_tokens
                if not union:
                    continue
                jaccard = len(tokens & cluster_tokens) / len(union)
                if jaccard >= threshold:
                    cluster.append((candidate, tokens))
                    merged = True
                    break
            if merged:
                break

        if not merged:
            clusters.append([(candidate, tokens)])

    return [[c for c, _ in cluster] for cluster in clusters]


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

# Approval rate below this threshold triggers needs_review flag.
# Issue #229: 70% over recent uses, matching the issue specification.
_NEEDS_REVIEW_THRESHOLD = 0.7


def reflect_on_skill(
    *,
    skill_path: str,
    corrections: list[dict] | None = None,
    friction_events: list[dict] | None = None,
) -> bool:
    """Refine a skill template using all available signals.

    Accepts gate correction deltas AND/OR friction events from execution.
    Sends all signals to a single LLM call so the refinement is coherent.
    Returns True if the skill was updated.

    Issue #229: Unified refinement replaces the separate reflect pass (#146)
    and friction refinement into a single mechanism.
    """
    corrections = corrections or []
    friction_events = friction_events or []

    if not corrections and not friction_events:
        return False

    if not os.path.isfile(skill_path):
        return False

    try:
        original = Path(skill_path).read_text(errors='replace')
    except OSError:
        return False

    updated = _apply_signals_to_skill(original, corrections, friction_events)

    if not updated or not updated.strip():
        return False

    # Validate the updated skill has frontmatter
    meta, body = _parse_candidate_frontmatter(updated)
    if not meta.get('name') or not body.strip():
        _log.warning('Reflect pass produced invalid skill — preserving original')
        return False

    try:
        Path(skill_path).write_text(updated)
        _log.info('Reflected %d corrections + %d friction events into skill: %s',
                  len(corrections), len(friction_events), skill_path)
        return True
    except OSError as exc:
        _log.warning('Failed to write reflected skill: %s', exc)
        return False


def update_skill_stats(
    *,
    skill_path: str,
    outcomes: list[str] | None = None,
    friction_events: list[dict] | None = None,
    correction_deltas: list[str] | None = None,
    was_refined: bool = False,
) -> None:
    """Update a skill's frontmatter with quality metrics from a session.

    Tracks (Issue #229 — per-skill quality monitoring):
    - uses: total session count
    - approval_rate: fraction of gate outcomes that were approvals
    - corrections: total correction count
    - correction_themes: recurring correction deltas (count >= 3)
    - friction_events_total: cumulative friction event count
    - friction_by_category: per-category friction counts (JSON)
    - sessions_since_refinement: sessions since last LLM refinement (resets on refine)

    Sets needs_review=true when:
    - approval_rate drops below 70% (issue spec)
    - average friction per session exceeds threshold
    - correction themes repeat 3+ times (refinement isn't working)
    """
    outcomes = outcomes or []
    friction_events = friction_events or []
    correction_deltas = correction_deltas or []

    if not outcomes and not friction_events and not was_refined:
        return

    if not os.path.isfile(skill_path):
        return

    try:
        content = Path(skill_path).read_text(errors='replace')
    except OSError:
        return

    meta, body = _parse_candidate_frontmatter(content)

    # ── Gate outcome stats ────────────────────────────────────────────────

    prior_uses = int(meta.get('uses', '0'))
    prior_approvals = round(float(meta.get('approval_rate', '1.0')) * prior_uses)
    prior_corrections = int(meta.get('corrections', '0'))

    new_approvals = sum(1 for o in outcomes if o == 'approve')
    new_corrections = sum(1 for o in outcomes if o == 'correct')

    total_uses = prior_uses + len(outcomes)
    total_approvals = prior_approvals + new_approvals
    total_corrections = prior_corrections + new_corrections
    approval_rate = total_approvals / total_uses if total_uses > 0 else 1.0

    meta['uses'] = str(total_uses)
    meta['approval_rate'] = f'{approval_rate:.2f}'
    meta['corrections'] = str(total_corrections)

    # ── Friction stats (Issue #229) ───────────────────────────────────────

    prior_friction = int(meta.get('friction_events_total', '0'))
    total_friction = prior_friction + len(friction_events)
    meta['friction_events_total'] = str(total_friction)

    # Per-category friction breakdown
    import json as _json
    try:
        prior_by_cat = _json.loads(meta.get('friction_by_category', '{}'))
    except (_json.JSONDecodeError, TypeError):
        prior_by_cat = {}

    for event in friction_events:
        cat = event.get('category', 'unknown')
        prior_by_cat[cat] = prior_by_cat.get(cat, 0) + 1

    if prior_by_cat:
        meta['friction_by_category'] = _json.dumps(prior_by_cat)

    # ── Correction theme tracking (Issue #229) ────────────────────────────

    try:
        prior_themes = _json.loads(meta.get('correction_themes', '{}'))
    except (_json.JSONDecodeError, TypeError):
        prior_themes = {}

    for delta in correction_deltas:
        # Normalize theme key: lowercase, first 80 chars
        theme_key = delta.strip().lower()[:80]
        if theme_key:
            prior_themes[theme_key] = prior_themes.get(theme_key, 0) + 1

    if prior_themes:
        meta['correction_themes'] = _json.dumps(prior_themes)

    # ── Sessions since refinement (Issue #229) ────────────────────────────

    if was_refined:
        meta['sessions_since_refinement'] = '0'
    else:
        prior_since = int(meta.get('sessions_since_refinement', '0'))
        meta['sessions_since_refinement'] = str(prior_since + 1)

    # ── Flag for review (Issue #229 — quality monitoring thresholds) ──────

    needs_review = False

    # Approval rate below 70%
    if total_uses > 0 and approval_rate < _NEEDS_REVIEW_THRESHOLD:
        needs_review = True

    # Average friction per session too high
    avg_friction = total_friction / max(total_uses, 1)
    if avg_friction >= _FRICTION_PER_SESSION_THRESHOLD:
        needs_review = True

    # Correction themes repeating 3+ times (refinement isn't working)
    if any(count >= 3 for count in prior_themes.values()):
        needs_review = True

    if needs_review:
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
    """Legacy wrapper — delegates to _apply_signals_to_skill.

    Preserved for backward compatibility with existing tests (#146).
    """
    return _apply_signals_to_skill(skill_content, corrections, [])


def _apply_signals_to_skill(
    skill_content: str,
    corrections: list[dict],
    friction_events: list[dict],
) -> str:
    """Call an LLM to apply gate corrections AND friction signals to a skill.

    Issue #229: Unified refinement — a single LLM call receives both types
    of signal so the refinement is coherent.  Replaces the separate
    _apply_corrections_to_skill (gate only) and _apply_friction_to_skill
    (friction only) with one pass.

    Isolated for easy mocking in tests.
    """
    sections = []

    if corrections:
        corrections_text = '\n'.join(
            f'- [{c.get("state", "?")}] {c.get("delta", "")}'
            for c in corrections
            if c.get('delta')
        )
        sections.append(
            '## Gate Corrections\n'
            'Human corrections from approval gates:\n\n'
            f'{corrections_text}'
        )

    if friction_events:
        friction_text = '\n'.join(
            f'- [{e.get("category", "?")}] {e.get("detail", "")}'
            for e in friction_events
            if e.get('detail')
        )
        sections.append(
            '## Execution Friction\n'
            'Operational friction observed during execution:\n\n'
            f'{friction_text}'
        )

    if not sections:
        return ''

    signals_block = '\n\n'.join(sections)

    prompt = (
        'You are updating a reusable skill template based on feedback from execution.\n\n'
        'Two types of signal may be present:\n'
        '- **Gate corrections**: Human corrections at approval gates — the plan was wrong.\n'
        '- **Execution friction**: Operational friction during execution — the plan was right '
        'but the instructions were incomplete (agent searched blindly for files, guessed at '
        'syntax, hit permission errors the skill could have warned about).\n\n'
        'Improve the template to incorporate corrections and prevent friction recurrence:\n'
        '- Apply gate corrections directly (the human said what to change)\n'
        '- Add explicit file paths so agents don\'t search blindly\n'
        '- Provide example commands so agents don\'t guess syntax\n'
        '- Specify permission requirements upfront\n'
        '- Add notes about common pitfalls\n\n'
        'IMPORTANT: Preserve the YAML frontmatter (name, description, category). '
        'Only modify the workflow body. Return the complete updated skill file.\n\n'
        '## Current Skill Template\n\n'
        f'{skill_content}\n\n'
        f'{signals_block}\n'
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
        _log.warning('LLM call for skill refinement failed: %s', exc)

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
    """Refine a skill template based on friction events.

    Delegates to reflect_on_skill (the unified refinement mechanism).
    Kept as a named entry point so callers don't need to know about
    the unification.
    """
    return reflect_on_skill(skill_path=skill_path, friction_events=friction_events)


def update_skill_friction_stats(
    *,
    skill_path: str,
    friction_events: list[dict],
) -> None:
    """Update a skill's frontmatter with friction event counts.

    Delegates to update_skill_stats (the unified stats function).
    Kept as a named entry point for backward compatibility.
    """
    update_skill_stats(skill_path=skill_path, friction_events=friction_events)


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
