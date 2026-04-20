"""Tests for issue #408 — CfA jobs use project lead from project.yaml.

Specification-based tests covering:
  1. PhaseConfig.resolve_phase() substitutes the project lead for 'project-lead'
     when project.yaml defines a lead — for planning and execution phases.
  2. Intent phase is NOT affected (out of scope per issue).
  3. Projects without a configured lead fall back to the phase-config.json default.
  4. _make_stream_event_handler uses the configured agent_sender, not hardcoded 'agent'.
  5. MessageBusInputProvider uses the configured sender, not hardcoded 'orchestrator'.
  6. check_message_bus_request finds gate questions regardless of sender name.
  7. The flat-mode path does not re-hardcode 'project-lead'.

Acceptance criteria mapped to test methods (see issue #408):
  AC1: planning/execution run project lead → TestPhaseConfigLeadResolution
  AC2: lead agent tools/skills/prompt active → TestAgentDefinitionResolution
  AC3: messages attributed to lead by name → TestStreamEventHandlerSender +
       TestMessageBusInputProviderSender + TestResumeSenderAttribution
  AC4: projects without lead fall back → TestPhaseConfigLeadResolution.*fallback*
  AC5: one source of truth → TestPhaseConfigLeadResolution (reads same project.yaml)
"""
import asyncio
import os
import shutil
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import yaml

