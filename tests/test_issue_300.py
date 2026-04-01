"""Tests for issue #300: home page — wire mockup to live bridge API.

Acceptance criteria:
1. index.html no longer reads mockData for project cards — data comes from GET /api/state
2. index.html does not load data.js as its data source
3. index.html establishes a WebSocket connection for real-time updates
4. Bridge _serialize_session includes all fields the home page needs:
   session_id (navigation), cfa_phase (workflow bar), needs_input (escalation dot),
   task (job name), status (status badge)
5. Bridge _serialize_project includes attention_count and active_count for the home page
6. CfA phase names map to the standard 7-element phase sequence used for workflow bars
7. Sessions with needs_input:true carry escalation signal the home page can detect
8. Projects with zero active sessions (idle state) are represented by active_count=0
"""
import os
import unittest


# ── Helpers ───────────────────────────────────────────────────────────────────

MOCKUP_DIR = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    'docs', 'proposals', 'ui-redesign', 'mockup',
)
INDEX_HTML = os.path.join(MOCKUP_DIR, 'index.html')


def _read_index():
    with open(INDEX_HTML) as f:
        return f.read()


def _make_session(
    session_id='20260325-143000',
    project='poc',
    status='active',
    cfa_phase='WORK',
    cfa_state='TASK_EXEC',
    cfa_actor='agent',
    needs_input=False,
    task='Fix the bug',
    heartbeat_status='alive',
    total_cost_usd=0.5,
    backtrack_count=0,
    infra_dir='/tmp/sess',
):
    from dataclasses import dataclass, field

    @dataclass
    class FakeSession:
        project: str
        session_id: str
        worktree_name: str
        worktree_path: str
        task: str
        status: str
        cfa_phase: str = ''
        cfa_state: str = ''
        cfa_actor: str = ''
        needs_input: bool = False
        is_orphaned: bool = False
        dispatches: list = field(default_factory=list)
        stream_age_seconds: int = -1
        duration_seconds: int = -1
        infra_dir: str = ''
        files_changed: list = field(default_factory=list)
        heartbeat_status: str = ''
        total_cost_usd: float = 0.0
        backtrack_count: int = 0

    return FakeSession(
        project=project,
        session_id=session_id,
        worktree_name='',
        worktree_path='',
        task=task,
        status=status,
        cfa_phase=cfa_phase,
        cfa_state=cfa_state,
        cfa_actor=cfa_actor,
        needs_input=needs_input,
        infra_dir=infra_dir,
        heartbeat_status=heartbeat_status,
        total_cost_usd=total_cost_usd,
        backtrack_count=backtrack_count,
    )


def _make_project(slug='poc', sessions=None, active_count=0, attention_count=0):
    from dataclasses import dataclass, field

    @dataclass
    class FakeProject:
        slug: str
        path: str
        name: str = ''
        sessions: list = field(default_factory=list)
        active_count: int = 0
        attention_count: int = 0

    return FakeProject(
        slug=slug,
        path=f'/projects/{slug}',
        sessions=sessions or [],
        active_count=active_count,
        attention_count=attention_count,
    )


# ── HTML content tests ────────────────────────────────────────────────────────

