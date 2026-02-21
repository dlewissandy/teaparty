"""Application settings loaded from environment variables and .env file."""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "TeaParty"
    database_url: str = "sqlite:///./teaparty.db"
    app_secret: str = "change-me"
    google_client_id: str = ""
    allow_dev_auth: bool = True
    session_expires_minutes: int = 24 * 60
    admin_agent_use_sdk: bool = True
    admin_agent_model: str = "sonnet"
    intent_probe_model: str = "haiku"
    agent_chain_max: int = 8
    agent_sdk_max_turns: int = 6
    anthropic_api_key: str = Field(default="", validation_alias="ANTHROPIC_API_KEY")
    llm_default_model: str = "ollama/mistral"
    llm_cheap_model: str = "ollama/mistral"
    ollama_base_url: str = "http://localhost:11434"
    workspace_root: str = ""

    model_config = SettingsConfigDict(
        env_prefix="TEAPARTY_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
