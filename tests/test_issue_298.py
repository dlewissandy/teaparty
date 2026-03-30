"""Tests for issue #298: bridge/poller.py — StateReader polling loop, state diffing,
WebSocket event push.

Acceptance criteria:
1. StatePoller is importable from bridge.poller
2. CfA state transition → state_changed event emitted
3. Heartbeat status change → heartbeat event emitted; no event when status unchanged
4. Session reaches COMPLETED_WORK or WITHDRAWN → session_completed emitted + bus closed
5. New active session → bus_factory called to open connection
6. Completed session → bus connection removed from registry
7. No event emitted when nothing changes between polls
"""
import asyncio
import unittest
from dataclasses import dataclass, field
from unittest.mock import MagicMock, call


# ── Test helpers ──────────────────────────────────────────────────────────────

@dataclass
class _FakeSession:
    """Minimal SessionState stand-in for poller tests."""
    session_id: str
    cfa_state: str = 'PLAN_EXEC'
    cfa_phase: str = 'planning'
    heartbeat_status: str = 'alive'
    status: str = 'active'
    infra_dir: str = '/fake/infra'


@dataclass
class _FakeProject:
    """Minimal ProjectState stand-in."""
    slug: str = 'test-project'
    sessions: list = field(default_factory=list)


class _FakeStateReader:
    """StateReader stub that returns a preset snapshot on each reload() call."""

    def __init__(self, snapshots: list[list[_FakeProject]]):
        self._snapshots = iter(snapshots)
        self._last: list[_FakeProject] = []

    def reload(self) -> list[_FakeProject]:
        try:
            self._last = next(self._snapshots)
        except StopIteration:
            pass  # repeat last snapshot
        return self._last


def _make_session(**kwargs) -> _FakeSession:
    return _FakeSession(**kwargs)


def _make_reader(*snapshot_lists) -> _FakeStateReader:
    """Create a reader whose reload() returns each snapshot in turn."""
    return _FakeStateReader(list(snapshot_lists))


async def _collect_events(poller, n_polls: int) -> list[dict]:
    """Run n_polls poll cycles and return all events broadcast."""
    events = []

    async def capture(event: dict) -> None:
        events.append(event)

    poller._broadcast = capture
    for _ in range(n_polls):
        await poller.poll_once()
    return events


# ── Import test ───────────────────────────────────────────────────────────────

class TestStatePollerImport(unittest.TestCase):
    """StatePoller must be importable from bridge.poller."""

    def test_state_poller_is_importable(self):
        from bridge.poller import StatePoller  # noqa: F401

    def test_state_poller_has_poll_once_method(self):
        from bridge.poller import StatePoller
        self.assertTrue(
            callable(getattr(StatePoller, 'poll_once', None)),
            'StatePoller must expose a poll_once() coroutine method',
        )

    def test_state_poller_has_run_method(self):
        from bridge.poller import StatePoller
        self.assertTrue(
            callable(getattr(StatePoller, 'run', None)),
            'StatePoller must expose a run() coroutine method',
        )


# ── CfA state transition ──────────────────────────────────────────────────────

