#!/usr/bin/env bash
# Prepare the shared data dir and (best-effort) fetch the Kokoro neural TTS model
# and the ISNet background-removal model once into the persistent volume, then
# hand off to the Celery command (CMD).
set -e

DATA_DIR="${REFRACT_DATA_DIR:-/data}"
mkdir -p "$DATA_DIR/media" "$DATA_DIR/kokoro" "$DATA_DIR/models"

if [ "${REFRACT_FETCH_KOKORO:-1}" = "1" ] && [ ! -f "$DATA_DIR/kokoro/kokoro-v1.0.onnx" ]; then
  base="https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0"
  echo "[worker] fetching Kokoro TTS model (~350MB, one time)…"
  curl -fsSL -C - "$base/kokoro-v1.0.onnx" -o "$DATA_DIR/kokoro/kokoro-v1.0.onnx" \
    && curl -fsSL -C - "$base/voices-v1.0.bin" -o "$DATA_DIR/kokoro/voices-v1.0.bin" \
    || echo "[worker] Kokoro download failed — TTS will fall back to Piper (keyless)."
fi

BG_MODEL="$DATA_DIR/models/isnet-general-use.onnx"
if [ "${REFRACT_FETCH_BG_MODEL:-1}" = "1" ] && [ ! -f "$BG_MODEL" ]; then
  echo "[worker] fetching background-removal model (~170MB, one time)…"
  curl -fsSL -C - "https://github.com/danielgatis/rembg/releases/download/v0.0.0/isnet-general-use.onnx" \
    -o "$BG_MODEL.part" && mv "$BG_MODEL.part" "$BG_MODEL" \
    || echo "[worker] background-removal model download failed — 'Remove BG' will key out flat backgrounds only."
fi

exec "$@"
