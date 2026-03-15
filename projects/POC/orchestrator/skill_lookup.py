"""Skill lookup — dual-process routing for planning.

Implements the System 1 / System 2 routing decision: before entering
cold-start planning, check if a learned skill already covers this
task category.  If so, seed the planning conversation with the skill
template (warm start).  If not, proceed with bespoke planning (cold start).

Skills are markdown files with YAML-style frontmatter stored in a
project's skills/ directory.  They are the output of procedural
learning — generalized from plans that worked.

See: docs/learning-system.md (Procedural Learning)
     docs/strategic-planning.md (Warm Start)
"""
from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass

_log = logging.getLogger('orchestrator')


@dataclass
class SkillMatch:
    """A skill matched from the library."""
    name: str
    path: str
    description: str
    score: float
    template: str


def lookup_skill(
    task: str,
    intent: str,
    skills_dir: str,
    threshold: float = 0.15,
) -> SkillMatch | None:
    """Search the skill library for a matching skill.

    Args:
        task: The task description.
        intent: The approved intent (INTENT.md content).
        skills_dir: Path to the skills directory.
        threshold: Minimum score to consider a match.

    Returns:
        Best matching SkillMatch if above threshold, else None.
    """
    if not os.path.isdir(skills_dir):
        return None

    task_tokens = _tokenize(task)
    intent_tokens = _tokenize(intent)

    best: SkillMatch | None = None
    best_score = 0.0

    for filename in os.listdir(skills_dir):
        if not filename.endswith('.md'):
            continue
        path = os.path.join(skills_dir, filename)
        if not os.path.isfile(path):
            continue

        try:
            meta, body = _parse_frontmatter(path)
        except Exception:
            _log.debug('Skipping malformed skill file: %s', path)
            continue

        name = meta.get('name', filename[:-3])
        description = meta.get('description', '')
        category = meta.get('category', '')

        skill_text = f'{name} {description} {category}'
        skill_tokens = _tokenize(skill_text)

        score = _score(task_tokens, intent_tokens, skill_tokens)

        if score > best_score:
            best_score = score
            best = SkillMatch(
                name=name,
                path=path,
                description=description,
                score=score,
                template=body,
            )

    if best and best.score >= threshold:
        return best
    return None


# ── Internal helpers ──────────────────────────────────────────────────────────


def _tokenize(text: str) -> set[str]:
    """Extract lowercase word tokens (2+ chars) from text."""
    return set(re.findall(r'[a-z][a-z0-9]+', text.lower()))


def _parse_frontmatter(path: str) -> tuple[dict[str, str], str]:
    """Parse YAML-style frontmatter from a skill markdown file.

    Returns (metadata_dict, body_text).  Keeps parsing simple:
    flat key: value pairs only, consistent with the project's
    memory_entry.py approach.
    """
    with open(path) as f:
        content = f.read()

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


def _score(
    task_tokens: set[str],
    intent_tokens: set[str],
    skill_tokens: set[str],
) -> float:
    """Score a skill against task + intent using Jaccard similarity."""
    query_tokens = task_tokens | intent_tokens
    if not query_tokens or not skill_tokens:
        return 0.0
    intersection = query_tokens & skill_tokens
    union = query_tokens | skill_tokens
    return len(intersection) / len(union) if union else 0.0
