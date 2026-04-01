"""Tests for Issue #351: Agent dispatch — independent invocations, bus-mediated messaging, routing.

Acceptance criteria (from issue):
SC1.  Proposal docs corrected: 'not running concurrently' in proposal.md;
      'transport level' (unhyphenated) and 'independent enforcement point' in routing.md
SC2.  AskTeam posts to message bus; calling agent is not blocked for recipient execution
SC3.  CfA engine supports caller with outstanding async requests (pending_count lifecycle)
SC4.  TeaParty spins up recipient agents independently from caller context
SC5.  Bus dispatcher enforces routing rules; cross-project posts rejected
SC6.  Agent spawn creates a git worktree with composed skill directory
SC7.  Agent-to-agent exchanges have stable context IDs; multi-turn via --resume
SC8.  Sub-conversations appear in the bus with the agent context type
SC9.  Liaison architecture: routing.md explicitly addresses disposition
SC10. Spec tests cover routing enforcement, context record lifecycle, skill composition
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).parent.parent
_PROPOSAL_MD = _REPO_ROOT / 'docs/proposals/agent-dispatch/proposal.md'
_ROUTING_MD = _REPO_ROOT / 'docs/proposals/agent-dispatch/references/routing.md'
_INVOCATION_MD = _REPO_ROOT / 'docs/proposals/agent-dispatch/references/invocation-model.md'


def _run(coro):
    return asyncio.run(coro)


# ── SC1: Proposal doc correctness ─────────────────────────────────────────────


class TestProposalDocCorrectness(unittest.TestCase):
    """SC1: proposal.md and routing.md must contain the required phrases."""

    def test_proposal_states_caller_is_not_running_concurrently(self):
        """agent-dispatch proposal must state the caller is not running concurrently."""
        text = _PROPOSAL_MD.read_text()
        self.assertIn(
            'not running concurrently',
            text,
            'proposal.md must explicitly state caller is not running concurrently with workers',
        )

    def test_routing_md_states_transport_level_rejection(self):
        """routing.md must describe transport-level rejection of unauthorized posts."""
        text = _ROUTING_MD.read_text()
        self.assertIn(
            'transport level',
            text,
            'routing.md must specify transport level rejection for unauthorized posts',
        )

    def test_routing_md_describes_independent_enforcement_point(self):
        """routing.md must describe the dispatcher as an independent enforcement point."""
        text = _ROUTING_MD.read_text()
        self.assertIn(
            'independent enforcement point',
            text,
            'routing.md must describe the bus dispatcher as an independent enforcement point',
        )

    def test_routing_md_addresses_liaison_disposition(self):
        """routing.md must explicitly address the disposition of liaison agents."""
        text = _ROUTING_MD.read_text()
        self.assertIn(
            'liaison',
            text.lower(),
            'routing.md must explicitly address liaison agent disposition',
        )

    def test_invocation_model_specifies_bare_flag_for_skill_suppression(self):
        """invocation-model.md must specify --bare for skill suppression, not --setting-sources."""
        text = _INVOCATION_MD.read_text()
        self.assertIn(
            '--bare',
            text,
            'invocation-model.md must specify --bare as the skill suppression mechanism',
        )


# ── SC3/SC7: Bus context records in SqliteMessageBus ─────────────────────────


def _make_bus(tmpdir: str) -> 'SqliteMessageBus':
    from orchestrator.messaging import SqliteMessageBus
    return SqliteMessageBus(os.path.join(tmpdir, 'bus.db'))


class TestBusContextRecords(unittest.TestCase):
    """SC3/SC7: SqliteMessageBus must support agent context records with pending_count."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_create_agent_context_stores_initiator_and_recipient(self):
        """create_agent_context stores initiator_agent_id and recipient_agent_id."""
        bus = _make_bus(self.tmpdir)
        bus.create_agent_context(
            context_id='ctx-1',
            initiator_agent_id='my-proj/coding/lead',
            recipient_agent_id='my-proj/coding/specialist',
        )
        ctx = bus.get_agent_context('ctx-1')
        self.assertIsNotNone(ctx)
        self.assertEqual(ctx['initiator_agent_id'], 'my-proj/coding/lead')
        self.assertEqual(ctx['recipient_agent_id'], 'my-proj/coding/specialist')

    def test_new_context_has_open_status(self):
        """Newly created agent context has status='open'."""
        bus = _make_bus(self.tmpdir)
        bus.create_agent_context('ctx-2', 'proj/a/lead', 'proj/b/worker')
        ctx = bus.get_agent_context('ctx-2')
        self.assertEqual(ctx['status'], 'open')

    def test_new_context_has_zero_pending_count(self):
        """Newly created agent context has pending_count=0."""
        bus = _make_bus(self.tmpdir)
        bus.create_agent_context('ctx-3', 'proj/a/lead', 'proj/b/worker')
        ctx = bus.get_agent_context('ctx-3')
        self.assertEqual(ctx['pending_count'], 0)

    def test_set_agent_context_session_id(self):
        """set_agent_context_session_id stores the Claude session ID."""
        bus = _make_bus(self.tmpdir)
        bus.create_agent_context('ctx-4', 'proj/a/lead', 'proj/b/worker')
        bus.set_agent_context_session_id('ctx-4', 'sess-abc123')
        ctx = bus.get_agent_context('ctx-4')
        self.assertEqual(ctx['session_id'], 'sess-abc123')

    def test_increment_pending_count(self):
        """increment_pending_count increases count by 1 atomically."""
        bus = _make_bus(self.tmpdir)
        bus.create_agent_context('ctx-5', 'proj/a/lead', 'proj/b/worker')
        bus.increment_pending_count('ctx-5')
        bus.increment_pending_count('ctx-5')
        ctx = bus.get_agent_context('ctx-5')
        self.assertEqual(ctx['pending_count'], 2)

    def test_decrement_pending_count_returns_new_count(self):
        """decrement_pending_count decrements and returns the new count."""
        bus = _make_bus(self.tmpdir)
        bus.create_agent_context('ctx-6', 'proj/a/lead', 'proj/b/worker')
        bus.increment_pending_count('ctx-6')
        bus.increment_pending_count('ctx-6')
        new_count = bus.decrement_pending_count('ctx-6')
        self.assertEqual(new_count, 1)

    def test_decrement_to_zero_triggers_reinvocation_flag(self):
        """decrement_pending_count returns 0 when count reaches zero (fan-in complete)."""
        bus = _make_bus(self.tmpdir)
        bus.create_agent_context('ctx-7', 'proj/a/lead', 'proj/b/worker')
        bus.increment_pending_count('ctx-7')
        new_count = bus.decrement_pending_count('ctx-7')
        self.assertEqual(new_count, 0, 'Decrement to zero signals fan-in completion')

    def test_close_agent_context_sets_status_closed(self):
        """close_agent_context transitions status to 'closed'."""
        bus = _make_bus(self.tmpdir)
        bus.create_agent_context('ctx-8', 'proj/a/lead', 'proj/b/worker')
        bus.close_agent_context('ctx-8')
        ctx = bus.get_agent_context('ctx-8')
        self.assertEqual(ctx['status'], 'closed')

    def test_get_agent_context_returns_none_for_unknown(self):
        """get_agent_context returns None for an unknown context_id."""
        bus = _make_bus(self.tmpdir)
        self.assertIsNone(bus.get_agent_context('nonexistent'))

    def test_open_agent_contexts_returns_only_open(self):
        """open_agent_contexts() returns only contexts with status='open'."""
        bus = _make_bus(self.tmpdir)
        bus.create_agent_context('ctx-open', 'proj/a/lead', 'proj/b/w1')
        bus.create_agent_context('ctx-closed', 'proj/a/lead', 'proj/b/w2')
        bus.close_agent_context('ctx-closed')
        open_ctxs = bus.open_agent_contexts()
        context_ids = {c['context_id'] for c in open_ctxs}
        self.assertIn('ctx-open', context_ids)
        self.assertNotIn('ctx-closed', context_ids)

    def test_two_record_atomicity_increment_and_create(self):
        """increment_pending_count for parent and create_agent_context for child are atomic."""
        # The bus must support creating a sub-context AND incrementing its parent's
        # pending_count in a single atomic write so a crash between them is impossible.
        bus = _make_bus(self.tmpdir)
        bus.create_agent_context('parent-ctx', 'proj/lead', 'proj/coding/lead')
        bus.create_agent_context_and_increment_parent(
            context_id='child-ctx',
            initiator_agent_id='proj/coding/lead',
            recipient_agent_id='proj/coding/worker',
            parent_context_id='parent-ctx',
        )
        parent = bus.get_agent_context('parent-ctx')
        child = bus.get_agent_context('child-ctx')
        self.assertEqual(parent['pending_count'], 1)
        self.assertIsNotNone(child)

    def test_create_context_and_increment_parent_is_all_or_nothing(self):
        """If parent context does not exist, create_agent_context_and_increment_parent raises."""
        bus = _make_bus(self.tmpdir)
        with self.assertRaises(Exception):
            bus.create_agent_context_and_increment_parent(
                context_id='orphan-child',
                initiator_agent_id='proj/coding/lead',
                recipient_agent_id='proj/coding/worker',
                parent_context_id='does-not-exist',
            )
        # The child context must not have been created either
        self.assertIsNone(bus.get_agent_context('orphan-child'))


