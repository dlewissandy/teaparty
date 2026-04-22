"""End-to-end tests for the Session orchestrator.

Each test emits a transcript to stderr showing exactly what happened:
state transitions, gate calls, and what the scripted runner wrote.
Run with -s to see it live; it's also embedded in assertion failures.

Backend selection (in priority order):
  1. Ollama  — if localhost:11434 is reachable, uses it for agent turns.
               The caller also writes the required artifact so the session
               can reach a terminal state regardless of LLM output.
  2. Scripted — deterministic caller; writes the artifact directly.

Coverage (five-state CfA model: INTENT, PLAN, EXECUTE, DONE, WITHDRAWN):
  Happy path (execute_only)               → DONE
  Happy path (skip_intent — planning + execution) → DONE
  EXECUTE → replan backtrack (re-runs planning + execution) → DONE
  EXECUTE → realign backtrack (re-runs intent + planning + execution) → DONE
  Dry-run exits before any LLM call
  Session events: SESSION_STARTED, SESSION_COMPLETED published
  State transitions: STATE_CHANGED events match execution path
"""
from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

from teaparty.runners.claude import ClaudeResult
from teaparty.messaging.bus import EventBus, EventType


# ── Ollama detection ─────────────────────────────────────────────────────────

def _check_ollama_sync(host: str = 'http://localhost:11434') -> bool:
    try:
        import urllib.request
        with urllib.request.urlopen(f'{host}/api/tags', timeout=2) as r:
            return r.status == 200
    except Exception:
        return False


_OLLAMA_AVAILABLE: bool = _check_ollama_sync()
_OLLAMA_MODEL: str = os.environ.get('TEAPARTY_E2E_OLLAMA_MODEL', 'mistral')


# ── Transcript ────────────────────────────────────────────────────────────────

class _Transcript:
    """Collects session events and renders a human-readable proof of execution."""

    def __init__(self, bus: EventBus):
        self.transitions: list[tuple[str, str, str]] = []
        # (state, artifact_path, bridge_text_snippet, response)
        self.gate_calls: list[tuple[str, str, str, str]] = []
        self.runner_calls: list[tuple[str, str, str]] = []  # (artifact, path, content)
        self._pending_request: dict = {}

        async def _collect(event) -> None:
            if event.type == EventType.STATE_CHANGED:
                self.transitions.append((
                    event.data.get('previous_state', '?'),
                    event.data.get('action', '?'),
                    event.data.get('state', '?'),
                ))
            elif event.type == EventType.INPUT_REQUESTED:
                self._pending_request = event.data
            elif event.type == EventType.INPUT_RECEIVED:
                req = self._pending_request
                state = req.get('state', '?')
                artifact = req.get('artifact', '')
                bridge = req.get('bridge_text', '')
                # First line of bridge text as a summary (full text can be long)
                bridge_snip = (bridge.splitlines()[0] if bridge else '').strip()
                response = event.data.get('response', '?')
                self.gate_calls.append((state, artifact, bridge_snip, response))
                self._pending_request = {}

        bus.subscribe(_collect)

    def record_runner(self, artifact: str, path: str, content: str) -> None:
        """Record an artifact write. Verifies existence and content immediately.

        The session removes its worktree after completion, so post-session
        disk checks would always fail.  We verify at write time instead.
        """
        full_path = Path(path, artifact)
        exists_now = full_path.exists()
        actual = full_path.read_text() if exists_now else None
        self.runner_calls.append((artifact, path, content, exists_now, actual))

    def render(self) -> str:
        lines = ['', '=== Session Transcript ===']
        lines.append('State transitions:')
        for prev, action, nxt in self.transitions:
            lines.append(f'  {prev} →({action})→ {nxt}')
        if self.gate_calls:
            lines.append('Gate dialog:')
            for state, artifact, bridge_snip, resp in self.gate_calls:
                artifact_name = Path(artifact).name if artifact else '—'
                lines.append(f'  [{state}] reviewing: {artifact_name}')
                if bridge_snip:
                    lines.append(f'           prompt:    {bridge_snip!r}')
                lines.append(f'           human said: {resp!r}')
        if self.runner_calls:
            lines.append('Runner artifacts written:')
            for name, path, content, exists, actual in self.runner_calls:
                first_line = content.splitlines()[0] if content else '(empty)'
                ok = '✓' if exists and actual == content else '✗'
                lines.append(f'  {ok} {name} → {path}')
                lines.append(f'           content[0]: {first_line!r}')
        lines.append('=========================')
        return '\n'.join(lines)


