"""Path resolution, YAML/frontmatter I/O helpers for MCP config tools."""
from __future__ import annotations

import json
import os
import re

import yaml


def _ok(message: str, **extra) -> str:
    return json.dumps({'success': True, 'message': message, **extra})


def _err(error: str) -> str:
    return json.dumps({'success': False, 'error': error})


def _resolve_repo_root() -> str:
    """Resolve the main repository root, even from a git worktree.

    Uses `git rev-parse --git-common-dir` which returns the main repo's
    .git directory regardless of whether cwd is the main checkout or a
    worktree.  This ensures config CRUD tools write to the real repo,
    not an ephemeral worktree copy.
    """
    import subprocess
    try:
        result = subprocess.run(
            ['git', 'rev-parse', '--git-common-dir'],
            capture_output=True, text=True, cwd=os.getcwd(),
        )
        if result.returncode == 0:
            git_dir = result.stdout.strip()
            return os.path.dirname(os.path.abspath(git_dir))
    except FileNotFoundError:
        pass
    return os.getcwd()


def _project_root(override: str) -> str:
    return override if override else _resolve_repo_root()


def _teaparty_home(override: str) -> str:
    return override if override else os.path.join(_resolve_repo_root(), '.teaparty')


def _mgmt_agents_dir(teaparty_home: str) -> str:
    return os.path.join(teaparty_home, 'management', 'agents')


def _mgmt_skills_dir(teaparty_home: str) -> str:
    return os.path.join(teaparty_home, 'management', 'skills')


def _mgmt_settings_yaml(teaparty_home: str) -> str:
    return os.path.join(teaparty_home, 'management', 'settings.yaml')


def _mgmt_workgroups_dir(teaparty_home: str) -> str:
    return os.path.join(teaparty_home, 'management', 'workgroups')


def _proj_agents_dir(project_root: str) -> str:
    return os.path.join(project_root, '.teaparty', 'project', 'agents')


def _proj_skills_dir(project_root: str) -> str:
    return os.path.join(project_root, '.teaparty', 'project', 'skills')


def _proj_settings_yaml(project_root: str) -> str:
    return os.path.join(project_root, '.teaparty', 'project', 'settings.yaml')


def _proj_workgroups_dir(project_root: str) -> str:
    return os.path.join(project_root, '.teaparty', 'project', 'workgroups')


def _resolve_scope(scope: str) -> tuple[str, bool]:
    """Resolve a scope string to (root_path, is_management).

    Args:
        scope: Either 'management' (or empty, which defaults to management)
            or a project name. Project names are resolved via teaparty.yaml
            and external-projects.yaml to their absolute paths.

    Returns:
        (root_path, is_management) where root_path is the repo root for
        the resolved scope.
    """
    if not scope or scope == 'management':
        return _resolve_repo_root(), True

    # Resolve project name to path via registry
    repo_root = _resolve_repo_root()
    teaparty_home = os.path.join(repo_root, '.teaparty')

    # Check inline projects in teaparty.yaml
    ty_path = os.path.join(teaparty_home, 'management', 'teaparty.yaml')
    if os.path.isfile(ty_path):
        with open(ty_path) as f:
            ty = yaml.safe_load(f) or {}
        for proj in ty.get('projects', []):
            if proj.get('name', '').lower() == scope.lower():
                proj_path = proj.get('path', '')
                if proj_path == '.':
                    return repo_root, False
                return os.path.abspath(os.path.join(repo_root, proj_path)), False

    # Check external projects
    ext_path = os.path.join(teaparty_home, 'management', 'external-projects.yaml')
    if os.path.isfile(ext_path):
        with open(ext_path) as f:
            ext = yaml.safe_load(f) or []
        for proj in ext:
            if proj.get('name', '').lower() == scope.lower():
                return proj.get('path', repo_root), False

    # Scope not found — fall back to management
    return repo_root, True


def _scoped_agents_dir(scope: str) -> str:
    """Resolve agents directory for the given scope."""
    root, is_mgmt = _resolve_scope(scope)
    if is_mgmt:
        return _mgmt_agents_dir(os.path.join(root, '.teaparty'))
    return _proj_agents_dir(root)


def _scoped_skills_dir(scope: str) -> str:
    """Resolve skills directory for the given scope."""
    root, is_mgmt = _resolve_scope(scope)
    if is_mgmt:
        return _mgmt_skills_dir(os.path.join(root, '.teaparty'))
    return _proj_skills_dir(root)


def _scoped_workgroups_dir(scope: str) -> str:
    """Resolve workgroups directory for the given scope."""
    root, is_mgmt = _resolve_scope(scope)
    if is_mgmt:
        return _mgmt_workgroups_dir(os.path.join(root, '.teaparty'))
    return _proj_workgroups_dir(root)


def _scoped_settings_yaml(scope: str) -> str:
    """Resolve settings.yaml for the given scope."""
    root, is_mgmt = _resolve_scope(scope)
    if is_mgmt:
        return _mgmt_settings_yaml(os.path.join(root, '.teaparty'))
    return _proj_settings_yaml(root)


def _parse_agent_file(path: str) -> tuple[dict, str]:
    """Parse an agents/{name}/agent.md file.

    Returns (frontmatter_dict, body_text).
    """
    with open(path) as f:
        content = f.read()
    m = re.match(r'^---\n(.*?\n)---\n(.*)', content, re.DOTALL)
    if not m:
        return {}, content
    return yaml.safe_load(m.group(1)) or {}, m.group(2)


def _write_agent_file(path: str, fm: dict, body: str) -> None:
    """Write an agents/{name}/agent.md file."""
    fm_str = yaml.dump(fm, default_flow_style=False, sort_keys=False).rstrip()
    content = f'---\n{fm_str}\n---\n{body}'
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        f.write(content)


def _parse_skill_file(path: str) -> tuple[dict, str]:
    """Parse a SKILL.md file.  Returns (frontmatter_dict, body_text)."""
    with open(path) as f:
        content = f.read()
    m = re.match(r'^---\n(.*?\n)---\n(.*)', content, re.DOTALL)
    if not m:
        return {}, content
    return yaml.safe_load(m.group(1)) or {}, m.group(2)


def _write_skill_file(path: str, fm: dict, body: str) -> None:
    """Write a SKILL.md file."""
    fm_str = yaml.dump(fm, default_flow_style=False, sort_keys=False).rstrip()
    content = f'---\n{fm_str}\n---\n{body}'
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        f.write(content)


def _load_settings(settings_path: str) -> dict:
    """Load a settings.yaml file, returning default if missing."""
    if os.path.exists(settings_path):
        with open(settings_path) as f:
            try:
                return yaml.safe_load(f) or {'hooks': {}}
            except yaml.YAMLError:
                return {'hooks': {}}
    return {'hooks': {}}


def _save_settings(settings_path: str, data: dict) -> None:
    os.makedirs(os.path.dirname(settings_path), exist_ok=True)
    with open(settings_path, 'w') as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)


def _load_teaparty_yaml(teaparty_home: str) -> dict:
    path = os.path.join(teaparty_home, 'management', 'teaparty.yaml')
    if not os.path.exists(path):
        raise FileNotFoundError(f'teaparty.yaml not found: {path}')
    with open(path) as f:
        return yaml.safe_load(f) or {}


def _save_teaparty_yaml(teaparty_home: str, data: dict) -> None:
    path = os.path.join(teaparty_home, 'management', 'teaparty.yaml')
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)