from teaparty.cfa.engine import _make_stream_event_handler
from teaparty.cfa.phase_config import PhaseConfig
from teaparty.cfa.session import _resolve_project_lead_sender
from teaparty.runners.launcher import resolve_agent_definition
from teaparty.messaging.bus import InputRequest
from teaparty.messaging.conversations import (
    ConversationType,
    MessageBusInputProvider,
    SqliteMessageBus,
    check_message_bus_request,
    make_conversation_id,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _run(coro):
    return asyncio.run(coro)


def _make_tmp(tc: unittest.TestCase) -> str:
    tmp = tempfile.mkdtemp(prefix='teaparty-408-test-')
    tc.addCleanup(shutil.rmtree, tmp, True)
    return tmp


def _install_jail_hook(worktree: str) -> None:
    """Create a stub worktree_hook.py so AgentRunner validation passes in tests."""
    hook_dir = os.path.join(worktree, '.claude', 'hooks')
    os.makedirs(hook_dir, exist_ok=True)
    with open(os.path.join(hook_dir, 'worktree_hook.py'), 'w') as f:
        f.write('# stub\n')


def _make_project_yaml(project_dir: str, lead: str = '') -> None:
    """Write a minimal project.yaml with the given lead into project_dir."""
    config_dir = os.path.join(project_dir, '.teaparty', 'project')
    os.makedirs(config_dir, exist_ok=True)
    data = {'name': 'test-project', 'description': 'test'}
    if lead:
        data['lead'] = lead
    with open(os.path.join(config_dir, 'project.yaml'), 'w') as f:
        yaml.dump(data, f)


def _make_phase_config(project_dir: str | None = None) -> PhaseConfig:
    """Build a PhaseConfig against the real phase-config.json."""
    # poc_root is the teaparty package root (two levels up from this file)
    poc_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return PhaseConfig(poc_root, project_dir=project_dir)


def _make_bus(tc: unittest.TestCase) -> tuple[SqliteMessageBus, str]:
    """Create a real SQLite message bus in a temp dir."""
    tmp = _make_tmp(tc)
    db_path = os.path.join(tmp, 'messages.db')
    bus = SqliteMessageBus(db_path)
    tc.addCleanup(bus.close)
    return bus, db_path


# ── Layer 1: PhaseConfig lead resolution ─────────────────────────────────────

class TestPhaseConfigLeadResolution(unittest.TestCase):
    """PhaseConfig.resolve_phase() must substitute the project lead from project.yaml."""

    def test_planning_phase_uses_project_lead_from_project_yaml(self):
        """resolve_phase('planning') returns the project's configured lead, not 'project-lead'."""
        tmp = _make_tmp(self)
        _make_project_yaml(tmp, lead='comics-lead')
        cfg = _make_phase_config(project_dir=tmp)

        spec = cfg.resolve_phase('planning')

        self.assertEqual(
            spec.lead, 'comics-lead',
            'planning phase must use the project lead from project.yaml, '
            f"got '{spec.lead}' — phase-config.json default 'project-lead' was not overridden",
        )

    def test_execution_phase_uses_project_lead_from_project_yaml(self):
        """resolve_phase('execution') returns the project's configured lead, not 'project-lead'."""
        tmp = _make_tmp(self)
        _make_project_yaml(tmp, lead='comics-lead')
        cfg = _make_phase_config(project_dir=tmp)

        spec = cfg.resolve_phase('execution')

        self.assertEqual(
            spec.lead, 'comics-lead',
            'execution phase must use the project lead from project.yaml, '
            f"got '{spec.lead}' — phase-config.json default 'project-lead' was not overridden",
        )

    def test_intent_phase_not_substituted_with_project_lead(self):
        """Intent phase keeps its own configured lead — project lead substitution is out of scope."""
        tmp = _make_tmp(self)
        _make_project_yaml(tmp, lead='comics-lead')
        cfg = _make_phase_config(project_dir=tmp)

        spec = cfg.resolve_phase('intent')

        # Intent phase has its own lead ('intent-lead') and must NOT be replaced
        # by the project lead. The issue explicitly excludes the intent phase.
        self.assertNotEqual(
            spec.lead, 'comics-lead',
            'intent phase must NOT use the project lead — intent is explicitly out of scope '
            '(see issue #408). Only planning and execution phases are in scope.',
        )

    def test_planning_phase_falls_back_when_no_project_yaml(self):
        """resolve_phase('planning') falls back to 'project-lead' when no project.yaml exists."""
        tmp = _make_tmp(self)
        # No project.yaml created — project_dir has no .teaparty/project/project.yaml
        cfg = _make_phase_config(project_dir=tmp)

        spec = cfg.resolve_phase('planning')

        self.assertEqual(
            spec.lead, 'project-lead',
            "planning phase must fall back to 'project-lead' when project.yaml is absent, "
            f"got '{spec.lead}'",
        )

    def test_planning_phase_falls_back_when_lead_field_absent(self):
        """resolve_phase('planning') falls back to 'project-lead' when project.yaml has no lead."""
        tmp = _make_tmp(self)
        _make_project_yaml(tmp, lead='')  # writes project.yaml with no lead key
        cfg = _make_phase_config(project_dir=tmp)

        spec = cfg.resolve_phase('planning')

        self.assertEqual(
            spec.lead, 'project-lead',
            "planning phase must fall back to 'project-lead' when project.yaml has no 'lead' field, "
            f"got '{spec.lead}'",
        )

    def test_planning_phase_falls_back_when_no_project_dir(self):
        """resolve_phase('planning') falls back to 'project-lead' when PhaseConfig has no project_dir."""
        cfg = _make_phase_config(project_dir=None)

        spec = cfg.resolve_phase('planning')

        self.assertEqual(
            spec.lead, 'project-lead',
            "planning phase must fall back to 'project-lead' when no project_dir is set, "
            f"got '{spec.lead}'",
        )

    def test_project_lead_property_returns_configured_lead(self):
        """PhaseConfig.project_lead returns the lead from project.yaml."""
        tmp = _make_tmp(self)
        _make_project_yaml(tmp, lead='comics-lead')
        cfg = _make_phase_config(project_dir=tmp)

        self.assertEqual(
            cfg.project_lead, 'comics-lead',
            'PhaseConfig.project_lead must return the lead from project.yaml, '
            f"got '{cfg.project_lead}'",
        )

    def test_project_lead_property_returns_empty_when_no_project_yaml(self):
        """PhaseConfig.project_lead returns empty string when no project.yaml exists."""
        tmp = _make_tmp(self)
        cfg = _make_phase_config(project_dir=tmp)

        self.assertEqual(
            cfg.project_lead, '',
            "PhaseConfig.project_lead must return '' when no project.yaml exists, "
            f"got '{cfg.project_lead}'",
        )

    def test_execution_phase_non_lead_fields_unchanged(self):
        """Substituting the lead must not alter other PhaseSpec fields (regression guard)."""
        tmp = _make_tmp(self)
        _make_project_yaml(tmp, lead='comics-lead')
        cfg = _make_phase_config(project_dir=tmp)
        base = cfg.phase('execution')

        spec = cfg.resolve_phase('execution')

        self.assertEqual(spec.agent_file, base.agent_file,
                         'agent_file must not change when substituting lead')
        self.assertEqual(spec.permission_mode, base.permission_mode,
                         'permission_mode must not change when substituting lead')
        self.assertEqual(spec.stream_file, base.stream_file,
                         'stream_file must not change when substituting lead')
        self.assertEqual(spec.artifact, base.artifact,
                         'artifact must not change when substituting lead')
        self.assertEqual(spec.approval_state, base.approval_state,
                         'approval_state must not change when substituting lead')

    def test_different_project_leads_for_different_projects(self):
        """Two different project dirs produce two different phase specs (no cross-contamination)."""
        tmp_a = _make_tmp(self)
        tmp_b = _make_tmp(self)
        _make_project_yaml(tmp_a, lead='comics-lead')
        _make_project_yaml(tmp_b, lead='scifi-lead')

        cfg_a = _make_phase_config(project_dir=tmp_a)
        cfg_b = _make_phase_config(project_dir=tmp_b)

        spec_a = cfg_a.resolve_phase('planning')
        spec_b = cfg_b.resolve_phase('planning')

        self.assertEqual(spec_a.lead, 'comics-lead',
                         'project A must use comics-lead')
        self.assertEqual(spec_b.lead, 'scifi-lead',
                         'project B must use scifi-lead')
        self.assertNotEqual(spec_a.lead, spec_b.lead,
                            'two different projects must not share the same lead')


# ── Layer 2: Flat-mode phase spec ────────────────────────────────────────────

class TestFlatModePhaseSpec(unittest.TestCase):
    """In --flat mode, _phase_spec must use the project lead, not hardcoded 'project-lead'."""

    def _make_orchestrator(self, project_dir: str, flat: bool = True):
        from teaparty.cfa.engine import Orchestrator
        from teaparty.messaging.bus import EventBus
        from unittest.mock import AsyncMock

        cfg = _make_phase_config(project_dir=project_dir)
        from teaparty.cfa.statemachine.cfa_state import CfaState
        cfa = CfaState(
            state='PLANNING_WORK',
            phase='planning',
            actor='agent',
            history=[],
            backtrack_count=0,
        )
        event_bus = MagicMock(spec=EventBus)
        event_bus.publish = AsyncMock()

        orch = Orchestrator(
            cfa_state=cfa,
            phase_config=cfg,
            event_bus=event_bus,
            input_provider=AsyncMock(return_value='approve'),
            infra_dir='/tmp/infra',
            project_workdir=project_dir,
            session_worktree='/tmp/worktree',
            proxy_model_path='/tmp/proxy.json',
            project_slug='comics',
            poc_root=cfg.poc_root,
            task='Do something',
            session_id='test-001',
            flat=flat,
            project_dir=project_dir,
        )
        return orch

    def test_flat_mode_planning_uses_project_lead_not_hardcoded(self):
        """_phase_spec('planning') in flat mode must use the project lead, not 'project-lead'."""
        tmp = _make_tmp(self)
        _make_project_yaml(tmp, lead='comics-lead')
        orch = self._make_orchestrator(project_dir=tmp, flat=True)

        spec = orch._phase_spec('planning')

        self.assertEqual(
            spec.lead, 'comics-lead',
            "flat mode _phase_spec('planning') must use the project lead from project.yaml, "
            f"got '{spec.lead}' — 'project-lead' was hardcoded instead of using the resolved lead",
        )

    def test_flat_mode_execution_uses_project_lead_not_hardcoded(self):
        """_phase_spec('execution') in flat mode must use the project lead, not 'project-lead'."""
        tmp = _make_tmp(self)
        _make_project_yaml(tmp, lead='comics-lead')
        orch = self._make_orchestrator(project_dir=tmp, flat=True)

        spec = orch._phase_spec('execution')

        self.assertEqual(
            spec.lead, 'comics-lead',
            "flat mode _phase_spec('execution') must use the project lead from project.yaml, "
            f"got '{spec.lead}' — 'project-lead' was hardcoded instead of using the resolved lead",
        )

    def test_non_flat_planning_also_uses_project_lead(self):
        """Normal (non-flat) mode also uses the project lead — confirms the same code path."""
        tmp = _make_tmp(self)
        _make_project_yaml(tmp, lead='comics-lead')
        orch = self._make_orchestrator(project_dir=tmp, flat=False)

        spec = orch._phase_spec('planning')

        self.assertEqual(
            spec.lead, 'comics-lead',
            "non-flat _phase_spec('planning') must use the project lead from project.yaml, "
            f"got '{spec.lead}'",
        )


# ── Layer 3: Stream event handler sender ─────────────────────────────────────

class TestStreamEventHandlerSender(unittest.TestCase):
    """_make_stream_event_handler must use the configured agent_sender, not 'agent'."""

    def _make_mock_bus(self):
        """Return a mock bus that records all sends as (sender, content) tuples."""
        bus = MagicMock()
        sent = []
        bus.send.side_effect = lambda conv_id, sender, content: sent.append((sender, content))
        return bus, sent

    def test_assistant_text_uses_configured_agent_sender(self):
        """An 'assistant' text event must be sent with agent_sender, not 'agent'."""
        bus, sent = self._make_mock_bus()
        handler = _make_stream_event_handler(bus, 'job:test:001', agent_sender='comics-lead')

        handler({'type': 'assistant', 'message': {'content': 'Here is my plan'}})

        self.assertEqual(len(sent), 1,
                         f'expected 1 message sent, got {len(sent)}')
        sender, content = sent[0]
        self.assertEqual(
            sender, 'comics-lead',
            f"assistant text event must be sent as 'comics-lead', got '{sender}'",
        )
        self.assertEqual(content, 'Here is my plan')

    def test_assistant_text_does_not_send_as_agent_when_lead_configured(self):
        """When agent_sender='comics-lead', no message must have sender 'agent' (regression guard)."""
        bus, sent = self._make_mock_bus()
        handler = _make_stream_event_handler(bus, 'job:test:001', agent_sender='comics-lead')

        handler({'type': 'assistant', 'message': {'content': 'Hello'}})
        handler({'type': 'result', 'result': 'Done'})

        senders = [s for s, _ in sent]
        self.assertNotIn(
            'agent', senders,
            f"no event must use sender 'agent' when agent_sender='comics-lead'; "
            f"senders seen: {senders}",
        )

    def test_result_event_uses_configured_agent_sender(self):
        """A 'result' event must use agent_sender, not 'agent'."""
        bus, sent = self._make_mock_bus()
        handler = _make_stream_event_handler(bus, 'job:test:001', agent_sender='comics-lead')

        handler({'type': 'result', 'result': 'Task complete'})

        self.assertEqual(len(sent), 1)
        sender, content = sent[0]
        self.assertEqual(
            sender, 'comics-lead',
            f"result event must be sent as 'comics-lead', got '{sender}'",
        )

    def test_thinking_events_still_use_thinking_sender(self):
        """Thinking blocks must still use 'thinking' sender regardless of agent_sender."""
        bus, sent = self._make_mock_bus()
        handler = _make_stream_event_handler(bus, 'job:test:001', agent_sender='comics-lead')

        handler({
            'type': 'assistant',
            'message': {
                'content': [{'type': 'thinking', 'thinking': 'Let me think...'}],
            },
        })

        self.assertEqual(len(sent), 1)
        sender, content = sent[0]
        self.assertEqual(
            sender, 'thinking',
            f"thinking blocks must use 'thinking' sender, got '{sender}'",
        )

    def test_tool_use_events_still_use_tool_use_sender(self):
        """Tool use blocks must still use 'tool_use' sender regardless of agent_sender."""
        bus, sent = self._make_mock_bus()
        handler = _make_stream_event_handler(bus, 'job:test:001', agent_sender='comics-lead')

        handler({'type': 'tool_use', 'name': 'Read', 'tool_use_id': 'tu-001'})

        self.assertEqual(len(sent), 1)
        sender, _ = sent[0]
        self.assertEqual(
            sender, 'tool_use',
            f"tool_use events must use 'tool_use' sender, got '{sender}'",
        )

    def test_default_agent_sender_is_agent(self):
        """Without an explicit agent_sender, the handler uses 'agent' (backward compatibility)."""
        bus, sent = self._make_mock_bus()
        handler = _make_stream_event_handler(bus, 'job:test:001')

        handler({'type': 'assistant', 'message': {'content': 'Hello'}})

        self.assertEqual(len(sent), 1)
        sender, _ = sent[0]
        self.assertEqual(
            sender, 'agent',
            f"default agent_sender must be 'agent', got '{sender}'",
        )

    def test_multiple_text_blocks_all_use_agent_sender(self):
        """Multiple text blocks in one assistant event all use the configured agent_sender."""
        bus, sent = self._make_mock_bus()
        handler = _make_stream_event_handler(bus, 'job:test:001', agent_sender='comics-lead')

        handler({
            'type': 'assistant',
            'message': {
                'content': [
                    {'type': 'text', 'text': 'First paragraph'},
                    {'type': 'text', 'text': 'Second paragraph'},
                ],
            },
        })

        self.assertEqual(len(sent), 2, f'expected 2 text messages, got {len(sent)}')
        for sender, _ in sent:
            self.assertEqual(
                sender, 'comics-lead',
                f"all text blocks must use 'comics-lead' sender, got '{sender}'",
            )


# ── Layer 3b: Dialog-reply publish sender ────────────────────────────────────
#
# The stream handler covers the `claude -p` stream path.  Gate review-
# dialog replies are produced by a separate **blocking** LLM call
# (``_generate_dialog_response``) and are written to the bus by
# ``ApprovalGate._publish_to_job_conversation(...)`` so they show up in
# the chat.  That write previously hardcoded ``sender='agent'``, which
# produced a second persona ("agent") next to the streamed text ("
# comics-lead") for the same speaker.  These tests lock in the fix:
# the dialog-reply publish uses the phase's configured lead, and no
# call site under ``actors.py`` passes the literal ``'agent'`` string
# to ``_publish_to_job_conversation``.


class TestDialogReplyPublishSender(unittest.TestCase):
    """Dialog-reply publish must use the phase lead, not hardcoded 'agent'."""

    def _actors_source(self) -> str:
        path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            'teaparty', 'cfa', 'actors.py',
        )
        with open(path) as f:
            return f.read()

    def test_no_hardcoded_agent_sender_in_publish_calls(self) -> None:
        """No ``_publish_to_job_conversation(..., 'agent', ...)`` call survives.

        Valid hardcoded senders for this helper are UI filter labels
        like ``'gate'`` and ``'proxy'``.  ``'agent'`` must never appear
        — the phase's configured lead is the correct sender for any
        text produced by the agent itself.
        """
        import re
        content = self._actors_source()
        # Match _publish_to_job_conversation(...) call arguments; look for
        # a literal 'agent' string as the sender.
        calls = re.findall(
            r'_publish_to_job_conversation\s*\(\s*[^,]+,\s*[^,]+,\s*'
            r"('[^']*'|\"[^\"]*\"|[^,\s)]+)",
            content,
        )
        for sender_arg in calls:
            self.assertNotEqual(
                sender_arg.strip(), "'agent'",
                'actors.py: no _publish_to_job_conversation call may pass '
                "the literal sender 'agent'.  Use the phase lead "
                '(ctx.phase_spec.lead) so chat attribution matches the '
                'streamed agent text.',
            )
            self.assertNotEqual(
                sender_arg.strip(), '"agent"',
                'actors.py: no _publish_to_job_conversation call may pass '
                'the literal sender "agent".',
            )

    def test_dialog_reply_publish_uses_phase_lead(self) -> None:
        """The dialog-reply publish site must derive its sender from ``ctx.phase_spec.lead``.

        This is the specific call at the end of the review-dialog turn
        that writes the agent's blocking-LLM response to the bus.
        Without the phase lead as sender, the chat shows two personas
        ("agent" and "{lead-name}") for the same speaker.
        """
        import re
        content = self._actors_source()
        # Locate the dialog-reply publish site by its explanatory
        # comment ("Publish the agent's dialog reply ... not streamed")
        # and confirm that the sender argument resolves to the phase
        # lead rather than a hardcoded string.
        block = re.search(
            r"Publish the agent's dialog reply[\s\S]{0,800}?"
            r'_publish_to_job_conversation\([^)]*\)',
            content,
        )
        self.assertIsNotNone(
            block,
            "could not locate the dialog-reply publish site in actors.py",
        )
        self.assertIn(
            'ctx.phase_spec.lead', block.group(),
            'dialog-reply publish must derive its sender from '
            '``ctx.phase_spec.lead`` so chat attribution matches the '
            'configured project or workgroup lead.',
        )