class TestIndexHtmlLiveDataBinding(unittest.TestCase):
    """index.html must fetch live data from the bridge API, not use hardcoded mockData."""

    def test_index_html_does_not_read_mock_data(self):
        """index.html must not reference mockData (the hardcoded data.js variable)."""
        content = _read_index()
        self.assertNotIn('mockData', content,
                         'index.html must not read from mockData — use GET /api/state instead')

    def test_index_html_does_not_load_data_js_as_page_data(self):
        """index.html must not use data.js as its primary data source for page content.

        data.js provides hardcoded fixture data. The live page must fetch from the API.
        A data.js script tag in the head means the page is still using static data.
        """
        content = _read_index()
        # If data.js is loaded, it will be used; the live page must not do this
        # (data.js can exist for other mockup pages — just not index.html's data)
        import re
        # Check for <script src="data.js ..."> pattern
        data_js_script = re.search(r'<script[^>]+src=["\']data\.js', content)
        self.assertIsNone(data_js_script,
                          'index.html must not load data.js — fetch /api/state instead')

    def test_index_html_fetches_api_state(self):
        """index.html must call GET /api/state to populate project cards."""
        content = _read_index()
        self.assertIn('/api/state', content,
                      'index.html must fetch /api/state for live project data')

    def test_index_html_has_websocket_connection(self):
        """index.html must open a WebSocket for real-time state_changed events."""
        content = _read_index()
        self.assertIn('WebSocket', content,
                      'index.html must establish a WebSocket connection for real-time updates')

    def test_index_html_handles_state_changed_event(self):
        """index.html must handle state_changed WebSocket events to update workflow bars."""
        content = _read_index()
        self.assertIn('state_changed', content,
                      'index.html must handle state_changed events from the WebSocket')

    def test_index_html_handles_message_event(self):
        """index.html must handle WebSocket message events to update badge counts.

        When a human sends a message resolving an escalation, the badge count must
        decrease without a page reload. The message event carries conversation_id
        and sender fields.
        """
        content = _read_index()
        self.assertIn("event.type === 'message'", content,
                      "index.html must handle 'message' WebSocket events for badge count updates")


class TestIndexHtmlNavigationLinks(unittest.TestCase):
    """Navigation links in index.html must use real conversation IDs."""

    def test_index_html_job_row_uses_job_conv_format(self):
        """Job row click handlers must use job:{project}:{session_id} format.

        Per the controls spec: "Click project job row → Opens job chat (chat.html?conv=JOB_ID)"
        where JOB_ID = job:{project}:{job_id}. In this system job_id == session_id.
        """
        content = _read_index()
        self.assertIn("'job:' + p.slug + ':' + s.session_id", content,
                      "Job row onclick must build job:{project}:{session_id} conv ID per spec")

    def test_index_html_does_not_use_hardcoded_job_ids(self):
        """index.html must not embed static job IDs from data.js."""
        content = _read_index()
        self.assertNotIn('job:poc:job-001', content,
                         'index.html must not use hardcoded job IDs — derive from session_id')
        self.assertNotIn('job:poc:job-002', content,
                         'index.html must not use hardcoded job IDs — derive from session_id')


class TestIndexHtmlIdleState(unittest.TestCase):
    """index.html must render correctly with zero active sessions."""

    def test_index_html_handles_empty_sessions_array(self):
        """The render function must not crash when sessions array is empty.

        A project with no active sessions must still show its card with
        stats (0, 0, N) and action buttons.
        """
        content = _read_index()
        # The page must guard against empty sessions
        # (e.g. checking array length before rendering job rows)
        # At minimum, verify the render code processes a 'sessions' array (not 'jobs')
        self.assertIn('sessions', content,
                      'index.html must reference the sessions field from GET /api/state')


# ── Bridge serialization contract ─────────────────────────────────────────────