class TestCfaStateTransitionEvents(unittest.TestCase):
    """state_changed events emitted on CfA state or phase transitions."""

    def _make_poller(self, reader):
        from bridge.poller import StatePoller
        async def noop(event): pass
        return StatePoller(reader, noop)

    def test_state_changed_event_emitted_on_cfa_state_transition(self):
        """A change in session.cfa_state must produce a state_changed event."""
        s1 = _make_session(session_id='s1', cfa_state='PLAN_EXEC', cfa_phase='planning')
        s2 = _make_session(session_id='s1', cfa_state='WORK_EXEC', cfa_phase='execution')

        reader = _make_reader(
            [_FakeProject(sessions=[s1])],
            [_FakeProject(sessions=[s2])],
        )
        poller = self._make_poller(reader)
        events = asyncio.run(_collect_events(poller, 2))

        state_changed = [e for e in events if e['type'] == 'state_changed']
        self.assertEqual(len(state_changed), 1)
        self.assertEqual(state_changed[0]['session_id'], 's1')
        self.assertEqual(state_changed[0]['state'], 'WORK_EXEC')
        self.assertEqual(state_changed[0]['phase'], 'execution')

    def test_no_state_changed_event_when_cfa_state_unchanged(self):
        """No state_changed event when cfa_state and cfa_phase are the same across polls."""
        s = _make_session(session_id='s1', cfa_state='PLAN_EXEC', cfa_phase='planning')

        reader = _make_reader(
            [_FakeProject(sessions=[s])],
            [_FakeProject(sessions=[s])],
        )
        poller = self._make_poller(reader)
        events = asyncio.run(_collect_events(poller, 2))

        state_changed = [e for e in events if e['type'] == 'state_changed']
        self.assertEqual(len(state_changed), 0)

    def test_no_state_changed_event_on_first_poll(self):
        """First poll establishes baseline — no events emitted until a transition occurs."""
        s = _make_session(session_id='s1', cfa_state='PLAN_EXEC')

        reader = _make_reader([_FakeProject(sessions=[s])])
        poller = self._make_poller(reader)
        events = asyncio.run(_collect_events(poller, 1))

        state_changed = [e for e in events if e['type'] == 'state_changed']
        self.assertEqual(len(state_changed), 0)

    def test_state_changed_event_contains_required_fields(self):
        """state_changed event must have type, session_id, phase, state fields."""
        s1 = _make_session(session_id='s1', cfa_state='PLAN_EXEC', cfa_phase='planning')
        s2 = _make_session(session_id='s1', cfa_state='WORK_EXEC', cfa_phase='execution')

        reader = _make_reader(
            [_FakeProject(sessions=[s1])],
            [_FakeProject(sessions=[s2])],
        )
        poller = self._make_poller(reader)
        events = asyncio.run(_collect_events(poller, 2))

        state_changed = [e for e in events if e['type'] == 'state_changed']
        self.assertEqual(len(state_changed), 1)
        event = state_changed[0]
        for key in ('type', 'session_id', 'phase', 'state'):
            self.assertIn(key, event, f'state_changed event missing field: {key}')


# ── Heartbeat transition ──────────────────────────────────────────────────────

