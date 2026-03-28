#!/usr/bin/env python3
"""Tests for within-scope learning consolidation (Issue #245).

Verifies that semantically similar entries within the same scope and type
are identified, clustered, and merged into single higher-confidence entries.
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent.parent))

from projects.POC.scripts.memory_entry import MemoryEntry, serialize_entry


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_entry(
    content: str,
    importance: float = 0.5,
    reinforcement_count: int = 0,
    status: str = 'active',
    entry_id: str = '',
    session_id: str = '',
    created_at: str = '2026-01-01',
) -> MemoryEntry:
    """Create a MemoryEntry with sensible defaults for testing."""
    import uuid
    return MemoryEntry(
        id=entry_id or str(uuid.uuid4()),
        type='procedural',
        domain='task',
        importance=importance,
        phase='implementation',
        status=status,
        reinforcement_count=reinforcement_count,
        last_reinforced=created_at,
        created_at=created_at,
        content=content,
        session_id=session_id,
    )


def _write_entry_file(directory: str, filename: str, entry: MemoryEntry) -> str:
    """Write a MemoryEntry to a file, return the path."""
    os.makedirs(directory, exist_ok=True)
    path = os.path.join(directory, filename)
    Path(path).write_text(serialize_entry(entry))
    return path


# ── Core clustering tests ────────────────────────────────────────────────────

class TestClusterEntries(unittest.TestCase):
    """Test the entry clustering logic."""

    def test_identical_entries_cluster_together(self):
        """Two entries with identical content form one cluster."""
        from projects.POC.orchestrator.consolidate_learnings import cluster_entries

        entries = [
            _make_entry("Always check edge cases for empty inputs"),
            _make_entry("Always check edge cases for empty inputs"),
        ]
        clusters = cluster_entries(entries)
        self.assertEqual(len(clusters), 1)
        self.assertEqual(len(clusters[0]), 2)

    def test_dissimilar_entries_stay_separate(self):
        """Entries with completely different content remain in separate clusters."""
        from projects.POC.orchestrator.consolidate_learnings import cluster_entries

        entries = [
            _make_entry("Always check edge cases for empty inputs"),
            _make_entry("Database migrations require backup verification first"),
        ]
        clusters = cluster_entries(entries)
        self.assertEqual(len(clusters), 2)

    def test_near_duplicate_entries_cluster(self):
        """Entries expressing the same insight in similar words cluster together."""
        from projects.POC.orchestrator.consolidate_learnings import cluster_entries

        entries = [
            _make_entry("When writing tests, always check edge cases for empty inputs"),
            _make_entry("Empty-input edge cases are the most common source of missed test coverage"),
            _make_entry("Tests that don't cover empty null inputs tend to miss real bugs"),
        ]
        # With Jaccard at 0.8 these may or may not cluster (depends on token overlap).
        # But with a custom similarity_fn that recognizes these as similar, they should.
        def _always_similar(a, b):
            return 0.9

        clusters = cluster_entries(entries, similarity_fn=_always_similar)
        self.assertEqual(len(clusters), 1)
        self.assertEqual(len(clusters[0]), 3)

    def test_custom_threshold(self):
        """Threshold parameter controls cluster sensitivity."""
        from projects.POC.orchestrator.consolidate_learnings import cluster_entries

        entries = [
            _make_entry("Check empty inputs in tests"),
            _make_entry("Check null inputs in tests"),
        ]
        # Low similarity — should cluster at low threshold but not high
        def _moderate_sim(a, b):
            return 0.6

        clusters_low = cluster_entries(entries, similarity_fn=_moderate_sim, threshold=0.5)
        self.assertEqual(len(clusters_low), 1)

        clusters_high = cluster_entries(entries, similarity_fn=_moderate_sim, threshold=0.7)
        self.assertEqual(len(clusters_high), 2)

    def test_single_entry_forms_singleton_cluster(self):
        """A single entry produces a single cluster of size 1."""
        from projects.POC.orchestrator.consolidate_learnings import cluster_entries

        entries = [_make_entry("Solo entry")]
        clusters = cluster_entries(entries)
        self.assertEqual(len(clusters), 1)
        self.assertEqual(len(clusters[0]), 1)

    def test_empty_input(self):
        """Empty entry list returns empty cluster list."""
        from projects.POC.orchestrator.consolidate_learnings import cluster_entries

        clusters = cluster_entries([])
        self.assertEqual(clusters, [])

    def test_retired_entries_excluded(self):
        """Retired entries are excluded from clustering."""
        from projects.POC.orchestrator.consolidate_learnings import cluster_entries

        entries = [
            _make_entry("Active entry about testing"),
            _make_entry("Active entry about testing", status='retired'),
        ]
        clusters = cluster_entries(entries)
        # Only the active entry should be present
        all_entries = [e for c in clusters for e in c]
        self.assertEqual(len(all_entries), 1)
        self.assertEqual(all_entries[0].status, 'active')


# ── Merge logic tests ────────────────────────────────────────────────────────

class TestMergeCluster(unittest.TestCase):
    """Test merging a cluster of similar entries into one."""

    def test_merge_preserves_longest_content(self):
        """Merged entry keeps the longest content from the cluster."""
        from projects.POC.orchestrator.consolidate_learnings import merge_cluster

        entries = [
            _make_entry("Short"),
            _make_entry("This is the longest and most detailed content in the cluster"),
            _make_entry("Medium length content here"),
        ]
        merged = merge_cluster(entries)
        self.assertEqual(merged.content, "This is the longest and most detailed content in the cluster")

    def test_merge_boosts_importance(self):
        """Merged entry's importance reflects convergence — higher than any single entry."""
        from projects.POC.orchestrator.consolidate_learnings import merge_cluster

        entries = [
            _make_entry("Same insight", importance=0.5),
            _make_entry("Same insight", importance=0.6),
            _make_entry("Same insight", importance=0.4),
        ]
        merged = merge_cluster(entries)
        # Importance should be at least max(individual importances)
        self.assertGreaterEqual(merged.importance, 0.6)
        # And boosted above the max to reflect convergence
        self.assertGreater(merged.importance, 0.6)
        # But capped at 1.0
        self.assertLessEqual(merged.importance, 1.0)

    def test_merge_reinforcement_uses_max_plus_one(self):
        """Reinforcement count is max(counts) + 1, not sum (avoids inflation)."""
        from projects.POC.orchestrator.consolidate_learnings import merge_cluster

        entries = [
            _make_entry("Same insight", reinforcement_count=3),
            _make_entry("Same insight", reinforcement_count=7),
            _make_entry("Same insight", reinforcement_count=1),
        ]
        merged = merge_cluster(entries)
        self.assertEqual(merged.reinforcement_count, 8)  # max(3,7,1) + 1

    def test_merge_sets_compacted_status(self):
        """Merged entry has status 'compacted'."""
        from projects.POC.orchestrator.consolidate_learnings import merge_cluster

        entries = [
            _make_entry("A"),
            _make_entry("B"),
        ]
        merged = merge_cluster(entries)
        self.assertEqual(merged.status, 'compacted')

    def test_merge_keeps_most_recent_reinforced_date(self):
        """Merged entry uses the most recent last_reinforced date."""
        from projects.POC.orchestrator.consolidate_learnings import merge_cluster

        entries = [
            _make_entry("A", created_at='2026-01-01'),
            _make_entry("B", created_at='2026-03-15'),
            _make_entry("C", created_at='2026-02-01'),
        ]
        merged = merge_cluster(entries)
        self.assertEqual(merged.last_reinforced, '2026-03-15')

    def test_merge_keeps_earliest_created_at(self):
        """Merged entry preserves the oldest created_at for provenance."""
        from projects.POC.orchestrator.consolidate_learnings import merge_cluster

        entries = [
            _make_entry("A", created_at='2026-02-01'),
            _make_entry("B", created_at='2026-01-01'),
            _make_entry("C", created_at='2026-03-01'),
        ]
        merged = merge_cluster(entries)
        self.assertEqual(merged.created_at, '2026-01-01')

    def test_singleton_cluster_returns_entry_unchanged(self):
        """A cluster of one entry returns that entry without modification."""
        from projects.POC.orchestrator.consolidate_learnings import merge_cluster

        entry = _make_entry("Solo", importance=0.5, reinforcement_count=2)
        merged = merge_cluster([entry])
        self.assertEqual(merged.content, "Solo")
        self.assertEqual(merged.importance, 0.5)
        self.assertEqual(merged.reinforcement_count, 2)


