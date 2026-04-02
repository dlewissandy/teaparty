"""Tests for issue #378: Config screens — scheduled tasks panel at management and project level.

Acceptance criteria:
1. Management config screen has a Scheduled Tasks panel
2. Project config screen has a Scheduled Tasks panel
3. Both panels show full inherited catalog; active tasks highlighted; click to enable/disable
4. Regular workgroup config screen does NOT have a Scheduled Tasks panel
5. Changes written back to YAML on disk
"""
import os
import tempfile
import unittest
import yaml


CONFIG_HTML = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    'bridge', 'static', 'config.html',
)


def _read_config_html():
    with open(CONFIG_HTML) as f:
        return f.read()


def _make_management_yaml(teaparty_home: str, scheduled: list | None = None):
    data = {
        'name': 'Management',
        'description': 'Test',
        'lead': 'office-manager',
        'humans': {'decider': 'darrell'},
        'members': {'agents': [], 'skills': []},
        'hooks': [],
        'scheduled': scheduled or [],
        'workgroups': [],
    }
    os.makedirs(teaparty_home, exist_ok=True)
    with open(os.path.join(teaparty_home, 'teaparty.yaml'), 'w') as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)


def _make_project_yaml(project_dir: str, scheduled: list | None = None):
    tp_local = os.path.join(project_dir, '.teaparty.local')
    os.makedirs(tp_local, exist_ok=True)
    data = {
        'name': 'Test Project',
        'description': 'A test project',
        'lead': 'project-lead',
        'humans': {'decider': 'darrell'},
        'members': {'agents': [], 'skills': []},
        'hooks': [],
        'scheduled': scheduled or [],
        'workgroups': [],
    }
    with open(os.path.join(tp_local, 'project.yaml'), 'w') as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)


def _read_management_yaml(teaparty_home: str) -> dict:
    with open(os.path.join(teaparty_home, 'teaparty.yaml')) as f:
        return yaml.safe_load(f)


def _read_project_yaml(project_dir: str) -> dict:
    with open(os.path.join(project_dir, '.teaparty.local', 'project.yaml')) as f:
        return yaml.safe_load(f)


def _make_scheduled_task(name='nightly-test-sweep', schedule='0 2 * * *',
                         skill='test-sweep', enabled=True) -> dict:
    return {'name': name, 'schedule': schedule, 'skill': skill, 'enabled': enabled}


# ── toggle_management_membership: scheduled_task kind ────────────────────────

class TestToggleManagementScheduledTask(unittest.TestCase):
    """toggle_management_membership must enable/disable scheduled tasks in teaparty.yaml."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.teaparty_home = os.path.join(self.tmp, '.teaparty')
        _make_management_yaml(
            self.teaparty_home,
            scheduled=[
                _make_scheduled_task(name='nightly-sweep', enabled=True),
                _make_scheduled_task(name='weekly-audit', enabled=False),
            ],
        )

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_disable_enabled_task_sets_enabled_false(self):
        """Toggling an active scheduled task off must set enabled=False in teaparty.yaml."""
        from orchestrator.config_reader import toggle_management_membership
        toggle_management_membership(self.teaparty_home, 'scheduled_task', 'nightly-sweep', False)
        data = _read_management_yaml(self.teaparty_home)
        task = next(t for t in data['scheduled'] if t['name'] == 'nightly-sweep')
        self.assertFalse(task['enabled'])

    def test_enable_disabled_task_sets_enabled_true(self):
        """Toggling an inactive scheduled task on must set enabled=True in teaparty.yaml."""
        from orchestrator.config_reader import toggle_management_membership
        toggle_management_membership(self.teaparty_home, 'scheduled_task', 'weekly-audit', True)
        data = _read_management_yaml(self.teaparty_home)
        task = next(t for t in data['scheduled'] if t['name'] == 'weekly-audit')
        self.assertTrue(task['enabled'])

    def test_other_tasks_unchanged_after_toggle(self):
        """Toggling one scheduled task must not alter other task entries."""
        from orchestrator.config_reader import toggle_management_membership
        toggle_management_membership(self.teaparty_home, 'scheduled_task', 'nightly-sweep', False)
        data = _read_management_yaml(self.teaparty_home)
        other = next(t for t in data['scheduled'] if t['name'] == 'weekly-audit')
        self.assertFalse(other['enabled'])  # unchanged

    def test_unknown_task_name_raises(self):
        """Toggling a scheduled_task name that doesn't exist must raise ValueError."""
        from orchestrator.config_reader import toggle_management_membership
        with self.assertRaises(ValueError):
            toggle_management_membership(self.teaparty_home, 'scheduled_task', 'no-such-task', True)

    def test_invalid_kind_still_raises(self):
        """toggle_management_membership must still reject invalid kind values."""
        from orchestrator.config_reader import toggle_management_membership
        with self.assertRaises(ValueError):
            toggle_management_membership(self.teaparty_home, 'banana', 'nightly-sweep', True)


