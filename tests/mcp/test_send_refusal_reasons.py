#!/usr/bin/env python3
"""Send handler must surface spawn_fn's refusal reason faithfully.

Before: every ``spawn_fn`` refusal — slot-limit, paused project,
unresolved member, worktree creation failure — was reported to the
calling agent as "you already have three open conversations." That
sent agents chasing the wrong fix (close a conversation) when the
real problem was a missing roster entry or a paused project.

After: ``spawn_fn`` signals the refusal reason in the third slot of
its return tuple (when ``session_id`` is empty), and the Send handler
translates the code to a specific user-facing message.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from teaparty.mcp.tools.messaging import (
    _spawn_refusal_reason, _default_send_post,
)
from teaparty.mcp import registry as mcp_registry


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


class TestSpawnRefusalReasonTranslation(unittest.TestCase):
    """The pure translation helper: code → user-facing message."""

    def test_slot_limit_says_three_open_conversations(self):
        msg = _spawn_refusal_reason('slot_limit', 'any-member')
        self.assertIn('three open conversations', msg)
        self.assertIn('CloseConversation', msg)

    def test_paused_says_project_is_paused(self):
        msg = _spawn_refusal_reason('paused', 'any-member')
        self.assertIn('paused', msg.lower())
        self.assertNotIn('three open conversations', msg)

    def test_unresolved_member_names_the_member_and_directs_to_list_tools(self):
        msg = _spawn_refusal_reason(
            'unresolved_member:project-specialist', 'fallback-name')
        self.assertIn('project-specialist', msg)
        self.assertIn('ListTeamMembers', msg)
        self.assertNotIn('three open conversations', msg)

    def test_unresolved_member_falls_back_to_member_arg_if_code_has_no_name(self):
        msg = _spawn_refusal_reason('unresolved_member:', 'caller-supplied')
        self.assertIn('caller-supplied', msg)

    def test_worktree_failure_names_the_member_and_points_to_log(self):
        msg = _spawn_refusal_reason('worktree_failed', 'teaparty-lead')
        self.assertIn('teaparty-lead', msg)
        self.assertIn('log', msg.lower())
        self.assertNotIn('three open conversations', msg)

    def test_unknown_code_does_not_crash_and_names_the_member(self):
        msg = _spawn_refusal_reason('something-new', 'some-member')
        self.assertIn('some-member', msg)


class TestSendHandlerSurfacesRefusalReason(unittest.TestCase):
    """End-to-end: spawn_fn returns a refusal code, handler translates it."""

    def setUp(self):
        mcp_registry.clear()

    def tearDown(self):
        mcp_registry.clear()

    def _register_refusing_spawn(self, reason_code: str):
        """Register a spawn_fn that always refuses with ``reason_code``."""
        async def spawn(member, composite, context_id):
            return ('', '', reason_code)
        mcp_registry.register_spawn_fn('caller-agent', spawn)
        mcp_registry.current_agent_name.set('caller-agent')

    def test_slot_limit_code_produces_three_open_conversations_message(self):
        self._register_refusing_spawn('slot_limit')
        result = _run(_default_send_post('target', 'msg', ''))
        payload = json.loads(result)
        self.assertEqual(payload['status'], 'failed')
        self.assertIn('three open conversations', payload['reason'])

    def test_unresolved_member_code_produces_roster_message_not_slot_message(self):
        self._register_refusing_spawn('unresolved_member:project-specialist')
        result = _run(_default_send_post('project-specialist', 'msg', ''))
        payload = json.loads(result)
        self.assertEqual(payload['status'], 'failed')
        self.assertIn('project-specialist', payload['reason'])
        self.assertIn('ListTeamMembers', payload['reason'])
        self.assertNotIn(
            'three open conversations', payload['reason'],
            'Send must not blame the slot limit when the real cause '
            'is a missing roster entry — that sends the agent chasing '
            'the wrong fix',
        )

    def test_paused_code_produces_paused_message_not_slot_message(self):
        self._register_refusing_spawn('paused')
        result = _run(_default_send_post('target', 'msg', ''))
        payload = json.loads(result)
        self.assertEqual(payload['status'], 'failed')
        self.assertIn('paused', payload['reason'].lower())
        self.assertNotIn('three open conversations', payload['reason'])

    def test_worktree_failed_code_surfaces_worktree_error(self):
        self._register_refusing_spawn('worktree_failed')
        result = _run(_default_send_post('target', 'msg', ''))
        payload = json.loads(result)
        self.assertEqual(payload['status'], 'failed')
        self.assertIn('worktree', payload['reason'].lower())
        self.assertNotIn('three open conversations', payload['reason'])


if __name__ == '__main__':
    unittest.main()
