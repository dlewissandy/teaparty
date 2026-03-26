"""Tests for Issue #226: Per-context prediction accuracy tracking.

The proxy stores prior/posterior predictions and human responses in ACT-R
memory chunks, but does not maintain a running accuracy metric per context.
These tests verify that:

1. proxy_accuracy table exists after open_proxy_db()
2. record_interaction() atomically updates accuracy counts
3. Prior/posterior match is computed correctly (including empty predictions)
4. get_accuracy() returns per-(state, task_type) accuracy records
5. consult_proxy() surfaces accuracy data in the proxy prompt
"""
from __future__ import annotations

import os
import tempfile
import unittest
from unittest.mock import patch, AsyncMock, MagicMock

from projects.POC.orchestrator.proxy_memory import (
    MemoryChunk,
    open_proxy_db,
    store_chunk,
    record_interaction,
    get_interaction_counter,
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
        content='test content',
        traces=traces or [1],
    )
    defaults.update(kwargs)
    return MemoryChunk(**defaults)


def _make_db():
    """Create a temp proxy memory DB; returns (conn, path)."""
    tmp = tempfile.mkdtemp()
    db_path = os.path.join(tmp, 'proxy-memory.db')
    conn = open_proxy_db(db_path)
    return conn, db_path


class TestProxyAccuracyTableExists(unittest.TestCase):
    """The proxy_accuracy table must be created by open_proxy_db()."""

    def test_table_created_on_new_db(self):
        conn, _ = _make_db()
        try:
            rows = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='proxy_accuracy'"
            ).fetchall()
            self.assertEqual(len(rows), 1, 'proxy_accuracy table should exist')
        finally:
            conn.close()

    def test_table_created_on_existing_db(self):
        """Opening a pre-existing DB (without proxy_accuracy) should add it."""
        conn, db_path = _make_db()
        # Drop the table to simulate a pre-existing DB
        conn.execute('DROP TABLE IF EXISTS proxy_accuracy')
        conn.commit()
        conn.close()

        # Reopen — should recreate the table
        conn = open_proxy_db(db_path)
        try:
            rows = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='proxy_accuracy'"
            ).fetchall()
            self.assertEqual(len(rows), 1, 'proxy_accuracy table should be recreated')
        finally:
            conn.close()


class TestAccuracyUpdatedByRecordInteraction(unittest.TestCase):
    """record_interaction() should atomically update proxy_accuracy counts."""

    def _record(self, conn, state='PLAN_ASSERT', task_type='security',
                outcome='approve', prior_prediction='approve',
                posterior_prediction='approve'):
        return record_interaction(
            conn,
            interaction_type='gate_outcome',
            state=state,
            task_type=task_type,
            outcome=outcome,
            content='test',
            prior_prediction=prior_prediction,
            posterior_prediction=posterior_prediction,
            embed_fn=lambda text: None,
        )

    def test_posterior_match_increments_correct(self):
        conn, _ = _make_db()
        try:
            self._record(conn, outcome='approve', posterior_prediction='approve')
            row = conn.execute(
                "SELECT posterior_correct, posterior_total FROM proxy_accuracy "
                "WHERE state='PLAN_ASSERT' AND task_type='security'"
            ).fetchone()
            self.assertIsNotNone(row, 'proxy_accuracy row should exist')
            self.assertEqual(row[0], 1, 'posterior_correct should be 1')
            self.assertEqual(row[1], 1, 'posterior_total should be 1')
        finally:
            conn.close()

    def test_posterior_mismatch_increments_total_only(self):
        conn, _ = _make_db()
        try:
            self._record(conn, outcome='correct', posterior_prediction='approve')
            row = conn.execute(
                "SELECT posterior_correct, posterior_total FROM proxy_accuracy "
                "WHERE state='PLAN_ASSERT' AND task_type='security'"
            ).fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(row[0], 0, 'posterior_correct should be 0')
            self.assertEqual(row[1], 1, 'posterior_total should be 1')
        finally:
            conn.close()

    def test_prior_match_increments_correct(self):
        conn, _ = _make_db()
        try:
            self._record(conn, outcome='approve', prior_prediction='approve')
            row = conn.execute(
                "SELECT prior_correct, prior_total FROM proxy_accuracy "
                "WHERE state='PLAN_ASSERT' AND task_type='security'"
            ).fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(row[0], 1, 'prior_correct should be 1')
            self.assertEqual(row[1], 1, 'prior_total should be 1')
        finally:
            conn.close()

    def test_prior_mismatch_increments_total_only(self):
        conn, _ = _make_db()
        try:
            self._record(conn, outcome='correct', prior_prediction='approve')
            row = conn.execute(
                "SELECT prior_correct, prior_total FROM proxy_accuracy "
                "WHERE state='PLAN_ASSERT' AND task_type='security'"
            ).fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(row[0], 0, 'prior_correct should be 0')
            self.assertEqual(row[1], 1, 'prior_total should be 1')
        finally:
            conn.close()

    def test_empty_prediction_excluded_from_totals(self):
        """Empty predictions (cold start, agent failure) should not count."""
        conn, _ = _make_db()
        try:
            self._record(conn, outcome='approve',
                         prior_prediction='', posterior_prediction='')
            row = conn.execute(
                "SELECT * FROM proxy_accuracy "
                "WHERE state='PLAN_ASSERT' AND task_type='security'"
            ).fetchone()
            # Either no row exists, or totals are 0
            if row:
                self.assertEqual(row['prior_total'], 0)
                self.assertEqual(row['posterior_total'], 0)
        finally:
            conn.close()

    def test_multiple_interactions_accumulate(self):
        conn, _ = _make_db()
        try:
            # 3 interactions: 2 posterior correct, 1 wrong
            self._record(conn, outcome='approve', posterior_prediction='approve')
            self._record(conn, outcome='approve', posterior_prediction='approve')
            self._record(conn, outcome='correct', posterior_prediction='approve')
            row = conn.execute(
                "SELECT posterior_correct, posterior_total FROM proxy_accuracy "
                "WHERE state='PLAN_ASSERT' AND task_type='security'"
            ).fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(row[0], 2, 'posterior_correct should be 2')
            self.assertEqual(row[1], 3, 'posterior_total should be 3')
        finally:
            conn.close()

    def test_different_contexts_tracked_independently(self):
        conn, _ = _make_db()
        try:
            self._record(conn, state='PLAN_ASSERT', task_type='security',
                         outcome='approve', posterior_prediction='approve')
            self._record(conn, state='PLAN_ASSERT', task_type='documentation',
                         outcome='correct', posterior_prediction='approve')
            self._record(conn, state='INTENT_ASSERT', task_type='POC',
                         outcome='approve', posterior_prediction='approve')

            rows = conn.execute(
                "SELECT state, task_type, posterior_correct, posterior_total "
                "FROM proxy_accuracy ORDER BY state, task_type"
            ).fetchall()
            self.assertEqual(len(rows), 3)
            # Each context has exactly 1 interaction
            for row in rows:
                self.assertEqual(row[3], 1)  # posterior_total
        finally:
            conn.close()


