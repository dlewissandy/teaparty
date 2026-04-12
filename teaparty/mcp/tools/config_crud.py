"""Config CRUD handlers — project, agent, skill, workgroup, hook, scheduled task management."""
from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess

import yaml


def _emit_config_event(event_type: str, **data) -> None:
    """Record a config_* or pin/unpin telemetry event (Issue #405).

    Best-effort — swallows all failures so config CRUD never breaks
    because of a telemetry hiccup. ``event_type`` is looked up against
    ``teaparty.telemetry.events`` by upper-cased name; if the constant
    does not exist, the event is dropped silently.
    """
    try:
        from teaparty import telemetry
        from teaparty.telemetry import events as _telem_events
        const_name = event_type.upper()
        et = getattr(_telem_events, const_name, None)
        if et is None:
            et = event_type
        scope = data.get('project') or 'management'
        telemetry.record_event(et, scope=scope, data=dict(data))
    except Exception:
        pass

from teaparty.mcp.tools.config_helpers import (
    _err,
    _load_settings,
    _load_teaparty_yaml,
    _mgmt_agents_dir,
    _mgmt_settings_yaml,
    _mgmt_skills_dir,
    _mgmt_workgroups_dir,
    _ok,
    _parse_agent_file,
    _parse_skill_file,
    _project_root,
    _resolve_repo_root,
    _resolve_scope,
    _save_settings,
    _save_teaparty_yaml,
    _scoped_agents_dir,
    _scoped_settings_yaml,
    _scoped_skills_dir,
    _scoped_workgroups_dir,
    _teaparty_home,
    _write_agent_file,
    _write_skill_file,
)


# ── Project tools ─────────────────────────────────────────────────────────────

def add_project_handler(
    name: str,
    path: str,
    description: str = '',
    lead: str = '',
    decider: str = '',
    agents: list | None = None,
    humans: list | None = None,
    workgroups: list | None = None,
    skills: list | None = None,
    teaparty_home: str = '',
) -> str:
    """Add an existing directory as a TeaParty project.

    Registers it in management/teaparty.yaml and creates
    .teaparty/project/project.yaml with the provided fields.  Returns JSON result.
    """
    if not name or not name.strip():
        return _err('AddProject requires a non-empty name')
    if not path or not path.strip():
        return _err('AddProject requires a non-empty path')

    home = _teaparty_home(teaparty_home)
    from teaparty.config.config_reader import add_project
    try:
        add_project(
            name=name,
            path=path,
            teaparty_home=home,
            description=description,
            lead=lead,
            decider=decider,
            workgroups=workgroups,
        )
    except ValueError as e:
        return _err(str(e))
    _emit_config_event('config_project_added', project=name, path=path)
    return _ok(f"Project '{name}' added at {path}")


def create_project_handler(
    name: str,
    path: str,
    description: str = '',
    lead: str = '',
    decider: str = '',
    agents: list | None = None,
    humans: list | None = None,
    workgroups: list | None = None,
    skills: list | None = None,
    teaparty_home: str = '',
) -> str:
    """Create a new project directory with full scaffolding (git init, .teaparty/, etc.)."""
    if not name or not name.strip():
        return _err('CreateProject requires a non-empty name')
    if not path or not path.strip():
        return _err('CreateProject requires a non-empty path')

    home = _teaparty_home(teaparty_home)
    from teaparty.config.config_reader import create_project
    try:
        create_project(
            name=name,
            path=path,
            teaparty_home=home,
            description=description,
            lead=lead,
            decider=decider,
            workgroups=workgroups,
        )
    except ValueError as e:
        return _err(str(e))
    _emit_config_event('config_project_added', project=name, path=path, created=True)
    return _ok(f"Project '{name}' created at {path}")


def remove_project_handler(name: str, teaparty_home: str = '') -> str:
    """Remove a project from teaparty.yaml (directory untouched)."""
    if not name or not name.strip():
        return _err('RemoveProject requires a non-empty name')

    home = _teaparty_home(teaparty_home)
    from teaparty.config.config_reader import remove_project
    try:
        remove_project(name=name, teaparty_home=home)
    except ValueError as e:
        return _err(str(e))
    _emit_config_event('config_project_removed', project=name)
    return _ok(f"Project '{name}' removed from registry")


def scaffold_project_yaml_handler(
    project_path: str,
    name: str,
    description: str = '',
    lead: str = '',
    decider: str = '',
    agents: list | None = None,
    humans: list | None = None,
    workgroups: list | None = None,
    skills: list | None = None,
) -> str:
    """Create or overwrite .teaparty/project/project.yaml for an existing project.

    Unlike _scaffold_project_yaml, this always writes (retroactive fix for
    projects with missing or empty fields).
    """
    if not project_path or not project_path.strip():
        return _err('ScaffoldProjectYaml requires a non-empty project_path')
    if not name or not name.strip():
        return _err('ScaffoldProjectYaml requires a non-empty name')

    tp_dir = os.path.join(project_path, '.teaparty', 'project')
    os.makedirs(tp_dir, exist_ok=True)
    data = {
        'name': name,
        'description': description,
        'lead': lead,
        'decider': decider,
        'agents': agents or [],
        'humans': humans or [],
        'workgroups': workgroups or [],
        'skills': skills or [],
    }
    yaml_path = os.path.join(tp_dir, 'project.yaml')
    with open(yaml_path, 'w') as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)
    return _ok(f'Scaffolded {yaml_path}', path=yaml_path)


