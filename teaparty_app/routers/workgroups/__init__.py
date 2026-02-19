from fastapi import APIRouter

from .core import router as _core_router
from .agents import router as _agents_router
from .members import router as _members_router

# Merge sub-routers into a single router for backwards-compatible mounting.
router = APIRouter()
router.include_router(_core_router)
router.include_router(_agents_router)
router.include_router(_members_router)

# Re-export symbols used by external modules (admin_workspace/global_tools, tests).
from .core import (  # noqa: E402, F401
    _reconcile_administration_template_files,
    _resolve_template_for_create,
    _resolve_workgroup_creation_agents,
    _resolve_workgroup_creation_files,
    _sync_workgroup_storage_for_user,
    create_workgroup_with_template,
)
from .agents import clone_agent, update_agent  # noqa: E402, F401
