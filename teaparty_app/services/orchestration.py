"""Orchestration service for coordinator agents.

Provides functions that coordinator agents invoke (via the CLI module)
to manage engagements, jobs, and payments programmatically.
"""

from __future__ import annotations

import logging
from sqlmodel import Session, select

from teaparty_app.models import (
    Agent,
    Conversation,
    ConversationParticipant,
    Engagement,
    Job,
    Message,
    Organization,
    Workgroup,
    utc_now,
)
from teaparty_app.services.activity import post_activity
from teaparty_app.services.payments import (
    InsufficientBalanceError,
    escrow_for_engagement,
    get_or_create_balance,
    refund_escrow,
    release_escrow,
)

logger = logging.getLogger(__name__)


def browse_directory(session: Session) -> list[dict]:
    """List organizations accepting engagements."""
    orgs = session.exec(
        select(Organization).where(Organization.is_accepting_engagements == True)  # noqa: E712
    ).all()
    return [
        {
            "id": org.id,
            "name": org.name,
            "description": org.description,
            "service_description": org.service_description,
        }
        for org in orgs
    ]


def check_balance(session: Session, org_id: str) -> dict:
    """Return an org's credit balance."""
    org = session.get(Organization, org_id)
    if not org:
        return {"error": "Organization not found"}
    balance = get_or_create_balance(session, org_id)
    return {
        "organization_id": org_id,
        "organization_name": org.name,
        "balance_credits": balance.balance_credits,
    }


def propose_engagement_by_agent(
    session: Session,
    agent_id: str,
    target_org_id: str,
    title: str,
    scope: str = "",
    requirements: str = "",
) -> dict:
    """Create an engagement proposal from the agent's org to a target org."""
    agent = session.get(Agent, agent_id)
    if not agent:
        return {"error": "Agent not found"}

    # Find the agent's workgroup and org
    workgroup = session.get(Workgroup, agent.workgroup_id)
    if not workgroup or not workgroup.organization_id:
        return {"error": "Agent's workgroup has no organization"}

    source_org = session.get(Organization, workgroup.organization_id)
    if not source_org:
        return {"error": "Source organization not found"}

    target_org = session.get(Organization, target_org_id)
    if not target_org:
        return {"error": "Target organization not found"}

    # Find target org's operations workgroup
    if target_org.operations_workgroup_id:
        target_wg = session.get(Workgroup, target_org.operations_workgroup_id)
    else:
        # Fall back to first workgroup in the target org
        target_wg = session.exec(
            select(Workgroup).where(Workgroup.organization_id == target_org_id)
        ).first()

    if not target_wg:
        return {"error": "Target organization has no workgroups"}

    # Use the org owner as proposed_by_user_id (agent acts on behalf of org owner)
    engagement = Engagement(
        source_workgroup_id=workgroup.id,
        target_workgroup_id=target_wg.id,
        proposed_by_user_id=source_org.owner_id,
        status="proposed",
        title=title.strip(),
        scope=scope.strip(),
        requirements=requirements.strip(),
    )
    session.add(engagement)
    session.flush()

    # Create source conversation
    source_conv = Conversation(
        workgroup_id=workgroup.id,
        created_by_user_id=source_org.owner_id,
        kind="engagement",
        topic=f"engagement:{engagement.id}",
        name=engagement.title,
        description=f"Engagement with {target_org.name}",
    )
    session.add(source_conv)
    session.flush()
    session.add(ConversationParticipant(conversation_id=source_conv.id, user_id=source_org.owner_id))

    # Create target conversation
    target_conv = Conversation(
        workgroup_id=target_wg.id,
        created_by_user_id=source_org.owner_id,
        kind="engagement",
        topic=f"engagement:{engagement.id}",
        name=engagement.title,
        description=f"Engagement from {source_org.name}",
    )
    session.add(target_conv)
    session.flush()
    session.add(ConversationParticipant(conversation_id=target_conv.id, user_id=target_org.owner_id))

    engagement.source_conversation_id = source_conv.id
    engagement.target_conversation_id = target_conv.id
    session.add(engagement)

    # Post system messages
    proposal_msg = (
        f"[Engagement proposed] {engagement.title}\n"
        f"Scope: {engagement.scope or '(none)'}\n"
        f"Requirements: {engagement.requirements or '(none)'}"
    )
    _post_system_message(session, source_conv.id, proposal_msg)
    _post_system_message(session, target_conv.id, proposal_msg)

    post_activity(session, workgroup.id, "engagement_proposed",
                  f"Proposed engagement: {engagement.title}", actor_agent_id=agent_id)
    post_activity(session, target_wg.id, "engagement_proposed",
                  f"New engagement proposal: {engagement.title}", actor_agent_id=agent_id)

    session.flush()

    return {
        "engagement_id": engagement.id,
        "title": engagement.title,
        "status": engagement.status,
        "source_conversation_id": source_conv.id,
        "target_conversation_id": target_conv.id,
    }


