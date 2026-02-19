"""Create and update engagement tracking files on Engagement.files."""

from __future__ import annotations

from uuid import uuid4

from sqlmodel import Session

from teaparty_app.models import Engagement, Workgroup, utc_now


def _timestamp() -> str:
    return utc_now().strftime("%Y-%m-%d %H:%M UTC")


def _render_agreement(engagement: Engagement, source_name: str, target_name: str) -> str:
    price_str = f"{engagement.agreed_price_credits} credits" if engagement.agreed_price_credits else "(not set)"
    payment_str = getattr(engagement, "payment_status", "none") or "none"
    return (
        f"# Engagement: {engagement.title}\n\n"
        f"**Status:** {engagement.status}\n\n"
        f"## Parties\n"
        f"- **Source (requester):** {source_name}\n"
        f"- **Target (provider):** {target_name}\n\n"
        f"## Scope\n{engagement.scope or '(none)'}\n\n"
        f"## Requirements\n{engagement.requirements or '(none)'}\n\n"
        f"## Terms\n{engagement.terms or '(none)'}\n\n"
        f"## Price\n{price_str}\n\n"
        f"## Payment Status\n{payment_str}\n\n"
        f"## Deliverables\n{engagement.deliverables or '(none)'}\n\n"
        f"## Timeline\n"
        f"- Created: {engagement.created_at.strftime('%Y-%m-%d %H:%M UTC') if engagement.created_at else 'N/A'}\n"
        f"- Accepted: {engagement.accepted_at.strftime('%Y-%m-%d %H:%M UTC') if engagement.accepted_at else 'N/A'}\n"
        f"- Completed: {engagement.completed_at.strftime('%Y-%m-%d %H:%M UTC') if engagement.completed_at else 'N/A'}\n"
        f"- Reviewed: {engagement.reviewed_at.strftime('%Y-%m-%d %H:%M UTC') if engagement.reviewed_at else 'N/A'}\n"
    )


def _render_deliverables(engagement: Engagement) -> str:
    return (
        f"# Deliverables: {engagement.title}\n\n"
        f"## Deliverables List\n{engagement.deliverables or '(to be defined)'}\n\n"
        f"## Status Updates\n"
        f"- [{_timestamp()}] Engagement accepted — work begins.\n"
    )


def _add_file(engagement: Engagement, path: str, content: str) -> None:
    """Add a file to Engagement.files."""
    raw_files = engagement.files if isinstance(engagement.files, list) else []
    all_files = list(raw_files)
    all_files.append({"id": str(uuid4()), "path": path, "content": content})
    engagement.files = all_files


def _update_file(engagement: Engagement, path: str, content: str) -> None:
    """Update a file's content on Engagement.files."""
    raw_files = engagement.files if isinstance(engagement.files, list) else []
    found = False
    new_files = []
    for entry in raw_files:
        if isinstance(entry, dict) and entry.get("path") == path:
            new_files.append({**entry, "content": content})
            found = True
        else:
            new_files.append(dict(entry) if isinstance(entry, dict) else entry)
    if found:
        engagement.files = new_files
        return
    _add_file(engagement, path, content)


def _append_to_deliverables(engagement: Engagement, path: str, line: str) -> None:
    """Append a status update line to the deliverables file."""
    raw_files = engagement.files if isinstance(engagement.files, list) else []
    new_files = []
    for entry in raw_files:
        if isinstance(entry, dict) and entry.get("path") == path:
            current = entry.get("content") or ""
            new_content = current.rstrip() + f"\n- [{_timestamp()}] {line}\n"
            new_files.append({**entry, "content": new_content})
        else:
            new_files.append(dict(entry) if isinstance(entry, dict) else entry)
    engagement.files = new_files


def create_engagement_files(
    session: Session,
    engagement: Engagement,
    source_wg: Workgroup,
    target_wg: Workgroup,
) -> None:
    """Write agreement.md and deliverables.md to Engagement.files."""
    source_name = source_wg.name
    target_name = target_wg.name

    agreement_content = _render_agreement(engagement, source_name, target_name)
    deliverables_content = _render_deliverables(engagement)

    _add_file(engagement, "agreement.md", agreement_content)
    _add_file(engagement, "deliverables.md", deliverables_content)
    session.add(engagement)


def update_engagement_files(
    session: Session,
    engagement: Engagement,
    source_wg: Workgroup,
    target_wg: Workgroup,
    event: str,
    detail: str = "",
) -> None:
    """Update agreement.md and append to deliverables.md on Engagement.files."""
    source_name = source_wg.name
    target_name = target_wg.name

    agreement_content = _render_agreement(engagement, source_name, target_name)
    _update_file(engagement, "agreement.md", agreement_content)

    line = event
    if detail:
        line += f" — {detail}"
    _append_to_deliverables(engagement, "deliverables.md", line)
    session.add(engagement)
