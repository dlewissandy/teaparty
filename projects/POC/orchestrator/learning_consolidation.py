"""Contradiction detection and resolution for task and institutional learnings.

Issue #244: Extends the proxy contradiction machinery (#228) to task-based
and institutional learnings. After learning extraction writes new entries,
the system detects contradictions with existing entries at the same scope,
classifies by cause, and resolves them.

Classification causes differ from proxy contradictions:
- temporal_obsolescence: was true earlier, no longer applies
- scope_dependent: true at one scope level, false at another
- genuine_tension: unresolved real disagreement between learnings
- retrieval_noise: entries appear related but are about different things

Architecture follows the same patterns as proxy_memory.py:
- Jaccard-based content similarity for candidate pre-filtering
- Heuristic classification using metadata (dates, reinforcement)
- Optional LLM classifier override
- Consolidation taxonomy (DELETE older for temporal_obsolescence,
  preserve both for everything else)
"""
from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from typing import Any, Callable

_log = logging.getLogger('orchestrator.learning_consolidation')

# ── Classification cause constants ───────────────────────────────────────────

CAUSE_TEMPORAL_OBSOLESCENCE = 'temporal_obsolescence'
CAUSE_SCOPE_DEPENDENT = 'scope_dependent'
CAUSE_GENUINE_TENSION = 'genuine_tension'
CAUSE_RETRIEVAL_NOISE = 'retrieval_noise'

VALID_CAUSES = frozenset({
    CAUSE_TEMPORAL_OBSOLESCENCE,
    CAUSE_SCOPE_DEPENDENT,
    CAUSE_GENUINE_TENSION,
    CAUSE_RETRIEVAL_NOISE,
})

# Date gap threshold (days): if creation dates differ by more than this,
# and entries are topically similar, classify as temporal_obsolescence.
_DATE_GAP_THRESHOLD_DAYS = 90

# Reinforcement threshold: both entries must have at least this many
# reinforcements to qualify as genuine_tension.
_TENSION_REINFORCEMENT_THRESHOLD = 3

# Jaccard similarity threshold for detecting topically related entries.
_SIMILARITY_THRESHOLD = 0.3

# Importance multiplier for entries involved in genuine tension.
# Reduces prominence at retrieval time so contradicted entries decay
# faster (#218 interaction). 0.7 means a 30% importance reduction.
_TENSION_IMPORTANCE_FACTOR = 0.7


@dataclass
class LearningConflictClassification:
    """Result of classifying a conflicting learning entry pair."""
    entry_a_id: str
    entry_b_id: str
    cause: str      # one of VALID_CAUSES
    action: str     # human-readable recommended action
    newer_id: str = ''


# ── Content similarity ───────────────────────────────────────────────────────

def _tokenize(text: str) -> set[str]:
    """Extract word tokens for similarity comparison."""
    return set(re.findall(r'[a-z0-9]+', text.lower()))


def _jaccard(a: set[str], b: set[str]) -> float:
    """Jaccard similarity between two token sets."""
    if not a and not b:
        return 1.0
    union = a | b
    if not union:
        return 0.0
    return len(a & b) / len(union)


# ── Finding conflicting entry pairs ──────────────────────────────────────────

def find_conflicting_entries(
    entries: list,
    *,
    similarity_threshold: float = _SIMILARITY_THRESHOLD,
) -> list[tuple]:
    """Identify candidate conflicting pairs among MemoryEntry objects.

    A pair is a candidate conflict when their content is topically similar
    (Jaccard above threshold) — unlike proxy chunks which use structured
    (state, task_type, outcome) matching, learning entries are unstructured
    text so we use content similarity as the pre-filter.

    The entry list is NOT modified (read-only).
    """
    if len(entries) < 2:
        return []

    tokens = [_tokenize(e.content) for e in entries]
    pairs = []

    for i in range(len(entries)):
        for j in range(i + 1, len(entries)):
            sim = _jaccard(tokens[i], tokens[j])
            if sim >= similarity_threshold:
                pairs.append((entries[i], entries[j]))

    return pairs


# ── Classifying conflicts ────────────────────────────────────────────────────

def _parse_date(date_str: str) -> int:
    """Parse ISO date string to ordinal for comparison."""
    from datetime import date
    try:
        parts = date_str.split('-')
        return date(int(parts[0]), int(parts[1]), int(parts[2])).toordinal()
    except (ValueError, IndexError):
        return 0


