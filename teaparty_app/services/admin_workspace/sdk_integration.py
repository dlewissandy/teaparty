"""LLM SDK wiring for admin workspace, isolated from core logic."""

from __future__ import annotations

import logging
import time

from sqlmodel import Session, select

from teaparty_app.config import settings
from teaparty_app.services import llm_client
from teaparty_app.models import Agent, Message, Workgroup
from teaparty_app.services.llm_usage import record_llm_usage
from teaparty_app.services.admin_workspace.bootstrap import (
    ADMINISTRATION_WORKGROUP_NAME,
    ADMIN_TOOL_ACCEPT_TASK,
    ADMIN_TOOL_ADD_AGENT,
    ADMIN_TOOL_ADD_FILE,
    ADMIN_TOOL_ADD_JOB,
    ADMIN_TOOL_ADD_USER,
    ADMIN_TOOL_ARCHIVE_JOB,
    ADMIN_TOOL_CLEAR_JOB_MESSAGES,
    ADMIN_TOOL_COMPLETE_TASK,
    ADMIN_TOOL_DECLINE_TASK,
    ADMIN_TOOL_DELETE_FILE,
    ADMIN_TOOL_DELETE_WORKGROUP,
    ADMIN_TOOL_EDIT_FILE,
    ADMIN_TOOL_LIST_FILES,
    ADMIN_TOOL_LIST_MEMBERS,
    ADMIN_TOOL_LIST_TASKS,
    ADMIN_TOOL_LIST_JOBS,
    ADMIN_TOOL_REMOVE_MEMBER,
    ADMIN_TOOL_REMOVE_JOB,
    ADMIN_TOOL_RENAME_FILE,
    ADMIN_TOOL_UNARCHIVE_JOB,
    GLOBAL_TOOL_ADD_AGENT,
    GLOBAL_TOOL_ADD_FILE,
    GLOBAL_TOOL_ADD_JOB,
    GLOBAL_TOOL_CREATE_ORGANIZATION,
    GLOBAL_TOOL_CREATE_WORKGROUP,
    GLOBAL_TOOL_LIST_AGENTS,
    GLOBAL_TOOL_LIST_AVAILABLE_TOOLS,
    GLOBAL_TOOL_LIST_ORGANIZATIONS,
    GLOBAL_TOOL_LIST_TEMPLATES,
    GLOBAL_TOOL_LIST_JOBS,
    GLOBAL_TOOL_LIST_WORKGROUPS,
    GLOBAL_TOOL_NAMES,
    GLOBAL_TOOL_UPDATE_AGENT,
)
from teaparty_app.services.admin_workspace.parsing import _help_text
from teaparty_app.services.admin_workspace.member_tools import (
    admin_tool_add_agent,
    admin_tool_add_user,
    admin_tool_delete_workgroup,
    admin_tool_list_members,
    admin_tool_remove_member,
)
from teaparty_app.services.admin_workspace.file_tools import (
    admin_tool_add_file,
    admin_tool_delete_file,
    admin_tool_edit_file,
    admin_tool_list_files,
    admin_tool_rename_file,
)
from teaparty_app.services.admin_workspace.job_tools import (
    admin_tool_add_job,
    admin_tool_archive_job,
    admin_tool_clear_job_messages,
    admin_tool_list_jobs,
    admin_tool_remove_job,
    admin_tool_unarchive_job,
)
from teaparty_app.services.admin_workspace.task_tools import (
    admin_tool_accept_task,
    admin_tool_complete_task,
    admin_tool_decline_task,
    admin_tool_list_tasks,
)

logger = logging.getLogger(__name__)

