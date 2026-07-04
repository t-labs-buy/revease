"""Build a narration-only audio track for the editor's live voice preview: synth
each step's script in the chosen voice (cached per line) and concat into one wav.
Lets the editor play the AI voice over the video without a full render."""

from __future__ import annotations

import logging
import subprocess

from sqlalchemy import select

from app.db import SessionLocal
from app.editspec import effective_script, voice_track_key
from app.models import VideoProject
from app.storage import store
from worker.pipeline.tts import synth_step

log = logging.getLogger("refract.pipeline.voicetrack")


def build_voice_track(project_id: str, voice_id: str, speed: float) -> dict:
    db = SessionLocal()
    try:
        vp = db.scalar(select(VideoProject).where(VideoProject.project_id == project_id))
        if vp is None:
            return {"error": "no video project"}
        spec = vp.edit_spec_json
        key = voice_track_key(project_id, voice_id, speed, spec)
        out = store.local_path(key)
        if out.exists():
            return {"key": key, "cached": True}

        # Synth each non-empty line, remembering where it sits on the timeline.
        placed: list[tuple[int, object]] = []
        for s in spec.get("segments", []):
            script = effective_script(s.get("words", []), s.get("removed", []))
            if not script.strip():
                continue
            r = synth_step(script, media_root=store.root, voice_id=voice_id, speed=speed)
            placed.append((int(s.get("source_start_ms", 0) or 0), store.local_path(r.storage_key)))
        if not placed:
            return {"error": "no segments"}

        out.parent.mkdir(parents=True, exist_ok=True)
        # Place each clip at its source_start_ms (adelay) and sum them (amix), so the
        # narration lines up with the video timeline — silence fills the gaps —
        # instead of bunching every line at 0:00.
        inputs: list[str] = []
        filters: list[str] = []
        for i, (start_ms, clip) in enumerate(placed):
            inputs += ["-i", str(clip)]
            filters.append(f"[{i}:a]aformat=channel_layouts=mono,adelay={start_ms}[a{i}]")
        labels = "".join(f"[a{i}]" for i in range(len(placed)))
        fc = (
            ";".join(filters)
            + f";{labels}amix=inputs={len(placed)}:normalize=0:dropout_transition=0[a]"
        )
        cmd = ["ffmpeg", "-y", *inputs, "-filter_complex", fc, "-map", "[a]",
               "-ar", "24000", "-ac", "1", str(out)]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            log.warning("voice-track build failed: %s", proc.stderr[-400:])
            return {"error": "build failed"}
        return {"key": key}
    finally:
        db.close()
