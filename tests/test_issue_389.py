"""Tests for issue #389: Dispatched subtasks navigable in chat window.

Layers:
  1. Task infra resolution — find task_dir from job_dir + dispatch_id
  2. Task bus routing — open task's messages.db and read the child's conversation
  3. Task list API — session/{id}/tasks returns task metadata with nesting
  4. Recursive nesting — subtasks within subtasks are discovered
"""
import json
import os
import shutil
import tempfile
import unittest

from orchestrator.messaging import (
    ConversationType,
    SqliteMessageBus,
    make_conversation_id,
)


def _make_tmpdir(tc: unittest.TestCase) -> str:
    tmp = tempfile.mkdtemp(prefix='teaparty-test-389-')
    tc.addCleanup(shutil.rmtree, tmp, True)
    return tmp


def _make_job(base: str, session_id: str, slug: str = 'test-job') -> str:
    """Create a minimal job directory structure. Returns job_dir."""
    job_name = f'job-{session_id}--{slug}'
    job_dir = os.path.join(base, '.teaparty', 'jobs', job_name)
    os.makedirs(os.path.join(job_dir, 'tasks'), exist_ok=True)
    with open(os.path.join(job_dir, 'job.json'), 'w') as f:
        json.dump({'job_id': f'job-{session_id}', 'status': 'active'}, f)

    # Create a messages.db with a JOB conversation
    bus = SqliteMessageBus(os.path.join(job_dir, 'messages.db'))
    conv_id = make_conversation_id(ConversationType.JOB, f'proj:{session_id}')
    bus.create_conversation(ConversationType.JOB, f'proj:{session_id}')
    bus.send(conv_id, 'human', 'Start the job')
    bus.send(conv_id, 'agent', 'Working on it')
    bus.close()
    return job_dir


def _make_task(parent_dir: str, dispatch_id: str, team: str = 'coding',
               slug: str = 'subtask', project: str = 'proj') -> str:
    """Create a minimal task directory under parent_dir/tasks/. Returns task_dir."""
    task_name = f'task-{dispatch_id}--{slug}'
    task_dir = os.path.join(parent_dir, 'tasks', task_name)
    os.makedirs(os.path.join(task_dir, 'tasks'), exist_ok=True)
    with open(os.path.join(task_dir, 'task.json'), 'w') as f:
        json.dump({
            'task_id': f'task-{dispatch_id}',
            'team': team,
            'status': 'active',
            'slug': slug,
        }, f)

    # Write PROMPT.txt for the task description
    with open(os.path.join(task_dir, 'PROMPT.txt'), 'w') as f:
        f.write(f'Implement the {slug} feature')

    # Create a messages.db with a JOB conversation (child orchestrator format)
    bus = SqliteMessageBus(os.path.join(task_dir, 'messages.db'))
    conv_id = make_conversation_id(ConversationType.JOB, f'{project}:{dispatch_id}')
    bus.create_conversation(ConversationType.JOB, f'{project}:{dispatch_id}')
    bus.send(conv_id, 'human', f'Dispatch to {team}: implement {slug}')
    bus.send(conv_id, 'agent', f'I will implement {slug} now')
    bus.send(conv_id, 'agent', f'Done with {slug}')
    bus.close()
    return task_dir


# ── Layer 1: Task infra resolution ──────────────────────────────────────────


class TestResolveJobInfra(unittest.TestCase):
    """_resolve_job_infra must find a job_dir from project_path + session_id."""

    def test_finds_job_dir_by_session_id(self):
        base = _make_tmpdir(self)
        job_dir = _make_job(base, 'abc12345')

        from bridge.server import TeaPartyBridge
        bridge = TeaPartyBridge.__new__(TeaPartyBridge)
        result = bridge._resolve_job_infra(base, 'abc12345')
        self.assertEqual(result, job_dir)

    def test_returns_none_for_missing_session(self):
        base = _make_tmpdir(self)
        _make_job(base, 'abc12345')

        from bridge.server import TeaPartyBridge
        bridge = TeaPartyBridge.__new__(TeaPartyBridge)
        result = bridge._resolve_job_infra(base, 'nonexistent')
        self.assertIsNone(result)