# ── SC5: Routing table and bus dispatcher ─────────────────────────────────────


def _make_workgroup(name: str, lead_role: str, worker_roles: list[str]) -> dict:
    """Build a minimal workgroup dict for routing derivation tests."""
    agents = [{'role': lead_role}] + [{'role': r} for r in worker_roles]
    return {'name': name, 'lead': lead_role, 'agents': agents}


class TestRoutingTableDerivation(unittest.TestCase):
    """SC5: RoutingTable.from_workgroups() must derive correct routing pairs."""

    def test_within_workgroup_all_agents_can_reach_each_other(self):
        """Within a workgroup, every agent pair (both directions) must be in the table."""
        from orchestrator.bus_dispatcher import RoutingTable

        wg = _make_workgroup('coding', 'team-lead', ['specialist-a', 'specialist-b'])
        table = RoutingTable.from_workgroups([wg], project_name='my-proj')

        # lead → specialist-a, specialist-a → lead
        self.assertTrue(table.allows('my-proj/coding/team-lead', 'my-proj/coding/specialist-a'))
        self.assertTrue(table.allows('my-proj/coding/specialist-a', 'my-proj/coding/team-lead'))
        # lead → specialist-b, specialist-b → lead
        self.assertTrue(table.allows('my-proj/coding/team-lead', 'my-proj/coding/specialist-b'))
        self.assertTrue(table.allows('my-proj/coding/specialist-b', 'my-proj/coding/team-lead'))
        # specialist-a → specialist-b (peers within workgroup)
        self.assertTrue(table.allows('my-proj/coding/specialist-a', 'my-proj/coding/specialist-b'))

    def test_workgroup_lead_can_reach_project_lead(self):
        """Workgroup lead must have a route to the project lead (cross-workgroup)."""
        from orchestrator.bus_dispatcher import RoutingTable

        wg = _make_workgroup('coding', 'team-lead', ['specialist'])
        table = RoutingTable.from_workgroups([wg], project_name='my-proj')

        self.assertTrue(table.allows('my-proj/coding/team-lead', 'my-proj/lead'))
        self.assertTrue(table.allows('my-proj/lead', 'my-proj/coding/team-lead'))

    def test_workers_do_not_have_route_to_project_lead_directly(self):
        """Workers must not have a direct route to the project lead (only lead does)."""
        from orchestrator.bus_dispatcher import RoutingTable

        wg = _make_workgroup('coding', 'team-lead', ['specialist'])
        table = RoutingTable.from_workgroups([wg], project_name='my-proj')

        self.assertFalse(
            table.allows('my-proj/coding/specialist', 'my-proj/lead'),
            'Specialists must not have a direct route to the project lead',
        )

    def test_project_lead_has_route_to_om(self):
        """Project lead must have a route to the OM (cross-project gateway)."""
        from orchestrator.bus_dispatcher import RoutingTable

        wg = _make_workgroup('coding', 'team-lead', ['specialist'])
        table = RoutingTable.from_workgroups([wg], project_name='my-proj')

        self.assertTrue(table.allows('my-proj/lead', 'om'))
        self.assertTrue(table.allows('om', 'my-proj/lead'))

    def test_workers_have_no_route_to_om(self):
        """Workers must not have a direct route to the OM."""
        from orchestrator.bus_dispatcher import RoutingTable

        wg = _make_workgroup('coding', 'team-lead', ['specialist'])
        table = RoutingTable.from_workgroups([wg], project_name='my-proj')

        self.assertFalse(
            table.allows('my-proj/coding/specialist', 'om'),
            'Workers must not have a direct route to the OM',
        )

    def test_cross_workgroup_workers_cannot_reach_each_other_directly(self):
        """Workers from different workgroups must not have direct routes."""
        from orchestrator.bus_dispatcher import RoutingTable

        wg1 = _make_workgroup('coding', 'coding-lead', ['coder'])
        wg2 = _make_workgroup('config', 'config-lead', ['configurer'])
        table = RoutingTable.from_workgroups([wg1, wg2], project_name='my-proj')

        self.assertFalse(
            table.allows('my-proj/coding/coder', 'my-proj/config/configurer'),
            'Workers from different workgroups must not have direct routes',
        )

    def test_matrixed_workgroup_different_projects_no_cross_project_route(self):
        """Same workgroup definition in two projects must produce no cross-project routes."""
        from orchestrator.bus_dispatcher import RoutingTable

        coding_wg = _make_workgroup('coding', 'team-lead', ['specialist'])
        # Same workgroup definition, two projects
        table_a = RoutingTable.from_workgroups([coding_wg], project_name='proj-a')
        table_b = RoutingTable.from_workgroups([coding_wg], project_name='proj-b')

        # Merge — combined table (as would happen in a multi-project session)
        combined = RoutingTable.merge([table_a, table_b])

        self.assertFalse(
            combined.allows('proj-a/coding/team-lead', 'proj-b/coding/team-lead'),
            'Matrixed workgroup must not create cross-project routes',
        )
        self.assertFalse(
            combined.allows('proj-a/coding/specialist', 'proj-b/coding/specialist'),
            'Shared workgroup membership must not create cross-project routes between workers',
        )

    def test_routing_table_contains_project_scoped_agent_ids(self):
        """All agent IDs in the routing table must be project-scoped ({project}/{wg}/{role})."""
        from orchestrator.bus_dispatcher import RoutingTable

        wg = _make_workgroup('coding', 'team-lead', ['specialist'])
        table = RoutingTable.from_workgroups([wg], project_name='my-proj')

        for sender, recipient in table.pairs():
            # Special IDs: 'om' and '{project}/lead' are valid exceptions
            if sender not in ('om',) and not sender.endswith('/lead'):
                parts = sender.split('/')
                self.assertEqual(
                    len(parts), 3,
                    f'agent_id {sender!r} must be project-scoped (project/wg/role)',
                )


