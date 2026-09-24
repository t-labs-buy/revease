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
    # OpenRouter *management* key (not a regular API key): lets the admin Usage
    # page read total AI spend for a date range from the analytics API.
    openrouter_management_key: str = ""
    # Name of the OpenRouter API key whose spend to report (as shown on
    # openrouter.ai/settings/keys). Empty = every key in the workspace.
    openrouter_cost_key: str = ""

    # --- Media storage ---
    # local = files under media_dir (single host). s3 = any S3-compatible object
    # store (MinIO on the host, or AWS S3): API and workers no longer need to
    # share a disk, so workers can run on other machines.
    storage_backend: str = "local"  # local | s3
    s3_endpoint_url: str = ""  # internal endpoint, e.g. http://minio:9000 (empty = AWS)
    # What browsers use instead of s3_endpoint_url in presigned URLs. Origin-
    # relative ("/s3") when an nginx edge proxies to MinIO with `Host: minio:9000`
    # (SigV4 signs host + path, so the proxy must reproduce them exactly).
    s3_public_url: str = ""
    s3_bucket: str = "revease-media"
    s3_region: str = "us-east-1"
    s3_access_key: str = ""
    s3_secret_key: str = ""
    # redirect = /media/{key} answers 307 to a presigned URL (bytes never pass
    # through the API). proxy = the API streams the object (when browsers
    # cannot reach the store at all).
    s3_serve_mode: str = "redirect"
    s3_presign_ttl_s: int = 6 * 3600
    # Worker/API local copies of objects (source videos, frames) for ffmpeg.
    media_cache_dir: Path = REPO_ROOT / "data" / "cache"
    media_cache_max_gb: float = 20.0
    # Direct multipart uploads: part size (S3 minimum is 5 MB except the last).
    upload_part_mb: int = 16

    # --- Retention (hourly sweep; 0 disables a rule) ---
    retention_enabled: bool = True
    retention_original_days: int = 7  # the browser's WebM once source.mp4 exists
    retention_audio_days: int = 2  # 16 kHz wav used only for transcription
    retention_old_renders_days: int = 7  # renders superseded by a newer one
    retention_tts_cache_days: int = 30  # regenerable voice clips
    retention_stale_uploads_hours: int = 24  # abandoned multipart uploads
    retention_interval_s: int = 3600

    # --- Heavy media processing ---
    # Redis redelivers an unacknowledged task after this many seconds. It MUST
    # exceed the longest task (a long recording's normalize + whisper + render):
    # at Celery's 1h default a 70-minute normalize was handed to a second worker
    # slot while the first was still running, and both wrote the same file.
    celery_visibility_timeout_s: int = 12 * 3600
    # A running stage whose heartbeat is older than this is presumed dead, so a
    # redelivered or re-requested run may take over.
    pipeline_stale_after_s: int = 180
    # ffmpeg threads per job — without a cap one encode takes every core and
    # starves the API, the other worker slot and everything else on the host.
    media_threads: int = 4
    # Browser recordings carry no real frame rate (WebM reports 1000/1); force
    # a constant rate so the encode is bounded. 30 fps is plenty for screen capture.
    media_normalize_fps: int = 30
    media_normalize_preset: str = "veryfast"
    media_normalize_timeout_s: int = 6 * 3600

    # --- Documentation (AI-written guide + per-step snapshots) ---
    # Snapshots are grabbed this long after a click so the pressed/hover state is
    # visible and the MediaRecorder start-up skew (~100-300ms) is absorbed.
    doc_snapshot_click_offset_ms: int = 150
    doc_snapshot_max_width: int = 1600
    doc_llm_timeout_s: int = 180

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

    # Comma-separated domains permitted for account registration (e.g. "tarento.com").
    # Empty string disables domain restriction.
    auth_allowed_email_domain: str = ""

    def admin_email_set(self) -> set[str]:
        return {e.strip().lower() for e in self.admin_emails.split(",") if e.strip()}

    def allowed_registration_domains(self) -> list[str]:
        return [
            d.strip().lower().lstrip("@")
            for d in self.auth_allowed_email_domain.split(",")
            if d.strip()
        ]

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