class TestResolveTaskInfra(unittest.TestCase):
    """_resolve_task_infra must find a task_dir from job_dir + dispatch_id."""

    def test_finds_task_dir_by_dispatch_id(self):
        base = _make_tmpdir(self)
        job_dir = _make_job(base, 'abc12345')
        task_dir = _make_task(job_dir, 'def67890', team='art')

        from bridge.server import TeaPartyBridge
        bridge = TeaPartyBridge.__new__(TeaPartyBridge)
        result = bridge._resolve_task_infra(job_dir, 'def67890')
        self.assertEqual(result, task_dir)

    def test_returns_none_for_missing_dispatch(self):
        base = _make_tmpdir(self)
        job_dir = _make_job(base, 'abc12345')

        from bridge.server import TeaPartyBridge
        bridge = TeaPartyBridge.__new__(TeaPartyBridge)
        result = bridge._resolve_task_infra(job_dir, 'nonexistent')
        self.assertIsNone(result)

    def test_finds_nested_task(self):
        """Subtask within a subtask is resolvable."""
        base = _make_tmpdir(self)
        job_dir = _make_job(base, 'abc12345')
        task_dir = _make_task(job_dir, 'def67890')
        nested_dir = _make_task(task_dir, 'ghi11111', team='writing')

        from bridge.server import TeaPartyBridge
        bridge = TeaPartyBridge.__new__(TeaPartyBridge)
        result = bridge._resolve_task_infra(task_dir, 'ghi11111')
        self.assertEqual(result, nested_dir)

    def test_finds_nested_task_from_job_root(self):
        """Nested task is resolvable from the job_dir (recursive search)."""
        base = _make_tmpdir(self)
        job_dir = _make_job(base, 'abc12345')
        task_dir = _make_task(job_dir, 'def67890')
        nested_dir = _make_task(task_dir, 'ghi11111', team='writing')

        from bridge.server import TeaPartyBridge
        bridge = TeaPartyBridge.__new__(TeaPartyBridge)
        # Search from job_dir should find the nested task recursively
        result = bridge._resolve_task_infra(job_dir, 'ghi11111')
        self.assertEqual(result, nested_dir)


# ── Layer 2: Task bus routing ────────────────────────────────────────────────


class TestTaskBusRouting(unittest.TestCase):
    """_bus_for_conversation must route task: conv IDs to the task's messages.db."""

    def _make_bridge_with_job(self):
        """Set up a bridge with a job and tasks, return (bridge, base, session_id)."""
        base = _make_tmpdir(self)
        session_id = 'abc12345'
        job_dir = _make_job(base, session_id)
        _make_task(job_dir, 'def67890', team='coding', slug='feature-x')

        from bridge.server import TeaPartyBridge
        bridge = TeaPartyBridge.__new__(TeaPartyBridge)
        bridge._buses = {}
        # Mock _lookup_project_path to return our base dir
        bridge._project_path_cache = {'proj': base}
        bridge.teaparty_home = os.path.join(base, '.teaparty')
        return bridge, base, session_id

    def test_task_conv_returns_bus(self):
        """task:{project}:{session}:{dispatch} should find the task's bus."""
        bridge, base, sid = self._make_bridge_with_job()
        conv_id = f'task:proj:{sid}:def67890'
        bus = bridge._bus_for_conversation(conv_id)
        self.assertIsNotNone(bus, 'Expected a bus for the task conversation')

    def test_task_conv_messages_from_child_bus(self):
        """Messages fetched via the task conv should come from the child's messages.db."""
        bridge, base, sid = self._make_bridge_with_job()
        conv_id = f'task:proj:{sid}:def67890'
        bus = bridge._bus_for_conversation(conv_id)
        self.assertIsNotNone(bus)

        # The child's bus has a JOB conv with id job:proj:def67890
        child_conv_id = make_conversation_id(ConversationType.JOB, 'proj:def67890')
        messages = bus.receive(child_conv_id)
        self.assertEqual(len(messages), 3)
        self.assertEqual(messages[0].sender, 'human')
        self.assertIn('Dispatch to coding', messages[0].content)

    def test_task_conv_id_remapping(self):
        """_handle_conversation_get remaps task: conv IDs to the child's job: conv ID."""
        bridge, base, sid = self._make_bridge_with_job()
        conv_id = f'task:proj:{sid}:def67890'
        bus = bridge._bus_for_conversation(conv_id)
        self.assertIsNotNone(bus)

        # Verify the remapping logic: task:proj:sessid:dispid -> job:proj:dispid
        parts = conv_id.split(':')
        project_slug = parts[1]
        dispatch_id = ':'.join(parts[3:])
        remapped = f'job:{project_slug}:{dispatch_id}'
        messages = bus.receive(remapped)
        self.assertEqual(len(messages), 3)
        # Verify the original task: conv_id does NOT exist in the bus
        direct = bus.receive(conv_id)
        self.assertEqual(len(direct), 0)


