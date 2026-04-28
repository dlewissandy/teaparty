"""Specification tests for the Delegate MCP tool (issue #423).

`Delegate(member, task, skill=None)` is shape-isomorphic to `Send` plus
two added behaviours that distinguish work dispatch from peer messaging:

1. **Open thread precondition**: when the caller already has an open
   dispatch conversation to *member*, `Delegate` rejects without
   launching anything and names the existing channel so the caller can
   switch to `Send` for follow-up.

2. **Workflow prefix**: when `skill` is set, the recipient's first
   dispatched composite is preceded by a directive naming the skill
   with a leading slash (e.g. `Run the /attempt-task skill...`). This
   routes the message to the model, which invokes the skill via the
   `Skill` tool — the same pattern the engine uses to start
   `intent-alignment` / `planning` / `execute` for project-leads.

Each test is load-bearing: reverting the corresponding production
behaviour must produce a specific, named failure.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from teaparty.mcp import registry as mcp_registry


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


class _StubBus:
    """In-memory bus stub: `children_of` returns whatever the test injects."""

    def __init__(self, children: list | None = None) -> None:
        self._children = list(children or [])

    def children_of(self, parent_conversation_id: str):
        return list(self._children)

    def close(self) -> None:
        pass


class _ConvRow:
    """Minimal Conversation shape for `children_of` results."""

    def __init__(self, conv_id: str, agent_name: str, state: str) -> None:
        self.id = conv_id
        self.agent_name = agent_name
        self.state = state


class DelegateReturnShapeTest(unittest.TestCase):
    """Acceptance criterion 1: return shape matches `Send`."""

    def setUp(self) -> None:
        mcp_registry.clear()

    def tearDown(self) -> None:
        mcp_registry.clear()

    def _register_succeeding_spawn(self, captured: list) -> None:
        async def spawn(member, composite, context_id):
            captured.append((member, composite, context_id))
            return ('abc12345', '/tmp/wt', '')
        mcp_registry.register_spawn_fn('caller-agent', spawn)
        mcp_registry.current_agent_name.set('caller-agent')

    def test_delegate_returns_dispatch_conversation_id(self) -> None:
        """A successful Delegate returns JSON whose `conversation_id`
        matches `Send`'s shape: `dispatch:<sid>`.
        """
        from teaparty.mcp.tools.messaging import _default_delegate_post

        captured: list = []
        self._register_succeeding_spawn(captured)
        result = _run(_default_delegate_post(
            'target-member', 'do this work', skill=None,
            _bus_for_test=_StubBus([]),
        ))
        payload = json.loads(result)
        self.assertEqual(
            payload.get('status'), 'message_sent',
            f'Delegate must return status=message_sent on success; '
            f'got: {payload}',
        )
        self.assertTrue(
            payload.get('conversation_id', '').startswith('dispatch:'),
            f'Delegate must return conversation_id of shape '
            f'dispatch:<sid>; got: {payload.get("conversation_id")!r}',
        )


class DelegateOpenThreadPreconditionTest(unittest.TestCase):
    """Acceptance criterion 2: open ACTIVE thread to target → rejection."""

    def setUp(self) -> None:
        mcp_registry.clear()

    def tearDown(self) -> None:
        mcp_registry.clear()

    def _register_spawn_that_records_calls(self, calls: list) -> None:
        async def spawn(member, composite, context_id):
            calls.append((member, composite, context_id))
            return ('newsid', '/tmp/wt', '')
        mcp_registry.register_spawn_fn('caller-agent', spawn)
        mcp_registry.current_agent_name.set('caller-agent')

    def test_open_active_thread_rejects_without_invoking_spawn(self) -> None:
        """A pre-existing ACTIVE dispatch to the same member must reject
        Delegate without calling spawn_fn at all."""
        from teaparty.mcp.tools.messaging import _default_delegate_post

        spawn_calls: list = []
        self._register_spawn_that_records_calls(spawn_calls)

        existing_thread = 'dispatch:already_open_abc'
        bus = _StubBus([
            _ConvRow(existing_thread, 'workgroup-lead', 'active'),
        ])

        result = _run(_default_delegate_post(
            'workgroup-lead', 'new work', skill='attempt-task',
            _bus_for_test=bus,
        ))
        payload = json.loads(result)

        self.assertEqual(
            payload.get('status'), 'failed',
            f'Open ACTIVE thread to target must produce status=failed; '
            f'got: {payload}',
        )
        self.assertIn(
            existing_thread, payload.get('reason', ''),
            f'Rejection reason must name the existing channel '
            f'({existing_thread!r}) so the caller can re-route via Send. '
            f'Got reason: {payload.get("reason")!r}',
        )
        self.assertIn(
            'Send', payload.get('reason', ''),
            f'Rejection reason must direct the caller to Send for '
            f'continuation. Got reason: {payload.get("reason")!r}',
        )
        self.assertEqual(
            spawn_calls, [],
            f'spawn_fn must NOT be invoked when the precondition rejects; '
            f'observed calls: {spawn_calls!r}',
        )

    def test_closed_thread_does_not_block_delegate(self) -> None:
        """Only ACTIVE threads block. A CLOSED thread to the same target
        must allow Delegate to proceed (otherwise the caller would be
        permanently blocked from re-dispatching after a normal close)."""
        from teaparty.mcp.tools.messaging import _default_delegate_post

        spawn_calls: list = []
        self._register_spawn_that_records_calls(spawn_calls)

        bus = _StubBus([
            _ConvRow('dispatch:old_closed', 'workgroup-lead', 'closed'),
        ])

        result = _run(_default_delegate_post(
            'workgroup-lead', 'fresh work', skill='attempt-task',
            _bus_for_test=bus,
        ))
        payload = json.loads(result)

        self.assertEqual(
            payload.get('status'), 'message_sent',
            f'CLOSED thread must not block a new Delegate; got: {payload}',
        )
        self.assertEqual(
            len(spawn_calls), 1,
            f'spawn_fn must be invoked exactly once when precondition '
            f'allows; observed: {spawn_calls!r}',
        )

    def test_open_thread_to_different_member_does_not_block(self) -> None:
        """An open thread to member A must not block a Delegate to member B."""
        from teaparty.mcp.tools.messaging import _default_delegate_post

        spawn_calls: list = []
        self._register_spawn_that_records_calls(spawn_calls)

        bus = _StubBus([
            _ConvRow('dispatch:other_member', 'other-lead', 'active'),
        ])

        result = _run(_default_delegate_post(
            'workgroup-lead', 'work', skill=None,
            _bus_for_test=bus,
        ))
        payload = json.loads(result)
        self.assertEqual(
            payload.get('status'), 'message_sent',
            f'Open thread to other-lead must not block Delegate to '
            f'workgroup-lead; got: {payload}',
        )
        self.assertEqual(len(spawn_calls), 1)


class DelegateWorkflowPrefixTest(unittest.TestCase):
    """Acceptance criteria 3 & 4: skill prefix injection."""

    def setUp(self) -> None:
        mcp_registry.clear()

    def tearDown(self) -> None:
        mcp_registry.clear()

    def _register_capturing_spawn(self, captured: list) -> None:
        async def spawn(member, composite, context_id):
            captured.append({'member': member, 'composite': composite,
                             'context_id': context_id})
            return ('sid123', '/tmp/wt', '')
        mcp_registry.register_spawn_fn('caller-agent', spawn)
        mcp_registry.current_agent_name.set('caller-agent')

    def test_skill_set_injects_directive_naming_skill_with_slash(self) -> None:
        """When `skill='attempt-task'`, the dispatched composite must
        contain a directive that names the skill prefixed with `/`,
        following the same pattern the engine uses for project-leads
        (e.g. `Run the /attempt-task skill...`)."""
        from teaparty.mcp.tools.messaging import _default_delegate_post

        captured: list = []
        self._register_capturing_spawn(captured)

        _run(_default_delegate_post(
            'workgroup-lead', 'produce a report', skill='attempt-task',
            _bus_for_test=_StubBus([]),
        ))
        self.assertEqual(len(captured), 1)
        composite = captured[0]['composite']
        self.assertIn(
            '/attempt-task', composite,
            f'Composite must contain `/attempt-task` directive when '
            f'skill is set. Got composite head: {composite[:200]!r}',
        )
        # Original task body is preserved.
        self.assertIn(
            'produce a report', composite,
            f'Original task body must survive prefix injection. '
            f'Got composite head: {composite[:200]!r}',
        )

    def test_skill_none_emits_no_skill_directive(self) -> None:
        """When `skill=None`, the composite must contain no `/<skill>`
        directive. Delegate-without-skill is a plain dispatch (the
        recipient processes the task directly, e.g. specialists)."""
        from teaparty.mcp.tools.messaging import _default_delegate_post

        captured: list = []
        self._register_capturing_spawn(captured)

        _run(_default_delegate_post(
            'specialist', 'small task', skill=None,
            _bus_for_test=_StubBus([]),
        ))
        composite = captured[0]['composite']
        # No leading slash command pattern.
        self.assertNotIn(
            '/attempt-task', composite,
            f'Composite must NOT contain `/attempt-task` when skill=None. '
            f'Got composite head: {composite[:200]!r}',
        )

    def test_skill_attempt_task_composite_contains_task_body(self) -> None:
        """The original task body must appear in the composite, after
        the skill directive. Without this, the recipient runs the
        skill but receives no task — workflow with no work."""
        from teaparty.mcp.tools.messaging import _default_delegate_post

        captured: list = []
        self._register_capturing_spawn(captured)

        unique_marker = 'XYZ_TASK_MARKER_42'
        _run(_default_delegate_post(
            'workgroup-lead', f'{unique_marker} the body content here',
            skill='attempt-task',
            _bus_for_test=_StubBus([]),
        ))
        composite = captured[0]['composite']
        self.assertIn(
            unique_marker, composite,
            f'Original task body marker {unique_marker!r} must be '
            f'present in the dispatched composite. The skill directive '
            f'must not consume the body. Got: {composite[:300]!r}',
        )


class DelegateInputValidationTest(unittest.TestCase):
    """The handler must reject empty member or empty task."""

    def test_empty_member_raises(self) -> None:
        from teaparty.mcp.tools.messaging import delegate_handler
        with self.assertRaisesRegex(ValueError, 'member'):
            _run(delegate_handler(member='', task='x'))

    def test_empty_task_raises(self) -> None:
        from teaparty.mcp.tools.messaging import delegate_handler
        with self.assertRaisesRegex(ValueError, 'task'):
            _run(delegate_handler(member='m', task=''))


if __name__ == '__main__':
    unittest.main()
