"""Isolate tests onto a temp SQLite DB + media dir BEFORE any app import."""

import os
import tempfile

_tmp = tempfile.mkdtemp(prefix="refract-worker-test-")
os.environ["REFRACT_DATA_DIR"] = _tmp
os.environ["REFRACT_MEDIA_DIR"] = os.path.join(_tmp, "media")
os.environ["REFRACT_DATABASE_URL"] = f"sqlite:///{_tmp}/test.sqlite3"
# Ensure deterministic (no-network) LLM labeling, transcription, and voice in tests.
os.environ.pop("REFRACT_OPENROUTER_API_KEY", None)
os.environ.pop("REFRACT_ANTHROPIC_API_KEY", None)
os.environ["REFRACT_DISABLE_WHISPER"] = "1"
os.environ["REFRACT_TTS_PROVIDER"] = "silent"  # no real Piper synth in tests

from app.db import init_db  # noqa: E402

init_db()
