"""Specification tests for issue #432.

Replaces the dormant 4-dimension cosine + structural-identity design with a
three-dimension weighted-cosine composite (conversation / job / project) and
wires production paths to populate and use it.

Composite formula post-fix:
    cosine = 0.9 · cos(conv) + 0.05 · cos(job) + 0.05 · cos(proj)
    composite = α · tanh(B − τ) + β · cosine + noise

Source-of-truth for embedding text:
    conversation — thread's conversation history through the chunk's stimulus
    job          — .teaparty/jobs/{job-id}/PROMPT.txt
    project      — .teaparty/project/project.yaml `description:` field
"""
from __future__ import annotations

import math
import os
import sys
import sqlite3
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from teaparty.proxy.memory import (
    COSINE_WEIGHT_CONVERSATION,
    COSINE_WEIGHT_JOB,
    COSINE_WEIGHT_PROJECT,
    DECAY,
    NOISE_SCALE,
    RETRIEVAL_THRESHOLD,
    MemoryChunk,
    composite_score,
    increment_interaction_counter,
    open_proxy_db,
    query_chunks,
    record_steering_chunk,
    retrieve_chunks,
    store_chunk,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _unit(*v: float) -> list[float]:
    """Return a unit-norm vector pointing in the given direction."""
    norm = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / norm for x in v]


def _make_chunk(
    *,
    traces: list[int] | None = None,
    conversation: list[float] | None = None,
    job: list[float] | None = None,
    project: list[float] | None = None,
) -> MemoryChunk:
    """Minimal chunk pinned on the three new embedding dimensions."""
    return MemoryChunk(
        id='chunk',
        type='gate_outcome',
        state='',
        task_type='',
        outcome='',
        content='',
        traces=traces if traces is not None else [99],
        embedding_conversation=conversation,
        embedding_job=job,
        embedding_project=project,
    )


# ── Test Group 1: chunk schema ────────────────────────────────────────────────

class TestChunkSchema(unittest.TestCase):
    """MemoryChunk and the SQL schema carry the three new embedding columns."""

    def test_dataclass_has_three_new_embedding_fields(self):
        """MemoryChunk has embedding_conversation, embedding_job, embedding_project."""
        chunk = MemoryChunk(
            id='x', type='t', state='', task_type='', outcome='', content='',
        )
        for field in ('embedding_conversation', 'embedding_job', 'embedding_project'):
            self.assertTrue(
                hasattr(chunk, field),
                f'MemoryChunk must define {field} (default None)',
            )
            self.assertIsNone(
                getattr(chunk, field),
                f'{field} must default to None for chunks without populated embeddings',
            )

    def test_dataclass_does_not_define_old_embedding_fields(self):
        """The old five-dim embeddings must be removed from MemoryChunk.

        Their continued presence would let stale code populate them and would
        suggest the schema migration is incomplete (issue #432).
        """
        chunk = MemoryChunk(
            id='x', type='t', state='', task_type='', outcome='', content='',
        )
        for field in (
            'embedding_situation', 'embedding_artifact', 'embedding_stimulus',
            'embedding_response', 'embedding_blended',
        ):
            self.assertFalse(
                hasattr(chunk, field),
                f'MemoryChunk must NOT carry {field} after #432; the old experience '
                f'embeddings are replaced by conversation/job/project',
            )

    def test_schema_persists_three_new_embedding_columns(self):
        """Storing a chunk with new embeddings round-trips through SQLite."""
        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, 'mem.db')
            conn = open_proxy_db(db_path)
            try:
                chunk = _make_chunk(
                    conversation=_unit(1.0, 0.0, 0.0),
                    job=_unit(0.0, 1.0, 0.0),
                    project=_unit(0.0, 0.0, 1.0),
                )
                store_chunk(conn, chunk)

                row = conn.execute(
                    'SELECT embedding_conversation, embedding_job, embedding_project '
                    'FROM proxy_chunks WHERE id = ?',
                    (chunk.id,),
                ).fetchone()
                self.assertIsNotNone(
                    row['embedding_conversation'],
                    'embedding_conversation column must be persisted',
                )
                self.assertIsNotNone(
                    row['embedding_job'],
                    'embedding_job column must be persisted',
                )
                self.assertIsNotNone(
                    row['embedding_project'],
                    'embedding_project column must be persisted',
                )
            finally:
                conn.close()


# ── Test Group 2: composite_score ─────────────────────────────────────────────