def respond_engagement_by_agent(
    session: Session,
    agent_id: str,
    engagement_id: str,
    action: str,
    terms: str = "",
) -> dict:
    """Accept or decline an engagement on behalf of the agent's org."""
    agent = session.get(Agent, agent_id)
    if not agent:
        return {"error": "Agent not found"}

    engagement = session.get(Engagement, engagement_id)
    if not engagement:
        return {"error": "Engagement not found"}

    # Verify agent belongs to the target workgroup
    if agent.workgroup_id != engagement.target_workgroup_id:
        # Check if agent's workgroup is in the same org as the target workgroup
        agent_wg = session.get(Workgroup, agent.workgroup_id)
        target_wg = session.get(Workgroup, engagement.target_workgroup_id)
        if not agent_wg or not target_wg or agent_wg.organization_id != target_wg.organization_id:
            return {"error": "Agent does not belong to the target organization"}

    if engagement.status not in ("proposed", "negotiating"):
        return {"error": f"Cannot respond to engagement in status '{engagement.status}'"}

    now = utc_now()

    if action == "decline":
        engagement.status = "declined"
        engagement.declined_at = now
        if terms:
            engagement.terms = terms.strip()
        session.add(engagement)

        _post_system_message(session, engagement.source_conversation_id,
                             f"[Engagement declined] {engagement.title}")
        _post_system_message(session, engagement.target_conversation_id,
                             f"[Engagement declined] {engagement.title}")
        session.flush()
        return {"engagement_id": engagement.id, "status": "declined"}

    # Accept flow
    engagement.status = "in_progress"
    engagement.accepted_at = now
    if terms:
        engagement.terms = terms.strip()
    session.add(engagement)

    # Escrow payment if price is set
    try:
        escrow_for_engagement(session, engagement)
    except InsufficientBalanceError as e:
        # Roll back acceptance
        engagement.status = "proposed"
        engagement.accepted_at = None
        session.add(engagement)
        session.flush()
        return {"error": f"Insufficient balance: {e.available} available, {e.required} required"}

    terms_note = f"\nTerms: {engagement.terms}" if engagement.terms else ""
    _post_system_message(session, engagement.source_conversation_id,
                         f"[Engagement accepted] {engagement.title}{terms_note}")
    _post_system_message(session, engagement.target_conversation_id,
                         f"[Engagement accepted] {engagement.title}{terms_note}")

    # Create engagement files
    source_wg = session.get(Workgroup, engagement.source_workgroup_id)
    target_wg = session.get(Workgroup, engagement.target_workgroup_id)
    if source_wg and target_wg:
        from teaparty_app.services.engagement_files import create_engagement_files
        create_engagement_files(session, engagement, source_wg, target_wg)

    session.flush()

    return {
        "engagement_id": engagement.id,
        "status": "in_progress",
        "payment_status": engagement.payment_status,
    }


def set_engagement_price(
    session: Session,
    engagement_id: str,
    price_credits: float,
) -> dict:
    """Record the agreed price and post notifications to both conversations."""
    engagement = session.get(Engagement, engagement_id)
    if not engagement:
        return {"error": "Engagement not found"}

    engagement.agreed_price_credits = price_credits
    session.add(engagement)

    price_msg = f"[Price agreed] {price_credits} credits for: {engagement.title}"
    _post_system_message(session, engagement.source_conversation_id, price_msg)
    _post_system_message(session, engagement.target_conversation_id, price_msg)

    session.flush()

    return {
        "engagement_id": engagement.id,
        "agreed_price_credits": price_credits,
    }


def create_engagement_job(
    session: Session,
    agent_id: str,
    team_name: str,
    title: str,
    scope: str = "",
    engagement_id: str | None = None,
) -> dict:
    """Create a Job + Conversation in a target team and trigger auto-responses."""
    agent = session.get(Agent, agent_id)
    if not agent:
        return {"error": "Agent not found"}

    agent_wg = session.get(Workgroup, agent.workgroup_id)
    if not agent_wg or not agent_wg.organization_id:
        return {"error": "Agent's workgroup has no organization"}

    # Find the target workgroup by name within the same org
    target_wg = session.exec(
        select(Workgroup).where(
            Workgroup.organization_id == agent_wg.organization_id,
            Workgroup.name == team_name,
        )
    ).first()
    if not target_wg:
        return {"error": f"Team '{team_name}' not found in organization"}

    # Validate engagement if provided
    engagement = None
    if engagement_id:
        engagement = session.get(Engagement, engagement_id)
        if not engagement:
            return {"error": "Engagement not found"}

    # Create the job conversation
    conversation = Conversation(
        workgroup_id=target_wg.id,
        created_by_user_id=agent_wg.owner_id,
        kind="job",
        topic=title,
        name=title,
        description=scope,
    )
    session.add(conversation)
    session.flush()

    # Create the Job record
    job = Job(
        title=title,
        scope=scope,
        workgroup_id=target_wg.id,
        conversation_id=conversation.id,
        engagement_id=engagement_id,
        created_by_agent_id=agent_id,
    )
    session.add(job)

    # Post the initial system message
    content = f"[Job created by Coordinator] {title}"
    if scope:
        content += f"\n\nScope: {scope}"
    if engagement:
        content += f"\nEngagement: {engagement.title} (ID: {engagement.id})"

    message = Message(
        conversation_id=conversation.id,
        sender_type="system",
        content=content,
        requires_response=True,
    )
    session.add(message)
    session.flush()

    post_activity(session, target_wg.id, "job_created",
                  f"Job dispatched: {title}", actor_agent_id=agent_id)

    session.commit()
    session.refresh(job)
    session.refresh(message)

    # Trigger auto-responses in background
    from teaparty_app.services.agent_runtime import _process_auto_responses_in_background
    _process_auto_responses_in_background(conversation.id, message.id)

    return {
        "job_id": job.id,
        "conversation_id": conversation.id,
        "title": title,
        "team": team_name,
    }