# ── Artifact pin tools ────────────────────────────────────────────────────────

def _load_project_registry(teaparty_home: str) -> dict:
    """Load the root teaparty.yaml (canonical project registry).

    Falls back to management/teaparty.yaml if the root file doesn't exist.
    """
    root_yaml = os.path.join(teaparty_home, 'teaparty.yaml')
    if os.path.exists(root_yaml):
        with open(root_yaml) as f:
            return yaml.safe_load(f) or {}
    return _load_teaparty_yaml(teaparty_home)


def _find_project_path(name: str, teaparty_home: str) -> str | None:
    """Return the project directory for a given project name, or None if not found."""
    data = _load_project_registry(teaparty_home)
    for team in data.get('projects', []):
        if team.get('name') == name:
            return team.get('path')
    return None


def _load_project_yaml(project_dir: str) -> dict:
    """Load .teaparty/project/project.yaml, returning an empty dict if missing."""
    path = os.path.join(project_dir, '.teaparty', 'project', 'project.yaml')
    if not os.path.exists(path):
        # Legacy fallback
        legacy = os.path.join(project_dir, '.teaparty.local', 'project.yaml')
        if os.path.exists(legacy):
            with open(legacy) as f:
                return yaml.safe_load(f) or {}
        return {}
    with open(path) as f:
        return yaml.safe_load(f) or {}


def _save_project_yaml(project_dir: str, data: dict) -> None:
    """Write data to .teaparty/project/project.yaml."""
    tp_dir = os.path.join(project_dir, '.teaparty', 'project')
    os.makedirs(tp_dir, exist_ok=True)
    path = os.path.join(tp_dir, 'project.yaml')
    with open(path, 'w') as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)


def pin_artifact_handler(
    project: str,
    path: str,
    label: str = '',
    teaparty_home: str = '',
) -> str:
    """Add or update an artifact pin in a project's artifact_pins list.

    If a pin with the same path already exists, its label is updated.
    Path is relative to the project root.
    """
    if not project or not project.strip():
        return _err('PinArtifact requires a non-empty project')
    if not path or not path.strip():
        return _err('PinArtifact requires a non-empty path')

    home = _teaparty_home(teaparty_home)
    project_dir = _find_project_path(project, home)
    if project_dir is None:
        return _err(f"Project '{project}' not found in registry")

    data = _load_project_yaml(project_dir)
    pins = data.get('artifact_pins', [])

    # Update existing or append new
    for pin in pins:
        if pin.get('path') == path:
            if label:
                pin['label'] = label
            data['artifact_pins'] = pins
            _save_project_yaml(project_dir, data)
            return _ok(f"Updated pin '{path}' in project '{project}'")

    entry: dict[str, str] = {'path': path}
    if label:
        entry['label'] = label
    pins.append(entry)
    data['artifact_pins'] = pins
    _save_project_yaml(project_dir, data)
    _emit_config_event('pin_artifact', project=project, path=path, label=label)
    return _ok(f"Pinned '{path}' in project '{project}'")


def unpin_artifact_handler(
    project: str,
    path: str,
    teaparty_home: str = '',
) -> str:
    """Remove an artifact pin from a project's artifact_pins list by path."""
    if not project or not project.strip():
        return _err('UnpinArtifact requires a non-empty project')
    if not path or not path.strip():
        return _err('UnpinArtifact requires a non-empty path')

    home = _teaparty_home(teaparty_home)
    project_dir = _find_project_path(project, home)
    if project_dir is None:
        return _err(f"Project '{project}' not found in registry")

    data = _load_project_yaml(project_dir)
    pins = data.get('artifact_pins', [])
    original_len = len(pins)
    pins = [p for p in pins if p.get('path') != path]

    if len(pins) == original_len:
        return _err(f"Pin '{path}' not found in project '{project}'")

    data['artifact_pins'] = pins
    _save_project_yaml(project_dir, data)
    _emit_config_event('unpin_artifact', project=project, path=path)
    return _ok(f"Unpinned '{path}' from project '{project}'")


# ── Read/list tools ──────────────────────────────────────────────────────────


def list_projects_handler(teaparty_home: str = '') -> str:
    """List all registered projects from the root teaparty.yaml."""
    home = _teaparty_home(teaparty_home)
    try:
        data = _load_project_registry(home)
    except FileNotFoundError as e:
        return _err(str(e))
    projects = data.get('projects', [])
    items = [{'name': p.get('name', ''), 'path': p.get('path', '')}
             for p in projects]
    return json.dumps({'success': True, 'projects': items})


