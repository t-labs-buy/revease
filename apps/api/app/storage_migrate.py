"""Copy the local media directory into the configured S3 bucket (one-time
switch from REFRACT_STORAGE_BACKEND=local to s3).

    REFRACT_STORAGE_BACKEND=s3 … python -m app.storage_migrate --from /data/media [--dry-run]

Keys are the relative paths, so every storage_key in the database stays valid.
Objects already present with the same size are skipped, so the copy can be
re-run after an interruption. Scratch/cache files (.uploads, *.part, the TTS
cache, render work clips) are skipped — they regenerate.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

SKIP_PREFIXES = (".uploads/", "tts/", "voicepreview_work/", "autoedit/")


def _worth_copying(rel: str) -> bool:
    if rel.startswith(SKIP_PREFIXES) or rel.endswith((".part", ".tmp", ".part.mp4", ".assembling")):
        return False
    if rel.startswith("renders/") and "/final_" not in rel:
        return False  # segment render cache
    return True


def main() -> int:
    from app.storage import S3MediaStore, _content_type, store

    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--from", dest="src", required=True, help="the local media directory")
    p.add_argument("--dry-run", action="store_true")
    a = p.parse_args()
    if not isinstance(store, S3MediaStore):
        print("set REFRACT_STORAGE_BACKEND=s3 (and the S3 settings) first", file=sys.stderr)
        return 2
    store.ensure_bucket()
    root = Path(a.src).resolve()
    copied = skipped = 0
    size_total = 0
    for f in sorted(root.rglob("*")):
        if not f.is_file():
            continue
        rel = str(f.relative_to(root))
        if not _worth_copying(rel):
            continue
        if store.size(rel) == f.stat().st_size:
            skipped += 1
            continue
        size_total += f.stat().st_size
        copied += 1
        if not a.dry_run:
            store.client.upload_file(str(f), store.bucket, rel, ExtraArgs={"ContentType": _content_type(rel)})
        if copied % 200 == 0:
            print(f"… {copied} files, {size_total / 1048576:.0f} MB")
    verb = "would copy" if a.dry_run else "copied"
    print(f"{verb} {copied} files ({size_total / 1048576:.1f} MB); {skipped} already present")
    return 0


if __name__ == "__main__":
    sys.exit(main())