class TestCompositeScore(unittest.TestCase):
    """composite_score computes weighted-cosine across three named dimensions."""

    def test_perfect_match_all_three_dims_reaches_one(self):
        """All three dimensions matching at cos=1 produce cosine=1.0 exactly.

        Old formula divided by 4 and capped at 0.75; the new formula uses
        explicit weights summing to 1.0 across three dimensions.
        """
        v = _unit(1.0, 0.0, 0.0)
        chunk = _make_chunk(conversation=v, job=v, project=v)
        ctx = {'conversation': v, 'job': v, 'project': v}
        score = composite_score(
            chunk, ctx, 100,
            activation_weight=0.0, semantic_weight=1.0, s=0.0,
        )
        self.assertAlmostEqual(
            score, 1.0, places=6,
            msg=f'Perfect match on all three dimensions must give cosine=1.0; got {score}',
        )

    def test_only_conversation_match_yields_0_9(self):
        """Conversation dim is weighted 0.9; the other two are 0.05 each."""
        match = _unit(1.0, 0.0, 0.0)
        ortho = _unit(0.0, 1.0, 0.0)
        chunk = _make_chunk(conversation=match, job=ortho, project=ortho)
        ctx = {'conversation': match, 'job': match, 'project': match}
        # cos(match,match)=1; cos(ortho,match)=0.
        # cosine_avg = 0.9*1 + 0.05*0 + 0.05*0 = 0.9
        score = composite_score(
            chunk, ctx, 100,
            activation_weight=0.0, semantic_weight=1.0, s=0.0,
        )
        self.assertAlmostEqual(
            score, 0.9, places=6,
            msg=f'Conversation-only match must contribute 0.9 (the conv weight); got {score}',
        )

    def test_only_job_match_yields_0_05(self):
        """Job dim is weighted 0.05."""
        match = _unit(1.0, 0.0)
        ortho = _unit(0.0, 1.0)
        chunk = _make_chunk(conversation=ortho, job=match, project=ortho)
        ctx = {'conversation': match, 'job': match, 'project': match}
        score = composite_score(
            chunk, ctx, 100,
            activation_weight=0.0, semantic_weight=1.0, s=0.0,
        )
        self.assertAlmostEqual(
            score, 0.05, places=6,
            msg=f'Job-only match must contribute 0.05 (the job weight); got {score}',
        )

    def test_only_project_match_yields_0_05(self):
        """Project dim is weighted 0.05."""
        match = _unit(1.0, 0.0)
        ortho = _unit(0.0, 1.0)
        chunk = _make_chunk(conversation=ortho, job=ortho, project=match)
        ctx = {'conversation': match, 'job': match, 'project': match}
        score = composite_score(
            chunk, ctx, 100,
            activation_weight=0.0, semantic_weight=1.0, s=0.0,
        )
        self.assertAlmostEqual(
            score, 0.05, places=6,
            msg=f'Project-only match must contribute 0.05 (the project weight); got {score}',
        )

    def test_cosine_weight_constants_exact_values(self):
        """The weight constants are 0.9/0.05/0.05 and sum to 1.0.

        A regression that nudges any constant would be caught here directly,
        even if no per-dimension test happens to run.
        """
        self.assertEqual(
            COSINE_WEIGHT_CONVERSATION, 0.9,
            f'Conversation weight must be 0.9; got {COSINE_WEIGHT_CONVERSATION}',
        )
        self.assertEqual(
            COSINE_WEIGHT_JOB, 0.05,
            f'Job weight must be 0.05; got {COSINE_WEIGHT_JOB}',
        )
        self.assertEqual(
            COSINE_WEIGHT_PROJECT, 0.05,
            f'Project weight must be 0.05; got {COSINE_WEIGHT_PROJECT}',
        )
        total = COSINE_WEIGHT_CONVERSATION + COSINE_WEIGHT_JOB + COSINE_WEIGHT_PROJECT
        self.assertAlmostEqual(
            total, 1.0, places=10,
            msg=f'Cosine weights must sum to 1.0 (so cosine reaches 1.0 on a '
                f'perfect three-of-three match); got {total}',
        )

    def test_null_chunk_embeddings_yield_zero_cosine(self):
        """Chunks with all-None embeddings contribute 0 to cosine, no crash.

        Migration safety: legacy chunks with no embeddings still survive
        retrieval — they fall back to activation alone.
        """
        chunk = _make_chunk(conversation=None, job=None, project=None)
        v = _unit(1.0, 0.0)
        ctx = {'conversation': v, 'job': v, 'project': v}
        score = composite_score(
            chunk, ctx, 100,
            activation_weight=0.0, semantic_weight=1.0, s=0.0,
        )
        self.assertEqual(
            score, 0.0,
            f'Null chunk embeddings must produce cosine=0; got {score}',
        )

    def test_no_query_embeddings_yield_zero_cosine(self):
        """When the caller passes no context embeddings, cosine is 0 (no crash)."""
        v = _unit(1.0, 0.0)
        chunk = _make_chunk(conversation=v, job=v, project=v)
        score = composite_score(
            chunk, {}, 100,
            activation_weight=0.0, semantic_weight=1.0, s=0.0,
        )
        self.assertEqual(
            score, 0.0,
            f'Empty context must produce cosine=0; got {score}',
        )

    def test_orthogonal_match_with_partial_dims_does_not_reach_threshold(self):
        """Old code divided by 4 capping at 0.75 even on perfect-3-of-4 match.

        With three dimensions and explicit weights summing to 1.0, a perfect
        three-of-three match must reach 1.0, not 0.75 (no /4 averaging).
        """
        # This is the negation of the old buggy ceiling.
        v = _unit(1.0, 0.0)
        chunk = _make_chunk(conversation=v, job=v, project=v)
        ctx = {'conversation': v, 'job': v, 'project': v}
        score = composite_score(
            chunk, ctx, 100,
            activation_weight=0.0, semantic_weight=1.0, s=0.0,
        )
        self.assertGreater(
            score, 0.75,
            f'Three-dim formula must exceed the old /4 ceiling of 0.75; got {score}',
        )


