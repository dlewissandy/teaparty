"""Cut 29: bus-based human-intervention delivery.

Replaces the deleted ``InterventionQueue`` with a watermark-driven
bus read.  These tests pin the contract:

* Trailing human messages on the bus at construction get delivered
  on the first ``_deliver_intervention`` call (the resume path).
* Messages already-acknowledged (after a non-human bus message) are
  skipped — the watermark starts past them.
* Each ``_deliver_intervention`` call advances the watermark so the
  same message isn't delivered twice.
* No-op when no new messages.
* role_enforcer.check_send filters informed senders.

The orchestrator's ``_pending_job_prompt`` slot is the post-condition
the gate inspects — when it's non-empty after ``_deliver_intervention``,
the engine prepends it to the next agent turn.
"""
from __future__ import annotations

import asyncio
import os
import shutil
import tempfile
import time
import unittest
from unittest.mock import AsyncMock, MagicMock

from teaparty.cfa.engine import Orchestrator
from teaparty.cfa.run_options import RunOptions
from teaparty.cfa.phase_config import PhaseConfig
from teaparty.cfa.statemachine.cfa_state import CfaState
from teaparty.messaging.bus import EventBus
from teaparty.messaging.conversations import (
    ConversationType, SqliteMessageBus,
)


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def _make_phase_config():
    cfg = MagicMock(spec=PhaseConfig)
    cfg.stall_timeout = 1800
    cfg.project_lead = 'lead'
    return cfg


def _make_orchestrator(infra_dir: str, project_slug: str = 'proj',
                      session_id: str = 'sess-1') -> Orchestrator:
    return Orchestrator(
        cfa_state=CfaState(state='INTENT', phase='intent', history=[],
                           backtrack_count=0),
        phase_config=_make_phase_config(),
        event_bus=MagicMock(spec=EventBus, publish=AsyncMock()),
        input_provider=AsyncMock(),
        infra_dir=infra_dir,
        project_workdir='/tmp/project',
        session_worktree=infra_dir,
        proxy_model_path='/tmp/proxy.json',
        project_slug=project_slug,
        poc_root='/tmp/poc',
        task='do a thing',
        session_id=session_id,
        options=RunOptions(),
    )


class TestBusWatermark(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix='tp-iv-')
        bus_path = os.path.join(self._tmp, 'messages.db')
        self._bus = SqliteMessageBus(bus_path)
        self._bus.create_conversation(
            ConversationType.JOB, 'proj:sess-1',
            agent_name='lead', project_slug='proj',
        )
        self._conv_id = 'job:proj:sess-1'

    def tearDown(self):
        try:
            self._bus.close()
        except Exception:
            pass
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_no_messages_means_no_delivery(self):
        """Empty bus → no _pending_job_prompt set."""
        orch = _make_orchestrator(self._tmp)
        _run(orch._deliver_intervention())
        self.assertEqual(orch._pending_job_prompt, '')

    def test_trailing_human_message_delivered_on_first_call(self):
        """A human message after the last agent message is delivered."""
        # Seed: one agent message, then one trailing human message.
        self._bus.send(self._conv_id, 'lead', 'I started work')
        time.sleep(0.001)  # Ensure distinct timestamps
        self._bus.send(self._conv_id, 'human', 'wait, change the task')

        orch = _make_orchestrator(self._tmp)
        _run(orch._deliver_intervention())

        self.assertIn('change the task', orch._pending_job_prompt)
        self.assertIn('CfA INTERVENE', orch._pending_job_prompt)

    def test_already_answered_human_message_not_redelivered(self):
        """A human message followed by an agent reply is past the watermark."""
        # Seed: human msg, then agent reply (the agent saw + answered it).
        self._bus.send(self._conv_id, 'human', 'old question')
        time.sleep(0.001)
        self._bus.send(self._conv_id, 'lead', 'here is my answer')

        orch = _make_orchestrator(self._tmp)
        _run(orch._deliver_intervention())

        self.assertEqual(
            orch._pending_job_prompt, '',
            'human message that was already followed by an agent reply '
            'must not be re-delivered — the watermark starts past it.',
        )

    def test_watermark_advances_so_same_message_not_delivered_twice(self):
        """After delivery, the next call must not re-deliver the same msg."""
        # Trailing human message.
        self._bus.send(self._conv_id, 'lead', 'started')
        time.sleep(0.001)
        self._bus.send(self._conv_id, 'human', 'change something')

        orch = _make_orchestrator(self._tmp)

        # First call: delivers.
        _run(orch._deliver_intervention())
        self.assertIn('change something', orch._pending_job_prompt)

        # Reset the slot to simulate the engine consuming it.
        orch._pending_job_prompt = ''

        # Second call (no new messages): no-op.
        _run(orch._deliver_intervention())
        self.assertEqual(
            orch._pending_job_prompt, '',
            'a delivered message must not be redelivered — the watermark '
            'must have advanced past it.',
        )

    def test_new_message_after_first_delivery_picked_up(self):
        """Watermark only suppresses already-delivered messages, not new ones."""
        self._bus.send(self._conv_id, 'lead', 'started')
        time.sleep(0.001)
        self._bus.send(self._conv_id, 'human', 'first interjection')

        orch = _make_orchestrator(self._tmp)
        _run(orch._deliver_intervention())
        self.assertIn('first interjection', orch._pending_job_prompt)
        orch._pending_job_prompt = ''

        # New human message after the first delivery.
        time.sleep(0.001)
        self._bus.send(self._conv_id, 'human', 'second interjection')

        _run(orch._deliver_intervention())
        self.assertIn('second interjection', orch._pending_job_prompt)
        self.assertNotIn(
            'first interjection', orch._pending_job_prompt,
            'a previously-delivered message must not be repeated when '
            'a new message arrives.',
        )

    def test_role_enforcer_blocks_informed_sender(self):
        """role_enforcer.check_send raising filters out the message."""
        self._bus.send(self._conv_id, 'lead', 'started')
        time.sleep(0.001)
        self._bus.send(self._conv_id, 'human', 'go ahead')

        orch = _make_orchestrator(self._tmp)
        # Stub a role_enforcer that refuses ALL senders.
        orch._role_enforcer = MagicMock()
        orch._role_enforcer.is_advisory.return_value = False
        orch._role_enforcer.check_send.side_effect = RuntimeError('blocked')

        _run(orch._deliver_intervention())
        self.assertEqual(
            orch._pending_job_prompt, '',
            'role_enforcer that refuses must filter out the human msg.',
        )


if __name__ == '__main__':
    unittest.main()