# ── Layer 3: Task list API ───────────────────────────────────────────────────


class TestTaskListEndpoint(unittest.TestCase):
    """GET /api/sessions/{session_id}/tasks returns task metadata."""

    def _make_bridge_with_tasks(self):
        base = _make_tmpdir(self)
        session_id = 'abc12345'
        job_dir = _make_job(base, session_id)
        _make_task(job_dir, 'def67890', team='coding', slug='feature-x')
        _make_task(job_dir, 'ghi11111', team='art', slug='icons')

        from bridge.server import TeaPartyBridge
        bridge = TeaPartyBridge.__new__(TeaPartyBridge)
        bridge._buses = {}
        bridge._project_path_cache = {'proj': base}
        bridge.teaparty_home = os.path.join(base, '.teaparty')
        return bridge, base, session_id

    def test_lists_tasks_for_session(self):
        bridge, base, sid = self._make_bridge_with_tasks()
        tasks = bridge._list_session_tasks(base, sid)
        self.assertEqual(len(tasks), 2)

    def test_task_includes_team(self):
        bridge, base, sid = self._make_bridge_with_tasks()
        tasks = bridge._list_session_tasks(base, sid)
        teams = {t['team'] for t in tasks}
        self.assertEqual(teams, {'coding', 'art'})

    def test_task_includes_dispatch_id(self):
        bridge, base, sid = self._make_bridge_with_tasks()
        tasks = bridge._list_session_tasks(base, sid)
        ids = {t['dispatch_id'] for t in tasks}
        self.assertEqual(ids, {'def67890', 'ghi11111'})

    def test_task_includes_description(self):
        bridge, base, sid = self._make_bridge_with_tasks()
        tasks = bridge._list_session_tasks(base, sid)
        descs = [t['task'] for t in tasks]
        self.assertTrue(any('feature-x' in d for d in descs))

    def test_task_includes_status(self):
        bridge, base, sid = self._make_bridge_with_tasks()
        tasks = bridge._list_session_tasks(base, sid)
        for t in tasks:
            self.assertIn('status', t)


# ── Layer 4: Recursive nesting ───────────────────────────────────────────────


