"""REST API for system-wide settings (admin-only)."""

from fastapi import APIRouter, Depends

from teaparty_app.config import settings
from teaparty_app.deps import require_system_admin
from teaparty_app.models import User
from teaparty_app.schemas import SystemSettingsRead, SystemSettingsUpdate

router = APIRouter(prefix="/api", tags=["system"])

EDITABLE_FIELDS = [
    "llm_default_model",
    "llm_cheap_model",
    "admin_agent_model",
    "intent_probe_model",
    "anthropic_api_key",
    "ollama_base_url",
    "agent_chain_max",
    "agent_sdk_max_turns",
    "app_name",
    "workspace_root",
    "admin_agent_use_sdk",
]


def _read_settings() -> SystemSettingsRead:
    return SystemSettingsRead(
        llm_default_model=settings.llm_default_model,
        llm_cheap_model=settings.llm_cheap_model,
        admin_agent_model=settings.admin_agent_model,
        intent_probe_model=settings.intent_probe_model,
        anthropic_api_key_set=bool(settings.anthropic_api_key),
        ollama_base_url=settings.ollama_base_url,
        agent_chain_max=settings.agent_chain_max,
        agent_sdk_max_turns=settings.agent_sdk_max_turns,
        app_name=settings.app_name,
        workspace_root=settings.workspace_root,
        admin_agent_use_sdk=settings.admin_agent_use_sdk,
    )


@router.get("/system/settings", response_model=SystemSettingsRead)
def get_system_settings(user: User = Depends(require_system_admin)):
    return _read_settings()


@router.patch("/system/settings", response_model=SystemSettingsRead)
def update_system_settings(
    body: SystemSettingsUpdate,
    user: User = Depends(require_system_admin),
):
    updates = body.model_dump(exclude_unset=True)
    for key, value in updates.items():
        if key not in EDITABLE_FIELDS:
            continue
        # Empty string for api key means clear it
        if key == "anthropic_api_key" and value == "":
            settings.anthropic_api_key = ""
            continue
        setattr(settings, key, value)
    return _read_settings()