# ── Layer 4: MessageBusInputProvider sender ───────────────────────────────────

class TestMessageBusInputProviderSender(unittest.TestCase):
    """MessageBusInputProvider must use the configured sender for gate prompts."""

    def test_gate_question_uses_configured_sender(self):
        """When sender='comics-lead', the gate question is sent with that sender."""
        bus, db_path = _make_bus(self)
        conv_id = make_conversation_id(ConversationType.JOB, 'comics:test-001')
        bus.create_conversation(ConversationType.JOB, 'comics:test-001')

        provider = MessageBusInputProvider(
            bus=bus,
            conversation_id=conv_id,
            sender='comics-lead',
            poll_interval=0.01,
        )

        async def run_provider():
            # Inject the human reply only after the gate question appears in the bus
            # (deterministic ordering — no fixed sleep).
            async def inject_reply():
                for _ in range(200):
                    if any(m.sender != 'human' for m in bus.receive(conv_id)):
                        break
                    await asyncio.sleep(0.01)
                bus.send(conv_id, 'human', 'approved')

            request = InputRequest(type='approval', state='PLAN_ASSERT', bridge_text='Approve this plan?')

            task = asyncio.create_task(inject_reply())
            result = await provider(request)
            await task
            return result

        _run(run_provider())

        # Inspect all messages in the conversation
        messages = bus.receive(conv_id)
        gate_messages = [m for m in messages if m.sender != 'human']

        self.assertEqual(len(gate_messages), 1,
                         f'expected 1 gate message, got {len(gate_messages)}: {gate_messages}')
        self.assertEqual(
            gate_messages[0].sender, 'comics-lead',
            f"gate question must have sender 'comics-lead', got '{gate_messages[0].sender}'",
        )

    def test_gate_question_does_not_use_orchestrator_when_lead_configured(self):
        """When sender='comics-lead', no message must have sender 'orchestrator' (regression guard)."""
        bus, db_path = _make_bus(self)
        conv_id = make_conversation_id(ConversationType.JOB, 'comics:test-002')
        bus.create_conversation(ConversationType.JOB, 'comics:test-002')

        provider = MessageBusInputProvider(
            bus=bus,
            conversation_id=conv_id,
            sender='comics-lead',
            poll_interval=0.01,
        )

        async def run_provider():
            async def inject_reply():
                for _ in range(200):
                    if any(m.sender != 'human' for m in bus.receive(conv_id)):
                        break
                    await asyncio.sleep(0.01)
                bus.send(conv_id, 'human', 'approved')

            from teaparty.messaging.bus import InputRequest
            request = InputRequest(type='approval', state='PLAN_ASSERT', bridge_text='Approve?')
            task = asyncio.create_task(inject_reply())
            await provider(request)
            await task

        _run(run_provider())

        messages = bus.receive(conv_id)
        orchestrator_messages = [m for m in messages if m.sender == 'orchestrator']
        self.assertEqual(
            len(orchestrator_messages), 0,
            f"no message must have sender 'orchestrator' when sender='comics-lead'; "
            f"found {len(orchestrator_messages)} such messages",
        )

    def test_gate_question_uses_orchestrator_as_default_sender(self):
        """Without an explicit sender, the provider uses 'orchestrator' (backward compatibility)."""
        bus, db_path = _make_bus(self)
        conv_id = make_conversation_id(ConversationType.JOB, 'comics:test-003')
        bus.create_conversation(ConversationType.JOB, 'comics:test-003')

        provider = MessageBusInputProvider(
            bus=bus,
            conversation_id=conv_id,
            poll_interval=0.01,
            # no sender= specified
        )

        async def run_provider():
            async def inject_reply():
                for _ in range(200):
                    if any(m.sender != 'human' for m in bus.receive(conv_id)):
                        break
                    await asyncio.sleep(0.01)
                bus.send(conv_id, 'human', 'approved')

            from teaparty.messaging.bus import InputRequest
            request = InputRequest(type='approval', state='PLAN_ASSERT', bridge_text='Approve?')
            task = asyncio.create_task(inject_reply())
            await provider(request)
            await task

        _run(run_provider())

        messages = bus.receive(conv_id)
        orchestrator_msgs = [m for m in messages if m.sender == 'orchestrator']
        self.assertEqual(
            len(orchestrator_msgs), 1,
            f"default sender must be 'orchestrator', "
            f"found {len(orchestrator_msgs)} messages with that sender",
        )


