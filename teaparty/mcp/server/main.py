"""MCP server for agent escalation, dispatch, intervention, and config tools.

FastMCP setup and tool registration. Handler logic lives in
teaparty.mcp.tools.{escalation, messaging, intervention, config_crud}.
Helper functions live in teaparty.mcp.tools.config_helpers.
"""
from __future__ import annotations

import os

import yaml
from mcp.server import FastMCP

# ── Handler imports ─────────────────────────────────────────────────────────

from teaparty.mcp.tools.escalation import (
    ask_question_handler,
    _scratch_path_from_env,
)

from teaparty.mcp.tools.messaging import (
    send_handler,
    close_conversation_handler,
)

from teaparty.mcp.tools.intervention import (
    intervention_handler,
)

from teaparty.mcp.tools.config_crud import (
    add_project_handler,
    create_agent_handler,
    create_hook_handler,
    create_project_handler,
    create_scheduled_task_handler,
    create_skill_handler,
    create_workgroup_handler,
    edit_agent_handler,
    edit_hook_handler,
    edit_scheduled_task_handler,
    edit_skill_handler,
    edit_workgroup_handler,
    get_agent_handler,
    get_project_handler,
    get_skill_handler,
    get_workgroup_handler,
    list_agents_handler,
    list_hooks_handler,
    list_pins_handler,
    list_projects_handler,
    list_scheduled_tasks_handler,
    list_skills_handler,
    list_team_members_handler,
    list_workgroups_handler,
    pin_artifact_handler,
    project_status_handler,
    remove_agent_handler,
    remove_hook_handler,
    remove_project_handler,
    remove_scheduled_task_handler,
    remove_skill_handler,
    remove_workgroup_handler,
    scaffold_project_yaml_handler,
    unpin_artifact_handler,
)

from teaparty.mcp.tools.config_helpers import _parse_agent_file

from teaparty.mcp.tools.research import (
    youtube_transcript_handler,
    arxiv_search_handler,
    semantic_scholar_search_handler,
    pubmed_search_handler,
)
from teaparty.mcp.tools.patent import (
    patent_search_uspto_handler,
    patent_search_epo_handler,
)
from teaparty.mcp.tools.image_gen import (
    image_gen_openai_handler,
    image_gen_flux_handler,
    image_gen_stability_handler,
)


MCP_SERVER_NAME = 'teaparty-config'


# Shared messaging discipline — used in the Send / AskQuestion tool
# descriptions.  Keep in one place so the wording stays consistent.
_SCRATCH_DISCLOSURE = (
    'Only if the message would run long, put the detail in '
    '`.scratch/<name>.md` and reference the path. `.scratch/` is '
    "gitignored; its contents snapshot to the child's worktree at "
    'Send time.'
)


def list_mcp_tool_names() -> list[str]:
    """Return the namespaced tool names exposed by the teaparty-config MCP server.

    Used by the bridge catalog API so the config UI can display all
    available tools without hardcoding them.  The names use Claude Code's
    ``mcp__{server}__{tool}`` convention.
    """
    server = create_server()
    prefix = f'mcp__{MCP_SERVER_NAME}__'
    return [prefix + name for name in sorted(server._tool_manager._tools)]