class TestBusDispatcher(unittest.TestCase):
    """SC5: BusDispatcher must enforce routing rules, raising RoutingError for violations."""

    def _make_table_and_dispatcher(self):
        from orchestrator.bus_dispatcher import RoutingTable, BusDispatcher
        wg = _make_workgroup('coding', 'team-lead', ['specialist'])
        table = RoutingTable.from_workgroups([wg], project_name='my-proj')
        return table, BusDispatcher(table)

    def test_dispatcher_allows_valid_route(self):
        """BusDispatcher.authorize() does not raise for a permitted sender/recipient pair."""
        from orchestrator.bus_dispatcher import RoutingError
        _, dispatcher = self._make_table_and_dispatcher()
        # Should not raise
        dispatcher.authorize('my-proj/coding/team-lead', 'my-proj/coding/specialist')

    def test_dispatcher_raises_routing_error_for_invalid_route(self):
        """BusDispatcher.authorize() raises RoutingError for a disallowed pair."""
        from orchestrator.bus_dispatcher import RoutingError
        _, dispatcher = self._make_table_and_dispatcher()
        with self.assertRaises(RoutingError):
            dispatcher.authorize('my-proj/coding/specialist', 'om')

    def test_routing_error_is_exception_subclass(self):
        """RoutingError must be an Exception subclass."""
        from orchestrator.bus_dispatcher import RoutingError
        self.assertTrue(issubclass(RoutingError, Exception))

    def test_dispatcher_allows_om_to_project_lead(self):
        """OM → project lead is always a valid route."""
        _, dispatcher = self._make_table_and_dispatcher()
        dispatcher.authorize('om', 'my-proj/lead')  # Must not raise

    def test_dispatcher_rejects_cross_project_without_om(self):
        """Cross-project post without OM mediation must be rejected."""
        from orchestrator.bus_dispatcher import RoutingTable, BusDispatcher, RoutingError

        wg = _make_workgroup('coding', 'team-lead', ['specialist'])
        table_a = RoutingTable.from_workgroups([wg], project_name='proj-a')
        table_b = RoutingTable.from_workgroups([wg], project_name='proj-b')
        combined = RoutingTable.merge([table_a, table_b])
        dispatcher = BusDispatcher(combined)

        with self.assertRaises(RoutingError):
            dispatcher.authorize('proj-a/coding/team-lead', 'proj-b/coding/team-lead')


