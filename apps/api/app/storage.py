"""Media storage: local filesystem (single host) or any S3-compatible object
store (MinIO / AWS S3), behind one interface.

The contract every caller follows — it is what makes the S3 backend possible:

- **Reading** a file with ffmpeg/Pillow: `fetch(key) -> Path | None`. Local
  returns the file itself; S3 downloads it into the media cache first (and
  re-downloads when the object changed).
- **Writing**: produce the file at `local_path(key)`, then `commit(key)` (or
  `commit_tree(prefix)` for a directory of frames). Local: no-op. S3: upload.
  `write(key, bytes)` does both.
- **Scratch/work dirs** (render segment cache, TTS cache): `local_path(...)`
  and never commit. On S3 these live in the worker's cache and are per-machine.
- **Browsers** always get `/media/{key}` (API route). On S3 that route answers
  307 to a short-lived presigned URL, so bytes never flow through the API.

Why presigned URLs are rewritten: they are signed against the internal endpoint
(http://minio:9000). SigV4 signs host + path, so the browser-facing URL keeps
the path and query and only swaps the origin to `s3_public_url`; an nginx edge
then proxies with `Host: minio:9000`, reproducing exactly what was signed.

Direct multipart uploads (`mp_*`) let a browser upload a multi-GB recording in
resumable parts straight to the store. The local backend implements the same
calls with part files, so the web client has one code path.
"""

from __future__ import annotations

import hashlib
import logging
import mimetypes
import os
import shutil
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from app.config import get_settings

log = logging.getLogger("refract.storage")


@dataclass(frozen=True)
class UploadTarget:
    """Where a client should send bytes for a small upload (always an API PUT
    route, so older clients such as the extension keep working on either backend)."""

    storage_key: str
    url: str
    method: str = "PUT"


@dataclass(frozen=True)
class ObjectInfo:
    key: str
    size: int
    modified: datetime


@dataclass(frozen=True)
class PartInfo:
    number: int
    etag: str
    size: int


def _attachment(name: str) -> str:
    """RFC 6266 attachment header value, safe for non-ASCII project names."""
    from urllib.parse import quote

    ascii_name = name.encode("ascii", "ignore").decode() or "video"
    ascii_name = ascii_name.replace('"', "")
    return f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(name)}"


def _content_type(key: str) -> str:
    return mimetypes.guess_type(key)[0] or "application/octet-stream"


