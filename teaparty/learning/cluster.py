"""Within-scope learning consolidation for duplicate and overlapping entries.

Issue #245: After learning extraction, identifies clusters of semantically
similar entries within the same scope and type, and merges each cluster into
a single higher-confidence entry. This reclaims retrieval slots in the
fuzzy-retrieved task-based and proxy-task stores.

Distinct from:
  - _try_compact() — operates on prose institutional.md files
  - contradiction detection (#244) — handles entries that disagree
  - proxy consolidation (#228) — handles proxy.md contradictions

This module targets the chunked task-based stores where entries are
individual files and retrieval budget is finite.
"""
from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path

from teaparty.learning.episodic.entry import (
    MemoryEntry,
    parse_memory_file,
    serialize_entry,
)

_log = logging.getLogger('teaparty.learning.cluster')

CONSOLIDATION_SIMILARITY_THRESHOLD = 0.4

# Stop words excluded from similarity computation — these inflate token
# counts without carrying topical signal.
_STOP_WORDS = frozenset(
    'a an the is are was were be been being have has had do does did '
    'will would shall should can could may might must '
    'i me my we our you your he she it they them their '
    'this that these those who what which when where how '
    'and or but not no nor so if then than too also '
    'to of in for on at by from with as into about '
    'all each every some any many much more most other such '
    'very just only even still already don t s'.split()
)


# ── Normalized token similarity (default, no dependencies) ──────────────────

_SUFFIXES = ('tion', 'sion', 'ness', 'ment', 'ence', 'ance',
             'ing', 'ies', 'ied', 'ers', 'est', 'ous', 'ive',
             'ed', 'ly', 'er', 'es', 'en', 'al')


def _normalize_token(word: str) -> str:
    """Basic English normalization: iteratively strip common suffixes.

    Not a full stemmer — just enough to unify plurals, gerunds, and past
    tense so "tests"/"test", "inputs"/"input", "writing"/"write",
    "missed"/"miss" all normalize to the same token.

    Applied iteratively so "missed" → "miss" → "mis" matches "miss" → "mis".
    """
    current = word
    prev = None
    while current != prev and len(current) > 3:
        prev = current
        for suffix in _SUFFIXES:
            if current.endswith(suffix) and len(current) - len(suffix) >= 3:
                current = current[:-len(suffix)]
                break
        else:
            if current.endswith('s') and len(current) > 3:
                current = current[:-1]
    return current


def _tokenize(text: str) -> set[str]:
    """Extract normalized, lowercased content tokens from text.

    Strips stop words and applies basic suffix normalization so that
    "tests"/"test", "inputs"/"input", "writing"/"write" are treated
    as the same token.
    """
    raw = set(re.findall(r'[a-z0-9]+', text.lower()))
    return {_normalize_token(w) for w in raw if w not in _STOP_WORDS}


def jaccard_token_similarity(a: str, b: str) -> float:
    """Jaccard similarity over normalized content tokens."""
    tokens_a = _tokenize(a)
    tokens_b = _tokenize(b)
    union = tokens_a | tokens_b
    if not union:
        return 0.0
    return len(tokens_a & tokens_b) / len(union)


def overlap_token_similarity(a: str, b: str) -> float:
    """Overlap coefficient over normalized content tokens.

    Returns |A ∩ B| / min(|A|, |B|).  Unlike Jaccard, this does not
    penalize one text for having extra unique terms — it measures how
    much the smaller set is contained in the larger.  Better for
    detecting paraphrased duplicates where vocabulary differs.
    """
    tokens_a = _tokenize(a)
    tokens_b = _tokenize(b)
    if not tokens_a or not tokens_b:
        return 0.0
    return len(tokens_a & tokens_b) / min(len(tokens_a), len(tokens_b))


def lexical_similarity(a: str, b: str) -> float:
    """Combined lexical similarity: max of Jaccard and overlap coefficient.

    Default similarity function when embeddings are unavailable.
    Uses both metrics because Jaccard catches near-duplicates (high
    overall overlap) while overlap coefficient catches paraphrases
    (one text's vocabulary is a subset of another's).
    """
    return max(jaccard_token_similarity(a, b), overlap_token_similarity(a, b))


# ── Clustering ───────────────────────────────────────────────────────────────

