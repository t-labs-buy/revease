"""Local media transfer. Mirrors an S3/MinIO presigned PUT/GET so the client code
is identical when V2 swaps in object storage. Streaming both ways so large video
files never block the event loop or exhaust memory.

Reads stay public: `<video src>` / `<img src>` and the public share viewer cannot
attach an Authorization header, and storage keys embed unguessable UUIDs. Writes
are authenticated *and* authorized against the key's owning entity, so no one can
overwrite another user's recording."""

from __future__ import annotations

import mimetypes

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, Response
from sqlalchemy.orm import Session

from app.auth import CurrentUser
from app.db import get_session
from app.models import BrandPackage, User
from app.ownership import owned_row, owned_session
from app.storage import store

router = APIRouter(prefix="/media", tags=["media"])


def _authorize_write(db: Session, user: User, storage_key: str) -> None:
    """Client uploads only ever target an entity the caller must own. Anything
    outside those namespaces (renders/, previews/ — written by the worker) is
    rejected outright rather than trusted."""
    parts = storage_key.split("/")
    if len(parts) >= 2 and parts[0] == "sessions":
        owned_session(db, user, parts[1])
        return
    if len(parts) >= 2 and parts[0] == "packages":
        owned_row(db, user, BrandPackage, parts[1], "package")
        return
    raise HTTPException(status_code=403, detail="cannot upload to this storage key")


@router.put("/{storage_key:path}")
async def put_media(
    storage_key: str,
    request: Request,
    user: CurrentUser,
    db: Session = Depends(get_session),
) -> Response:
    _authorize_write(db, user, storage_key)
    try:
        path = store.local_path(storage_key)  # validates against traversal
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    path.parent.mkdir(parents=True, exist_ok=True)

    total = 0
    with path.open("wb") as f:
        async for chunk in request.stream():  # stream to disk, never buffer in memory
            if chunk:
                f.write(chunk)
                total += len(chunk)
    if total == 0:
        path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="empty body")
    return Response(status_code=204)


@router.get("/{storage_key:path}")
def get_media(storage_key: str) -> FileResponse:
    try:
        path = store.local_path(storage_key)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    if not path.exists():
        raise HTTPException(status_code=404, detail="not found")
    media_type = mimetypes.guess_type(storage_key)[0] or "application/octet-stream"
    # FileResponse streams from disk and honours HTTP Range (video seeking).
    return FileResponse(path, media_type=media_type)
