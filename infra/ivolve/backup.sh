#!/usr/bin/env bash
# Nightly backup of the RevEase data volume -> ~/apps-data/revease-backups/.
#
# The SQLite DB is copied with sqlite3's online backup API, NOT by tarring the
# live file: the DB runs in WAL mode with the api and worker both writing, so a
# plain copy can capture a torn page set. The snapshot is taken inside the volume,
# tarred alongside media/, then removed.
#
# Deliberately NOT backed up: data/kokoro (338MB TTS model, re-downloaded on first
# worker start) and data/tts (regenerable synthesis cache). Those would triple the
# archive for nothing.
#
# Installed as: 30 2 * * *  /home/ubuntu/apps/revease/backup.sh
set -euo pipefail

DEST="$HOME/apps-data/revease-backups"
KEEP=7                 # nightly archives to retain
MIN_FREE_GB=8          # refuse to run if the disk is this tight
VOLUME=revease_revease-data
STAMP=$(date +%F)
LOG="$DEST/backup.log"

mkdir -p "$DEST"
exec >>"$LOG" 2>&1
echo "=== $(date -Is) starting ==="

free_gb=$(df --output=avail -BG / | tail -1 | tr -dc '0-9')
if [ "$free_gb" -lt "$MIN_FREE_GB" ]; then
    echo "ABORT: only ${free_gb}G free on /, need ${MIN_FREE_GB}G"
    exit 1
fi

# Consistent DB snapshot from inside the running api container.
docker exec revease-api python -c "
import sqlite3
src = sqlite3.connect('file:/data/refract.sqlite3?mode=ro', uri=True)
dst = sqlite3.connect('/data/_backup.sqlite3')
src.backup(dst)
dst.close(); src.close()
print('sqlite snapshot ok')
"

ARCHIVE="$DEST/revease-$STAMP.tar.gz"
docker run --rm \
    -v "$VOLUME":/data:ro \
    -v "$DEST":/backup \
    alpine:3 \
    tar czf "/backup/revease-$STAMP.tar.gz" \
        --exclude=./kokoro --exclude=./tts \
        --exclude=./refract.sqlite3 \
        --exclude=./refract.sqlite3-wal --exclude=./refract.sqlite3-shm \
        -C /data .

docker exec revease-api rm -f /data/_backup.sqlite3

echo "wrote $ARCHIVE ($(du -h "$ARCHIVE" | cut -f1))"

# Retention: keep the newest $KEEP archives, drop the rest.
ls -1t "$DEST"/revease-*.tar.gz 2>/dev/null | tail -n +$((KEEP + 1)) | while read -r old; do
    echo "pruning $(basename "$old")"
    rm -f "$old"
done

echo "=== $(date -Is) done ==="