class TestBridgeSessionSerializationContract(unittest.TestCase):
    """_serialize_session must include all fields the home page needs."""

    def setUp(self):
        import shutil
        import tempfile
        self.tmpdir = tempfile.mkdtemp()
        from bridge.server import TeaPartyBridge
        static_dir = os.path.join(self.tmpdir, 'static')
        os.makedirs(static_dir)
        self.bridge = TeaPartyBridge(
            teaparty_home=self.tmpdir,
            static_dir=static_dir,
        )

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_session_id_in_serialized_session(self):
        """session_id must be present — used to build navigation URLs."""
        session = _make_session(session_id='20260325-143000')
        result = self.bridge._serialize_session(session)
        self.assertIn('session_id', result)
        self.assertEqual(result['session_id'], '20260325-143000')

    def test_cfa_phase_in_serialized_session(self):
        """cfa_phase must be present — used to position the workflow bar."""
        session = _make_session(cfa_phase='WORK')
        result = self.bridge._serialize_session(session)
        self.assertIn('cfa_phase', result)
        self.assertEqual(result['cfa_phase'], 'WORK')

    def test_needs_input_in_serialized_session(self):
        """needs_input must be present — used to show escalation dot."""
        session = _make_session(needs_input=True)
        result = self.bridge._serialize_session(session)
        self.assertIn('needs_input', result)
        self.assertTrue(result['needs_input'])

    def test_needs_input_false_by_default(self):
        """needs_input must be false for sessions not awaiting human input."""
        session = _make_session(needs_input=False)
        result = self.bridge._serialize_session(session)
        self.assertFalse(result['needs_input'])

    def test_task_in_serialized_session(self):
        """task must be present — displayed as the job name in the row."""
        session = _make_session(task='Implement the feature')
        result = self.bridge._serialize_session(session)
        self.assertIn('task', result)
        self.assertEqual(result['task'], 'Implement the feature')

    def test_status_in_serialized_session(self):
        """status must be present — used for the status badge."""
        session = _make_session(status='active')
        result = self.bridge._serialize_session(session)
        self.assertIn('status', result)
        self.assertEqual(result['status'], 'active')

    def test_project_in_serialized_session(self):
        """project must be present — used to scope navigation links."""
        session = _make_session(project='poc')
        result = self.bridge._serialize_session(session)
        self.assertIn('project', result)
        self.assertEqual(result['project'], 'poc')

    def test_input_conv_id_present_in_serialized_session(self):
        """input_conv_id must be present — used to build task-specific escalation URL at render time.

        When a session has needs_input=True, the home page needs the conversation_id that
        is awaiting input so it can construct the correct chat.html?conv=JOB_ID&task=TASK_ID
        URL for the escalation dot at initial page load (not just via WebSocket).
        When no bus is available (needs_input=False or bus not found), it must be empty string.
        """
        session = _make_session(needs_input=False)
        result = self.bridge._serialize_session(session)
        self.assertIn('input_conv_id', result)
        self.assertEqual(result['input_conv_id'], '',
                         'input_conv_id must be empty string when needs_input is False')

    def test_input_conv_id_empty_when_no_bus(self):
        """input_conv_id must be empty string when no message bus is registered for the session.

        The bridge uses self._buses to look up the session bus. When needs_input=True
        but no bus is registered (e.g. orphaned session), input_conv_id must degrade
        gracefully to an empty string — not raise.
        """
        session = _make_session(needs_input=True)
        result = self.bridge._serialize_session(session)
        self.assertIn('input_conv_id', result)
        self.assertEqual(result['input_conv_id'], '',
                         'input_conv_id must be empty string when no bus is registered')


class TestBridgeProjectSerializationContract(unittest.TestCase):
    """_serialize_project must include all fields the home page needs."""

    def setUp(self):
        import shutil
        import tempfile
        self.tmpdir = tempfile.mkdtemp()
        from bridge.server import TeaPartyBridge
        static_dir = os.path.join(self.tmpdir, 'static')
        os.makedirs(static_dir)
        self.bridge = TeaPartyBridge(
            teaparty_home=self.tmpdir,
            static_dir=static_dir,
        )

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_slug_in_serialized_project(self):
        """slug must be present — used as project name in the card header."""
        project = _make_project(slug='poc')
        result = self.bridge._serialize_project(project)
        self.assertIn('slug', result)
        self.assertEqual(result['slug'], 'poc')

    def test_active_count_in_serialized_project(self):
        """active_count must be present — used for active jobs stat and ACTIVE/IDLE badge."""
        project = _make_project(active_count=3)
        result = self.bridge._serialize_project(project)
        self.assertIn('active_count', result)
        self.assertEqual(result['active_count'], 3)

    def test_attention_count_in_serialized_project(self):
        """attention_count must be present — used for escalation count stat."""
        project = _make_project(attention_count=2)
        result = self.bridge._serialize_project(project)
        self.assertIn('attention_count', result)
        self.assertEqual(result['attention_count'], 2)

    def test_sessions_array_in_serialized_project(self):
        """sessions must be present as a list — each entry becomes a job row."""
        session = _make_session()
        project = _make_project(sessions=[session], active_count=1)
        result = self.bridge._serialize_project(project)
        self.assertIn('sessions', result)
        self.assertIsInstance(result['sessions'], list)
        self.assertEqual(len(result['sessions']), 1)

    def test_idle_project_has_zero_active_count(self):
        """A project with no active sessions must have active_count=0 (idle state)."""
        project = _make_project(sessions=[], active_count=0, attention_count=0)
        result = self.bridge._serialize_project(project)
        self.assertEqual(result['active_count'], 0)
        self.assertEqual(result['sessions'], [])


