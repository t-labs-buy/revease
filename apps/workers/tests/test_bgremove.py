"""Background removal: the offline border-key fallback (ISNet needs the model)."""

from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from worker.pipeline import bgremove


def _logo(bg=(255, 255, 255)):
    im = Image.new("RGB", (120, 80), bg)
    # teal ring with a WHITE centre — the centre must survive (not border-connected)
    for x in range(30, 90):
        for y in range(15, 65):
            inner = 40 <= x < 80 and 25 <= y < 55
            im.putpixel((x, y), bg if inner else (30, 143, 142))
    return im


def test_border_key_removes_only_the_connected_background(monkeypatch, tmp_path):
    monkeypatch.setattr(bgremove, "model_path", lambda: tmp_path / "absent.onnx")
    out, method = bgremove.cutout(_logo())
    a = np.asarray(out.getchannel("A"))
    assert method == "border-key" and out.mode == "RGBA"
    assert a[0, 0] == 0 and a[79, 119] == 0          # corners gone
    assert a[20, 35] == 255                           # the ring stays
    assert a[40, 60] == 255                           # white inside the ring stays


def test_existing_transparency_is_kept(monkeypatch, tmp_path):
    monkeypatch.setattr(bgremove, "model_path", lambda: tmp_path / "absent.onnx")
    im = _logo((10, 10, 10)).convert("RGBA")
    im.putpixel((60, 20), (30, 143, 142, 0))  # already transparent pixel in the ring
    out, _ = bgremove.cutout(im)
    assert out.getpixel((60, 20))[3] == 0


# tests run on a temp data dir, so look for the model where `make bg-model` puts it
REPO_MODEL = Path(__file__).resolve().parents[3] / "data" / "models" / bgremove.MODEL_FILE


@pytest.mark.skipif(not REPO_MODEL.exists(), reason="ISNet model not downloaded (make bg-model)")
def test_isnet_cuts_out_the_subject(monkeypatch):
    monkeypatch.setattr(bgremove, "model_path", lambda: REPO_MODEL)
    # a solid teal disc on a white card: the disc is the salient object
    im = Image.new("RGB", (256, 256), (255, 255, 255))
    from PIL import ImageDraw

    ImageDraw.Draw(im).ellipse((64, 64, 192, 192), fill=(30, 143, 142))
    out, method = bgremove.cutout(im)
    a = np.asarray(out.getchannel("A"))
    assert method == "isnet" and out.size == (256, 256)
    assert a[128, 128] > 200 and a[5, 5] < 60
