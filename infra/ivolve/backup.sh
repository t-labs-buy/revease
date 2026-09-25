#!/usr/bin/env bash
# Nightly backup of RevEase data -> ~/apps-data/revease-backups/.
#
# Follows whatever backends .env selects:
#   database  Postgres (REFRACT_DATABASE_URL=postgresql…) -> pg_dump custom format
#             SQLite (default)                            -> sqlite3 online backup
#   media     S3/MinIO (REFRACT_STORAGE_BACKEND=s3)       -> tar of the minio-data volume
#             local (default)                             -> tar of the data volume's media/
#
# Why not a plain copy of the SQLite file: WAL mode with two writers means a file
# copy can capture a torn page set. Why tar the MinIO volume rather than mirror
# the bucket: restoring the volume brings back MinIO exactly as it was, metadata
# included, with one command.
#
# Deliberately NOT backed up: kokoro/ (TTS model, re-downloaded on start), the
# TTS clip cache and the media cache (all regenerable).
#
# Restore:
#   Postgres  docker exec -i revease-postgres pg_restore -U revease -d revease --clean < revease-<date>-db.pgdump
#   SQLite    extract revease-<date>-db.sqlite3 into the data volume as refract.sqlite3
#   MinIO     stop minio; docker run --rm -v revease_minio-data:/d -v $PWD:/b alpine sh -c "rm -rf /d/* && tar xzf /b/revease-<date>-media.tar.gz -C /d"
#   local     docker run --rm -v revease_revease-data:/d -v $PWD:/b alpine tar xzf /b/revease-<date>-media.tar.gz -C /d
#
# Installed as: 30 2 * * *  /home/ubuntu/apps/revease/backup.sh
set -euo pipefail
cd "$(dirname "$0")"

DEST="$HOME/apps-data/revease-backups"
KEEP=7                 # nightly sets to retain
MIN_FREE_GB=8          # refuse to run if the disk is this tight
DATA_VOLUME=revease_revease-data
MINIO_VOLUME=revease_minio-data
STAMP=$(date +%F)
LOG="$DEST/backup.log"

setting() { grep -E "^$1=" .env 2>/dev/null | tail -1 | cut -d= -f2- || true; }
DB_URL=$(setting REFRACT_DATABASE_URL)
STORAGE=$(setting REFRACT_STORAGE_BACKEND)

mkdir -p "$DEST"
exec >>"$LOG" 2>&1
echo "=== $(date -Is) starting (db=${DB_URL%%:*} storage=${STORAGE:-local}) ==="

free_gb=$(df --output=avail -BG / | tail -1 | tr -dc '0-9')
if [ "$free_gb" -lt "$MIN_FREE_GB" ]; then
    echo "ABORT: only ${free_gb}G free on /, need ${MIN_FREE_GB}G"
    exit 1
fi

# ---- database ----
if [[ "$DB_URL" == postgresql* ]]; then
    docker exec revease-postgres pg_dump -U revease -Fc revease > "$DEST/revease-$STAMP-db.pgdump"
    echo "pg_dump ok ($(du -h "$DEST/revease-$STAMP-db.pgdump" | cut -f1))"
else
    docker exec revease-api python -c "
import sqlite3
src = sqlite3.connect('file:/data/refract.sqlite3?mode=ro', uri=True)
dst = sqlite3.connect('/data/_backup.sqlite3')
src.backup(dst)
dst.close(); src.close()
print('sqlite snapshot ok')
"
    docker run --rm -v "$DATA_VOLUME":/data -v "$DEST":/backup alpine:3 \
        sh -c "cp /data/_backup.sqlite3 /backup/revease-$STAMP-db.sqlite3 && rm -f /data/_backup.sqlite3"
fi

# ---- media ----
if [ "$STORAGE" = "s3" ]; then
    docker run --rm -v "$MINIO_VOLUME":/d:ro -v "$DEST":/backup alpine:3 \
        tar czf "/backup/revease-$STAMP-media.tar.gz" -C /d .
else
    docker run --rm -v "$DATA_VOLUME":/data:ro -v "$DEST":/backup alpine:3 \
        tar czf "/backup/revease-$STAMP-media.tar.gz" --exclude=./media/tts -C /data ./media
fi
echo "media archive ok ($(du -h "$DEST/revease-$STAMP-media.tar.gz" | cut -f1))"

# ---- retention: keep the newest $KEEP of each kind ----
for pattern in 'revease-*-db.*' 'revease-*-media.tar.gz' 'revease-????-??-??.tar.gz'; do
    ls -1t "$DEST"/$pattern 2>/dev/null | tail -n +$((KEEP + 1)) | while read -r old; do
        echo "pruning $(basename "$old")"
        rm -f "$old"
    done
done

echo "=== $(date -Is) done ==="