# ── Scripted input providers ──────────────────────────────────────────────────

class _GateScript:
    """Returns scripted gate responses in call order; falls back to 'approve'."""

    def __init__(self, *responses: str):
        self._responses = list(responses)
        self._index = 0
        self.calls: list[tuple[str, str]] = []   # (state, response)

    async def __call__(self, request) -> str:
        response = (
            self._responses[self._index]
            if self._index < len(self._responses)
            else 'approve'
        )
        self.calls.append((request.state, response))
        self._index += 1
        return response


# ── Scripted LLM callers ──────────────────────────────────────────────────────

def _make_phase_aware_caller(transcript: _Transcript | None = None) -> Any:
    """Write the artifact matching the current phase (detected from stream_file path).

    intent   stream → writes INTENT.md
    planning stream → writes PLAN.md
    execution stream → writes WORK_SUMMARY.md
    """
    async def caller(**kwargs) -> ClaudeResult:
        cwd = kwargs.get('cwd', '')
        stream_file = kwargs.get('stream_file', '')
        on_stream_event = kwargs.get('on_stream_event')

        sf = stream_file or ''
        if '.intent-stream' in sf:
            artifact, content = 'INTENT.md', '# Intent\nBuild a summary tool.\n'
        elif '.plan-stream' in sf:
            artifact, content = 'PLAN.md', '# Plan\nStep 1: write summary.\n'
        else:
            artifact, content = 'WORK_SUMMARY.md', '# Work Summary\nDone.\n'

        if cwd:
            Path(cwd, artifact).write_text(content)
            if transcript:
                transcript.record_runner(artifact, cwd, content)
            # Intent-alignment and planning skills self-terminate via
            # .phase-outcome.json. The scripted caller emits APPROVE to
            # advance to the next phase.
            if '.intent-stream' in sf or '.plan-stream' in sf:
                import json as _json
                Path(cwd, '.phase-outcome.json').write_text(
                    _json.dumps({'outcome': 'APPROVE',
                                 'reason': 'scripted e2e approval'})
                )

        if stream_file:
            Path(stream_file).touch()

        if on_stream_event:
            on_stream_event({
                'type': 'assistant',
                'message': {'content': [{'type': 'text', 'text': content}]},
            })

        return ClaudeResult(exit_code=0, session_id='e2e-scripted')

    return caller


def _make_ollama_caller(transcript: _Transcript | None = None) -> Any:
    """Run real Ollama inference AND write the artifact so the session completes."""
    async def caller(**kwargs) -> ClaudeResult:
        from teaparty.runners.ollama import OllamaRunner
        cwd = kwargs.get('cwd', '')
        stream_file = kwargs.get('stream_file', '')

        sf = stream_file or ''
        if '.intent-stream' in sf:
            artifact, content = 'INTENT.md', '# Intent\nBuild a summary tool.\n'
        elif '.plan-stream' in sf:
            artifact, content = 'PLAN.md', '# Plan\nStep 1: write summary.\n'
        else:
            artifact, content = 'WORK_SUMMARY.md', '# Work Summary\nDone.\n'

        ollama_kwargs = {k: v for k, v in kwargs.items()
                        if k in ('cwd', 'stream_file')}
        message = kwargs.get('message', '')
        ollama_kwargs.setdefault('model', _OLLAMA_MODEL)

        runner = OllamaRunner(message, **ollama_kwargs)
        result = await runner.run()

        # Guarantee the artifact regardless of what Ollama produced
        if cwd:
            Path(cwd, artifact).write_text(content)
            if transcript:
                transcript.record_runner(artifact, f'{cwd} (via ollama)', content)

        return ClaudeResult(
            exit_code=0,
            session_id=result.session_id or 'e2e-ollama',
            stream_file=result.stream_file,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            duration_ms=result.duration_ms,
        )

    return caller


