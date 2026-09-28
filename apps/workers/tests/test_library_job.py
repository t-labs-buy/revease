"""Library normalization: any format in, PNG / H.264 MP4 / playable audio out."""

import shutil
import subprocess

import pytest
from PIL import Image

from app.db import SessionLocal
from app.models import LibraryAsset
from app.storage import store
from worker.pipeline.library import process_asset, remove_background

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")


def _asset(kind: str, ext: str, make) -> str:  # noqa: ANN001
    db = SessionLocal()
    try:
        a = LibraryAsset(kind=kind, name=f"test.{ext}", ext=ext, storage_key="", status="processing")
        db.add(a)
        db.flush()
        a.storage_key = f"library/{a.id}/original.{ext}"
        out = store.local_path(a.storage_key)
        out.parent.mkdir(parents=True, exist_ok=True)
        make(out)
        db.commit()
        return a.id
    finally:
        db.close()


def _get(asset_id: str) -> LibraryAsset:
    db = SessionLocal()
    try:
        a = db.get(LibraryAsset, asset_id)
        db.expunge(a)
        return a
    finally:
        db.close()


def _ff(*args: str):
    return lambda out: subprocess.run(["ffmpeg", "-y", *args, str(out)], capture_output=True, check=True)


def test_still_images_become_png_with_orientation_and_alpha():
    aid = _asset("image", "jpg", lambda o: Image.new("RGB", (300, 120), (200, 10, 10)).save(o, "JPEG"))
    assert process_asset(aid)["status"] == "ready"
    a = _get(aid)
    assert a.normalized_key.endswith("normalized.png") and (a.width, a.height) == (300, 120)

    aid = _asset("image", "png", lambda o: Image.new("RGBA", (50, 50), (0, 0, 0, 0)).save(o))
    process_asset(aid)
    with Image.open(store.local_path(_get(aid).normalized_key)) as im:
        assert im.mode == "RGBA"


def test_animated_gif_becomes_a_video():
    def gif(out):
        frames = [Image.new("RGB", (64, 64), (i * 40, 0, 0)) for i in range(5)]
        frames[0].save(out, save_all=True, append_images=frames[1:], duration=100, loop=0)

    aid = _asset("image", "gif", gif)
    assert process_asset(aid) == {"status": "ready", "kind": "video"}
    a = _get(aid)
    assert a.normalized_key.endswith(".mp4") and a.poster_key and a.duration_ms


def test_webm_is_transcoded_and_mp4_reused():
    aid = _asset("video", "webm", _ff("-f", "lavfi", "-i", "testsrc=size=320x240:rate=10:duration=1",
                                        "-c:v", "libvpx-vp9"))
    assert process_asset(aid)["status"] == "ready"
    a = _get(aid)
    assert a.normalized_key.endswith("normalized.mp4") and a.duration_ms and a.poster_key

    aid = _asset("video", "mp4", _ff("-f", "lavfi", "-i", "testsrc=size=320x240:rate=10:duration=1",
                                       "-pix_fmt", "yuv420p"))
    process_asset(aid)
    a = _get(aid)
    assert a.normalized_key == a.storage_key  # already H.264 MP4: no re-encode


def test_audio_and_bad_files():
    aid = _asset("audio", "wav", _ff("-f", "lavfi", "-i", "sine=duration=1"))
    process_asset(aid)
    a = _get(aid)
    assert a.status == "ready" and a.normalized_key == a.storage_key and 900 <= a.duration_ms <= 1100

    aid = _asset("audio", "flac", _ff("-f", "lavfi", "-i", "sine=duration=1"))
    process_asset(aid)
    assert _get(aid).normalized_key.endswith("normalized.m4a")

    aid = _asset("video", "mp4", lambda o: o.write_bytes(b"not a video"))
    assert process_asset(aid)["status"] == "error"
    assert _get(aid).error


def test_remove_background_writes_a_cutout_and_keeps_the_original():
    def logo(out):
        im = Image.new("RGB", (80, 80), (255, 255, 255))
        im.paste((30, 143, 142), (20, 20, 60, 60))
        im.save(out)

    aid = _asset("image", "png", logo)
    process_asset(aid)
    assert remove_background(aid)["bg_status"] == "ready"
    a = _get(aid)
    assert a.nobg_key.endswith("nobg.png") and store.exists(a.normalized_key)
    with Image.open(store.local_path(a.nobg_key)) as im:
        assert im.getpixel((0, 0))[3] == 0 and im.getpixel((40, 40))[3] == 255
