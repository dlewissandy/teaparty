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
        """The exit expression in the unified subtree loop is
        ``response_text = '\\n'.join(response_parts) or last_gc_payload``.
        If anyone refactors that to drop the fallback, this test fires.
        """
        import inspect
        from teaparty.messaging import child_dispatch
        src = inspect.getsource(child_dispatch.run_subtree_loop)
        self.assertIn(
            "or last_gc_payload",
            src,
            'run_subtree_loop must fall back to last_gc_payload '
            'when response_parts is empty.  Without this, an '
            'intermediate agent that stays silent on a resume turn '
            'breaks the relay chain.',
        )

    def test_last_gc_payload_is_assigned_in_loop(self) -> None:
        """The in-loop gather updates last_gc_payload before
        re-launching with the children's payload as the next message.
        """
        import inspect
        from teaparty.messaging import child_dispatch
        src = inspect.getsource(child_dispatch.run_subtree_loop)
        self.assertGreaterEqual(
            src.count('last_gc_payload ='), 1,
            'last_gc_payload must be assigned wherever gc_replies '
            'are computed; otherwise the fallback has no value to '
            'fall back to.',
        )


if __name__ == '__main__':
    unittest.main()