def get_project_handler(name: str, teaparty_home: str = '') -> str:
    """Get full details for a single project."""
    if not name or not name.strip():
        return _err('GetProject requires a non-empty name')
    home = _teaparty_home(teaparty_home)
    project_dir = _find_project_path(name, home)
    if project_dir is None:
        return _err(f"Project '{name}' not found in registry")
    data = _load_project_yaml(project_dir)
    data['path'] = project_dir
    return json.dumps({'success': True, 'project': data})


def project_status_handler(name: str, days: int = 7, teaparty_home: str = '') -> str:
    """Generate a status summary for a project.

    Returns recent git commits and in-progress sessions/jobs.
    """
    import logging
    import subprocess
    _ps_log = logging.getLogger('teaparty.mcp.server.main.project_status')
    _ps_log.info('ProjectStatus called: name=%r days=%d', name, days)

    if not name or not name.strip():
        return _err('ProjectStatus requires a non-empty project name')
    home = _teaparty_home(teaparty_home)
    project_dir = _find_project_path(name, home)
    if project_dir is None:
        return _err(f"Project '{name}' not found in registry")

    # Git commits from the last N days
    commits = []
    git_error = ''
    try:
        result = subprocess.run(
            ['git', 'log', '--oneline', '--all', f'--since={days} days ago',
             '--format=%h %ai %s'],
            cwd=project_dir, capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            for line in result.stdout.strip().splitlines():
                if line:
                    commits.append(line)
        else:
            git_error = result.stderr.strip() or f'git log exited with code {result.returncode}'
    except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
        git_error = str(exc)

    # If no commits in the requested window, include the latest commit
    # so the report shows when the project was last active.
    latest_commit = ''
    if not commits and not git_error:
        try:
            result = subprocess.run(
                ['git', 'log', '-1', '--format=%h %ai %s'],
                cwd=project_dir, capture_output=True, text=True, timeout=10,
            )
            if result.returncode == 0 and result.stdout.strip():
                latest_commit = result.stdout.strip()
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass

    # In-progress sessions (scan .teaparty/jobs/)
    jobs_dir = os.path.join(project_dir, '.teaparty', 'jobs')
    active_sessions = []
    if os.path.isdir(jobs_dir):
        from teaparty.cfa.statemachine.cfa_state import is_globally_terminal
        for entry in sorted(os.listdir(jobs_dir), reverse=True):
            sess_path = os.path.join(jobs_dir, entry)
            if not os.path.isdir(sess_path) or not os.path.isfile(os.path.join(sess_path, 'job.json')):
                continue
            cfa_path = os.path.join(sess_path, '.cfa-state.json')
            cfa = {}
            if os.path.isfile(cfa_path):
                try:
                    with open(cfa_path) as f:
                        cfa = json.load(f)
                except (json.JSONDecodeError, OSError):
                    pass
            state = cfa.get('state', '')
            if state and is_globally_terminal(state):
                continue
            task_path = os.path.join(sess_path, 'INTENT.md')
            task = ''
            if os.path.isfile(task_path):
                try:
                    with open(task_path) as f:
                        task = f.read(200).strip()
                except OSError:
                    pass
            # Extract session_id from job.json
            try:
                with open(os.path.join(sess_path, 'job.json')) as f:
                    job_state = json.load(f)
                job_id = job_state.get('job_id', entry)
                session_id = job_id[4:] if job_id.startswith('job-') else job_id
            except (json.JSONDecodeError, OSError):
                session_id = entry
            active_sessions.append({
                'session_id': session_id,
                'phase': cfa.get('phase', ''),
                'state': state or 'unknown',
                'task': task,
            })

    result_data: dict[str, object] = {
        'success': True,
        'project': name,
        'period_days': days,
        'commits': commits,
        'commit_count': len(commits),
        'active_sessions': active_sessions,
        'active_session_count': len(active_sessions),
    }
    if git_error:
        result_data['git_error'] = git_error
    if latest_commit:
        result_data['latest_commit'] = latest_commit
    _ps_log.info(
        'ProjectStatus result: project=%r commits=%d git_error=%r latest_commit=%r',
        name, len(commits), git_error, latest_commit,
    )
    return json.dumps(result_data)


def list_team_members_handler(teaparty_home: str = '') -> str:
    """List the team members for the calling agent's team.

    Membership is derived from config, not from agent definitions:
    - Proxy agents implied by humans: entries
    - Project leads implied by members.projects
    - Workgroup leads implied by members.workgroups
    """
    from teaparty.config.config_reader import (
        load_management_team,
        load_management_workgroups,
        load_project_team,
        read_agent_frontmatter,
    )

    home = _teaparty_home(teaparty_home)
    try:
        team = load_management_team(teaparty_home=home)
    except FileNotFoundError as e:
        return _err(str(e))

    repo_root = os.path.dirname(home)
    mgmt_agents_dir = os.path.join(home, 'management', 'agents')
    members: list[dict] = []

    def _read_desc(agent_name: str) -> str:
        for candidate in (
            os.path.join(mgmt_agents_dir, agent_name, 'agent.md'),
        ):
            if os.path.isfile(candidate):
                fm, _ = _parse_agent_file(candidate)
                return fm.get('description', '')
        return ''

    # Project leads
    for project_name in team.members_projects:
        project_entry = None
        for p in team.projects:
            if p.get('name') == project_name:
                project_entry = p
                break
        if project_entry is None:
            continue
        project_path = project_entry.get('path', '')
        if not os.path.isabs(project_path):
            project_path = os.path.join(repo_root, project_path)
        config_path = project_entry.get('config', '')
        full_config = os.path.join(project_path, config_path) if config_path else None
        try:
            pt = load_project_team(project_path, config_path=full_config)
        except FileNotFoundError:
            continue
        if pt.lead:
            members.append({
                'name': pt.lead,
                'role': 'project-lead',
                'project': project_name,
                'description': _read_desc(pt.lead) or pt.description or project_name,
            })

    # Workgroup leads
    try:
        workgroups = load_management_workgroups(team, teaparty_home=home)
        for wg in workgroups:
            if wg.lead:
                members.append({
                    'name': wg.lead,
                    'role': 'workgroup-lead',
                    'workgroup': wg.name,
                    'description': _read_desc(wg.lead) or wg.description or wg.name,
                })
    except Exception:
        pass

    # Proxy agents
    for human in team.humans:
        proxy_name = 'proxy-review'
        members.append({
            'name': proxy_name,
            'role': 'proxy',
            'human': human.name,
            'description': _read_desc(proxy_name) or f'Human proxy for {human.name}',
        })

    return json.dumps({'success': True, 'members': members})


def list_agents_handler(project_root: str = '', scope: str = '') -> str:
    """List all agent definitions with summary info."""
    agents_dir = _scoped_agents_dir(scope) if scope else _mgmt_agents_dir(
        os.path.join(_project_root(project_root), '.teaparty'))
    items = []
    if os.path.isdir(agents_dir):
        for name in sorted(os.listdir(agents_dir)):
            path = os.path.join(agents_dir, name, 'agent.md')
            if os.path.isfile(path):
                fm, _ = _parse_agent_file(path)
                items.append({
                    'name': name,
                    'description': fm.get('description', ''),
                    'model': fm.get('model', ''),
                })
    return json.dumps({'success': True, 'agents': items})


def get_agent_handler(name: str, project_root: str = '', scope: str = '') -> str:
    """Get full details for a single agent definition."""
    if not name or not name.strip():
        return _err('GetAgent requires a non-empty name')
    agents_dir = _scoped_agents_dir(scope) if scope else _mgmt_agents_dir(
        os.path.join(_project_root(project_root), '.teaparty'))
    path = os.path.join(agents_dir, name, 'agent.md')
    if not os.path.isfile(path):
        return _err(f"Agent '{name}' not found at {path}")
    fm, body = _parse_agent_file(path)
    return json.dumps({'success': True, 'agent': {
        'name': name, 'path': path, **fm, 'body': body,
    }})


def list_skills_handler(project_root: str = '', scope: str = '') -> str:
    """List all skill definitions with summary info."""
    skills_dir = _scoped_skills_dir(scope) if scope else _mgmt_skills_dir(
        os.path.join(_project_root(project_root), '.teaparty'))
    items = []
    if os.path.isdir(skills_dir):
        for name in sorted(os.listdir(skills_dir)):
            path = os.path.join(skills_dir, name, 'SKILL.md')
            if os.path.isfile(path):
                fm, _ = _parse_skill_file(path)
                items.append({
                    'name': name,
                    'description': fm.get('description', ''),
                    'user-invocable': fm.get('user-invocable', False),
                })
    return json.dumps({'success': True, 'skills': items})


def get_skill_handler(name: str, project_root: str = '', scope: str = '') -> str:
    """Get full details for a single skill definition."""
    if not name or not name.strip():
        return _err('GetSkill requires a non-empty name')
    skills_dir = _scoped_skills_dir(scope) if scope else _mgmt_skills_dir(
        os.path.join(_project_root(project_root), '.teaparty'))
    path = os.path.join(skills_dir, name, 'SKILL.md')
    if not os.path.isfile(path):
        return _err(f"Skill '{name}' not found at {path}")
    fm, body = _parse_skill_file(path)
    return json.dumps({'success': True, 'skill': {
        'name': name, 'path': path, **fm, 'body': body,
    }})


def list_workgroups_handler(teaparty_home: str = '') -> str:
    """List all workgroup definitions."""
    home = _teaparty_home(teaparty_home)
    wg_dir = _mgmt_workgroups_dir(home)
    items = []
    if os.path.isdir(wg_dir):
        for fname in sorted(os.listdir(wg_dir)):
            if fname.endswith('.yaml'):
                path = os.path.join(wg_dir, fname)
                with open(path) as f:
                    data = yaml.safe_load(f) or {}
                items.append({
                    'name': data.get('name', fname[:-5]),
                    'description': data.get('description', ''),
                    'lead': data.get('lead', ''),
                })
    return json.dumps({'success': True, 'workgroups': items})


def get_workgroup_handler(name: str, teaparty_home: str = '') -> str:
    """Get full details for a single workgroup."""
    if not name or not name.strip():
        return _err('GetWorkgroup requires a non-empty name')
    home = _teaparty_home(teaparty_home)
    path = os.path.join(_mgmt_workgroups_dir(home), f'{name}.yaml')
    if not os.path.exists(path):
        return _err(f"Workgroup '{name}' not found at {path}")
    with open(path) as f:
        data = yaml.safe_load(f) or {}
    return json.dumps({'success': True, 'workgroup': data})


def list_hooks_handler(project_root: str = '') -> str:
    """List all hooks grouped by event."""
    root = _project_root(project_root)
    settings_path = _mgmt_settings_yaml(os.path.join(root, '.teaparty'))
    data = _load_settings(settings_path)
    hooks = data.get('hooks', {})
    items = []
    for event, entries in hooks.items():
        for entry in entries:
            items.append({
                'event': event,
                'matcher': entry.get('matcher', ''),
                'hooks': entry.get('hooks', []),
            })
    return json.dumps({'success': True, 'hooks': items})


def list_scheduled_tasks_handler(teaparty_home: str = '') -> str:
    """List all scheduled tasks."""
    home = _teaparty_home(teaparty_home)
    try:
        data = _load_teaparty_yaml(home)
    except FileNotFoundError as e:
        return _err(str(e))
    scheduled = data.get('scheduled', [])
    return json.dumps({'success': True, 'scheduled_tasks': scheduled})


def list_pins_handler(project: str, teaparty_home: str = '') -> str:
    """List all artifact pins for a project."""
    if not project or not project.strip():
        return _err('ListPins requires a non-empty project')
    home = _teaparty_home(teaparty_home)
    project_dir = _find_project_path(project, home)
    if project_dir is None:
        return _err(f"Project '{project}' not found in registry")
    data = _load_project_yaml(project_dir)
    pins = data.get('artifact_pins', [])
    return json.dumps({'success': True, 'pins': pins})


# ── Agent tools ───────────────────────────────────────────────────────────────

def create_agent_handler(
    name: str,
    description: str,
    model: str,
    tools: str,
    body: str,
    skills: str = '',
    max_turns: int = 20,
    project_root: str = '',
    scope: str = '',
) -> str:
    """Create agents/{name}/agent.md with validated frontmatter."""
    if not name or not name.strip():
        return _err('CreateAgent requires a non-empty name')
    if not description or not description.strip():
        return _err('CreateAgent requires a non-empty description')
    if not model or not model.strip():
        return _err('CreateAgent requires a non-empty model')

    agents_dir = _scoped_agents_dir(scope) if scope else _mgmt_agents_dir(
        os.path.join(_project_root(project_root), '.teaparty'))
    path = os.path.join(agents_dir, name, 'agent.md')

    fm: dict[str, Any] = {
        'name': name,
        'description': description,
        'tools': tools,
        'model': model,
        'maxTurns': max_turns,
    }
    if skills and skills.strip():
        skill_list = [s.strip() for s in skills.split(',') if s.strip()]
        if skill_list:
            fm['skills'] = skill_list

    body_text = body if body.startswith('\n') else f'\n{body}'
    _write_agent_file(path, fm, body_text)

    # Write default settings.yaml with message bus dispatch permissions.
    agent_dir = os.path.dirname(path)
    settings_path = os.path.join(agent_dir, 'settings.yaml')
    if not os.path.exists(settings_path):
        import yaml as _yaml
        default_settings = {
            'permissions': {
                'allow': [
                    'mcp__teaparty-config__Send',
                    'mcp__teaparty-config__Reply',
                    'mcp__teaparty-config__ListAgents',
                    'mcp__teaparty-config__GetAgent',
                    'mcp__teaparty-config__ListSkills',
                    'mcp__teaparty-config__GetSkill',
                    'mcp__teaparty-config__ListWorkgroups',
                    'mcp__teaparty-config__GetWorkgroup',
                    'mcp__teaparty-config__ListProjects',
                    'mcp__teaparty-config__GetProject',
                ],
            },
        }
        with open(settings_path, 'w') as f:
            _yaml.dump(default_settings, f, default_flow_style=False)

    # Write default pins.yaml so every agent has prompt and settings pinned.
    from teaparty.config.config_reader import write_pins
    pins_dir = agent_dir
    pins_path = os.path.join(pins_dir, 'pins.yaml')
    if not os.path.exists(pins_path):
        write_pins(pins_dir, [
            {'path': 'agent.md', 'label': 'Prompt & Identity'},
            {'path': 'settings.yaml', 'label': 'Tool & File Permissions'},
        ])

    _emit_config_event('config_agent_created', name=name, path=path)
    return _ok(f"Agent '{name}' created at {path}", path=path)


def edit_agent_handler(
    name: str,
    field: str,
    value: str,
    project_root: str = '',
    scope: str = '',
) -> str:
    """Edit a single frontmatter field (or body) in an existing agent definition."""
    if not name or not name.strip():
        return _err('EditAgent requires a non-empty name')

    agents_dir = _scoped_agents_dir(scope) if scope else _mgmt_agents_dir(
        os.path.join(_project_root(project_root), '.teaparty'))
    path = os.path.join(agents_dir, name, 'agent.md')
    if not os.path.exists(path):
        return _err(f"Agent '{name}' not found at {path}")

    fm, body = _parse_agent_file(path)
    if field == 'body':
        body = value if value.startswith('\n') else f'\n{value}'
    elif field == 'maxTurns':
        try:
            fm['maxTurns'] = int(value)
        except ValueError:
            return _err(f'maxTurns must be an integer, got: {value!r}')
    elif field == 'skills':
        fm['skills'] = [s.strip() for s in value.split(',') if s.strip()]
    else:
        fm[field] = value

    _write_agent_file(path, fm, body)
    _emit_config_event('config_agent_edited', name=name, field=field)
    return _ok(f"Agent '{name}' field '{field}' updated")


def remove_agent_handler(name: str, project_root: str = '', scope: str = '') -> str:
    """Delete agents/{name}/ directory."""
    if not name or not name.strip():
        return _err('RemoveAgent requires a non-empty name')

    agents_dir = _scoped_agents_dir(scope) if scope else _mgmt_agents_dir(
        os.path.join(_project_root(project_root), '.teaparty'))
    agent_dir = os.path.join(agents_dir, name)
    if not os.path.isdir(agent_dir):
        return _err(f"Agent '{name}' not found at {agent_dir}")

    shutil.rmtree(agent_dir)
    _emit_config_event('config_agent_removed', name=name)
    return _ok(f"Agent '{name}' removed")


# ── Skill tools ───────────────────────────────────────────────────────────────

def create_skill_handler(
    name: str,
    description: str,
    body: str,
    allowed_tools: str = '',
    argument_hint: str = '',
    user_invocable: bool = False,
    project_root: str = '',
    scope: str = '',
) -> str:
    """Create skills/{name}/SKILL.md with validated frontmatter."""
    if not name or not name.strip():
        return _err('CreateSkill requires a non-empty name')
    if not description or not description.strip():
        return _err('CreateSkill requires a non-empty description')

    skills_dir = _scoped_skills_dir(scope) if scope else _mgmt_skills_dir(
        os.path.join(_project_root(project_root), '.teaparty'))
    skill_dir = os.path.join(skills_dir, name)
    path = os.path.join(skill_dir, 'SKILL.md')

    fm: dict[str, Any] = {
        'name': name,
        'description': description,
    }
    if argument_hint:
        fm['argument-hint'] = argument_hint
    fm['user-invocable'] = user_invocable
    if allowed_tools:
        fm['allowed-tools'] = allowed_tools

    body_text = body if body.startswith('\n') else f'\n{body}'
    _write_skill_file(path, fm, body_text)
    _emit_config_event('config_skill_created', name=name, path=path)
    return _ok(f"Skill '{name}' created at {path}", path=path)


def edit_skill_handler(
    name: str,
    field: str,
    value: str,
    project_root: str = '',
    scope: str = '',
) -> str:
    """Edit a single frontmatter field (or body) in an existing skill's SKILL.md.

    field may be 'body', 'description', 'allowed-tools', 'argument-hint',
    'user-invocable', or any other frontmatter key.
    """
    if not name or not name.strip():
        return _err('EditSkill requires a non-empty name')

    skills_dir = _scoped_skills_dir(scope) if scope else _mgmt_skills_dir(
        os.path.join(_project_root(project_root), '.teaparty'))
    path = os.path.join(skills_dir, name, 'SKILL.md')
    if not os.path.exists(path):
        return _err(f"Skill '{name}' not found at {path}")

    fm, body = _parse_skill_file(path)
    if field == 'body':
        body = value if value.startswith('\n') else f'\n{value}'
    elif field == 'allowed-tools':
        fm['allowed-tools'] = value
    else:
        fm[field] = value

    _write_skill_file(path, fm, body)
    _emit_config_event('config_skill_edited', name=name, field=field)
    return _ok(f"Skill '{name}' field '{field}' updated")


def remove_skill_handler(name: str, project_root: str = '', scope: str = '') -> str:
    """Remove skills/{name}/ directory."""
    if not name or not name.strip():
        return _err('RemoveSkill requires a non-empty name')

    skills_dir = _scoped_skills_dir(scope) if scope else _mgmt_skills_dir(
        os.path.join(_project_root(project_root), '.teaparty'))
    skill_dir = os.path.join(skills_dir, name)
    if not os.path.isdir(skill_dir):
        return _err(f"Skill '{name}' not found at {skill_dir}")

    shutil.rmtree(skill_dir)
    _emit_config_event('config_skill_removed', name=name)
    return _ok(f"Skill '{name}' removed")


# ── Workgroup tools ───────────────────────────────────────────────────────────

def create_workgroup_handler(
    name: str,
    description: str = '',
    lead: str = '',
    agents_yaml: str = '',
    skills: str = '',
    norms_yaml: str = '',
    teaparty_home: str = '',
    scope: str = '',
) -> str:
    """Create a workgroup YAML in workgroups/{name}.yaml."""
    if not name or not name.strip():
        return _err('CreateWorkgroup requires a non-empty name')

    wg_dir = _scoped_workgroups_dir(scope) if scope else _mgmt_workgroups_dir(
        _teaparty_home(teaparty_home))
    os.makedirs(wg_dir, exist_ok=True)
    path = os.path.join(wg_dir, f'{name}.yaml')

    agents_list: list = []
    if agents_yaml:
        try:
            agents_list = yaml.safe_load(agents_yaml) or []
        except yaml.YAMLError:
            agents_list = []

    skills_list: list = []
    if skills:
        skills_list = [s.strip() for s in skills.split(',') if s.strip()]

    norms_dict: dict = {}
    if norms_yaml:
        try:
            norms_dict = yaml.safe_load(norms_yaml) or {}
        except yaml.YAMLError:
            norms_dict = {}

    data = {
        'name': name,
        'description': description,
        'lead': lead,
        'agents': agents_list,
        'skills': skills_list,
        'norms': norms_dict,
    }
    with open(path, 'w') as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)
    _emit_config_event('config_workgroup_created', name=name, path=path)
    return _ok(f"Workgroup '{name}' created at {path}", path=path)


