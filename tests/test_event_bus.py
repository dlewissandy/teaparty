"""Unit tests for the SSE event bus."""

import asyncio
import threading
import unittest

from teaparty_app.services.event_bus import publish, subscribe, unsubscribe


class EventBusTests(unittest.TestCase):
    """Tests for subscribe / publish / unsubscribe."""

    def test_subscribe_publish_receive(self) -> None:
        """Published events appear in the subscriber's queue."""
        loop = asyncio.new_event_loop()

        async def run():
            q, handle = subscribe("conv-1")
            publish("conv-1", {"type": "activity", "agents": []})
            event = await asyncio.wait_for(q.get(), timeout=2)
            unsubscribe("conv-1", handle)
            return event

        try:
            result = loop.run_until_complete(run())
        finally:
            loop.close()

        self.assertEqual(result["type"], "activity")

    def test_unsubscribe_stops_delivery(self) -> None:
        """After unsubscribe, new publishes don't land in the queue."""
        loop = asyncio.new_event_loop()

        async def run():
            q, handle = subscribe("conv-2")
            unsubscribe("conv-2", handle)
            publish("conv-2", {"type": "message"})
            self.assertTrue(q.empty())

        try:
            loop.run_until_complete(run())
        finally:
            loop.close()

    def test_multiple_subscribers(self) -> None:
        """Multiple subscribers each receive the same event."""
        loop = asyncio.new_event_loop()

        async def run():
            q1, h1 = subscribe("conv-3")
            q2, h2 = subscribe("conv-3")
            publish("conv-3", {"type": "activity", "test": True})
            e1 = await asyncio.wait_for(q1.get(), timeout=2)
            e2 = await asyncio.wait_for(q2.get(), timeout=2)
            unsubscribe("conv-3", h1)
            unsubscribe("conv-3", h2)
            return e1, e2

        try:
            e1, e2 = loop.run_until_complete(run())
        finally:
            loop.close()

        self.assertEqual(e1["type"], "activity")
        self.assertEqual(e2["type"], "activity")

    def test_publish_from_background_thread(self) -> None:
        """Events published from a background thread are received."""
        loop = asyncio.new_event_loop()

        async def run():
            q, handle = subscribe("conv-4")

            def bg():
                publish("conv-4", {"type": "message", "from_thread": True})

            t = threading.Thread(target=bg)
            t.start()
            t.join(timeout=5)

            event = await asyncio.wait_for(q.get(), timeout=2)
            unsubscribe("conv-4", handle)
            return event

        try:
            result = loop.run_until_complete(run())
        finally:
            loop.close()

        self.assertEqual(result["type"], "message")
        self.assertTrue(result["from_thread"])

    def test_publish_no_subscribers(self) -> None:
        """Publishing to a conversation with no subscribers doesn't error."""
        publish("conv-nonexistent", {"type": "activity"})


if __name__ == "__main__":
    unittest.main()
