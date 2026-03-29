"""Tests for issue #272: Workgroup dashboard shows no data.

Verifies that the workgroup dashboard populates all five cards:
1. Sessions — sessions containing dispatches from this workgroup's team
2. Escalations — pending escalations from workgroup-relevant sessions
3. Active Tasks — active dispatches belonging to this workgroup's team
4. Agents — workgroup agent list (already worked before this fix)
5. Skills — workgroup-scoped skills

Also verifies stats bar summary for the workgroup level.
"""
import os
import tempfile
import unittest
import yaml

from projects.POC.orchestrator.state_reader import DispatchState, SessionState, ProjectState


def _make_dispatch(**kwargs):
    defaults = dict(
        team='coding',
        worktree_name='wt-dispatch',
        worktree_path='/tmp/wt-dispatch',
        task='implement feature',
        status='active',
        cfa_state='WORK_IN_PROGRESS',
        cfa_phase='execution',
        is_running=True,
        infra_dir='',
        stream_age_seconds=30,
        needs_input=False,
        heartbeat_status='alive',
    )
    defaults.update(kwargs)
    return DispatchState(**defaults)


def _make_session(**kwargs):
    defaults = dict(
        project='test-proj',
        session_id='20260328-120000',
        worktree_name='wt-session',
        worktree_path='/tmp/session',
        task='do something',
        status='active',
        cfa_phase='execution',
        cfa_state='WORK_IN_PROGRESS',
        cfa_actor='uber_team',
        needs_input=False,
        is_orphaned=False,
        dispatches=[],
        stream_age_seconds=10,
        duration_seconds=300,
        infra_dir='',
    )
    defaults.update(kwargs)
    return SessionState(**defaults)


def _make_project(**kwargs):
    defaults = dict(
        slug='test-proj',
        path='/tmp/proj',
        sessions=[],
        active_count=0,
        attention_count=0,
    )
    defaults.update(kwargs)
    return ProjectState(**defaults)


def _make_workgroup_yaml(tmpdir, name='Coding', agents=None, skills=None, lead='coding-lead'):
    """Write a workgroup YAML file and return its path."""
    if agents is None:
        agents = [
            {'name': 'Developer', 'role': 'specialist', 'model': 'claude-sonnet-4'},
        ]
    if skills is None:
        skills = ['fix-issue', 'code-cleanup']
    data = {
        'name': name,
        'description': f'{name} workgroup',
        'lead': lead,
        'agents': agents,
        'skills': skills,
    }
    path = os.path.join(tmpdir, f'{name.lower()}.yaml')
    with open(path, 'w') as f:
        yaml.dump(data, f)
    return path


class TestWorkgroupSessionFiltering(unittest.TestCase):
    """Sessions card should show sessions that have dispatches from this workgroup's team."""

    def test_sessions_with_matching_team_dispatches_are_included(self):
        """A session with a dispatch whose team matches the workgroup name should appear."""
        from projects.POC.tui.screens.dashboard_screen import filter_sessions_for_workgroup
        coding_dispatch = _make_dispatch(team='coding', status='active')
        session = _make_session(dispatches=[coding_dispatch])
        result = filter_sessions_for_workgroup([session], 'Coding')
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].session_id, session.session_id)

    def test_sessions_without_matching_dispatches_are_excluded(self):
        """A session with only non-matching dispatches should not appear."""
        from projects.POC.tui.screens.dashboard_screen import filter_sessions_for_workgroup
        research_dispatch = _make_dispatch(team='research', status='active')
        session = _make_session(dispatches=[research_dispatch])
        result = filter_sessions_for_workgroup([session], 'Coding')
        self.assertEqual(len(result), 0)

    def test_session_with_mixed_dispatches_is_included(self):
        """A session with both matching and non-matching dispatches should appear."""
        from projects.POC.tui.screens.dashboard_screen import filter_sessions_for_workgroup
        coding = _make_dispatch(team='coding')
        research = _make_dispatch(team='research')
        session = _make_session(dispatches=[coding, research])
        result = filter_sessions_for_workgroup([session], 'Coding')
        self.assertEqual(len(result), 1)

    def test_case_insensitive_team_matching(self):
        """Workgroup name 'Coding' should match dispatch team 'coding'."""
        from projects.POC.tui.screens.dashboard_screen import filter_sessions_for_workgroup
        dispatch = _make_dispatch(team='coding')
        session = _make_session(dispatches=[dispatch])
        result = filter_sessions_for_workgroup([session], 'Coding')
        self.assertEqual(len(result), 1)

    def test_empty_sessions_list(self):
        from projects.POC.tui.screens.dashboard_screen import filter_sessions_for_workgroup
        result = filter_sessions_for_workgroup([], 'Coding')
        self.assertEqual(result, [])