def classify_learning_conflict(
    entry_a,
    entry_b,
    *,
    date_gap_threshold: int = _DATE_GAP_THRESHOLD_DAYS,
    reinforcement_threshold: int = _TENSION_REINFORCEMENT_THRESHOLD,
) -> LearningConflictClassification:
    """Classify a conflicting MemoryEntry pair by cause.

    Uses heuristic signals from entry metadata — no LLM call.

    Classification rules (applied in order):
    1. Temporal obsolescence: large date gap between entries.
    2. Genuine tension: both well-reinforced (validated by experience).
    3. Default: genuine_tension (preserve both, flag for review —
       safer than silently deleting).
    """
    a_date = _parse_date(entry_a.created_at)
    b_date = _parse_date(entry_b.created_at)
    date_gap = abs(a_date - b_date)

    # Determine which is newer
    if a_date >= b_date:
        newer, older = entry_a, entry_b
    else:
        newer, older = entry_b, entry_a

    # Rule 1: temporal obsolescence — large date gap
    if date_gap >= date_gap_threshold:
        return LearningConflictClassification(
            entry_a_id=entry_a.id,
            entry_b_id=entry_b.id,
            cause=CAUSE_TEMPORAL_OBSOLESCENCE,
            action=f'Prefer newer entry ({newer.id}); older entry may no longer apply.',
            newer_id=newer.id,
        )

    # Rule 2: genuine tension — both well-reinforced
    a_reinforced = entry_a.reinforcement_count >= reinforcement_threshold
    b_reinforced = entry_b.reinforcement_count >= reinforcement_threshold
    if a_reinforced and b_reinforced:
        return LearningConflictClassification(
            entry_a_id=entry_a.id,
            entry_b_id=entry_b.id,
            cause=CAUSE_GENUINE_TENSION,
            action='Flag for review — both entries validated by experience.',
        )

    # Default: genuine_tension (preserve both, flag for review)
    return LearningConflictClassification(
        entry_a_id=entry_a.id,
        entry_b_id=entry_b.id,
        cause=CAUSE_GENUINE_TENSION,
        action='Flag for review — cannot reliably determine resolution without more context.',
    )


# ── Consolidation (resolution) ───────────────────────────────────────────────

def consolidate_learning_entries(
    entries: list,
    *,
    classifier: Callable | None = None,
    similarity_threshold: float = _SIMILARITY_THRESHOLD,
    already_decayed_ids: set[str] | None = None,
) -> tuple[list, list[dict]]:
    """Apply contradiction resolution to a list of MemoryEntry objects.

    For each conflicting pair:
    - temporal_obsolescence -> DELETE older entry
    - scope_dependent -> preserve both
    - genuine_tension -> preserve both, reduce importance once (#218)
    - retrieval_noise -> preserve both

    Args:
        entries: list of MemoryEntry objects
        classifier: optional callable(entry_a, entry_b) -> cause string.
            When provided, overrides heuristic classification.
        similarity_threshold: Jaccard threshold for conflict detection.
        already_decayed_ids: entry IDs that had importance reduced in a
            prior consolidation run. These are skipped for importance
            reduction to prevent compounding decay across sessions.

    Returns:
        (consolidated_entries, decisions) for auditability.
    """
    if len(entries) < 2:
        return list(entries), []

    pairs = find_conflicting_entries(
        entries, similarity_threshold=similarity_threshold,
    )
    if not pairs:
        return list(entries), []

    _already_decayed = already_decayed_ids or set()
    delete_ids: set[str] = set()
    tension_ids: set[str] = set()
    decisions: list[dict] = []

    for a, b in pairs:
        if classifier:
            cause = classifier(a, b)
        else:
            classification = classify_learning_conflict(a, b)
            cause = classification.cause

        decision = {
            'entry_a': a.id,
            'entry_b': b.id,
            'cause': cause,
        }

        if cause == CAUSE_TEMPORAL_OBSOLESCENCE:
            # Delete the older entry
            a_date = _parse_date(a.created_at)
            b_date = _parse_date(b.created_at)
            older_id = a.id if a_date < b_date else b.id
            delete_ids.add(older_id)
            decision['action'] = 'DELETE'
            decision['deleted_id'] = older_id
        elif cause == CAUSE_GENUINE_TENSION:
            # Track entries for importance reduction (#218 interaction),
            # but only if not already decayed in a prior run.
            if a.id not in _already_decayed:
                tension_ids.add(a.id)
            if b.id not in _already_decayed:
                tension_ids.add(b.id)
            decision['action'] = 'PRESERVE_BOTH_DECAYED'
        else:
            decision['action'] = 'PRESERVE_BOTH'

        decisions.append(decision)

    consolidated = [e for e in entries if e.id not in delete_ids]

    # Apply importance reduction to entries involved in genuine tension
    # (only those not already decayed in a prior run)
    for entry in consolidated:
        if entry.id in tension_ids:
            entry.importance = max(0.1, entry.importance * _TENSION_IMPORTANCE_FACTOR)

    return consolidated, decisions