# ── SC6: Worktree and skill composition ────────────────────────────────────────


class TestSkillComposition(unittest.TestCase):
    """SC6: compose_skills() must layer common + role + project skills in the worktree."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _make_skill(self, skills_dir: str, skill_name: str) -> str:
        """Create a minimal skill directory with SKILL.md."""
        skill_dir = os.path.join(skills_dir, skill_name)
        os.makedirs(skill_dir, exist_ok=True)
        with open(os.path.join(skill_dir, 'SKILL.md'), 'w') as f:
            f.write(f'# {skill_name}\n')
        return skill_dir

    def test_common_skills_appear_in_composed_directory(self):
        """Skills from common/ must appear in the worktree's .claude/skills/."""
        from orchestrator.agent_spawner import compose_skills

        teaparty_home = os.path.join(self.tmpdir, 'tp_home')
        os.makedirs(os.path.join(teaparty_home, 'skills', 'common'))
        self._make_skill(os.path.join(teaparty_home, 'skills', 'common'), 'fix-issue')

        worktree = os.path.join(self.tmpdir, 'agent-wt')
        os.makedirs(worktree)

        compose_skills(worktree, teaparty_home, role='specialist')

        skills_dir = os.path.join(worktree, '.claude', 'skills')
        self.assertIn('fix-issue', os.listdir(skills_dir))

    def test_role_skills_appear_in_composed_directory(self):
        """Skills from roles/{role}/ must appear in the worktree's .claude/skills/."""
        from orchestrator.agent_spawner import compose_skills

        teaparty_home = os.path.join(self.tmpdir, 'tp_home')
        os.makedirs(os.path.join(teaparty_home, 'skills', 'roles', 'coder'))
        self._make_skill(os.path.join(teaparty_home, 'skills', 'roles', 'coder'), 'code-review')

        worktree = os.path.join(self.tmpdir, 'agent-wt')
        os.makedirs(worktree)

        compose_skills(worktree, teaparty_home, role='coder')

        skills_dir = os.path.join(worktree, '.claude', 'skills')
        self.assertIn('code-review', os.listdir(skills_dir))

    def test_project_skills_override_common_on_name_collision(self):
        """Project skills with the same name as common skills must shadow them."""
        from orchestrator.agent_spawner import compose_skills

        teaparty_home = os.path.join(self.tmpdir, 'tp_home')
        # Common version of 'audit' skill
        os.makedirs(os.path.join(teaparty_home, 'skills', 'common'))
        self._make_skill(os.path.join(teaparty_home, 'skills', 'common'), 'audit')

        # Project version of 'audit' skill (should win)
        project_dir = os.path.join(self.tmpdir, 'my-project')
        os.makedirs(os.path.join(project_dir, '.claude', 'skills'))
        project_skill = self._make_skill(
            os.path.join(project_dir, '.claude', 'skills'), 'audit',
        )

        worktree = os.path.join(self.tmpdir, 'agent-wt')
        os.makedirs(worktree)

        compose_skills(worktree, teaparty_home, role='specialist', project_dir=project_dir)

        skills_dir = os.path.join(worktree, '.claude', 'skills')
        self.assertIn('audit', os.listdir(skills_dir))
        # The symlink (or copy) must point to the project version, not the common one
        audit_entry = os.path.join(skills_dir, 'audit')
        if os.path.islink(audit_entry):
            link_target = os.readlink(audit_entry)
            self.assertIn(
                'my-project', link_target,
                'Project skill must override common skill on name collision',
            )

    def test_skills_dir_created_even_with_no_skills(self):
        """compose_skills() must create .claude/skills/ even when no skills exist."""
        from orchestrator.agent_spawner import compose_skills

        teaparty_home = os.path.join(self.tmpdir, 'tp_home')
        os.makedirs(teaparty_home)

        worktree = os.path.join(self.tmpdir, 'agent-wt')
        os.makedirs(worktree)

        compose_skills(worktree, teaparty_home, role='specialist')

        self.assertTrue(
            os.path.isdir(os.path.join(worktree, '.claude', 'skills')),
            'compose_skills must create .claude/skills/ directory',
        )

    def test_role_not_found_falls_back_to_common_only(self):
        """If no role-specific skills exist, compose_skills falls back to common only."""
        from orchestrator.agent_spawner import compose_skills

        teaparty_home = os.path.join(self.tmpdir, 'tp_home')
        os.makedirs(os.path.join(teaparty_home, 'skills', 'common'))
        self._make_skill(os.path.join(teaparty_home, 'skills', 'common'), 'research')

        worktree = os.path.join(self.tmpdir, 'agent-wt')
        os.makedirs(worktree)

        # Role that doesn't exist in skills/roles/
        compose_skills(worktree, teaparty_home, role='nonexistent-role')

        skills_dir = os.path.join(worktree, '.claude', 'skills')
        self.assertIn('research', os.listdir(skills_dir), 'Common skills must still appear')