# ── Layer 5: check_message_bus_request with non-orchestrator sender ───────────

class TestCheckMessageBusRequest(unittest.TestCase):
    """check_message_bus_request must find gate questions regardless of sender name."""

    def test_finds_gate_question_from_project_lead_sender(self):
        """check_message_bus_request returns the gate question when sender is a project lead name."""
        bus, db_path = _make_bus(self)
        conv_id = make_conversation_id(ConversationType.JOB, 'comics:test-004')
        bus.create_conversation(ConversationType.JOB, 'comics:test-004')

        # Simulate: stream events followed by gate question from project lead
        bus.send(conv_id, 'comics-lead', 'Here is my plan...')
        bus.send(conv_id, 'tool_use', 'Read')
        bus.send(conv_id, 'comics-lead', 'Please review this plan')  # gate question
        bus.set_awaiting_input(conv_id, True)

        result = check_message_bus_request(db_path, conv_id)

        self.assertIsNotNone(
            result,
            'check_message_bus_request must find a gate question when sender is a project lead name',
        )
        self.assertEqual(
            result['bridge_text'], 'Please review this plan',
            f"bridge_text must be the most recent non-human message, "
            f"got: {result.get('bridge_text')}",
        )

    def test_finds_gate_question_from_orchestrator_sender(self):
        """check_message_bus_request still works with 'orchestrator' sender (backward compat)."""
        bus, db_path = _make_bus(self)
        conv_id = make_conversation_id(ConversationType.JOB, 'comics:test-005')
        bus.create_conversation(ConversationType.JOB, 'comics:test-005')

        bus.send(conv_id, 'agent', 'planning output...')
        bus.send(conv_id, 'orchestrator', 'Ready for review?')
        bus.set_awaiting_input(conv_id, True)

        result = check_message_bus_request(db_path, conv_id)

        self.assertIsNotNone(result,
                             "check_message_bus_request must work with 'orchestrator' sender")
        self.assertEqual(result['bridge_text'], 'Ready for review?')

    def test_returns_none_when_awaiting_input_false(self):
        """check_message_bus_request returns None when awaiting_input is not set."""
        bus, db_path = _make_bus(self)
        conv_id = make_conversation_id(ConversationType.JOB, 'comics:test-006')
        bus.create_conversation(ConversationType.JOB, 'comics:test-006')

        bus.send(conv_id, 'comics-lead', 'Some output')
        # awaiting_input NOT set to True

        result = check_message_bus_request(db_path, conv_id)

        self.assertIsNone(
            result,
            'check_message_bus_request must return None when awaiting_input is not set; '
            f'got: {result}',
        )

    def test_does_not_return_human_message_as_gate_question(self):
        """check_message_bus_request returns None when only human messages are present."""
        bus, db_path = _make_bus(self)
        conv_id = make_conversation_id(ConversationType.JOB, 'comics:test-007')
        bus.create_conversation(ConversationType.JOB, 'comics:test-007')

        # Only a human message in the conversation; then awaiting_input (unusual but tested)
        bus.send(conv_id, 'human', 'Start the job')
        bus.set_awaiting_input(conv_id, True)

        result = check_message_bus_request(db_path, conv_id)

        # No non-human message available — must return None, not the human message.
        self.assertIsNone(
            result,
            'check_message_bus_request must return None when the only message is from human; '
            f'got: {result}',
        )

    def test_gate_question_is_most_recent_non_human_message(self):
        """check_message_bus_request returns the MOST RECENT non-human message, not the first."""
        bus, db_path = _make_bus(self)
        conv_id = make_conversation_id(ConversationType.JOB, 'comics:test-008')
        bus.create_conversation(ConversationType.JOB, 'comics:test-008')

        bus.send(conv_id, 'comics-lead', 'First output')
        bus.send(conv_id, 'tool_use', 'Read')
        bus.send(conv_id, 'comics-lead', 'Gate question: approve this?')
        bus.set_awaiting_input(conv_id, True)

        result = check_message_bus_request(db_path, conv_id)

        self.assertIsNotNone(result)
        self.assertEqual(
            result['bridge_text'], 'Gate question: approve this?',
            f"must return the most recent non-human message, "
            f"got: '{result.get('bridge_text')}'",
        )


