"""Top-level chat and dispatched children share ONE lifecycle.

The bug this pins: the chain ``joke-book-lead → art-lead →
svg-specialist`` (top-level joke-book chat) failed silently because
two different mechanisms drove "agent through turns + integrate
child replies + fan-in fallback" — one in ``run_child_lifecycle``
and one in ``AgentSession._invoke_inner``.  They drifted: the
former had the silent-agent fallback, the latter emitted
"session may have expired" instead of relaying the payload.

The unification: both paths now delegate to
:func:`run_subtree_loop` for the loop / gather / fan-in behavior.
``AgentSession._invoke_inner`` no longer has its own loop; it
builds ``launch_kwargs_base`` and calls ``run_subtree_loop`` with
the user's chat conversation as the stream target.
``run_child_lifecycle`` does the same with the dispatch
conversation as the stream target.  ONE mechanism — and the
fan-in fallback exists once, in the loop.
"""
from __future__ import annotations

import inspect
import unittest


class TestUnifiedSubtreeLoop(unittest.TestCase):
    """Both paths must delegate to run_subtree_loop."""

    def test_run_subtree_loop_has_fan_in_fallback(self) -> None:
        from teaparty.messaging import child_dispatch
        src = inspect.getsource(child_dispatch.run_subtree_loop)
        self.assertIn(
            "or last_gc_payload",
            src,
            'run_subtree_loop must fall back to last_gc_payload '
            'when response_parts is empty.',
        )

    def test_run_child_lifecycle_delegates_to_subtree_loop(self) -> None:
        from teaparty.messaging import child_dispatch
        src = inspect.getsource(child_dispatch.run_child_lifecycle)
        self.assertIn(
            'await run_subtree_loop(',
            src,
            'run_child_lifecycle must delegate to run_subtree_loop. '
            'A separate loop is exactly the asymmetry this unification '
            'eliminates.',
        )

    def test_agent_session_invoke_delegates_to_subtree_loop(self) -> None:
        from teaparty.teams import session
        src = inspect.getsource(session.AgentSession._invoke_inner)
        self.assertIn(
            'run_subtree_loop',
            src,
            'AgentSession._invoke_inner must delegate to '
            'run_subtree_loop.  Without this, top-level chat has its '
            'own loop that drifts from the dispatched-children loop.',
        )


if __name__ == '__main__':
    unittest.main()