class TestHeartbeatTransitionEvents(unittest.TestCase):
    """heartbeat events emitted only on alive/stale/dead status transitions."""

    def _make_poller(self, reader):
        from bridge.poller import StatePoller
        async def noop(event): pass
        return StatePoller(reader, noop)

    def test_heartbeat_event_emitted_on_status_change_alive_to_stale(self):
        """Transition from alive → stale must produce a heartbeat event."""
        s1 = _make_session(session_id='s1', heartbeat_status='alive')
        s2 = _make_session(session_id='s1', heartbeat_status='stale')

        reader = _make_reader(
            [_FakeProject(sessions=[s1])],
            [_FakeProject(sessions=[s2])],
        )
        poller = self._make_poller(reader)
        events = asyncio.run(_collect_events(poller, 2))

        hb_events = [e for e in events if e['type'] == 'heartbeat']
        self.assertEqual(len(hb_events), 1)
        self.assertEqual(hb_events[0]['session_id'], 's1')
        self.assertEqual(hb_events[0]['status'], 'stale')

    def test_heartbeat_event_emitted_on_status_change_stale_to_dead(self):
        """Transition from stale → dead must produce a heartbeat event."""
        s1 = _make_session(session_id='s1', heartbeat_status='stale')
        s2 = _make_session(session_id='s1', heartbeat_status='dead')

        reader = _make_reader(
            [_FakeProject(sessions=[s1])],
            [_FakeProject(sessions=[s2])],
        )
        poller = self._make_poller(reader)
        events = asyncio.run(_collect_events(poller, 2))

        hb_events = [e for e in events if e['type'] == 'heartbeat']
        self.assertEqual(len(hb_events), 1)
        self.assertEqual(hb_events[0]['status'], 'dead')

    def test_no_heartbeat_event_when_status_unchanged(self):
        """No heartbeat event when heartbeat_status is the same across polls."""
        s = _make_session(session_id='s1', heartbeat_status='alive')

        reader = _make_reader(
            [_FakeProject(sessions=[s])],
            [_FakeProject(sessions=[s])],
        )
        poller = self._make_poller(reader)
        events = asyncio.run(_collect_events(poller, 2))

        hb_events = [e for e in events if e['type'] == 'heartbeat']
        self.assertEqual(len(hb_events), 0)

    def test_no_heartbeat_event_on_first_poll(self):
        """First poll establishes baseline — no heartbeat event on first observation."""
        s = _make_session(session_id='s1', heartbeat_status='alive')

        reader = _make_reader([_FakeProject(sessions=[s])])
        poller = self._make_poller(reader)
        events = asyncio.run(_collect_events(poller, 1))

        hb_events = [e for e in events if e['type'] == 'heartbeat']
        self.assertEqual(len(hb_events), 0)

    def test_heartbeat_event_contains_required_fields(self):
        """heartbeat event must have type, session_id, status fields."""
        s1 = _make_session(session_id='s1', heartbeat_status='alive')
        s2 = _make_session(session_id='s1', heartbeat_status='dead')

        reader = _make_reader(
            [_FakeProject(sessions=[s1])],
            [_FakeProject(sessions=[s2])],
        )
        poller = self._make_poller(reader)
        events = asyncio.run(_collect_events(poller, 2))

        hb_events = [e for e in events if e['type'] == 'heartbeat']
        self.assertEqual(len(hb_events), 1)
        for key in ('type', 'session_id', 'status'):
            self.assertIn(key, hb_events[0], f'heartbeat event missing field: {key}')


# ── Session completion ────────────────────────────────────────────────────────

class TestSessionCompletedEvents(unittest.TestCase):
    """session_completed events emitted when sessions reach terminal CfA state."""

    def _make_poller(self, reader, bus_factory=None):
        from bridge.poller import StatePoller
        async def noop(event): pass
        return StatePoller(reader, noop, bus_factory=bus_factory)

    def test_session_completed_event_on_completed_work(self):
        """Transition to COMPLETED_WORK must produce a session_completed event."""
        s1 = _make_session(session_id='s1', cfa_state='WORK_EXEC')
        s2 = _make_session(session_id='s1', cfa_state='COMPLETED_WORK')

        reader = _make_reader(
            [_FakeProject(sessions=[s1])],
            [_FakeProject(sessions=[s2])],
        )
        poller = self._make_poller(reader)
        events = asyncio.run(_collect_events(poller, 2))

        completed = [e for e in events if e['type'] == 'session_completed']
        self.assertEqual(len(completed), 1)
        self.assertEqual(completed[0]['session_id'], 's1')
        self.assertEqual(completed[0]['terminal_state'], 'COMPLETED_WORK')

    def test_session_completed_event_on_withdrawn(self):
        """Transition to WITHDRAWN must produce a session_completed event."""
        s1 = _make_session(session_id='s1', cfa_state='WORK_EXEC')
        s2 = _make_session(session_id='s1', cfa_state='WITHDRAWN')

        reader = _make_reader(
            [_FakeProject(sessions=[s1])],
            [_FakeProject(sessions=[s2])],
        )
        poller = self._make_poller(reader)
        events = asyncio.run(_collect_events(poller, 2))

        completed = [e for e in events if e['type'] == 'session_completed']
        self.assertEqual(len(completed), 1)
        self.assertEqual(completed[0]['terminal_state'], 'WITHDRAWN')

    def test_session_completed_not_emitted_repeatedly(self):
        """session_completed must be emitted once, not on every subsequent poll."""
        s1 = _make_session(session_id='s1', cfa_state='WORK_EXEC')
        s2 = _make_session(session_id='s1', cfa_state='COMPLETED_WORK')

        # Three polls: baseline, completion, still completed
        reader = _make_reader(
            [_FakeProject(sessions=[s1])],
            [_FakeProject(sessions=[s2])],
            [_FakeProject(sessions=[s2])],
        )
        poller = self._make_poller(reader)
        events = asyncio.run(_collect_events(poller, 3))

        completed = [e for e in events if e['type'] == 'session_completed']
        self.assertEqual(len(completed), 1)

    def test_session_completed_event_contains_required_fields(self):
        """session_completed event must have type, session_id, terminal_state fields."""
        s1 = _make_session(session_id='s1', cfa_state='WORK_EXEC')
        s2 = _make_session(session_id='s1', cfa_state='COMPLETED_WORK')

        reader = _make_reader(
            [_FakeProject(sessions=[s1])],
            [_FakeProject(sessions=[s2])],
        )
        poller = self._make_poller(reader)
        events = asyncio.run(_collect_events(poller, 2))

        completed = [e for e in events if e['type'] == 'session_completed']
        self.assertEqual(len(completed), 1)
        for key in ('type', 'session_id', 'terminal_state'):
            self.assertIn(key, completed[0], f'session_completed event missing field: {key}')