# ── Layer 6: Resume path sender attribution ───────────────────────────────────

class TestResumeSenderAttribution(unittest.TestCase):
    """_resolve_project_lead_sender() must return the project lead for resume-path attribution.

    This function is the extracted helper used by Session.resume_from_disk() to
    resolve the sender for MessageBusInputProvider — the code path responsible for
    AC3 on resumed sessions.
    """

    def test_returns_project_lead_when_project_yaml_has_lead(self):
        """Returns the project lead name when project.yaml defines one."""
        tmp = _make_tmp(self)
        _make_project_yaml(tmp, lead='comics-lead')

        sender = _resolve_project_lead_sender(tmp)

        self.assertEqual(
            sender, 'comics-lead',
            f"resume sender must be 'comics-lead' when project.yaml defines that lead; "
            f"got '{sender}'",
        )

    def test_returns_orchestrator_when_no_project_yaml(self):
        """Falls back to 'orchestrator' when project.yaml is absent."""
        tmp = _make_tmp(self)
        # No project.yaml created

        sender = _resolve_project_lead_sender(tmp)

        self.assertEqual(
            sender, 'orchestrator',
            f"resume sender must fall back to 'orchestrator' when project.yaml is absent; "
            f"got '{sender}'",
        )

    def test_returns_orchestrator_when_lead_field_absent(self):
        """Falls back to 'orchestrator' when project.yaml has no lead field."""
        tmp = _make_tmp(self)
        _make_project_yaml(tmp, lead='')  # project.yaml exists but no lead key

        sender = _resolve_project_lead_sender(tmp)

        self.assertEqual(
            sender, 'orchestrator',
            f"resume sender must fall back to 'orchestrator' when project.yaml has no 'lead'; "
            f"got '{sender}'",
        )

    def test_returns_orchestrator_when_project_dir_missing(self):
        """Falls back to 'orchestrator' when the project directory does not exist."""
        nonexistent = '/tmp/teaparty-test-nonexistent-project-dir-408'

        sender = _resolve_project_lead_sender(nonexistent)

        self.assertEqual(
            sender, 'orchestrator',
            f"resume sender must fall back to 'orchestrator' when project dir is missing; "
            f"got '{sender}'",
        )

    def test_different_projects_resolve_independently(self):
        """Two different project dirs resolve to their own leads (no cross-contamination)."""
        tmp_a = _make_tmp(self)
        tmp_b = _make_tmp(self)
        _make_project_yaml(tmp_a, lead='comics-lead')
        _make_project_yaml(tmp_b, lead='scifi-lead')

        sender_a = _resolve_project_lead_sender(tmp_a)
        sender_b = _resolve_project_lead_sender(tmp_b)

        self.assertEqual(sender_a, 'comics-lead', f"project A must resolve to 'comics-lead'; got '{sender_a}'")
        self.assertEqual(sender_b, 'scifi-lead', f"project B must resolve to 'scifi-lead'; got '{sender_b}'")
        self.assertNotEqual(sender_a, sender_b, 'two different projects must not share the same sender')