# ── File-level consolidation: task directories ───────────────────────────────

def consolidate_learning_file(
    directory: str,
    *,
    classifier: Callable | None = None,
    already_decayed_ids: set[str] | None = None,
) -> tuple[int, list[dict]]:
    """Consolidate learning entries in a tasks/ directory.

    Reads all .md files, detects contradictions, resolves them,
    removes files for deleted entries, and rewrites files for
    entries whose importance was modified.

    Returns (files_removed, decisions).
    """
    from projects.POC.scripts.memory_entry import parse_memory_file, serialize_entry

    if not os.path.isdir(directory):
        return 0, []

    # Read all entries from .md files
    md_files = sorted(f for f in os.listdir(directory) if f.endswith('.md'))
    if len(md_files) < 2:
        return 0, []

    entries = []
    entry_to_file: dict[str, str] = {}
    original_importance: dict[str, float] = {}

    for fname in md_files:
        fpath = os.path.join(directory, fname)
        try:
            with open(fpath) as f:
                text = f.read()
        except OSError:
            continue
        parsed = parse_memory_file(text)
        for entry in parsed:
            entries.append(entry)
            entry_to_file[entry.id] = fpath
            original_importance[entry.id] = entry.importance

    if len(entries) < 2:
        return 0, []

    consolidated, decisions = consolidate_learning_entries(
        entries, classifier=classifier,
        already_decayed_ids=already_decayed_ids,
    )

    # Determine which entries were removed
    kept_ids = {e.id for e in consolidated}
    removed_ids = {e.id for e in entries} - kept_ids
    files_removed = 0

    # Build reverse map: file → kept entry IDs (for multi-entry file safety)
    file_to_kept: dict[str, list] = {}
    for entry in consolidated:
        fpath = entry_to_file.get(entry.id)
        if fpath:
            file_to_kept.setdefault(fpath, []).append(entry)

    for entry_id in removed_ids:
        fpath = entry_to_file.get(entry_id)
        if not fpath or not os.path.isfile(fpath):
            continue
        surviving_in_file = file_to_kept.get(fpath, [])
        if surviving_in_file:
            # File has other entries that must survive — rewrite with
            # only the surviving entries instead of deleting the file.
            from projects.POC.scripts.memory_entry import serialize_memory_file
            try:
                with open(fpath, 'w') as f:
                    f.write(serialize_memory_file(surviving_in_file))
                files_removed += 1
            except OSError:
                pass
            # Clear so we don't rewrite again for another removed entry
            # in the same file
            del file_to_kept[fpath]
        else:
            try:
                os.remove(fpath)
                files_removed += 1
            except OSError:
                pass

    # Rewrite files for entries whose importance was modified
    for entry in consolidated:
        if entry.importance != original_importance.get(entry.id):
            fpath = entry_to_file.get(entry.id)
            if fpath and os.path.isfile(fpath):
                try:
                    with open(fpath, 'w') as f:
                        f.write(serialize_entry(entry))
                except OSError:
                    pass

    return files_removed, decisions


# ── File-level consolidation: institutional.md ───────────────────────────────

def consolidate_institutional_file(
    file_path: str,
    *,
    classifier: Callable | None = None,
    already_decayed_ids: set[str] | None = None,
) -> tuple[int, list[dict]]:
    """Consolidate entries within an institutional.md file.

    Reads multi-entry institutional.md, detects contradictions,
    resolves them, and rewrites the file when entries are removed
    or importance is modified.

    Returns (entries_removed, decisions).
    """
    from projects.POC.scripts.memory_entry import (
        parse_memory_file,
        serialize_memory_file,
    )

    if not os.path.isfile(file_path):
        return 0, []

    try:
        with open(file_path) as f:
            text = f.read()
    except OSError:
        return 0, []

    entries = parse_memory_file(text)
    if len(entries) < 2:
        return 0, []

    original_importance = {e.id: e.importance for e in entries}

    consolidated, decisions = consolidate_learning_entries(
        entries, classifier=classifier,
        already_decayed_ids=already_decayed_ids,
    )

    entries_removed = len(entries) - len(consolidated)
    # Also check if any importance values changed
    importance_changed = any(
        e.importance != original_importance.get(e.id)
        for e in consolidated
    )

    if entries_removed > 0 or importance_changed:
        output = serialize_memory_file(consolidated)
        import tempfile
        try:
            fd, tmp = tempfile.mkstemp(
                dir=os.path.dirname(os.path.abspath(file_path)),
                suffix='.tmp',
            )
            with os.fdopen(fd, 'w') as f:
                f.write(output)
                if output and not output.endswith('\n'):
                    f.write('\n')
            os.replace(tmp, file_path)
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    return entries_removed, decisions