# ── SC4/SC7: BusEventListener socket server ────────────────────────────────────


class TestBusEventListenerLifecycle(unittest.TestCase):
    """SC4/SC7: BusEventListener must start Send/Reply sockets and return their paths."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_start_returns_two_socket_paths(self):
        """BusEventListener.start() returns (send_socket_path, reply_socket_path)."""
        from orchestrator.bus_event_listener import BusEventListener

        bus_db = os.path.join(self.tmpdir, 'bus.db')

        async def run():
            listener = BusEventListener(bus_db_path=bus_db)
            send_path, reply_path = await listener.start()
            try:
                return os.path.exists(send_path), os.path.exists(reply_path)
            finally:
                await listener.stop()

        send_exists, reply_exists = _run(run())
        self.assertTrue(send_exists, 'send socket path must exist after start()')
        self.assertTrue(reply_exists, 'reply socket path must exist after start()')

    def test_stop_removes_socket_files(self):
        """BusEventListener.stop() must clean up socket files."""
        from orchestrator.bus_event_listener import BusEventListener

        bus_db = os.path.join(self.tmpdir, 'bus.db')

        async def run():
            listener = BusEventListener(bus_db_path=bus_db)
            send_path, reply_path = await listener.start()
            await listener.stop()
            return os.path.exists(send_path), os.path.exists(reply_path)

        send_exists, reply_exists = _run(run())
        self.assertFalse(send_exists, 'send socket must be removed after stop()')
        self.assertFalse(reply_exists, 'reply socket must be removed after stop()')

    def test_send_request_creates_agent_context_record(self):
        """A Send request to BusEventListener creates a bus context record."""
        from orchestrator.bus_event_listener import BusEventListener
        from orchestrator.messaging import SqliteMessageBus

        bus_db = os.path.join(self.tmpdir, 'bus.db')
        spawned = {}

        async def mock_spawn_fn(member, composite, context_id):
            spawned['member'] = member
            return 'mock-session-id'

        async def run():
            listener = BusEventListener(bus_db_path=bus_db, spawn_fn=mock_spawn_fn)
            send_path, _reply_path = await listener.start()
            try:
                reader, writer = await asyncio.open_unix_connection(send_path)
                try:
                    req = json.dumps({
                        'type': 'send',
                        'member': 'coding-specialist',
                        'composite': '## Task\ndo the thing\n\n## Context\nstate',
                        'context_id': '',
                    })
                    writer.write(req.encode() + b'\n')
                    await writer.drain()
                    await reader.readline()
                finally:
                    writer.close()
                    await writer.wait_closed()
            finally:
                await listener.stop()

        _run(run())

        bus = SqliteMessageBus(bus_db)
        open_ctxs = bus.open_agent_contexts()
        self.assertEqual(len(open_ctxs), 1, 'One agent context must be created per Send call')
        ctx = open_ctxs[0]
        self.assertEqual(ctx['recipient_agent_id'], 'coding-specialist')

    def test_reply_request_closes_agent_context(self):
        """A Reply request to BusEventListener closes the agent context."""
        from orchestrator.bus_event_listener import BusEventListener
        from orchestrator.messaging import SqliteMessageBus

        bus_db = os.path.join(self.tmpdir, 'bus.db')
        bus = SqliteMessageBus(bus_db)

        # Pre-create a context with caller session registered
        bus.create_agent_context('ctx-reply-test', 'proj/lead', 'proj/coding/worker')
        bus.set_agent_context_session_id('ctx-reply-test', 'lead-session-id')
        bus.close()

        reinvoked = {}

        async def mock_reinvoke_fn(context_id, session_id, composite):
            reinvoked['context_id'] = context_id
            reinvoked['session_id'] = session_id

        async def run():
            listener = BusEventListener(
                bus_db_path=bus_db,
                reinvoke_fn=mock_reinvoke_fn,
                current_context_id='ctx-reply-test',
            )
            _send_path, reply_path = await listener.start()
            try:
                reader, writer = await asyncio.open_unix_connection(reply_path)
                try:
                    req = json.dumps({'type': 'reply', 'message': 'Task complete.'})
                    writer.write(req.encode() + b'\n')
                    await writer.drain()
                    await reader.readline()
                finally:
                    writer.close()
                    await writer.wait_closed()
            finally:
                await listener.stop()

        _run(run())

        bus2 = SqliteMessageBus(bus_db)
        ctx = bus2.get_agent_context('ctx-reply-test')
        self.assertEqual(ctx['status'], 'closed', 'Reply must close the agent context')

    def test_send_handler_posts_composite_to_spawn_fn(self):
        """BusEventListener passes the composite (not raw message) to the spawn function."""
        from orchestrator.bus_event_listener import BusEventListener

        bus_db = os.path.join(self.tmpdir, 'bus.db')
        spawned = {}

        async def mock_spawn_fn(member, composite, context_id):
            spawned['composite'] = composite
            return 'sess-id'

        composite_sent = '## Task\nwrite tests\n\n## Context\ncurrent state'

        async def run():
            listener = BusEventListener(bus_db_path=bus_db, spawn_fn=mock_spawn_fn)
            send_path, _ = await listener.start()
            try:
                reader, writer = await asyncio.open_unix_connection(send_path)
                try:
                    req = json.dumps({
                        'type': 'send',
                        'member': 'coding-specialist',
                        'composite': composite_sent,
                        'context_id': '',
                    })
                    writer.write(req.encode() + b'\n')
                    await writer.drain()
                    await reader.readline()
                finally:
                    writer.close()
                    await writer.wait_closed()
            finally:
                await listener.stop()

        _run(run())

        self.assertEqual(
            spawned.get('composite'), composite_sent,
            'spawn_fn must receive the composite as-is',
        )


# ── SC2: Non-blocking dispatch (caller gets response before recipient runs) ────


class TestNonBlockingDispatch(unittest.TestCase):
    """SC2: The Send socket must return immediately; caller is not blocked on recipient."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_send_returns_before_spawn_completes(self):
        """Send socket responds before the spawned agent finishes its work."""
        import time
        from orchestrator.bus_event_listener import BusEventListener

        bus_db = os.path.join(self.tmpdir, 'bus.db')
        spawn_completed = []

        async def slow_spawn_fn(member, composite, context_id):
            # Simulate slow agent — 50ms delay
            await asyncio.sleep(0.05)
            spawn_completed.append(True)
            return 'sess-slow'

        result = {}

        async def run():
            listener = BusEventListener(bus_db_path=bus_db, spawn_fn=slow_spawn_fn)
            send_path, _ = await listener.start()
            try:
                reader, writer = await asyncio.open_unix_connection(send_path)
                try:
                    req = json.dumps({
                        'type': 'send', 'member': 'worker',
                        'composite': '## Task\nrun\n\n## Context\n', 'context_id': '',
                    })
                    writer.write(req.encode() + b'\n')
                    await writer.drain()
                    t0 = time.monotonic()
                    await reader.readline()
                    result['elapsed'] = time.monotonic() - t0
                    result['completed_at_response'] = list(spawn_completed)
                finally:
                    writer.close()
                    await writer.wait_closed()
            finally:
                await listener.stop()

        _run(run())

        # The response must arrive before the slow spawn completes (< 40ms)
        self.assertLess(
            result['elapsed'], 0.04,
            f"Send must return immediately; got {result['elapsed']*1000:.1f}ms — "
            'caller is blocked on recipient',
        )
        self.assertEqual(
            result['completed_at_response'], [],
            'spawn_fn must not have completed by the time Send returns',
        )


