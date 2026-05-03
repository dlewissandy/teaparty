"""Regression: orchestrator-driven ``/compact`` is disabled — issue #260.

The CfA engine used to queue ``/compact <focus>`` as
``_pending_state_prompt`` whenever the budget tracker fired
``should_compact``.  ``on_pre_turn`` prepended that onto the next
user message.  Two structural defects made this unsafe:

1. ``ContextBudget`` hardcodes a 200K context window.  Agents on the
   1M-context model trip the threshold at ~43% real utilization,
   an order of magnitude earlier than the design intended.
2. Claude CLI's slash-command dispatcher consumes a user message that
   starts with ``/compact`` as the slash command's focus argument.
   The actual content the engine intended for the agent (e.g. a
   worker's Reply) is eaten as part of the focus and never queued as
   a turn the agent answers.  ``result.result`` comes back empty,
   the loop exits naturally, the engine raises ``"skill is
   incomplete"``, and the run dies.

Both defects are reproducible in the joke-book exec streams
(``compact_boundary trigger='manual'``).  Until agent-controlled
compaction lands, the gate is forced off: the budget keeps observing
tokens for telemetry, but ``_pending_state_prompt`` is never set to
a compact prompt.

This test pins the disabled state.  It will need to be removed (or
inverted) when #260's redesign restores compaction via the
agent-controlled path.
"""
from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from teaparty.util.context_budget import ContextBudget


class _StubResult:
    """Minimal result shape that ``_post_turn_bookkeeping`` reads."""

    def __init__(self, budget: ContextBudget) -> None:
        self.context_budget = budget
        # The bookkeeping path also touches these on healthy turns.
        self.session_id = ''
        self.result = ''


class _StubSpec:
    artifact = ''
    stream_file = '.exec-stream.jsonl'


class CompactionGateDisabledTest(unittest.TestCase):
    """``_post_turn_bookkeeping`` does not queue ``/compact`` even when the
    budget says ``should_compact`` is True."""

    def _engine_with_tripped_budget(self):
        """Build the smallest engine instance the bookkeeping needs.

        The bookkeeping path touches:
          - ``self.session_worktree`` (for misplaced-artifact relocation)
          - ``self.infra_dir`` (joins ``stream_file``)
          - ``self._update_scratch(state)``
          - ``self._task_for_phase(state)`` (was used to build the
            compact focus; the fix path no longer reaches it)
          - ``self._pending_state_prompt`` (the slot under test)

        Use ``object.__new__`` to skip ``__init__`` entirely — we only
        exercise the gate, not the orchestrator's full setup.
        """
        from teaparty.cfa.engine import Orchestrator

        engine = object.__new__(Orchestrator)
        # The fields the bookkeeping path reads/writes.
        engine.session_worktree = '/tmp/_test_no_worktree'
        engine.infra_dir = '/tmp/_test_no_infra'
        engine._pending_state_prompt = ''

        # Stub helpers to no-ops so the bookkeeping body executes
        # without doing real I/O.
        engine._update_scratch = lambda state: None  # type: ignore[method-assign]
        engine._task_for_phase = lambda state: 'irrelevant'  # type: ignore[method-assign]

        return engine

    def test_should_compact_does_not_queue_a_compact_prompt(self) -> None:
        """A budget at >78% utilization MUST NOT cause /compact to be queued."""
        from teaparty.cfa.engine import Orchestrator
        engine = self._engine_with_tripped_budget()

        budget = ContextBudget(context_window=200_000, compact_threshold=0.78)
        budget.update({
            'type': 'result',
            'usage': {
                # 95% utilization — well over the threshold.
                'input_tokens': 100_000,
                'cache_creation_input_tokens': 50_000,
                'cache_read_input_tokens': 40_000,
            },
        })
        self.assertTrue(budget.should_compact, 'precondition: budget tripped')

        result = _StubResult(budget)
        spec = _StubSpec()

        asyncio.run(Orchestrator._post_turn_bookkeeping(
            engine, 'EXECUTE', spec, result,
        ))

        self.assertEqual(
            engine._pending_state_prompt, '',
            'orchestrator-driven /compact is disabled (#260) — '
            'no prompt may be queued even when should_compact is True',
        )
        # The flag is cleared so a subsequent turn doesn't re-trip on the
        # same observation.  Without the clear, every subsequent turn
        # would re-queue.
        self.assertFalse(
            budget.should_compact,
            'budget._compact_fired must be cleared after the gate fires',
        )

    def test_engine_does_not_import_build_compact_prompt_for_queueing(self) -> None:
        """Pin the absence of the queueing call site.

        Source-level pin: a future refactor that adds a
        ``self._pending_state_prompt = build_compact_prompt(...)``
        line back into ``_post_turn_bookkeeping`` should fail this
        test.  Issue #260 re-tracks the redesign — a casual revert
        should not re-introduce the broken path silently.
        """
        import inspect
        from teaparty.cfa.engine import Orchestrator

        src = inspect.getsource(Orchestrator._post_turn_bookkeeping)
        # The build_compact_prompt call must not appear inside this method.
        self.assertNotIn(
            'build_compact_prompt(',
            src,
            'orchestrator-driven /compact must remain disabled until '
            '#260 redesign lands; do not re-introduce the queueing call',
        )


if __name__ == '__main__':
    unittest.main()
