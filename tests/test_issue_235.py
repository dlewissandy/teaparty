"""Tests for Issue #235: Noise scale calibration and sensitivity analysis.

The logistic noise in composite_score() must not dominate the deterministic
signal.  The noise scale should be small enough that the signal difference
between best and worst candidates is rarely overridden by noise.

Additionally, the ablation harness should support noise-scale sweep so that
the effect of different noise levels on retrieval quality can be measured.
"""
from __future__ import annotations

import math
import os
import random
import tempfile
import unittest

from orchestrator.proxy_memory import (
    NOISE_SCALE,
    MemoryChunk,
    composite_score,
    logistic_noise,
    open_proxy_db,
    store_chunk,
    run_scoring_ablation,
)


def _make_chunk(
    chunk_id: str = 'test-chunk',
    state: str = 'PLAN_ASSERT',
    task_type: str = 'security',
    outcome: str = 'approve',
    traces: list[int] | None = None,
    **kwargs,
) -> MemoryChunk:
    defaults = dict(
        id=chunk_id,
        type='gate_outcome',
        state=state,
        task_type=task_type,
        outcome=outcome,
        content='test interaction content',
        traces=traces or [1],
        embedding_model='test/test',
    )
    defaults.update(kwargs)
    return MemoryChunk(**defaults)


def _make_db(tmpdir: str, chunks: list[MemoryChunk], counter: int = 20):
    """Seed a proxy memory DB with chunks and return the connection."""
    db_path = os.path.join(tmpdir, '.proxy-memory.db')
    conn = open_proxy_db(db_path)
    for chunk in chunks:
        store_chunk(conn, chunk)
    conn.execute(
        "UPDATE proxy_state SET value=? WHERE key='interaction_counter'",
        (counter,),
    )
    conn.commit()
    return conn, db_path


class TestNoiseScaleCalibration(unittest.TestCase):
    """NOISE_SCALE must be calibrated so noise does not dominate signal."""

    def test_noise_scale_below_signal_range(self):
        """The logistic std dev (pi * s / sqrt(3)) must be less than the
        typical deterministic signal difference between candidates.

        With weights 0.5/0.5 and signals in [0, 1], a representative
        signal difference between best and worst candidates is ~0.3.
        The noise std dev must be well below this — at most 0.15 — so
        that noise perturbs but does not dominate ranking.
        """
        std_dev = math.pi * NOISE_SCALE / math.sqrt(3)
        self.assertLess(
            std_dev, 0.15,
            f'Noise std dev {std_dev:.3f} exceeds 0.15; noise dominates signal'
        )

    def test_noise_rarely_exceeds_full_signal_range(self):
        """Over many samples, noise should rarely exceed the typical signal
        difference between candidates (~0.3).  At most 5% of samples should
        exceed this threshold — meaning noise almost never fully overrides
        the ranking signal."""
        random.seed(42)
        samples = [abs(logistic_noise(NOISE_SCALE)) for _ in range(10000)]
        exceed_count = sum(1 for s in samples if s > 0.3)
        exceed_pct = exceed_count / len(samples)
        self.assertLess(
            exceed_pct, 0.05,
            f'{exceed_pct:.1%} of noise samples exceed 0.3 (want < 5%)'
        )


