#!/usr/bin/env python3
"""Tests for issue #181: Silent exception swallowing in EMA recording,
embedding fallback, and EventBus.

Verifies:
 1. actors.py _proxy_record() logs a WARNING when EMA recording raises
 2. proxy_memory._default_embed() logs a WARNING when memory_indexer import fails
 3. events.EventBus.publish() logs a WARNING when a subscriber raises
"""
import asyncio
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))


# ── helpers ──────────────────────────────────────────────────────────────────

def _make_approval_gate():
    """Build a minimal ApprovalGate with proxy_model_path set."""
    from orchestrator.actors import ApprovalGate
    gate = ApprovalGate.__new__(ApprovalGate)
    gate.proxy_model_path = '/tmp/test_proxy_model.json'
    gate._last_proxy_result = None
    return gate


def _make_event():
    """Build a minimal Event."""
    from orchestrator.events import Event, EventType
    return Event(type=EventType.LOG, data={'msg': 'test'})


# ── EMA recording warning ─────────────────────────────────────────────────────

class TestActorsEmaWarning(unittest.TestCase):

    def test_proxy_record_logs_warning_on_ema_exception(self):
        """_proxy_record must log a WARNING when EMA recording raises."""
        gate = _make_approval_gate()

        # Patch resolve_team_model_path to raise so EMA block fails immediately
        with patch(
            'orchestrator.actors.resolve_team_model_path',
            side_effect=RuntimeError('model path exploded'),
        ):
            with self.assertLogs('orchestrator.actors', level='WARNING') as cm:
                gate._proxy_record(
                    state='INTENT_ASSERT',
                    project_slug='test-proj',
                    outcome='approve',
                )

        self.assertTrue(
            any('WARNING' in line for line in cm.output),
            f"Expected a WARNING log line, got: {cm.output}",
        )


# ── _default_embed import-failure warning ─────────────────────────────────────

class TestProxyMemoryEmbedWarning(unittest.TestCase):

    def test_default_embed_logs_warning_on_import_failure(self):
        """_default_embed must log a WARNING when memory_indexer is unavailable."""
        import sqlite3
        from orchestrator import proxy_memory

        conn = sqlite3.connect(':memory:')

        with patch.dict(
            'sys.modules',
            {'scripts.memory_indexer': None},
        ):
            with self.assertLogs('orchestrator.proxy_memory', level='WARNING') as cm:
                embed_fn = proxy_memory._default_embed(conn)

        # The fallback no-op lambda must still be returned
        self.assertIsNotNone(embed_fn)
        self.assertIsNone(embed_fn('any text'))

        self.assertTrue(
            any('WARNING' in line for line in cm.output),
            f"Expected a WARNING log line, got: {cm.output}",
        )


# ── EventBus subscriber warning ───────────────────────────────────────────────

class TestEventBusPublishWarning(unittest.TestCase):

    def test_publish_logs_warning_when_subscriber_raises(self):
        """EventBus.publish must log a WARNING when a subscriber raises."""
        from orchestrator.events import EventBus

        bus = EventBus()
        event = _make_event()

        async def bad_subscriber(evt):
            raise ValueError('subscriber blew up')

        bus.subscribe(bad_subscriber)

        with self.assertLogs('orchestrator.events', level='WARNING') as cm:
            asyncio.get_event_loop().run_until_complete(bus.publish(event))

        self.assertTrue(
            any('WARNING' in line for line in cm.output),
            f"Expected a WARNING log line, got: {cm.output}",
        )

    def test_publish_continues_after_bad_subscriber(self):
        """EventBus.publish must call subsequent subscribers even when one raises."""
        from orchestrator.events import EventBus

        bus = EventBus()
        event = _make_event()
        called = []

        async def bad_subscriber(evt):
            raise RuntimeError('first subscriber fails')

        async def good_subscriber(evt):
            called.append(evt)

        bus.subscribe(bad_subscriber)
        bus.subscribe(good_subscriber)

        # We expect a warning log; use assertLogs to capture it
        with self.assertLogs('orchestrator.events', level='WARNING'):
            asyncio.get_event_loop().run_until_complete(bus.publish(event))

        self.assertEqual(len(called), 1, "Good subscriber should still be called")


if __name__ == '__main__':
    unittest.main()
