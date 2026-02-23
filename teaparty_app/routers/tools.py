"""REST API for listing available agent tools per workgroup."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from teaparty_app.db import get_session
from teaparty_app.deps import get_current_user
from teaparty_app.models import User
from teaparty_app.services.claude_tools import CLAUDE_TOOLS, CLAUDE_TOOLSETS
from teaparty_app.services.permissions import require_workgroup_membership

router = APIRouter(prefix="/api", tags=["tools"])


@router.get("/workgroups/{workgroup_id}/tools")
def list_available_tools(
    workgroup_id: str,
    session=Depends(get_session),
    user: User = Depends(get_current_user),
) -> list[dict]:
    require_workgroup_membership(session, workgroup_id, user.id)
    return list(CLAUDE_TOOLS)


@router.get("/workgroups/{workgroup_id}/toolsets")
def list_available_toolsets(
    workgroup_id: str,
    session=Depends(get_session),
    user: User = Depends(get_current_user),
) -> list[dict]:
    require_workgroup_membership(session, workgroup_id, user.id)
    return list(CLAUDE_TOOLSETS)