# ── SC8: Sub-conversations written to bus with agent context type ─────────────


class TestSubConversationNavigation(unittest.TestCase):
    """SC8: Agent-to-agent exchanges must be addressable via bus conversation IDs."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_agent_context_id_follows_stable_format(self):
        """Context ID for agent-to-agent exchange must follow 'agent:{init}:{recip}:{uuid}' format."""
        import re
        from orchestrator.bus_event_listener import make_agent_context_id

        ctx_id = make_agent_context_id('proj/coding/lead', 'proj/coding/worker')
        pattern = r'^agent:[^:]+:[^:]+:[0-9a-f-]{36}$'
        self.assertRegex(
            ctx_id, pattern,
            f'context_id {ctx_id!r} must match agent:{{init}}:{{recip}}:{{uuid4}}',
        )

    def test_two_sends_to_same_recipient_produce_distinct_context_ids(self):
        """Two Send calls to the same recipient must produce distinct context IDs."""
        from orchestrator.bus_event_listener import make_agent_context_id

        ctx1 = make_agent_context_id('proj/coding/lead', 'proj/coding/worker')
        ctx2 = make_agent_context_id('proj/coding/lead', 'proj/coding/worker')
        self.assertNotEqual(ctx1, ctx2, 'Parallel sends must produce distinct context IDs')


# ── SC9: Liaison architecture disposition ─────────────────────────────────────


class TestLiaisonDisposition(unittest.TestCase):
    """SC9: routing.md must explicitly address liaison agent disposition."""

    def test_routing_md_names_liaison_functions_and_their_disposition(self):
        """routing.md must name the liaison functions and explain the supersession."""
        text = _ROUTING_MD.read_text()
        self.assertIn(
            '_make_project_liaison_def',
            text,
            'routing.md must name the existing liaison function being superseded',
        )
        self.assertIn(
            'supersedes',
            text.lower(),
            'routing.md must state that the routing model supersedes the liaison architecture',
        )

    def test_routing_md_describes_removal_condition(self):
        """routing.md must state when the liaison definitions will be removed."""
        text = _ROUTING_MD.read_text()
        self.assertRegex(
            text,
            r'(?i)removed|retire|supersed',
            'routing.md must state when liaison definitions are removed',
        )


# ── SC10: engine.py wires Send/Reply sockets ──────────────────────────────────


class TestEngineMcpEnvWiring(unittest.TestCase):
    """SC10: engine.py must set SEND_SOCKET and REPLY_SOCKET in mcp_env."""

    def test_engine_sets_send_socket_env_var(self):
        """The engine must set SEND_SOCKET in the MCP env so send_handler can connect."""
        import ast

        engine_src = (_REPO_ROOT / 'orchestrator' / 'engine.py').read_text()
        self.assertIn(
            'SEND_SOCKET',
            engine_src,
            'engine.py must set SEND_SOCKET in mcp_env',
        )

    def test_engine_sets_reply_socket_env_var(self):
        """The engine must set REPLY_SOCKET in the MCP env so reply_handler can connect."""
        engine_src = (_REPO_ROOT / 'orchestrator' / 'engine.py').read_text()
        self.assertIn(
            'REPLY_SOCKET',
            engine_src,
            'engine.py must set REPLY_SOCKET in mcp_env',
        )

    def test_engine_imports_bus_event_listener(self):
        """engine.py must import or reference BusEventListener."""
        engine_src = (_REPO_ROOT / 'orchestrator' / 'engine.py').read_text()
        self.assertIn(
            'BusEventListener',
            engine_src,
            'engine.py must reference BusEventListener',
        )


if __name__ == '__main__':
    unittest.main()
