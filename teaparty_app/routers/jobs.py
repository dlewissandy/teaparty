from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session, select

from teaparty_app.db import get_session
from teaparty_app.deps import get_current_user
from teaparty_app.models import Engagement, Job, Membership, User, Workgroup
from teaparty_app.schemas import JobDetailRead, JobRead

router = APIRouter(prefix="/api", tags=["jobs"])


@router.get("/workgroups/{workgroup_id}/jobs", response_model=list[JobRead])
def list_jobs(
    workgroup_id: str,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> list[JobRead]:
    membership = session.exec(
        select(Membership).where(
            Membership.workgroup_id == workgroup_id,
            Membership.user_id == user.id,
        )
    ).first()
    if not membership:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not a workgroup member",
        )

    jobs = session.exec(
        select(Job)
        .where(Job.workgroup_id == workgroup_id)
        .order_by(Job.created_at.desc())
    ).all()
    return [JobRead.model_validate(j) for j in jobs]


@router.get("/jobs/{job_id}", response_model=JobDetailRead)
def get_job(
    job_id: str,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> JobDetailRead:
    job = session.get(Job, job_id)
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Job not found",
        )

    # Check membership in the job's workgroup
    membership = session.exec(
        select(Membership).where(
            Membership.workgroup_id == job.workgroup_id,
            Membership.user_id == user.id,
        )
    ).first()
    if not membership:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not a member of the job's workgroup",
        )

    workgroup = session.get(Workgroup, job.workgroup_id)
    engagement = session.get(Engagement, job.engagement_id) if job.engagement_id else None

    return JobDetailRead(
        **JobRead.model_validate(job).model_dump(),
        workgroup_name=workgroup.name if workgroup else "",
        engagement_title=engagement.title if engagement else "",
    )
