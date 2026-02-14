"""Activity channel service for workgroup event notifications."""

from __future__ import annotations

from sqlmodel import Session, select

from teaparty_app.models import (
    Conversation,
    ConversationParticipant,
    Membership,
    Message,
    Workgroup,
)

ACTIVITY_CONVERSATION_TOPIC = "Activity"


def _find_activity_conversation(session: Session, workgroup_id: str) -> Conversation | None:
    return session.exec(
        select(Conversation).where(
            Conversation.workgroup_id == workgroup_id,
            Conversation.kind == "activity",
        )
    ).first()


def ensure_activity_conversation(
    session: Session,
    workgroup: Workgroup,
) -> tuple[Conversation, bool]:
    changed = False

    activity_conversation = _find_activity_conversation(session, workgroup.id)
    if not activity_conversation:
        activity_conversation = Conversation(
            workgroup_id=workgroup.id,
            created_by_user_id=workgroup.owner_id,
            kind="activity",
            topic=ACTIVITY_CONVERSATION_TOPIC,
            name=ACTIVITY_CONVERSATION_TOPIC,
            description="Automatic notifications for workgroup events.",
            is_archived=False,
        )
        session.add(activity_conversation)
        session.flush()
        changed = True

    memberships = session.exec(
        select(Membership).where(Membership.workgroup_id == workgroup.id)
    ).all()

    existing_participants = session.exec(
        select(ConversationParticipant).where(
            ConversationParticipant.conversation_id == activity_conversation.id,
        )
    ).all()
    existing_user_ids = {p.user_id for p in existing_participants if p.user_id}

    for membership in memberships:
        if membership.user_id not in existing_user_ids:
            session.add(
                ConversationParticipant(
                    conversation_id=activity_conversation.id,
                    user_id=membership.user_id,
                )
            )
            changed = True

    return activity_conversation, changed


def ensure_activity_conversation_for_workgroup_id(
    session: Session,
    workgroup_id: str,
) -> tuple[Conversation, bool]:
    workgroup = session.get(Workgroup, workgroup_id)
    if not workgroup:
        from fastapi import HTTPException, status

        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workgroup not found")
    return ensure_activity_conversation(session, workgroup)


def add_activity_participant(
    session: Session,
    workgroup_id: str,
    user_id: str,
) -> bool:
    activity_conversation = _find_activity_conversation(session, workgroup_id)
    if not activity_conversation:
        return False

    existing = session.exec(
        select(ConversationParticipant).where(
            ConversationParticipant.conversation_id == activity_conversation.id,
            ConversationParticipant.user_id == user_id,
        )
    ).first()
    if existing:
        return False

    session.add(
        ConversationParticipant(
            conversation_id=activity_conversation.id,
            user_id=user_id,
        )
    )
    return True


def post_activity(
    session: Session,
    workgroup_id: str,
    event_type: str,
    description: str,
    *,
    actor_user_id: str | None = None,
    actor_agent_id: str | None = None,
) -> Message | None:
    activity_conversation = _find_activity_conversation(session, workgroup_id)
    if not activity_conversation:
        return None

    message = Message(
        conversation_id=activity_conversation.id,
        sender_type="system",
        sender_user_id=actor_user_id,
        sender_agent_id=actor_agent_id,
        content=f"[{event_type}] {description}",
        requires_response=False,
    )
    session.add(message)
    return message


def post_file_change_activity(
    session: Session,
    workgroup_id: str,
    event_type: str,
    file_path: str,
    *,
    actor_user_id: str | None = None,
    actor_agent_id: str | None = None,
) -> Message | None:
    return post_activity(
        session,
        workgroup_id,
        event_type,
        file_path,
        actor_user_id=actor_user_id,
        actor_agent_id=actor_agent_id,
    )


def _compute_file_diff(
    old_files: list[dict[str, str]],
    new_files: list[dict[str, str]],
) -> list[str]:
    old_by_id = {f["id"]: f for f in old_files if f.get("id")}
    new_by_id = {f["id"]: f for f in new_files if f.get("id")}
    old_by_path = {f["path"]: f for f in old_files}
    new_by_path = {f["path"]: f for f in new_files}

    lines: list[str] = []

    # Detect renames and modifications by matching IDs
    for file_id, new_file in new_by_id.items():
        old_file = old_by_id.get(file_id)
        if not old_file:
            continue
        if old_file["path"] != new_file["path"]:
            lines.append(f"Renamed '{old_file['path']}' to '{new_file['path']}'")
            if old_file.get("content", "") != new_file.get("content", ""):
                lines.append(f"Modified '{new_file['path']}'")
        elif old_file.get("content", "") != new_file.get("content", ""):
            lines.append(f"Modified '{new_file['path']}'")

    # Detect added files (path not in old)
    old_ids = set(old_by_id.keys())
    for file_id, new_file in new_by_id.items():
        if file_id not in old_ids and new_file["path"] not in old_by_path:
            lines.append(f"Added '{new_file['path']}'")

    # Also check files without IDs in new but not old
    for new_file in new_files:
        if not new_file.get("id") and new_file["path"] not in old_by_path:
            lines.append(f"Added '{new_file['path']}'")

    # Detect removed files (path in old but not in new, and ID not reused)
    new_ids = set(new_by_id.keys())
    for file_id, old_file in old_by_id.items():
        if file_id not in new_ids and old_file["path"] not in new_by_path:
            lines.append(f"Removed '{old_file['path']}'")

    # Also check files without IDs in old but not new
    for old_file in old_files:
        if not old_file.get("id") and old_file["path"] not in new_by_path:
            lines.append(f"Removed '{old_file['path']}'")

    return lines


def post_bulk_file_change_activity(
    session: Session,
    workgroup_id: str,
    old_files: list[dict[str, str]],
    new_files: list[dict[str, str]],
    *,
    actor_user_id: str | None = None,
) -> Message | None:
    diff_lines = _compute_file_diff(old_files, new_files)
    if not diff_lines:
        return None

    description = "; ".join(diff_lines)
    return post_activity(
        session,
        workgroup_id,
        "files_changed",
        description,
        actor_user_id=actor_user_id,
    )