_ADMIN_TOOLS = [
    {
        "name": ADMIN_TOOL_ADD_JOB,
        "description": "Add a new job conversation in the current workgroup with optional description.",
        "input_schema": {
            "type": "object",
            "properties": {
                "job_name": {"type": "string", "description": "Name of the new job"},
                "description": {"type": "string", "description": "Optional job description", "default": ""},
            },
            "required": ["job_name"],
        },
    },
    {
        "name": ADMIN_TOOL_ARCHIVE_JOB,
        "description": "Archive a job conversation by job name or job conversation id.",
        "input_schema": {
            "type": "object",
            "properties": {
                "job_selector": {"type": "string", "description": "Job name or id to archive"},
            },
            "required": ["job_selector"],
        },
    },
    {
        "name": ADMIN_TOOL_UNARCHIVE_JOB,
        "description": "Unarchive a job conversation by job name or job conversation id.",
        "input_schema": {
            "type": "object",
            "properties": {
                "job_selector": {"type": "string", "description": "Job name or id to unarchive"},
            },
            "required": ["job_selector"],
        },
    },
    {
        "name": ADMIN_TOOL_ADD_AGENT,
        "description": "Create a new AI agent in the workgroup (owner-only). Supports prompt and model.",
        "input_schema": {
            "type": "object",
            "properties": {
                "agent_name": {"type": "string", "description": "Short name for the agent"},
                "prompt": {"type": "string", "description": "Agent system prompt", "default": ""},
                "description": {"type": "string", "description": "Short agent description", "default": ""},
                "model": {"type": "string", "description": "Model name", "default": "sonnet"},
            },
            "required": ["agent_name"],
        },
    },
    {
        "name": ADMIN_TOOL_ADD_USER,
        "description": "Add a user to the workgroup by email or create an invite (owner-only action).",
        "input_schema": {
            "type": "object",
            "properties": {
                "email": {"type": "string", "description": "Email address of the user"},
            },
            "required": ["email"],
        },
    },
    {
        "name": ADMIN_TOOL_ADD_FILE,
        "description": "Add a file to the current workgroup by path (owner-only action).",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path"},
                "content": {"type": "string", "description": "File content", "default": ""},
            },
            "required": ["path"],
        },
    },
    {
        "name": ADMIN_TOOL_EDIT_FILE,
        "description": "Update file contents for an existing workgroup file by path (owner-only action).",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path"},
                "content": {"type": "string", "description": "New file content"},
            },
            "required": ["path", "content"],
        },
    },
    {
        "name": ADMIN_TOOL_RENAME_FILE,
        "description": "Rename a workgroup file from source_path to destination_path (owner-only action).",
        "input_schema": {
            "type": "object",
            "properties": {
                "source_path": {"type": "string", "description": "Current file path"},
                "destination_path": {"type": "string", "description": "New file path"},
            },
            "required": ["source_path", "destination_path"],
        },
    },
    {
        "name": ADMIN_TOOL_DELETE_FILE,
        "description": "Delete a workgroup file by path (owner-only action).",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path to delete"},
            },
            "required": ["path"],
        },
    },
    {
        "name": ADMIN_TOOL_LIST_JOBS,
        "description": "List job conversations by status: open, archived, or both.",
        "input_schema": {
            "type": "object",
            "properties": {
                "status": {"type": "string", "description": "Filter: open, archived, or both", "default": "open"},
            },
        },
    },
    {
        "name": ADMIN_TOOL_LIST_MEMBERS,
        "description": "List workgroup members, including human users and agents.",
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": ADMIN_TOOL_LIST_FILES,
        "description": "List workgroup files and paths.",
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": ADMIN_TOOL_REMOVE_JOB,
        "description": "Permanently remove a job conversation by job name or id (owner-only action).",
        "input_schema": {
            "type": "object",
            "properties": {
                "job_selector": {"type": "string", "description": "Job name or id to remove"},
            },
            "required": ["job_selector"],
        },
    },
    {
        "name": ADMIN_TOOL_CLEAR_JOB_MESSAGES,
        "description": "Delete all messages in a job conversation by job name or id (owner-only action).",
        "input_schema": {
            "type": "object",
            "properties": {
                "job_selector": {"type": "string", "description": "Job name or id"},
            },
            "required": ["job_selector"],
        },
    },
    {
        "name": ADMIN_TOOL_REMOVE_MEMBER,
        "description": "Remove a human member or non-admin agent from the workgroup (owner-only action).",
        "input_schema": {
            "type": "object",
            "properties": {
                "member_selector": {"type": "string", "description": "Member id, email, or name"},
            },
            "required": ["member_selector"],
        },
    },
    {
        "name": ADMIN_TOOL_DELETE_WORKGROUP,
        "description": "Delete the current workgroup and all its data. Set confirmed=true to execute.",
        "input_schema": {
            "type": "object",
            "properties": {
                "confirmed": {"type": "boolean", "description": "Must be true to confirm deletion", "default": False},
            },
        },
    },
    {
        "name": ADMIN_TOOL_LIST_TASKS,
        "description": "List tasks (engagements) for this workgroup.",
        "input_schema": {
            "type": "object",
            "properties": {
                "direction": {
                    "type": "string",
                    "description": "Filter: incoming, outgoing, or all",
                    "default": "all",
                },
            },
        },
    },
    {
        "name": ADMIN_TOOL_ACCEPT_TASK,
        "description": "Accept an incoming task by its id or title.",
        "input_schema": {
            "type": "object",
            "properties": {
                "task_selector": {"type": "string", "description": "Task id or title"},
            },
            "required": ["task_selector"],
        },
    },
    {
        "name": ADMIN_TOOL_DECLINE_TASK,
        "description": "Decline an incoming task by its id or title.",
        "input_schema": {
            "type": "object",
            "properties": {
                "task_selector": {"type": "string", "description": "Task id or title"},
            },
            "required": ["task_selector"],
        },
    },
    {
        "name": ADMIN_TOOL_COMPLETE_TASK,
        "description": "Mark a task as complete by its id or title.",
        "input_schema": {
            "type": "object",
            "properties": {
                "task_selector": {"type": "string", "description": "Task id or title"},
            },
            "required": ["task_selector"],
        },
    },
]


