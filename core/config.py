"""
All runtime settings, read from the environment (or a .env file).

Secrets are SecretStr so they never end up in logs or reprs. AWS credentials
are deliberately not settings: boto3 reads them from its standard chain
(an IAM role on EC2, or AWS_* variables locally), so they never pass
through this code.
"""
from datetime import date
from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", env_file_encoding="utf-8", extra="ignore")

    # --- environment ----------------------------------------------------------
    environment: str = Field("development", description="development | production")
    log_level: str = "INFO"
    host: str = "127.0.0.1"
    port: int = 7860
    # Comma-separated host names the server answers to; "*" only in development.
    allowed_hosts: str = "localhost,127.0.0.1"
    # Behind Caddy/nginx, trust the right-most X-Forwarded-For entry for the client IP.
    trust_proxy: bool = False

    # --- access ---------------------------------------------------------------
    # When set, every new call needs this code. Share it only with testers.
    access_code: SecretStr | None = None

    # --- LLM: Amazon Nova on Bedrock -----------------------------------------
    aws_region: str = "ap-south-1"
    nova_model_id: str = "global.amazon.nova-2-lite-v1:0"
    llm_temperature: float = 0.2
    llm_max_tokens: int = 350
    llm_timeout_seconds: float = 20.0

    # --- speech: Sarvam -------------------------------------------------------
    sarvam_api_key: SecretStr | None = None
    sarvam_stt_model: str = "saaras:v4"
    sarvam_tts_model: str = "bulbul:v3"
    sarvam_tts_voice: str = "priya"

    # --- WebRTC ---------------------------------------------------------------
    stun_url: str = "stun:stun.l.google.com:19302"
    turn_url: str | None = None
    turn_username: str | None = None
    turn_password: SecretStr | None = None

    # --- limits (cost and abuse protection) -----------------------------------
    max_concurrent_voice_calls: int = 3       # also keeps us inside Sarvam's concurrency limits
    max_open_sessions: int = 50
    max_sessions_per_ip: int = 3              # open at the same time
    calls_per_ip_per_hour: int = 12
    daily_call_budget: int = 150              # across everyone; resets at midnight UTC
    text_turns_per_minute: int = 20           # per call
    requests_per_minute_per_ip: int = 120
    access_code_attempts_per_15min: int = 8
    call_max_seconds: int = 600
    call_idle_seconds: int = 90
    session_ttl_seconds: int = 1800
    max_turns_per_call: int = 60
    max_text_chars: int = 500
    max_writes_per_call: int = 15             # tickets, notes, requests a call may create
    max_body_bytes: int = 64_000

    # --- data -----------------------------------------------------------------
    data_dir: Path = ROOT / "data" / "generated"
    var_dir: Path = ROOT / "var"              # audit log lives here
    # The demo data is consistent with this date ("next EMI", "last month"...).
    demo_today: date = date(2026, 10, 18)

    @field_validator("access_code", "sarvam_api_key", "turn_url", "turn_username", "turn_password", mode="before")
    @classmethod
    def _blank_is_unset(cls, v):
        return None if isinstance(v, str) and not v.strip() else v

    @field_validator("environment")
    @classmethod
    def _env(cls, v: str) -> str:
        if v not in ("development", "production"):
            raise ValueError("ENVIRONMENT must be development or production")
        return v

    @property
    def production(self) -> bool:
        return self.environment == "production"

    @property
    def hosts(self) -> list[str]:
        return [h.strip() for h in self.allowed_hosts.split(",") if h.strip()]

    @property
    def voice_available(self) -> bool:
        return self.sarvam_api_key is not None and bool(self.sarvam_api_key.get_secret_value())

    def check_production(self) -> list[str]:
        """Settings that are unsafe to run with in production."""
        problems = []
        if "*" in self.hosts:
            problems.append("ALLOWED_HOSTS must list real host names, not *")
        if self.access_code is None or len(self.access_code.get_secret_value()) < 8:
            problems.append("ACCESS_CODE must be set (8+ characters) so strangers cannot run up your API bills")
        return problems


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