class TestGetAccuracy(unittest.TestCase):
    """get_accuracy() should return per-context accuracy records."""

    def test_get_accuracy_returns_record(self):
        from projects.POC.orchestrator.proxy_memory import get_accuracy
        conn, _ = _make_db()
        try:
            record_interaction(
                conn,
                interaction_type='gate_outcome',
                state='PLAN_ASSERT',
                task_type='security',
                outcome='approve',
                content='test',
                prior_prediction='approve',
                posterior_prediction='approve',
                embed_fn=lambda text: None,
            )
            acc = get_accuracy(conn, state='PLAN_ASSERT', task_type='security')
            self.assertIsNotNone(acc)
            self.assertEqual(acc['prior_correct'], 1)
            self.assertEqual(acc['prior_total'], 1)
            self.assertEqual(acc['posterior_correct'], 1)
            self.assertEqual(acc['posterior_total'], 1)
        finally:
            conn.close()

    def test_get_accuracy_missing_context_returns_none(self):
        from projects.POC.orchestrator.proxy_memory import get_accuracy
        conn, _ = _make_db()
        try:
            acc = get_accuracy(conn, state='NONEXISTENT', task_type='nope')
            self.assertIsNone(acc)
        finally:
            conn.close()


class TestAccuracyInConsultProxy(unittest.TestCase):
    """consult_proxy() should surface accuracy data in the proxy prompt."""

    def test_accuracy_data_passed_to_proxy_agent(self):
        """When accuracy data exists, it should appear in the proxy prompt."""
        import asyncio
        from projects.POC.orchestrator.proxy_agent import consult_proxy

        # Create a DB with accuracy data
        conn, db_path = _make_db()
        try:
            record_interaction(
                conn,
                interaction_type='gate_outcome',
                state='PLAN_ASSERT',
                task_type='test-project',
                outcome='approve',
                content='test',
                prior_prediction='correct',
                posterior_prediction='approve',
                embed_fn=lambda text: None,
            )
            # Record several more to build accuracy
            for _ in range(9):
                record_interaction(
                    conn,
                    interaction_type='gate_outcome',
                    state='PLAN_ASSERT',
                    task_type='test-project',
                    outcome='approve',
                    content='test',
                    prior_prediction='approve',
                    posterior_prediction='approve',
                    embed_fn=lambda text: None,
                )
        finally:
            conn.close()

        proxy_model_path = os.path.join(os.path.dirname(db_path), '.proxy-confidence.json')

        captured_prompts = []

        async def _fake_invoke(prompt, session_worktree):
            captured_prompts.append(prompt)
            return ('test response\nACTION: approve\nCONFIDENCE: 0.9', 0.9, 'approve')

        with patch('projects.POC.orchestrator.proxy_agent._invoke_claude_proxy', side_effect=_fake_invoke), \
             patch('projects.POC.orchestrator.proxy_agent._retrieve_actr_memories') as mock_retrieve, \
             patch('projects.POC.orchestrator.proxy_agent._reinforce_actr_memories'), \
             patch('projects.POC.orchestrator.proxy_agent._calibrate_confidence', return_value=0.9), \
             patch('projects.POC.orchestrator.proxy_memory.resolve_memory_db_path', return_value=db_path):

            mock_retrieve.return_value = MagicMock(
                serialized='', chunk_ids=[], db_path=db_path, interaction_counter=10,
                accuracy={
                    'prior_correct': 9, 'prior_total': 10,
                    'posterior_correct': 10, 'posterior_total': 10,
                    'last_updated': '2026-03-26',
                },
            )

            result = asyncio.run(consult_proxy(
                'Test question',
                state='PLAN_ASSERT',
                project_slug='test-project',
                proxy_model_path=proxy_model_path,
            ))

        # At least one prompt should contain accuracy data
        self.assertTrue(
            any('accuracy' in p.lower() or 'prediction accuracy' in p.lower()
                for p in captured_prompts),
            f'Expected accuracy data in proxy prompt, got: {captured_prompts[:1]}'
        )


