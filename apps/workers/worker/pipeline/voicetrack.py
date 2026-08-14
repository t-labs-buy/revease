"""Build a narration-only audio track for the editor's live voice preview: synth
each step's script in the chosen voice (cached per line), place each clip on the
render's own OUTPUT clock (build_timeline — the same one the final render uses),
and concat into one wav + a sidecar pacing timeline. Lets the editor play the AI
voice over the video, retimed the same way the render retimes it, without a
full render."""

from __future__ import annotations

import json
import logging
import subprocess

from sqlalchemy import select

from app.db import SessionLocal
from app.editspec import voice_timeline_key, voice_track_key
from app.models import VideoProject
from app.storage import store
from worker.pipeline.render import DEFAULT_PACE, compute_step_audio
from worker.pipeline.timeline import StepInput, build_timeline

log = logging.getLogger("refract.pipeline.voicetrack")


def build_voice_track(project_id: str, voice_id: str, speed: float) -> dict:
    db = SessionLocal()
    try:
        vp = db.scalar(select(VideoProject).where(VideoProject.project_id == project_id))
        if vp is None:
            return {"error": "no video project"}
        spec = vp.edit_spec_json
        key = voice_track_key(project_id, voice_id, speed, spec)
        timeline_key = voice_timeline_key(project_id, voice_id, speed, spec)
        out = store.local_path(key)
        if out.exists():
            return {"key": key, "timeline_key": timeline_key, "cached": True}

        pace = min(1.5, max(1.0, float(spec.get("pace") or DEFAULT_PACE)))
        voice = {"voice_id": voice_id, "speed": speed}
        work = store.local_path(f"voicepreview_work/{project_id}")
        work.mkdir(parents=True, exist_ok=True)

        segs = [s for s in spec.get("segments", []) if not s.get("skipped")]
        # Mirror the render's trim filter exactly (worker.pipeline.render.run_render)
        # so a trimmed preview's timeline matches what trim actually keeps.
        trim = spec.get("trim") or {}
        if trim.get("enabled") and trim.get("end_ms", 0) > trim.get("start_ms", 0):
            t0, t1 = trim["start_ms"], trim["end_ms"]
            kept = [s for s in segs if t0 <= s.get("source_start_ms", 0) <= t1]
            if kept:
                segs = kept
        if not segs:
            return {"error": "no segments"}

        # Every kept scene contributes a clip (silence included) so the preview's
        # output clock has the same total length and per-scene pacing as the
        # render's — skipping silent scenes here would make the two drift apart.
        step_inputs: list[StepInput] = []
        clip_by_id: dict[str, str] = {}
        for s in segs:
            audio = compute_step_audio(
                s, work=work, src_video=None, pace=pace, voice=voice, use_original=False,
            )
            clip_by_id[s["step_id"]] = audio.path
            step_inputs.append(
                StepInput(
                    step_id=s["step_id"],
                    tts_duration_ms=audio.duration_ms,
                    source_start_ms=s.get("source_start_ms", 0),
                    source_end_ms=s.get("source_end_ms", 0),
                )
            )
        timeline = build_timeline(step_inputs)

        out.parent.mkdir(parents=True, exist_ok=True)
        # Place each clip at its OUTPUT-clock start (adelay) and sum them (amix),
        # matching build_timeline exactly — NOT source_start_ms, which is only
        # meaningful for un-retimed (1x) playback.
        inputs: list[str] = []
        filters: list[str] = []
        for i, seg_tl in enumerate(timeline.segments):
            inputs += ["-i", clip_by_id[seg_tl.step_id]]
            filters.append(f"[{i}:a]aformat=channel_layouts=mono,adelay={seg_tl.out_start_ms}[a{i}]")
        labels = "".join(f"[a{i}]" for i in range(len(timeline.segments)))
        fc = (
            ";".join(filters)
            + f";{labels}amix=inputs={len(timeline.segments)}:normalize=0:dropout_transition=0[a]"
        )
        cmd = ["ffmpeg", "-y", *inputs, "-filter_complex", fc, "-map", "[a]",
               "-ar", "24000", "-ac", "1", str(out)]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            log.warning("voice-track build failed: %s", proc.stderr[-400:])
            return {"error": "build failed"}

        tpath = store.local_path(timeline_key)
        tpath.parent.mkdir(parents=True, exist_ok=True)
        tpath.write_text(json.dumps(timeline.as_dict()))
        return {"key": key, "timeline_key": timeline_key}
    finally:
        db.close()