# ── Test Group 3: retrieval prefers context-relevant over recent ──────────────

class TestRetrievalPrefersContextRelevant(unittest.TestCase):
    """End-to-end: with embeddings populated, cosine outranks pure recency."""

    def test_older_relevant_chunk_outranks_newer_irrelevant_chunk(self):
        """A chunk that matches the current conversation outranks a more recent one
        that doesn't, given equal activation weight and semantic weight.

        Pre-fix (cosine dormant): retrieval is purely activation; the newer
        chunk always wins. Post-fix: cosine on conversation flips this when
        the older chunk is contextually relevant.
        """
        match = _unit(1.0, 0.0, 0.0)
        ortho = _unit(0.0, 1.0, 0.0)
        # Older but relevant: trace 5 ago, conversation matches current
        relevant_old = _make_chunk(
            traces=[95], conversation=match, job=match, project=match,
        )
        relevant_old.id = 'relevant_old'
        # Fresher but irrelevant: trace 1 ago, all dims orthogonal
        irrelevant_new = _make_chunk(
            traces=[99], conversation=ortho, job=ortho, project=ortho,
        )
        irrelevant_new.id = 'irrelevant_new'

        ctx = {'conversation': match, 'job': match, 'project': match}

        # Default 0.5/0.5 weights: cosine half (0.9 from conv match) >>
        # the activation difference between trace=50 and trace=99.
        score_old = composite_score(
            relevant_old, ctx, 100,
            activation_weight=0.5, semantic_weight=0.5, s=0.0,
        )
        score_new = composite_score(
            irrelevant_new, ctx, 100,
            activation_weight=0.5, semantic_weight=0.5, s=0.0,
        )

        self.assertGreater(
            score_old, score_new,
            f'Contextually-relevant older chunk must outrank irrelevant newer chunk '
            f'when cosine is wired (old={score_old:.4f}, new={score_new:.4f}); '
            f'pre-fix this would be reversed because cosine was dormant',
        )


# ── Test Group 4: production wiring ───────────────────────────────────────────