def cluster_entries(
    entries: list[MemoryEntry],
    similarity_fn=None,
    threshold: float = CONSOLIDATION_SIMILARITY_THRESHOLD,
) -> list[list[MemoryEntry]]:
    """Cluster entries by semantic similarity using single-linkage clustering.

    Args:
        entries: MemoryEntry objects to cluster.
        similarity_fn: (str, str) -> float. Defaults to lexical_similarity.
        threshold: Minimum similarity to join a cluster.

    Returns:
        List of clusters, where each cluster is a list of MemoryEntry objects.
        Retired entries are excluded before clustering.
    """
    if similarity_fn is None:
        similarity_fn = lexical_similarity

    # Filter out retired entries and entries too short to cluster reliably.
    # Short entries (< 4 content tokens after normalization) have inflated
    # similarity scores and produce false merges.
    _MIN_TOKENS = 4
    active = [
        e for e in entries
        if e.status != 'retired' and len(_tokenize(e.content)) >= _MIN_TOKENS
    ]
    # Carry through short entries as singleton clusters
    short = [
        e for e in entries
        if e.status != 'retired' and len(_tokenize(e.content)) < _MIN_TOKENS
    ]
    if not active:
        return [[e] for e in short]

    clusters: list[list[MemoryEntry]] = []

    for entry in active:
        merged = False
        for cluster in clusters:
            for member in cluster:
                sim = similarity_fn(entry.content.strip(), member.content.strip())
                if sim >= threshold:
                    cluster.append(entry)
                    merged = True
                    break
            if merged:
                break
        if not merged:
            clusters.append([entry])

    # Append short entries as singleton clusters (not eligible for merging)
    for e in short:
        clusters.append([e])

    return clusters


# ── Merging ──────────────────────────────────────────────────────────────────

# Per-entry convergence boost: each additional entry in a cluster adds this
# to the max importance, reflecting that independent sessions reaching the
# same conclusion is stronger evidence.
_CONVERGENCE_BOOST_PER_ENTRY = 0.05


def merge_cluster(entries: list[MemoryEntry]) -> MemoryEntry:
    """Merge a cluster of similar entries into a single consolidated entry.

    - Content: longest entry's content (most detailed expression of the insight)
    - Importance: max(importances) + convergence boost (capped at 1.0)
    - Reinforcement: max(counts) + 1 (convergence signal, avoids inflation)
    - Status: 'compacted'
    - Dates: earliest created_at, most recent last_reinforced
    - ID: inherits from the entry with highest importance

    A singleton cluster returns the entry unchanged.
    """
    if len(entries) == 1:
        return entries[0]

    # Pick the entry with longest content as the base
    best = max(entries, key=lambda e: len(e.content))

    # Importance: max + convergence boost
    max_importance = max(e.importance for e in entries)
    extra_entries = len(entries) - 1
    boosted = min(1.0, max_importance + extra_entries * _CONVERGENCE_BOOST_PER_ENTRY)

    # Reinforcement: max + 1
    max_reinforcement = max(e.reinforcement_count for e in entries)

    # Dates
    earliest_created = min(e.created_at for e in entries)
    latest_reinforced = max(e.last_reinforced for e in entries)

    # ID from highest-importance entry (stable reference)
    id_source = max(entries, key=lambda e: e.importance)

    return MemoryEntry(
        id=id_source.id,
        type=best.type,
        domain=best.domain,
        importance=boosted,
        phase=best.phase,
        status='compacted',
        reinforcement_count=max_reinforcement + 1,
        last_reinforced=latest_reinforced,
        created_at=earliest_created,
        content=best.content,
        session_id=best.session_id,
        session_task=best.session_task,
        promoted_from=best.promoted_from,
        promoted_at=best.promoted_at,
    )


# ── Directory-level consolidation ────────────────────────────────────────────

@dataclass
class ConsolidationResult:
    """Result of consolidating a task store directory."""
    original_count: int
    final_count: int
    merged_count: int


