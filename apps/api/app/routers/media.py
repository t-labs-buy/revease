"""Local media transfer. Mirrors an S3/MinIO presigned PUT/GET so the client code
is identical when V2 swaps in object storage. Streaming both ways so large video
files never block the event loop or exhaust memory."""

from __future__ import annotations

import mimetypes

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, Response

from app.storage import store

router = APIRouter(prefix="/media", tags=["media"])


@router.put("/{storage_key:path}")
async def put_media(storage_key: str, request: Request) -> Response:
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
