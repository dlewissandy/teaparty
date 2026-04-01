"""Agent spawner: worktree creation, skill composition, and claude -p invocation.

Each agent receives an isolated git worktree with a composed .claude/skills/ directory.
Skills are layered: common → role → project (project wins on name collision).

Skill directory structure in teaparty_home:
  {teaparty_home}/skills/common/{skill_name}/SKILL.md
  {teaparty_home}/skills/roles/{role}/{skill_name}/SKILL.md

Project skills:
  {project_dir}/.claude/skills/{skill_name}/SKILL.md

See docs/proposals/agent-dispatch/references/invocation-model.md for the full spec.
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
from typing import Any

_log = logging.getLogger('orchestrator.agent_spawner')


def compose_skills(
    worktree: str,
    teaparty_home: str,
    role: str,
    *,
    project_dir: str = '',
) -> None:
    """Compose .claude/skills/ in the worktree from common + role + project layers.

    Layer order (first match wins on name collision):
      1. common — {teaparty_home}/skills/common/*
      2. role   — {teaparty_home}/skills/roles/{role}/*
      3. project — {project_dir}/.claude/skills/*  (highest priority)

    Each skill is a directory containing SKILL.md.  Composition uses symlinks so
    the composed directory stays thin; callers can resolve symlinks if needed.

    Args:
        worktree: Path to the agent's git worktree.
        teaparty_home: TeaParty installation root (contains skills/).
        role: The agent's role name (used to locate role-specific skills).
        project_dir: Optional project directory for project-scoped skill overrides.
    """
    skills_dest = os.path.join(worktree, '.claude', 'skills')
    os.makedirs(skills_dest, exist_ok=True)

    # Layer 1: common skills (lowest priority — overridden by role and project)
    _link_skills(
        os.path.join(teaparty_home, 'skills', 'common'),
        skills_dest,
        overwrite=False,
    )

    # Layer 2: role-specific skills (override common on name collision)
    _link_skills(
        os.path.join(teaparty_home, 'skills', 'roles', role),
        skills_dest,
        overwrite=True,
    )

    # Layer 3: project skills (highest priority — override everything)
    if project_dir:
        _link_skills(
            os.path.join(project_dir, '.claude', 'skills'),
            skills_dest,
            overwrite=True,
        )


def _link_skills(source_dir: str, dest_dir: str, *, overwrite: bool) -> None:
    """Symlink each skill directory from source_dir into dest_dir.

    Args:
        source_dir: Directory containing skill subdirectories (may not exist).
        dest_dir:   Destination .claude/skills/ directory.
        overwrite:  When True, replace an existing symlink with the new source.
    """
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
      - A composed .claude/skills/ directory
      - --bare to suppress user-level auto-discovery
      - --output-format json to capture session_id

    The caller is responsible for creating and cleaning up the git worktree.
    compose_skills() and spawn() are separable so tests can exercise each
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
    ) -> str:
        """Spawn an independent claude -p process and return its session_id.

        Composes .claude/skills/ in the worktree first, then launches claude.
        The task_message is passed as the $TASK prompt.

        Args:
            task_message: The composite Task/Context message delivered as the prompt.
            worktree:     Path to the agent's git worktree.
            role:         Agent role, used for skill composition.
            project_dir:  Project directory for project-scoped skills.
            mcp_config:   MCP server config dict written to --settings inline JSON.
            resume_session: If set, passes --resume <session_id> instead of fresh start.
            extra_env:    Additional environment variables for the process.

        Returns:
            The claude session_id captured from --output-format json output.
            Returns empty string if not captured (non-fatal; caller handles gracefully).
        """
        compose_skills(worktree, self.teaparty_home, role, project_dir=project_dir)

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