_GLOBAL_ADMIN_TOOLS = [
    {
        "name": GLOBAL_TOOL_CREATE_ORGANIZATION,
        "description": "Create a new organization to group workgroups together.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Organization name"},
                "description": {"type": "string", "description": "Organization description", "default": ""},
            },
            "required": ["name"],
        },
    },
    {
        "name": GLOBAL_TOOL_LIST_ORGANIZATIONS,
        "description": "List all organizations owned by the current user.",
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": GLOBAL_TOOL_CREATE_WORKGROUP,
        "description": "Create a new workgroup, optionally from a template and in an organization.",
        "input_schema": {
            "type": "object",
            "properties": {
                "workgroup_name": {"type": "string", "description": "Name for the new workgroup"},
                "organization_name": {"type": "string", "description": "Organization to add it to (optional)", "default": ""},
                "template_key": {"type": "string", "description": "Template key to use (optional, use global_list_templates to see available)", "default": ""},
            },
            "required": ["workgroup_name"],
        },
    },
    {
        "name": GLOBAL_TOOL_LIST_WORKGROUPS,
        "description": "List workgroups, optionally filtered by organization.",
        "input_schema": {
            "type": "object",
            "properties": {
                "organization_name": {"type": "string", "description": "Filter by organization name (optional)", "default": ""},
            },
        },
    },
    {
        "name": GLOBAL_TOOL_ADD_AGENT,
        "description": "Add an AI agent to any workgroup by workgroup name.",
        "input_schema": {
            "type": "object",
            "properties": {
                "workgroup_name": {"type": "string", "description": "Target workgroup name"},
                "agent_name": {"type": "string", "description": "Short name for the agent"},
                "prompt": {"type": "string", "description": "Agent system prompt", "default": ""},
                "description": {"type": "string", "description": "Short agent description", "default": ""},
                "model": {"type": "string", "description": "Model name", "default": "sonnet"},
                "tools": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of tool names to assign (use global_list_available_tools to see options)",
                    "default": [],
                },
            },
            "required": ["workgroup_name", "agent_name"],
        },
    },
    {
        "name": GLOBAL_TOOL_LIST_AGENTS,
        "description": "List agents in a workgroup by workgroup name.",
        "input_schema": {
            "type": "object",
            "properties": {
                "workgroup_name": {"type": "string", "description": "Workgroup name"},
            },
            "required": ["workgroup_name"],
        },
    },
    {
        "name": GLOBAL_TOOL_ADD_JOB,
        "description": "Add a job conversation to any workgroup by workgroup name.",
        "input_schema": {
            "type": "object",
            "properties": {
                "workgroup_name": {"type": "string", "description": "Target workgroup name"},
                "job_name": {"type": "string", "description": "Name of the new job"},
                "description": {"type": "string", "description": "Job description", "default": ""},
            },
            "required": ["workgroup_name", "job_name"],
        },
    },
    {
        "name": GLOBAL_TOOL_LIST_JOBS,
        "description": "List jobs in a workgroup by workgroup name.",
        "input_schema": {
            "type": "object",
            "properties": {
                "workgroup_name": {"type": "string", "description": "Workgroup name"},
                "status": {"type": "string", "description": "Filter: open, archived, or both", "default": "open"},
            },
            "required": ["workgroup_name"],
        },
    },
    {
        "name": GLOBAL_TOOL_ADD_FILE,
        "description": "Add a file to any workgroup by workgroup name.",
        "input_schema": {
            "type": "object",
            "properties": {
                "workgroup_name": {"type": "string", "description": "Target workgroup name"},
                "path": {"type": "string", "description": "File path"},
                "content": {"type": "string", "description": "File content", "default": ""},
            },
            "required": ["workgroup_name", "path"],
        },
    },
    {
        "name": GLOBAL_TOOL_LIST_TEMPLATES,
        "description": "List available workgroup templates that can be used when creating workgroups.",
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": GLOBAL_TOOL_LIST_AVAILABLE_TOOLS,
        "description": "List all available tools that can be assigned to agents in a workgroup.",
        "input_schema": {
            "type": "object",
            "properties": {
                "workgroup_name": {"type": "string", "description": "Workgroup name"},
            },
            "required": ["workgroup_name"],
        },
    },
    {
        "name": GLOBAL_TOOL_UPDATE_AGENT,
        "description": "Update an existing agent's settings in any workgroup. Only provided fields are changed.",
        "input_schema": {
            "type": "object",
            "properties": {
                "workgroup_name": {"type": "string", "description": "Target workgroup name"},
                "agent_name": {"type": "string", "description": "Name of the agent to update"},
                "prompt": {"type": "string", "description": "New system prompt"},
                "permission_mode": {"type": "string", "description": "New permission mode (e.g. default, acceptEdits)"},
                "model": {"type": "string", "description": "New model name"},
                "tools": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "New list of tools (replaces current list). Use global_list_available_tools to see options.",
                },
            },
            "required": ["workgroup_name", "agent_name"],
        },
    },
]


