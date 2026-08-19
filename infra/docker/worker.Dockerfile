# Refract worker — Celery + FFmpeg render/ML/TTS pipeline. Build context = repo root.
# docker build -f infra/docker/worker.Dockerfile -t tlabsdoc/revease:worker .
# syntax=docker/dockerfile:1
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

# ffmpeg/ffprobe are required by the render + auto-edit pipeline; curl fetches the TTS model.
RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg curl \
 && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app

# The worker depends on the api ("app") package and the workflow-graph package,
# both as editable path deps — replicate the repo layout so uv can resolve them.
COPY packages/workflow-graph /app/packages/workflow-graph
COPY apps/api /app/apps/api
COPY apps/workers /app/apps/workers

WORKDIR /app/apps/workers
# WHISPER=1 (default) installs faster-whisper for real transcription; set 0 for a
# lighter image that falls back to an empty transcript.
ARG WHISPER=1
RUN if [ "$WHISPER" = "1" ]; then \
      uv sync --frozen --no-dev --extra whisper; \
    else \
      uv sync --frozen --no-dev; \
    fi

ENV PATH="/app/apps/workers/.venv/bin:$PATH" \
    REFRACT_DATA_DIR=/data \
    REFRACT_MEDIA_DIR=/data/media

COPY infra/docker/worker-entrypoint.sh /usr/local/bin/worker-entrypoint.sh
RUN chmod +x /usr/local/bin/worker-entrypoint.sh

ENTRYPOINT ["worker-entrypoint.sh"]
CMD ["celery", "-A", "worker.celery_app", "worker", "--loglevel=info", "--concurrency=2"]