def consolidate_task_store(
    directory: str,
    similarity_fn=None,
    threshold: float = CONSOLIDATION_SIMILARITY_THRESHOLD,
) -> ConsolidationResult:
    """Consolidate semantically similar entries in a tasks/ directory.

    Reads all .md files, clusters similar entries, merges clusters,
    rewrites the directory atomically (new files first, then remove old).

    Args:
        directory: Path to a tasks/ or proxy-tasks/ directory.
        similarity_fn: Optional (str, str) -> float similarity function.
        threshold: Clustering threshold (default 0.8).

    Returns:
        ConsolidationResult with counts.
    """
    if not os.path.isdir(directory):
        return ConsolidationResult(0, 0, 0)

    # Read all .md files and their entries.
    # Exclude correction-*.md files — they have a dedicated compaction
    # pipeline (_compact_proxy_correction_entries, issue #198).
    md_files = sorted(
        f for f in os.listdir(directory)
        if f.endswith('.md') and not f.startswith('.') and not f.startswith('correction-')
    )
    if not md_files:
        return ConsolidationResult(0, 0, 0)

    all_entries: list[MemoryEntry] = []
    file_for_entry: dict[str, str] = {}  # entry.id -> source filename

    for fname in md_files:
        fpath = os.path.join(directory, fname)
        try:
            text = Path(fpath).read_text(errors='replace')
        except OSError:
            continue
        entries = parse_memory_file(text)
        for entry in entries:
            all_entries.append(entry)
            file_for_entry[entry.id] = fname

    if len(all_entries) < 2:
        return ConsolidationResult(len(all_entries), len(all_entries), 0)

    # Cluster and merge
    clusters = cluster_entries(all_entries, similarity_fn=similarity_fn, threshold=threshold)

    merged_entries: list[MemoryEntry] = []
    log_entries: list[dict] = []
    merged_count = 0

    for cluster in clusters:
        if len(cluster) > 1:
            merged = merge_cluster(cluster)
            merged_entries.append(merged)
            merged_count += len(cluster) - 1
            log_entries.append({
                'action': 'merge',
                'cluster_size': len(cluster),
                'merged_ids': [e.id for e in cluster],
                'surviving_id': merged.id,
                'importance': merged.importance,
            })
        else:
            merged_entries.append(cluster[0])

    if merged_count == 0:
        return ConsolidationResult(len(all_entries), len(all_entries), 0)

    # Only rewrite files that participated in merges — leave singletons
    # and their original filenames untouched to preserve provenance.
    from filelock import FileLock

    # Collect IDs and source files involved in merges
    merged_ids: set[str] = set()
    for cluster in clusters:
        if len(cluster) > 1:
            for entry in cluster:
                merged_ids.add(entry.id)

    files_to_remove: set[str] = set()
    for entry_id in merged_ids:
        if entry_id in file_for_entry:
            files_to_remove.add(file_for_entry[entry_id])

    # Write merged entries (new files for merged clusters only)
    for cluster in clusters:
        if len(cluster) <= 1:
            continue
        merged = merge_cluster(cluster)
        fname = f'consolidated-{merged.id}.md'
        fpath = os.path.join(directory, fname)
        # Don't remove the new file we're about to write
        files_to_remove.discard(fname)
        lock = FileLock(fpath + '.lock', timeout=10)
        with lock:
            import tempfile as _tf
            fd, tmp = _tf.mkstemp(dir=directory, suffix='.tmp')
            try:
                content = serialize_entry(merged)
                with os.fdopen(fd, 'w') as f:
                    f.write(content)
                    if content and not content.endswith('\n'):
                        f.write('\n')
                os.replace(tmp, fpath)
            except Exception:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
                raise

    # Rescue orphaned entries: entries in files marked for removal that
    # were NOT part of any merge.  Prevents data loss when a multi-entry
    # file contains both merged and non-merged entries.
    for entry in all_entries:
        if entry.id not in merged_ids and file_for_entry.get(entry.id) in files_to_remove:
            fname = f'{entry.id}.md'
            fpath = os.path.join(directory, fname)
            lock = FileLock(fpath + '.lock', timeout=10)
            with lock:
                import tempfile as _tf
                fd, tmp = _tf.mkstemp(dir=directory, suffix='.tmp')
                try:
                    content = serialize_entry(entry)
                    with os.fdopen(fd, 'w') as f:
                        f.write(content)
                        if content and not content.endswith('\n'):
                            f.write('\n')
                    os.replace(tmp, fpath)
                except Exception:
                    try:
                        os.unlink(tmp)
                    except OSError:
                        pass
                    raise

    # Remove old files that were merged into consolidated entries
    for fname in files_to_remove:
        fpath = os.path.join(directory, fname)
        try:
            os.remove(fpath)
        except OSError:
            pass
        lock_path = fpath + '.lock'
        try:
            os.remove(lock_path)
        except OSError:
            pass

    # Write consolidation log
    if log_entries:
        log_path = os.path.join(directory, '.consolidation-log.jsonl')
        try:
            with open(log_path, 'a') as f:
                for entry in log_entries:
                    f.write(json.dumps(entry) + '\n')
        except OSError:
            pass

    _log.info(
        'Consolidated %s: %d → %d entries (%d merged)',
        directory, len(all_entries), len(merged_entries), merged_count,
    )

    return ConsolidationResult(
        original_count=len(all_entries),
        final_count=len(merged_entries),
        merged_count=merged_count,
    )