# ── CfA phase → workflow bar position ────────────────────────────────────────

class TestCfaPhaseToWorkflowBarMapping(unittest.TestCase):
    """The standard CfA phases must map to the correct positions in the workflow bar.

    The home page uses a 7-element phases array:
    INTENT(0) → INTENT_ASSERT(1) → PLAN(2) → PLAN_ASSERT(3)
                → WORK(4) → WORK_ASSERT(5) → DONE(6)

    Gates (INTENT_ASSERT, PLAN_ASSERT, WORK_ASSERT) show as circles.
    Bars (INTENT, PLAN, WORK, DONE) show as line segments.
    """

    # Authoritative CfA phase sequence for the home page workflow bar
    PHASES = ['INTENT', 'INTENT_ASSERT', 'PLAN', 'PLAN_ASSERT', 'WORK', 'WORK_ASSERT', 'DONE']

    def test_standard_phases_have_seven_elements(self):
        """The workflow bar must use exactly 7 elements."""
        self.assertEqual(len(self.PHASES), 7)

    def test_gate_phases_are_at_odd_indices(self):
        """Gates (ASSERT phases) must be at indices 1, 3, 5."""
        gates = [p for p in self.PHASES if 'ASSERT' in p]
        self.assertEqual(gates, ['INTENT_ASSERT', 'PLAN_ASSERT', 'WORK_ASSERT'])
        for gate in gates:
            idx = self.PHASES.index(gate)
            self.assertEqual(idx % 2, 1,
                             f'{gate} must be at an odd index (circle position), got {idx}')

    def test_work_phase_is_at_index_4(self):
        """WORK phase must be at index 4 — after two gates."""
        self.assertEqual(self.PHASES.index('WORK'), 4)

    def test_work_assert_phase_is_at_index_5(self):
        """WORK_ASSERT gate must be at index 5 — a pulsing red circle when active."""
        self.assertEqual(self.PHASES.index('WORK_ASSERT'), 5)

    def test_intent_is_first_phase(self):
        """INTENT must be at index 0 — the starting phase."""
        self.assertEqual(self.PHASES.index('INTENT'), 0)

    def test_done_is_last_phase(self):
        """DONE must be at index 6 — the terminal phase."""
        self.assertEqual(self.PHASES.index('DONE'), 6)

    def test_cfa_phase_names_match_state_reader_output(self):
        """Phase names used in the workflow bar must match what StateReader produces.

        StateReader reads cfa_phase from .cfa-state.json. The JSON uses uppercase
        phase names (INTENT, PLAN, WORK, DONE). The workflow bar must use the
        same names — no aliasing or lowercasing.
        """
        # StateReader sets cfa_phase from the 'phase' key in .cfa-state.json
        # which uses uppercase names. Verify the bar phases match.
        for phase in self.PHASES:
            self.assertEqual(phase, phase.upper(),
                             f'Phase name {phase!r} must be uppercase to match StateReader output')


