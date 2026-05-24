"""Specification tests for issue #434.

Three changes to the proxy ACT-R memory (teaparty/proxy/memory.py):

P0 — Capacity bound. Today nothing removes a chunk for merely decaying:
    soft-delete/purge (#236) is concurrency-only, and consolidation (#228)
    only removes chunks involved in a *contradiction*. A chunk that falls
    below the retrieval threshold τ and is never reinforced or contradicted
    is retained forever. `evict_stale_chunks` adds the missing eviction:
    chunks that are below τ AND dormant (no trace within an eviction window)
    are soft-deleted — except `review_correction` and `steering` chunks,
    which encode direct human teaching and must never be silently dropped.
    Eviction is wired into the session-end consolidation pass.

P2 — Tunable cosine dimension weights. The conversation/job/project weights
    (0.9/0.05/0.05) were hardcoded module constants. They become a parameter
    of composite_score/retrieve_chunks (default unchanged) and gain ablation
    configs, so they can be tuned from data rather than guessed.

P2 — Noise decision. NOISE_SCALE=0.08 was a non-decision (too small to
    randomize, nonzero). Resolved to 0.0 (deterministic retrieval); a test
    pins both the value and the resulting determinism.

Out of scope (do NOT test for here): reverting tanh to min-max (#416 keeps
    tanh deliberately); the cosine-spread/anisotropy remap (deferred pending
    real embedding-distribution data).
"""
from __future__ import annotations

import math
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from teaparty.proxy.memory import (  # noqa: E402
    NOISE_SCALE,
    RETRIEVAL_THRESHOLD,
    ABLATION_CONFIGS,
    MemoryChunk,
    base_level_activation,
    composite_score,
    get_interaction_counter,
    open_proxy_db,
    purge_deleted_chunks,
    query_chunks,
    store_chunk,
)


# ── Helpers ────────────────────────────────────────────────────────────────

def _set_counter(conn, value: int) -> None:
    conn.execute(
        "UPDATE proxy_state SET value=? WHERE key='interaction_counter'", (value,),
    )
    conn.commit()


def _store(conn, *, id: str, traces: list[int], type: str = 'gate_outcome',
           task_type: str = 'proj', outcome: str = 'approve',
           emb_job: list[float] | None = None) -> None:
    store_chunk(conn, MemoryChunk(
        id=id, type=type, state='PLAN_ASSERT', task_type=task_type,
        outcome=outcome, content=f'content-{id}', traces=traces,
        embedding_job=emb_job,
    ))


def _row_exists(conn, chunk_id: str) -> bool:
    """True if the row is physically present (regardless of soft-delete)."""
    return conn.execute(
        'SELECT 1 FROM proxy_chunks WHERE id=?', (chunk_id,),
    ).fetchone() is not None


def _is_active(conn, chunk_id: str) -> bool:
    """True if the chunk is retrievable (present and not soft-deleted)."""
    return any(c.id == chunk_id for c in query_chunks(conn))


class _DBTest(unittest.TestCase):
    def setUp(self) -> None:
        self._dir = tempfile.mkdtemp()
        self.db_path = str(Path(self._dir) / '.proxy-memory.db')
        self.conn = open_proxy_db(self.db_path)

    def tearDown(self) -> None:
        self.conn.close()


# ── P0: capacity-bound eviction ─────────────────────────────────────────────