class TestProductionWiring(unittest.TestCase):
    """Recording and retrieval sites populate / use the new embeddings."""

    def test_proxy_build_prompt_passes_context_embeddings_to_retrieve_chunks(self):
        """proxy_build_prompt must pass non-empty context_embeddings.

        Pre-fix: hooks.py:128 calls retrieve_chunks(conn, current_interaction=...,
        top_k=10) with no embeddings; cosine is structurally always 0.
        Post-fix: at least 'conversation' must be passed.
        """
        from teaparty.proxy import hooks as proxy_hooks
        captured: dict = {}

        def fake_retrieve_chunks(conn, **kwargs):
            captured.update(kwargs)
            return []

        # Patch retrieve_chunks at the import site that hooks.py uses.
        from teaparty.proxy import memory as proxy_memory
        original = proxy_memory.retrieve_chunks
        original_embed = proxy_memory._default_embed
        proxy_memory.retrieve_chunks = fake_retrieve_chunks
        # Stub the embedder so context_embeddings actually populates in tests
        # where no real embedding provider is configured.
        proxy_memory._default_embed = lambda conn: (lambda text: [1.0, 0.0])
        try:
            with tempfile.TemporaryDirectory() as tmp:
                # Build a minimal session-shaped object
                teaparty_home = os.path.join(tmp, '.teaparty')
                proxy_dir = os.path.join(teaparty_home, 'proxy')
                project_dir = os.path.join(teaparty_home, 'project')
                os.makedirs(proxy_dir, exist_ok=True)
                os.makedirs(project_dir, exist_ok=True)
                with open(os.path.join(project_dir, 'project.yaml'), 'w') as fh:
                    fh.write('description: a test project\n')
                # Touch the memory DB so the retrieve path runs
                db_path = os.path.join(proxy_dir, '.proxy-memory.db')
                conn = open_proxy_db(db_path)
                conn.close()

                class _StubSession:
                    claude_session_id = None
                    qualifier = 'test'
                    infra_dir = None
                    project = ''
                    cfa_state = ''
                    task = ''

                    def get_messages(self):
                        return []

                stub = _StubSession()
                stub.teaparty_home = teaparty_home
                proxy_hooks.proxy_build_prompt(stub, 'hello')

                self.assertIn(
                    'context_embeddings', captured,
                    'proxy_build_prompt must pass context_embeddings to retrieve_chunks',
                )
                self.assertIsInstance(
                    captured['context_embeddings'], dict,
                    'context_embeddings must be a dict',
                )
                ctx = captured['context_embeddings']
                self.assertIn(
                    'conversation', ctx,
                    f"context_embeddings must contain the 'conversation' key (got {sorted(ctx)})",
                )
                self.assertIn(
                    'project', ctx,
                    f"context_embeddings must contain the 'project' key (got {sorted(ctx)})",
                )
                # 'job' is absent here because the stub session has no infra_dir;
                # PROMPT.txt cannot be read, so the dimension is skipped.
                self.assertIsInstance(
                    ctx['conversation'], list,
                    'conversation embedding must be a list of floats',
                )
        finally:
            proxy_memory.retrieve_chunks = original
            proxy_memory._default_embed = original_embed


# ── Test Group 5: recording-site wiring ───────────────────────────────────────