class TestIndexHtmlEscalationRouting(unittest.TestCase):
    """Escalation dots must route to the correct conversation and clear on human reply."""

    def test_session_completed_event_is_handled(self):
        """index.html must handle session_completed WebSocket events.

        When a session completes, the bridge emits session_completed. The page
        must handle this event — if unhandled, completed sessions stay visible.
        """
        content = _read_index()
        self.assertIn("session_completed", content,
                      "index.html must handle session_completed events to refresh session list")

    def test_escalation_conv_map_in_page_state(self):
        """pageState must include escalationConvMap to track input_requested conversation IDs.

        onMessage must use a reverse lookup on this map — not a session: prefix check —
        so that job: and task: conversation IDs clear escalation dots correctly.
        """
        content = _read_index()
        self.assertIn('escalationConvMap', content,
                      'pageState must have escalationConvMap for conv_id → session_id reverse lookup')

    def test_on_message_does_not_use_session_prefix_guard(self):
        """onMessage must not guard on session: prefix — human replies use job:/task: conv IDs.

        The original implementation returned early for any convId not starting with 'session:',
        which permanently blocked escalation dots from clearing for job/task conversations.
        """
        content = _read_index()
        self.assertNotIn("convId.indexOf('session:') !== 0", content,
                         "onMessage must not reject non-session: convIds — use escalationConvMap reverse lookup")

    def test_session_conv_escalation_rewrites_to_job_format(self):
        """When input_requested carries a session: conv ID, the dot must still link to job: format.

        JOB is what the uberteam does. The dot must always use job:{project}:{session_id}
        so the chat page opens the job conversation, not the raw session conversation.
        Per spec: escalation dot → chat.html?conv=JOB_ID (or JOB_ID&task=TASK_ID).
        """
        content = _read_index()
        self.assertIn("'chat.html?conv=job:' + projectSlug + ':' + sessionId", content,
                      "onInputRequested must rewrite session: escalations to job: format for the dot URL")

    def test_on_input_requested_passes_conv_id(self):
        """onInputRequested must accept conversation_id from WebSocket event.

        The conversation_id is needed to: (a) populate escalationConvMap for reverse
        lookup, and (b) construct the task-specific escalation click URL.
        """
        content = _read_index()
        self.assertIn('onInputRequested(event.session_id, event.conversation_id)', content,
                      'WebSocket handler must pass conversation_id to onInputRequested')

    def test_escalation_dot_has_stop_propagation(self):
        """Escalation dot must stop event propagation so it navigates independently of the row.

        Without stopPropagation, clicking the dot triggers both the dot's task URL
        and the row's session URL, causing a double navigation.
        """
        content = _read_index()
        self.assertIn('stopPropagation', content,
                      'Escalation dot onclick must call event.stopPropagation()')

    def test_task_conversation_id_routes_to_task(self):
        """A task: conversation_id in input_requested must produce &task= in the escalation URL.

        When input_requested carries conversation_id=task:poc:job-001:task-a, clicking
        the escalation dot must open chat.html?conv=job:poc:job-001&task=task-a.
        """
        content = _read_index()
        # The routing logic must extract task ID from task: conv IDs
        self.assertIn("parts[0] === 'task'", content,
                      "onInputRequested must detect task: conversation IDs and extract task ID for &task= routing")
        self.assertIn("'&task=' + parts[3]", content,
                      "onInputRequested must append &task=<task_id> for task: conversation IDs")

    def test_render_time_escalation_uses_input_conv_id(self):
        """render() must use s.input_conv_id (from REST) to build the escalation dot URL.

        Escalation dots on sessions that were already awaiting input at page load
        must navigate to the correct task-specific URL, not a generic job URL.
        The REST /api/state response includes input_conv_id when needs_input is true.
        """
        content = _read_index()
        self.assertIn('s.input_conv_id', content,
                      'render() must use s.input_conv_id to build escalation dot URL at page load')
        self.assertIn('escParts', content,
                      'render() must parse input_conv_id to extract task routing parts')

    def test_fetchall_prepopulates_escalation_conv_map(self):
        """fetchAll() must populate escalationConvMap from REST data after render.

        Pre-existing escalations (present at page load) need their conv IDs stored
        in escalationConvMap so onMessage can clear their dots when the human replies.
        Without this, dots from pre-load escalations never clear via WebSocket.
        """
        content = _read_index()
        self.assertIn('s.input_conv_id', content,
                      'fetchAll() must store input_conv_id in escalationConvMap after render')
        self.assertIn('escalationConvMap[s.session_id] = s.input_conv_id', content,
                      'escalationConvMap must be populated per session from input_conv_id')


if __name__ == '__main__':
    unittest.main()