class TestEvictStaleChunks(_DBTest):
    """evict_stale_chunks soft-deletes decayed, dormant, non-exempt chunks."""

    def _evict(self, current: int, **kw):
        from teaparty.proxy.memory import evict_stale_chunks
        return evict_stale_chunks(self.conn, current, **kw)

    def test_dormant_below_threshold_chunk_is_evicted(self):
        """A chunk below τ whose only trace is older than the window is evicted.

        trace age 60 (window 50): B = ln(60^-0.5) ≈ -2.05 < τ=-0.5, and
        60 ≥ 50 ⇒ dormant. This is the unbounded-growth case the issue fixes.
        """
        current = 100
        _set_counter(self.conn, current)
        _store(self.conn, id='stale', traces=[current - 60])
        b = base_level_activation([current - 60], current)
        self.assertLess(b, RETRIEVAL_THRESHOLD,
                        f'fixture: B={b:.3f} must be below τ={RETRIEVAL_THRESHOLD}')

        evicted = self._evict(current, window=50)

        self.assertEqual(
            evicted, ['stale'],
            f'evict_stale_chunks must return exactly the stale chunk id; got {evicted}',
        )
        self.assertFalse(
            _is_active(self.conn, 'stale'),
            'stale chunk must be excluded from retrieval after eviction',
        )

    def test_recent_below_threshold_chunk_is_retained(self):
        """A below-τ chunk touched within the window is NOT evicted.

        trace age 40 (window 50): B ≈ -1.84 < τ, but 40 < 50 ⇒ recent.
        The window guard protects freshly-created / recently-touched chunks
        from being evicted before they have a chance to be reinforced.
        """
        current = 100
        _set_counter(self.conn, current)
        _store(self.conn, id='recent', traces=[current - 40])

        evicted = self._evict(current, window=50)

        self.assertNotIn(
            'recent', evicted,
            'a chunk whose newest trace is inside the window must not be evicted '
            'even when its activation is below τ (context-triggered-recall guard)',
        )
        self.assertTrue(_is_active(self.conn, 'recent'),
                        'recent chunk must remain retrievable')

    def test_frequent_above_threshold_chunk_is_retained(self):
        """A dormant chunk kept above τ by frequency is NOT evicted.

        20 traces at age 60: Σ = 20·60^-0.5 ≈ 2.58, B = ln(2.58) ≈ 0.95 > τ.
        Eviction keys on activation, not age alone — frequently-reinforced
        knowledge survives dormancy.
        """
        current = 100
        _set_counter(self.conn, current)
        _store(self.conn, id='frequent', traces=[current - 60] * 20)
        b = base_level_activation([current - 60] * 20, current)
        self.assertGreater(b, RETRIEVAL_THRESHOLD,
                           f'fixture: B={b:.3f} must be above τ')

        evicted = self._evict(current, window=50)

        self.assertNotIn('frequent', evicted,
                         'a chunk above τ must never be evicted regardless of dormancy')
        self.assertTrue(_is_active(self.conn, 'frequent'))

    def test_corrections_and_steering_are_exempt(self):
        """Stale review_correction and steering chunks are never evicted.

        Both are dormant and below τ (single trace age 60), so an unguarded
        eviction would remove them. They encode direct human teaching;
        silently deleting a correction is the opposite of the proxy's purpose.
        """
        current = 100
        _set_counter(self.conn, current)
        _store(self.conn, id='corr', type='review_correction', traces=[current - 60])
        _store(self.conn, id='steer', type='steering', traces=[current - 60])

        evicted = self._evict(current, window=50)

        self.assertNotIn('corr', evicted,
                         'review_correction chunks must be exempt from eviction')
        self.assertNotIn('steer', evicted,
                         'steering chunks must be exempt from eviction')
        self.assertTrue(_is_active(self.conn, 'corr'))
        self.assertTrue(_is_active(self.conn, 'steer'))

    def test_eviction_is_soft_delete_respecting_purge_window(self):
        """Eviction soft-deletes (row stays until the purge safe window).

        A concurrent session may still hold the chunk; the row must persist,
        excluded from retrieval, until purge_deleted_chunks clears it after
        the safe window — never hard-deleted in the same breath (#236).
        """
        current = 100
        _set_counter(self.conn, current)
        _store(self.conn, id='stale', traces=[current - 60])

        self._evict(current, window=50)

        # Soft, not hard: row present, but not retrievable.
        self.assertTrue(_row_exists(self.conn, 'stale'),
                        'evicted chunk row must still physically exist (soft-delete)')
        self.assertFalse(_is_active(self.conn, 'stale'),
                         'evicted chunk must be excluded from retrieval')

        # Too soon to purge (deleted_at == current; window not elapsed).
        purge_deleted_chunks(self.conn, current_interaction=current, safe_window=50)
        self.assertTrue(_row_exists(self.conn, 'stale'),
                        'evicted chunk must survive purge until the safe window elapses')

        # After the safe window, purge hard-deletes it.
        purge_deleted_chunks(self.conn, current_interaction=current + 60, safe_window=50)
        self.assertFalse(_row_exists(self.conn, 'stale'),
                         'evicted chunk must be hard-deleted once the safe window passes')


