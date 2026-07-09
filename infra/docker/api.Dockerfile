# Refract API — FastAPI + SQLite + local media. Build context = repo root.
# docker build -f infra/docker/api.Dockerfile -t tlabsdoc/revease:api .
# syntax=docker/dockerfile:1
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

ENV PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app

# Local workspace dependency (editable path in pyproject) must sit at ../../packages.
COPY packages/workflow-graph /app/packages/workflow-graph
COPY apps/api /app/apps/api

WORKDIR /app/apps/api
RUN uv sync --frozen --no-dev

ENV PATH="/app/apps/api/.venv/bin:$PATH" \
    REFRACT_DATA_DIR=/data \
    REFRACT_MEDIA_DIR=/data/media

EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=10 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/openapi.json')" || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
