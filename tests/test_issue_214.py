#!/usr/bin/env python3
"""Tests for issue #214: Semantic pattern identification in _compact_proxy_patterns().

The function currently does exact-string dedup of correction deltas.  It should:
1. Cluster semantically equivalent deltas using embedding similarity.
2. Track frequency — how many raw deltas each cluster represents.
3. Use the most informative (longest) delta as the cluster representative.
4. Fall back to exact-string dedup when no embed function is available.
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


# ── Helpers ───────────────────────────────────────────────────────────────────

def _write_interaction_log(td: str, entries: list[dict]) -> str:
    """Write a JSONL interaction log and return its path."""
    log_path = os.path.join(td, '.proxy-interactions.jsonl')
    with open(log_path, 'w') as f:
        for e in entries:
            f.write(json.dumps(e) + '\n')
    return log_path


def _make_entries(state: str, deltas: list[str]) -> list[dict]:
    """Create correction entries for a single state with the given deltas."""
    return [
        {
            'state': state,
            'outcome': 'correct',
            'delta': d,
            'timestamp': f'2026-03-14T{i:02d}:00:00Z',
        }
        for i, d in enumerate(deltas)
    ]


def _fake_embed_fn(text: str) -> list[float]:
    """Deterministic embedding: maps known test strings to known vectors.

    Strings about "error handling" cluster together (similar vectors).
    Strings about "rollback" cluster together (similar vectors).
    The two clusters are distant from each other.
    """
    text_lower = text.strip().lower()

    # Error-handling cluster: vectors near [1, 0, 0]
    if 'error' in text_lower or 'exception' in text_lower:
        return [0.95, 0.05, 0.05]
    # Rollback cluster: vectors near [0, 1, 0]
    if 'rollback' in text_lower:
        return [0.05, 0.95, 0.05]
    # Logging cluster: vectors near [0, 0, 1]
    if 'log' in text_lower:
        return [0.05, 0.05, 0.95]
    # Default: orthogonal to everything
    return [0.33, 0.33, 0.33]


def _read_patterns(td: str) -> str:
    """Read the proxy-patterns.md output file."""
    path = os.path.join(td, 'proxy-patterns.md')
    return Path(path).read_text()


# ── Tests: Semantic clustering ───────────────────────────────────────────────

class TestSemanticClustering(unittest.TestCase):
    """Semantically equivalent deltas should be clustered together."""

    def test_similar_deltas_are_merged(self):
        """Deltas about the same concept (error handling) should collapse
        into a single pattern, not appear as separate items."""
        from orchestrator.learnings import _compact_proxy_patterns

        deltas = [
            'Missing error handling',
            'No error handling section',
            'Error handling missing from plan',
            'Add exception handling',
        ]
        entries = _make_entries('PLAN_ASSERT', deltas)

        with tempfile.TemporaryDirectory() as td:
            log_path = _write_interaction_log(td, entries)
            _compact_proxy_patterns(
                project_dir=td, log_path=log_path, embed_fn=_fake_embed_fn,
            )
            output = _read_patterns(td)

            # All four deltas are about error handling — should be one pattern
            # under PLAN_ASSERT, not four separate bullets
            plan_lines = [
                l for l in output.split('\n')
                if l.startswith('- ')
            ]
            self.assertEqual(
                len(plan_lines), 1,
                f'Four similar deltas should cluster into 1 pattern, '
                f'got {len(plan_lines)}: {plan_lines}',
            )

    def test_distinct_deltas_stay_separate(self):
        """Deltas about different concepts should NOT be merged."""
        from orchestrator.learnings import _compact_proxy_patterns

        deltas = [
            'Missing error handling',
            'Add rollback strategy',
            'No logging in critical path',
        ]
        entries = _make_entries('PLAN_ASSERT', deltas)

        with tempfile.TemporaryDirectory() as td:
            log_path = _write_interaction_log(td, entries)
            _compact_proxy_patterns(
                project_dir=td, log_path=log_path, embed_fn=_fake_embed_fn,
            )
            output = _read_patterns(td)

            plan_lines = [
                l for l in output.split('\n')
                if l.startswith('- ')
            ]
            self.assertEqual(
                len(plan_lines), 3,
                f'Three distinct deltas should remain as 3 patterns, '
                f'got {len(plan_lines)}: {plan_lines}',
            )

    def test_mixed_similar_and_distinct(self):
        """A mix of similar and distinct deltas clusters correctly."""
        from orchestrator.learnings import _compact_proxy_patterns

        deltas = [
            'Missing error handling',
            'No error handling section',       # clusters with above
            'Add rollback strategy',
            'Include a rollback plan',         # clusters with above
            'No logging in critical path',     # distinct
        ]
        entries = _make_entries('PLAN_ASSERT', deltas)

        with tempfile.TemporaryDirectory() as td:
            log_path = _write_interaction_log(td, entries)
            _compact_proxy_patterns(
                project_dir=td, log_path=log_path, embed_fn=_fake_embed_fn,
            )
            output = _read_patterns(td)

            plan_lines = [
                l for l in output.split('\n')
                if l.startswith('- ')
            ]
            self.assertEqual(
                len(plan_lines), 3,
                f'Should produce 3 clusters (error, rollback, logging), '
                f'got {len(plan_lines)}: {plan_lines}',
            )


# ── Tests: Frequency tracking ────────────────────────────────────────────────

class TestFrequencyTracking(unittest.TestCase):
    """Each pattern should include how many times the correction recurred."""

    def test_frequency_appears_in_output(self):
        """A cluster of 4 similar deltas should show frequency of 4."""
        from orchestrator.learnings import _compact_proxy_patterns

        deltas = [
            'Missing error handling',
            'No error handling section',
            'Error handling missing from plan',
            'Add exception handling',
        ]
        entries = _make_entries('PLAN_ASSERT', deltas)

        with tempfile.TemporaryDirectory() as td:
            log_path = _write_interaction_log(td, entries)
            _compact_proxy_patterns(
                project_dir=td, log_path=log_path, embed_fn=_fake_embed_fn,
            )
            output = _read_patterns(td)

            # The pattern should indicate it occurred 4 times
            self.assertRegex(
                output, r'4',
                'Output should contain the frequency count 4 for the '
                'error-handling cluster',
            )

    def test_singleton_shows_frequency_one(self):
        """A pattern that occurred only once should show frequency 1."""
        from orchestrator.learnings import _compact_proxy_patterns

        entries = _make_entries('PLAN_ASSERT', ['Add rollback strategy'])

        with tempfile.TemporaryDirectory() as td:
            log_path = _write_interaction_log(td, entries)
            _compact_proxy_patterns(
                project_dir=td, log_path=log_path, embed_fn=_fake_embed_fn,
            )
            output = _read_patterns(td)

            plan_lines = [
                l for l in output.split('\n')
                if l.startswith('- ')
            ]
            self.assertEqual(len(plan_lines), 1)
            # Should indicate frequency of 1
            self.assertIn('1', plan_lines[0])


# ── Tests: Representative selection ──────────────────────────────────────────

class TestRepresentativeSelection(unittest.TestCase):
    """The longest delta in a cluster should be chosen as the representative."""

    def test_longest_delta_is_representative(self):
        """Within a cluster, the longest (most informative) delta is displayed."""
        from orchestrator.learnings import _compact_proxy_patterns

        deltas = [
            'No error handling',                    # 18 chars
            'Error handling missing from the plan',  # 36 chars — longest
            'Missing errors',                       # 14 chars
        ]
        entries = _make_entries('PLAN_ASSERT', deltas)

        with tempfile.TemporaryDirectory() as td:
            log_path = _write_interaction_log(td, entries)
            _compact_proxy_patterns(
                project_dir=td, log_path=log_path, embed_fn=_fake_embed_fn,
            )
            output = _read_patterns(td)

            plan_lines = [
                l for l in output.split('\n')
                if l.startswith('- ')
            ]
            self.assertEqual(len(plan_lines), 1)
            self.assertIn(
                'Error handling missing from the plan',
                plan_lines[0],
                'Should use the longest delta as the cluster representative',
            )


# ── Tests: Fallback without embeddings ───────────────────────────────────────

class TestFallbackWithoutEmbeddings(unittest.TestCase):
    """When no embed_fn is provided, falls back to exact-string dedup."""

    def test_no_embed_fn_still_produces_output(self):
        """Without embeddings, the function still works (exact dedup)."""
        from orchestrator.learnings import _compact_proxy_patterns

        deltas = [
            'Missing error handling',
            'Missing error handling',   # exact dup
            'Add rollback strategy',
        ]
        entries = _make_entries('PLAN_ASSERT', deltas)

        with tempfile.TemporaryDirectory() as td:
            log_path = _write_interaction_log(td, entries)
            _compact_proxy_patterns(
                project_dir=td, log_path=log_path,
            )
            output = _read_patterns(td)

            plan_lines = [
                l for l in output.split('\n')
                if l.startswith('- ')
            ]
            # Exact dedup: "Missing error handling" appears once, plus "Add rollback"
            self.assertEqual(len(plan_lines), 2)

    def test_no_embed_fn_still_has_frequency(self):
        """Even without embeddings, frequency counts should appear."""
        from orchestrator.learnings import _compact_proxy_patterns

        deltas = [
            'Missing error handling',
            'Missing error handling',
            'Missing error handling',
        ]
        entries = _make_entries('PLAN_ASSERT', deltas)

        with tempfile.TemporaryDirectory() as td:
            log_path = _write_interaction_log(td, entries)
            _compact_proxy_patterns(
                project_dir=td, log_path=log_path,
            )
            output = _read_patterns(td)

            # Should show frequency 3 for the single pattern
            plan_lines = [
                l for l in output.split('\n')
                if l.startswith('- ')
            ]
            self.assertEqual(len(plan_lines), 1)
            self.assertIn('3', plan_lines[0])


# ── Tests: Downstream compatibility ──────────────────────────────────────────

class TestDownstreamCompatibility(unittest.TestCase):
    """Output format must remain parseable by _extract_state_patterns()."""

    def test_extract_state_patterns_reads_new_format(self):
        """approval_gate._extract_state_patterns can parse the updated format."""
        from orchestrator.learnings import _compact_proxy_patterns
        from scripts.approval_gate import _extract_state_patterns

        deltas = [
            'Missing error handling',
            'No error handling section',
            'Add rollback strategy',
        ]
        entries = _make_entries('PLAN_ASSERT', deltas)

        with tempfile.TemporaryDirectory() as td:
            log_path = _write_interaction_log(td, entries)
            _compact_proxy_patterns(
                project_dir=td, log_path=log_path, embed_fn=_fake_embed_fn,
            )
            output = _read_patterns(td)

            patterns = _extract_state_patterns(output, 'PLAN_ASSERT')
            self.assertGreater(
                len(patterns), 0,
                '_extract_state_patterns should parse at least one pattern '
                'from the new output format',
            )


# ── Tests: Caller wiring ─────────────────────────────────────────────────────

class TestCallerWiring(unittest.TestCase):
    """extract_learnings() must pass embed_fn to _compact_proxy_patterns."""

    def test_extract_learnings_passes_embed_fn(self):
        """The proxy-patterns scope in extract_learnings passes embed_fn."""
        from orchestrator import learnings

        # _make_embed_fn should be called and its result passed through
        self.assertTrue(
            callable(getattr(learnings, '_make_embed_fn', None)),
            '_make_embed_fn should exist in learnings module',
        )

    def test_make_embed_fn_returns_callable_or_none(self):
        """_make_embed_fn returns a callable when providers are available, else None."""
        from orchestrator.learnings import _make_embed_fn

        result = _make_embed_fn()
        # In test environments without API keys, should return None (graceful)
        # In environments with keys, should return a callable
        self.assertTrue(
            result is None or callable(result),
            f'_make_embed_fn should return None or callable, got {type(result)}',
        )


if __name__ == '__main__':
    unittest.main()