class TestEvictionWiredIntoConsolidation(unittest.TestCase):
    """The session-end consolidation pass actually performs eviction.

    A module that exists but is never called is not done — the issue requires
    eviction to run as part of _consolidate_proxy_memory.
    """

    def test_consolidation_evicts_only_dormant_below_threshold_chunks(self):
        """The wired consolidation pass evicts a dormant below-τ chunk while
        retaining both an above-τ chunk and a below-τ-but-recent chunk —
        using the shipped STALE_EVICTION_WINDOW default (no explicit window
        passed), so the wired path proves the dormancy guard AND a silent
        change to the constant flips this test.

        Counter=100, default window=50:
          stale       trace age 60  → below τ, dormant       → evicted
          fresh       trace age  1  → above τ                 → retained
          recent_low  trace age 40  → below τ but age<window  → retained
        The 40/60 straddle pins the default window to (40, 60].
        """
        # The proxy writes its ACT-R memory to the hooks path
        # proxy_home(teaparty_home)/.proxy-memory.db, NOT under project_dir.
        # Construct the DB exactly where the runtime hooks would, and drive
        # consolidation by poc_root — so this test fails if consolidation
        # resolves the DB any other way (e.g. globbing project_dir, which the
        # proxy never writes to).
        from teaparty.proxy.hooks import proxy_memory_path
        poc_root = tempfile.mkdtemp()
        project_dir = tempfile.mkdtemp()  # holds proxy.md (Stage 2a); no DB here
        db_path = proxy_memory_path(os.path.join(poc_root, '.teaparty'))
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        conn = open_proxy_db(db_path)
        try:
            _set_counter(conn, 100)
            # Distinct task_types so contradiction-consolidation does not act;
            # only eviction should touch these.
            _store(conn, id='stale', traces=[40], task_type='a')        # age 60, B<τ, dormant
            _store(conn, id='fresh', traces=[99], task_type='b')        # age 1,  B≈0 > τ
            _store(conn, id='recent_low', traces=[60], task_type='c')   # age 40, B<τ, recent
            b_recent = base_level_activation([60], 100)
            self.assertLess(
                b_recent, RETRIEVAL_THRESHOLD,
                f'fixture: recent_low B={b_recent:.3f} must be below τ so only '
                f'the dormancy guard (not the τ guard) can retain it',
            )
        finally:
            conn.close()

        from teaparty.learning.extract import _consolidate_proxy_memory
        _consolidate_proxy_memory(project_dir=project_dir, poc_root=poc_root)

        conn = open_proxy_db(db_path)
        try:
            active = {c.id for c in query_chunks(conn)}
            self.assertNotIn(
                'stale', active,
                'consolidation must evict the dormant below-τ chunk on the live '
                'hooks DB (proxy_home(teaparty_home)/.proxy-memory.db). If '
                'consolidation still globbed project_dir it would find no DB '
                'here and evict nothing — stale would remain active.',
            )
            self.assertIn(
                'fresh', active,
                'consolidation must retain the above-threshold chunk',
            )
            self.assertIn(
                'recent_low', active,
                'consolidation must retain the below-τ chunk whose trace is '
                'within the default window — proves the dormancy guard runs in '
                'the wired path (would fail if the wired call evicted everything '
                'below τ, or the default window shrank below 40)',
            )
        finally:
            conn.close()


# ── P2: tunable cosine dimension weights ────────────────────────────────────