class TestAgentDefinitionResolution(unittest.TestCase):
    """resolve_agent_definition uses project-first, org-fallback lookup order.

    Covers AC2: lead agent tools/skills/prompt active.

    The user-specified lookup order:
      1. {project_dir}/.teaparty/project/agents/{name}/agent.md
      2. {poc_root}/.teaparty/management/agents/{name}/agent.md  (org fallback)
    """

    def _write_agent_md(self, base_dir: str, scope: str, agent_name: str) -> str:
        """Write a minimal agent.md and return its path."""
        agent_dir = os.path.join(base_dir, scope, 'agents', agent_name)
        os.makedirs(agent_dir, exist_ok=True)
        path = os.path.join(agent_dir, 'agent.md')
        with open(path, 'w') as f:
            f.write(f'# {agent_name}\n')
        return path

    def test_finds_agent_in_project_teaparty_directory(self):
        """resolve_agent_definition finds agent.md under {project}/.teaparty/project/agents/."""
        project_home = _make_tmp(self)
        expected = self._write_agent_md(project_home, 'project', 'comics-lead')

        result = resolve_agent_definition(
            'comics-lead',
            'project',
            teaparty_home=project_home,
        )

        self.assertEqual(
            result, expected,
            f"must find agent.md in project teaparty_home; got '{result}'",
        )

    def test_falls_back_to_org_management_catalog_when_not_in_project(self):
        """Falls back to org management catalog when agent not found in project home."""
        project_home = _make_tmp(self)  # no agent here
        org_home = _make_tmp(self)
        expected = self._write_agent_md(org_home, 'management', 'comics-lead')

        result = resolve_agent_definition(
            'comics-lead',
            'project',
            teaparty_home=project_home,
            org_home=org_home,
        )

        self.assertEqual(
            result, expected,
            f"must fall back to org management catalog; got '{result}'",
        )

    def test_project_scope_wins_over_org_management(self):
        """Project-scope definition wins when both project and org have the agent."""
        project_home = _make_tmp(self)
        org_home = _make_tmp(self)
        expected = self._write_agent_md(project_home, 'project', 'comics-lead')
        self._write_agent_md(org_home, 'management', 'comics-lead')

        result = resolve_agent_definition(
            'comics-lead',
            'project',
            teaparty_home=project_home,
            org_home=org_home,
        )

        self.assertEqual(
            result, expected,
            f"project-scope definition must win over org management; got '{result}'",
        )

    def test_raises_when_agent_not_found_anywhere(self):
        """FileNotFoundError raised when agent not in project or org catalog."""
        project_home = _make_tmp(self)
        org_home = _make_tmp(self)

        with self.assertRaises(FileNotFoundError):
            resolve_agent_definition(
                'nonexistent-lead',
                'project',
                teaparty_home=project_home,
                org_home=org_home,
            )

    def test_raises_without_org_home_when_not_in_project(self):
        """FileNotFoundError raised when org_home is absent and agent not in project home."""
        project_home = _make_tmp(self)

        with self.assertRaises(FileNotFoundError):
            resolve_agent_definition(
                'comics-lead',
                'project',
                teaparty_home=project_home,
            )


