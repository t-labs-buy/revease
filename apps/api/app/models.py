"""SQLAlchemy models.

Every user gets their own private space: the four top-level entities a user can
create (Project, Skill, KbArticle, BrandPackage) carry a `user_id` owner, and
everything else hangs off a Project, so ownership is reachable for any row.

`user_id` is nullable at the DB level only because SQLite's ADD COLUMN cannot add
a NOT NULL column to an existing table — the API always sets it. Rows that predate
auth therefore read as ownerless and belong to nobody; `app.purge` removes them."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def _uuid() -> str:
    return uuid.uuid4().hex


def _now() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    """An account. `email` is stored lower-cased and is the login identifier."""

    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    email: Mapped[str] = mapped_column(String, unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String, default="")
    password_hash: Mapped[str] = mapped_column(String, nullable=False)
    # "user" | "admin". Admins can see every user's space. Nullable at the DB
    # level only because SQLite's ADD COLUMN backfill needs it (see module
    # docstring); treat NULL as "user" via `is_admin`.
    role: Mapped[str | None] = mapped_column(String, default="user", server_default="user")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    # Present on every other mutable row here, and required by `users` tables
    # created before this model existed (that column is NOT NULL with no default,
    # so omitting it makes every INSERT fail against such a database).
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )

    @property
    def is_admin(self) -> bool:
        return (self.role or "user") == "admin"


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), index=True, nullable=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    favorite: Mapped[int] = mapped_column(Integer, default=0)  # 0/1 — starred/pinned
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    sessions: Mapped[list["CaptureSession"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    graphs: Mapped[list["WorkflowGraphRow"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )


class CaptureSession(Base):
    __tablename__ = "capture_sessions"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    source_type: Mapped[str] = mapped_column(String, nullable=False)  # extension|recorder|upload
    telemetry: Mapped[str] = mapped_column(String, default="absent")  # present|absent
    status: Mapped[str] = mapped_column(String, default="created")
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    trim_start_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    trim_end_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    keep_ranges_json: Mapped[list | None] = mapped_column(JSON, nullable=True)  # [[startMs,endMs],…]
    viewport_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    project: Mapped[Project] = relationship(back_populates="sessions")
    assets: Mapped[list["MediaAsset"]] = relationship(
        back_populates="session", cascade="all, delete-orphan"
    )
    events: Mapped[list["Event"]] = relationship(
        back_populates="session", cascade="all, delete-orphan"
    )


class AutoRecordRun(Base):
    """An AI-driven Auto Record session: the agent drives the user's browser tab
    (via the extension + CDP) through a coverage plan while the tab is recorded.

    One run maps 1:1 to a CaptureSession (source_type="auto"). The `agent_log_json`
    is the authoritative source for the Workflow Graph — the agent knows each step's
    action/target/intent/screen at decision time, so no LLM extraction is needed."""

    __tablename__ = "autorecord_runs"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("capture_sessions.id"), index=True)
    # created|driving|capture_done|processing|ready|failed|aborted
    status: Mapped[str] = mapped_column(String, default="created")
    start_url: Mapped[str | None] = mapped_column(String, nullable=True)
    # [{ "id": "p1", "text": "...", "status": "pending|active|done" }, …]
    coverage_plan_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    transcript_text: Mapped[str] = mapped_column(Text, default="")
    # ordered decisions: [{ index, action, ref, target, intent, screen_name,
    #   plan_item_id, reason, ok, selector, bbox, t_ms, error }, …]
    agent_log_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    current_plan_item: Mapped[str | None] = mapped_column(String, nullable=True)
    step_count: Mapped[int] = mapped_column(Integer, default=0)
    max_steps: Mapped[int] = mapped_column(Integer, default=60)
    error_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )


class Event(Base):
    """A captured user action (click/input/navigation/...) on the session timeline.
    `value_redacted` never holds raw password/PII values — masking happens at capture."""

    __tablename__ = "events"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    session_id: Mapped[str] = mapped_column(ForeignKey("capture_sessions.id"), index=True)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    type: Mapped[str] = mapped_column(String, nullable=False)  # click|input|navigation|scroll|keydown
    selector: Mapped[str | None] = mapped_column(String, nullable=True)
    text: Mapped[str | None] = mapped_column(Text, nullable=True)
    bbox_json: Mapped[list[float] | None] = mapped_column(JSON, nullable=True)  # [x,y,w,h]
    value_redacted: Mapped[str | None] = mapped_column(String, nullable=True)
    t_ms: Mapped[int] = mapped_column(Integer, nullable=False)

    session: Mapped["CaptureSession"] = relationship(back_populates="events")


class MediaAsset(Base):
    __tablename__ = "media_assets"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    session_id: Mapped[str] = mapped_column(ForeignKey("capture_sessions.id"), index=True)
    kind: Mapped[str] = mapped_column(String, nullable=False)  # raw_video|audio|screenshot|frame
    storage_key: Mapped[str] = mapped_column(String, nullable=False)
    meta_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    session: Mapped[CaptureSession] = relationship(back_populates="assets")


class WorkflowGraphRow(Base):
    __tablename__ = "workflow_graphs"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    graph_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    project: Mapped[Project] = relationship(back_populates="graphs")


class Transcript(Base):
    __tablename__ = "transcripts"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    session_id: Mapped[str] = mapped_column(ForeignKey("capture_sessions.id"), index=True)
    # words_json: [{"w": "hello", "t_start": 0.0, "t_end": 0.4}, ...]
    words_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    text: Mapped[str | None] = mapped_column(Text, nullable=True)
    provider: Mapped[str] = mapped_column(String, default="none")


class VideoProject(Base):
    """The editable video layer over a Workflow Graph — scenes, per-step script,
    filler removal, zooms, captions, music, aspect. One per project (V1)."""

    __tablename__ = "video_projects"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    graph_version: Mapped[int] = mapped_column(Integer, nullable=False)
    edit_spec_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )


class AutoEditJob(Base):
    """A 'smart' render of the original recording: silent stretches sped up,
    motion regions zoomed. Independent of the step-based studio render."""

    __tablename__ = "autoedit_jobs"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    status: Mapped[str] = mapped_column(String, default="pending")
    options_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    output_key: Mapped[str | None] = mapped_column(String, nullable=True)
    stats_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    error_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )


class Share(Base):
    """A public, tokenized link to a project's rendered video or generated doc."""

    __tablename__ = "shares"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    token: Mapped[str] = mapped_column(String, unique=True, index=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    kind: Mapped[str] = mapped_column(String, default="video")  # video | doc
    revoked: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Document(Base):
    """A generated step-by-step doc (SOP) derived from a Workflow Graph."""

    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    graph_version: Mapped[int] = mapped_column(Integer, nullable=False)
    doc_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )


