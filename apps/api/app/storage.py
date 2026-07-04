"""Local media storage with a presigned-style interface.

V1 stores media on the local filesystem but exposes the same shape MinIO/S3 uses
(create an upload target, resolve a download URL) so V2 can drop in object storage
without touching callers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.config import get_settings


@dataclass(frozen=True)
class UploadTarget:
    """Where a client should send bytes. For local storage the 'url' is an API
    route that accepts a PUT; for S3/MinIO it becomes a real presigned URL."""

    storage_key: str
    url: str
    method: str = "PUT"


class LocalMediaStore:
    def __init__(self, root: Path | None = None) -> None:
        self.root = root or get_settings().media_dir
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, storage_key: str) -> Path:
        # Prevent traversal outside the media root.
        p = (self.root / storage_key).resolve()
        if not str(p).startswith(str(self.root.resolve())):
            raise ValueError(f"storage_key escapes media root: {storage_key!r}")
        return p

    def upload_target(self, storage_key: str) -> UploadTarget:
        return UploadTarget(storage_key=storage_key, url=f"/media/{storage_key}")

    def write(self, storage_key: str, data: bytes) -> str:
        path = self._path(storage_key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return storage_key

    def read(self, storage_key: str) -> bytes:
        return self._path(storage_key).read_bytes()

    def exists(self, storage_key: str) -> bool:
        return self._path(storage_key).exists()

    def download_url(self, storage_key: str) -> str:
        return f"/media/{storage_key}"

    def local_path(self, storage_key: str) -> Path:
        """Filesystem path for a key (workers read/write media directly in V1)."""
        return self._path(storage_key)


store = LocalMediaStore()
