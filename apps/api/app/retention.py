"""Retention sweep: delete what can be regenerated or has been superseded, so
storage grows with the number of projects rather than with every re-render.

Every rule is conservative on purpose — it only touches files that are either
rebuilt on demand or replaced by something better:

- **originals**: the browser's raw WebM/MOV once the pipeline has produced
  `source.mp4` (the asset was repointed, so nothing references the original).
- **audio**: the 16 kHz transcription WAV; a reprocess demuxes it again.
- **old renders**: finished renders older than the project's newest one (the
  newest is what the editor and share links serve), plus idle render-cache clips.
- **TTS cache**: synthesized voice clips; the renderer re-synthesizes on demand.
- **stale uploads**: multipart uploads abandoned mid-way (the parts cost space).
- **media cache**: on S3, local copies are evicted LRU down to the size cap.

A rule set to 0 days/hours is disabled. Runs hourly on the light worker via
Celery beat, or by hand: `python -m app.retention --dry-run`.
"""

from __future__ import annotations

import argparse
import logging
import re
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.config import get_settings
from app.db import SessionLocal
from app.models import CaptureSession, MediaAsset, RenderJob, Upload
from app.storage import prune_cache, store

log = logging.getLogger("refract.retention")

_ORIGINAL = re.compile(r"^sessions/([^/]+)/raw_video_[^/]+\.(webm|mov|mkv|mp4)$")
_AUDIO = re.compile(r"^sessions/([^/]+)/audio\.wav$")
_RENDER_FINAL = re.compile(r"^renders/([^/]+)/final_[^/]+\.mp4$")


@dataclass
class Report:
    dry_run: bool
    deleted: dict[str, int] = field(default_factory=dict)
    freed_bytes: dict[str, int] = field(default_factory=dict)

    def add(self, rule: str, size: int) -> None:
        self.deleted[rule] = self.deleted.get(rule, 0) + 1
        self.freed_bytes[rule] = self.freed_bytes.get(rule, 0) + size

    def as_dict(self) -> dict:
        return {"dry_run": self.dry_run, "deleted": self.deleted,
                "freed_mb": {k: round(v / 1048576, 1) for k, v in self.freed_bytes.items()},
                "total_freed_mb": round(sum(self.freed_bytes.values()) / 1048576, 1)}


def _utc(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def run_retention(*, dry_run: bool = False, now: datetime | None = None) -> dict:
    s = get_settings()
    now = now or datetime.now(timezone.utc)
    rep = Report(dry_run=dry_run)
    db = SessionLocal()
    try:
        referenced = set(db.scalars(select(MediaAsset.storage_key)))
        ready_sessions = set(db.scalars(select(CaptureSession.id).where(CaptureSession.status == "ready")))

        def older(obj_modified: datetime, days: float) -> bool:
            return days > 0 and now - _utc(obj_modified) > timedelta(days=days)

        def drop(rule: str, key: str, size: int) -> None:
            rep.add(rule, size)
            if not dry_run:
                store.delete(key)

        for obj in store.list("sessions/"):
            m = _ORIGINAL.match(obj.key)
            if m and obj.key not in referenced and m.group(1) in ready_sessions \
                    and older(obj.modified, s.retention_original_days):
                drop("originals", obj.key, obj.size)
                continue
            m = _AUDIO.match(obj.key)
            if m and m.group(1) in ready_sessions and older(obj.modified, s.retention_audio_days):
                drop("audio", obj.key, obj.size)
                if not dry_run:
                    for a in db.scalars(select(MediaAsset).where(MediaAsset.storage_key == obj.key)):
                        db.delete(a)

        # ---- renders: keep each project's newest finished render ----
        if s.retention_old_renders_days > 0:
            newest: dict[str, str] = {}
            for job in db.scalars(select(RenderJob).where(RenderJob.status == "done").order_by(RenderJob.created_at)):
                if job.output_key:
                    newest[job.video_project_id] = job.output_key
            keep = set(newest.values())
            stale_keys: set[str] = set()
            for obj in store.list("renders/"):
                # superseded finals and idle render-cache clips (both rebuildable)
                if obj.key not in keep and older(obj.modified, s.retention_old_renders_days):
                    drop("old_renders", obj.key, obj.size)
                    if _RENDER_FINAL.match(obj.key):
                        stale_keys.add(obj.key)
            if stale_keys and not dry_run:
                for job in db.scalars(select(RenderJob).where(RenderJob.output_key.in_(stale_keys))):
                    job.output_key = None  # the file is gone; the row stays as history

        # ---- TTS clip cache ----
        for obj in store.list("tts/"):
            if older(obj.modified, s.retention_tts_cache_days):
                drop("tts_cache", obj.key, obj.size)

        # ---- abandoned multipart uploads ----
        if s.retention_stale_uploads_hours > 0:
            cutoff = now - timedelta(hours=s.retention_stale_uploads_hours)
            known = set()
            for up in db.scalars(select(Upload).where(Upload.status == "uploading")):
                known.add(up.backend_upload_id)
                if _utc(up.updated_at) < cutoff:
                    rep.add("stale_uploads", up.size)
                    if not dry_run:
                        store.mp_abort(up.storage_key, up.backend_upload_id)
                        up.status = "aborted"
            if store.backend == "s3":
                for key, upload_id, initiated in store.list_multipart_uploads():
                    if upload_id not in known and _utc(initiated) < cutoff:
                        rep.add("stale_uploads", 0)
                        if not dry_run:
                            store.mp_abort(key, upload_id)
            else:
                parts_root = store.root / ".uploads"
                for d in parts_root.iterdir() if parts_root.exists() else []:
                    mtime = datetime.fromtimestamp(d.stat().st_mtime, timezone.utc)
                    if d.is_dir() and d.name not in known and mtime < cutoff:
                        size = sum(f.stat().st_size for f in d.glob("*") if f.is_file())
                        rep.add("stale_uploads", size)
                        if not dry_run:
                            shutil.rmtree(d, ignore_errors=True)

        if not dry_run:
            db.commit()
            freed = prune_cache()
            if freed:
                rep.freed_bytes["media_cache"] = freed
    finally:
        db.close()
    out = rep.as_dict()
    log.info("retention %s: %s", "dry run" if dry_run else "sweep", out)
    return out


def main() -> int:
    p = argparse.ArgumentParser(description="Delete regenerable/superseded media (see module docstring).")
    p.add_argument("--dry-run", action="store_true", help="report what would be deleted")
    a = p.parse_args()
    import json

    print(json.dumps(run_retention(dry_run=a.dry_run), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
