"""Admin workspace package — re-exports public API and orchestrates message handling."""

from __future__ import annotations

import logging

from sqlmodel import Session

logger = logging.getLogger(__name__)

from teaparty_app.services.admin_workspace.bootstrap import (  # noqa: F401
    ADMIN_AGENT_SENTINEL,
    ADMIN_CONVERSATION_NAME,
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
    ADMIN_TOOL_NAMES,
    ADMIN_TOOL_REMOVE_MEMBER,
    ADMIN_TOOL_REMOVE_JOB,
    ADMIN_TOOL_RENAME_FILE,
    ADMIN_TOOL_UNARCHIVE_JOB,
    ADMINISTRATION_WORKGROUP_NAME,
    GLOBAL_TOOL_ADD_AGENT,
    GLOBAL_TOOL_ADD_FILE,
    GLOBAL_TOOL_ADD_JOB,
    GLOBAL_TOOL_CREATE_ORGANIZATION,
    GLOBAL_TOOL_CREATE_WORKGROUP,
    GLOBAL_TOOL_LIST_AGENTS,
    GLOBAL_TOOL_LIST_ORGANIZATIONS,
    GLOBAL_TOOL_LIST_TEMPLATES,
    GLOBAL_TOOL_LIST_JOBS,
    GLOBAL_TOOL_LIST_WORKGROUPS,
    GLOBAL_TOOL_NAMES,
    SESSION_DELETE_WORKGROUP_KEY,
    direct_conversation_key,
    direct_conversation_key_user_agent,
    ensure_admin_workspace,
    ensure_admin_workspace_for_workgroup_id,
    ensure_direct_conversation,
    ensure_direct_conversation_with_agent,
    ensure_lead_agent,
    find_admin_agent,
    find_admin_conversation,
    is_admin_agent,
    is_lead_agent,
    lead_agent_name,
    list_members,
)
from teaparty_app.services.admin_workspace.parsing import (  # noqa: F401
    ACCEPT_TASK_RE,
    ADD_AGENT_RE,
    ADD_FILE_RE,
    ADD_JOB_RE,
    ADD_USER_RE,
    ARCHIVE_JOB_RE,
    CLEAR_JOB_MESSAGES_RE,
    COMPLETE_TASK_RE,
    DECLINE_TASK_RE,
    DELETE_FILE_RE,
    DELETE_WORKGROUP_RE,
    EDIT_FILE_RE,
    LIST_FILES_RE,
    LIST_MEMBERS_RE,
    LIST_TASKS_RE,
    LIST_JOBS_RE,
    REMOVE_MEMBER_RE,
    REMOVE_JOB_RE,
    RENAME_FILE_RE,
    UNARCHIVE_JOB_RE,
    _help_text,
    _is_confirmed_word,
    _normalize_admin_message_for_matching,
    _normalize_file_content,
    _normalize_list_jobs_status,
    _normalize_task_selector,
    _normalize_job_selector,
    _parse_add_agent_payload,
    _parse_add_job_payload,
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
from teaparty_app.services.admin_workspace.job_tools import (  # noqa: F401
    admin_tool_add_job,
    admin_tool_archive_job,
    admin_tool_clear_job_messages,
    admin_tool_list_jobs,
    admin_tool_remove_job,
    admin_tool_unarchive_job,
)
from teaparty_app.services.admin_workspace.task_tools import (  # noqa: F401
    admin_tool_accept_task,
    admin_tool_complete_task,
    admin_tool_decline_task,
    admin_tool_list_tasks,
)


def _handle_admin_message_deterministic(
    session: Session,
    workgroup_id: str,
    requester_user_id: str,
    content: str,
) -> str | None:
    message = _normalize_admin_message_for_matching(content)
    if not message:
        return None

    delete_workgroup_match = DELETE_WORKGROUP_RE.match(message)
    if delete_workgroup_match:
        return admin_tool_delete_workgroup(
            session=session,
            workgroup_id=workgroup_id,
            requester_user_id=requester_user_id,
            confirmed=_is_confirmed_word(delete_workgroup_match.group(1)),
        )

    unarchive_match = UNARCHIVE_JOB_RE.match(message)
    if unarchive_match:
        return admin_tool_unarchive_job(session, workgroup_id, requester_user_id, unarchive_match.group(1))

    archive_match = ARCHIVE_JOB_RE.match(message)
    if archive_match:
        return admin_tool_archive_job(session, workgroup_id, requester_user_id, archive_match.group(1))

    remove_job_match = REMOVE_JOB_RE.match(message)
    if remove_job_match:
        return admin_tool_remove_job(
            session=session,
            workgroup_id=workgroup_id,
            requester_user_id=requester_user_id,
            selector=remove_job_match.group(1),
        )

    clear_job_match = CLEAR_JOB_MESSAGES_RE.match(message)
    if clear_job_match:
        return admin_tool_clear_job_messages(
            session=session,
            workgroup_id=workgroup_id,
            requester_user_id=requester_user_id,
            selector=clear_job_match.group(1),
        )

    add_job_match = ADD_JOB_RE.match(message)
    if add_job_match:
        job_name, job_description = _parse_add_job_payload(add_job_match.group(1))
        return admin_tool_add_job(
            session=session,
            workgroup_id=workgroup_id,
            requester_user_id=requester_user_id,
            topic_name=job_name,
            description=job_description,
        )

    add_agent_match = ADD_AGENT_RE.match(message)
    if add_agent_match:
        name, parsed = _parse_add_agent_payload(add_agent_match.group(1))
        if not name:
            return "Usage: add agent <name> [role=<text>] [personality=<text>] [backstory=<text>] [model=<name>] [temperature=<0..2>]"
        return admin_tool_add_agent(
            session=session,
            workgroup_id=workgroup_id,
            requester_user_id=requester_user_id,
            name=name,
            personality=parsed["personality"],
            role=parsed["role"],
            backstory=parsed["backstory"],
            model=parsed["model"],
            temperature=parsed["temperature"],
        )

    add_user_match = ADD_USER_RE.match(message)
    if add_user_match:
        return admin_tool_add_user(session, workgroup_id, requester_user_id, add_user_match.group(1))

    rename_file_match = RENAME_FILE_RE.match(message)
    if rename_file_match:
        return admin_tool_rename_file(
            session=session,
            workgroup_id=workgroup_id,
            requester_user_id=requester_user_id,
            source_path=rename_file_match.group(1),
            destination_path=rename_file_match.group(2),
        )

    delete_file_match = DELETE_FILE_RE.match(message)
    if delete_file_match:
        return admin_tool_delete_file(
            session=session,
            workgroup_id=workgroup_id,
            requester_user_id=requester_user_id,
            path=delete_file_match.group(1),
        )

    edit_file_match = EDIT_FILE_RE.match(message)
    if edit_file_match:
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
    if add_file_match:
        file_path, file_content, _has_content = _parse_file_payload(add_file_match.group(1))
        return admin_tool_add_file(
            session=session,
            workgroup_id=workgroup_id,
            requester_user_id=requester_user_id,
            path=file_path,
            content=file_content,
        )

    remove_member_match = REMOVE_MEMBER_RE.match(message)
    if remove_member_match:
        return admin_tool_remove_member(
            session=session,
            workgroup_id=workgroup_id,
            requester_user_id=requester_user_id,
            member_selector=remove_member_match.group(1),
        )

    list_jobs_match = LIST_JOBS_RE.match(message)
    if list_jobs_match:
        status_selector = list_jobs_match.group(1) or list_jobs_match.group(2) or "open"
        return admin_tool_list_jobs(session, workgroup_id, status=status_selector)

    list_files_match = LIST_FILES_RE.match(message)
    if list_files_match:
        return admin_tool_list_files(session, workgroup_id)

    list_members_match = LIST_MEMBERS_RE.match(message)
    if list_members_match:
        return admin_tool_list_members(session, workgroup_id)

    list_tasks_match = LIST_TASKS_RE.match(message)
    if list_tasks_match:
        direction = list_tasks_match.group(1) or "all"
        return admin_tool_list_tasks(session, workgroup_id, direction=direction)

    accept_task_match = ACCEPT_TASK_RE.match(message)
    if accept_task_match:
        return admin_tool_accept_task(
            session=session,
            workgroup_id=workgroup_id,
            requester_user_id=requester_user_id,
            selector=accept_task_match.group(1),
        )

    decline_task_match = DECLINE_TASK_RE.match(message)
    if decline_task_match:
        return admin_tool_decline_task(
            session=session,
            workgroup_id=workgroup_id,
            requester_user_id=requester_user_id,
            selector=decline_task_match.group(1),
        )

    complete_task_match = COMPLETE_TASK_RE.match(message)
    if complete_task_match:
        return admin_tool_complete_task(
            session=session,
            workgroup_id=workgroup_id,
            requester_user_id=requester_user_id,
            selector=complete_task_match.group(1),
        )

    return None


def handle_admin_message(
    session: Session,
    workgroup_id: str,
    requester_user_id: str,
    content: str,
    conversation_id: str | None = None,
) -> str:
    from teaparty_app.services.admin_workspace.sdk_integration import (
        _handle_admin_message_with_sdk,
        _sdk_enabled,
    )

    # Primary path: LLM-driven agentic loop.
    if _sdk_enabled():
        try:
            return _handle_admin_message_with_sdk(
                session=session,
                workgroup_id=workgroup_id,
                requester_user_id=requester_user_id,
                content=content,
                conversation_id=conversation_id,
            )
        except Exception:
            logger.exception("Admin SDK handler failed, falling back to deterministic parsing")

    # Fallback: deterministic regex dispatch (no API key needed).
    deterministic = _handle_admin_message_deterministic(
        session=session,
        workgroup_id=workgroup_id,
        requester_user_id=requester_user_id,
        content=content,
    )
    if deterministic is not None:
        return deterministic

    return _help_text()
