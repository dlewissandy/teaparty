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
    _default_flush,
    _scratch_path_from_env,
)

from teaparty.mcp.tools.messaging import (
    send_handler,
    reply_handler,
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


def create_server() -> FastMCP:
    """Create the MCP server with tools scoped to the agent's role."""
    import logging as _logging
    _cs_log = _logging.getLogger('teaparty.mcp.server.main.create')

    server = FastMCP('teaparty-escalation')
    scope = _agent_tool_scope()
    _cs_log.info('create_server: AGENT_TOOL_SCOPE=%r', scope)

    # Leaf agents need no MCP tools — they just answer and exit.
    if scope == 'leaf':
        _cs_log.info('create_server: leaf scope — returning empty server')
        return server

    @server.tool()
    async def AskQuestion(question: str, context: str = '') -> str:
        """Ask a question that will be routed to the appropriate responder.

        Use this tool when you need clarification, have a question about
        intent, or need human input before proceeding.  The question will
        be answered — you do not need to write escalation files.

        The tool automatically injects the caller's scratch file as context
        so the proxy or human receives the full job state alongside the
        question.

        Args:
            question: Your question. Be specific and concise.
            context: Ignored when a scratch file is present; kept for
                backward compatibility when the scratch file is absent.
        """
        return await ask_question_handler(
            question=question,
            context=context,
            scratch_path=_scratch_path_from_env(),
            flush_fn=_default_flush,
        )

    @server.tool()
    async def Send(member: str, message: str, context_id: str = '') -> str:
        """Send a message to a roster member, opening or continuing a thread.

        The tool automatically prepends the caller's scratch file as a
        Context section so the recipient has full job state without the
        caller constructing a manual brief.

        After Send completes, the agent's turn ends.  TeaParty re-invokes
        the caller when a response arrives on the thread.

        Args:
            member: Name key of a roster entry in your --agents object.
            message: The task or question for the recipient.
            context_id: Optional existing context ID to continue a thread.
                Omit to open a new thread.
        """
        return await send_handler(
            member=member,
            message=message,
            context_id=context_id,
            scratch_path=_scratch_path_from_env(),
            flush_fn=_default_flush,
        )

    @server.tool()
    async def Reply(message: str) -> str:
        """Reply to the agent that opened the current thread and close it.

        No context injection — the context is already established in the
        thread.  Calling Reply ends the agent's turn and marks the thread
        closed.  The calling agent's pending_count in the parent context
        is decremented.

        Args:
            message: Your reply — result, answer, or completion notice.
        """
        return await reply_handler(message=message)

    @server.tool()
    async def CloseConversation(context_id: str) -> str:
        """Close a conversation thread you opened.

        Marks the conversation as closed so no further follow-up Sends
        are accepted on this thread.  Only the originator of the thread
        should call this.  Does not affect the session turn — use Reply
        to close the current session turn.

        Args:
            context_id: The conversation context ID returned by the
                original Send call.
        """
        return await close_conversation_handler(context_id=context_id)

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
    async def ListWorkgroups(teaparty_home: str = '') -> str:
        """List all workgroup definitions with summary info.

        Returns name, description, and lead for each workgroup YAML
        found in the workgroups/ directory.

        Args:
            teaparty_home: Override for .teaparty/ directory path.
        """
        return list_workgroups_handler(teaparty_home=teaparty_home)

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

    # ── Config tools ──────────────────────────────────────────────────────────
    # Dispatching agents need Send + read tools only.
    # Remove Reply/CloseConversation/intervention — result returns via stdout.
    # Skip the 25+ config CRUD tools entirely.
    if scope == 'dispatch':
        for name in ('Reply', 'CloseConversation', 'WithdrawSession',
                     'PauseDispatch', 'ResumeDispatch', 'ReprioritizeDispatch'):
            server._tool_manager._tools.pop(name, None)
        return server

    @server.tool()
    async def AddProject(
        name: str,
        path: str,
        description: str = '',
        lead: str = '',
        decider: str = '',
        agents: str = '',
        humans: str = '',
        workgroups: str = '',
        skills: str = '',
        teaparty_home: str = '',
    ) -> str:
        """Register an existing directory as a TeaParty project.

        Creates a projects: entry in management/teaparty.yaml and scaffolds
        .teaparty/project/project.yaml with the provided fields.

        Args:
            name: Project name (must be unique in teaparty.yaml).
            path: Absolute path to the existing project directory.
            description: Short description of the project.
            lead: Agent name that leads this project.
            decider: Human name with decider role.
            agents: Comma-separated agent names.
            humans: YAML list of {name, role} dicts.
            workgroups: YAML list of workgroup refs or entries.
            skills: Comma-separated skill names.
            teaparty_home: Override for .teaparty/ directory path.
        """
        agents_list = [a.strip() for a in agents.split(',') if a.strip()] if agents else None
        humans_list = yaml.safe_load(humans) if humans else None
        workgroups_list = yaml.safe_load(workgroups) if workgroups else None
        skills_list = [s.strip() for s in skills.split(',') if s.strip()] if skills else None
        return add_project_handler(
            name=name, path=path, description=description,
            lead=lead, decider=decider,
            agents=agents_list, humans=humans_list,
            workgroups=workgroups_list, skills=skills_list,
            teaparty_home=teaparty_home,
        )

    @server.tool()
    async def CreateProject(
        name: str,
        path: str,
        description: str = '',
        lead: str = '',
        decider: str = '',
        agents: str = '',
        humans: str = '',
        workgroups: str = '',
        skills: str = '',
        teaparty_home: str = '',
    ) -> str:
        """Create a new project directory with full scaffolding.

        Runs git init, scaffolds .teaparty/project/project.yaml,
        and adds a teams: entry to teaparty.yaml.

        Args:
            name: Project name (must be unique in teaparty.yaml).
            path: Path for the new project directory (must not exist yet).
            description: Short description.
            lead: Agent name for project lead.
            decider: Human decider name.
            agents: Comma-separated agent names.
            humans: YAML list of human entries.
            workgroups: YAML list of workgroup entries.
            skills: Comma-separated skill names.
            teaparty_home: Override for .teaparty/ directory path.
        """
        agents_list = [a.strip() for a in agents.split(',') if a.strip()] if agents else None
        humans_list = yaml.safe_load(humans) if humans else None
        workgroups_list = yaml.safe_load(workgroups) if workgroups else None
        skills_list = [s.strip() for s in skills.split(',') if s.strip()] if skills else None
        return create_project_handler(
            name=name, path=path, description=description,
            lead=lead, decider=decider,
            agents=agents_list, humans=humans_list,
            workgroups=workgroups_list, skills=skills_list,
            teaparty_home=teaparty_home,
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

    # Filter MCP tools to the agent's frontmatter whitelist.
    agent_id = os.environ.get('AGENT_ID', '')
    if agent_id:
        agent_md = os.path.join(
            os.getcwd(), '.claude', 'agents', f'{agent_id}.md',
        )
        try:
            from teaparty.config.config_reader import read_agent_frontmatter
            fm = read_agent_frontmatter(agent_md)
            allowed = {
                t.strip() for t in fm.get('tools', '').split(',') if t.strip()
            }
            if allowed:
                mcp_prefix = 'mcp__teaparty-config__'
                bare_allowed = set()
                for t in allowed:
                    if t.startswith(mcp_prefix):
                        bare_allowed.add(t[len(mcp_prefix):])
                    else:
                        bare_allowed.add(t)
                import asyncio
                registered = asyncio.run(server.list_tools())
                for tool in registered:
                    if tool.name not in bare_allowed:
                        server.remove_tool(tool.name)
                remaining = len(bare_allowed & {t.name for t in registered})
                _cs_log.info(
                    'create_server: filtered to %d MCP tools for agent %r',
                    remaining, agent_id,
                )
        except FileNotFoundError:
            pass
        except Exception as exc:
            _cs_log.warning(
                'create_server: tool filter failed for %r: %s', agent_id, exc,
            )

    return server


def main():
    """Run the MCP server on stdio."""
    import argparse
    import logging

    parser = argparse.ArgumentParser()
    parser.add_argument('--send-socket', default='')
    parser.add_argument('--reply-socket', default='')
    parser.add_argument('--close-conv-socket', default='')
    parser.add_argument('--agent-id', default='')
    parser.add_argument('--context-id', default='')
    args, _unknown = parser.parse_known_args()

    if args.send_socket:
        os.environ['SEND_SOCKET'] = args.send_socket
    if args.reply_socket:
        os.environ['REPLY_SOCKET'] = args.reply_socket
    if args.close_conv_socket:
        os.environ['CLOSE_CONV_SOCKET'] = args.close_conv_socket
    if args.agent_id:
        os.environ['AGENT_ID'] = args.agent_id
    if args.context_id:
        os.environ['CONTEXT_ID'] = args.context_id

    teaparty_home = os.environ.get('TEAPARTY_HOME', '')
    if not teaparty_home:
        d = os.getcwd()
        while d != os.path.dirname(d):
            candidate = os.path.join(d, '.teaparty')
            if os.path.isdir(candidate):
                teaparty_home = candidate
                break
            d = os.path.dirname(d)

    if teaparty_home:
        log_dir = os.path.join(teaparty_home, 'logs')
        os.makedirs(log_dir, exist_ok=True)
        log_file = os.path.join(log_dir, 'mcp-server.log')
        logging.basicConfig(
            level=logging.DEBUG,
            format='%(asctime)s %(name)s %(levelname)s %(message)s',
            filename=log_file,
        )

    _mlog = logging.getLogger('teaparty.mcp.server.main')
    _mlog.info(
        'main: SEND_SOCKET=%r AGENT_ID=%r CONTEXT_ID=%r',
        os.environ.get('SEND_SOCKET', ''),
        os.environ.get('AGENT_ID', ''),
        os.environ.get('CONTEXT_ID', ''),
    )
    server = create_server()
    _mlog.info('main: registered %d tools', len(server._tool_manager._tools))
    server.run(transport='stdio')


if __name__ == '__main__':
    main()