class TestRecordingSitePopulatesEmbeddings(unittest.TestCase):
    """Each production recording site populates the three embeddings (#432 AC 3)."""

    def _stub_default_embed(self):
        """Replace _default_embed in proxy.memory and proxy.hooks for the test."""
        from teaparty.proxy import memory as proxy_memory
        from teaparty.proxy import hooks as proxy_hooks
        self._orig_mem_embed = proxy_memory._default_embed
        proxy_memory._default_embed = lambda conn: (lambda text: [1.0, 0.0])
        # hooks.py imports _default_embed lazily inside _embed_context; patching
        # the source attribute is sufficient.
        return proxy_hooks

    def _restore_default_embed(self):
        from teaparty.proxy import memory as proxy_memory
        proxy_memory._default_embed = self._orig_mem_embed

    def test_proxy_post_invoke_populates_three_embeddings_on_correction_chunk(self):
        """[CORRECTION:...] in proxy response creates a chunk with all three embeddings."""
        proxy_hooks = self._stub_default_embed()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                teaparty_home = os.path.join(tmp, '.teaparty')
                proxy_dir = os.path.join(teaparty_home, 'proxy')
                project_dir = os.path.join(teaparty_home, 'project')
                os.makedirs(proxy_dir, exist_ok=True)
                os.makedirs(project_dir, exist_ok=True)
                # Project description so _read_project_description returns text
                with open(os.path.join(project_dir, 'project.yaml'), 'w') as fh:
                    fh.write('name: TestProj\ndescription: a test project\n')
                # PROMPT.txt for job text
                infra_dir = os.path.join(tmp, 'job-test')
                os.makedirs(infra_dir, exist_ok=True)
                with open(os.path.join(infra_dir, 'PROMPT.txt'), 'w') as fh:
                    fh.write('Please review this thing.')

                # Stub session with the surface proxy_post_invoke needs.
                class _Session:
                    qualifier = 'test'
                    def get_messages(self):
                        return []
                stub = _Session()
                stub.teaparty_home = teaparty_home
                stub.infra_dir = infra_dir

                proxy_hooks.proxy_post_invoke(
                    '[CORRECTION: tests must use uv run pytest]', stub,
                )

                # Inspect the chunk that was written.
                db_path = os.path.join(proxy_dir, '.proxy-memory.db')
                conn = open_proxy_db(db_path)
                try:
                    chunks = query_chunks(conn, type='review_correction')
                finally:
                    conn.close()
                self.assertEqual(
                    len(chunks), 1,
                    f'Expected exactly one review_correction chunk; got {len(chunks)}',
                )
                c = chunks[0]
                self.assertIsNotNone(
                    c.embedding_conversation,
                    'review_correction chunk must have embedding_conversation populated '
                    '(comes from session messages + latest response)',
                )
                self.assertIsNotNone(
                    c.embedding_job,
                    'review_correction chunk must have embedding_job populated '
                    '(comes from PROMPT.txt)',
                )
                self.assertIsNotNone(
                    c.embedding_project,
                    'review_correction chunk must have embedding_project populated '
                    '(comes from project.yaml description)',
                )
        finally:
            self._restore_default_embed()

    def test_record_steering_chunk_populates_conversation_and_project(self):
        """Steering chunks embed the directive itself as conversation; project optional."""
        self._stub_default_embed()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                db_path = os.path.join(tmp, 'mem.db')
                conn = open_proxy_db(db_path)
                try:
                    record_steering_chunk(
                        conn,
                        content='Always run uv run pytest.',
                        source='primus',
                        current_interaction=1,
                        project_text='a test project',
                    )
                    chunks = query_chunks(conn, type='steering')
                finally:
                    conn.close()
                self.assertEqual(
                    len(chunks), 1,
                    f'Expected exactly one steering chunk; got {len(chunks)}',
                )
                c = chunks[0]
                self.assertIsNotNone(
                    c.embedding_conversation,
                    'Steering chunk must embed the directive text as embedding_conversation '
                    'so cosine retrieval can match it',
                )
                self.assertIsNotNone(
                    c.embedding_project,
                    'Steering chunk must populate embedding_project when project_text is given',
                )
                self.assertIsNone(
                    c.embedding_job,
                    'Steering chunks have no job (project-scoped); embedding_job must be None',
                )
        finally:
            self._restore_default_embed()

    def test_withdrawal_recording_populates_three_embeddings(self):
        """Withdrawal chunks populate all three embeddings via SessionState path.

        The withdrawal site receives a SessionState dataclass (not an
        AgentSession), and must populate conversation/job/project regardless.
        """
        self._stub_default_embed()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                # Lay out infra: {project_root}/.teaparty/jobs/{job-id}/
                project_root = os.path.join(tmp, 'proj')
                jobs_dir = os.path.join(project_root, '.teaparty', 'jobs')
                infra_dir = os.path.join(jobs_dir, 'job-12345--test')
                os.makedirs(infra_dir)
                proxy_dir = os.path.join(project_root, '.teaparty', 'proxy')
                os.makedirs(proxy_dir)
                project_yaml = os.path.join(project_root, '.teaparty', 'project')
                os.makedirs(project_yaml)
                with open(os.path.join(project_yaml, 'project.yaml'), 'w') as fh:
                    fh.write('description: a test project\n')
                with open(os.path.join(infra_dir, 'PROMPT.txt'), 'w') as fh:
                    fh.write('I would like to test this thing.')

                # Initialize the proxy DB
                db_path = os.path.join(proxy_dir, '.proxy-memory.db')
                conn = open_proxy_db(db_path)
                conn.close()

                from teaparty.workspace.withdraw import _record_withdrawal_memory_chunk
                from dataclasses import dataclass

                @dataclass
                class _StubSessionState:
                    project: str = 'proj'
                    cfa_state: str = 'PLAN'
                    task: str = 'do the thing'
                    infra_dir: str = ''

                stub = _StubSessionState(infra_dir=infra_dir)
                _record_withdrawal_memory_chunk(stub, phase='planning')

                # Inspect the chunk that landed
                conn = open_proxy_db(db_path)
                try:
                    chunks = query_chunks(conn, type='withdrawal')
                finally:
                    conn.close()
                self.assertEqual(
                    len(chunks), 1,
                    f'Expected exactly one withdrawal chunk; got {len(chunks)}',
                )
                c = chunks[0]
                self.assertIsNotNone(
                    c.embedding_conversation,
                    'Withdrawal chunk must populate embedding_conversation '
                    '(content text serves as the conversation signal at withdraw)',
                )
                self.assertIsNotNone(
                    c.embedding_job,
                    'Withdrawal chunk must populate embedding_job from PROMPT.txt',
                )
                self.assertIsNotNone(
                    c.embedding_project,
                    'Withdrawal chunk must populate embedding_project from project.yaml',
                )
        finally:
            self._restore_default_embed()