def _make_scripted_outcome_caller(
    exec_outcomes: list[str],
    transcript: _Transcript | None = None,
) -> Any:
    """Phase-aware scripted caller whose execution-phase outcomes are scripted.

    ``exec_outcomes`` is consumed in order for each execution-phase turn.
    Typical use: ['REPLAN', 'APPROVE'] to force a backtrack-to-PLAN on the
    first execute turn and approval on the re-run.

    Intent and planning turns always emit APPROVE so those phases advance
    cleanly — backtracks from those phases aren't exercised by these tests.
    """
    remaining = list(exec_outcomes)

    async def caller(**kwargs) -> ClaudeResult:
        import json as _json
        cwd = kwargs.get('cwd', '')
        stream_file = kwargs.get('stream_file', '')
        on_stream_event = kwargs.get('on_stream_event')

        sf = stream_file or ''
        if '.intent-stream' in sf:
            artifact, content, outcome = (
                'INTENT.md', '# Intent\nBuild a summary tool.\n', 'APPROVE',
            )
        elif '.plan-stream' in sf:
            artifact, content, outcome = (
                'PLAN.md', '# Plan\nStep 1: write summary.\n', 'APPROVE',
            )
        else:
            artifact, content = 'WORK_SUMMARY.md', '# Work Summary\nDone.\n'
            outcome = remaining.pop(0) if remaining else 'APPROVE'

        if cwd:
            Path(cwd, artifact).write_text(content)
            if transcript:
                transcript.record_runner(artifact, cwd, content)
            Path(cwd, '.phase-outcome.json').write_text(
                _json.dumps({'outcome': outcome,
                             'reason': f'scripted e2e {outcome.lower()}'})
            )

        if stream_file:
            Path(stream_file).touch()

        if on_stream_event:
            on_stream_event({
                'type': 'assistant',
                'message': {'content': [{'type': 'text', 'text': content}]},
            })

        return ClaudeResult(exit_code=0, session_id='e2e-scripted')

    return caller


def _make_caller(transcript: _Transcript | None = None) -> Any:
    """Return the scripted caller by default.

    Ollama is only used when TEAPARTY_E2E_OLLAMA_MODEL is explicitly set in
    the environment (not just available).  Ollama inference is too slow to be
    useful in the default test suite.
    """
    if os.environ.get('TEAPARTY_E2E_OLLAMA_MODEL') and _OLLAMA_AVAILABLE:
        return _make_ollama_caller(transcript)
    return _make_phase_aware_caller(transcript)


# ── classify_review stub ──────────────────────────────────────────────────────

def _stub_classify(state: str, response: str, dialog_history: str = '', **_) -> tuple[str, str]:
    """Parse the gate response directly instead of calling Claude Haiku.

    Input providers return  'action'  or  'action\tfeedback'.
    This stub splits on tab so the backtrack/dialog tests are deterministic
    and don't depend on an external LLM call to classify.
    """
    parts = response.strip().split('\t', 1)
    action = parts[0].strip().lower()
    feedback = parts[1].strip() if len(parts) > 1 else ''
    return action, feedback


# ── Git repo fixture ──────────────────────────────────────────────────────────

def _init_git_repo(path: str) -> None:
    subprocess.run(['git', 'init', '-b', 'main'], cwd=path, check=True,
                   capture_output=True)
    subprocess.run(['git', 'config', 'user.email', 'test@example.com'],
                   cwd=path, check=True, capture_output=True)
    subprocess.run(['git', 'config', 'user.name', 'Test'],
                   cwd=path, check=True, capture_output=True)
    Path(path, 'README.md').write_text('# e2e test repo\n')
    # The jail hook script is staged into each worktree by
    # AgentRunner._stage_jail_hook from the installed teaparty package;
    # tests don't need to pre-populate it in the repo.
    subprocess.run(['git', 'add', 'README.md'], cwd=path, check=True,
                   capture_output=True)
    subprocess.run(['git', 'commit', '-m', 'init'], cwd=path, check=True,
                   capture_output=True)


def _run(coro):
    return asyncio.run(coro)


# ── Base test class ───────────────────────────────────────────────────────────

