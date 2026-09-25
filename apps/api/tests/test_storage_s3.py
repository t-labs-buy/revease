"""The S3 backend against moto's in-memory S3: commit/fetch round trip, cache
staleness, listing, prefix delete, presigned-URL origin rewrite, multipart."""

from __future__ import annotations

import pytest

moto = pytest.importorskip("moto")


@pytest.fixture()
def s3store(monkeypatch, tmp_path):
    from moto import mock_aws

    from app import storage
    from app.config import get_settings

    s = get_settings()
    for k, v in {"storage_backend": "s3", "s3_endpoint_url": "http://minio:9000", "s3_public_url": "/s3",
                 "s3_bucket": "test-bucket", "s3_access_key": "k", "s3_secret_key": "s",
                 "media_cache_dir": tmp_path / "cache"}.items():
        monkeypatch.setattr(s, k, v)
    with mock_aws():
        st = storage.S3MediaStore.__new__(storage.S3MediaStore)
        import boto3
        from botocore.config import Config

        st.settings, st.bucket, st.root, st._bucket_ready = s, s.s3_bucket, s.media_cache_dir, False
        st.root.mkdir(parents=True)
        # moto intercepts AWS endpoints; the internal endpoint is only used for presign strings
        st.client = boto3.client("s3", region_name="us-east-1", aws_access_key_id="k",
                                 aws_secret_access_key="s", config=Config(signature_version="s3v4", s3={"addressing_style": "path"}))
        st.ensure_bucket()
        yield st


def test_commit_fetch_roundtrip_and_cache_refresh(s3store):
    key = "sessions/abc/frames/frame_0001.jpg"
    s3store.write(key, b"one")
    s3store.local_path(key).unlink()  # a different worker: nothing cached locally
    assert s3store.fetch(key).read_bytes() == b"one"
    # the object changes remotely -> the stale cached copy is replaced
    s3store.client.put_object(Bucket=s3store.bucket, Key=key, Body=b"two!")
    assert s3store.fetch(key).read_bytes() == b"two!"
    assert s3store.fetch("sessions/abc/missing.jpg") is None
    assert s3store.exists(key) and s3store.size(key) == 4


def test_commit_tree_list_and_delete_prefix(s3store):
    d = s3store.local_path("sessions/s1/frames")
    d.mkdir(parents=True)
    for i in range(3):
        (d / f"frame_{i}.jpg").write_bytes(b"x" * (i + 1))
    s3store.commit_tree("sessions/s1/frames")
    keys = sorted(o.key for o in s3store.list("sessions/s1/"))
    assert keys == [f"sessions/s1/frames/frame_{i}.jpg" for i in range(3)]
    s3store.delete_prefix("sessions/s1/")
    assert list(s3store.list("sessions/s1/")) == [] and not d.exists()


def test_presigned_urls_swap_origin_only(s3store):
    s3store.client = s3store.client  # moto client signs against its own endpoint
    url = s3store.presigned_get("sessions/a/source.mp4")
    assert "X-Amz-Signature=" in url
    s3store.settings.s3_endpoint_url = url.split("/test-bucket/")[0]
    rewritten = s3store.presigned_get("sessions/a/source.mp4")
    assert rewritten.startswith("/s3/test-bucket/sessions/a/source.mp4?")


def test_multipart_roundtrip(s3store):
    key = "sessions/s2/raw_video_x.webm"
    uid = s3store.mp_create(key)
    p1, p2 = b"a" * (5 * 1024 * 1024), b"tail"
    e1 = s3store.client.upload_part(Bucket=s3store.bucket, Key=key, UploadId=uid, PartNumber=1, Body=p1)["ETag"]
    s3store.client.upload_part(Bucket=s3store.bucket, Key=key, UploadId=uid, PartNumber=2, Body=p2)
    parts = s3store.mp_list_parts(key, uid)
    assert [(p.number, p.size) for p in parts] == [(1, len(p1)), (2, 4)] and parts[0].etag == e1.strip('"')
    s3store.mp_complete(key, uid, [(p.number, p.etag) for p in parts])
    assert s3store.read(key) == p1 + p2