def _is_global_admin_context(session: Session, workgroup_id: str) -> bool:
    """Return True when the workgroup is the system-level Administration workgroup (no org)."""
    workgroup = session.get(Workgroup, workgroup_id)
    return (
        workgroup is not None
        and workgroup.name == ADMINISTRATION_WORKGROUP_NAME
        and workgroup.organization_id is None
    )


def _is_org_admin_context(session: Session, workgroup_id: str) -> str | None:
    """Return the org name if the workgroup is an org-level Administration workgroup, else None."""
    workgroup = session.get(Workgroup, workgroup_id)
    if workgroup is None or workgroup.name != ADMINISTRATION_WORKGROUP_NAME or workgroup.organization_id is None:
        return None
    from teaparty_app.models import Organization
    org = session.get(Organization, workgroup.organization_id)
    return org.name if org else "Organization"


def _dispatch_global_tool(
    session: Session,
    requester_user_id: str,
    tool_name: str,
    tool_input: dict,
) -> str:
    from teaparty_app.services.admin_workspace.global_tools import (
        global_add_agent,
        global_add_file,
        global_add_job,
        global_create_organization,
        global_create_workgroup,
        global_list_agents,
        global_list_available_tools,
        global_list_organizations,
        global_list_templates,
        global_list_jobs,
        global_list_workgroups,
        global_update_agent,
    )

    dispatch = {
        GLOBAL_TOOL_CREATE_ORGANIZATION: global_create_organization,
        GLOBAL_TOOL_LIST_ORGANIZATIONS: global_list_organizations,
        GLOBAL_TOOL_CREATE_WORKGROUP: global_create_workgroup,
        GLOBAL_TOOL_LIST_WORKGROUPS: global_list_workgroups,
        GLOBAL_TOOL_ADD_AGENT: global_add_agent,
        GLOBAL_TOOL_LIST_AGENTS: global_list_agents,
        GLOBAL_TOOL_ADD_JOB: global_add_job,
        GLOBAL_TOOL_LIST_JOBS: global_list_jobs,
        GLOBAL_TOOL_ADD_FILE: global_add_file,
        GLOBAL_TOOL_LIST_TEMPLATES: global_list_templates,
        GLOBAL_TOOL_LIST_AVAILABLE_TOOLS: global_list_available_tools,
        GLOBAL_TOOL_UPDATE_AGENT: global_update_agent,
    }
    handler = dispatch.get(tool_name)
    if not handler:
        return f"Unknown global tool: {tool_name}"
    return handler(session, requester_user_id, tool_input)


