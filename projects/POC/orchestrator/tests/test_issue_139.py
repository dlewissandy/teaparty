#!/usr/bin/env python3
"""Tests for issue #139: Proxy agent must be an actual agent, not a statistical heuristic.

The proxy must be a Claude agent that generates full text responses — the same
kind of response a human would give.  It reads the artifact under review using
tools (file read, list files), then produces text predicting what the human
would say.  That text has a confidence score.

Flow:
  1. Proxy agent is asked the canonical gate question
  2. Agent uses tools to read the artifact, reasons, generates text + confidence
  3. If confidence >= threshold → agent's text IS the answer (skip human)
  4. If confidence < threshold → same question goes to human, their text IS the answer
  5. Both predicted text and actual text feed into learning
  6. Final text (from either source) is classified by _classify_review into a CfA action

The proxy does NOT return categorical approve/escalate.  It returns TEXT.
Classification into actions happens downstream, identically for both sources.
"""
import asyncio
import inspect
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent.parent))

from projects.POC.orchestrator.actors import (
    ActorContext,
    ActorResult,
    ApprovalGate,
)
from projects.POC.orchestrator.events import EventBus
from projects.POC.orchestrator.phase_config import PhaseSpec


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_event_bus() -> EventBus:
    bus = MagicMock(spec=EventBus)
    bus.publish = AsyncMock()
    return bus


def _make_phase_spec(artifact: str | None = 'INTENT.md') -> PhaseSpec:
    return PhaseSpec(
        name='intent',
        agent_file='agents/intent-team.json',
        lead='intent-lead',
        permission_mode='acceptEdits',
        stream_file='.intent-stream.jsonl',
        artifact=artifact,
        approval_state='INTENT_ASSERT',
        settings_overlay={},
    )


def _make_ctx(
    state: str = 'INTENT_ASSERT',
    session_worktree: str = '/tmp/worktree',
    infra_dir: str = '/tmp/infra',
) -> ActorContext:
    return ActorContext(
        state=state,
        phase='intent',
        task='Write a blog post about AI',
        infra_dir=infra_dir,
        project_workdir='/tmp/project',
        session_worktree=session_worktree,
        stream_file='.intent-stream.jsonl',
        phase_spec=_make_phase_spec(),
        poc_root='/tmp/poc',
        event_bus=_make_event_bus(),
        session_id='test-session',
    )


def _make_gate(tmpdir: str, human_response: str = 'approve') -> ApprovalGate:
    async def _input_provider(req):
        return human_response

    return ApprovalGate(
        proxy_model_path=os.path.join(tmpdir, '.proxy.json'),
        input_provider=_input_provider,
        poc_root=tmpdir,
    )


def _make_warm_model_json(state: str = 'INTENT_ASSERT', task: str = 'default') -> dict:
    """Proxy model with enough history to pass cold start + staleness."""
    from datetime import date
    key = f'{state}|{task}'
    return {
        'entries': {
            key: {
                'state': state,
                'task_type': task,
                'approve_count': 10,
                'correct_count': 0,
                'reject_count': 0,
                'total_count': 10,
                'last_updated': date.today().isoformat(),
                'differentials': [],
                'ema_approval_rate': 0.95,
                'artifact_lengths': [],
                'question_patterns': [],
                'prediction_correct_count': 0,
                'prediction_total_count': 0,
            },
        },
        'global_threshold': 0.8,
        'generative_threshold': 0.95,
    }


def _run(coro):
    return asyncio.run(coro)


# ── _run_proxy_agent exists and is an async agent ────────────────────────────