class TestRecursiveSubtasks(unittest.TestCase):
    """Nested dispatches (subtask dispatches further subtasks) are discoverable."""

    def test_nested_subtasks_in_task_list(self):
        base = _make_tmpdir(self)
        session_id = 'abc12345'
        job_dir = _make_job(base, session_id)
        task_dir = _make_task(job_dir, 'def67890', team='coding')
        _make_task(task_dir, 'nested1', team='writing', slug='docs')

        from bridge.server import TeaPartyBridge
        bridge = TeaPartyBridge.__new__(TeaPartyBridge)
        bridge._buses = {}
        bridge._project_path_cache = {'proj': base}
        bridge.teaparty_home = os.path.join(base, '.teaparty')

        tasks = bridge._list_session_tasks(base, session_id)
        self.assertEqual(len(tasks), 1)  # One top-level task

        # The top-level task should have nested subtasks
        top_task = tasks[0]
        self.assertIn('subtasks', top_task)
        self.assertEqual(len(top_task['subtasks']), 1)
        self.assertEqual(top_task['subtasks'][0]['team'], 'writing')

    def test_deeply_nested_subtasks(self):
        """Three levels: job → task → subtask → sub-subtask."""
        base = _make_tmpdir(self)
        session_id = 'abc12345'
        job_dir = _make_job(base, session_id)
        task_dir = _make_task(job_dir, 'level1', team='coding')
        sub_dir = _make_task(task_dir, 'level2', team='art')
        _make_task(sub_dir, 'level3', team='writing')

        from bridge.server import TeaPartyBridge
        bridge = TeaPartyBridge.__new__(TeaPartyBridge)
        bridge._buses = {}
        bridge._project_path_cache = {'proj': base}
        bridge.teaparty_home = os.path.join(base, '.teaparty')

        tasks = bridge._list_session_tasks(base, session_id)
        level1 = tasks[0]
        self.assertEqual(len(level1['subtasks']), 1)
        level2 = level1['subtasks'][0]
        self.assertEqual(len(level2['subtasks']), 1)
        level3 = level2['subtasks'][0]
        self.assertEqual(level3['team'], 'writing')


# ── Layer 5: Edge cases ──────────────────────────────────────────────────────


def _write_heartbeat(path: str, status: str = 'active', pid: int = 99999) -> None:
    """Write a minimal .heartbeat JSON file."""
    import time
    with open(path, 'w') as f:
        json.dump({
            'pid': pid,
            'status': status,
            'timestamp': time.time(),
            'role': 'test',
        }, f)


def _make_direct_dispatch(job_dir: str, team: str, dispatch_id: str,
                          project: str = 'proj') -> str:
    """Create a direct-model dispatch (not under tasks/). Returns dispatch_infra."""
    dispatch_infra = os.path.join(job_dir, team, dispatch_id)
    os.makedirs(dispatch_infra, exist_ok=True)

    # Write .heartbeat
    _write_heartbeat(os.path.join(dispatch_infra, '.heartbeat'), status='completed')

    # Write .cfa-state.json
    with open(os.path.join(dispatch_infra, '.cfa-state.json'), 'w') as f:
        json.dump({'state': 'COMPLETED_WORK', 'phase': 'execution'}, f)

    # Register in .children
    children_path = os.path.join(job_dir, '.children')
    entry = {
        'heartbeat': os.path.join(dispatch_infra, '.heartbeat'),
        'team': team,
        'task_id': None,
        'status': 'active',
    }
    with open(children_path, 'a') as f:
        f.write(json.dumps(entry) + '\n')

    # Create messages.db
    bus = SqliteMessageBus(os.path.join(dispatch_infra, 'messages.db'))
    conv_id = make_conversation_id(ConversationType.JOB, f'{project}:{dispatch_id}')
    bus.create_conversation(ConversationType.JOB, f'{project}:{dispatch_id}')
    bus.send(conv_id, 'human', f'Direct dispatch to {team}')
    bus.send(conv_id, 'agent', f'Config applied by {team}')
    bus.close()
    return dispatch_infra


class TestTaskStatusHeartbeat(unittest.TestCase):
    """Task status must reflect heartbeat liveness, not just task.json."""

    def test_dead_task_shows_complete(self):
        """A task whose heartbeat is terminal should show status=complete."""
        base = _make_tmpdir(self)
        job_dir = _make_job(base, 'abc12345')
        task_dir = _make_task(job_dir, 'def67890', team='coding')
        # Write a terminal heartbeat
        _write_heartbeat(os.path.join(task_dir, '.heartbeat'), status='completed')

        from bridge.server import TeaPartyBridge
        bridge = TeaPartyBridge.__new__(TeaPartyBridge)
        bridge._buses = {}
        bridge.teaparty_home = os.path.join(base, '.teaparty')

        tasks = bridge._list_session_tasks(base, 'abc12345')
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0]['status'], 'complete')

    def test_active_task_without_heartbeat_stays_active(self):
        """A task with no heartbeat file retains its task.json status."""
        base = _make_tmpdir(self)
        job_dir = _make_job(base, 'abc12345')
        _make_task(job_dir, 'def67890', team='coding')
        # No heartbeat written — _make_task doesn't create one

        from bridge.server import TeaPartyBridge
        bridge = TeaPartyBridge.__new__(TeaPartyBridge)
        bridge._buses = {}
        bridge.teaparty_home = os.path.join(base, '.teaparty')

        tasks = bridge._list_session_tasks(base, 'abc12345')
        self.assertEqual(tasks[0]['status'], 'active')