def _dispatch_admin_tool(
    session: Session,
    workgroup_id: str,
    requester_user_id: str,
    tool_name: str,
    tool_input: dict,
) -> str:
    if tool_name == ADMIN_TOOL_ADD_JOB:
        return admin_tool_add_job(session, workgroup_id, requester_user_id, tool_input["job_name"], tool_input.get("description", ""))
    if tool_name == ADMIN_TOOL_ARCHIVE_JOB:
        return admin_tool_archive_job(session, workgroup_id, requester_user_id, tool_input["job_selector"])
    if tool_name == ADMIN_TOOL_UNARCHIVE_JOB:
        return admin_tool_unarchive_job(session, workgroup_id, requester_user_id, tool_input["job_selector"])
    if tool_name == ADMIN_TOOL_ADD_AGENT:
        return admin_tool_add_agent(
            session, workgroup_id, requester_user_id,
            name=tool_input["agent_name"],
            prompt=tool_input.get("prompt", ""),
            description=tool_input.get("description", ""),
            model=tool_input.get("model", ""),
        )
    if tool_name == ADMIN_TOOL_ADD_USER:
        return admin_tool_add_user(session, workgroup_id, requester_user_id, tool_input["email"])
    if tool_name == ADMIN_TOOL_ADD_FILE:
        return admin_tool_add_file(session, workgroup_id, requester_user_id, tool_input["path"], tool_input.get("content", ""))
    if tool_name == ADMIN_TOOL_EDIT_FILE:
        return admin_tool_edit_file(session, workgroup_id, requester_user_id, tool_input["path"], tool_input["content"])
    if tool_name == ADMIN_TOOL_RENAME_FILE:
        return admin_tool_rename_file(session, workgroup_id, requester_user_id, tool_input["source_path"], tool_input["destination_path"])
    if tool_name == ADMIN_TOOL_DELETE_FILE:
        return admin_tool_delete_file(session, workgroup_id, requester_user_id, tool_input["path"])
    if tool_name == ADMIN_TOOL_LIST_JOBS:
        return admin_tool_list_jobs(session, workgroup_id, status=tool_input.get("status", "open"))
    if tool_name == ADMIN_TOOL_LIST_MEMBERS:
        return admin_tool_list_members(session, workgroup_id)
    if tool_name == ADMIN_TOOL_LIST_FILES:
        return admin_tool_list_files(session, workgroup_id)
    if tool_name == ADMIN_TOOL_REMOVE_JOB:
        return admin_tool_remove_job(session, workgroup_id, requester_user_id, tool_input["job_selector"])
    if tool_name == ADMIN_TOOL_CLEAR_JOB_MESSAGES:
        return admin_tool_clear_job_messages(session, workgroup_id, requester_user_id, tool_input["job_selector"])
    if tool_name == ADMIN_TOOL_REMOVE_MEMBER:
        return admin_tool_remove_member(session, workgroup_id, requester_user_id, tool_input["member_selector"])
    if tool_name == ADMIN_TOOL_DELETE_WORKGROUP:
        return admin_tool_delete_workgroup(session, workgroup_id, requester_user_id, confirmed=tool_input.get("confirmed", False))
    if tool_name == ADMIN_TOOL_LIST_TASKS:
        return admin_tool_list_tasks(session, workgroup_id, direction=tool_input.get("direction", "all"))
    if tool_name == ADMIN_TOOL_ACCEPT_TASK:
        return admin_tool_accept_task(session, workgroup_id, requester_user_id, selector=tool_input["task_selector"])
    if tool_name == ADMIN_TOOL_DECLINE_TASK:
        return admin_tool_decline_task(session, workgroup_id, requester_user_id, selector=tool_input["task_selector"])
    if tool_name == ADMIN_TOOL_COMPLETE_TASK:
        return admin_tool_complete_task(session, workgroup_id, requester_user_id, selector=tool_input["task_selector"])
    if tool_name in GLOBAL_TOOL_NAMES:
        return _dispatch_global_tool(session, requester_user_id, tool_name, tool_input)
    return f"Unknown tool: {tool_name}"


