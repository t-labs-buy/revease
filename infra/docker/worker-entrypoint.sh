#!/usr/bin/env bash
# Prepare the shared data dir and (best-effort) fetch the Kokoro neural TTS model
# once into the persistent volume, then hand off to the Celery command (CMD).
set -e

DATA_DIR="${REFRACT_DATA_DIR:-/data}"
mkdir -p "$DATA_DIR/media" "$DATA_DIR/kokoro"

if [ "${REFRACT_FETCH_KOKORO:-1}" = "1" ] && [ ! -f "$DATA_DIR/kokoro/kokoro-v1.0.onnx" ]; then
  base="https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0"
  echo "[worker] fetching Kokoro TTS model (~350MB, one time)…"
  curl -fsSL -C - "$base/kokoro-v1.0.onnx" -o "$DATA_DIR/kokoro/kokoro-v1.0.onnx" \
    && curl -fsSL -C - "$base/voices-v1.0.bin" -o "$DATA_DIR/kokoro/voices-v1.0.bin" \
    || echo "[worker] Kokoro download failed — TTS will fall back to Piper (keyless)."
fi

exec "$@"