# ── Test Group 6: end-to-end retrieval through retrieve_chunks ────────────────

class TestRetrieveChunksEndToEnd(unittest.TestCase):
    """retrieve_chunks (not just composite_score) returns chunks correctly ranked."""

    def test_retrieve_chunks_orders_by_composite_with_cosine(self):
        """retrieve_chunks ranks contextually-relevant chunk above irrelevant one.

        Exercises the full retrieve_chunks path: SQL fetch, activation
        filter, composite scoring, top_k slicing.  Bypassed in the
        composite-only test, so this catches kwarg routing and sort-order
        regressions in retrieve_chunks itself.
        """
        match = _unit(1.0, 0.0, 0.0)
        ortho = _unit(0.0, 1.0, 0.0)
        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, 'mem.db')
            conn = open_proxy_db(db_path)
            try:
                # Seed two chunks. The retrieve_chunks default weights are
                # 0.5 / 0.5 with noise=NOISE_SCALE.  We disable noise via
                # a deterministic seed and trace ages so cosine dominates.
                # Relevant chunk: age=2 (trace=98) so B≈-0.347 stays above τ=-0.5.
                store_chunk(conn, MemoryChunk(
                    id='relevant', type='gate_outcome', state='', task_type='',
                    outcome='approve', content='', traces=[98],
                    embedding_conversation=match, embedding_job=match,
                    embedding_project=match,
                ))
                store_chunk(conn, MemoryChunk(
                    id='irrelevant', type='gate_outcome', state='', task_type='',
                    outcome='approve', content='', traces=[99],
                    embedding_conversation=ortho, embedding_job=ortho,
                    embedding_project=ortho,
                ))
                # Set the interaction counter so age math matches our chunks.
                conn.execute(
                    "UPDATE proxy_state SET value=? WHERE key='interaction_counter'",
                    (100,),
                )
                conn.commit()

                # Disable noise for determinism.
                results = retrieve_chunks(
                    conn,
                    context_embeddings={
                        'conversation': match, 'job': match, 'project': match,
                    },
                    current_interaction=100, top_k=2, s=0.0,
                )
            finally:
                conn.close()

            self.assertEqual(
                len(results), 2,
                f'Both seeded chunks must survive; got {len(results)}',
            )
            self.assertEqual(
                results[0].id, 'relevant',
                f'retrieve_chunks must rank the contextually-relevant chunk first; '
                f'got order {[c.id for c in results]}',
            )
            self.assertEqual(
                results[1].id, 'irrelevant',
                f'retrieve_chunks must rank the irrelevant chunk last; '
                f'got order {[c.id for c in results]}',
            )

    def test_retrieve_chunks_returns_null_embedding_chunks(self):
        """A chunk with all-None embeddings still surfaces via activation alone.

        Migration safety: legacy chunks (no embeddings populated) must remain
        retrievable; they fall back to activation-only ranking.
        """
        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, 'mem.db')
            conn = open_proxy_db(db_path)
            try:
                store_chunk(conn, MemoryChunk(
                    id='legacy', type='gate_outcome', state='', task_type='',
                    outcome='approve', content='', traces=[99],
                ))
                conn.execute(
                    "UPDATE proxy_state SET value=? WHERE key='interaction_counter'",
                    (100,),
                )
                conn.commit()

                results = retrieve_chunks(
                    conn,
                    context_embeddings={
                        'conversation': _unit(1.0, 0.0), 'job': _unit(1.0, 0.0),
                        'project': _unit(1.0, 0.0),
                    },
                    current_interaction=100, top_k=10, s=0.0,
                )
            finally:
                conn.close()

            self.assertEqual(
                len(results), 1,
                f'Legacy null-embedding chunk must remain retrievable; got {len(results)}',
            )
            self.assertEqual(
                results[0].id, 'legacy',
                f'Returned chunk must be the seeded legacy chunk; got {results[0].id}',
            )


if __name__ == '__main__':
    unittest.main()
