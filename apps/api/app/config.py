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

    cors_origins: str = "http://localhost:3000"

    def resolved_database_url(self) -> str:
        if self.database_url:
            return self.database_url
        return f"sqlite:///{self.data_dir / 'refract.sqlite3'}"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.media_dir.mkdir(parents=True, exist_ok=True)
    return settings
