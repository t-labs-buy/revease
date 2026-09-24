"""Resumable multipart uploads for large capture files.

Flow: create -> sign part URLs (in batches) -> PUT each part -> complete. On
S3 the browser PUTs parts straight to the store via presigned URLs, so a 2 GB
recording never passes through the API. On the local backend the part URLs
point at `PUT /uploads/{id}/parts/{n}` here — same client code either way.

Resuming: `GET /uploads/{id}` lists the parts the store already has, so a
client that lost its connection (or reloaded and re-picked the same file)
uploads only what is missing.
"""

from __future__ import annotations

import math

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.orm import Session

from app.auth import CurrentUser
from app.config import get_settings
from app.db import get_session
from app.models import MediaAsset, Upload
from app.ownership import owned_session
from app.schemas import PartSignIn, UploadCompleteIn, UploadCreate, UploadOut
from app.storage import store

router = APIRouter(tags=["uploads"])

MIN_PART = 5 * 1024 * 1024  # S3 minimum for every part but the last


def _part_size(size: int) -> int:
    """Configured part size, grown when needed to stay under S3's 10,000 parts."""
    base = max(MIN_PART, get_settings().upload_part_mb * 1024 * 1024)
    return max(base, math.ceil(size / 9_000))


def _owned_upload(db: Session, user, upload_id: str) -> Upload:
    up = db.get(Upload, upload_id)
    if up is None:
        raise HTTPException(status_code=404, detail="upload not found")
    owned_session(db, user, up.session_id)  # 404s for anyone else
    return up


def _out(up: Upload, with_parts: bool = False) -> UploadOut:
    parts = []
    if with_parts and up.status == "uploading":
        parts = [{"number": p.number, "etag": p.etag, "size": p.size}
                 for p in store.mp_list_parts(up.storage_key, up.backend_upload_id)]
    return UploadOut(upload_id=up.id, storage_key=up.storage_key, size=up.size, part_size=up.part_size,
                     part_count=max(1, math.ceil(up.size / up.part_size)), status=up.status, parts=parts)


@router.post("/sessions/{session_id}/uploads", response_model=UploadOut, status_code=201)
def create_upload(session_id: str, payload: UploadCreate, user: CurrentUser,
                  db: Session = Depends(get_session)) -> UploadOut:
    sess = owned_session(db, user, session_id)
    up = Upload(session_id=sess.id, kind=payload.kind, storage_key="", backend_upload_id="",
                size=payload.size, part_size=_part_size(payload.size))
    db.add(up)
    db.flush()
    up.storage_key = f"sessions/{sess.id}/{payload.kind}_{up.id}.{payload.ext}"
    up.backend_upload_id = store.mp_create(up.storage_key)
    db.commit()
    return _out(up)


@router.get("/uploads/{upload_id}", response_model=UploadOut)
def get_upload(upload_id: str, user: CurrentUser, db: Session = Depends(get_session)) -> UploadOut:
    return _out(_owned_upload(db, user, upload_id), with_parts=True)


@router.post("/uploads/{upload_id}/parts/sign")
def sign_parts(upload_id: str, payload: PartSignIn, user: CurrentUser,
               db: Session = Depends(get_session)) -> dict:
    up = _owned_upload(db, user, upload_id)
    if up.status != "uploading":
        raise HTTPException(status_code=409, detail=f"upload is {up.status}")
    count = max(1, math.ceil(up.size / up.part_size))
    out = []
    for n in payload.numbers:
        if not 1 <= n <= count:
            raise HTTPException(status_code=422, detail=f"part {n} outside 1..{count}")
        url = store.mp_part_url(up.storage_key, up.backend_upload_id, n)
        out.append({"number": n, "url": url or f"/uploads/{up.id}/parts/{n}", "direct": url is not None})
    return {"parts": out}


@router.put("/uploads/{upload_id}/parts/{number}")
async def put_part(upload_id: str, number: int, request: Request, user: CurrentUser,
                   db: Session = Depends(get_session)) -> dict:
    """Local backend only: receive one part (S3 parts go straight to the store)."""
    up = _owned_upload(db, user, upload_id)
    if store.backend != "local":
        raise HTTPException(status_code=409, detail="parts go directly to object storage")
    if up.status != "uploading":
        raise HTTPException(status_code=409, detail=f"upload is {up.status}")
    count = max(1, math.ceil(up.size / up.part_size))
    if not 1 <= number <= count:
        raise HTTPException(status_code=422, detail=f"part {number} outside 1..{count}")

    chunks: list[bytes] = []
    async for chunk in request.stream():
        if chunk:
            chunks.append(chunk)  # at most one part (<= part_size) in memory
    if not chunks:
        raise HTTPException(status_code=400, detail="empty part")
    info = await run_in_threadpool(store.write_part, up.backend_upload_id, number, iter(chunks))
    return {"number": info.number, "etag": info.etag, "size": info.size}


@router.post("/uploads/{upload_id}/complete")
def complete_upload(upload_id: str, payload: UploadCompleteIn, user: CurrentUser,
                    db: Session = Depends(get_session)) -> dict:
    up = _owned_upload(db, user, upload_id)
    if up.status == "done":
        asset = db.query(MediaAsset).filter(MediaAsset.storage_key == up.storage_key).first()
        return {"asset_id": asset.id if asset else None, "storage_key": up.storage_key}
    if up.status != "uploading":
        raise HTTPException(status_code=409, detail=f"upload is {up.status}")
    count = max(1, math.ceil(up.size / up.part_size))
    numbers = sorted({p.number for p in payload.parts})
    if numbers != list(range(1, count + 1)):
        raise HTTPException(status_code=422, detail=f"expected parts 1..{count}")
    have = {p.number: p for p in store.mp_list_parts(up.storage_key, up.backend_upload_id)}
    missing = [n for n in numbers if n not in have]
    if missing:
        raise HTTPException(status_code=409, detail=f"parts not received yet: {missing[:10]}")
    received = sum(have[n].size for n in numbers)
    if received != up.size:
        raise HTTPException(status_code=409, detail=f"received {received} bytes, expected {up.size}")
    store.mp_complete(up.storage_key, up.backend_upload_id, [(n, have[n].etag) for n in numbers])
    asset = MediaAsset(session_id=up.session_id, kind=up.kind, storage_key=up.storage_key,
                       meta_json={"size": up.size})
    db.add(asset)
    up.status = "done"
    db.commit()
    return {"asset_id": asset.id, "storage_key": up.storage_key}


@router.delete("/uploads/{upload_id}", status_code=204)
def abort_upload(upload_id: str, user: CurrentUser, db: Session = Depends(get_session)) -> None:
    up = _owned_upload(db, user, upload_id)
    if up.status == "uploading":
        store.mp_abort(up.storage_key, up.backend_upload_id)
        up.status = "aborted"
        db.commit()
