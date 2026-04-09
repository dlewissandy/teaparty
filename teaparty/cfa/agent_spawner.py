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

_log = logging.getLogger('teaparty.cfa.agent_spawner')


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
    import time as _time
    t0 = _time.monotonic()
    compose_claude_md(worktree, teaparty_home, project_dir=project_dir,
                      is_management=is_management)
    t1 = _time.monotonic()
    # Only include the agent's own definition — not the full roster.
    # Agents discover teammates via MCP ListTeamMembers.
    own_agent = catalog_agents if catalog_agents is not None else [role]
    compose_agents(worktree, teaparty_home, project_dir=project_dir,
                   catalog_agents=own_agent, is_management=is_management)
    t2 = _time.monotonic()
    compose_skills(worktree, teaparty_home, role, project_dir=project_dir,
                   catalog_skills=catalog_skills)
    t3 = _time.monotonic()
    compose_settings(worktree, teaparty_home, project_dir=project_dir,
                     agent_name=agent_name, is_management=is_management)
    t4 = _time.monotonic()
    # Determine project name for MCP URL scope
    _project_name = ''
    if project_dir and not is_management:
        _project_name = os.path.basename(project_dir)
    compose_mcp_config(worktree, role,
                       scope='management' if is_management else 'project',
                       project_name=_project_name)
    t5 = _time.monotonic()
    _log.info(
        'compose_worktree_timing: role=%r claude_md=%.3fs agents=%.3fs '
        'skills=%.3fs settings=%.3fs mcp=%.3fs total=%.3fs',
        role, t1 - t0, t2 - t1, t3 - t2, t4 - t3, t5 - t4, t5 - t0,
    )