# ── Bus lifecycle ─────────────────────────────────────────────────────────────

class TestBusConnectionLifecycle(unittest.TestCase):
    """SqliteMessageBus connections opened per active session, closed on completion."""

    def _make_poller(self, reader, bus_factory):
        from bridge.poller import StatePoller
        async def noop(event): pass
        return StatePoller(reader, noop, bus_factory=bus_factory)

    def test_bus_opened_for_new_active_session(self):
        """When a new active session appears, bus_factory must be called with its infra_dir."""
        s = _make_session(session_id='s1', cfa_state='PLAN_EXEC', infra_dir='/fake/s1')
        mock_bus = MagicMock()
        factory = MagicMock(return_value=mock_bus)

        reader = _make_reader([_FakeProject(sessions=[s])])
        poller = self._make_poller(reader, factory)
        asyncio.run(poller.poll_once())

        factory.assert_called_once_with('/fake/s1')

    def test_bus_not_duplicated_across_polls(self):
        """bus_factory must be called only once per session, not on every poll."""
        s = _make_session(session_id='s1', cfa_state='PLAN_EXEC', infra_dir='/fake/s1')
        mock_bus = MagicMock()
        factory = MagicMock(return_value=mock_bus)

        reader = _make_reader(
            [_FakeProject(sessions=[s])],
            [_FakeProject(sessions=[s])],
            [_FakeProject(sessions=[s])],
        )
        poller = self._make_poller(reader, factory)
        asyncio.run(_collect_events(poller, 3))

        self.assertEqual(factory.call_count, 1,
                         'bus_factory must be called once per session, not once per poll')

    def test_bus_closed_when_session_reaches_terminal_state(self):
        """When a session transitions to COMPLETED_WORK, bus.close() must be called."""
        s1 = _make_session(session_id='s1', cfa_state='WORK_EXEC', infra_dir='/fake/s1')
        s2 = _make_session(session_id='s1', cfa_state='COMPLETED_WORK', infra_dir='/fake/s1')
        mock_bus = MagicMock()
        factory = MagicMock(return_value=mock_bus)

        reader = _make_reader(
            [_FakeProject(sessions=[s1])],
            [_FakeProject(sessions=[s2])],
        )
        poller = self._make_poller(reader, factory)
        asyncio.run(_collect_events(poller, 2))

        mock_bus.close.assert_called_once()

    def test_bus_closed_when_session_withdrawn(self):
        """When a session transitions to WITHDRAWN, bus.close() must be called."""
        s1 = _make_session(session_id='s1', cfa_state='WORK_EXEC', infra_dir='/fake/s1')
        s2 = _make_session(session_id='s1', cfa_state='WITHDRAWN', infra_dir='/fake/s1')
        mock_bus = MagicMock()
        factory = MagicMock(return_value=mock_bus)

        reader = _make_reader(
            [_FakeProject(sessions=[s1])],
            [_FakeProject(sessions=[s2])],
        )
        poller = self._make_poller(reader, factory)
        asyncio.run(_collect_events(poller, 2))

        mock_bus.close.assert_called_once()

    def test_bus_removed_from_registry_after_session_completes(self):
        """After completion, the poller must not hold a reference to the closed bus."""
        s1 = _make_session(session_id='s1', cfa_state='WORK_EXEC', infra_dir='/fake/s1')
        s2 = _make_session(session_id='s1', cfa_state='COMPLETED_WORK', infra_dir='/fake/s1')
        mock_bus = MagicMock()
        factory = MagicMock(return_value=mock_bus)

        reader = _make_reader(
            [_FakeProject(sessions=[s1])],
            [_FakeProject(sessions=[s2])],
        )
        poller = self._make_poller(reader, factory)
        asyncio.run(_collect_events(poller, 2))

        self.assertNotIn('s1', poller._buses,
                         'completed session bus must be removed from the registry')

    def test_no_bus_opened_for_terminal_session_on_first_poll(self):
        """A session already in terminal state on first poll must not open a bus."""
        s = _make_session(session_id='s1', cfa_state='COMPLETED_WORK', infra_dir='/fake/s1')
        factory = MagicMock()

        reader = _make_reader([_FakeProject(sessions=[s])])
        poller = self._make_poller(reader, factory)
        asyncio.run(poller.poll_once())

        factory.assert_not_called()

    def test_no_bus_opened_when_no_factory_provided(self):
        """Without a bus_factory, poll_once must succeed without error."""
        s = _make_session(session_id='s1', cfa_state='PLAN_EXEC', infra_dir='/fake/s1')
        reader = _make_reader([_FakeProject(sessions=[s])])

        from bridge.poller import StatePoller
        async def noop(event): pass
        poller = StatePoller(reader, noop)  # no bus_factory

        # Must not raise
        asyncio.run(poller.poll_once())