# ── Directory-level consolidation tests ──────────────────────────────────────

class TestConsolidateTaskStore(unittest.TestCase):
    """Test consolidation of an entire tasks/ directory."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_duplicate_files_consolidated(self):
        """Two files with identical content are merged into one file."""
        from projects.POC.orchestrator.consolidate_learnings import consolidate_task_store

        tasks_dir = os.path.join(self.tmpdir, 'tasks')
        _write_entry_file(tasks_dir, 'a.md', _make_entry("Always test empty inputs"))
        _write_entry_file(tasks_dir, 'b.md', _make_entry("Always test empty inputs"))

        result = consolidate_task_store(tasks_dir)
        self.assertGreater(result.merged_count, 0)

        # Should have one file remaining
        remaining = [f for f in os.listdir(tasks_dir) if f.endswith('.md')]
        self.assertEqual(len(remaining), 1)

    def test_dissimilar_files_preserved(self):
        """Files with different content are not touched."""
        from projects.POC.orchestrator.consolidate_learnings import consolidate_task_store

        tasks_dir = os.path.join(self.tmpdir, 'tasks')
        _write_entry_file(tasks_dir, 'a.md', _make_entry("Always test empty inputs"))
        _write_entry_file(tasks_dir, 'b.md', _make_entry("Database migrations require backups"))

        result = consolidate_task_store(tasks_dir)
        self.assertEqual(result.merged_count, 0)

        remaining = [f for f in os.listdir(tasks_dir) if f.endswith('.md')]
        self.assertEqual(len(remaining), 2)

    def test_empty_directory_is_noop(self):
        """Empty directory returns zero-count result."""
        from projects.POC.orchestrator.consolidate_learnings import consolidate_task_store

        tasks_dir = os.path.join(self.tmpdir, 'tasks')
        os.makedirs(tasks_dir)

        result = consolidate_task_store(tasks_dir)
        self.assertEqual(result.merged_count, 0)
        self.assertEqual(result.original_count, 0)

    def test_nonexistent_directory_is_noop(self):
        """Nonexistent directory returns zero-count result without error."""
        from projects.POC.orchestrator.consolidate_learnings import consolidate_task_store

        result = consolidate_task_store(os.path.join(self.tmpdir, 'nonexistent'))
        self.assertEqual(result.merged_count, 0)

    def test_consolidation_log_written(self):
        """A consolidation log file is written when merges occur."""
        from projects.POC.orchestrator.consolidate_learnings import consolidate_task_store

        tasks_dir = os.path.join(self.tmpdir, 'tasks')
        _write_entry_file(tasks_dir, 'a.md', _make_entry("Always test empty inputs"))
        _write_entry_file(tasks_dir, 'b.md', _make_entry("Always test empty inputs"))

        consolidate_task_store(tasks_dir)

        log_path = os.path.join(tasks_dir, '.consolidation-log.jsonl')
        self.assertTrue(os.path.isfile(log_path))

    def test_merged_file_has_boosted_importance(self):
        """The remaining file after merge has importance > max of originals."""
        from projects.POC.orchestrator.consolidate_learnings import consolidate_task_store
        from projects.POC.scripts.memory_entry import parse_memory_file

        tasks_dir = os.path.join(self.tmpdir, 'tasks')
        _write_entry_file(tasks_dir, 'a.md', _make_entry("Always test empty inputs", importance=0.5))
        _write_entry_file(tasks_dir, 'b.md', _make_entry("Always test empty inputs", importance=0.6))

        consolidate_task_store(tasks_dir)

        remaining = [f for f in os.listdir(tasks_dir) if f.endswith('.md')]
        self.assertEqual(len(remaining), 1)

        text = Path(os.path.join(tasks_dir, remaining[0])).read_text()
        entries = parse_memory_file(text)
        self.assertEqual(len(entries), 1)
        self.assertGreater(entries[0].importance, 0.6)

    def test_custom_similarity_fn(self):
        """Custom similarity function is used for clustering."""
        from projects.POC.orchestrator.consolidate_learnings import consolidate_task_store

        tasks_dir = os.path.join(self.tmpdir, 'tasks')
        _write_entry_file(tasks_dir, 'a.md', _make_entry("Alpha approach"))
        _write_entry_file(tasks_dir, 'b.md', _make_entry("Beta approach"))

        # With always-similar, these should merge
        result = consolidate_task_store(tasks_dir, similarity_fn=lambda a, b: 0.95)
        self.assertGreater(result.merged_count, 0)

    def test_files_with_multiple_entries_handled(self):
        """Files containing multiple entries are parsed and each entry considered."""
        from projects.POC.orchestrator.consolidate_learnings import consolidate_task_store
        from projects.POC.scripts.memory_entry import serialize_memory_file

        tasks_dir = os.path.join(self.tmpdir, 'tasks')
        os.makedirs(tasks_dir)

        # Write a file with two entries
        entries = [
            _make_entry("Always test empty inputs"),
            _make_entry("Always test empty inputs variant"),
        ]
        Path(os.path.join(tasks_dir, 'multi.md')).write_text(serialize_memory_file(entries))
        # And another file with the same content
        _write_entry_file(tasks_dir, 'dup.md', _make_entry("Always test empty inputs"))

        result = consolidate_task_store(tasks_dir)
        # At least 2 entries should have been identified as duplicates
        self.assertGreater(result.original_count, 1)


# ── Pipeline wiring tests ────────────────────────────────────────────────────

class TestConsolidationPipelineWiring(unittest.TestCase):
    """Test that consolidation is wired into extract_learnings."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_consolidate_task_learnings_calls_consolidate_task_store(self):
        """_consolidate_task_learnings delegates to consolidate_task_store for both dirs."""
        from projects.POC.orchestrator.learnings import _consolidate_task_learnings

        project_dir = os.path.join(self.tmpdir, 'project')
        tasks_dir = os.path.join(project_dir, 'tasks')
        proxy_tasks_dir = os.path.join(project_dir, 'proxy-tasks')
        os.makedirs(tasks_dir)
        os.makedirs(proxy_tasks_dir)

        calls = []
        original_consolidate = None
        try:
            from projects.POC.orchestrator import consolidate_learnings as cl_mod
            original_consolidate = cl_mod.consolidate_task_store

            def _mock_consolidate(directory, **kwargs):
                calls.append(directory)
                return cl_mod.ConsolidationResult(0, 0, 0)

            cl_mod.consolidate_task_store = _mock_consolidate
            _consolidate_task_learnings(project_dir=project_dir)
        finally:
            if original_consolidate is not None:
                cl_mod.consolidate_task_store = original_consolidate

        self.assertIn(tasks_dir, calls)
        self.assertIn(proxy_tasks_dir, calls)


# ── Default similarity function tests ────────────────────────────────────────

class TestJaccardSimilarity(unittest.TestCase):
    """Test the default Jaccard token similarity function."""

    def test_identical_strings(self):
        from projects.POC.orchestrator.consolidate_learnings import jaccard_token_similarity
        self.assertAlmostEqual(jaccard_token_similarity("hello world", "hello world"), 1.0)

    def test_completely_different(self):
        from projects.POC.orchestrator.consolidate_learnings import jaccard_token_similarity
        sim = jaccard_token_similarity("alpha beta gamma", "delta epsilon zeta")
        self.assertAlmostEqual(sim, 0.0)

    def test_partial_overlap(self):
        from projects.POC.orchestrator.consolidate_learnings import jaccard_token_similarity
        sim = jaccard_token_similarity("test empty inputs coverage", "test null inputs validation")
        # "test" and "inputs" overlap — 2 shared out of 6 unique
        self.assertGreater(sim, 0.0)
        self.assertLess(sim, 1.0)

    def test_empty_strings(self):
        from projects.POC.orchestrator.consolidate_learnings import jaccard_token_similarity
        self.assertAlmostEqual(jaccard_token_similarity("", ""), 0.0)


if __name__ == '__main__':
    unittest.main()