class TestWorkgroupEscalations(unittest.TestCase):
    """Escalations card should show escalations from workgroup-relevant sessions."""

    def test_dispatch_escalation_from_matching_team_appears(self):
        """An escalation in a dispatch whose team matches the workgroup should appear."""
        from projects.POC.tui.screens.dashboard_screen import (
            filter_sessions_for_workgroup,
            _build_workgroup_escalation_items,
        )
        escalated = _make_dispatch(team='coding', needs_input=True,
                                   cfa_state='WORK_ASSERT')
        session = _make_session(dispatches=[escalated])
        filtered = filter_sessions_for_workgroup([session], 'Coding')
        items = _build_workgroup_escalation_items(filtered, 'Coding')
        self.assertEqual(len(items), 1)

    def test_session_level_escalation_on_matching_session(self):
        """A session-level escalation should appear if the session has matching dispatches."""
        from projects.POC.tui.screens.dashboard_screen import (
            filter_sessions_for_workgroup,
            _build_workgroup_escalation_items,
        )
        dispatch = _make_dispatch(team='coding')
        session = _make_session(dispatches=[dispatch], needs_input=True,
                                cfa_state='INTENT_ASSERT')
        filtered = filter_sessions_for_workgroup([session], 'Coding')
        items = _build_workgroup_escalation_items(filtered, 'Coding')
        self.assertEqual(len(items), 1)

    def test_escalation_from_other_team_dispatch_excluded(self):
        """A dispatch escalation from a non-matching team should not appear."""
        from projects.POC.tui.screens.dashboard_screen import (
            filter_sessions_for_workgroup,
            _build_workgroup_escalation_items,
        )
        coding = _make_dispatch(team='coding', needs_input=False)
        research = _make_dispatch(team='research', needs_input=True, cfa_state='WORK_ASSERT')
        session = _make_session(dispatches=[coding, research])
        filtered = filter_sessions_for_workgroup([session], 'Coding')
        items = _build_workgroup_escalation_items(filtered, 'Coding')
        # Only session-level if needed, not the research dispatch escalation
        self.assertEqual(len(items), 0)


class TestWorkgroupActiveTasks(unittest.TestCase):
    """Active Tasks card should show active dispatches from this workgroup's team."""

    def test_active_dispatches_from_matching_team(self):
        """Active dispatches whose team matches the workgroup should appear as tasks."""
        from projects.POC.tui.screens.dashboard_screen import build_active_task_items
        active = _make_dispatch(team='coding', status='active')
        complete = _make_dispatch(team='coding', status='complete')
        other = _make_dispatch(team='research', status='active')
        session = _make_session(dispatches=[active, complete, other])
        items = build_active_task_items([session], 'Coding')
        self.assertEqual(len(items), 1)

    def test_no_active_dispatches_returns_empty(self):
        from projects.POC.tui.screens.dashboard_screen import build_active_task_items
        complete = _make_dispatch(team='coding', status='complete')
        session = _make_session(dispatches=[complete])
        items = build_active_task_items([session], 'Coding')
        self.assertEqual(len(items), 0)


class TestWorkgroupSkills(unittest.TestCase):
    """Skills card should show skills from the workgroup config."""

    def test_skills_loaded_from_workgroup_config(self):
        """Skills listed in the workgroup YAML should appear as card items."""
        from projects.POC.tui.screens.dashboard_screen import build_skill_items
        items = build_skill_items(['fix-issue', 'code-cleanup'])
        self.assertEqual(len(items), 2)
        labels = [item.label for item in items]
        self.assertIn('fix-issue', labels)
        self.assertIn('code-cleanup', labels)

    def test_empty_skills_list(self):
        from projects.POC.tui.screens.dashboard_screen import build_skill_items
        items = build_skill_items([])
        self.assertEqual(items, [])


class TestWorkgroupStats(unittest.TestCase):
    """Stats bar should show summary counts for the workgroup."""

    def test_stats_include_session_and_task_counts(self):
        """Stats should include sessions, active tasks, and escalation counts."""
        from projects.POC.tui.screens.dashboard_screen import compute_workgroup_stats
        active_d = _make_dispatch(team='coding', status='active')
        complete_d = _make_dispatch(team='coding', status='complete')
        escalated_d = _make_dispatch(team='coding', status='active', needs_input=True)
        s1 = _make_session(session_id='20260328-120000', dispatches=[active_d, complete_d])
        s2 = _make_session(session_id='20260328-130000', dispatches=[escalated_d])
        stats = compute_workgroup_stats([s1, s2], 'Coding')
        self.assertEqual(stats['sessions'], 2)
        # escalated dispatch is still active (status='active')
        self.assertEqual(stats['active_tasks'], 2)
        self.assertEqual(stats['complete_tasks'], 1)
        self.assertEqual(stats['escalations'], 1)


class TestManagementLevelWorkgroupFiltering(unittest.TestCase):
    """Management-level workgroups have no project_slug — sessions come from all projects."""

    def test_sessions_from_multiple_projects_are_collected(self):
        """When project_slug is empty, sessions from all projects should be considered."""
        from projects.POC.tui.screens.dashboard_screen import filter_sessions_for_workgroup
        d1 = _make_dispatch(team='configuration', status='active')
        d2 = _make_dispatch(team='configuration', status='complete')
        d3 = _make_dispatch(team='coding', status='active')
        s1 = _make_session(project='proj-a', session_id='20260328-100000', dispatches=[d1])
        s2 = _make_session(project='proj-b', session_id='20260328-110000', dispatches=[d2])
        s3 = _make_session(project='proj-a', session_id='20260328-120000', dispatches=[d3])
        # All sessions from all projects combined
        all_sessions = [s1, s2, s3]
        result = filter_sessions_for_workgroup(all_sessions, 'Configuration')
        self.assertEqual(len(result), 2)
        session_ids = {s.session_id for s in result}
        self.assertEqual(session_ids, {'20260328-100000', '20260328-110000'})


if __name__ == '__main__':
    unittest.main()