# ── No spurious events ────────────────────────────────────────────────────────

class TestNoSpuriousEvents(unittest.TestCase):
    """No events emitted when state is stable across polls."""

    def _make_poller(self, reader):
        from bridge.poller import StatePoller
        async def noop(event): pass
        return StatePoller(reader, noop)

    def test_no_events_emitted_when_nothing_changes(self):
        """Two polls with identical session state must produce zero events."""
        s = _make_session(
            session_id='s1',
            cfa_state='WORK_EXEC',
            cfa_phase='execution',
            heartbeat_status='alive',
        )
        reader = _make_reader(
            [_FakeProject(sessions=[s])],
            [_FakeProject(sessions=[s])],
        )
        poller = self._make_poller(reader)
        events = asyncio.run(_collect_events(poller, 2))

        self.assertEqual(events, [],
                         f'Expected no events on stable state, got: {events}')

    def test_no_events_on_first_poll_regardless_of_state(self):
        """First poll never emits events — all transitions need a baseline."""
        s = _make_session(
            session_id='s1',
            cfa_state='WORK_EXEC',
            heartbeat_status='stale',
        )
        reader = _make_reader([_FakeProject(sessions=[s])])
        poller = self._make_poller(reader)
        events = asyncio.run(_collect_events(poller, 1))

        self.assertEqual(events, [],
                         f'First poll must not emit events, got: {events}')


if __name__ == '__main__':
    unittest.main()