class TestDirectModelDispatches(unittest.TestCase):
    """Direct-model dispatches (not under tasks/) must appear in task list."""

    def test_direct_dispatch_discovered(self):
        base = _make_tmpdir(self)
        job_dir = _make_job(base, 'abc12345')
        _make_direct_dispatch(job_dir, 'configuration', '20260407-120000-000001')

        from bridge.server import TeaPartyBridge
        bridge = TeaPartyBridge.__new__(TeaPartyBridge)
        bridge._buses = {}
        bridge.teaparty_home = os.path.join(base, '.teaparty')

        tasks = bridge._list_session_tasks(base, 'abc12345')
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0]['team'], 'configuration')

    def test_direct_and_worktree_dispatches_combined(self):
        """Both direct-model and worktree-model dispatches appear."""
        base = _make_tmpdir(self)
        job_dir = _make_job(base, 'abc12345')
        _make_task(job_dir, 'def67890', team='coding')
        _make_direct_dispatch(job_dir, 'configuration', '20260407-120000-000001')

        from bridge.server import TeaPartyBridge
        bridge = TeaPartyBridge.__new__(TeaPartyBridge)
        bridge._buses = {}
        bridge.teaparty_home = os.path.join(base, '.teaparty')

        tasks = bridge._list_session_tasks(base, 'abc12345')
        teams = {t['team'] for t in tasks}
        self.assertEqual(teams, {'coding', 'configuration'})


class TestDirectModelBusRouting(unittest.TestCase):
    """Clicking a direct-model dispatch must open its messages.db."""

    def test_direct_dispatch_bus_routing(self):
        base = _make_tmpdir(self)
        session_id = 'abc12345'
        job_dir = _make_job(base, session_id)
        dispatch_id = '20260407-120000-000001'
        _make_direct_dispatch(job_dir, 'configuration', dispatch_id)

        from bridge.server import TeaPartyBridge
        bridge = TeaPartyBridge.__new__(TeaPartyBridge)
        bridge._buses = {}
        bridge._project_path_cache = {'proj': base}
        bridge.teaparty_home = os.path.join(base, '.teaparty')

        conv_id = f'task:proj:{session_id}:{dispatch_id}'
        bus = bridge._bus_for_conversation(conv_id)
        self.assertIsNotNone(bus, 'Expected a bus for the direct-model dispatch')

        # Verify messages are readable via the remapped conv_id
        child_conv_id = make_conversation_id(ConversationType.JOB, f'proj:{dispatch_id}')
        messages = bus.receive(child_conv_id)
        self.assertEqual(len(messages), 2)
        self.assertIn('Direct dispatch', messages[0].content)


class TestDescriptionFallback(unittest.TestCase):
    """Task description should fall back to slug when PROMPT.txt is missing."""

    def test_no_prompt_falls_back_to_slug(self):
        base = _make_tmpdir(self)
        job_dir = _make_job(base, 'abc12345')
        task_dir = _make_task(job_dir, 'def67890', team='coding', slug='my-feature')
        # Remove PROMPT.txt
        os.remove(os.path.join(task_dir, 'PROMPT.txt'))

        from bridge.server import TeaPartyBridge
        bridge = TeaPartyBridge.__new__(TeaPartyBridge)
        bridge._buses = {}
        bridge.teaparty_home = os.path.join(base, '.teaparty')

        tasks = bridge._list_session_tasks(base, 'abc12345')
        self.assertEqual(len(tasks), 1)
        # Should fall back to slug, not empty string
        self.assertTrue(len(tasks[0]['task']) > 0, 'Task description should not be empty')
        self.assertIn('my-feature', tasks[0]['task'])


if __name__ == '__main__':
    unittest.main()
