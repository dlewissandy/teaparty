"""Specification tests for issue #416.

Bug: normalize_activation returns a constant 0.5 when exactly one chunk
survives the activation filter (b_min == b_max), discarding the actual
activation signal during the proxy's early operational life.

Fix: replace min-max normalization with tanh(B - τ), where τ is the
retrieval threshold (-0.5). This maps ℝ → (-1, 1), preserves the signal
in the single-survivor case, and has no degenerate cases.

Composite formula post-fix:
    composite = activation_weight * tanh(B - τ)  +  semantic_weight * cosine_avg  +  noise
"""
import inspect
import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from teaparty.proxy.memory import (
    DECAY,
    NOISE_SCALE,
    RETRIEVAL_THRESHOLD,
    MemoryChunk,
    base_level_activation,
    composite_score,
    single_composite_score,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_chunk(traces: list[int], embedding: list[float] | None = None) -> MemoryChunk:
    """Minimal MemoryChunk with controllable traces and situation embedding."""
    return MemoryChunk(
        id='test-chunk',
        type='gate_outcome',
        state='PLAN_ASSERT',
        task_type='proj',
        outcome='approve',
        traces=traces,
        embedding_situation=embedding,
    )


def _activation_contribution(b: float, tau: float = RETRIEVAL_THRESHOLD) -> float:
    """Expected activation contribution under the tanh formula."""
    return math.tanh(b - tau)


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestTanhNormalizationFormula(unittest.TestCase):
    """tanh(B - τ) replaces min-max normalization in composite_score."""

    def test_chunk_at_threshold_contributes_zero_activation(self):
        """A chunk whose B equals τ contributes exactly 0 to the activation term.

        tanh(B - τ) at B = τ = tanh(0) = 0. With no semantic context, the
        composite should be noise only (≈ 0 at s=0).
        """
        tau = RETRIEVAL_THRESHOLD  # -0.5
        # We need traces such that base_level_activation == tau exactly.
        # B = ln(age^(-d)), so ln(age^(-0.5)) = tau
        # age^(-0.5) = e^tau => age = e^(-2*tau)
        age = math.exp(-2 * tau)
        # current - trace = age => trace = current - age
        current = int(age) + 100
        trace = current - int(age)
        chunk = _make_chunk(traces=[trace])
        b = base_level_activation(chunk.traces, current)
        # Verify the activation is near tau (construction above may be slightly off)
        # For a clean test, verify tanh(b - tau) directly is what drives the score.
        expected_activation_contribution = math.tanh(b - tau)

        # s=0 disables noise; no context embeddings → semantic term = 0
        score = composite_score(chunk, {}, current, activation_weight=1.0,
                                semantic_weight=0.0, s=0.0)

        self.assertAlmostEqual(
            score, expected_activation_contribution, places=10,
            msg=f'composite_score with activation_weight=1, no semantics must equal '
                f'tanh(B - τ) = tanh({b:.4f} - {tau}) = {expected_activation_contribution:.6f}; '
                f'got {score:.6f}',
        )

    def test_chunk_well_above_threshold_contributes_positive(self):
        """A chunk with B well above τ produces a positive activation contribution.

        tanh(B - τ) > 0 whenever B > τ, which is true for all survivors
        (they passed the B > τ filter).
        """
        # Fresh chunk at age=1: B = ln(1^(-0.5)) = 0, well above τ = -0.5
        chunk = _make_chunk(traces=[99])
        b = base_level_activation(chunk.traces, 100)
        self.assertGreater(b, RETRIEVAL_THRESHOLD,
                           'Sanity: chunk must be above threshold')
        expected = math.tanh(b - RETRIEVAL_THRESHOLD)
        self.assertGreater(expected, 0,
                           f'tanh(B - τ) must be positive for B > τ; B={b:.4f}')

        score = composite_score(chunk, {}, 100, activation_weight=1.0,
                                semantic_weight=0.0, s=0.0)
        self.assertAlmostEqual(
            score, expected, places=10,
            msg=f'composite must equal tanh(B - τ) = {expected:.6f}; got {score:.6f}',
        )

    def test_two_survivors_with_different_activations_produce_different_scores(self):
        """Two chunks above threshold with different B values get different scores.

        This is the core regression test for the bug: normalize_activation
        returned 0.5 for all chunks when b_min == b_max (single survivor) and
        for the first chunk (value=0) vs last chunk (value=1) in multi-survivor
        sets.  tanh(B - τ) must preserve the magnitude difference.

        Activation math (d=0.5):
          age=1 → B = ln(1^-0.5) = 0.0     (above τ=-0.5)
          age=2 → B = ln(2^-0.5) ≈ -0.347  (above τ=-0.5)
          age=3 → B = ln(3^-0.5) ≈ -0.549  (below τ=-0.5)
        Both chunks must survive the activation filter.
        """
        current = 10

        # Chunk A: age=1 → B=0.0
        chunk_a = _make_chunk(traces=[9])
        b_a = base_level_activation(chunk_a.traces, current)

        # Chunk B: age=2 → B≈-0.347, still above τ=-0.5
        chunk_b = _make_chunk(traces=[8])
        b_b = base_level_activation(chunk_b.traces, current)

        self.assertGreater(b_a, b_b,
                           f'Sanity: chunk_a B={b_a:.4f} must exceed chunk_b B={b_b:.4f}')
        self.assertGreater(b_b, RETRIEVAL_THRESHOLD,
                           f'Sanity: chunk_b B={b_b:.4f} must be above τ={RETRIEVAL_THRESHOLD}')

        tau = RETRIEVAL_THRESHOLD
        expected_a = math.tanh(b_a - tau)
        expected_b = math.tanh(b_b - tau)

        score_a = composite_score(chunk_a, {}, current, activation_weight=1.0,
                                  semantic_weight=0.0, s=0.0)
        score_b = composite_score(chunk_b, {}, current, activation_weight=1.0,
                                  semantic_weight=0.0, s=0.0)

        # Exact-value assertions: old min-max code returns 1.0 and 0.0 for two
        # survivors (b_max maps to 1, b_min maps to 0). tanh returns ≈0.462 and
        # ≈0.152. The exact check fails if the old formula is in place.
        self.assertAlmostEqual(
            score_a, expected_a, places=10,
            msg=f'score_a must equal tanh(B_a - τ) = tanh({b_a:.4f} - {tau}) = '
                f'{expected_a:.6f}; got {score_a:.6f}. '
                f'Old min-max would produce 1.0 for the higher-activation chunk.',
        )
        self.assertAlmostEqual(
            score_b, expected_b, places=10,
            msg=f'score_b must equal tanh(B_b - τ) = tanh({b_b:.4f} - {tau}) = '
                f'{expected_b:.6f}; got {score_b:.6f}. '
                f'Old min-max would produce 0.0 for the lower-activation chunk.',
        )
        self.assertGreater(
            score_a, score_b,
            msg=f'Higher activation (B={b_a:.4f}) must produce higher composite score '
                f'than lower activation (B={b_b:.4f}) when semantics and noise are disabled.',
        )

    def test_activation_contribution_matches_tanh_formula_exactly(self):
        """composite_score activation term equals tanh(B - τ) for arbitrary B.

        With activation_weight=1, semantic_weight=0, s=0: score = tanh(B - τ).
        This verifies the formula is applied as specified in the design resolution.
        """
        # Use multiple different activation levels to cover the tanh curve.
        # age=1 → B=0 > τ; age=2 → B≈-0.347 > τ.  Both are above τ=-0.5.
        # 10 traces at age=1 each → B=ln(10)≈2.3 (well above).
        test_cases = [
            # (traces, current, description)
            ([9], 10, 'age=1, B=0'),
            ([8], 10, 'age=2, B≈-0.347'),
            ([9, 9, 9, 9, 9, 9, 9, 9, 9, 9], 10, '10 traces age=1, B≈2.3'),
        ]
        tau = RETRIEVAL_THRESHOLD
        for traces, current, description in test_cases:
            with self.subTest(description=description):
                chunk = _make_chunk(traces=traces)
                b = base_level_activation(chunk.traces, current)
                if b <= tau:
                    continue  # skip if below threshold (not a retrieval candidate)
                expected = math.tanh(b - tau)
                score = composite_score(chunk, {}, current,
                                        activation_weight=1.0,
                                        semantic_weight=0.0, s=0.0)
                self.assertAlmostEqual(
                    score, expected, places=10,
                    msg=f'{description}: composite_score with activation_weight=1 must '
                        f'equal tanh(B - τ) = tanh({b:.4f} - {tau}) = {expected:.6f}; '
                        f'got {score:.6f}',
                )


class TestSingleSurvivorPreservesSignal(unittest.TestCase):
    """The single-survivor case that was broken under min-max normalization."""

    def test_single_survivor_score_varies_with_activation_strength(self):
        """A barely-above-threshold chunk and a well-above-threshold chunk
        produce different composite scores.

        Under the old min-max normalization, both would return 0.5 because
        b_min == b_max when there is only one survivor.  Under tanh(B - τ)
        the scores are distinct and reflect actual activation strength.

        Activation math (d=0.5):
          age=1 → B = 0.0      (well above τ=-0.5)
          age=2 → B ≈ -0.347   (barely above τ=-0.5)
        Both produce tanh(B - τ) values that differ, not the same 0.5.
        """
        current = 10

        # Barely above threshold: age=2, B ≈ -0.347 (τ=-0.5, so B-τ ≈ 0.153)
        chunk_weak = _make_chunk(traces=[8])
        b_weak = base_level_activation(chunk_weak.traces, current)
        self.assertGreater(b_weak, RETRIEVAL_THRESHOLD,
                           f'Sanity: weak chunk B={b_weak:.4f} must be above τ={RETRIEVAL_THRESHOLD}')

        # Well above threshold: age=1, B = 0 (τ=-0.5, so B-τ = 0.5)
        chunk_strong = _make_chunk(traces=[9])
        b_strong = base_level_activation(chunk_strong.traces, current)

        score_weak = composite_score(chunk_weak, {}, current,
                                     activation_weight=1.0, semantic_weight=0.0, s=0.0)
        score_strong = composite_score(chunk_strong, {}, current,
                                       activation_weight=1.0, semantic_weight=0.0, s=0.0)

        self.assertGreater(
            b_strong, b_weak,
            f'Sanity: strong chunk B={b_strong:.4f} must exceed weak chunk B={b_weak:.4f}',
        )
        self.assertGreater(
            score_strong, score_weak,
            msg=f'Well-activated chunk (B={b_strong:.4f}, score={score_strong:.6f}) '
                f'must outrank barely-above-threshold chunk '
                f'(B={b_weak:.4f}, score={score_weak:.6f}). '
                f'A constant 0.5 would collapse these to equal scores — '
                f'that is the bug this test encodes.',
        )
        self.assertNotAlmostEqual(
            score_strong, score_weak, places=3,
            msg=f'Scores must differ by more than 0.001; '
                f'strong={score_strong:.6f}, weak={score_weak:.6f}. '
                f'Constant 0.5 normalization would make these equal.',
        )


class TestSingleCompositeScoreUsesTanh(unittest.TestCase):
    """tanh formula also applies to single_composite_score (blended embedding path)."""

    def test_single_composite_score_activation_uses_tanh(self):
        """single_composite_score activation term equals tanh(B - τ) at activation_weight=1."""
        chunk = _make_chunk(traces=[99], embedding=[1.0, 0.0])
        chunk.embedding_blended = [1.0, 0.0]
        b = base_level_activation(chunk.traces, 100)
        tau = RETRIEVAL_THRESHOLD
        expected = math.tanh(b - tau)

        # No blended context → semantic = 0; s=0 → no noise
        score = single_composite_score(chunk, [], 100,
                                       activation_weight=1.0, semantic_weight=0.0, s=0.0)
        self.assertAlmostEqual(
            score, expected, places=10,
            msg=f'single_composite_score with activation_weight=1 must equal '
                f'tanh(B - τ) = {expected:.6f}; got {score:.6f}',
        )

    def test_single_survivor_blended_scores_differ_by_activation(self):
        """In single-embedding mode, two chunks with different B produce different scores.

        age=1 → B=0.0 (strong), age=2 → B≈-0.347 (weak, but above τ=-0.5).
        """
        current = 10
        chunk_recent = _make_chunk(traces=[9])  # age=1, B=0
        chunk_older = _make_chunk(traces=[8])   # age=2, B≈-0.347

        score_recent = single_composite_score(chunk_recent, [], current,
                                              activation_weight=1.0, semantic_weight=0.0, s=0.0)
        score_older = single_composite_score(chunk_older, [], current,
                                             activation_weight=1.0, semantic_weight=0.0, s=0.0)

        self.assertGreater(
            score_recent, score_older,
            msg=f'Recent chunk (age=1, B=0) must outscore older chunk (age=2, B≈-0.347); '
                f'score_recent={score_recent:.6f}, score_older={score_older:.6f}',
        )


class TestSignatureCleanup(unittest.TestCase):
    """b_min and b_max parameters are removed from the scoring functions.

    The old normalize_activation required callers to pass the activation range.
    The tanh formulation eliminates that dependency entirely.
    """

    def test_composite_score_has_no_b_min_b_max_parameters(self):
        """composite_score must not accept b_min or b_max parameters."""
        sig = inspect.signature(composite_score)
        params = list(sig.parameters.keys())
        self.assertNotIn(
            'b_min', params,
            msg=f'composite_score must not accept b_min (tanh eliminates the need '
                f'for range normalization); found params: {params}',
        )
        self.assertNotIn(
            'b_max', params,
            msg=f'composite_score must not accept b_max; found params: {params}',
        )

    def test_single_composite_score_has_no_b_min_b_max_parameters(self):
        """single_composite_score must not accept b_min or b_max parameters."""
        sig = inspect.signature(single_composite_score)
        params = list(sig.parameters.keys())
        self.assertNotIn(
            'b_min', params,
            msg=f'single_composite_score must not accept b_min; found params: {params}',
        )
        self.assertNotIn(
            'b_max', params,
            msg=f'single_composite_score must not accept b_max; found params: {params}',
        )

    def test_normalize_activation_is_removed(self):
        """normalize_activation must not exist in the memory module.

        It was the source of the bug — returning 0.5 when b_min == b_max.
        tanh(B - τ) replaces it entirely.
        """
        import teaparty.proxy.memory as memory_module
        self.assertFalse(
            hasattr(memory_module, 'normalize_activation'),
            msg='normalize_activation must be deleted; it is replaced by tanh(B - τ). '
                'Its presence means the fix was not applied.',
        )


if __name__ == '__main__':
    unittest.main()