class RenderJob(Base):
    __tablename__ = "render_jobs"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    video_project_id: Mapped[str] = mapped_column(ForeignKey("video_projects.id"), index=True)
    status: Mapped[str] = mapped_column(String, default="pending")
    output_key: Mapped[str | None] = mapped_column(String, nullable=True)
    stats_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    error_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    session_id: Mapped[str] = mapped_column(ForeignKey("capture_sessions.id"), index=True)
    stage: Mapped[str] = mapped_column(String, nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=0)  # pipeline run version
    status: Mapped[str] = mapped_column(String, default="pending")
    error_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )


class Skill(Base):
    """A reusable generation preset that shapes how AI produces a Video or Doc
    (voice, tone, aspect, captions, zoom). Applied to a project to pre-fill its
    edit-spec."""

    __tablename__ = "skills"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), index=True, nullable=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    target: Mapped[str] = mapped_column(String, default="video")  # "video" | "doc"
    settings_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class KbArticle(Base):
    """A Knowledge Base entry — a guide/doc that's searchable and shareable."""

    __tablename__ = "kb_articles"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), index=True, nullable=True)
    title: Mapped[str] = mapped_column(String, nullable=False)
    summary: Mapped[str] = mapped_column(Text, default="")
    body_md: Mapped[str] = mapped_column(Text, default="")
    tags_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    project_id: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class BrandPackage(Base):
    """A reusable brand kit — company intro/outro, logo, fonts, colours. A skill can
    reference a package by name to brand the generated video/doc."""

    __tablename__ = "brand_packages"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), index=True, nullable=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    settings_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