class TestNoiseDoesNotDominateRanking(unittest.TestCase):
    """With production noise scale, the better candidate should usually rank
    higher despite noise perturbation."""

    def test_better_candidate_wins_majority(self):
        """A chunk with higher deterministic score should rank first in at
        least 90% of trials when noise is at production scale."""
        vec_a = [1.0, 0.0, 0.0]

        # Chunk with strong match across all 4 experience dimensions
        chunk_good = _make_chunk(
            chunk_id='good', traces=[15, 17, 19],
            embedding_situation=vec_a,
            embedding_artifact=vec_a,
            embedding_stimulus=vec_a,
            embedding_response=vec_a,
        )
        # Chunk with no embedding match and fewer traces
        chunk_weak = _make_chunk(
            chunk_id='weak', traces=[5],
            embedding_situation=None,
            embedding_artifact=None,
            embedding_stimulus=None,
            embedding_response=None,
        )

        context = {
            'situation': vec_a,
            'artifact': vec_a,
            'stimulus': vec_a,
            'response': vec_a,
        }

        random.seed(42)
        wins = 0
        trials = 1000
        for _ in range(trials):
            score_good = composite_score(
                chunk_good, context, current_interaction=20,
                b_min=0.0, b_max=2.0, s=NOISE_SCALE,
            )
            score_weak = composite_score(
                chunk_weak, context, current_interaction=20,
                b_min=0.0, b_max=2.0, s=NOISE_SCALE,
            )
            if score_good > score_weak:
                wins += 1

        win_rate = wins / trials
        self.assertGreater(
            win_rate, 0.90,
            f'Better candidate only won {win_rate:.1%} of trials (want > 90%)'
        )


class TestNoiseScaleAblation(unittest.TestCase):
    """The ablation harness must support noise-scale sensitivity analysis."""

    def test_run_scoring_ablation_accepts_noise_scales(self):
        """run_scoring_ablation() must accept a noise_scales parameter and
        return results for each noise level."""
        chunks = [
            _make_chunk(
                chunk_id=f'chunk-{i}',
                outcome='approve' if i % 2 == 0 else 'correct',
                traces=[i],
                embedding_situation=[float(i % 3), float(i % 2), 0.0],
            )
            for i in range(1, 11)
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            conn, _ = _make_db(tmpdir, chunks, counter=15)
            result = run_scoring_ablation(
                conn,
                checkpoints=[10],
                noise_scales=[0.0, 0.05, 0.1],
                trials_per_noise=5,
            )
            conn.close()

        # The result should contain noise-scale sweep data
        self.assertTrue(
            hasattr(result, 'noise_sensitivity'),
            'AblationResult must have noise_sensitivity attribute'
        )
        self.assertIn(0.0, result.noise_sensitivity)
        self.assertIn(0.05, result.noise_sensitivity)
        self.assertIn(0.1, result.noise_sensitivity)

    def test_noise_sensitivity_includes_mean_and_std(self):
        """Each noise level in the sensitivity results should report
        mean and std of match rates across trials."""
        chunks = [
            _make_chunk(
                chunk_id=f'chunk-{i}',
                outcome='approve' if i % 2 == 0 else 'correct',
                traces=[i],
                embedding_situation=[float(i % 3), float(i % 2), 0.0],
            )
            for i in range(1, 11)
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            conn, _ = _make_db(tmpdir, chunks, counter=15)
            result = run_scoring_ablation(
                conn,
                checkpoints=[10],
                noise_scales=[0.0, 0.1],
                trials_per_noise=10,
            )
            conn.close()

        for s_val in [0.0, 0.1]:
            entry = result.noise_sensitivity[s_val]
            self.assertIn('mean', entry)
            self.assertIn('std', entry)
            # s=0.0 should have zero std (deterministic)
            if s_val == 0.0:
                self.assertAlmostEqual(entry['std'], 0.0, places=10)

    def test_noise_sensitivity_summary_in_output(self):
        """AblationResult.summary() should include noise sensitivity data."""
        chunks = [
            _make_chunk(
                chunk_id=f'chunk-{i}',
                outcome='approve' if i % 2 == 0 else 'correct',
                traces=[i],
                embedding_situation=[float(i % 3), float(i % 2), 0.0],
            )
            for i in range(1, 11)
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            conn, _ = _make_db(tmpdir, chunks, counter=15)
            result = run_scoring_ablation(
                conn,
                checkpoints=[10],
                noise_scales=[0.0, 0.1, 0.25],
                trials_per_noise=5,
            )
            conn.close()

        summary = result.summary()
        self.assertIn('Noise', summary)
        self.assertIn('0.1', summary)


if __name__ == '__main__':
    unittest.main()