def edit_workgroup_handler(
    name: str,
    field: str,
    value: str,
    teaparty_home: str = '',
    scope: str = '',
) -> str:
    """Edit a single field in an existing workgroup YAML."""
    wg_dir = _scoped_workgroups_dir(scope) if scope else _mgmt_workgroups_dir(
        _teaparty_home(teaparty_home))
    path = os.path.join(wg_dir, f'{name}.yaml')
    if not os.path.exists(path):
        return _err(f"Workgroup '{name}' not found at {path}")

    with open(path) as f:
        data = yaml.safe_load(f) or {}

    # For list/dict fields, try to parse as YAML; fall back to plain string
    if field in ('agents', 'skills', 'norms'):
        try:
            data[field] = yaml.safe_load(value)
        except yaml.YAMLError:
            data[field] = value
    else:
        data[field] = value

    with open(path, 'w') as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)
    _emit_config_event('config_workgroup_edited', name=name, field=field)
    return _ok(f"Workgroup '{name}' field '{field}' updated")


def remove_workgroup_handler(name: str, teaparty_home: str = '', scope: str = '') -> str:
    """Remove workgroups/{name}.yaml."""
    wg_dir = _scoped_workgroups_dir(scope) if scope else _mgmt_workgroups_dir(
        _teaparty_home(teaparty_home))
    path = os.path.join(wg_dir, f'{name}.yaml')
    if not os.path.exists(path):
        return _err(f"Workgroup '{name}' not found at {path}")

    os.remove(path)
    _emit_config_event('config_workgroup_removed', name=name)
    return _ok(f"Workgroup '{name}' removed")