class TestAgentRunnerLaunchArgs(unittest.TestCase):
    """AgentRunner.run() must pass the correct teaparty_home and org_home to launch().

    This test guards the actors.py callsite — the root cause of the original AC2 bug
    (teaparty_home=ctx.poc_root caused the wrong directory to be searched).

    If actors.py were reverted to teaparty_home=ctx.poc_root (or org_home were dropped),
    this test would fail with an assertion error on the captured launch kwargs.
    """

    def _make_context(self, project_workdir: str, poc_root: str) -> 'ActorContext':
        from teaparty.cfa.actors import ActorContext
        from teaparty.cfa.phase_config import PhaseSpec
        from teaparty.messaging.bus import EventBus

        phase_spec = PhaseSpec(
            name='planning',
            agent_file='uber',
            lead='comics-lead',
            permission_mode='default',
            stream_file='planning.jsonl',
            artifact=None,
            approval_state='PLAN_ASSERT',
        )
        return ActorContext(
            state='PLANNING_RUN',
            phase='planning',
            task='Write a plan.',
            infra_dir=project_workdir,
            project_workdir=project_workdir,
            session_worktree=project_workdir,
            stream_file='planning.jsonl',
            phase_spec=phase_spec,
            poc_root=poc_root,
            event_bus=EventBus(),
        )

    def test_launch_receives_project_teaparty_home(self):
        """launch() must receive teaparty_home={project_workdir}/.teaparty, not ctx.poc_root."""
        from teaparty.cfa.actors import AgentRunner
        from teaparty.runners.claude import ClaudeResult

        project_workdir = _make_tmp(self)
        poc_root = _make_tmp(self)
        _install_jail_hook(project_workdir)
        ctx = self._make_context(project_workdir, poc_root)

        captured = {}

        async def fake_launch(**kwargs):
            captured.update(kwargs)
            return ClaudeResult(exit_code=1)

        with patch('teaparty.runners.launcher.launch', side_effect=fake_launch):
            _run(AgentRunner().run(ctx))

        expected_teaparty_home = os.path.join(project_workdir, '.teaparty')
        self.assertEqual(
            captured.get('teaparty_home'), expected_teaparty_home,
            f"launch must receive teaparty_home='{expected_teaparty_home}' "
            f"(project's own .teaparty/), not '{captured.get('teaparty_home')}'; "
            f"reverting actors.py to teaparty_home=ctx.poc_root breaks AC2",
        )

    def test_launch_receives_org_home_as_fallback(self):
        """launch() must receive org_home={poc_root}/.teaparty for the org catalog fallback."""
        from teaparty.cfa.actors import AgentRunner
        from teaparty.runners.claude import ClaudeResult

        project_workdir = _make_tmp(self)
        poc_root = _make_tmp(self)
        _install_jail_hook(project_workdir)
        ctx = self._make_context(project_workdir, poc_root)

        captured = {}

        async def fake_launch(**kwargs):
            captured.update(kwargs)
            return ClaudeResult(exit_code=1)

        with patch('teaparty.runners.launcher.launch', side_effect=fake_launch):
            _run(AgentRunner().run(ctx))

        expected_org_home = os.path.join(poc_root, '.teaparty')
        self.assertEqual(
            captured.get('org_home'), expected_org_home,
            f"launch must receive org_home='{expected_org_home}' "
            f"(org-level management catalog); got '{captured.get('org_home')}'",
        )

    def test_launch_teaparty_home_differs_from_poc_root(self):
        """teaparty_home must not be ctx.poc_root — that was the original bug."""
        from teaparty.cfa.actors import AgentRunner
        from teaparty.runners.claude import ClaudeResult

        project_workdir = _make_tmp(self)
        poc_root = _make_tmp(self)
        _install_jail_hook(project_workdir)
        ctx = self._make_context(project_workdir, poc_root)

        captured = {}

        async def fake_launch(**kwargs):
            captured.update(kwargs)
            return ClaudeResult(exit_code=1)

        with patch('teaparty.runners.launcher.launch', side_effect=fake_launch):
            _run(AgentRunner().run(ctx))

        self.assertNotEqual(
            captured.get('teaparty_home'), poc_root,
            f"teaparty_home must NOT be ctx.poc_root ('{poc_root}') — "
            f"that was the original bug; agent definitions are in "
            f"{{project_workdir}}/.teaparty/, not poc_root directly",
        )


if __name__ == '__main__':
    unittest.main()
