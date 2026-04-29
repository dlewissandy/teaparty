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
        (e.g. `Run the /attempt-task skill...`).

        The prefix is built by ``delegate_handler`` (the public entry
        point) before the post_fn is called, so this test exercises
        the handler — not the bare post_fn — to cover the full path.
        """
        from teaparty.mcp.tools.messaging import delegate_handler

        captured: list = []
        self._register_capturing_spawn(captured)

        async def post(member, composite, skill):
            from teaparty.mcp.tools.messaging import _default_delegate_post
            return await _default_delegate_post(
                member, composite, skill,
            )

        _run(delegate_handler(
            member='workgroup-lead', task='produce a report',
            skill='attempt-task',
            scratch_path='/no/such/scratch',
            post_fn=post,
        ))
        self.assertEqual(len(captured), 1)
        composite = captured[0]['composite']
        self.assertIn(
            '/attempt-task', composite,
            f'Composite must contain `/attempt-task` directive when '
            f'skill is set. Got composite head: {composite[:200]!r}',
        )
        # Spec wording: the composite *begins with* the directive.
        # A regression that swaps composition order to put the directive
        # at the end (or in the middle) would still satisfy a bare
        # ``in`` check but violates the spec. The exact form is bare
        # slash with no backticks — same prose pattern the CfA engine
        # uses for project-lead skills.
        self.assertTrue(
            composite.lstrip().startswith('Run the /attempt-task'),
            f'Composite must START with the skill directive in the '
            f'engine\'s exact prose form (`Run the /<skill> skill...`, '
            f'bare slash, no backticks). Got composite head: '
            f'{composite[:200]!r}',
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
        from teaparty.mcp.tools.messaging import delegate_handler

        captured: list = []
        self._register_capturing_spawn(captured)

        async def post(member, composite, skill):
            from teaparty.mcp.tools.messaging import _default_delegate_post
            return await _default_delegate_post(
                member, composite, skill,
            )

        _run(delegate_handler(
            member='specialist', task='small task', skill=None,
            scratch_path='/no/such/scratch',
            post_fn=post,
        ))
        composite = captured[0]['composite']
        # Broad negative-space: no skill directive of any shape may
        # appear when skill=None.  An always-fire regression that
        # rendered ``Run the /None skill...`` would not contain
        # ``/attempt-task`` but would contain the directive opener
        # ``Run the /`` — the broader pattern catches that.
        self.assertNotIn(
            '/attempt-task', composite,
            f'Composite must NOT contain `/attempt-task` when skill=None. '
            f'Got composite head: {composite[:200]!r}',
        )
        self.assertNotIn(
            'Run the /', composite,
            f'Composite must NOT contain any `Run the /<skill>...` '
            f'directive when skill=None — the prefix block must be '
            f'gated by ``if skill:``, not always-fire. '
            f'Got composite head: {composite[:200]!r}',
        )

    def test_skill_attempt_task_composite_contains_task_body(self) -> None:
        """The original task body must appear in the composite, after
        the skill directive. Without this, the recipient runs the
        skill but receives no task — workflow with no work."""
        from teaparty.mcp.tools.messaging import delegate_handler

        captured: list = []
        self._register_capturing_spawn(captured)

        async def post(member, composite, skill):
            from teaparty.mcp.tools.messaging import _default_delegate_post
            return await _default_delegate_post(
                member, composite, skill,
            )

        unique_marker = 'XYZ_TASK_MARKER_42'
        _run(delegate_handler(
            member='workgroup-lead',
            task=f'{unique_marker} the body content here',
            skill='attempt-task',
            scratch_path='/no/such/scratch',
            post_fn=post,
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


class ToolDescriptionDisambiguationTest(unittest.TestCase):
    """Send and Delegate must describe themselves so a model picking
    between them at choice-time has unambiguous guidance.

    The bug class this guards against: a workgroup-lead with both
    Send and Delegate in its catalog defaulting to Send (its trained
    instinct) for a fresh dispatch — exactly the failure mode that
    motivated #423 at the project-lead level.  Fixing the catalog
    ontology without fixing the descriptions would leave the
    confusion vector open at every nesting level.
    """

    def test_send_docstring_scopes_to_continuation_or_peer(self) -> None:
        """Send's tool docstring must NOT describe it as opening new
        dispatch threads — that role belongs to Delegate now."""
        from teaparty.mcp.server import main as _server_main
        import inspect
        src = inspect.getsource(_server_main.create_server)
        # Locate the Send tool definition.  Fragile to refactor but
        # acceptable: the bug class is "Send still claims to dispatch."
        send_idx = src.find('async def Send(')
        self.assertGreater(send_idx, -1)
        # Read the docstring block following ``async def Send``.
        next_def = src.find('async def ', send_idx + 1)
        send_block = src[send_idx:next_def] if next_def > 0 else src[send_idx:]
        self.assertIn(
            'Continue', send_block,
            f'Send docstring must scope itself to thread continuation '
            f'or peer messaging. The old "opening or continuing" '
            f'wording leaves the dispatch role ambiguous, defeating '
            f'the verb-tool split #423 introduces.',
        )
        self.assertIn(
            'Delegate', send_block,
            f'Send docstring must point the agent at Delegate for '
            f'opening new dispatch threads. Without this redirect, '
            f'an agent picking between the two tools may default to '
            f'its trained Send-as-dispatch instinct.',
        )

    def test_delegate_docstring_describes_open_thread_role(self) -> None:
        """Delegate's tool docstring must position it as the
        open-new-thread verb, not as a generic dispatch alternative."""
        from teaparty.mcp.server import main as _server_main
        import inspect
        src = inspect.getsource(_server_main.create_server)
        delegate_idx = src.find('async def Delegate(')
        self.assertGreater(delegate_idx, -1)
        block = src[max(0, delegate_idx - 2000):delegate_idx]
        # Either ``new dispatch thread`` or ``fresh dispatch thread`` —
        # the framing is what matters, not the specific adjective.
        opens_thread = (
            'new dispatch thread' in block
            or 'fresh dispatch thread' in block
        )
        self.assertTrue(
            opens_thread,
            f'Delegate docstring must describe its role as opening a '
            f'(new|fresh) dispatch thread — the verb the issue spec '
            f'assigns to it. Without this framing, the tool-choice '
            f'signal at agent decision time is muddled.',
        )


if __name__ == '__main__':
    unittest.main()