def _sdk_enabled() -> bool:
    if not settings.admin_agent_use_sdk:
        return False
    return llm_client.llm_enabled()


def _message_sender_label(message: Message) -> str:
    if message.sender_type == "user":
        return f"user:{message.sender_user_id or 'unknown'}"
    return f"agent:{message.sender_agent_id or 'unknown'}"


def _conversation_history_context(
    session: Session,
    conversation_id: str,
    max_messages: int = 40,
    max_chars: int = 12000,
) -> str:
    rows = session.exec(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at.asc())
    ).all()
    if not rows:
        return ""

    if len(rows) > max_messages:
        rows = rows[-max_messages:]

    lines: list[str] = []
    for row in rows:
        text = " ".join(row.content.split())
        if len(text) > 320:
            text = text[:320].rstrip() + "..."
        lines.append(f"- {_message_sender_label(row)}: {text}")

    history = "\n".join(lines)
    if len(history) > max_chars:
        history = "...\n" + history[-max_chars:]
    return history


def _build_admin_llm_input(
    session: Session,
    conversation_id: str | None,
    message: str,
) -> str:
    if not conversation_id:
        return message

    history = _conversation_history_context(session, conversation_id=conversation_id)
    if not history:
        return message

    return (
        "Use the conversation history as context for references and follow-up actions.\n"
        "Conversation history (oldest to newest):\n"
        f"{history}\n\n"
        "Current user message:\n"
        f"{message}"
    )


