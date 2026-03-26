"""Learning promotion chain: recurrence detection, proxy exclusion, and agnostic filtering.

Implements the three promotion gates described in issue #217:

1. Session → Project: learnings that recur across N distinct sessions
   (configurable, default N=3) are promoted to project scope. Recurrence
   is detected via a pluggable similarity function (embedding-based or
   exact-match fallback). Session learnings that match existing project
   entries reinforce those entries instead of re-promoting.

2. Project → Global: learnings that are project-agnostic (not tied to a
   specific codebase or domain) are promoted to global scope. This requires
   an LLM judgment call via a pluggable judge function.

3. Proxy exclusion: proxy learnings (from proxy.md or proxy-tasks/) are
   excluded from all promotion. They describe a specific human and must
   not become organizational knowledge.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from datetime import date
from typing import Callable

_log = logging.getLogger('orchestrator.promotion')

# Type alias for a similarity function: (text_a, text_b) -> float in [0, 1]
SimilarityFn = Callable[[str, str], float]

# Similarity threshold for considering two learnings as "the same"
RECURRENCE_SIMILARITY_THRESHOLD = 0.8


@dataclass
class PromotionResult:
    """Result of find_recurring_learnings: entries to promote and paths to reinforce."""
    to_promote: list = field(default_factory=list)
    to_reinforce: list = field(default_factory=list)  # list of file paths


def is_proxy_learning(path: str) -> bool:
    """Check whether a file path belongs to a proxy learning.

    Proxy learnings are stored in proxy.md or proxy-tasks/ directories.
    They describe a specific human's patterns and must not promote.
    """
    basename = os.path.basename(path)
    if basename == 'proxy.md':
        return True
    # Check if any path component is 'proxy-tasks'
    parts = path.replace('\\', '/').split('/')
    return 'proxy-tasks' in parts


def find_recurring_learnings(
    project_dir: str,
    *,
    min_recurrences: int = 3,
    similarity_fn: SimilarityFn | None = None,
) -> PromotionResult:
    """Find session-scope learnings that recur across N distinct sessions.

    Walks .sessions/*/tasks/*.md and .sessions/*/institutional.md under
    project_dir, groups learnings by semantic similarity, and returns a
    PromotionResult with:
    - to_promote: entries that recur in min_recurrences+ sessions and have
      no matching project-scope counterpart
    - to_reinforce: file paths of existing project entries that match
      recurring session learnings (should have reinforcement_count bumped)

    Args:
        project_dir: Path to the project directory.
        min_recurrences: Minimum distinct sessions a learning must appear in.
        similarity_fn: Function (text_a, text_b) -> float. Defaults to
            case-insensitive exact match.

    Returns:
        PromotionResult with to_promote and to_reinforce lists.
    """
    from projects.POC.scripts.memory_entry import parse_memory_file

    if similarity_fn is None:
        similarity_fn = _default_similarity

    # Collect session learnings, excluding proxy paths
    # Each item: (session_name, entry)
    session_entries: list[tuple[str, object]] = []
    sessions_dir = os.path.join(project_dir, '.sessions')
    if not os.path.isdir(sessions_dir):
        return PromotionResult()

    for session_name in sorted(os.listdir(sessions_dir)):
        session_path = os.path.join(sessions_dir, session_name)
        if not os.path.isdir(session_path):
            continue

        # Scan tasks/ directory
        tasks_dir = os.path.join(session_path, 'tasks')
        if os.path.isdir(tasks_dir):
            for fname in sorted(os.listdir(tasks_dir)):
                if not fname.endswith('.md'):
                    continue
                fpath = os.path.join(tasks_dir, fname)
                if is_proxy_learning(fpath):
                    continue
                _collect_entries_from_file(fpath, session_name, session_entries)

        # Scan institutional.md
        inst_path = os.path.join(session_path, 'institutional.md')
        if os.path.isfile(inst_path) and not is_proxy_learning(inst_path):
            _collect_entries_from_file(inst_path, session_name, session_entries)

    if not session_entries:
        return PromotionResult()

    # Collect existing project-scope learnings with their file paths
    # for both dedup (skip re-promotion) and reinforcement
    project_entries: list[tuple[str, str]] = []  # (content, file_path)
    project_tasks_dir = os.path.join(project_dir, 'tasks')
    if os.path.isdir(project_tasks_dir):
        for fname in sorted(os.listdir(project_tasks_dir)):
            if not fname.endswith('.md'):
                continue
            fpath = os.path.join(project_tasks_dir, fname)
            try:
                text = open(fpath, errors='replace').read()
            except OSError:
                continue
            entries = parse_memory_file(text)
            for entry in entries:
                if entry.content.strip():
                    project_entries.append((entry.content.strip(), fpath))

    # Also check project institutional.md
    proj_inst = os.path.join(project_dir, 'institutional.md')
    if os.path.isfile(proj_inst):
        try:
            text = open(proj_inst, errors='replace').read()
        except OSError:
            text = ''
        if text:
            entries = parse_memory_file(text)
            for entry in entries:
                if entry.content.strip():
                    project_entries.append((entry.content.strip(), proj_inst))

    # Cluster session learnings by similarity
    # clusters: list of (representative_entry, set of session_names)
    clusters: list[tuple[object, set[str]]] = []

    for session_name, entry in session_entries:
        merged = False
        for idx, (rep_entry, sessions) in enumerate(clusters):
            sim = similarity_fn(entry.content.strip(), rep_entry.content.strip())
            if sim >= RECURRENCE_SIMILARITY_THRESHOLD:
                sessions.add(session_name)
                # Keep the longest content as representative
                if len(entry.content) > len(rep_entry.content):
                    clusters[idx] = (entry, sessions)
                merged = True
                break
        if not merged:
            clusters.append((entry, {session_name}))

    # Filter: require min_recurrences distinct sessions
    result = PromotionResult()
    for rep_entry, sessions in clusters:
        if len(sessions) < min_recurrences:
            continue

        # Check if already at project scope
        matching_path = None
        for pc_content, pc_path in project_entries:
            if similarity_fn(rep_entry.content.strip(), pc_content) >= RECURRENCE_SIMILARITY_THRESHOLD:
                matching_path = pc_path
                break

        if matching_path is not None:
            # Already at project scope — reinforce instead of promoting
            if matching_path not in result.to_reinforce:
                result.to_reinforce.append(matching_path)
        else:
            result.to_promote.append(rep_entry)

    return result


def filter_project_agnostic(
    entries: list,
    *,
    judge_fn: Callable[[str], bool] | None = None,
) -> list:
    """Filter learnings to only those that are project-agnostic.

    Uses a judge function to determine whether each learning is
    generalizable (not tied to a specific project). If the judge
    raises an exception, the learning is conservatively NOT promoted.

    Args:
        entries: List of MemoryEntry objects to evaluate.
        judge_fn: Function (content) -> bool. True = project-agnostic.
            If None, no entries pass (conservative default).

    Returns:
        List of MemoryEntry objects that are project-agnostic.
    """
    if judge_fn is None:
        return []

    result = []
    for entry in entries:
        try:
            if judge_fn(entry.content.strip()):
                result.append(entry)
        except Exception as exc:
            _log.warning(
                'Project-agnostic judgment failed for entry %s: %s',
                entry.id, exc,
            )
            # Conservative: don't promote on failure
    return result


def _collect_entries_from_file(
    fpath: str,
    session_name: str,
    session_entries: list[tuple[str, object]],
) -> None:
    """Read entries from a file and append to session_entries."""
    from projects.POC.scripts.memory_entry import parse_memory_file

    try:
        text = open(fpath, errors='replace').read()
    except OSError:
        return
    entries = parse_memory_file(text)
    for entry in entries:
        if entry.content.strip():
            session_entries.append((session_name, entry))


def _default_similarity(a: str, b: str) -> float:
    """Case-insensitive exact match: 1.0 if equal, 0.0 otherwise."""
    return 1.0 if a.strip().lower() == b.strip().lower() else 0.0