def create_server(agent_tools: set[str] | None = None) -> FastMCP:
    """Create the MCP server, optionally filtered to a set of tool names.

    Args:
        agent_tools: If provided, only register tools whose names are in
            this set. When None, all tools are registered (interactive session).
    """
    import logging as _logging
    _cs_log = _logging.getLogger('teaparty.mcp.server.main.create')

    # json_response=False → POST tool responses use SSE streaming.
    # This is required for long-running tools like Send: SSE keepalive
    # pings prevent the client from timing out while the tool blocks.
    server = FastMCP('teaparty-config', json_response=False)


    @server.tool(description=(
        'Ask a question; routed to the appropriate responder.\n\n'
        "Self-contained: the responder hasn't seen your conversation. "
        'Name the situation, the decision, options ruled out, and what '
        'their answer commits them to. "Should I proceed?" is a misuse.'
        '\n\n' + _SCRATCH_DISCLOSURE + '\n\n'
        'Args:\n'
        '    question: Your question, self-contained per the above.\n'
        '    context: Ignored when a scratch file is present.'
    ))
    async def AskQuestion(question: str, context: str = '') -> str:
        """Ask a question; routed to the appropriate responder."""
        return await ask_question_handler(
            question=question,
            context=context,
            scratch_path=_scratch_path_from_env(),
        )

    @server.tool()
    async def Send(member: str, message: str, context_id: str = '') -> str:
        """Send a message to a roster member, opening or continuing a thread.

        Self-contained: the recipient hasn't seen your conversation.
        Name the work, definition of done, pointers to authoritative
        context, and what you've decided or ruled out. "Write the
        essay" is a misuse; continuing a thread doesn't excuse you.

        Only if the message would run long, put the detail in
        `.scratch/<name>.md` and reference the path. `.scratch/` is
        gitignored; its contents snapshot to the child's worktree at
        Send time.

        After Send your turn ends; TeaParty re-invokes you on reply.

        Args:
            member: Name key of a roster entry in --agents.
            message: The task or question, self-contained per the above.
            context_id: Existing context ID to continue a thread; omit
                to open a new one.
        """
        return await send_handler(
            member=member,
            message=message,
            context_id=context_id,
            scratch_path=_scratch_path_from_env(),
        )

    @server.tool()
    async def CloseConversation(conversation_id: str) -> str:
        """Close a dispatch conversation you opened via Send.

        Recursively tears down the child agent and any conversations it
        opened. Kills running processes, cleans up worktrees, and frees
        the conversation slot so you can dispatch again.

        Only the originator of the conversation should call this.

        Args:
            conversation_id: The conversation_id returned by Send
                (e.g. "dispatch:abc123").
        """
        return await close_conversation_handler(context_id=conversation_id)

    @server.tool()
    async def WithdrawSession(session_id: str) -> str:
        """Withdraw a session, setting its CfA state to WITHDRAWN.

        This is a team-lead authority action. It terminates the session
        and finalizes its heartbeat. Use when a session should be stopped
        entirely — the work is no longer needed or the approach is wrong.

        Args:
            session_id: The session to withdraw.
        """
        return await intervention_handler(
            'withdraw_session', session_id=session_id,
        )

    @server.tool()
    async def PauseDispatch(dispatch_id: str) -> str:
        """Pause a running dispatch.

        A paused dispatch will not launch new phases. Work already in
        progress completes but no new work starts. Use when you need
        to temporarily halt a dispatch without terminating it.

        Args:
            dispatch_id: The dispatch to pause.
        """
        return await intervention_handler(
            'pause_dispatch', dispatch_id=dispatch_id,
        )

    @server.tool()
    async def ResumeDispatch(dispatch_id: str) -> str:
        """Resume a paused dispatch.

        Restores the dispatch to running state so new phases can launch.
        Only works on dispatches that are currently paused.

        Args:
            dispatch_id: The dispatch to resume.
        """
        return await intervention_handler(
            'resume_dispatch', dispatch_id=dispatch_id,
        )

    @server.tool()
    async def ReprioritizeDispatch(dispatch_id: str, priority: str) -> str:
        """Change the priority of a dispatch.

        Updates the dispatch's priority level. Only works on dispatches
        that are currently running or paused (not terminal).

        Args:
            dispatch_id: The dispatch to reprioritize.
            priority: The new priority level (e.g. 'high', 'normal', 'low').
        """
        return await intervention_handler(
            'reprioritize_dispatch', dispatch_id=dispatch_id, priority=priority,
        )

    # ── Read/list tools ──────────────────────────────────────────────────────

    @server.tool()
    async def ListProjects(teaparty_home: str = '') -> str:
        """List all registered projects.

        Returns project names and paths for all projects registered in
        teaparty.yaml (both inline and external-projects).

        Args:
            teaparty_home: Override for .teaparty/ directory path.
        """
        return list_projects_handler(teaparty_home=teaparty_home)

    @server.tool()
    async def GetProject(name: str, teaparty_home: str = '') -> str:
        """Get full configuration for a registered project.

        Returns the project's project.yaml contents including lead,
        decider, humans, workgroups, and artifact pins.

        Args:
            name: Project name as registered in teaparty.yaml.
            teaparty_home: Override for .teaparty/ directory path.
        """
        return get_project_handler(name=name, teaparty_home=teaparty_home)

    @server.tool()
    async def ProjectStatus(name: str, days: int = 7, teaparty_home: str = '') -> str:
        """Get a status summary for a project.

        Returns recent git commits and in-progress sessions/jobs.
        Use this to generate weekly status updates or check what
        is currently happening in a project.

        Args:
            name: Project name as registered in teaparty.yaml.
            days: Number of days of git history to include (default 7).
            teaparty_home: Override for .teaparty/ directory path.
        """
        return project_status_handler(name=name, days=days, teaparty_home=teaparty_home)

    @server.tool()
    async def ListTeamMembers(teaparty_home: str = '') -> str:
        """List the members of your team.

        Returns your direct reports derived from the team config:
        project leads, workgroup leads, and proxy agents. This is
        your team — use it to answer "who is on my team?".

        Args:
            teaparty_home: Override for .teaparty/ directory path.
        """
        return list_team_members_handler(teaparty_home=teaparty_home)

    @server.tool()
    async def ListAgents(project_root: str = '', scope: str = '') -> str:
        """List all agent definitions with summary info.

        Returns name, description, and model for each agent found in
        the agents/ directory. Note: this lists all definitions across
        the hierarchy, not just your team members.

        Args:
            project_root: Override for project root directory.
            scope: 'management' or a project name.
        """
        return list_agents_handler(project_root=project_root, scope=scope)

    @server.tool()
    async def GetAgent(name: str, project_root: str = '', scope: str = '') -> str:
        """Get full definition for a single agent.

        Returns all frontmatter fields (name, description, model, tools,
        maxTurns, skills) and the body text.

        Args:
            name: Agent name.
            project_root: Override for project root directory.
            scope: 'management' or a project name.
        """
        return get_agent_handler(name=name, project_root=project_root, scope=scope)

    @server.tool()
    async def ListSkills(project_root: str = '', scope: str = '') -> str:
        """List all skill definitions with summary info.

        Returns name, description, and user-invocable flag for each
        skill found in the skills/ directory.

        Args:
            project_root: Override for project root directory.
            scope: 'management' or a project name.
        """
        return list_skills_handler(project_root=project_root, scope=scope)

    @server.tool()
    async def GetSkill(name: str, project_root: str = '', scope: str = '') -> str:
        """Get full definition for a single skill.

        Returns all frontmatter fields and the body text.

        Args:
            name: Skill name.
            project_root: Override for project root directory.
            scope: 'management' or a project name.
        """
        return get_skill_handler(name=name, project_root=project_root, scope=scope)

    @server.tool()
    async def ListWorkgroups(teaparty_home: str = '', project: str = '') -> str:
        """List workgroup definitions with summary info.

        Returns name, description, and lead for each workgroup. When
        project is provided, only workgroups that are active members of
        that project team are returned.

        Args:
            teaparty_home: Override for .teaparty/ directory path.
            project: Project name to filter by active membership.
        """
        return list_workgroups_handler(teaparty_home=teaparty_home, project=project)

    @server.tool()
    async def GetWorkgroup(name: str, teaparty_home: str = '') -> str:
        """Get full configuration for a single workgroup.

        Returns all fields: name, description, lead, agents, skills, norms.

        Args:
            name: Workgroup name.
            teaparty_home: Override for .teaparty/ directory path.
        """
        return get_workgroup_handler(name=name, teaparty_home=teaparty_home)

    @server.tool()
    async def ListHooks(project_root: str = '') -> str:
        """List all hooks from settings.yaml.

        Returns each hook entry with its event, matcher, and handler
        configuration.

        Args:
            project_root: Override for project root directory.
        """
        return list_hooks_handler(project_root=project_root)

    @server.tool()
    async def ListScheduledTasks(teaparty_home: str = '') -> str:
        """List all scheduled tasks from teaparty.yaml.

        Returns each task with name, schedule, skill, args, and
        enabled status.

        Args:
            teaparty_home: Override for .teaparty/ directory path.
        """
        return list_scheduled_tasks_handler(teaparty_home=teaparty_home)

    @server.tool()
    async def ListPins(project: str, teaparty_home: str = '') -> str:
        """List all artifact pins for a project.

        Returns each pin's path and label from the project's
        artifact_pins list.

        Args:
            project: Project name as registered in teaparty.yaml.
            teaparty_home: Override for .teaparty/ directory path.
        """
        return list_pins_handler(project=project, teaparty_home=teaparty_home)

    @server.tool()
    async def AddProject(
        name: str,
        path: str,
        description: str = '',
        decider: str = '',
        teaparty_home: str = '',
    ) -> str:
        """Register an existing directory as a TeaParty project.

        Runs the full onboarding sequence: normalizes the name, scaffolds
        .teaparty/project/project.yaml, writes .gitignore, registers the
        project, scaffolds ``{name}-lead`` in the management catalog, and
        makes an initial commit. See docs/guides/project-onboarding.md.

        Args:
            name: Project name. Normalized to lowercase with hyphens.
            path: Absolute path to the existing project directory.
            description: Human-readable description. Defaults to the sentinel.
            decider: Human decider for this project.
            teaparty_home: Override for .teaparty/ directory path.
        """
        return add_project_handler(
            name=name, path=path, description=description,
            decider=decider, teaparty_home=teaparty_home,
        )

    @server.tool()
    async def CreateProject(
        name: str,
        path: str,
        description: str = '',
        decider: str = '',
        teaparty_home: str = '',
    ) -> str:
        """Create a new project directory with full scaffolding.

        Same onboarding sequence as AddProject, plus directory creation and
        ``git init``. See docs/guides/project-onboarding.md.

        Args:
            name: Project name. Normalized to lowercase with hyphens.
            path: Path for the new project directory (must not exist yet).
            description: Human-readable description. Defaults to the sentinel.
            decider: Human decider for this project.
            teaparty_home: Override for .teaparty/ directory path.
        """
        return create_project_handler(
            name=name, path=path, description=description,
            decider=decider, teaparty_home=teaparty_home,
        )

    @server.tool()
    async def RemoveProject(name: str, teaparty_home: str = '') -> str:
        """Remove a project from teaparty.yaml.

        The project directory is left untouched.  Only the teams: entry is removed.

        Args:
            name: Project name to remove.
            teaparty_home: Override for .teaparty/ directory path.
        """
        return remove_project_handler(name=name, teaparty_home=teaparty_home)

    @server.tool()
    async def ScaffoldProjectYaml(
        project_path: str,
        name: str,
        description: str = '',
        lead: str = '',
        decider: str = '',
        agents: str = '',
        humans: str = '',
        workgroups: str = '',
        skills: str = '',
    ) -> str:
        """Create or overwrite .teaparty/project/project.yaml for an existing project.

        Use this to retroactively fix a project.yaml that was created without
        required fields (e.g. empty lead or decider).  Always overwrites.

        Args:
            project_path: Absolute path to the project directory.
            name: Project name.
            description: Short description.
            lead: Agent name for project lead.
            decider: Human decider name.
            agents: Comma-separated agent names.
            humans: YAML list of human entries.
            workgroups: YAML list of workgroup entries.
            skills: Comma-separated skill names.
        """
        agents_list = [a.strip() for a in agents.split(',') if a.strip()] if agents else None
        humans_list = yaml.safe_load(humans) if humans else None
        workgroups_list = yaml.safe_load(workgroups) if workgroups else None
        skills_list = [s.strip() for s in skills.split(',') if s.strip()] if skills else None
        return scaffold_project_yaml_handler(
            project_path=project_path, name=name,
            description=description, lead=lead, decider=decider,
            agents=agents_list, humans=humans_list,
            workgroups=workgroups_list, skills=skills_list,
        )

    @server.tool()
    async def CreateAgent(
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
        """Create a new agent definition at agents/{name}/agent.md.

        Args:
            name: Agent name (becomes the filename).
            description: One-line description used for auto-invocation matching.
            model: Claude model ID (e.g. claude-sonnet-4-5, claude-opus-4-5).
            tools: Comma-separated tool names (e.g. Read, Glob, Grep, Bash).
            body: Agent role description and instructions (Markdown).
            skills: Comma-separated skill names for the skills: allowlist.
            max_turns: Maximum turns before the agent stops.
            project_root: Override for project root directory.
            scope: 'management' or a project name. Determines where the
                agent is created. Defaults to management.
        """
        return create_agent_handler(
            name=name, description=description, model=model,
            tools=tools, body=body, skills=skills,
            max_turns=max_turns, project_root=project_root, scope=scope,
        )

    @server.tool()
    async def EditAgent(
        name: str,
        field: str,
        value: str,
        project_root: str = '',
        scope: str = '',
    ) -> str:
        """Edit a single field in an existing agent definition.

        Args:
            name: Agent name.
            field: Field to update (name, description, model, tools,
                maxTurns, skills, body, or any other frontmatter key).
            value: New value (for skills, use comma-separated list).
            project_root: Override for project root directory.
            scope: 'management' or a project name.
        """
        return edit_agent_handler(
            name=name, field=field, value=value,
            project_root=project_root, scope=scope,
        )

    @server.tool()
    async def RemoveAgent(name: str, project_root: str = '', scope: str = '') -> str:
        """Delete agents/{name}/ directory.

        Args:
            name: Agent name.
            project_root: Override for project root directory.
            scope: 'management' or a project name.
        """
        return remove_agent_handler(name=name, project_root=project_root, scope=scope)

    @server.tool()
    async def CreateSkill(
        name: str,
        description: str,
        body: str,
        allowed_tools: str = '',
        argument_hint: str = '',
        user_invocable: bool = False,
        project_root: str = '',
        scope: str = '',
    ) -> str:
        """Create a new skill at skills/{name}/SKILL.md.

        Args:
            name: Skill name (becomes the directory name).
            description: One-line description for auto-invocation matching.
            body: Skill instructions (Markdown).
            allowed_tools: Comma-separated tools available during skill execution.
            argument_hint: Argument syntax hint (e.g. <skill-name>).
            user_invocable: Whether the skill can be invoked with /{name}.
            project_root: Override for project root directory.
            scope: 'management' or a project name.
        """
        return create_skill_handler(
            name=name, description=description, body=body,
            allowed_tools=allowed_tools, argument_hint=argument_hint,
            user_invocable=user_invocable, project_root=project_root,
            scope=scope,
        )

    @server.tool()
    async def EditSkill(
        name: str,
        field: str,
        value: str,
        project_root: str = '',
        scope: str = '',
    ) -> str:
        """Edit a single field of an existing skill's SKILL.md.

        Args:
            name: Skill name.
            field: Field to update ('body', 'description', 'allowed-tools', etc.).
            value: New value for the field.
            project_root: Override for project root directory.
            scope: 'management' or a project name.
        """
        return edit_skill_handler(
            name=name, field=field, value=value,
            project_root=project_root, scope=scope,
        )

    @server.tool()
    async def RemoveSkill(name: str, project_root: str = '', scope: str = '') -> str:
        """Remove skills/{name}/ directory and all its contents.

        Args:
            name: Skill name.
            project_root: Override for project root directory.
            scope: 'management' or a project name.
        """
        return remove_skill_handler(name=name, project_root=project_root, scope=scope)

    @server.tool()
    async def CreateWorkgroup(
        name: str,
        description: str = '',
        lead: str = '',
        agents_yaml: str = '',
        skills: str = '',
        norms_yaml: str = '',
        teaparty_home: str = '',
        scope: str = '',
    ) -> str:
        """Create a workgroup YAML at workgroups/{name}.yaml.

        Args:
            name: Workgroup name.
            description: Short description.
            lead: Agent name for workgroup lead.
            agents_yaml: YAML list of agent entries.
            skills: Comma-separated skill names for the workgroup catalog.
            norms_yaml: YAML dict of norms categories.
            teaparty_home: Override for .teaparty/ directory path.
            scope: 'management' or a project name.
        """
        return create_workgroup_handler(
            name=name, description=description, lead=lead,
            agents_yaml=agents_yaml, skills=skills, norms_yaml=norms_yaml,
            teaparty_home=teaparty_home, scope=scope,
        )

    @server.tool()
    async def EditWorkgroup(
        name: str,
        field: str,
        value: str,
        teaparty_home: str = '',
        scope: str = '',
    ) -> str:
        """Edit a single field in an existing workgroup YAML.

        Args:
            name: Workgroup name.
            field: Field to update (name, description, lead, agents, skills, norms).
            value: New value (YAML string for list/dict fields).
            teaparty_home: Override for .teaparty/ directory path.
            scope: 'management' or a project name.
        """
        return edit_workgroup_handler(
            name=name, field=field, value=value,
            teaparty_home=teaparty_home, scope=scope,
        )

    @server.tool()
    async def RemoveWorkgroup(name: str, teaparty_home: str = '', scope: str = '') -> str:
        """Remove workgroups/{name}.yaml.

        Args:
            name: Workgroup name.
            teaparty_home: Override for .teaparty/ directory path.
            scope: 'management' or a project name.
        """
        return remove_workgroup_handler(name=name, teaparty_home=teaparty_home, scope=scope)

    @server.tool()
    async def CreateHook(
        event: str,
        matcher: str,
        handler_type: str,
        command: str,
        project_root: str = '',
        scope: str = '',
    ) -> str:
        """Add a hook entry to settings.yaml.

        Args:
            event: Lifecycle event (PreToolUse, PostToolUse, Notification, Stop).
            matcher: Tool name or pattern to match (e.g. Edit, Write|Edit).
            handler_type: Handler type (command, agent, prompt, http).
            command: Shell command or handler expression.
            project_root: Override for project root directory.
            scope: 'management' or a project name.
        """
        return create_hook_handler(
            event=event, matcher=matcher,
            handler_type=handler_type, command=command,
            project_root=project_root, scope=scope,
        )

    @server.tool()
    async def EditHook(
        event: str,
        matcher: str,
        field: str,
        value: str,
        project_root: str = '',
        scope: str = '',
    ) -> str:
        """Edit a field in an existing hook entry.

        Args:
            event: Lifecycle event of the hook to edit.
            matcher: Matcher of the hook entry to edit.
            field: Field to update (command, type, or matcher).
            value: New value.
            project_root: Override for project root directory.
            scope: 'management' or a project name.
        """
        return edit_hook_handler(
            event=event, matcher=matcher,
            field=field, value=value, project_root=project_root,
            scope=scope,
        )

    @server.tool()
    async def RemoveHook(event: str, matcher: str, project_root: str = '', scope: str = '') -> str:
        """Remove a hook entry from settings.yaml.

        Args:
            event: Lifecycle event of the hook to remove.
            matcher: Matcher of the hook entry to remove.
            project_root: Override for project root directory.
            scope: 'management' or a project name.
        """
        return remove_hook_handler(
            event=event, matcher=matcher, project_root=project_root,
            scope=scope,
        )

    @server.tool()
    async def CreateScheduledTask(
        name: str,
        schedule: str,
        skill: str,
        args: str = '',
        teaparty_home: str = '',
    ) -> str:
        """Add a scheduled task entry to teaparty.yaml.

        The referenced skill must exist before calling this tool.

        Args:
            name: Task name (unique identifier).
            schedule: Cron expression (e.g. '0 2 * * *' for 2am daily).
            skill: Name of the skill to invoke on schedule.
            args: Optional arguments to pass to the skill.
            teaparty_home: Override for .teaparty/ directory path.
        """
        return create_scheduled_task_handler(
            name=name, schedule=schedule, skill=skill,
            args=args, teaparty_home=teaparty_home,
        )

    @server.tool()
    async def EditScheduledTask(
        name: str,
        field: str,
        value: str,
        teaparty_home: str = '',
    ) -> str:
        """Edit a field in an existing scheduled task entry.

        Args:
            name: Task name.
            field: Field to update (schedule, skill, args, enabled).
            value: New value.
            teaparty_home: Override for .teaparty/ directory path.
        """
        return edit_scheduled_task_handler(
            name=name, field=field, value=value, teaparty_home=teaparty_home,
        )

    @server.tool()
    async def RemoveScheduledTask(name: str, teaparty_home: str = '') -> str:
        """Remove a scheduled task entry from teaparty.yaml.

        Args:
            name: Task name.
            teaparty_home: Override for .teaparty/ directory path.
        """
        return remove_scheduled_task_handler(name=name, teaparty_home=teaparty_home)

    # ── Artifact pin tools ────────────────────────────────────────────────────

    @server.tool()
    async def PinArtifact(
        project: str,
        path: str,
        label: str = '',
        teaparty_home: str = '',
    ) -> str:
        """Add or update an artifact pin in a project's artifact viewer navigator.

        Pins a file or directory as a persistent entry in the project's artifact
        viewer. File pins open immediately on click; folder pins render as
        collapsible trees. If a pin with the same path exists, its label is updated.

        Args:
            project: Project name as registered in teaparty.yaml.
            path: Path relative to the project root (e.g. 'docs/', 'tests/test_engine.py').
            label: Display label for the navigator. Falls back to the last path component.
            teaparty_home: Override for .teaparty/ directory path.
        """
        return pin_artifact_handler(
            project=project, path=path, label=label, teaparty_home=teaparty_home,
        )

    @server.tool()
    async def UnpinArtifact(
        project: str,
        path: str,
        teaparty_home: str = '',
    ) -> str:
        """Remove an artifact pin from a project's artifact viewer navigator.

        Args:
            project: Project name as registered in teaparty.yaml.
            path: Path to remove (must match the path used when pinning).
            teaparty_home: Override for .teaparty/ directory path.
        """
        return unpin_artifact_handler(
            project=project, path=path, teaparty_home=teaparty_home,
        )

    # ── Research tools ────────────────────────────────────────────────────────

    @server.tool()
    async def youtube_transcript(url: str, include_timestamps: bool = False) -> str:
        """Retrieve the transcript for a YouTube video.

        Args:
            url: YouTube URL (youtube.com/watch?v=..., youtu.be/...) or bare video ID.
            include_timestamps: If True, prefix each line with [MM:SS] timestamps.
        """
        return await youtube_transcript_handler(url=url, include_timestamps=include_timestamps)

    @server.tool()
    async def arxiv_search(query: str, max_results: int = 10) -> str:
        """Search arXiv for academic papers.

        Supports arXiv query syntax (e.g. "ti:transformer AND cat:cs.LG"). No API key required.

        Args:
            query: Search query string.
            max_results: Maximum number of results (1–50).
        """
        return await arxiv_search_handler(query=query, max_results=max_results)

    @server.tool()
    async def semantic_scholar_search(query: str, max_results: int = 10) -> str:
        """Search Semantic Scholar for academic papers with citation counts.

        Optional S2_API_KEY environment variable raises rate limits.

        Args:
            query: Search query string.
            max_results: Maximum number of results (1–100).
        """
        return await semantic_scholar_search_handler(query=query, max_results=max_results)

    @server.tool()
    async def pubmed_search(query: str, max_results: int = 10) -> str:
        """Search PubMed for biomedical literature.

        Supports MeSH terms and PubMed field tags. Optional NCBI_API_KEY raises rate limits.

        Args:
            query: PubMed search query.
            max_results: Maximum number of results (1–100).
        """
        return await pubmed_search_handler(query=query, max_results=max_results)

    # ── Patent tools ──────────────────────────────────────────────────────────

    @server.tool()
    async def patent_search_uspto(query: str, max_results: int = 10) -> str:
        """Search US patents via the USPTO PatentsView API. No API key required.

        Args:
            query: Keyword query to search in patent titles and abstracts.
            max_results: Maximum number of results (1–25).
        """
        return await patent_search_uspto_handler(query=query, max_results=max_results)

    @server.tool()
    async def patent_search_epo(query: str, max_results: int = 10) -> str:
        """Search European patents via EPO Open Patent Services.

        Requires EPO_OPS_KEY and EPO_OPS_SECRET environment variables.

        Args:
            query: CQL query string (e.g. 'ti="machine learning" AND pa="Google"').
            max_results: Maximum number of results (1–25).
        """
        return await patent_search_epo_handler(query=query, max_results=max_results)

    # ── Image generation tools ────────────────────────────────────────────────

    @server.tool()
    async def image_gen_openai(
        prompt: str,
        model: str = 'gpt-image-1',
        size: str = '1024x1024',
        output_path: str = '',
    ) -> str:
        """Generate an image using OpenAI's image generation API.

        Requires the OPENAI_API_KEY environment variable.

        Args:
            prompt: Text description of the image to generate.
            model: 'gpt-image-1' (default) or 'dall-e-3'.
            size: Image dimensions — '1024x1024', '1024x1536', '1536x1024' (gpt-image-1)
                  or '1024x1024', '1792x1024', '1024x1792' (dall-e-3).
            output_path: File path for the output PNG. Defaults to a timestamped file in cwd.
        """
        return await image_gen_openai_handler(
            prompt=prompt, model=model, size=size, output_path=output_path,
        )

    @server.tool()
    async def image_gen_flux(
        prompt: str,
        width: int = 1024,
        height: int = 1024,
        output_path: str = '',
    ) -> str:
        """Generate an image using Black Forest Labs' Flux API.

        Requires the BFL_API_KEY environment variable.

        Args:
            prompt: Text description of the image to generate.
            width: Image width in pixels (default 1024).
            height: Image height in pixels (default 1024).
            output_path: File path for the output PNG. Defaults to a timestamped file in cwd.
        """
        return await image_gen_flux_handler(
            prompt=prompt, width=width, height=height, output_path=output_path,
        )

    @server.tool()
    async def image_gen_stability(
        prompt: str,
        aspect_ratio: str = '1:1',
        output_path: str = '',
    ) -> str:
        """Generate an image using Stability AI's Stable Image Core API.

        Requires the STABILITY_API_KEY environment variable.

        Args:
            prompt: Text description of the image to generate.
            aspect_ratio: '1:1', '16:9', '9:16', '4:3', '3:4', or '21:9'.
            output_path: File path for the output PNG. Defaults to a timestamped file in cwd.
        """
        return await image_gen_stability_handler(
            prompt=prompt, aspect_ratio=aspect_ratio, output_path=output_path,
        )

    # Filter to agent's allowed tools when specified.
    if agent_tools is not None:
        registered = server._tool_manager.list_tools()
        mcp_prefix = 'mcp__teaparty-config__'
        bare_names = set()
        for t in agent_tools:
            bare_names.add(t[len(mcp_prefix):] if t.startswith(mcp_prefix) else t)
        to_remove = [tool.name for tool in registered if tool.name not in bare_names]
        for name in to_remove:
            server.remove_tool(name)
        _cs_log.info('create_server: filtered to %d/%d tools',
                     len(registered) - len(to_remove), len(registered))

    return server


def _resolve_teaparty_home() -> str:
    """Find the .teaparty/ directory."""
    home = os.environ.get('TEAPARTY_HOME', '')
    if home:
        return home
    d = os.getcwd()
    while d != os.path.dirname(d):
        candidate = os.path.join(d, '.teaparty')
        if os.path.isdir(candidate):
            return candidate
        d = os.path.dirname(d)
    return ''


def _load_agent_tools(
    agent_id: str,
    *,
    scope: str = 'management',
    project_name: str = '',
) -> set[str] | None:
    """Read the allowed tools from an agent's frontmatter.

    Scope resolution: project overrides management. If scope is a project
    name, look there first; fall back to management.

    Returns the set of tool names (both builtins and MCP), or None if
    the agent has no tools restriction.
    """
    from teaparty.config.config_reader import read_agent_frontmatter

    teaparty_home = _resolve_teaparty_home()
    if not teaparty_home:
        return None

    candidates = []

    # Project scope: check project agents first
    if project_name and project_name != 'management':
        from teaparty.mcp.tools.config_crud import _find_project_path
        project_dir = _find_project_path(project_name, teaparty_home)
        if project_dir:
            candidates.append(
                os.path.join(project_dir, '.teaparty', 'project', 'agents', agent_id, 'agent.md')
            )

    # Management scope: always checked as fallback
    candidates.append(
        os.path.join(teaparty_home, 'management', 'agents', agent_id, 'agent.md')
    )

    for agent_md in candidates:
        if not os.path.isfile(agent_md):
            continue
        try:
            fm = read_agent_frontmatter(agent_md)
            tools_str = fm.get('tools', '')
            if tools_str:
                return {t.strip() for t in tools_str.split(',') if t.strip()}
        except (FileNotFoundError, Exception):
            continue

    return None


# ── HTTP server with ASGI response filter ─────────────────────────────────────

# ── HTTP server with ASGI response filter ─────────────────────────────────────

def create_http_app(port: int = 8082):
    """HTTP MCP server with ASGI response filter for per-agent tool filtering.

    One FastMCP instance, one session manager. tools/list responses on
    agent-scoped paths are intercepted and filtered to the agent's
    frontmatter allowlist.

    Paths:
        /mcp                           — all tools (interactive session)
        /mcp/management/{agent}        — management-scoped agent
        /mcp/{project}/{agent}         — project-scoped agent
    """
    import json as _json
    import logging as _logging
    import uvicorn

    _log = _logging.getLogger('teaparty.mcp.server')

    # One server with all tools, one session manager
    server = create_server()
    starlette_app = server.streamable_http_app()

    def _get_allowed_names(scope_or_project: str, agent_name: str) -> set[str] | None:
        """Load agent's allowed tool names (bare, no mcp__ prefix)."""
        if scope_or_project == 'management':
            tools = _load_agent_tools(agent_name, scope='management')
        else:
            tools = _load_agent_tools(agent_name, project_name=scope_or_project)
        if tools is None:
            return None
        mcp_prefix = 'mcp__teaparty-config__'
        return {t[len(mcp_prefix):] if t.startswith(mcp_prefix) else t
                for t in tools}

    _allowlist_cache: dict[str, set[str] | None] = {}

    def _filter_tools_response(body: bytes, allowed: set[str]) -> bytes:
        """Filter a tools/list JSON-RPC response to only allowed tools."""
        data = _json.loads(body)
        result = data.get('result', {})
        tools = result.get('tools')
        if tools is not None:
            result['tools'] = [t for t in tools if t.get('name') in allowed]
            data['result'] = result
        return _json.dumps(data).encode()

    async def filtering_app(scope, receive, send):
        """ASGI app: one server, filter tools/list for agent paths."""

        # Non-HTTP (lifespan etc.) -> delegate directly
        if scope['type'] != 'http':
            await starlette_app(scope, receive, send)
            return

        original_path = scope.get('path', '')
        parts = original_path.strip('/').split('/')

        # Parse agent scope from path:
        #   /mcp/{scope}/{agent}              — legacy (no session)
        #   /mcp/{scope}/{agent}/{session_id} — per-instance
        agent_info = None
        if len(parts) >= 3 and parts[0] == 'mcp':
            agent_info = (parts[1], parts[2])

        # Rewrite path to /mcp for the FastMCP app
        scope = dict(scope)
        scope['path'] = '/mcp'

        # No agent scope -> pass through unchanged (all tools)
        if agent_info is None:
            await starlette_app(scope, receive, send)
            return

        scope_name, agent_name = agent_info
        cache_key = f'{scope_name}/{agent_name}'

        # Set the agent context so tool handlers know who's calling
        from teaparty.mcp.registry import current_agent_name, current_session_id
        current_agent_name.set(agent_name)
        # Session ID present in 4-part paths: /mcp/{scope}/{agent}/{session_id}
        if len(parts) >= 4:
            current_session_id.set(parts[3])

        # Load allowlist
        if cache_key not in _allowlist_cache:
            _allowlist_cache[cache_key] = _get_allowed_names(scope_name, agent_name)
            allowed = _allowlist_cache[cache_key]
            _log.info('Loaded allowlist for %s: %s',
                      cache_key, f'{len(allowed)} tools' if allowed else 'all')

        allowed = _allowlist_cache[cache_key]

        # No allowlist -> pass through (all tools)
        if allowed is None:
            await starlette_app(scope, receive, send)
            return

        # Peek at request body to check if this is tools/list
        first_msg = await receive()
        request_body = first_msg.get('body', b'')

        is_tools_list = False
        try:
            req = _json.loads(request_body)
            is_tools_list = req.get('method') == 'tools/list'
        except (ValueError, _json.JSONDecodeError):
            pass

        # Replay the peeked message
        replayed = False
        async def replay_receive():
            nonlocal replayed
            if not replayed:
                replayed = True
                return first_msg
            return await receive()

        # Not tools/list -> pass through
        if not is_tools_list:
            await starlette_app(scope, replay_receive, send)
            return

        # tools/list -> buffer response, filter, send
        captured_start = None
        captured_body = b''

        async def capture_send(msg):
            nonlocal captured_start, captured_body
            if msg['type'] == 'http.response.start':
                captured_start = msg
            elif msg['type'] == 'http.response.body':
                captured_body += msg.get('body', b'')

        await starlette_app(scope, replay_receive, capture_send)

        # Filter the tools
        if captured_start and captured_start.get('status') == 200 and captured_body:
            try:
                filtered = _filter_tools_response(captured_body, allowed)
            except Exception as exc:
                _log.warning('tools/list filter failed for %s: %s', cache_key, exc)
                filtered = captured_body

            # Rewrite Content-Length
            headers = [
                (b'content-length', str(len(filtered)).encode())
                if name.lower() == b'content-length' else (name, value)
                for name, value in captured_start.get('headers', [])
            ]
            await send({**captured_start, 'headers': headers})
            await send({'type': 'http.response.body', 'body': filtered})
        else:
            if captured_start:
                await send(captured_start)
            await send({'type': 'http.response.body', 'body': captured_body})

    # Return the ASGI app, the Starlette app (for lifespan), and a standalone run function
    return filtering_app, starlette_app, server

    # Standalone run function (for python -m teaparty.mcp.server.main --http)
    # Not used when mounted inside the bridge.


def run_standalone_http(port: int = 8082):
    """Run the HTTP MCP server standalone with uvicorn (for testing)."""
    import uvicorn
    import asyncio
    import logging as _logging
    _log = _logging.getLogger('teaparty.mcp.server')

    filtering_app, _, _ = create_http_app(port)

    async def _serve():
        config = uvicorn.Config(
            filtering_app,
            host='127.0.0.1',
            port=port,
            log_level='warning',
        )
        uv_server = uvicorn.Server(config)
        _log.info('HTTP MCP server starting on port %d', port)
        await uv_server.serve()

    asyncio.run(_serve())


def main():
    """Run the MCP server.

    HTTP mode (production — started by the bridge):
        python -m teaparty.mcp.server.main --http --port 8082

    Stdio mode (interactive session fallback):
        python -m teaparty.mcp.server.main
    """
    import argparse
    import logging

    parser = argparse.ArgumentParser()
    parser.add_argument('--http', action='store_true',
                        help='Run as HTTP server with per-agent path routing')
    parser.add_argument('--port', type=int, default=8082,
                        help='HTTP server port (default: 8082)')
    args, _unknown = parser.parse_known_args()

    teaparty_home = _resolve_teaparty_home()
    if teaparty_home:
        log_dir = os.path.join(teaparty_home, 'logs')
        os.makedirs(log_dir, exist_ok=True)
        log_file = os.path.join(log_dir, 'mcp-server.log')
        logging.basicConfig(
            level=logging.DEBUG,
            format='%(asctime)s %(name)s %(levelname)s %(message)s',
            filename=log_file,
        )

    if args.http:
        run_standalone_http(port=args.port)
    else:
        server = create_server()
        server.run(transport='stdio')


if __name__ == '__main__':
    main()
