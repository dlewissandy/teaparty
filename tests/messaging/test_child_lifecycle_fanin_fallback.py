"""Fan-in fallback: an intermediate agent's silence on a resume turn
must not drop their children's contribution.

The bug this pins: in a relay chain (OM → joke-book-lead → art-lead →
svg-artist), svg-artist produced a joke that art-lead's resume turn
did not echo back as agent text.  ``run_child_lifecycle`` returned
the empty string for art-lead (response_parts of the LAST iteration
only — cleared each time), joke-book-lead's gather got '' for
art-lead, the ``if isinstance(r, str) and r:`` filter dropped it,
joke-book-lead's loop broke after its first turn, and OM's relay
ended at "I'll dispatch and wait" — the joke never made it up.

Fix: when the lead's own resume turn produces no agent output, fall
back to propagating the most recent grandchild payload up.  An
intermediate that "has nothing to add" is fine — but the chain must
preserve the children's contribution rather than losing it.

This is implemented at ``run_child_lifecycle``:

    response_text = '\n'.join(response_parts) or last_gc_payload
"""
from __future__ import annotations

import unittest


class TestFanInFallback(unittest.TestCase):
    """Code-shape pin: the lifecycle's return value falls back to
    the most recent grandchild payload when the agent stays silent.
    """

    def test_response_text_falls_back_to_last_gc_payload(self) -> None:
        """The exit branch in run_agent_loop must surface
        last_gc_payload when response_parts is empty AND must
        write it to the bus (otherwise a silent intermediate agent's
        relay never appears in the user's chat blade or the
        accordion).
        """
        import inspect
        from teaparty.messaging import child_dispatch
        src = inspect.getsource(child_dispatch.run_agent_loop)
        self.assertIn(
            'response_text = last_gc_payload',
            src,
            'run_agent_loop must surface last_gc_payload as '
            'response_text when the agent stays silent.',
        )
        self.assertIn(
            'bus.send(conv_id, agent_name, response_text)',
            src,
            'run_agent_loop must also write the fallback payload to '
            'the bus — otherwise the relay propagates as a return '
            'value but never appears in the bus, so the user sees '
            'nothing in the chat blade.',
        )

    def test_last_gc_payload_is_assigned_in_loop(self) -> None:
        """The in-loop gather updates last_gc_payload before
        re-launching with the children's payload as the next message.
        """
        import inspect
        from teaparty.messaging import child_dispatch
        src = inspect.getsource(child_dispatch.run_agent_loop)
        self.assertGreaterEqual(
            src.count('last_gc_payload ='), 1,
            'last_gc_payload must be assigned wherever gc_replies '
            'are computed; otherwise the fallback has no value to '
            'fall back to.',
        )


if __name__ == '__main__':
    unittest.main()