def compose_mcp_config(
    worktree: str,
    agent_name: str,
    *,
    scope: str = 'management',
    project_name: str = '',
    mcp_port: int = 8082,
) -> None:
    """Write a per-agent .mcp.json pointing to the shared HTTP MCP server.

    The URL encodes the scope so the server returns only this agent's
    allowed tools:
        /mcp/management/{agent}     — management-scoped
        /mcp/{project}/{agent}      — project-scoped (overrides management)
    """
    import json as _json

    if project_name and project_name != 'management':
        path = f'/mcp/{project_name}/{agent_name}'
    else:
        path = f'/mcp/management/{agent_name}'

    mcp_config = {
        'mcpServers': {
            'teaparty-config': {
                'type': 'http',
                'url': f'http://localhost:{mcp_port}{path}',
            },
        },
    }
    mcp_path = os.path.join(worktree, '.mcp.json')
    with open(mcp_path, 'w') as f:
        _json.dump(mcp_config, f, indent=2)


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
    """Symlink the agent's OWN definition into worktree .claude/agents/.

    Only the agent's own definition is included — NOT the full roster.
    Claude Code enables its builtin SendMessage when it sees multiple
    agents in .claude/agents/, which bypasses TeaParty's bus listener.
    Agents discover teammates via mcp__teaparty-config__ListTeamMembers.

    catalog_agents controls which agents are included. Typically this
    is just the agent itself (single-element list).
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

    # Clean out old agent symlinks to prevent stale roster
    for existing in os.scandir(dest_dir):
        if existing.is_symlink() or existing.name.endswith('.md'):
            os.unlink(existing.path)

    for entry in os.scandir(source_dir):
        if not entry.is_dir():
            continue
        if catalog_agents is not None and entry.name not in catalog_agents:
            continue
        agent_md = os.path.join(entry.path, 'agent.md')
        if not os.path.exists(agent_md):
            continue
        dest_link = os.path.join(dest_dir, entry.name)
        if os.path.lexists(dest_link):
            os.unlink(dest_link)
        os.symlink(entry.path, dest_link)
        dest_md = os.path.join(dest_dir, entry.name + '.md')
        if os.path.lexists(dest_md):
            os.unlink(dest_md)
        os.symlink(agent_md, dest_md)


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


def _parse_json_output(output: str) -> tuple[str, str]:
    """Parse claude --output-format json output.

    Returns (session_id, result_text).  Both may be empty if not found.
    """
    session_id = ''
    result_text = ''
    for line in output.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        if not session_id:
            if 'session_id' in obj:
                session_id = str(obj['session_id'])
            elif obj.get('type') == 'system' and 'session_id' in obj.get('data', {}):
                session_id = str(obj['data']['session_id'])
        if not result_text and 'result' in obj:
            result_text = str(obj['result'])
    return session_id, result_text


def _read_agent_model(
    role: str,
    teaparty_home: str,
    is_management: bool = False,
) -> str:
    """Read the model from an agent's frontmatter.

    Returns the model string (e.g. 'claude-sonnet-4-5') or '' if not found.
    """
    try:
        from teaparty.config.config_reader import read_agent_frontmatter
        if is_management:
            agent_path = os.path.join(
                teaparty_home, 'management', 'agents', role, 'agent.md',
            )
        else:
            agent_path = ''
        if agent_path and os.path.isfile(agent_path):
            fm = read_agent_frontmatter(agent_path)
            return fm.get('model', '')
    except Exception:
        pass
    return ''


def _derive_roster(
    role: str,
    teaparty_home: str,
    *,
    project_dir: str = '',
) -> dict[str, Any] | None:
    """Auto-derive the --agents roster for an agent based on its position.

    Checks whether the agent is a workgroup lead or project lead and builds
    the roster dict from the corresponding YAML definition.  Returns None
    if the agent has no sub-agents.
    """
    try:
        from teaparty.config.roster import (
            derive_workgroup_roster,
            derive_project_roster,
        )
        from teaparty.config.config_reader import load_management_team

        mgmt_agents_dir = os.path.join(teaparty_home, 'management', 'agents')

        # Check workgroup lead
        wg_dir = os.path.join(teaparty_home, 'workgroups')
        if os.path.isdir(wg_dir):
            for entry in os.scandir(wg_dir):
                if not entry.name.endswith('.yaml'):
                    continue
                try:
                    import yaml
                    with open(entry.path) as f:
                        wg = yaml.safe_load(f) or {}
                    if wg.get('lead') == role:
                        roster = derive_workgroup_roster(
                            entry.path,
                            agents_dir=mgmt_agents_dir,
                            teaparty_home=teaparty_home,
                        )
                        if roster:
                            return roster
                except Exception:
                    continue

        # Check project lead
        if project_dir:
            try:
                roster = derive_project_roster(
                    teaparty_home,
                    project_dir=project_dir,
                    agents_dir=mgmt_agents_dir,
                )
                if roster:
                    return roster
            except Exception:
                pass

    except Exception:
        _log.debug('_derive_roster failed for role=%r', role, exc_info=True)

    return None


class AgentSpawner:
    """Spawns independent claude -p processes for agent-to-agent dispatch.

    Each spawned agent gets:
      - A git worktree (created by the caller via git worktree add)
      - A composed .claude/ directory (CLAUDE.md, agents, skills, settings.json)
      - --agent <role> to select the agent definition
      - --output-format json to capture session_id
      - --setting-sources user to preserve OAuth auth

    spawn() is async so the event loop stays alive during child execution,
    enabling recursive dispatch (child agents calling Send to grandchildren).

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

    async def spawn(
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
        agents_json: dict[str, Any] | None = None,
    ) -> tuple[str, str]:
        """Spawn an independent claude -p process and return (session_id, result_text).

        Async so the event loop stays alive during execution — this is what
        enables recursive dispatch.  A child agent calling Send posts to the
        parent's BusEventListener socket, which the event loop processes
        while this coroutine awaits the child process.

        Composes .claude/ in the worktree first, then launches claude with
        --agent <role> to select the agent definition and --agents <json>
        to provide the roster of available sub-agents.

        Args:
            task_message: The composite Task/Context message delivered as the prompt.
            worktree:     Path to the agent's git worktree.
            role:         Agent role — used for skill composition and passed as
                          --agent <role> so Claude Code uses the correct definition.
            project_dir:  Project directory for project-scoped sources.
            mcp_config:   MCP server config dict.  Passed via --settings so the
                          spawned agent's MCP server has the correct socket paths.
            resume_session: If set, passes --resume <session_id> instead of fresh start.
            extra_env:    Additional environment variables for the process.
            catalog_agents: Agent names to include in worktree (workgroup catalog).
            catalog_skills: Skill names to include in worktree (workgroup catalog).
            agent_name:   Name of dispatched agent (for agent-level settings).
            is_management: True for management-team dispatches.
            agents_json:  Roster dict ``{name: {description: ...}}`` passed as
                          --agents so the agent knows its available sub-agents.
                          If None, no --agents flag is passed.

        Returns:
            (session_id, result_text) from --output-format json output.
            Either may be empty if not captured (non-fatal).
        """
        import asyncio
        import time as _time

        t_start = _time.monotonic()

        compose_worktree(
            worktree, self.teaparty_home, role,
            project_dir=project_dir,
            catalog_agents=catalog_agents,
            catalog_skills=catalog_skills,
            agent_name=agent_name,
            is_management=is_management,
        )
        t_compose = _time.monotonic()

        # Auto-derive roster if not explicitly provided.  If the agent is a
        # workgroup or project lead, it needs to know its team members.
        if agents_json is None:
            agents_json = _derive_roster(
                role, self.teaparty_home, project_dir=project_dir,
            )
        t_roster = _time.monotonic()

        env = dict(os.environ)
        env.pop('AGENT_TOOL_SCOPE', None)
        env.update(self.env_vars)
        if extra_env:
            env.update(extra_env)

        # Performance env vars: eliminate telemetry network calls and
        # reduce MCP connection timeout for fast local stdio servers.
        env.setdefault('DISABLE_NONESSENTIAL_TRAFFIC', '1')
        env.setdefault('MCP_TIMEOUT', '5000')

        # Tool scope for the MCP server:
        # - Leads (have roster): dispatch scope (Send + read, ~14 tools)
        # - Leaf specialists (no roster, have MCP): full tools (Create/Edit/etc.)
        # - No MCP at all: irrelevant
        tool_scope = 'dispatch' if agents_json else ''
        scope_file = os.path.join(worktree, '.tool-scope')
        with open(scope_file, 'w') as f:
            f.write(tool_scope)

        # Read agent settings from the composed worktree.
        settings_path = os.path.join(worktree, '.claude', 'settings.json')
        settings_dict = {}
        if os.path.isfile(settings_path):
            with open(settings_path) as f:
                import json as _json
                try:
                    settings_dict = _json.loads(f.read())
                except (ValueError, _json.JSONDecodeError):
                    pass

        # All agents use default builtin tools. MCP tool filtering is
        # handled per-agent by compose_mcp_config (--agent flag in .mcp.json).
        # Never pass --agents — it enables Claude Code's builtin SendMessage
        # which bypasses the TeaParty bus listener.
        cmd = [self.claude_cmd, '-p', '--output-format', 'json',
               '--agent', role,
               '--setting-sources', 'user']

        if settings_dict:
            cmd += ['--settings', json.dumps(settings_dict)]

        if resume_session:
            cmd += ['--resume', resume_session]

        # Pass MCP config when provided.  Leads need Send; leaf specialists
        # need CreateAgent/EditWorkgroup etc.  Only skip if no config at all.
        if mcp_config:
            cmd += ['--mcp-config', json.dumps({'mcpServers': mcp_config}),
                    '--strict-mcp-config']

        cmd.append(task_message)
        t_cmd = _time.monotonic()

        _log.info(
            'spawn: role=%r worktree=%r resume=%r mcp=%s',
            role, worktree, bool(resume_session), bool(mcp_config),
        )

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=worktree,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )
            t_proc_started = _time.monotonic()

            stdout_bytes, stderr_bytes = await proc.communicate()
            t_proc_done = _time.monotonic()

            stdout = stdout_bytes.decode() if stdout_bytes else ''
            stderr = stderr_bytes.decode() if stderr_bytes else ''
        except FileNotFoundError:
            _log.warning('claude command not found at %r; agent spawn skipped', self.claude_cmd)
            return '', ''

        session_id, result_text = _parse_json_output(stdout)
        t_parse = _time.monotonic()

        _log.info(
            'spawn_timing: role=%r compose=%.2fs roster=%.2fs cmd_build=%.2fs '
            'proc_start=%.2fs proc_run=%.2fs parse=%.2fs total=%.2fs',
            role,
            t_compose - t_start,
            t_roster - t_compose,
            t_cmd - t_roster,
            t_proc_started - t_cmd,
            t_proc_done - t_proc_started,
            t_parse - t_proc_done,
            t_parse - t_start,
        )

        if not session_id:
            _log.warning(
                'spawn: no session_id from claude (exit=%d) stderr=%s',
                proc.returncode, stderr[:500] if stderr else '',
            )
        return session_id, result_text