class TestRunProxyAgentExists(unittest.TestCase):
    """ApprovalGate must have a _run_proxy_agent method that invokes a Claude agent."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_method_exists(self):
        """ApprovalGate must have a _run_proxy_agent method."""
        gate = _make_gate(self.tmpdir)
        self.assertTrue(hasattr(gate, '_run_proxy_agent'),
                        "ApprovalGate must have a _run_proxy_agent method")

    def test_method_is_async(self):
        """_run_proxy_agent must be async (it invokes Claude CLI)."""
        gate = _make_gate(self.tmpdir)
        method = getattr(gate, '_run_proxy_agent', None)
        self.assertTrue(inspect.iscoroutinefunction(method),
                        "_run_proxy_agent must be a coroutine (async def)")

    def test_returns_text_and_confidence(self):
        """_run_proxy_agent must return (text, confidence) — not a categorical decision."""
        gate = _make_gate(self.tmpdir)
        artifact_path = os.path.join(self.tmpdir, 'INTENT.md')
        Path(artifact_path).write_text('# Intent\nBuild a blog platform')

        # Mock at the subprocess level — the agent invokes Claude CLI
        with patch('subprocess.run') as mock_subprocess:
            mock_subprocess.return_value = MagicMock(
                returncode=0,
                stdout='Yes, this captures the idea well. Approved.',
            )
            result = _run(gate._run_proxy_agent(
                state='INTENT_ASSERT',
                artifact_path=artifact_path,
                gate_question='Do you recognize this as your idea?',
                session_worktree=self.tmpdir,
            ))

        # Must return a tuple of (text, confidence)
        self.assertIsInstance(result, tuple,
                             "_run_proxy_agent must return a (text, confidence) tuple")
        self.assertEqual(len(result), 2)
        text, confidence = result
        self.assertIsInstance(text, str, "First element must be text (str)")
        self.assertIsInstance(confidence, (int, float),
                             "Second element must be confidence (number)")


# ── Proxy agent generates text, not categorical decisions ────────────────────

class TestProxyAgentGeneratesText(unittest.TestCase):
    """The proxy agent generates full text responses, not approve/escalate."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        model_path = os.path.join(self.tmpdir, '.proxy.json')
        with open(model_path, 'w') as f:
            json.dump(_make_warm_model_json(), f)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_agent_text_used_when_confident(self):
        """When confidence >= threshold, the agent's text is used as the answer
        and classified by _classify_review — the human is never asked."""
        input_calls = []

        async def _input_provider(req):
            input_calls.append(req)
            return 'approve'

        gate = ApprovalGate(
            proxy_model_path=os.path.join(self.tmpdir, '.proxy.json'),
            input_provider=_input_provider,
            poc_root=self.tmpdir,
        )
        ctx = _make_ctx(session_worktree=self.tmpdir, infra_dir=self.tmpdir)
        artifact_path = os.path.join(self.tmpdir, 'INTENT.md')
        Path(artifact_path).write_text('# Intent\nBuild something great')
        ctx.data = {'artifact_path': artifact_path}

        agent_text = 'Yes, this captures my idea completely and accurately.'

        with patch('random.random', return_value=0.99), \
             patch.object(gate, '_run_proxy_agent', new_callable=AsyncMock) as mock_agent:
            # Agent returns high-confidence text
            mock_agent.return_value = (agent_text, 0.95)

            with patch.object(gate, '_classify_review',
                              return_value=('approve', '')) as mock_classify, \
                 patch.object(gate, '_proxy_record'):
                result = _run(gate.run(ctx))

            # The agent's text must be classified (not the human's)
            mock_classify.assert_called()
            classified_text = mock_classify.call_args[0][1]  # second positional arg
            self.assertEqual(classified_text, agent_text,
                             "The agent's text must be what gets classified")

        # Human must NOT have been asked
        self.assertEqual(len(input_calls), 0,
                         "Human must not be asked when proxy is confident")

    def test_human_asked_when_not_confident(self):
        """When confidence < threshold, the same question goes to the human."""
        input_calls = []

        async def _input_provider(req):
            input_calls.append(req)
            return 'Looks good, approved.'

        gate = ApprovalGate(
            proxy_model_path=os.path.join(self.tmpdir, '.proxy.json'),
            input_provider=_input_provider,
            poc_root=self.tmpdir,
        )
        ctx = _make_ctx(session_worktree=self.tmpdir, infra_dir=self.tmpdir)
        artifact_path = os.path.join(self.tmpdir, 'INTENT.md')
        Path(artifact_path).write_text('# Intent\nBuild something')
        ctx.data = {'artifact_path': artifact_path}

        with patch('random.random', return_value=0.99), \
             patch.object(gate, '_run_proxy_agent', new_callable=AsyncMock) as mock_agent:
            # Agent returns low-confidence text
            mock_agent.return_value = ("I'm not sure about this one.", 0.3)

            with patch.object(gate, '_classify_review',
                              return_value=('approve', '')) as mock_classify, \
                 patch.object(gate, '_proxy_record'):
                result = _run(gate.run(ctx))

        # Human MUST have been asked
        self.assertGreaterEqual(len(input_calls), 1,
                                "Human must be asked when proxy confidence is low")

    def test_both_predictions_feed_into_learning(self):
        """Both the agent's predicted text and the actual answer must be recorded."""
        async def _input_provider(req):
            return 'Actually, the second criterion needs rewording.'

        gate = ApprovalGate(
            proxy_model_path=os.path.join(self.tmpdir, '.proxy.json'),
            input_provider=_input_provider,
            poc_root=self.tmpdir,
        )
        ctx = _make_ctx(session_worktree=self.tmpdir, infra_dir=self.tmpdir)
        artifact_path = os.path.join(self.tmpdir, 'INTENT.md')
        Path(artifact_path).write_text('# Intent\nBuild something')
        ctx.data = {'artifact_path': artifact_path}

        agent_prediction = 'Yes, this looks correct.'

        with patch('random.random', return_value=0.99), \
             patch.object(gate, '_run_proxy_agent', new_callable=AsyncMock) as mock_agent:
            mock_agent.return_value = (agent_prediction, 0.3)  # low confidence → human asked

            with patch.object(gate, '_classify_review',
                              return_value=('correct', 'Reword criterion 2')), \
                 patch.object(gate, '_proxy_record') as mock_record:
                _run(gate.run(ctx))

        # _proxy_record must receive both the prediction and the actual response
        mock_record.assert_called()
        call_kwargs = mock_record.call_args
        all_args = str(call_kwargs)
        # The predicted text from the agent must be passed for learning
        self.assertIn(agent_prediction, all_args,
                      "Agent's predicted text must be passed to learning")