def list_team_jobs(
    session: Session,
    org_id: str,
    team_name: str,
    status_filter: str | None = None,
) -> dict:
    """List jobs in a workgroup within the org."""
    target_wg = session.exec(
        select(Workgroup).where(
            Workgroup.organization_id == org_id,
            Workgroup.name == team_name,
        )
    ).first()
    if not target_wg:
        return {"error": f"Team '{team_name}' not found"}

    query = select(Job).where(Job.workgroup_id == target_wg.id)
    if status_filter:
        query = query.where(Job.status == status_filter)
    query = query.order_by(Job.created_at.desc())

    jobs = session.exec(query).all()
    return {
        "team": team_name,
        "jobs": [
            {
                "id": j.id,
                "title": j.title,
                "status": j.status,
                "engagement_id": j.engagement_id,
                "created_at": j.created_at.isoformat() if j.created_at else None,
            }
            for j in jobs
        ],
    }


def read_job_status(session: Session, job_id: str, message_limit: int = 10) -> dict:
    """Return job details + last N messages from its conversation."""
    job = session.get(Job, job_id)
    if not job:
        return {"error": "Job not found"}

    result: dict = {
        "id": job.id,
        "title": job.title,
        "scope": job.scope,
        "status": job.status,
        "engagement_id": job.engagement_id,
        "deliverables": job.deliverables,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "completed_at": job.completed_at.isoformat() if job.completed_at else None,
    }

    if job.conversation_id:
        messages = session.exec(
            select(Message)
            .where(Message.conversation_id == job.conversation_id)
            .order_by(Message.created_at.desc())
            .limit(message_limit)
        ).all()
        result["messages"] = [
            {
                "sender_type": m.sender_type,
                "content": m.content[:500],
                "created_at": m.created_at.isoformat() if m.created_at else None,
            }
            for m in reversed(messages)
        ]

    return result


def post_to_job(
    session: Session,
    agent_id: str,
    job_id: str,
    message_content: str,
) -> dict:
    """Post a message to a job's conversation and trigger auto-responses."""
    agent = session.get(Agent, agent_id)
    if not agent:
        return {"error": "Agent not found"}

    job = session.get(Job, job_id)
    if not job:
        return {"error": "Job not found"}

    if not job.conversation_id:
        return {"error": "Job has no conversation"}

    message = Message(
        conversation_id=job.conversation_id,
        sender_type="system",
        sender_agent_id=agent_id,
        content=f"[Coordinator] {message_content}",
        requires_response=True,
    )
    session.add(message)
    session.commit()
    session.refresh(message)

    # Trigger auto-responses
    from teaparty_app.services.agent_runtime import _process_auto_responses_in_background
    _process_auto_responses_in_background(job.conversation_id, message.id)

    return {
        "job_id": job.id,
        "message_id": message.id,
        "posted": True,
    }


def complete_engagement_by_agent(
    session: Session,
    agent_id: str,
    engagement_id: str,
    summary: str = "",
) -> dict:
    """Transition an engagement to completed."""
    agent = session.get(Agent, agent_id)
    if not agent:
        return {"error": "Agent not found"}

    engagement = session.get(Engagement, engagement_id)
    if not engagement:
        return {"error": "Engagement not found"}

    if engagement.status != "in_progress":
        return {"error": f"Cannot complete engagement in status '{engagement.status}'"}

    engagement.status = "completed"
    engagement.completed_at = utc_now()
    session.add(engagement)

    summary_text = summary.strip() if summary else "Engagement marked as completed."

    _post_system_message(session, engagement.source_conversation_id,
                         f"[Engagement completed] {summary_text}")
    _post_system_message(session, engagement.target_conversation_id,
                         f"[Engagement completed] {summary_text}")

    # Update engagement files
    source_wg = session.get(Workgroup, engagement.source_workgroup_id)
    target_wg = session.get(Workgroup, engagement.target_workgroup_id)
    if source_wg and target_wg:
        from teaparty_app.services.engagement_files import update_engagement_files
        update_engagement_files(session, engagement, source_wg, target_wg,
                                "Engagement completed", summary_text)

    session.flush()

    return {
        "engagement_id": engagement.id,
        "status": "completed",
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _post_system_message(session: Session, conversation_id: str | None, content: str) -> Message | None:
    if not conversation_id:
        return None
    msg = Message(
        conversation_id=conversation_id,
        sender_type="system",
        content=content,
        requires_response=False,
    )
    session.add(msg)
    return msg