# ── Hook tools ────────────────────────────────────────────────────────────────

def create_hook_handler(
    event: str,
    matcher: str,
    handler_type: str,
    command: str,
    project_root: str = '',
    scope: str = '',
) -> str:
    """Add a hook entry to settings.yaml."""
    if not event or not event.strip():
        return _err('CreateHook requires a non-empty event')
    if not command or not command.strip():
        return _err('CreateHook requires a non-empty command')

    settings_path = _scoped_settings_yaml(scope) if scope else _mgmt_settings_yaml(
        os.path.join(_project_root(project_root), '.teaparty'))
    data = _load_settings(settings_path)
    hooks = data.setdefault('hooks', {})
    event_hooks = hooks.setdefault(event, [])

    new_entry = {
        'matcher': matcher,
        'hooks': [{'type': handler_type, 'command': command}],
    }
    event_hooks.append(new_entry)
    _save_settings(settings_path, data)
    _emit_config_event('config_hook_created', event=event, matcher=matcher)
    return _ok(f"Hook added: {event}/{matcher}")


def edit_hook_handler(
    event: str,
    matcher: str,
    field: str,
    value: str,
    project_root: str = '',
    scope: str = '',
) -> str:
    """Edit a field in an existing hook entry."""
    settings_path = _scoped_settings_yaml(scope) if scope else _mgmt_settings_yaml(
        os.path.join(_project_root(project_root), '.teaparty'))
    data = _load_settings(settings_path)
    event_hooks = data.get('hooks', {}).get(event, [])

    for entry in event_hooks:
        if entry.get('matcher') == matcher:
            if field == 'matcher':
                entry['matcher'] = value
            elif field in ('command', 'type'):
                for h in entry.get('hooks', []):
                    h[field] = value
            else:
                entry[field] = value
            _save_settings(settings_path, data)
            return _ok(f"Hook {event}/{matcher} field '{field}' updated")

    return _err(f"Hook not found: {event}/{matcher}")