# ── Statistical pre-filters still gate the agent ─────────────────────────────

class TestStatisticalPreFilters(unittest.TestCase):
    """Cold start, staleness, low confidence still escalate without invoking the agent."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _run_gate_with_model(self, model_json: dict, human_response: str = 'approve'):
        """Set up a gate with a given model and run it, tracking agent calls."""
        model_path = os.path.join(self.tmpdir, '.proxy.json')
        with open(model_path, 'w') as f:
            json.dump(model_json, f)

        async def _input_provider(req):
            return human_response

        gate = ApprovalGate(
            proxy_model_path=model_path,
            input_provider=_input_provider,
            poc_root=self.tmpdir,
        )
        ctx = _make_ctx(session_worktree=self.tmpdir, infra_dir=self.tmpdir)
        artifact_path = os.path.join(self.tmpdir, 'INTENT.md')
        Path(artifact_path).write_text('# Intent\nBuild something')
        ctx.data = {'artifact_path': artifact_path}

        with patch.object(gate, '_run_proxy_agent', new_callable=AsyncMock) as mock_agent, \
             patch.object(gate, '_classify_review', return_value=('approve', '')), \
             patch.object(gate, '_proxy_record'):
            _run(gate.run(ctx))

        return mock_agent

    def test_cold_start_skips_agent(self):
        """On cold start (no history), go straight to human — no agent invocation."""
        empty_model = {'entries': {}, 'global_threshold': 0.8, 'generative_threshold': 0.95}
        mock_agent = self._run_gate_with_model(empty_model)
        mock_agent.assert_not_called()

    def test_stale_model_skips_agent(self):
        """When model is stale (>7 days old), go straight to human."""
        model = _make_warm_model_json()
        key = 'INTENT_ASSERT|default'
        model['entries'][key]['last_updated'] = '2020-01-01'
        mock_agent = self._run_gate_with_model(model)
        mock_agent.assert_not_called()

    def test_low_confidence_skips_agent(self):
        """When statistical confidence is below threshold, go straight to human."""
        model = _make_warm_model_json()
        key = 'INTENT_ASSERT|default'
        model['entries'][key]['approve_count'] = 2
        model['entries'][key]['correct_count'] = 8
        model['entries'][key]['ema_approval_rate'] = 0.2
        mock_agent = self._run_gate_with_model(model)
        mock_agent.assert_not_called()


# ── Agent receives the right inputs ──────────────────────────────────────────

class TestProxyAgentInputs(unittest.TestCase):
    """The proxy agent must receive artifact path, gate question, and context."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        model_path = os.path.join(self.tmpdir, '.proxy.json')
        with open(model_path, 'w') as f:
            json.dump(_make_warm_model_json(), f)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_agent_receives_artifact_path(self):
        """The proxy agent must be told which artifact to review."""
        gate = _make_gate(self.tmpdir)
        ctx = _make_ctx(session_worktree=self.tmpdir, infra_dir=self.tmpdir)
        artifact_path = os.path.join(self.tmpdir, 'INTENT.md')
        Path(artifact_path).write_text('# Intent\nDo something useful')
        ctx.data = {'artifact_path': artifact_path}

        with patch('random.random', return_value=0.99), \
             patch.object(gate, '_run_proxy_agent', new_callable=AsyncMock) as mock_agent, \
             patch.object(gate, '_classify_review', return_value=('approve', '')), \
             patch.object(gate, '_proxy_record'):
            mock_agent.return_value = ('Looks good.', 0.95)
            _run(gate.run(ctx))

        mock_agent.assert_called_once()
        call_str = str(mock_agent.call_args)
        self.assertIn(artifact_path, call_str,
                      "Proxy agent must receive the artifact path")

    def test_agent_receives_gate_question(self):
        """The proxy agent must receive the canonical gate question."""
        gate = _make_gate(self.tmpdir)
        ctx = _make_ctx(session_worktree=self.tmpdir, infra_dir=self.tmpdir)
        artifact_path = os.path.join(self.tmpdir, 'INTENT.md')
        Path(artifact_path).write_text('# Intent\nBuild it')
        ctx.data = {'artifact_path': artifact_path}

        with patch('random.random', return_value=0.99), \
             patch.object(gate, '_run_proxy_agent', new_callable=AsyncMock) as mock_agent, \
             patch.object(gate, '_classify_review', return_value=('approve', '')), \
             patch.object(gate, '_proxy_record'):
            mock_agent.return_value = ('Yes, approved.', 0.95)
            _run(gate.run(ctx))

        call_str = str(mock_agent.call_args)
        self.assertIn('Do you recognize this as your idea', call_str,
                      "Proxy agent must receive the canonical gate question")

    def test_agent_receives_session_worktree(self):
        """The proxy agent must know the session worktree so it can read files."""
        gate = _make_gate(self.tmpdir)
        ctx = _make_ctx(session_worktree=self.tmpdir, infra_dir=self.tmpdir)
        artifact_path = os.path.join(self.tmpdir, 'INTENT.md')
        Path(artifact_path).write_text('# Intent')
        ctx.data = {'artifact_path': artifact_path}

        with patch('random.random', return_value=0.99), \
             patch.object(gate, '_run_proxy_agent', new_callable=AsyncMock) as mock_agent, \
             patch.object(gate, '_classify_review', return_value=('approve', '')), \
             patch.object(gate, '_proxy_record'):
            mock_agent.return_value = ('Approved.', 0.95)
            _run(gate.run(ctx))

        call_str = str(mock_agent.call_args)
        self.assertIn(self.tmpdir, call_str,
                      "Proxy agent must receive the session worktree path")