class _SessionTestBase(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self.poc_root = os.path.join(self._tmp, 'poc')
        os.makedirs(self.poc_root)
        _init_git_repo(self.poc_root)
        self.projects_dir = os.path.join(self._tmp, 'projects')
        os.makedirs(self.projects_dir)
        project_dir = os.path.join(self.projects_dir, 'e2e-test')
        os.makedirs(project_dir)
        _init_git_repo(project_dir)

    def tearDown(self):
        import shutil
        try:
            subprocess.run(['git', 'worktree', 'prune'], cwd=self.poc_root,
                           capture_output=True)
        except Exception:
            pass
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _make_session(self, transcript: _Transcript, gate_script: _GateScript,
                      **kwargs):
        from teaparty.cfa.session import Session
        defaults = dict(
            poc_root=self.poc_root,
            projects_dir=self.projects_dir,
            project_override='e2e-test',
            skip_learnings=True,
            input_provider=gate_script,
            event_bus=transcript._bus,
            proxy_enabled=False,
            # In the five-state CfA model the approval-gate actor is not
            # invoked at all — each phase runs a skill that self-terminates
            # by writing .phase-outcome.json.  ``escalation_modes`` is kept
            # here for forward compatibility but has no effect on the e2e
            # path exercised by these tests.
            escalation_modes={},
        )
        defaults.update(kwargs)
        return Session(**defaults)

    def _make_transcript_and_bus(self) -> tuple[_Transcript, EventBus]:
        bus = EventBus()
        t = _Transcript(bus)
        t._bus = bus
        return t, bus

    def _run_session(self, session, transcript: _Transcript) -> Any:
        """Run the session and print the transcript regardless of pass/fail."""
        try:
            result = _run(session.run())
        except Exception as exc:
            print(transcript.render(), file=sys.stderr)
            raise
        print(transcript.render(), file=sys.stderr)
        return result

    def _assert_completed(self, result, transcript: _Transcript):
        self.assertEqual(
            result.terminal_state, 'DONE',
            f'Expected DONE, got {result.terminal_state!r}'
            f'{transcript.render()}',
        )

    def _assert_path_includes(self, transcript: _Transcript, *states: str):
        """Assert that every listed state appears in the transitions.

        Checks both sides of each edge so states that are entered via
        ``set_state_direct`` (e.g., EXECUTE in execute_only mode) count as
        visited even when they appear only as the source of the first edge.
        """
        visited = {s for edge in transcript.transitions for s in (edge[0], edge[2])}
        for state in states:
            self.assertIn(
                state, visited,
                f'{state} was never reached{transcript.render()}',
            )

    def _assert_artifacts_exist(self, transcript: _Transcript):
        """Assert every recorded artifact existed on disk with correct content at write time.

        Existence is verified when record_runner() is called (immediately after
        the file is written), because the session removes its worktree after
        completion.
        """
        self.assertGreater(
            len(transcript.runner_calls), 0,
            f'No artifacts were written{transcript.render()}',
        )
        for name, path, expected_content, existed, actual in transcript.runner_calls:
            full_path = Path(path, name)
            self.assertTrue(
                existed,
                f'Artifact {full_path} did not exist at write time{transcript.render()}',
            )
            self.assertEqual(
                actual, expected_content,
                f'Artifact {full_path} content mismatch at write time{transcript.render()}',
            )


# ── Happy-path tests ──────────────────────────────────────────────────────────

class TestSessionHappyPath(_SessionTestBase):

    def test_execute_only_reaches_completed_work(self):
        """execute_only=True + pre-written PLAN.md → DONE."""
        plan_path = os.path.join(self._tmp, 'PLAN.md')
        Path(plan_path).write_text('# Plan\nWrite a one-line summary.\n')

        t, bus = self._make_transcript_and_bus()
        gate = _GateScript('approve')

        with patch('teaparty.cfa.actors.ApprovalGate._classify_review',
                   side_effect=_stub_classify):
            session = self._make_session(
                t, gate,
                task='Write a one-line project summary',
                execute_only=True,
                plan_file=plan_path,
                llm_caller=_make_caller(t),
            )
            result = self._run_session(session, t)

        self._assert_completed(result, t)
        self._assert_path_includes(t, 'EXECUTE', 'DONE')
        self._assert_artifacts_exist(t)

    def test_skip_intent_reaches_completed_work(self):
        """skip_intent=True + pre-written INTENT.md → planning + execution → DONE."""
        intent_path = os.path.join(self._tmp, 'INTENT.md')
        Path(intent_path).write_text('# Intent\nBuild a summary tool.\n')

        t, bus = self._make_transcript_and_bus()
        # Gate script is unused in the five-state model (no approval-gate
        # actor), but a valid input_provider is still required.
        gate = _GateScript('approve', 'approve')

        with patch('teaparty.cfa.actors.ApprovalGate._classify_review',
                   side_effect=_stub_classify):
            session = self._make_session(
                t, gate,
                task='Build a simple summary tool',
                skip_intent=True,
                intent_file=intent_path,
                llm_caller=_make_phase_aware_caller(t),
            )
            result = self._run_session(session, t)

        self._assert_completed(result, t)
        self._assert_path_includes(t, 'PLAN', 'EXECUTE', 'DONE')
        self._assert_artifacts_exist(t)
        # Verify both phases ran
        artifact_names = {name for name, *_ in t.runner_calls}
        self.assertIn('PLAN.md', artifact_names, f'Planning phase never ran{t.render()}')
        self.assertIn('WORK_SUMMARY.md', artifact_names, f'Execution phase never ran{t.render()}')

    def test_dry_run_exits_without_llm(self):
        """dry_run=True exits immediately with DRY_RUN — no LLM calls."""
        called = []

        async def sentinel(**kwargs) -> ClaudeResult:
            called.append(kwargs)
            return ClaudeResult(exit_code=0)

        t, bus = self._make_transcript_and_bus()
        gate = _GateScript()

        session = self._make_session(
            t, gate,
            task='Does not matter',
            dry_run=True,
            llm_caller=sentinel,
        )
        result = self._run_session(session, t)

        self.assertEqual(result.terminal_state, 'DRY_RUN',
                         f'Expected DRY_RUN{t.render()}')
        self.assertEqual(len(called), 0,
                         f'LLM must not be called during dry_run{t.render()}')


# ── Backtrack path tests ──────────────────────────────────────────────────────

class TestSessionBacktrackPaths(_SessionTestBase):

    def _plan_file(self) -> str:
        p = os.path.join(self._tmp, 'PLAN.md')
        Path(p).write_text('# Plan\nStep 1.\n')
        return p

    def test_work_assert_revise_plan_backtrack(self):
        """EXECUTE → replan → re-runs planning → re-runs execution → DONE.

        The execute skill emits REPLAN on the first run (via phase-outcome)
        and APPROVE on the re-run after planning completes again.
        """
        t, bus = self._make_transcript_and_bus()
        gate = _GateScript()  # unused — skill self-terminates via phase-outcome

        with patch('teaparty.cfa.actors.ApprovalGate._classify_review',
                   side_effect=_stub_classify):
            session = self._make_session(
                t, gate,
                task='Build a summary tool',
                execute_only=True,
                plan_file=self._plan_file(),
                llm_caller=_make_scripted_outcome_caller(
                    exec_outcomes=['REPLAN', 'APPROVE'], transcript=t,
                ),
            )
            result = self._run_session(session, t)

        self._assert_completed(result, t)
        self._assert_path_includes(t, 'EXECUTE', 'PLAN', 'DONE')
        self.assertGreater(result.backtrack_count, 0,
                           f'backtrack_count must be > 0{t.render()}')
        execute_visits = sum(1 for _, _, nxt in t.transitions
                             if nxt == 'EXECUTE')
        self.assertGreaterEqual(execute_visits, 1,
                                f'EXECUTE must be re-entered after replan{t.render()}')

    def test_work_assert_refine_intent_backtrack(self):
        """EXECUTE → realign → re-runs intent+planning+execution → DONE.

        The execute skill emits REALIGN on the first run (via phase-outcome)
        and APPROVE on the re-run after intent and planning complete again.
        """
        t, bus = self._make_transcript_and_bus()
        gate = _GateScript()  # unused — skill self-terminates via phase-outcome

        with patch('teaparty.cfa.actors.ApprovalGate._classify_review',
                   side_effect=_stub_classify):
            session = self._make_session(
                t, gate,
                task='Build a summary tool',
                execute_only=True,
                plan_file=self._plan_file(),
                llm_caller=_make_scripted_outcome_caller(
                    exec_outcomes=['REALIGN', 'APPROVE'], transcript=t,
                ),
            )
            result = self._run_session(session, t)

        self._assert_completed(result, t)
        self._assert_path_includes(t, 'EXECUTE', 'INTENT', 'DONE')
        self.assertGreater(result.backtrack_count, 0,
                           f'backtrack_count must be > 0{t.render()}')


# ── Gate dialog tests ─────────────────────────────────────────────────────────
#
# The pre-collapse ``test_work_assert_correct_then_approve`` has been removed:
# the ``correct`` action (WORK_ASSERT → WORK_IN_PROGRESS re-run) no longer
# exists as a state-machine edge in the five-state model.  Mid-phase
# correction is handled internally by the execute skill and is not visible
# as a CfA transition — nothing for an end-to-end test at this layer to
# assert against.


# ── Proxy path tests ──────────────────────────────────────────────────────────
#
# The pre-collapse ``TestSessionProxyPaths`` class has been removed.  Both
# tests verified behaviour of the ApprovalGate actor (proxy vs. input_provider
# routing at *_ASSERT gate states).  In the five-state model there are no
# approval-gate actor states — phases self-terminate via .phase-outcome.json
# and input_provider is not consulted at this layer.  Proxy/gate routing is
# exercised by the unit tests in tests/proxy/ and tests/cfa/, which are the
# right layer for that coverage.


# ── Event tests ───────────────────────────────────────────────────────────────

class TestSessionEvents(_SessionTestBase):

    def _plan_file(self) -> str:
        p = os.path.join(self._tmp, 'PLAN.md')
        Path(p).write_text('# Plan\n')
        return p

    def test_session_started_and_completed_published(self):
        """SESSION_STARTED and SESSION_COMPLETED must fire with correct payloads."""
        t, bus = self._make_transcript_and_bus()
        all_events: list = []

        async def collect(event) -> None:
            all_events.append(event)

        bus.subscribe(collect)

        gate = _GateScript('approve')

        with patch('teaparty.cfa.actors.ApprovalGate._classify_review',
                   side_effect=_stub_classify):
            session = self._make_session(
                t, gate,
                task='event test',
                execute_only=True,
                plan_file=self._plan_file(),
                llm_caller=_make_phase_aware_caller(t),
                event_bus=bus,
            )
            result = self._run_session(session, t)

        types = {e.type for e in all_events}
        self.assertIn(EventType.SESSION_STARTED, types,
                      f'SESSION_STARTED missing{t.render()}')
        self.assertIn(EventType.SESSION_COMPLETED, types,
                      f'SESSION_COMPLETED missing{t.render()}')

        completed = next(e for e in all_events
                         if e.type == EventType.SESSION_COMPLETED)
        self.assertEqual(completed.data.get('terminal_state'), 'DONE',
                         f'SESSION_COMPLETED must carry DONE{t.render()}')

    def test_state_changes_traverse_execution_path(self):
        """STATE_CHANGED events must show the execution-phase states."""
        t, bus = self._make_transcript_and_bus()
        gate = _GateScript('approve')

        with patch('teaparty.cfa.actors.ApprovalGate._classify_review',
                   side_effect=_stub_classify):
            session = self._make_session(
                t, gate,
                task='transition test',
                execute_only=True,
                plan_file=self._plan_file(),
                llm_caller=_make_phase_aware_caller(t),
                event_bus=bus,
            )
            result = self._run_session(session, t)

        self.assertGreater(len(t.transitions), 0,
                           f'No STATE_CHANGED events{t.render()}')
        final_states = [nxt for _, _, nxt in t.transitions]
        self.assertIn('DONE', final_states,
                      f'DONE never reached{t.render()}')
        # EXECUTE is entered via set_state_direct in execute_only mode, so it
        # appears as the source of the first transition rather than as a
        # target.  Cover both sides of each edge.
        visited = {s for edge in t.transitions for s in (edge[0], edge[2])}
        self.assertIn(
            'EXECUTE', visited,
            f'EXECUTE must appear in the execution path{t.render()}',
        )


if __name__ == '__main__':
    unittest.main()