def remove_hook_handler(event: str, matcher: str, project_root: str = '', scope: str = '') -> str:
    """Remove a hook entry from settings.yaml."""
    settings_path = _scoped_settings_yaml(scope) if scope else _mgmt_settings_yaml(
        os.path.join(_project_root(project_root), '.teaparty'))
    data = _load_settings(settings_path)
    event_hooks = data.get('hooks', {}).get(event, [])

    original_len = len(event_hooks)
    data['hooks'][event] = [
        e for e in event_hooks if e.get('matcher') != matcher
    ]

    if len(data['hooks'][event]) == original_len:
        return _err(f"Hook not found: {event}/{matcher}")

    _save_settings(settings_path, data)
    _emit_config_event('config_hook_removed', event=event, matcher=matcher)
    return _ok(f"Hook removed: {event}/{matcher}")


# ── Scheduled task tools ──────────────────────────────────────────────────────

def create_scheduled_task_handler(
    name: str,
    schedule: str,
    skill: str,
    args: str = '',
    teaparty_home: str = '',
) -> str:
    """Add a scheduled task entry to teaparty.yaml."""
    if not name or not name.strip():
        return _err('CreateScheduledTask requires a non-empty name')
    if not schedule or not schedule.strip():
        return _err('CreateScheduledTask requires a non-empty schedule')
    if not skill or not skill.strip():
        return _err('CreateScheduledTask requires a non-empty skill')

    home = _teaparty_home(teaparty_home)
    try:
        data = _load_teaparty_yaml(home)
    except FileNotFoundError as e:
        return _err(str(e))

    scheduled = data.setdefault('scheduled', [])
    entry = {'name': name, 'schedule': schedule, 'skill': skill,
             'args': args, 'enabled': True}
    scheduled.append(entry)
    _save_teaparty_yaml(home, data)
    return _ok(f"Scheduled task '{name}' created")


