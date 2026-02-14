from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "TeaParty"
    database_url: str = "sqlite:///./teaparty.db"
    app_secret: str = "change-me"
    google_client_id: str = ""
    allow_dev_auth: bool = True
    session_expires_minutes: int = 24 * 60
    follow_up_scan_limit: int = 100
    admin_agent_use_sdk: bool = True
    admin_agent_model: str = "claude-sonnet-4-5"
    agent_chain_max: int = 8
    anthropic_api_key: str = Field(default="", validation_alias="ANTHROPIC_API_KEY")

    model_config = SettingsConfigDict(
        env_prefix="TEAPARTY_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
