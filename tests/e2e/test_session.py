"""End-to-end tests for the Session orchestrator.

Each test emits a transcript to stderr showing exactly what happened:
state transitions, gate calls, and what the scripted runner wrote.
Run with -s to see it live; it's also embedded in assertion failures.

Backend selection (in priority order):
  1. Ollama  — if localhost:11434 is reachable, uses it for agent turns.
               The caller also writes the required artifact so the session
               can reach a terminal state regardless of LLM output.
  2. Scripted — deterministic caller; writes the artifact directly.

Coverage:
  Happy path (execute_only)
  Happy path (skip_intent — planning + execution)
  PLAN_ASSERT → refine-intent backtrack → COMPLETED_WORK
  WORK_ASSERT → revise-plan backtrack   → COMPLETED_WORK
  WORK_ASSERT → refine-intent backtrack → COMPLETED_WORK
  Gate dialog: PLAN_ASSERT correct → re-run → approve
  Gate dialog: WORK_ASSERT correct → re-run → approve
  Proxy escalates to human (proxy has no model; input_provider IS called)
  Proxy auto-approves   (consult_proxy patched to return confidence=0.95)
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
from teaparty.proxy.presence import HumanPresence, PresenceLevel


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
    subprocess.run(['git', 'add', 'README.md'], cwd=path, check=True,
                   capture_output=True)
    subprocess.run(['git', 'commit', '-m', 'init'], cwd=path, check=True,
                   capture_output=True)


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _make_human_presence() -> HumanPresence:
    """Human present at all gate levels so input_provider is always called.

    Without this, TASK_ASSERT is in _DEFAULT_NEVER_ESCALATE and the gate
    never routes to input_provider — it relies on the proxy agent instead.
    Proxy tests that need the proxy path pass human_presence=None explicitly.
    """
    p = HumanPresence()
    p.arrive(PresenceLevel.PROJECT)
    p.arrive(PresenceLevel.SUBTEAM)
    return p


# ── Base test class ───────────────────────────────────────────────────────────

class _SessionTestBase(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self.poc_root = os.path.join(self._tmp, 'poc')
        os.makedirs(self.poc_root)
        _init_git_repo(self.poc_root)
        self.projects_dir = os.path.join(self._tmp, 'projects')
        os.makedirs(self.projects_dir)

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
            # Human present at all levels → gate always calls input_provider.
            # TASK_ASSERT is in _DEFAULT_NEVER_ESCALATE (proxy-only by default);
            # human_presence overrides that so gate_script controls everything.
            # Proxy tests that need real proxy routing pass human_presence=None.
            human_presence=_make_human_presence(),
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
            result.terminal_state, 'COMPLETED_WORK',
            f'Expected COMPLETED_WORK, got {result.terminal_state!r}'
            f'{transcript.render()}',
        )

    def _assert_path_includes(self, transcript: _Transcript, *states: str):
        """Assert that every listed state appears somewhere in the transitions."""
        visited = {nxt for _, _, nxt in transcript.transitions}
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
        """execute_only=True + pre-written PLAN.md → COMPLETED_WORK."""
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
        self._assert_path_includes(t, 'WORK_ASSERT', 'COMPLETED_WORK')
        self._assert_artifacts_exist(t)

    def test_skip_intent_reaches_completed_work(self):
        """skip_intent=True + pre-written INTENT.md → planning + execution → COMPLETED_WORK."""
        intent_path = os.path.join(self._tmp, 'INTENT.md')
        Path(intent_path).write_text('# Intent\nBuild a summary tool.\n')

        t, bus = self._make_transcript_and_bus()
        # Gate calls: PLAN_ASSERT then WORK_ASSERT
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
        self._assert_path_includes(t, 'PLAN_ASSERT', 'WORK_ASSERT', 'COMPLETED_WORK')
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

    def test_plan_assert_refine_intent_backtrack(self):
        """PLAN_ASSERT → refine-intent → re-runs intent → re-runs planning → COMPLETED_WORK.

        Gate call sequence:
          1. PLAN_ASSERT:   refine-intent  (backtrack to intent)
          2. INTENT_ASSERT: approve        (second pass through intent)
          3. PLAN_ASSERT:   approve        (second pass through planning)
          4. WORK_ASSERT:   approve
        """
        intent_path = os.path.join(self._tmp, 'INTENT.md')
        Path(intent_path).write_text('# Intent\nBuild something.\n')

        t, bus = self._make_transcript_and_bus()
        gate = _GateScript(
            'refine-intent\tchange the objective to building a better tool',
            'approve',
            'approve',
            'approve',
        )

        with patch('teaparty.cfa.actors.ApprovalGate._classify_review',
                   side_effect=_stub_classify):
            session = self._make_session(
                t, gate,
                task='Build something',
                skip_intent=True,
                intent_file=intent_path,
                llm_caller=_make_phase_aware_caller(t),
            )
            result = self._run_session(session, t)

        self._assert_completed(result, t)
        self._assert_path_includes(t, 'PLAN_ASSERT', 'INTENT_RESPONSE',
                                   'INTENT_ASSERT', 'COMPLETED_WORK')
        self.assertGreater(result.backtrack_count, 0,
                           f'backtrack_count must be > 0{t.render()}')
        # Verify PLAN_ASSERT was visited at least twice
        plan_assert_visits = sum(1 for _, _, nxt in t.transitions
                                 if nxt == 'PLAN_ASSERT')
        self.assertGreaterEqual(plan_assert_visits, 2,
                                f'PLAN_ASSERT must be visited ≥2 times{t.render()}')

    def test_work_assert_revise_plan_backtrack(self):
        """WORK_ASSERT → revise-plan → re-runs planning → re-runs execution → COMPLETED_WORK.

        Gate call sequence (execute_only — starts at TASK, so TASK_ASSERT fires first):
          1. TASK_ASSERT:   approve        (first execution pass)
          2. WORK_ASSERT:   revise-plan    (backtrack to planning)
          3. PLAN_ASSERT:   approve        (re-planning)
          4. TASK_ASSERT:   approve        (re-execution)
          5. WORK_ASSERT:   approve
        """
        t, bus = self._make_transcript_and_bus()
        gate = _GateScript(
            'approve',                                                     # TASK_ASSERT
            'revise-plan\tthe approach was wrong, use a different architecture',  # WORK_ASSERT
            'approve',                                                     # PLAN_ASSERT
            'approve',                                                     # TASK_ASSERT (2nd)
            # WORK_ASSERT (2nd) → fallback 'approve'
        )

        with patch('teaparty.cfa.actors.ApprovalGate._classify_review',
                   side_effect=_stub_classify):
            session = self._make_session(
                t, gate,
                task='Build a summary tool',
                execute_only=True,
                plan_file=self._plan_file(),
                llm_caller=_make_phase_aware_caller(t),
            )
            result = self._run_session(session, t)

        self._assert_completed(result, t)
        self._assert_path_includes(t, 'WORK_ASSERT', 'PLANNING_RESPONSE',
                                   'PLAN_ASSERT', 'COMPLETED_WORK')
        self.assertGreater(result.backtrack_count, 0,
                           f'backtrack_count must be > 0{t.render()}')
        work_assert_visits = sum(1 for _, _, nxt in t.transitions
                                 if nxt == 'WORK_ASSERT')
        self.assertGreaterEqual(work_assert_visits, 2,
                                f'WORK_ASSERT must be visited ≥2 times{t.render()}')

    def test_work_assert_refine_intent_backtrack(self):
        """WORK_ASSERT → refine-intent → re-runs intent+planning+execution → COMPLETED_WORK.

        Gate call sequence (execute_only — starts at TASK, so TASK_ASSERT fires first):
          1. TASK_ASSERT:   approve        (first execution pass)
          2. WORK_ASSERT:   refine-intent  (backtrack all the way to intent)
          3. INTENT_ASSERT: approve
          4. PLAN_ASSERT:   approve
          5. TASK_ASSERT:   approve        (second execution pass)
          6. WORK_ASSERT:   approve        (fallback)
        """
        t, bus = self._make_transcript_and_bus()
        gate = _GateScript(
            'approve',                                               # TASK_ASSERT
            'refine-intent\tactually the goal should be different',  # WORK_ASSERT
            'approve',                                               # INTENT_ASSERT
            'approve',                                               # PLAN_ASSERT
            'approve',                                               # TASK_ASSERT (2nd)
            # WORK_ASSERT (2nd) → fallback 'approve'
        )

        with patch('teaparty.cfa.actors.ApprovalGate._classify_review',
                   side_effect=_stub_classify):
            session = self._make_session(
                t, gate,
                task='Build a summary tool',
                execute_only=True,
                plan_file=self._plan_file(),
                llm_caller=_make_phase_aware_caller(t),
            )
            result = self._run_session(session, t)

        self._assert_completed(result, t)
        self._assert_path_includes(t, 'WORK_ASSERT', 'INTENT_RESPONSE',
                                   'INTENT_ASSERT', 'COMPLETED_WORK')
        self.assertGreater(result.backtrack_count, 0,
                           f'backtrack_count must be > 0{t.render()}')


# ── Gate dialog tests ─────────────────────────────────────────────────────────

class TestSessionGateDialog(_SessionTestBase):

    def _plan_file(self) -> str:
        p = os.path.join(self._tmp, 'PLAN.md')
        Path(p).write_text('# Plan\nStep 1.\n')
        return p

    def test_work_assert_correct_then_approve(self):
        """WORK_ASSERT → correct (re-run execution) → WORK_ASSERT → approve.

        Gate call sequence (execute_only — starts at TASK, so TASK_ASSERT fires first):
          1. TASK_ASSERT:   approve        (first execution pass)
          2. WORK_ASSERT:   correct        (re-run execution)
          3. TASK_ASSERT:   approve        (after re-run)
          4. WORK_ASSERT:   approve
        """
        t, bus = self._make_transcript_and_bus()
        gate = _GateScript(
            'approve',                          # TASK_ASSERT (first pass)
            'correct\tthe summary needs more detail',  # WORK_ASSERT
            'approve',                          # TASK_ASSERT (after re-run)
            # WORK_ASSERT second visit → fallback 'approve'
        )

        with patch('teaparty.cfa.actors.ApprovalGate._classify_review',
                   side_effect=_stub_classify):
            session = self._make_session(
                t, gate,
                task='Write a detailed summary',
                execute_only=True,
                plan_file=self._plan_file(),
                llm_caller=_make_phase_aware_caller(t),
            )
            result = self._run_session(session, t)

        self._assert_completed(result, t)
        # TASK_RESPONSE must appear (correct action routes there)
        self._assert_path_includes(t, 'TASK_RESPONSE', 'WORK_ASSERT', 'COMPLETED_WORK')
        work_assert_visits = sum(1 for _, _, nxt in t.transitions
                                 if nxt == 'WORK_ASSERT')
        self.assertGreaterEqual(work_assert_visits, 2,
                                f'WORK_ASSERT must be visited ≥2 times{t.render()}')

    def test_plan_assert_correct_then_approve(self):
        """PLAN_ASSERT → correct (re-run planning) → PLAN_ASSERT → approve → COMPLETED_WORK.

        correct at PLAN_ASSERT → PLANNING_RESPONSE → DRAFT (agent re-runs) →
        PLAN_ASSERT → approve → PLAN → execution → COMPLETED_WORK.
        """
        intent_path = os.path.join(self._tmp, 'INTENT.md')
        Path(intent_path).write_text('# Intent\nBuild something.\n')

        t, bus = self._make_transcript_and_bus()
        gate = _GateScript(
            'correct\tadd error handling to step 2',
            'approve',   # PLAN_ASSERT second visit
            'approve',   # WORK_ASSERT
        )

        with patch('teaparty.cfa.actors.ApprovalGate._classify_review',
                   side_effect=_stub_classify):
            session = self._make_session(
                t, gate,
                task='Build something',
                skip_intent=True,
                intent_file=intent_path,
                llm_caller=_make_phase_aware_caller(t),
            )
            result = self._run_session(session, t)

        self._assert_completed(result, t)
        self._assert_path_includes(t, 'PLANNING_RESPONSE', 'PLAN_ASSERT', 'COMPLETED_WORK')
        plan_assert_visits = sum(1 for _, _, nxt in t.transitions
                                 if nxt == 'PLAN_ASSERT')
        self.assertGreaterEqual(plan_assert_visits, 2,
                                f'PLAN_ASSERT must be visited ≥2 times{t.render()}')


# ── Proxy path tests ──────────────────────────────────────────────────────────

class TestSessionProxyPaths(_SessionTestBase):

    def _plan_file(self) -> str:
        p = os.path.join(self._tmp, 'PLAN.md')
        Path(p).write_text('# Plan\nStep 1.\n')
        return p

    def test_proxy_escalates_calls_input_provider(self):
        """Human presence overrides proxy — input_provider IS called at every gate.

        With human_presence set (the default), the gate routes directly to
        input_provider regardless of proxy confidence.  This verifies that
        the input_provider is the decision-maker when the human is present.
        """
        t, bus = self._make_transcript_and_bus()
        gate = _GateScript('approve')

        with patch('teaparty.cfa.actors.ApprovalGate._classify_review',
                   side_effect=_stub_classify):
            session = self._make_session(
                t, gate,
                task='Proxy escalation test',
                execute_only=True,
                plan_file=self._plan_file(),
                llm_caller=_make_phase_aware_caller(t),
            )
            result = self._run_session(session, t)

        self._assert_completed(result, t)
        # gate.calls accumulates (state, response) for every gate invocation
        self.assertGreater(len(gate.calls), 0,
                           f'input_provider must be called at every gate{t.render()}')

    def test_proxy_auto_approves_skips_input_provider(self):
        """High-confidence proxy answers at every gate — input_provider is NOT called.

        human_presence=None removes the "human present" override so the proxy
        path is active.  consult_proxy patched to return confident 'approve'.
        TASK_ASSERT is in _DEFAULT_NEVER_ESCALATE — also handled by proxy.
        """
        from teaparty.proxy.agent import ProxyResult

        t, bus = self._make_transcript_and_bus()
        provider_calls: list[str] = []

        async def recording_provider(request) -> str:
            provider_calls.append(request.state)
            return 'approve'

        high_confidence = ProxyResult(text='approve', confidence=0.95, from_agent=True)

        async def mock_consult_high(*args, **kwargs) -> ProxyResult:
            return high_confidence

        with patch('teaparty.cfa.actors.ApprovalGate._classify_review',
                   side_effect=_stub_classify):
            with patch('teaparty.proxy.agent.consult_proxy', new=mock_consult_high):
                session = self._make_session(
                    t, recording_provider,
                    task='Proxy auto-approve test',
                    execute_only=True,
                    plan_file=self._plan_file(),
                    llm_caller=_make_phase_aware_caller(t),
                    proxy_enabled=True,
                    human_presence=None,  # proxy path — no direct human override
                )
                result = self._run_session(session, t)

        self._assert_completed(result, t)
        self.assertEqual(len(provider_calls), 0,
                         f'input_provider must NOT be called when proxy is confident'
                         f'{t.render()}')


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
        self.assertEqual(completed.data.get('terminal_state'), 'COMPLETED_WORK',
                         f'SESSION_COMPLETED must carry COMPLETED_WORK{t.render()}')

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
        self.assertIn('COMPLETED_WORK', final_states,
                      f'COMPLETED_WORK never reached{t.render()}')
        visited = {nxt for _, _, nxt in t.transitions}
        self.assertTrue(
            visited & {'TASK', 'TASK_IN_PROGRESS', 'WORK_IN_PROGRESS'},
            f'No execution-phase states in transitions{t.render()}',
        )


if __name__ == '__main__':
    unittest.main()