def edit_scheduled_task_handler(
    name: str,
    field: str,
    value: str,
    teaparty_home: str = '',
) -> str:
    """Edit a field in an existing scheduled task entry."""
    home = _teaparty_home(teaparty_home)
    try:
        data = _load_teaparty_yaml(home)
    except FileNotFoundError as e:
        return _err(str(e))

    scheduled = data.get('scheduled', [])
    for entry in scheduled:
        if entry.get('name') == name:
            if field == 'enabled':
                entry[field] = value.lower() in ('true', '1', 'yes')
            else:
                entry[field] = value
            _save_teaparty_yaml(home, data)
            return _ok(f"Scheduled task '{name}' field '{field}' updated")

    return _err(f"Scheduled task '{name}' not found")


def remove_scheduled_task_handler(name: str, teaparty_home: str = '') -> str:
    """Remove a scheduled task entry from teaparty.yaml."""
    home = _teaparty_home(teaparty_home)
    try:
        data = _load_teaparty_yaml(home)
    except FileNotFoundError as e:
        return _err(str(e))

    scheduled = data.get('scheduled', [])
    original_len = len(scheduled)
    data['scheduled'] = [e for e in scheduled if e.get('name') != name]

    if len(data['scheduled']) == original_len:
        return _err(f"Scheduled task '{name}' not found")

    _save_teaparty_yaml(home, data)
    return _ok(f"Scheduled task '{name}' removed")


MCP_SERVER_NAME = 'teaparty-config'


def list_mcp_tool_names() -> list[str]:
    """Return the namespaced tool names exposed by the teaparty-config MCP server.

    Used by the bridge catalog API so the config UI can display all
    available tools without hardcoding them.  The names use Claude Code's
    ``mcp__{server}__{tool}`` convention.
    """
    server = create_server()
    prefix = f'mcp__{MCP_SERVER_NAME}__'
    return [prefix + name for name in sorted(server._tool_manager._tools)]


def _agent_tool_scope() -> str:
    """Determine tool scope for this MCP server instance.

    Checked in order:
    1. AGENT_TOOL_SCOPE env var (set by mcp_server_dispatch entry point)
    2. .tool-scope file in cwd (written by compose_worktree)
    3. '' (full tool set — interactive session)
    """
    scope = os.environ.get('AGENT_TOOL_SCOPE', '')
    if scope:
        return scope
    scope_file = os.path.join(os.getcwd(), '.tool-scope')
    try:
        with open(scope_file) as f:
            return f.read().strip()
    except FileNotFoundError:
        return ''


