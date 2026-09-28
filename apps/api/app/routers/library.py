"""The user's media library — logos, images, video clips and music tracks for
the editor's Media tab, reusable across every project the user edits.

Uploads accept "any format": the browser sends the file as-is, and the
`refract.library.process` worker task normalizes it (PNG for stills, H.264 MP4
for clips, the original or M4A for audio) so the renderer only ever sees
formats it handles. Small files go up in one PUT to `/media/library/{id}/…`;
large ones use the same resumable multipart primitives as capture uploads
(`routers/uploads.py`), with the multipart state kept on the asset row itself.

Rows are owned by the user (not a project) and deleting one removes its whole
`library/{id}/` prefix. A project that still places a deleted asset renders
without it — the renderer skips missing media rather than failing the export.
"""

from __future__ import annotations

import math

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import CurrentUser
from app.db import get_session
from app.models import CaptureSession, LibraryAsset, MediaAsset, Project
from app.ownership import owned_row, owned_session, project_ids_for
from app.queue import enqueue_library_import, enqueue_library_process, enqueue_library_remove_bg
from app.routers.uploads import _part_size
from app.schemas import (
    LibraryAssetOut,
    LibraryCreate,
    LibraryImportIn,
    LibraryRename,
    PartSignIn,
    ReusableRecording,
    UploadCompleteIn,
)
from app.storage import store

router = APIRouter(prefix="/library", tags=["library"])

# Extensions by kind. Anything ffmpeg/Pillow can read works; this list only
# keeps executables and documents out and decides the asset kind.
IMAGE_EXTS = {"png", "jpg", "jpeg", "webp", "gif", "bmp", "tif", "tiff", "heic", "heif", "avif", "svg", "ico"}
VIDEO_EXTS = {"mp4", "mov", "webm", "mkv", "avi", "m4v", "mpeg", "mpg", "wmv", "flv", "3gp", "ts", "ogv"}
AUDIO_EXTS = {"mp3", "wav", "m4a", "aac", "ogg", "oga", "flac", "opus", "wma", "aif", "aiff"}
SINGLE_PUT_MAX = 32 * 1024 * 1024  # above this, resumable multipart


def kind_for_ext(ext: str) -> str | None:
    ext = ext.lower()
    if ext in IMAGE_EXTS:
        return "image"
    if ext in VIDEO_EXTS:
        return "video"
    if ext in AUDIO_EXTS:
        return "audio"
    return None


def _owned(db: Session, user, asset_id: str) -> LibraryAsset:
    return owned_row(db, user, LibraryAsset, asset_id, "asset")


def _out(a: LibraryAsset, **extra) -> LibraryAssetOut:
    out = LibraryAssetOut.model_validate(a)
    out.has_audio = bool(a.has_audio)
    for k, v in extra.items():
        setattr(out, k, v)
    return out


@router.get("", response_model=list[LibraryAssetOut])
def list_library(user: CurrentUser, kind: str | None = None,
                 db: Session = Depends(get_session)) -> list[LibraryAssetOut]:
    q = select(LibraryAsset).where(LibraryAsset.user_id == user.id, LibraryAsset.status != "uploading")
    if kind:
        q = q.where(LibraryAsset.kind == kind)
    return [_out(a) for a in db.scalars(q.order_by(LibraryAsset.created_at.desc()))]


@router.post("", response_model=LibraryAssetOut, status_code=201)
def create_asset(payload: LibraryCreate, user: CurrentUser,
                 db: Session = Depends(get_session)) -> LibraryAssetOut:
    kind = kind_for_ext(payload.ext)
    if kind is None:
        raise HTTPException(status_code=422, detail=f"unsupported file type .{payload.ext}")
    a = LibraryAsset(user_id=user.id, kind=kind, name=payload.name.strip()[:200], ext=payload.ext.lower(),
                     storage_key="", size=payload.size)
    db.add(a)
    db.flush()
    a.storage_key = f"library/{a.id}/original.{a.ext}"
    if payload.size <= SINGLE_PUT_MAX:
        db.commit()
        return _out(a, put_url=f"/media/{a.storage_key}")
    a.part_size = _part_size(payload.size)
    a.upload_id = store.mp_create(a.storage_key)
    db.commit()
    return _out(a, upload_id=a.upload_id, part_size=a.part_size,
                part_count=max(1, math.ceil(a.size / a.part_size)))