# ── toggle_project_membership: scheduled_task kind ───────────────────────────

class TestToggleProjectScheduledTask(unittest.TestCase):
    """toggle_project_membership must enable/disable scheduled tasks in project.yaml."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.project_dir = os.path.join(self.tmp, 'my-project')
        _make_project_yaml(
            self.project_dir,
            scheduled=[
                _make_scheduled_task(name='daily-scan', enabled=True),
                _make_scheduled_task(name='report-gen', enabled=False),
            ],
        )

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_disable_task_sets_enabled_false_in_project_yaml(self):
        """Toggling a project scheduled task off must set enabled=False in project.yaml."""
        from orchestrator.config_reader import toggle_project_membership
        toggle_project_membership(self.project_dir, 'scheduled_task', 'daily-scan', False)
        data = _read_project_yaml(self.project_dir)
        task = next(t for t in data['scheduled'] if t['name'] == 'daily-scan')
        self.assertFalse(task['enabled'])

    def test_enable_task_sets_enabled_true_in_project_yaml(self):
        """Toggling a project scheduled task on must set enabled=True in project.yaml."""
        from orchestrator.config_reader import toggle_project_membership
        toggle_project_membership(self.project_dir, 'scheduled_task', 'report-gen', True)
        data = _read_project_yaml(self.project_dir)
        task = next(t for t in data['scheduled'] if t['name'] == 'report-gen')
        self.assertTrue(task['enabled'])

    def test_unknown_project_task_name_raises(self):
        """Toggling a project scheduled_task name that doesn't exist must raise ValueError."""
        from orchestrator.config_reader import toggle_project_membership
        with self.assertRaises(ValueError):
            toggle_project_membership(self.project_dir, 'scheduled_task', 'ghost-task', True)


# ── Frontend: config.html scheduled tasks panel rendering ────────────────────

class TestConfigHtmlScheduledTasksPanel(unittest.TestCase):
    """config.html must render Scheduled Tasks panels with catalog-vs-active pattern."""

    def setUp(self):
        self.content = _read_config_html()

    def test_scheduled_tasks_panel_present_in_render_global(self):
        """renderGlobal() must include a 'Scheduled Tasks' section card."""
        self.assertIn(
            'Scheduled Tasks',
            self.content,
            'config.html must include a Scheduled Tasks section card',
        )

    def test_scheduled_tasks_use_catalog_active_class(self):
        """Active scheduled tasks must use item-catalog-active CSS class."""
        self.assertIn(
            'item-catalog-active',
            self.content,
            'config.html must use item-catalog-active class for enabled scheduled tasks',
        )

    def test_scheduled_tasks_use_catalog_inactive_class(self):
        """Inactive scheduled tasks must use item-catalog-inactive CSS class."""
        self.assertIn(
            'item-catalog-inactive',
            self.content,
            'config.html must use item-catalog-inactive class for disabled scheduled tasks',
        )

    def test_scheduled_task_toggle_calls_toggle_membership_with_correct_type(self):
        """Clicking a scheduled task must call toggleMembership with type 'scheduled_task'."""
        self.assertIn(
            'scheduled_task',
            self.content,
            "config.html must pass 'scheduled_task' type to toggleMembership for cron item clicks",
        )

    def test_scheduled_task_active_state_uses_enabled_field(self):
        """cronItems rendering must check c.enabled to determine active/inactive state."""
        self.assertIn(
            'c.enabled',
            self.content,
            'cronItems rendering must use c.enabled to determine active vs inactive state',
        )

    def test_scheduled_task_item_renders_skill_name(self):
        """cronItems rendering must include c.skill in the item meta so tasks are browsable."""
        self.assertIn(
            'c.skill',
            self.content,
            'cronItems rendering must include c.skill in item meta — skill name identifies what the task does',
        )

    def test_workgroup_render_has_no_scheduled_tasks_section(self):
        """renderWorkgroup() must not include a Scheduled Tasks panel."""
        # Find renderWorkgroup function body — everything between renderWorkgroup and
        # the next top-level async function definition.
        start = self.content.find('async function renderWorkgroup(')
        self.assertGreater(start, 0, 'renderWorkgroup must be defined in config.html')
        # Find the next function definition after renderWorkgroup
        next_fn = self.content.find('\nasync function ', start + 1)
        if next_fn == -1:
            next_fn = len(self.content)
        wg_body = self.content[start:next_fn]
        self.assertNotIn(
            'Scheduled Tasks',
            wg_body,
            'renderWorkgroup() must not include a Scheduled Tasks panel',
        )