def _handle_admin_message_with_sdk(
    session: Session,
    workgroup_id: str,
    requester_user_id: str,
    content: str,
    conversation_id: str | None = None,
    agent: Agent | None = None,
) -> str:
    message = content.strip()
    if not message:
        return _help_text()

    resolved_model = llm_client.resolve_model("admin", settings.admin_agent_model)

    is_global = _is_global_admin_context(session, workgroup_id)
    org_name = _is_org_admin_context(session, workgroup_id)

    system_instructions = (
        "You are the administration agent for a workgroup chat application. "
        "Use tools for every state-changing request. "
        "If the user asks to add/archive/unarchive/clear/remove job, add user, add agent, remove member, "
        "add/edit/rename/delete file, list jobs, list members, list files, or delete workgroup, "
        "call the matching tool. "
        "When extracting names for tools (job_name, agent_name, etc.), pass only the actual name — "
        "strip any surrounding context like 'to this workgroup' or 'in this group'. "
        "When adding jobs, include the description argument when the user provides one. "
        "When creating agents, include explicit prompt/model when provided. "
        "For add_agent, pass only the agent's short name in agent_name; put profile text into prompt. "
        "The default model for new agents is sonnet. "
        "For add_file/edit_file, include full file content in the content argument when provided. "
        "Deleting a workgroup is destructive; require explicit confirmation before execution. "
        "Never claim an action succeeded unless a tool returned success text. "
        "If a request is unsupported or ambiguous, ask one concise clarification or share supported commands. "
        "Keep responses concise and factual."
    )

    if is_global:
        system_instructions += (
            "\n\nYou are the global administration agent. You can manage organizations, create workgroups, "
            "add agents/jobs/files to any workgroup, and apply templates. When creating a complex "
            "structure (like a company), plan the steps then execute them one by one using tools. "
            "Use global_list_templates to see available templates before creating workgroups. "
            "When adding agents, choose appropriate tools from the available tools list. "
            "For cross-workgroup operations, use the global_* tools (they take workgroup_name). "
            "For operations on the current Administration workgroup itself, use the non-global tools."
        )
    elif org_name:
        system_instructions += (
            f"\n\nYou are the organization administration agent for '{org_name}'. "
            "You manage this organization's workgroups, agents, jobs, and files. "
            "Use the global_* tools to create workgroups, add agents, and manage resources "
            "across workgroups within this organization. "
            "Use global_list_templates to see available templates before creating workgroups. "
            "When adding agents, choose appropriate tools from the available tools list. "
            "For operations on this Administration workgroup itself, use the non-global tools."
        )

    # Filter tools by the responding agent's tool set.
    agent_tool_set = set(agent.tools) if agent and agent.tools else None
    if agent_tool_set is not None:
        admin_tools = [t for t in _ADMIN_TOOLS if t["name"] in agent_tool_set]
    else:
        admin_tools = list(_ADMIN_TOOLS)

    # Global tools filtered by agent's tool set (when in org/global context).
    if is_global or org_name:
        if agent_tool_set is not None:
            global_tools = [t for t in _GLOBAL_ADMIN_TOOLS if t["name"] in agent_tool_set]
        else:
            global_tools = list(_GLOBAL_ADMIN_TOOLS)
    else:
        global_tools = []

    tools = admin_tools + global_tools

    llm_input = _build_admin_llm_input(session=session, conversation_id=conversation_id, message=message)
    messages = [{"role": "user", "content": llm_input}]

    max_turns = 25 if (is_global or org_name) else 8
    response = None
    for _ in range(max_turns):
        t0 = time.monotonic()
        response = llm_client.create_message(
            model=resolved_model,
            max_tokens=16384,
            system=system_instructions,
            messages=messages,
            tools=tools,
        )
        duration_ms = int((time.monotonic() - t0) * 1000)
        if conversation_id:
            record_llm_usage(
                session, conversation_id, None, resolved_model,
                response.usage.input_tokens, response.usage.output_tokens,
                "admin", duration_ms,
            )

        if response.stop_reason == "end_turn":
            text_parts = [block.text for block in response.content if block.type == "text"]
            output = " ".join(text_parts).strip()
            return output or _help_text()

        if response.stop_reason != "tool_use":
            text_parts = [block.text for block in response.content if block.type == "text"]
            output = " ".join(text_parts).strip()
            return output or _help_text()

        messages.append({"role": "assistant", "content": response.content})

        tool_results = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            try:
                result = _dispatch_admin_tool(session, workgroup_id, requester_user_id, block.name, block.input)
            except Exception as exc:
                logger.warning("Admin tool %s failed: %s", block.name, exc)
                result = f"Error: {exc}"
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": result,
            })

        messages.append({"role": "user", "content": tool_results})

    if response is not None:
        text_parts = [block.text for block in response.content if block.type == "text"]
        output = " ".join(text_parts).strip()
        return output or _help_text()
    return _help_text()