class TestAccuracyGatesAutonomy(unittest.TestCase):
    """Prediction accuracy should gate proxy autonomy via _calibrate_confidence."""

    def _calibrate(self, agent_confidence, accuracy=None, depth=5):
        from projects.POC.orchestrator.proxy_agent import _calibrate_confidence
        with patch('projects.POC.orchestrator.proxy_agent._get_memory_depth', return_value=depth):
            return _calibrate_confidence(
                agent_confidence, 'PLAN_ASSERT', 'security', '', '',
                accuracy=accuracy,
            )

    def test_high_accuracy_trusts_agent_confidence(self):
        """Posterior accuracy >= 85% over >= 10 interactions → trust agent."""
        acc = {'posterior_correct': 9, 'posterior_total': 10,
               'prior_correct': 5, 'prior_total': 10}
        result = self._calibrate(0.9, accuracy=acc)
        self.assertEqual(result, 0.9)

    def test_low_accuracy_caps_confidence(self):
        """Posterior accuracy < 85% over >= 10 interactions → cap at 0.5."""
        acc = {'posterior_correct': 6, 'posterior_total': 10,
               'prior_correct': 3, 'prior_total': 10}
        result = self._calibrate(0.9, accuracy=acc)
        self.assertEqual(result, 0.5)

    def test_insufficient_interactions_no_cap(self):
        """Fewer than 10 interactions → accuracy gating does not apply."""
        acc = {'posterior_correct': 3, 'posterior_total': 5,
               'prior_correct': 1, 'prior_total': 5}
        result = self._calibrate(0.9, accuracy=acc)
        self.assertEqual(result, 0.9)

    def test_no_accuracy_data_no_cap(self):
        """No accuracy record → no accuracy-based cap."""
        result = self._calibrate(0.9, accuracy=None)
        self.assertEqual(result, 0.9)

    def test_cold_start_overrides_accuracy(self):
        """Cold-start guard (low memory depth) takes precedence over accuracy."""
        acc = {'posterior_correct': 10, 'posterior_total': 10,
               'prior_correct': 10, 'prior_total': 10}
        result = self._calibrate(0.9, accuracy=acc, depth=1)
        self.assertEqual(result, 0.5)

    def test_exactly_at_threshold(self):
        """Posterior accuracy exactly at 85% → trusted (not capped)."""
        # 17/20 = 0.85 exactly
        acc = {'posterior_correct': 17, 'posterior_total': 20,
               'prior_correct': 10, 'prior_total': 20}
        result = self._calibrate(0.9, accuracy=acc)
        self.assertEqual(result, 0.9)

    def test_just_below_threshold(self):
        """Posterior accuracy just below 85% → capped."""
        # 8/10 = 0.80
        acc = {'posterior_correct': 8, 'posterior_total': 10,
               'prior_correct': 5, 'prior_total': 10}
        result = self._calibrate(0.9, accuracy=acc)
        self.assertEqual(result, 0.5)


if __name__ == '__main__':
    unittest.main()
