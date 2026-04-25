"""Shared test helpers for orchestrator test isolation.

Provides real temp-directory creation with automatic cleanup, replacing
hardcoded fake paths like /tmp/fake throughout the test suite.

Issue #314.
"""
import shutil
import tempfile
import unittest


def make_tmp_dir(test_case: unittest.TestCase) -> str:
    """Create a real temp directory and register cleanup via addCleanup.

    Returns a real directory path suitable for use as infra_dir, project_workdir,
    session_worktree, proxy_model_path, poc_root, or any other path argument
    that needs a real (but ephemeral) location during testing.

    The directory is removed after the test via test_case.addCleanup, so no
    filesystem artifacts accumulate at fixed paths like /tmp/fake.

    Usage in tests:
        tmp = make_tmp_dir(self)
        orch = Orchestrator(infra_dir=tmp, project_workdir=tmp, ...)
    """
    tmp = tempfile.mkdtemp(prefix='teaparty-test-')
    test_case.addCleanup(shutil.rmtree, tmp, True)
    return tmp


async def call_spawn_fn(
    orch, member: str, composite: str, context_id: str = '',
):
    """Invoke the unified spawn_fn against a stub Orchestrator.

    Cut 24 unified the spawn-fn prelude into
    ``messaging/child_dispatch.schedule_child_dispatch``.  Tests that
    used to call ``orch._bus_spawn_agent(...)`` directly now build a
    ``ChildDispatchContext`` from the stub orchestrator's attrs and
    invoke the shared function.

    The stub ``orch`` must carry: ``_dispatcher_session``,
    ``_bus_event_listener``, ``_session_registry``, ``_tasks_by_child``,
    ``_paused_check``, ``_mcp_routes``, ``_on_dispatch``, ``teaparty_home``,
    ``project_slug``, ``project_workdir`` (plus ``session_worktree`` —
    populated onto ``_dispatcher_session.worktree_path`` here so the
    shared prelude derives source_repo correctly).
    """
    from teaparty.messaging.child_dispatch import (
        ChildDispatchContext, schedule_child_dispatch,
    )
    from teaparty.messaging.conversations import SqliteMessageBus

    # Mirror engine.run() setup: stamp the dispatcher session with the
    # orchestrator's session_worktree so the unified prelude derives
    # source_repo / merge_target_repo the way CfA expects.
    if getattr(orch, 'session_worktree', None):
        orch._dispatcher_session.worktree_path = orch.session_worktree
        orch._dispatcher_session.merge_target_repo = orch.project_workdir
        orch._dispatcher_session.merge_target_worktree = orch.session_worktree
    if not getattr(orch._dispatcher_session, 'agent_name', ''):
        orch._dispatcher_session.agent_name = 'lead'

    # The bus must outlive the spawn call: schedule_child_dispatch
    # schedules a background task that uses ctx.bus for the lifecycle
    # loop's children_of() reads.  Stash the bus on orch so the test's
    # cleanup (or orch's lifetime) controls its close, instead of
    # closing it inside the helper while the task still references it.
    if not hasattr(orch, '_test_spawn_bus') or orch._test_spawn_bus is None:
        orch._test_spawn_bus = SqliteMessageBus(
            orch._bus_event_listener.bus_db_path,
        )
    bus = orch._test_spawn_bus

    async def _on_complete(child_session, response_text):
        return None

    ctx = ChildDispatchContext(
        dispatcher_session=orch._dispatcher_session,
        bus=bus,
        bus_listener=orch._bus_event_listener,
        session_registry=orch._session_registry,
        tasks_by_child=orch._tasks_by_child,
        factory_registry=None,
        teaparty_home=orch.teaparty_home,
        project_slug=getattr(orch, 'project_slug', '') or '',
        repo_root=getattr(orch, 'project_workdir', '') or '',
        telemetry_scope=getattr(orch, 'project_slug', '') or '',
        fixed_scope='management',
        cross_repo_supported=False,
        log_tag='test._bus_spawn_agent',
        paused_check=getattr(orch, '_paused_check', None),
        mcp_routes=getattr(orch, '_mcp_routes', None),
        on_dispatch=getattr(orch, '_on_dispatch', None),
        on_child_complete=_on_complete,
    )
    return await schedule_child_dispatch(
        member, composite, context_id, ctx=ctx,
    )
