"""Refract V1 API entrypoint."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.db import init_db
from app.routers import (
    auto_record,
    autoedit,
    documents,
    graphs,
    kb,
    media,
    packages,
    projects,
    rewrite,
    sessions,
    shares,
    skills,
    video,
    voices,
)
from app.schemas import HealthOut


@asynccontextmanager
async def lifespan(app: FastAPI):
    from app.tracing import init_tracing

    init_tracing()  # Langfuse + Anthropic auto-instrumentation (no-op if unconfigured)
    init_db()
    yield


app = FastAPI(title="Refract API", version="0.1.0", lifespan=lifespan)

_settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in _settings.cors_origins.split(",") if o.strip()],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(projects.router)
app.include_router(sessions.router)
app.include_router(auto_record.router)
app.include_router(graphs.router)
app.include_router(video.router)
app.include_router(documents.router)
app.include_router(autoedit.router)
app.include_router(voices.router)
app.include_router(shares.router)
app.include_router(media.router)
app.include_router(rewrite.router)
app.include_router(skills.router)
app.include_router(kb.router)
app.include_router(packages.router)


@app.get("/healthz", response_model=HealthOut)
def healthz() -> HealthOut:
    return HealthOut()