class _PathMixin:
    root: Path

    def _path(self, storage_key: str) -> Path:
        # Prevent traversal outside the root.
        p = (self.root / storage_key).resolve()
        if not str(p).startswith(str(self.root.resolve())):
            raise ValueError(f"storage_key escapes media root: {storage_key!r}")
        return p

    def local_path(self, storage_key: str) -> Path:
        """Where this machine keeps the file for `storage_key` (may not exist).
        Write here, then `commit`."""
        return self._path(storage_key)

    def upload_target(self, storage_key: str) -> UploadTarget:
        return UploadTarget(storage_key=storage_key, url=f"/media/{storage_key}")

    def download_url(self, storage_key: str) -> str:
        return f"/media/{storage_key}"

    def write(self, storage_key: str, data: bytes) -> str:
        path = self._path(storage_key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        self.commit(storage_key)
        return storage_key

    # ---- local part files (used by the local backend's multipart) ----
    def _parts_dir(self, upload_id: str) -> Path:
        if not upload_id.isalnum():
            raise ValueError("bad upload id")
        return self.root / ".uploads" / upload_id

    def write_part(self, upload_id: str, number: int, chunks: Iterator[bytes]) -> PartInfo:
        """Stream one part to disk (local backend). Returns its md5 ETag."""
        d = self._parts_dir(upload_id)
        d.mkdir(parents=True, exist_ok=True)
        tmp = d / f"{number:05d}.tmp"
        md5 = hashlib.md5()
        size = 0
        with tmp.open("wb") as f:
            for chunk in chunks:
                f.write(chunk)
                md5.update(chunk)
                size += len(chunk)
        tmp.replace(d / f"{number:05d}.part")
        return PartInfo(number, md5.hexdigest(), size)


class LocalMediaStore(_PathMixin):
    backend = "local"

    def __init__(self, root: Path | None = None) -> None:
        self.root = root or get_settings().media_dir
        self.root.mkdir(parents=True, exist_ok=True)

    def fetch(self, storage_key: str) -> Path | None:
        p = self._path(storage_key)
        return p if p.exists() else None

    def commit(self, storage_key: str) -> None:  # already in place
        return None

    def commit_tree(self, prefix: str) -> None:
        return None

    def read(self, storage_key: str) -> bytes:
        return self._path(storage_key).read_bytes()

    def exists(self, storage_key: str) -> bool:
        return self._path(storage_key).exists()

    def size(self, storage_key: str) -> int | None:
        p = self._path(storage_key)
        return p.stat().st_size if p.exists() else None

    def delete(self, storage_key: str) -> None:
        self._path(storage_key).unlink(missing_ok=True)

    def delete_prefix(self, prefix: str) -> None:
        p = self._path(prefix)
        if p.is_dir():
            shutil.rmtree(p, ignore_errors=True)
        else:
            p.unlink(missing_ok=True)

    def list(self, prefix: str = "") -> Iterator[ObjectInfo]:
        base = self._path(prefix) if prefix else self.root
        if base.is_file():
            files = [base]
        elif base.is_dir():
            files = (f for f in base.rglob("*") if f.is_file())
        else:
            return
        root = self.root.resolve()
        for f in files:
            rel = str(f.resolve().relative_to(root))
            if rel.startswith(".uploads/"):
                continue
            st = f.stat()
            yield ObjectInfo(rel, st.st_size, datetime.fromtimestamp(st.st_mtime, timezone.utc))

    def presigned_get(self, storage_key: str, download_name: str | None = None) -> str | None:
        return None

    # ---- multipart (part files under .uploads/<id>) ----
    def mp_create(self, storage_key: str) -> str:
        upload_id = uuid.uuid4().hex
        self._parts_dir(upload_id).mkdir(parents=True, exist_ok=True)
        return upload_id

    def mp_part_url(self, storage_key: str, upload_id: str, number: int) -> str | None:
        return None  # the API route /uploads/{id}/parts/{n} receives the bytes

    def mp_list_parts(self, storage_key: str, upload_id: str) -> list[PartInfo]:
        d = self._parts_dir(upload_id)
        out = []
        for f in sorted(d.glob("*.part")) if d.exists() else []:
            md5 = hashlib.md5()
            with f.open("rb") as fh:
                for chunk in iter(lambda: fh.read(1 << 20), b""):
                    md5.update(chunk)
            out.append(PartInfo(int(f.stem), md5.hexdigest(), f.stat().st_size))
        return out

    def mp_complete(self, storage_key: str, upload_id: str, parts: list[tuple[int, str]]) -> None:
        d = self._parts_dir(upload_id)
        dest = self._path(storage_key)
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_name(dest.name + ".assembling")
        with tmp.open("wb") as out:
            for number, _etag in sorted(parts):
                part = d / f"{number:05d}.part"
                if not part.exists():
                    raise ValueError(f"part {number} missing")
                with part.open("rb") as fh:
                    shutil.copyfileobj(fh, out, 1 << 20)
        tmp.replace(dest)
        shutil.rmtree(d, ignore_errors=True)

    def mp_abort(self, storage_key: str, upload_id: str) -> None:
        shutil.rmtree(self._parts_dir(upload_id), ignore_errors=True)


class S3MediaStore(_PathMixin):
    backend = "s3"

    def __init__(self) -> None:
        import boto3
        from botocore.config import Config

        s = get_settings()
        self.settings = s
        self.bucket = s.s3_bucket
        self.root = s.media_cache_dir  # local cache + scratch
        self.root.mkdir(parents=True, exist_ok=True)
        cfg = Config(signature_version="s3v4", s3={"addressing_style": "path"},
                     retries={"max_attempts": 5, "mode": "standard"})
        self.client = boto3.client(
            "s3",
            endpoint_url=s.s3_endpoint_url or None,
            region_name=s.s3_region,
            aws_access_key_id=s.s3_access_key or None,
            aws_secret_access_key=s.s3_secret_key or None,
            config=cfg,
        )
        self._bucket_ready = False

    # ---- helpers ----
    def ensure_bucket(self) -> None:
        if self._bucket_ready:
            return
        from botocore.exceptions import ClientError

        try:
            self.client.head_bucket(Bucket=self.bucket)
        except ClientError:
            kwargs = {"Bucket": self.bucket}
            if self.settings.s3_region != "us-east-1":
                kwargs["CreateBucketConfiguration"] = {"LocationConstraint": self.settings.s3_region}
            self.client.create_bucket(**kwargs)
        self._bucket_ready = True

    def _public(self, url: str) -> str:
        pub, ep = self.settings.s3_public_url.rstrip("/"), self.settings.s3_endpoint_url.rstrip("/")
        if pub and ep and url.startswith(ep):
            return pub + url[len(ep):]
        return url

    def _head(self, storage_key: str) -> dict | None:
        from botocore.exceptions import ClientError

        try:
            return self.client.head_object(Bucket=self.bucket, Key=storage_key)
        except ClientError:
            return None

    # ---- read ----
    def fetch(self, storage_key: str) -> Path | None:
        head = self._head(storage_key)
        if head is None:
            return None
        p = self._path(storage_key)
        remote_mtime = head["LastModified"].timestamp()
        if p.exists() and p.stat().st_size == head["ContentLength"] and abs(p.stat().st_mtime - remote_mtime) < 1:
            os.utime(p, (datetime.now().timestamp(), remote_mtime))  # touch atime for LRU
            return p
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(p.name + f".{uuid.uuid4().hex[:6]}.dl")
        self.client.download_file(self.bucket, storage_key, str(tmp))
        tmp.replace(p)
        os.utime(p, (datetime.now().timestamp(), remote_mtime))
        return p

    def read(self, storage_key: str) -> bytes:
        return self.client.get_object(Bucket=self.bucket, Key=storage_key)["Body"].read()

    def exists(self, storage_key: str) -> bool:
        return self._head(storage_key) is not None

    def size(self, storage_key: str) -> int | None:
        head = self._head(storage_key)
        return head["ContentLength"] if head else None

    def presigned_get(self, storage_key: str, download_name: str | None = None) -> str | None:
        """Signed GET. With `download_name` the store answers with
        `Content-Disposition: attachment`, so browsers save instead of playing."""
        params = {"Bucket": self.bucket, "Key": storage_key}
        if download_name:
            params["ResponseContentDisposition"] = _attachment(download_name)
        url = self.client.generate_presigned_url(
            "get_object", Params=params, ExpiresIn=self.settings.s3_presign_ttl_s,
        )
        return self._public(url)

    # ---- write ----
    def commit(self, storage_key: str) -> None:
        p = self._path(storage_key)
        self.client.upload_file(str(p), self.bucket, storage_key,
                                ExtraArgs={"ContentType": _content_type(storage_key)})
        head = self._head(storage_key)
        if head:  # align the cached copy so the next fetch trusts it
            os.utime(p, (datetime.now().timestamp(), head["LastModified"].timestamp()))

    def commit_tree(self, prefix: str) -> None:
        base = self._path(prefix)
        root = self.root.resolve()
        for f in sorted(base.rglob("*")) if base.is_dir() else []:
            if f.is_file() and not f.name.endswith((".tmp", ".dl", ".part")):
                self.commit(str(f.resolve().relative_to(root)))

    def delete(self, storage_key: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=storage_key)
        self._path(storage_key).unlink(missing_ok=True)

    def delete_prefix(self, prefix: str) -> None:
        batch: list[dict] = []
        for obj in self.list(prefix):
            batch.append({"Key": obj.key})
            if len(batch) == 1000:
                self.client.delete_objects(Bucket=self.bucket, Delete={"Objects": batch})
                batch = []
        if batch:
            self.client.delete_objects(Bucket=self.bucket, Delete={"Objects": batch})
        p = self._path(prefix)
        if p.is_dir():
            shutil.rmtree(p, ignore_errors=True)
        else:
            p.unlink(missing_ok=True)

    def list(self, prefix: str = "") -> Iterator[ObjectInfo]:
        paginator = self.client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
            for o in page.get("Contents", []):
                yield ObjectInfo(o["Key"], o["Size"], o["LastModified"])

    # ---- multipart ----
    def mp_create(self, storage_key: str) -> str:
        r = self.client.create_multipart_upload(Bucket=self.bucket, Key=storage_key,
                                                ContentType=_content_type(storage_key))
        return r["UploadId"]

    def mp_part_url(self, storage_key: str, upload_id: str, number: int) -> str | None:
        url = self.client.generate_presigned_url(
            "upload_part",
            Params={"Bucket": self.bucket, "Key": storage_key, "UploadId": upload_id, "PartNumber": number},
            ExpiresIn=self.settings.s3_presign_ttl_s,
        )
        return self._public(url)

    def mp_list_parts(self, storage_key: str, upload_id: str) -> list[PartInfo]:
        out: list[PartInfo] = []
        kwargs = {"Bucket": self.bucket, "Key": storage_key, "UploadId": upload_id}
        while True:
            r = self.client.list_parts(**kwargs)
            out += [PartInfo(p["PartNumber"], p["ETag"].strip('"'), p["Size"]) for p in r.get("Parts", [])]
            if not r.get("IsTruncated"):
                return out
            kwargs["PartNumberMarker"] = r["NextPartNumberMarker"]

    def mp_complete(self, storage_key: str, upload_id: str, parts: list[tuple[int, str]]) -> None:
        self.client.complete_multipart_upload(
            Bucket=self.bucket, Key=storage_key, UploadId=upload_id,
            MultipartUpload={"Parts": [{"PartNumber": n, "ETag": f'"{e.strip(chr(34))}"'} for n, e in sorted(parts)]},
        )

    def mp_abort(self, storage_key: str, upload_id: str) -> None:
        from botocore.exceptions import ClientError

        try:
            self.client.abort_multipart_upload(Bucket=self.bucket, Key=storage_key, UploadId=upload_id)
        except ClientError:
            pass

    def list_multipart_uploads(self) -> Iterator[tuple[str, str, datetime]]:
        paginator = self.client.get_paginator("list_multipart_uploads")
        for page in paginator.paginate(Bucket=self.bucket):
            for u in page.get("Uploads", []):
                yield u["Key"], u["UploadId"], u["Initiated"]


MediaStore = LocalMediaStore | S3MediaStore


def make_store() -> MediaStore:
    backend = get_settings().storage_backend.lower()
    if backend == "s3":
        return S3MediaStore()
    return LocalMediaStore()


def prune_cache(max_bytes: int | None = None) -> int:
    """Evict least-recently-used files from the S3 media cache until it fits.
    Returns bytes freed. No-op for the local backend (its 'cache' is the store)."""
    if store.backend != "s3":
        return 0
    limit = max_bytes if max_bytes is not None else int(get_settings().media_cache_max_gb * (1 << 30))
    files = [(f, f.stat()) for f in store.root.rglob("*") if f.is_file()]
    total = sum(st.st_size for _, st in files)
    freed = 0
    for f, st in sorted(files, key=lambda x: x[1].st_atime):
        if total - freed <= limit:
            break
        try:
            f.unlink()
            freed += st.st_size
        except OSError:
            pass
    if freed:
        log.info("media cache: evicted %.1f MB", freed / (1 << 20))
    return freed


store: MediaStore = make_store()
