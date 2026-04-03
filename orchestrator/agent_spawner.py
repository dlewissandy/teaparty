"""Agent spawner: worktree composition and claude -p invocation.

TeaParty owns agent/skill/settings sources under .teaparty/. At dispatch time,
the worktree composer assembles the subset each agent needs into the worktree's
.claude/ directory — which is what Claude Code reads at runtime.

Composition:
  .claude/CLAUDE.md   ← project.md or management.md (rules/conventions)
  .claude/agents/     ← only agents in the workgroup catalog (symlinked)
  .claude/skills/     ← layered: common → role → project (symlinked)
  .claude/settings.json ← project settings.yaml + agent settings.yaml → JSON

Source layout:
  {teaparty_home}/management/agents/{name}/agent.md
  {teaparty_home}/management/skills/{name}/SKILL.md
  {teaparty_home}/management/settings.yaml
  {teaparty_home}/management/management.md
  {project_dir}/.teaparty/project/agents/{name}/agent.md
  {project_dir}/.teaparty/project/skills/{name}/SKILL.md
  {project_dir}/.teaparty/project/settings.yaml
  {project_dir}/.teaparty/project/project.md

See docs/proposals/agent-dispatch/references/invocation-model.md for the full spec.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
from typing import Any

import yaml

_log = logging.getLogger('orchestrator.agent_spawner')


# ── Worktree composer ────────────────────────────────────────────────────────

def compose_worktree(
    worktree: str,
    teaparty_home: str,
    role: str,
    *,
    project_dir: str = '',
    catalog_agents: list[str] | None = None,
    catalog_skills: list[str] | None = None,
    agent_name: str = '',
    is_management: bool = False,
) -> None:
    """Compose the full .claude/ directory in a worktree for dispatch.

    Assembles CLAUDE.md, agents, skills, and settings from .teaparty/ sources
    into the worktree's .claude/ so Claude Code can consume them.

    Args:
        worktree: Path to the agent's git worktree.
        teaparty_home: TeaParty installation root (.teaparty/).
        role: Agent role, used for skill composition layering.
        project_dir: Project directory for project-level sources.
        catalog_agents: Agent names to include (workgroup catalog).
            If None, all discovered agents are included.
        catalog_skills: Skill names to include (workgroup lead's catalog).
            If None, all skills from the layered composition are included.
        agent_name: Name of the dispatched agent (for agent-level settings).
        is_management: True for management-team dispatches (uses management.md).
    """
    compose_claude_md(worktree, teaparty_home, project_dir=project_dir,
                      is_management=is_management)
    compose_agents(worktree, teaparty_home, project_dir=project_dir,
                   catalog_agents=catalog_agents, is_management=is_management)
    compose_skills(worktree, teaparty_home, role, project_dir=project_dir,
                   catalog_skills=catalog_skills)
    compose_settings(worktree, teaparty_home, project_dir=project_dir,
                     agent_name=agent_name, is_management=is_management)


def compose_claude_md(
    worktree: str,
    teaparty_home: str,
    *,
    project_dir: str = '',
    is_management: bool = False,
) -> None:
    """Copy project.md or management.md into worktree as .claude/CLAUDE.md."""
    if is_management:
        source = os.path.join(teaparty_home, 'management', 'management.md')
    elif project_dir:
        source = os.path.join(project_dir, '.teaparty', 'project', 'project.md')
    else:
        return
    if not os.path.isfile(source):
        return
    dest = os.path.join(worktree, '.claude', 'CLAUDE.md')
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    shutil.copy2(source, dest)


def compose_agents(
    worktree: str,
    teaparty_home: str,
    *,
    project_dir: str = '',
    catalog_agents: list[str] | None = None,
    is_management: bool = False,
) -> None:
    """Symlink agents from .teaparty/ sources into worktree .claude/agents/.

    Only agents named in catalog_agents are included. If catalog_agents is
    None, all discovered agents from the source directory are included.
    """
    if is_management:
        source_dir = os.path.join(teaparty_home, 'management', 'agents')
    elif project_dir:
        source_dir = os.path.join(project_dir, '.teaparty', 'project', 'agents')
    else:
        return
    if not os.path.isdir(source_dir):
        return
    dest_dir = os.path.join(worktree, '.claude', 'agents')
    os.makedirs(dest_dir, exist_ok=True)

    for entry in os.scandir(source_dir):
        if not entry.is_dir():
            continue
        if catalog_agents is not None and entry.name not in catalog_agents:
            continue
        if not os.path.exists(os.path.join(entry.path, 'agent.md')):
            continue
        dest_link = os.path.join(dest_dir, entry.name)
        if os.path.lexists(dest_link):
            os.unlink(dest_link)
        os.symlink(entry.path, dest_link)


def compose_skills(
    worktree: str,
    teaparty_home: str,
    role: str,
    *,
    project_dir: str = '',
    catalog_skills: list[str] | None = None,
) -> None:
    """Compose .claude/skills/ in the worktree from layered sources.

    Layer order (later layers override on name collision):
      1. common — {teaparty_home}/skills/common/*
      2. role   — {teaparty_home}/skills/roles/{role}/*
      3. project — {project_dir}/.teaparty/project/skills/*

    If catalog_skills is provided, only those skills are kept after composition.
    """
    skills_dest = os.path.join(worktree, '.claude', 'skills')
    os.makedirs(skills_dest, exist_ok=True)

    # Layer 1: common skills (lowest priority)
    _link_skills(
        os.path.join(teaparty_home, 'skills', 'common'),
        skills_dest,
        overwrite=False,
    )

    # Layer 2: role-specific skills (override common)
    _link_skills(
        os.path.join(teaparty_home, 'skills', 'roles', role),
        skills_dest,
        overwrite=True,
    )

    # Layer 3: project skills (highest priority)
    if project_dir:
        _link_skills(
            os.path.join(project_dir, '.teaparty', 'project', 'skills'),
            skills_dest,
            overwrite=True,
        )

    # Filter to catalog if specified
    if catalog_skills is not None:
        catalog_set = set(catalog_skills)
        for entry in os.scandir(skills_dest):
            if entry.name not in catalog_set:
                if entry.is_symlink() or entry.is_file():
                    os.unlink(entry.path)
                elif entry.is_dir():
                    shutil.rmtree(entry.path)


def compose_settings(
    worktree: str,
    teaparty_home: str,
    *,
    project_dir: str = '',
    agent_name: str = '',
    is_management: bool = False,
) -> None:
    """Merge settings YAML and write .claude/settings.json for Claude Code.

    Base: project settings.yaml (or management settings.yaml).
    Override: agent settings.yaml (agent wins per-key).
    Output: JSON in Claude Code's native format.
    """
    if is_management:
        base_path = os.path.join(teaparty_home, 'management', 'settings.yaml')
    elif project_dir:
        base_path = os.path.join(project_dir, '.teaparty', 'project', 'settings.yaml')
    else:
        return

    base = _load_yaml(base_path)
    if not base:
        base = {}

    # Agent-level override
    if agent_name:
        if is_management:
            agent_settings = os.path.join(
                teaparty_home, 'management', 'agents', agent_name, 'settings.yaml')
        elif project_dir:
            agent_settings = os.path.join(
                project_dir, '.teaparty', 'project', 'agents', agent_name, 'settings.yaml')
        else:
            agent_settings = ''
        if agent_settings:
            override = _load_yaml(agent_settings)
            if override:
                base = _deep_merge(base, override)

    dest = os.path.join(worktree, '.claude', 'settings.json')
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    with open(dest, 'w') as f:
        json.dump(base, f, indent=2)


def _load_yaml(path: str) -> dict | None:
    """Load a YAML file, returning None if missing or empty."""
    if not os.path.isfile(path):
        return None
    with open(path) as f:
        return yaml.safe_load(f) or None


def _deep_merge(base: dict, override: dict) -> dict:
    """Deep-merge override into base. Override values win on collision."""
    result = dict(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _link_skills(source_dir: str, dest_dir: str, *, overwrite: bool) -> None:
    """Symlink each skill directory from source_dir into dest_dir."""
    if not os.path.isdir(source_dir):
        return
    for entry in os.scandir(source_dir):
        if not entry.is_dir(follow_symlinks=False):
            continue
        dest_link = os.path.join(dest_dir, entry.name)
        if os.path.lexists(dest_link):
            if overwrite:
                os.unlink(dest_link)
            else:
                continue
        os.symlink(entry.path, dest_link)


def _extract_session_id(output: str) -> str:
    """Extract session_id from claude --output-format json output.

    Scans output lines for the system/init event that carries session_id.
    Falls back to parsing any JSON line with a 'session_id' key.

    Returns empty string if not found.
    """
    for line in output.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        # Stream JSON events: look for session_id at the top level
        if 'session_id' in obj:
            return str(obj['session_id'])
        # Nested in system/init event
        if obj.get('type') == 'system' and 'session_id' in obj.get('data', {}):
            return str(obj['data']['session_id'])
    return ''


class AgentSpawner:
    """Spawns independent claude -p processes for agent-to-agent dispatch.

    Each spawned agent gets:
      - A git worktree (created by the caller via git worktree add)
      - A composed .claude/ directory (CLAUDE.md, agents, skills, settings.json)
      - --bare to suppress user-level auto-discovery
      - --output-format json to capture session_id

    The caller is responsible for creating and cleaning up the git worktree.
    compose_worktree() and spawn() are separable so tests can exercise each
    step independently.
    """

    def __init__(
        self,
        teaparty_home: str,
        *,
        claude_cmd: str = 'claude',
        env_vars: dict[str, str] | None = None,
    ) -> None:
        self.teaparty_home = teaparty_home
        self.claude_cmd = claude_cmd
        self.env_vars = env_vars or {}

    def spawn(
        self,
        task_message: str,
        *,
        worktree: str,
        role: str,
        project_dir: str = '',
        mcp_config: dict[str, Any] | None = None,
        resume_session: str = '',
        extra_env: dict[str, str] | None = None,
        catalog_agents: list[str] | None = None,
        catalog_skills: list[str] | None = None,
        agent_name: str = '',
        is_management: bool = False,
    ) -> str:
        """Spawn an independent claude -p process and return its session_id.

        Composes .claude/ in the worktree first, then launches claude.
        The task_message is passed as the $TASK prompt.

        Args:
            task_message: The composite Task/Context message delivered as the prompt.
            worktree:     Path to the agent's git worktree.
            role:         Agent role, used for skill composition.
            project_dir:  Project directory for project-scoped sources.
            mcp_config:   MCP server config dict written to --settings inline JSON.
            resume_session: If set, passes --resume <session_id> instead of fresh start.
            extra_env:    Additional environment variables for the process.
            catalog_agents: Agent names to include in worktree (workgroup catalog).
            catalog_skills: Skill names to include in worktree (workgroup catalog).
            agent_name:   Name of dispatched agent (for agent-level settings).
            is_management: True for management-team dispatches.

        Returns:
            The claude session_id captured from --output-format json output.
            Returns empty string if not captured (non-fatal; caller handles gracefully).
        """
        compose_worktree(
            worktree, self.teaparty_home, role,
            project_dir=project_dir,
            catalog_agents=catalog_agents,
            catalog_skills=catalog_skills,
            agent_name=agent_name,
            is_management=is_management,
        )

        env = dict(os.environ)
        env.update(self.env_vars)
        if extra_env:
            env.update(extra_env)

        cmd = [self.claude_cmd, '-p', '--output-format', 'json', '--bare']

        if resume_session:
            cmd += ['--resume', resume_session]

        if mcp_config:
            cmd += ['--settings', json.dumps({'mcpServers': mcp_config})]

        cmd.append(task_message)

        try:
            result = subprocess.run(
                cmd,
                cwd=worktree,
                capture_output=True,
                text=True,
                env=env,
            )
        except FileNotFoundError:
            _log.warning('claude command not found at %r; agent spawn skipped', self.claude_cmd)
            return ''

        session_id = _extract_session_id(result.stdout)
        if not session_id:
            _log.debug(
                'Could not extract session_id from claude output (exit=%d)', result.returncode,
            )
        return session_id