def _start_processing(db: Session, a: LibraryAsset) -> LibraryAssetOut:
    a.status = "processing"
    a.error = None
    db.commit()
    enqueue_library_process(a.id)
    return _out(a)


@router.post("/{asset_id}/uploaded", response_model=LibraryAssetOut)
def single_put_done(asset_id: str, user: CurrentUser, db: Session = Depends(get_session)) -> LibraryAssetOut:
    a = _owned(db, user, asset_id)
    if a.status != "uploading":
        return _out(a)
    if not store.exists(a.storage_key):
        raise HTTPException(status_code=409, detail="file not received yet")
    return _start_processing(db, a)


@router.get("/{asset_id}/parts")
def list_parts(asset_id: str, user: CurrentUser, db: Session = Depends(get_session)) -> dict:
    a = _owned(db, user, asset_id)
    if a.status != "uploading" or not a.upload_id:
        return {"status": a.status, "parts": []}
    parts = store.mp_list_parts(a.storage_key, a.upload_id)
    return {"status": a.status, "parts": [{"number": p.number, "etag": p.etag, "size": p.size} for p in parts]}


@router.post("/{asset_id}/parts/sign")
def sign_parts(asset_id: str, payload: PartSignIn, user: CurrentUser,
               db: Session = Depends(get_session)) -> dict:
    a = _owned(db, user, asset_id)
    if a.status != "uploading" or not a.upload_id:
        raise HTTPException(status_code=409, detail=f"asset is {a.status}")
    count = max(1, math.ceil(a.size / a.part_size))
    out = []
    for n in payload.numbers:
        if not 1 <= n <= count:
            raise HTTPException(status_code=422, detail=f"part {n} outside 1..{count}")
        url = store.mp_part_url(a.storage_key, a.upload_id, n)
        out.append({"number": n, "url": url or f"/library/{a.id}/parts/{n}", "direct": url is not None})
    return {"parts": out}


@router.put("/{asset_id}/parts/{number}")
async def put_part(asset_id: str, number: int, request: Request, user: CurrentUser,
                   db: Session = Depends(get_session)) -> dict:
    """Local backend only: receive one part (S3 parts go straight to the store)."""
    a = _owned(db, user, asset_id)
    if store.backend != "local":
        raise HTTPException(status_code=409, detail="parts go directly to object storage")
    if a.status != "uploading" or not a.upload_id:
        raise HTTPException(status_code=409, detail=f"asset is {a.status}")
    count = max(1, math.ceil(a.size / a.part_size))
    if not 1 <= number <= count:
        raise HTTPException(status_code=422, detail=f"part {number} outside 1..{count}")
    chunks: list[bytes] = []
    async for chunk in request.stream():
        if chunk:
            chunks.append(chunk)
    if not chunks:
        raise HTTPException(status_code=400, detail="empty part")
    info = await run_in_threadpool(store.write_part, a.upload_id, number, iter(chunks))
    return {"number": info.number, "etag": info.etag, "size": info.size}


@router.post("/{asset_id}/complete", response_model=LibraryAssetOut)
def complete(asset_id: str, payload: UploadCompleteIn, user: CurrentUser,
             db: Session = Depends(get_session)) -> LibraryAssetOut:
    a = _owned(db, user, asset_id)
    if a.status != "uploading":
        return _out(a)
    if not a.upload_id:
        raise HTTPException(status_code=409, detail="not a multipart upload")
    count = max(1, math.ceil(a.size / a.part_size))
    numbers = sorted({p.number for p in payload.parts})
    if numbers != list(range(1, count + 1)):
        raise HTTPException(status_code=422, detail=f"expected parts 1..{count}")
    have = {p.number: p for p in store.mp_list_parts(a.storage_key, a.upload_id)}
    missing = [n for n in numbers if n not in have]
    if missing:
        raise HTTPException(status_code=409, detail=f"parts not received yet: {missing[:10]}")
    received = sum(have[n].size for n in numbers)
    if received != a.size:
        raise HTTPException(status_code=409, detail=f"received {received} bytes, expected {a.size}")
    store.mp_complete(a.storage_key, a.upload_id, [(n, have[n].etag) for n in numbers])
    return _start_processing(db, a)


