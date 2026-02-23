"""Admin workspace package — re-exports public API and orchestrates message handling."""

from __future__ import annotations

import logging

from sqlmodel import Session

logger = logging.getLogger(__name__)

from teaparty_app.services.admin_workspace.bootstrap import (  # noqa: F401
    ADMIN_AGENT_SENTINEL,
    ADMIN_CONVERSATION_NAME,
    ADMIN_TEAM_NAMES,
    ADMIN_TOOL_ADD_AGENT,
    ADMIN_TOOL_ADD_FILE,
    ADMIN_TOOL_ADD_USER,
    ADMIN_TOOL_DELETE_FILE,
    ADMIN_TOOL_DELETE_WORKGROUP,
    ADMIN_TOOL_EDIT_FILE,
    ADMIN_TOOL_LIST_FILES,
    ADMIN_TOOL_LIST_MEMBERS,
    ADMIN_TOOL_NAMES,
    ADMIN_TOOL_REMOVE_MEMBER,
    ADMIN_TOOL_RENAME_FILE,
    ADMINISTRATION_WORKGROUP_NAME,
    SYSTEM_WORKGROUP_NAMES,
    is_system_workgroup,
    GLOBAL_TOOL_ADD_AGENT,
    GLOBAL_TOOL_ADD_FILE,
    GLOBAL_TOOL_CREATE_ORGANIZATION,
    GLOBAL_TOOL_CREATE_WORKGROUP,
    GLOBAL_TOOL_LIST_AGENTS,
    GLOBAL_TOOL_LIST_ORGANIZATIONS,
    GLOBAL_TOOL_LIST_TEMPLATES,
    GLOBAL_TOOL_LIST_WORKGROUPS,
    GLOBAL_TOOL_NAMES,
    GLOBAL_TOOL_EDIT_WORKGROUP,
    GLOBAL_TOOL_ADD_AGENT_TO_WORKGROUP,
    GLOBAL_TOOL_REMOVE_AGENT_FROM_WORKGROUP,
    GLOBAL_TOOL_LIST_PARTNERS,
    GLOBAL_TOOL_FIND_ORGANIZATION,
    GLOBAL_TOOL_ADD_PARTNER,
    GLOBAL_TOOL_DELETE_PARTNER,
    GLOBAL_TOOL_FIND_AGENT,
    GLOBAL_TOOL_DELETE_AGENT,
    GLOBAL_TOOL_ADD_TOOL_TO_AGENT,
    GLOBAL_TOOL_REMOVE_TOOL_FROM_AGENT,
    GLOBAL_TOOL_LIST_WORKFLOWS,
    GLOBAL_TOOL_CREATE_WORKFLOW,
    GLOBAL_TOOL_DELETE_WORKFLOW,
    GLOBAL_TOOL_FIND_WORKFLOW,
    SESSION_DELETE_WORKGROUP_KEY,
    direct_conversation_key,
    direct_conversation_key_user_agent,
    ensure_admin_workspace,
    ensure_admin_workspace_for_workgroup_id,
    ensure_direct_conversation,
    ensure_direct_conversation_with_agent,
    ensure_lead_agent,
    find_admin_agent,
    find_admin_agents,
    find_admin_conversation,
    is_admin_agent,
    is_lead_agent,
    lead_agent_name,
    list_members,
)
from teaparty_app.services.admin_workspace.parsing import (  # noqa: F401
    ADD_AGENT_RE,
    ADD_FILE_RE,
    ADD_USER_RE,
    DELETE_FILE_RE,
    DELETE_WORKGROUP_RE,
    EDIT_FILE_RE,
    LIST_FILES_RE,
    LIST_MEMBERS_RE,
    REMOVE_MEMBER_RE,
    RENAME_FILE_RE,
    _help_text,
    _is_confirmed_word,
    _normalize_admin_message_for_matching,
    _normalize_file_content,
    _parse_add_agent_payload,
    _parse_file_payload,
    _parse_temperature,
)
from teaparty_app.services.admin_workspace.tools_common import (  # noqa: F401
    ResolvedMemberTarget,
    clear_conversation_messages,
    consume_queued_workgroup_deletion,
    delete_workgroup_data,
    queue_workgroup_deletion,
)
from teaparty_app.services.admin_workspace.member_tools import (  # noqa: F401
    admin_tool_add_agent,
    admin_tool_add_user,
    admin_tool_delete_workgroup,
    admin_tool_list_members,
    admin_tool_remove_member,
)
from teaparty_app.services.admin_workspace.file_tools import (  # noqa: F401
    admin_tool_add_file,
    admin_tool_delete_file,
    admin_tool_edit_file,
    admin_tool_list_files,
    admin_tool_rename_file,
)
def _handle_admin_message_deterministic(
    session: Session,
    workgroup_id: str,
    requester_user_id: str,
    content: str,
    allowed_tools: set[str] | None = None,
) -> str | None:
    message = _normalize_admin_message_for_matching(content)
    if not message:
        return None

    def _tool_allowed(tool_name: str) -> bool:
        return allowed_tools is None or tool_name in allowed_tools

    delete_workgroup_match = DELETE_WORKGROUP_RE.match(message)
    if delete_workgroup_match and _tool_allowed(ADMIN_TOOL_DELETE_WORKGROUP):
        return admin_tool_delete_workgroup(
            session=session,
            workgroup_id=workgroup_id,
            requester_user_id=requester_user_id,
            confirmed=_is_confirmed_word(delete_workgroup_match.group(1)),
        )

    add_agent_match = ADD_AGENT_RE.match(message)
    if add_agent_match and _tool_allowed(ADMIN_TOOL_ADD_AGENT):
        name, parsed = _parse_add_agent_payload(add_agent_match.group(1))
        if not name:
            return "Usage: add agent <name> [prompt=<text>] [model=<name>]"
        return admin_tool_add_agent(
            session=session,
            workgroup_id=workgroup_id,
            requester_user_id=requester_user_id,
            name=name,
            prompt=parsed["prompt"],
            model=parsed["model"],
        )

    add_user_match = ADD_USER_RE.match(message)
    if add_user_match and _tool_allowed(ADMIN_TOOL_ADD_USER):
        return admin_tool_add_user(session, workgroup_id, requester_user_id, add_user_match.group(1))

    rename_file_match = RENAME_FILE_RE.match(message)
    if rename_file_match and _tool_allowed(ADMIN_TOOL_RENAME_FILE):
        return admin_tool_rename_file(
            session=session,
            workgroup_id=workgroup_id,
            requester_user_id=requester_user_id,
            source_path=rename_file_match.group(1),
            destination_path=rename_file_match.group(2),
        )

    delete_file_match = DELETE_FILE_RE.match(message)
    if delete_file_match and _tool_allowed(ADMIN_TOOL_DELETE_FILE):
        return admin_tool_delete_file(
            session=session,
            workgroup_id=workgroup_id,
            requester_user_id=requester_user_id,
            path=delete_file_match.group(1),
        )

    edit_file_match = EDIT_FILE_RE.match(message)
    if edit_file_match and _tool_allowed(ADMIN_TOOL_EDIT_FILE):
        file_path, file_content, has_content = _parse_file_payload(edit_file_match.group(1))
        if not has_content:
            return "Usage: edit file <path> content=<text>"
        return admin_tool_edit_file(
            session=session,
            workgroup_id=workgroup_id,
            requester_user_id=requester_user_id,
            path=file_path,
            content=file_content,
        )

    add_file_match = ADD_FILE_RE.match(message)
    if add_file_match and _tool_allowed(ADMIN_TOOL_ADD_FILE):
        file_path, file_content, _has_content = _parse_file_payload(add_file_match.group(1))
        return admin_tool_add_file(
            session=session,
            workgroup_id=workgroup_id,
            requester_user_id=requester_user_id,
            path=file_path,
            content=file_content,
        )

    remove_member_match = REMOVE_MEMBER_RE.match(message)
    if remove_member_match and _tool_allowed(ADMIN_TOOL_REMOVE_MEMBER):
        return admin_tool_remove_member(
            session=session,
            workgroup_id=workgroup_id,
            requester_user_id=requester_user_id,
            member_selector=remove_member_match.group(1),
        )

    list_files_match = LIST_FILES_RE.match(message)
    if list_files_match and _tool_allowed(ADMIN_TOOL_LIST_FILES):
        return admin_tool_list_files(session, workgroup_id)

    list_members_match = LIST_MEMBERS_RE.match(message)
    if list_members_match and _tool_allowed(ADMIN_TOOL_LIST_MEMBERS):
        return admin_tool_list_members(session, workgroup_id)

    return None


def handle_admin_message(
    session: Session,
    workgroup_id: str,
    requester_user_id: str,
    content: str,
    conversation_id: str | None = None,
    agent: "Agent | None" = None,
) -> str:
    from teaparty_app.services.admin_workspace.sdk_integration import (
        _handle_admin_message_with_sdk,
        _sdk_enabled,
    )

    allowed_tools = set(agent.tools) if agent and agent.tools else None

    # Primary path: LLM-driven agentic loop.
    if _sdk_enabled():
        try:
            return _handle_admin_message_with_sdk(
                session=session,
                workgroup_id=workgroup_id,
                requester_user_id=requester_user_id,
                content=content,
                conversation_id=conversation_id,
                agent=agent,
            )
        except Exception:
            logger.exception("Admin SDK handler failed, falling back to deterministic parsing")

    # Fallback: deterministic regex dispatch (no API key needed).
    deterministic = _handle_admin_message_deterministic(
        session=session,
        workgroup_id=workgroup_id,
        requester_user_id=requester_user_id,
        content=content,
        allowed_tools=allowed_tools,
    )
    if deterministic is not None:
        return deterministic

    return _help_text()