class TestTunableDimensionWeights(unittest.TestCase):
    """The conversation/job/project cosine weights are a parameter, not a
    hardcoded constant baked into composite_score."""

    def _job_chunk(self) -> MemoryChunk:
        # Matches the query only on the 'job' dimension.
        return MemoryChunk(
            id='c', type='gate_outcome', state='S', task_type='p', outcome='approve',
            traces=[10], embedding_job=[1.0, 0.0],
        )

    def test_raising_job_weight_raises_semantic_contribution(self):
        """With the query matching only the job dimension, a higher job weight
        must increase the composite score. If the weights were hardcoded at
        0.05, passing a new weight would have no effect and this fails."""
        chunk = self._job_chunk()
        ctx = {'job': [1.0, 0.0]}  # perfect cosine on job, nothing else

        low = composite_score(
            chunk, ctx, 10, activation_weight=0.0, semantic_weight=1.0, s=0.0,
            cosine_weights={'conversation': 0.9, 'job': 0.05, 'project': 0.05},
        )
        high = composite_score(
            chunk, ctx, 10, activation_weight=0.0, semantic_weight=1.0, s=0.0,
            cosine_weights={'conversation': 0.0, 'job': 1.0, 'project': 0.0},
        )

        self.assertAlmostEqual(
            low, 0.05, places=6,
            msg=f'job weight 0.05 × cos 1.0 must contribute 0.05; got {low:.6f}',
        )
        self.assertAlmostEqual(
            high, 1.0, places=6,
            msg=f'job weight 1.0 × cos 1.0 must contribute 1.0; got {high:.6f}',
        )

    def test_default_weights_unchanged(self):
        """Omitting cosine_weights must reproduce the historical 0.9/0.05/0.05
        blend — this change is plumbing, not a behavior change."""
        chunk = self._job_chunk()
        ctx = {'job': [1.0, 0.0]}
        default = composite_score(
            chunk, ctx, 10, activation_weight=0.0, semantic_weight=1.0, s=0.0,
        )
        self.assertAlmostEqual(
            default, 0.05, places=6,
            msg=f'default job weight must remain 0.05; got {default:.6f}',
        )

    def test_ablation_configs_include_dimension_weight_variants(self):
        """At least two ablation configs must vary the dimension weights, so
        the weights can be evaluated from data (not just the act/sem split)."""
        with_dims = [
            name for name, cfg in ABLATION_CONFIGS.items()
            if 'cosine_weights' in cfg
        ]
        self.assertGreaterEqual(
            len(with_dims), 2,
            f'ABLATION_CONFIGS must include ≥2 dimension-weight variants; '
            f'found {with_dims}',
        )


# ── P2: noise decision ──────────────────────────────────────────────────────

class TestNoiseDecision(unittest.TestCase):
    """NOISE_SCALE resolved to a deliberate value with deterministic effect."""

    def test_noise_scale_is_a_deliberate_value(self):
        """NOISE_SCALE must be 0.0 (deterministic) or in ACT-R's [0.2, 0.5]
        range — not the 0.08 non-decision."""
        self.assertTrue(
            NOISE_SCALE == 0.0 or 0.2 <= NOISE_SCALE <= 0.5,
            f'NOISE_SCALE must be 0.0 or in [0.2, 0.5]; got {NOISE_SCALE} '
            f'(0.08 is the undecided default the issue resolves)',
        )

    def test_default_retrieval_scoring_is_deterministic(self):
        """With the resolved NOISE_SCALE (0.0), repeated composite_score calls
        on the same inputs are identical. At s=0.08 they would differ."""
        chunk = MemoryChunk(
            id='c', type='gate_outcome', state='S', task_type='p',
            outcome='approve', traces=[9],
        )
        scores = {round(composite_score(chunk, {}, 10), 12) for _ in range(20)}
        self.assertEqual(
            len(scores), 1,
            f'default-noise retrieval must be deterministic; got {len(scores)} '
            f'distinct scores across 20 calls: {scores}',
        )


if __name__ == '__main__':
    unittest.main()
