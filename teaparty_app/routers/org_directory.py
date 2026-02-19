"""REST API for the public organization directory listing."""

from fastapi import APIRouter, Depends
from sqlmodel import Session, select

from teaparty_app.db import get_session
from teaparty_app.models import Organization
from teaparty_app.schemas import OrgDirectoryEntry

router = APIRouter(prefix="/api", tags=["org-directory"])


@router.get("/org-directory", response_model=list[OrgDirectoryEntry])
def list_directory(
    session: Session = Depends(get_session),
) -> list[OrgDirectoryEntry]:
    orgs = session.exec(
        select(Organization).where(
            Organization.is_accepting_engagements == True  # noqa: E712
        )
    ).all()
    return [
        OrgDirectoryEntry(
            id=org.id,
            name=org.name,
            description=org.description,
            service_description=org.service_description,
            owner_id=org.owner_id,
        )
        for org in orgs
    ]