class TestProxyAgentReceivesLearningContext(unittest.TestCase):
    """The proxy agent must receive learned patterns and past interactions."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        model_path = os.path.join(self.tmpdir, '.proxy.json')
        with open(model_path, 'w') as f:
            json.dump(_make_warm_model_json(), f)
        # Write learned patterns — use patterns that won't conflict with
        # the artifact content (tier 1 pattern matching checks for keyword
        # coverage, and will escalate if the artifact doesn't address them).
        patterns_path = os.path.join(self.tmpdir, 'proxy-patterns.md')
        Path(patterns_path).write_text(
            '## INTENT_ASSERT\n'
            '- Human prefers concise intent documents\n'
        )
        # Write interaction history
        log_path = os.path.join(self.tmpdir, '.proxy-interactions.jsonl')
        entries = [
            {'state': 'INTENT_ASSERT', 'project': 'default',
             'outcome': 'approve', 'delta': '', 'timestamp': '2026-03-14T12:00:00Z'},
            {'state': 'INTENT_ASSERT', 'project': 'default',
             'outcome': 'correct', 'delta': 'Intent was too verbose',
             'timestamp': '2026-03-13T12:00:00Z'},
        ]
        with open(log_path, 'w') as f:
            for e in entries:
                f.write(json.dumps(e) + '\n')

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_agent_receives_learned_patterns(self):
        """The proxy agent must be given the learned behavioral patterns."""
        gate = _make_gate(self.tmpdir)
        ctx = _make_ctx(session_worktree=self.tmpdir, infra_dir=self.tmpdir)
        artifact_path = os.path.join(self.tmpdir, 'INTENT.md')
        # Artifact must contain enough keywords to pass tier 1 pattern matching
        Path(artifact_path).write_text(
            '# Intent\nBuild a concise intent document for the platform')
        ctx.data = {'artifact_path': artifact_path}

        with patch('random.random', return_value=0.99), \
             patch.object(gate, '_run_proxy_agent', new_callable=AsyncMock) as mock_agent, \
             patch.object(gate, '_classify_review', return_value=('approve', '')), \
             patch.object(gate, '_proxy_record'):
            mock_agent.return_value = ('Approved.', 0.95)
            _run(gate.run(ctx))

        mock_agent.assert_called_once()
        call_kwargs = mock_agent.call_args
        # learned_patterns must be passed as a keyword arg
        all_args = str(call_kwargs)
        self.assertIn('concise intent', all_args,
                      "Proxy agent must receive learned behavioral patterns")

    def test_agent_receives_similar_interactions(self):
        """The proxy agent must be given past interaction history."""
        gate = _make_gate(self.tmpdir)
        ctx = _make_ctx(session_worktree=self.tmpdir, infra_dir=self.tmpdir)
        artifact_path = os.path.join(self.tmpdir, 'INTENT.md')
        Path(artifact_path).write_text(
            '# Intent\nBuild a concise intent document for the platform')
        ctx.data = {'artifact_path': artifact_path}

        with patch('random.random', return_value=0.99), \
             patch.object(gate, '_run_proxy_agent', new_callable=AsyncMock) as mock_agent, \
             patch.object(gate, '_classify_review', return_value=('approve', '')), \
             patch.object(gate, '_proxy_record'):
            mock_agent.return_value = ('Approved.', 0.95)
            _run(gate.run(ctx))

        mock_agent.assert_called_once()
        call_kwargs = mock_agent.call_args
        # similar_interactions must be passed
        all_args = str(call_kwargs)
        self.assertTrue(
            'similar_interactions' in all_args or 'too verbose' in all_args,
            "Proxy agent must receive past interaction history",
        )


class TestProxyAgentDialog(unittest.TestCase):
    """The proxy agent must be able to ask questions and have dialog."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        model_path = os.path.join(self.tmpdir, '.proxy.json')
        with open(model_path, 'w') as f:
            json.dump(_make_warm_model_json(), f)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_proxy_agent_question_triggers_dialog(self):
        """When the proxy agent asks a question (classifies as dialog),
        the question goes to the requester and the proxy gets another turn."""
        input_calls = []

        async def _input_provider(req):
            input_calls.append(req)
            return 'approve'

        gate = ApprovalGate(
            proxy_model_path=os.path.join(self.tmpdir, '.proxy.json'),
            input_provider=_input_provider,
            poc_root=self.tmpdir,
        )
        ctx = _make_ctx(session_worktree=self.tmpdir, infra_dir=self.tmpdir)
        artifact_path = os.path.join(self.tmpdir, 'INTENT.md')
        Path(artifact_path).write_text('# Intent\nBuild a platform')
        ctx.data = {'artifact_path': artifact_path}

        # First call: agent asks a question (dialog).
        # Second call: agent approves after getting the answer.
        agent_calls = [
            ('Why did you choose a monolith over microservices?', 0.90),
            ('OK, that makes sense. Approved.', 0.95),
        ]
        call_count = [0]

        async def mock_run_proxy_agent(**kwargs):
            idx = call_count[0]
            call_count[0] += 1
            return agent_calls[idx]

        # Classification: first response is dialog, second is approve
        classify_returns = iter([
            ('dialog', ''),       # proxy asks a question
            ('approve', ''),      # proxy approves after dialog
        ])

        with patch('random.random', return_value=0.99), \
             patch.object(gate, '_run_proxy_agent', side_effect=mock_run_proxy_agent) as mock_agent, \
             patch.object(gate, '_classify_review', side_effect=lambda *a, **kw: next(classify_returns)), \
             patch.object(gate, '_generate_dialog_response', return_value='We chose monolith for simplicity.') as mock_dialog, \
             patch.object(gate, '_proxy_record'):
            result = _run(gate.run(ctx))

        # The proxy agent should have been called twice: initial + after dialog
        self.assertEqual(call_count[0], 2,
                         "Proxy agent must get a second turn after asking a question")
        # The dialog response generator should have been called to answer the question
        mock_dialog.assert_called_once()
        # Human should NOT have been asked (proxy handled everything)
        self.assertEqual(len(input_calls), 0,
                         "Human must not be asked when proxy resolves via dialog")
        # Final action should be approve
        self.assertEqual(result.action, 'approve')

    def test_proxy_agent_loses_confidence_during_dialog_escalates(self):
        """If the proxy agent's confidence drops during dialog, escalate to human."""
        input_calls = []

        async def _input_provider(req):
            input_calls.append(req)
            return 'Yes, approved.'

        gate = ApprovalGate(
            proxy_model_path=os.path.join(self.tmpdir, '.proxy.json'),
            input_provider=_input_provider,
            poc_root=self.tmpdir,
        )
        ctx = _make_ctx(session_worktree=self.tmpdir, infra_dir=self.tmpdir)
        artifact_path = os.path.join(self.tmpdir, 'INTENT.md')
        Path(artifact_path).write_text('# Intent\nBuild a platform')
        ctx.data = {'artifact_path': artifact_path}

        # First call: agent asks a question (dialog). Second call: low confidence.
        agent_calls = [
            ('What about the rollback plan?', 0.90),
            ("I'm not sure what to think about this.", 0.3),  # confidence drops
        ]
        call_count = [0]

        async def mock_run_proxy_agent(**kwargs):
            idx = call_count[0]
            call_count[0] += 1
            return agent_calls[idx]

        classify_returns = iter([
            ('dialog', ''),       # proxy asks a question
            ('approve', ''),      # human approves (after escalation)
        ])

        with patch('random.random', return_value=0.99), \
             patch.object(gate, '_run_proxy_agent', side_effect=mock_run_proxy_agent), \
             patch.object(gate, '_classify_review', side_effect=lambda *a, **kw: next(classify_returns)), \
             patch.object(gate, '_generate_dialog_response', return_value='No rollback plan yet.'), \
             patch.object(gate, '_proxy_record'):
            result = _run(gate.run(ctx))

        # Human MUST have been asked because proxy lost confidence
        self.assertGreaterEqual(len(input_calls), 1,
                                "Human must be asked when proxy loses confidence during dialog")

    def test_proxy_dialog_history_passed_to_second_turn(self):
        """On the second turn, the proxy agent must receive the dialog history."""
        gate = ApprovalGate(
            proxy_model_path=os.path.join(self.tmpdir, '.proxy.json'),
            input_provider=AsyncMock(return_value='approve'),
            poc_root=self.tmpdir,
        )
        ctx = _make_ctx(session_worktree=self.tmpdir, infra_dir=self.tmpdir)
        artifact_path = os.path.join(self.tmpdir, 'INTENT.md')
        Path(artifact_path).write_text('# Intent\nBuild a platform')
        ctx.data = {'artifact_path': artifact_path}

        call_kwargs_list = []

        async def mock_run_proxy_agent(**kwargs):
            call_kwargs_list.append(kwargs)
            if len(call_kwargs_list) == 1:
                return ('What testing strategy?', 0.90)
            return ('Good, approved.', 0.95)

        classify_returns = iter([
            ('dialog', ''),
            ('approve', ''),
        ])

        with patch('random.random', return_value=0.99), \
             patch.object(gate, '_run_proxy_agent', side_effect=mock_run_proxy_agent), \
             patch.object(gate, '_classify_review', side_effect=lambda *a, **kw: next(classify_returns)), \
             patch.object(gate, '_generate_dialog_response', return_value='Unit tests plus integration.'), \
             patch.object(gate, '_proxy_record'):
            _run(gate.run(ctx))

        # Second call must include dialog_history
        self.assertEqual(len(call_kwargs_list), 2)
        second_call = call_kwargs_list[1]
        dialog_hist = second_call.get('dialog_history', '')
        self.assertIn('What testing strategy', dialog_hist,
                      "Second proxy turn must include the proxy's question in dialog_history")
        self.assertIn('Unit tests plus integration', dialog_hist,
                      "Second proxy turn must include the requester's reply in dialog_history")


