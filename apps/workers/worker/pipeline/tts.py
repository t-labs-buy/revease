"""Minimal voice: one TTSProvider behind a thin adapter (master §Phase-5 trimmed).

Per-step synthesis returns {audio, duration_ms} and is cached by
(text_hash, voice_id, speed, provider) — identical text+voice never re-synthesizes,
which is what keeps regenerate cheap. Default provider is OpenAI TTS; when no key is
configured we emit a SILENT clip of the correct estimated duration (the plan's
sanctioned stub) so the whole render pipeline runs offline.

Per-step (never whole-script) synthesis is what keeps Phase-4 timeline drift-free.
"""

from __future__ import annotations

import hashlib
import logging
import subprocess
import sys
import wave
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import httpx

from app.config import get_settings

log = logging.getLogger("refract.pipeline.tts")

_WORDS_PER_SEC = 2.6  # speaking rate for the silent-clip duration estimate


@dataclass
class TTSResult:
    storage_key: str
    duration_ms: int
    provider: str
    cached: bool = False


def _probe_duration_ms(path: Path) -> int:
    proc = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(path)],
        capture_output=True, text=True,
    )
    try:
        return int(round(float(proc.stdout.strip()) * 1000))
    except (ValueError, AttributeError):
        return 0


def _estimate_ms(text: str, speed: float) -> int:
    words = max(1, len(text.split()))
    seconds = words / (_WORDS_PER_SEC * max(0.5, speed))
    return max(300, int(seconds * 1000))  # floor so a step is never truly zero


def _silent_wav(out: Path, duration_ms: int) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono",
         "-t", f"{max(1, duration_ms) / 1000:.3f}", "-c:a", "pcm_s16le", str(out)],
        capture_output=True, check=True,
    )


def _piper_models_dir() -> Path:
    d = get_settings().data_dir / "piper"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _ensure_piper_model(voice: str) -> Path:
    """Return the local .onnx path for a Piper voice, downloading it once if needed."""
    models = _piper_models_dir()
    onnx = models / f"{voice}.onnx"
    if not onnx.exists():
        log.info("downloading Piper voice %s ...", voice)
        subprocess.run(
            [sys.executable, "-m", "piper.download_voices", voice, "--data-dir", str(models)],
            capture_output=True, check=True,
        )
    return onnx


@lru_cache(maxsize=4)
def _load_piper(model_path: str):
    from piper import PiperVoice

    return PiperVoice.load(model_path)


def _is_piper_voice(voice_id: str) -> bool:
    import re

    return bool(re.match(r"^[a-z]{2}_[A-Z]{2}-", voice_id or ""))


def _is_kokoro_voice(voice_id: str) -> bool:
    import re

    return bool(re.match(r"^[abhijpz][fm]_", voice_id or ""))  # af_/am_/bf_/bm_/...


_KOKORO = None


def _kokoro():
    global _KOKORO
    if _KOKORO is None:
        from kokoro_onnx import Kokoro

        d = get_settings().data_dir / "kokoro"
        model = d / "kokoro-v1.0.onnx"
        voices = d / "voices-v1.0.bin"
        if not (model.exists() and voices.exists()):
            raise FileNotFoundError("kokoro model not downloaded")
        _KOKORO = Kokoro(str(model), str(voices))
    return _KOKORO


def _kokoro_tts(text: str, speed: float, out: Path, voice_name: str) -> None:
    import soundfile as sf

    samples, sr = _kokoro().create(text, voice=voice_name, speed=float(speed), lang="en-us")
    out.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(out), samples, sr)


def _piper_tts(text: str, speed: float, out: Path, voice_name: str) -> None:
    from piper import SynthesisConfig

    model_path = _ensure_piper_model(voice_name)
    voice = _load_piper(str(model_path))
    out.parent.mkdir(parents=True, exist_ok=True)
    # length_scale is inverse speed: >1 slower, <1 faster.
    syn = SynthesisConfig(length_scale=1.0 / max(0.5, speed))
    with wave.open(str(out), "wb") as wf:
        voice.synthesize_wav(text, wf, syn_config=syn)


def _openai_tts(text: str, voice: str, speed: float, out: Path) -> None:
    api_key = get_settings().openai_api_key
    model = "tts-1"
    out.parent.mkdir(parents=True, exist_ok=True)
    resp = httpx.post(
        "https://api.openai.com/v1/audio/speech",
        headers={"Authorization": f"Bearer {api_key}"},
        json={"model": model, "voice": voice, "input": text, "response_format": "wav", "speed": speed},
        timeout=120,
    )
    resp.raise_for_status()
    out.write_bytes(resp.content)


def synth_step(
    text: str,
    *,
    media_root: Path,
    voice_id: str = "alloy",
    speed: float = 1.0,
    provider: str | None = None,
) -> TTSResult:
    """Synthesize one step's narration. Cached under <media_root>/tts/<hash>.wav.
    Provider order: piper (keyless local) -> openai (needs key) -> silent."""
    settings = get_settings()
    provider = provider or settings.tts_provider
    if provider == "silent":  # explicit override (tests / no-voice)
        effective, voice_label = "silent", voice_id
    elif _is_piper_voice(voice_id):
        effective, voice_label = "piper", voice_id
    elif _is_kokoro_voice(voice_id):
        effective, voice_label = "kokoro", voice_id
    elif provider == "openai" and settings.openai_api_key:
        effective, voice_label = "openai", voice_id
    elif provider == "piper":
        effective, voice_label = "piper", settings.piper_voice
    else:  # kokoro (default)
        effective, voice_label = "kokoro", settings.kokoro_voice

    text = (text or "").strip() or "(no narration)"

    def _key(prov: str, label: str) -> tuple[str, Path]:
        digest = hashlib.sha1(f"{prov}|{label}|{speed}|{text}".encode()).hexdigest()[:16]
        sk = f"tts/{digest}.wav"
        return sk, media_root / sk

    storage_key, path = _key(effective, voice_label)
    if path.exists():
        return TTSResult(storage_key, _probe_duration_ms(path), effective, cached=True)

    try:
        if effective == "kokoro":
            _kokoro_tts(text, speed, path, voice_label)
        elif effective == "piper":
            _piper_tts(text, speed, path, voice_label)
        elif effective == "openai":
            _openai_tts(text, voice_id, speed, path)
        else:
            _silent_wav(path, _estimate_ms(text, speed))
    except Exception as e:
        log.warning("%s TTS failed (%s); falling back.", effective, e)
        # kokoro/openai failure -> Piper (still keyless); then silent
        try:
            pv = settings.piper_voice
            effective, voice_label = "piper", pv
            storage_key, path = _key("piper", pv)
            if not path.exists():
                _piper_tts(text, speed, path, pv)
        except Exception as e2:
            log.warning("piper fallback failed (%s); using silent clip.", e2)
            effective = "silent"
            storage_key, path = _key("silent", voice_id)
            if not path.exists():
                _silent_wav(path, _estimate_ms(text, speed))

    return TTSResult(storage_key, _probe_duration_ms(path), effective, cached=False)
