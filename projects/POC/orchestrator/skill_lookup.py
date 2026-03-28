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
from typing import Callable

_log = logging.getLogger('orchestrator')


@dataclass
class SkillMatch:
    """A skill matched from the library."""
    name: str
    path: str
    description: str
    score: float
    template: str
    scope: str = 'project'


def lookup_skill(
    task: str,
    intent: str,
    skills_dir: str = '',
    threshold: float = 0.15,
    skills_dirs: list[tuple[str, str]] | None = None,
    embed_fn: Callable[[str], list[float] | None] | None = None,
) -> SkillMatch | None:
    """Search the skill library for a matching skill.

    Supports two modes:

    **Single directory** (backward compatible): pass ``skills_dir``.
    **Scoped directories** (Issue #196): pass ``skills_dirs`` — a list of
    ``(scope_name, path)`` tuples ordered from narrowest to broadest scope.
    A skill name that appears at a narrower scope shadows the same name at
    a broader scope (name-based override).

    Args:
        task: The task description.
        intent: The approved intent (INTENT.md content).
        skills_dir: Path to a single skills directory (legacy).
        threshold: Minimum score to consider a match.
        skills_dirs: Scope-ordered skill directories, narrowest first.

    Returns:
        Best matching SkillMatch if above threshold, else None.
    """
    # Normalize into a unified list of (scope, path) tuples.
    if skills_dirs is not None:
        dirs = skills_dirs
    elif skills_dir:
        dirs = [('project', skills_dir)]
    else:
        return None

    # Determine scoring mode: embedding or Jaccard fallback.
    # Embedding mode: embed the query once, embed each skill, cosine similarity.
    # Jaccard mode: tokenize and compute set overlap (legacy).
    use_embeddings = False
    query_embedding: list[float] | None = None
    if embed_fn is not None:
        query_text = f'{task} {intent}'
        try:
            query_embedding = embed_fn(query_text)
        except Exception:
            _log.debug('embed_fn failed for query, falling back to Jaccard')
        if query_embedding is not None:
            use_embeddings = True

    if use_embeddings:
        effective_threshold = max(threshold, 0.5)
    else:
        effective_threshold = threshold

    task_tokens = _tokenize(task) if not use_embeddings else set()
    intent_tokens = _tokenize(intent) if not use_embeddings else set()

    # Collect all skills, applying name-based override: narrower scope wins.
    # skills_dirs is ordered narrowest-first, so first occurrence of a name wins.
    seen_names: set[str] = set()
    candidates: list[SkillMatch] = []

    for scope, dirpath in dirs:
        if not os.path.isdir(dirpath):
            continue

        for filename in os.listdir(dirpath):
            if not filename.endswith('.md'):
                continue
            path = os.path.join(dirpath, filename)
            if not os.path.isfile(path):
                continue

            try:
                meta, body = _parse_frontmatter(path)
            except Exception:
                _log.debug('Skipping malformed skill file: %s', path)
                continue

            # Skip degraded skills flagged for review (Issue #229)
            if meta.get('needs_review', '').lower() == 'true':
                _log.debug('Skipping degraded skill: %s (needs_review=true)', filename)
                continue

            name = meta.get('name', filename[:-3])

            # Name-based override: skip if a narrower scope already claimed this name
            if name in seen_names:
                continue
            seen_names.add(name)

            description = meta.get('description', '')
            category = meta.get('category', '')

            skill_text = f'{name} {description} {category}'

            if use_embeddings:
                score = _score_embedding(
                    query_embedding, skill_text, embed_fn,
                )
            else:
                skill_tokens = _tokenize(skill_text)
                score = _score(task_tokens, intent_tokens, skill_tokens)

            candidates.append(SkillMatch(
                name=name,
                path=path,
                description=description,
                score=score,
                template=body,
                scope=scope,
            ))

    if not candidates:
        return None

    best = max(candidates, key=lambda c: c.score)
    if best.score >= effective_threshold:
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
    """Score a skill against task + intent using Jaccard similarity (fallback)."""
    query_tokens = task_tokens | intent_tokens
    if not query_tokens or not skill_tokens:
        return 0.0
    intersection = query_tokens & skill_tokens
    union = query_tokens | skill_tokens
    return len(intersection) / len(union) if union else 0.0


def _score_embedding(
    query_vec: list[float],
    skill_text: str,
    embed_fn: Callable[[str], list[float] | None],
) -> float:
    """Score a skill against the query using cosine similarity of embeddings."""
    from projects.POC.orchestrator.proxy_memory import cosine_similarity

    try:
        skill_vec = embed_fn(skill_text)
    except Exception:
        return 0.0
    if skill_vec is None:
        return 0.0
    return cosine_similarity(query_vec, skill_vec)