class TestParseProxyAgentOutput(unittest.TestCase):
    """_parse_proxy_agent_output must handle various confidence formats."""

    def test_standard_format(self):
        output = 'Yes, this looks good.\nCONFIDENCE: 0.85'
        text, conf = ApprovalGate._parse_proxy_agent_output(output)
        self.assertEqual(text, 'Yes, this looks good.')
        self.assertAlmostEqual(conf, 0.85)

    def test_confidence_on_last_line_with_whitespace(self):
        output = 'Approved.\n\nCONFIDENCE:  0.92  \n'
        text, conf = ApprovalGate._parse_proxy_agent_output(output)
        self.assertEqual(text, 'Approved.')
        self.assertAlmostEqual(conf, 0.92)

    def test_no_confidence_marker_returns_zero(self):
        output = 'I approve this intent document.'
        text, conf = ApprovalGate._parse_proxy_agent_output(output)
        self.assertEqual(text, output)
        self.assertAlmostEqual(conf, 0.0)

    def test_confidence_caps_at_1(self):
        output = 'Good.\nCONFIDENCE: 1.5'
        text, conf = ApprovalGate._parse_proxy_agent_output(output)
        self.assertAlmostEqual(conf, 1.0)

    def test_confidence_floors_at_0(self):
        output = 'Hmm.\nCONFIDENCE: -0.3'
        text, conf = ApprovalGate._parse_proxy_agent_output(output)
        self.assertAlmostEqual(conf, 0.0)

    def test_multiline_response_with_confidence(self):
        output = 'The intent is well-articulated.\nHowever, criterion 2 is vague.\nCONFIDENCE: 0.6'
        text, conf = ApprovalGate._parse_proxy_agent_output(output)
        self.assertIn('criterion 2 is vague', text)
        self.assertAlmostEqual(conf, 0.6)

    def test_case_insensitive(self):
        output = 'Looks fine.\nconfidence: 0.75'
        text, conf = ApprovalGate._parse_proxy_agent_output(output)
        self.assertAlmostEqual(conf, 0.75)


if __name__ == '__main__':
    unittest.main()
