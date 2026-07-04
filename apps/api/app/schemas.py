"""Pydantic request/response models."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

# ---- shared ----
SourceType = Literal["extension", "recorder", "upload"]
EventType = Literal["click", "input", "navigation", "scroll", "keydown"]
Bbox = Annotated[list[float], Field(min_length=4, max_length=4)]


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class ProjectOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    favorite: int = 0
    created_at: datetime


class HealthOut(BaseModel):
    status: str = "ok"
    service: str = "refract-api"


# ---- capture sessions ----
class Viewport(BaseModel):
    w: int = Field(gt=0)
    h: int = Field(gt=0)


class SessionCreate(BaseModel):
    project_id: str
    source_type: SourceType
    viewport: Viewport | None = None


class SessionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    source_type: str
    telemetry: str
    status: str
    duration_ms: int | None = None
    trim_start_ms: int | None = None
    trim_end_ms: int | None = None
    poster: str | None = None  # storage_key of a representative frame/screenshot
    created_at: datetime


class SessionTrim(BaseModel):
    start_ms: int = Field(ge=0)
    end_ms: int = Field(ge=0)


class AssetOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    kind: str
    storage_key: str


class SessionDetail(SessionOut):
    assets: list[AssetOut] = []
    event_count: int = 0


class SessionComplete(BaseModel):
    duration_ms: int | None = None


# ---- asset upload (presigned-style) ----
AssetKind = Literal["raw_video", "audio", "screenshot", "frame"]


class AssetRegister(BaseModel):
    kind: AssetKind
    ext: str = Field(default="bin", pattern=r"^[a-z0-9]{1,8}$")
    meta: dict | None = None


class UploadTargetOut(BaseModel):
    asset_id: str
    storage_key: str
    url: str
    method: str = "PUT"


# ---- events ----
class EventIn(BaseModel):
    seq: int = Field(ge=0)
    type: EventType
    t_ms: int = Field(ge=0)
    selector: str | None = None
    text: str | None = None
    bbox: Bbox | None = None
    value_redacted: str | None = None


class EventsIngest(BaseModel):
    events: list[EventIn] = Field(min_length=1)


class EventsIngestOut(BaseModel):
    ingested: int


# ---- pipeline status ----
class JobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    stage: str
    version: int
    status: str
    attempts: int
    error_json: dict | None = None


class SessionStatus(BaseModel):
    session_id: str
    status: str
    latest_version: int | None = None
    jobs: list[JobOut] = []


# ---- workflow graph ----
class GraphOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    version: int
    graph_json: dict
    created_at: datetime


# ---- video editor / render ----
class VideoSpecOut(BaseModel):
    video_project_id: str
    project_id: str
    graph_version: int
    edit_spec: dict
    source_video: str | None = None  # storage key of the project's raw recording


class EditSpecPatch(BaseModel):
    edit_spec: dict


class DocumentOut(BaseModel):
    document_id: str
    project_id: str
    graph_version: int
    doc: dict


class RenderJobOut(BaseModel):
    id: str
    status: str
    output_key: str | None = None
    output_url: str | None = None
    stats_json: dict | None = None
    error_json: dict | None = None


class AutoEditStart(BaseModel):
    aggressiveness: Literal["gentle", "balanced", "aggressive"] = "balanced"
    captions: bool = True
    zoom: bool = True


class ShareCreate(BaseModel):
    kind: Literal["video", "doc"] = "video"


class ShareOut(BaseModel):
    token: str
    kind: str
    revoked: bool
    created_at: datetime
    project_id: str


class SharePublic(BaseModel):
    kind: str
    title: str
    project_id: str
    video_url: str | None = None
    doc: dict | None = None


class AutoEditOut(BaseModel):
    id: str
    status: str
    output_key: str | None = None
    output_url: str | None = None
    stats_json: dict | None = None
    error_json: dict | None = None