@router.post("/{asset_id}/remove-bg", response_model=LibraryAssetOut, status_code=202)
def remove_background(asset_id: str, user: CurrentUser, db: Session = Depends(get_session)) -> LibraryAssetOut:
    a = _owned(db, user, asset_id)
    if a.kind != "image":
        raise HTTPException(status_code=400, detail="background removal works on images only")
    if a.status != "ready":
        raise HTTPException(status_code=409, detail="the image is still processing")
    if a.bg_status != "running":
        a.bg_status = "running"
        a.error = None
        db.commit()
        enqueue_library_remove_bg(a.id)
    return _out(a)


@router.get("/recordings", response_model=list[ReusableRecording])
def reusable_recordings(user: CurrentUser, db: Session = Depends(get_session)) -> list[ReusableRecording]:
    """Recordings from every project the user can edit, for "reuse a recording"."""
    pids = project_ids_for(db, user)
    if not pids:
        return []
    rows = db.execute(
        select(CaptureSession, Project.name, MediaAsset.storage_key)
        .join(Project, Project.id == CaptureSession.project_id)
        .join(MediaAsset, (MediaAsset.session_id == CaptureSession.id) & (MediaAsset.kind == "raw_video"))
        .where(CaptureSession.project_id.in_(pids))
        .order_by(CaptureSession.created_at.desc())
        .limit(200)
    ).all()
    from app.routers.sessions import _poster_for

    return [
        ReusableRecording(session_id=s.id, project_id=s.project_id, project_name=name,
                          created_at=s.created_at, duration_ms=s.duration_ms,
                          poster=_poster_for(db, s.id), storage_key=key)
        for s, name, key in rows
    ]


@router.post("/import-recording", response_model=LibraryAssetOut, status_code=202)
def import_recording(payload: LibraryImportIn, user: CurrentUser,
                     db: Session = Depends(get_session)) -> LibraryAssetOut:
    sess = owned_session(db, user, payload.session_id)
    video = db.scalar(select(MediaAsset).where(MediaAsset.session_id == sess.id,
                                               MediaAsset.kind == "raw_video"))
    if video is None:
        raise HTTPException(status_code=409, detail="that recording has no video")
    project = db.get(Project, sess.project_id)
    ext = video.storage_key.rsplit(".", 1)[-1].lower()[:5] if "." in video.storage_key else "mp4"
    a = LibraryAsset(user_id=user.id, kind="video", name=f"{project.name if project else 'Recording'}",
                     ext=ext, source="recording", source_session_id=sess.id,
                     storage_key=video.storage_key, status="processing", size=0)
    db.add(a)
    db.commit()
    enqueue_library_import(a.id)
    return _out(a)


@router.patch("/{asset_id}", response_model=LibraryAssetOut)
def rename(asset_id: str, payload: LibraryRename, user: CurrentUser,
           db: Session = Depends(get_session)) -> LibraryAssetOut:
    a = _owned(db, user, asset_id)
    a.name = payload.name.strip()[:200]
    db.commit()
    return _out(a)


@router.delete("/{asset_id}", status_code=204)
def delete_asset(asset_id: str, user: CurrentUser, db: Session = Depends(get_session)) -> None:
    a = _owned(db, user, asset_id)
    if a.status == "uploading" and a.upload_id:
        try:
            store.mp_abort(a.storage_key, a.upload_id)
        except Exception:  # noqa: BLE001 - an abandoned upload must not block the delete
            pass
    db.delete(a)
    db.commit()
    try:
        store.delete_prefix(f"library/{asset_id}/")
    except Exception:  # noqa: BLE001 - leftover files never fail a delete
        pass
