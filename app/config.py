from pathlib import Path
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./data/certificates.db"
    wechat_work_webhook_url: str = ""
    email_smtp_host: str = ""
    email_smtp_port: int = Field(default=465, ge=1, le=65535)
    email_smtp_username: str = ""
    email_smtp_password: str = ""
    email_smtp_from: str = ""
    email_smtp_use_ssl: bool = True
    email_smtp_starttls: bool = False
    check_hour: int = 9
    wechat_due_reminder_hour: int = Field(default=8, ge=0, le=23)
    default_remind_days: int = 30
    cors_origins: str = ""
    session_ttl_hours: int = Field(default=12, ge=1, le=168)
    session_cookie_secure: bool = True
    allowed_hosts: str = "localhost,127.0.0.1"
    scheduler_enabled: bool = True

    @property
    def allowed_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def trusted_hosts(self) -> list[str]:
        return [host.strip() for host in self.allowed_hosts.split(",") if host.strip()]


settings = Settings()
Path("data").mkdir(exist_ok=True)

