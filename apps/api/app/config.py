"""Runtime configuration. All secrets/paths via env; see .env.example."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Repo root = apps/api/app/config.py -> up 3.
REPO_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    # Load the repo-root .env regardless of the process CWD (api and worker run
    # from apps/*), so a single .env at the root configures everything.
    model_config = SettingsConfigDict(
        env_prefix="REFRACT_", env_file=str(REPO_ROOT / ".env"), extra="ignore"
    )

    # Local persistence (SQLite) + media dir live under data/ by default.
    data_dir: Path = REPO_ROOT / "data"
    database_url: str = ""  # derived from data_dir if empty
    media_dir: Path = REPO_ROOT / "data" / "media"

    # Background jobs.
    redis_url: str = "redis://localhost:6379/0"

    # --- LLM (step labeling / narration). Prefer a direct Anthropic key; fall
    #     back to OpenRouter; else a deterministic offline labeler. ---
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-opus-4-8"
    openrouter_api_key: str = ""
    openrouter_model: str = "anthropic/claude-opus-4.1"

    # --- TTS voice (keyless local). `kokoro` = high-quality neural (default),
    #     `piper` = lighter fallback, `openai` needs a key; else silent clips. ---
    tts_provider: str = "kokoro"
    openai_api_key: str = ""
    tts_voice_id: str = "alloy"
    piper_voice: str = "en_US-lessac-medium"
    kokoro_voice: str = "af_sarah"

    # --- Whisper transcription ---
    # "small" is markedly more accurate than "base" (downloads ~460MB once). For
    # even higher accuracy set REFRACT_WHISPER_MODEL=medium, or small.en/medium.en
    # for English-only content; set REFRACT_WHISPER_DEVICE=cuda for GPU speed.
    whisper_model: str = "small"
    whisper_device: str = "cpu"
    whisper_compute: str = "int8"
    disable_whisper: bool = False
    # Comma-separated product/feature names or jargon Whisper should recognize
    # verbatim instead of guessing at (e.g. "RevEase, Auto Record, webhook").
    whisper_vocab: str = ""

    # --- Auto Record (AI-driven tab recording) ---
    # Hard cap on agent decisions per run (server force-ends with `done` when hit).
    autorecord_max_steps: int = 60
    # How many recent screenshots to keep in the agent's context window (older
    # observations keep their text summary but drop the image to bound token cost).
    autorecord_screenshot_window: int = 3

    cors_origins: str = "http://localhost:3000"

    # --- Auth (per-user spaces) ---
    # Signing key for access tokens. Leave empty for local dev: a key is generated
    # once and persisted under data_dir so sessions survive a server restart. In
    # any shared/deployed environment set REFRACT_AUTH_SECRET_KEY explicitly.
    auth_secret_key: str = ""
    auth_token_ttl_hours: int = 24 * 14  # how long a login lasts
    auth_min_password_length: int = 8
    # Comma-separated emails promoted to the admin role on register/login — the
    # bootstrap admins. Further admins can then be promoted from the Admin UI.
    admin_emails: str = ""

    def admin_email_set(self) -> set[str]:
        return {e.strip().lower() for e in self.admin_emails.split(",") if e.strip()}

    # --- Usage reporting ---
    # Static key an external app sends as `X-Report-Key` to pull the usage
    # report (GET /admin/usage/report). Empty disables the endpoint.
    usage_report_key: str = ""

    def resolved_database_url(self) -> str:
        if self.database_url:
            return self.database_url
        return f"sqlite:///{self.data_dir / 'refract.sqlite3'}"

    def resolved_auth_secret(self) -> str:
        """The token signing key: the configured one, else a generated key cached
        on disk (so restarts don't silently log everyone out during local dev)."""
        if self.auth_secret_key:
            return self.auth_secret_key
        key_file = self.data_dir / "auth_secret.key"
        if key_file.exists():
            cached = key_file.read_text().strip()
            if cached:
                return cached
        import secrets

        generated = secrets.token_urlsafe(48)
        key_file.write_text(generated)
        key_file.chmod(0o600)
        return generated


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.media_dir.mkdir(parents=True, exist_ok=True)
    return settings
