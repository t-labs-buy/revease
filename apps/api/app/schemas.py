"""Pydantic request/response models."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field

# ---- shared ----
SourceType = Literal["extension", "recorder", "upload", "auto"]
EventType = Literal["click", "input", "navigation", "scroll", "keydown"]
Bbox = Annotated[list[float], Field(min_length=4, max_length=4)]


# ---- auth ----
class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=200)
    name: str = Field(default="", max_length=120)


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=200)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    email: str
    name: str
    created_at: datetime


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int  # seconds until the token expires
    user: UserOut


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class ProjectOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    favorite: int = 0
    created_at: datetime
    # Whether a step-by-step doc has actually been generated for this project, so
    # the UI can label it truthfully instead of guessing from capture counts.
    has_document: bool = False
    capture_count: int = 0


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


# ---- auto record (AI-driven tab recording) ----
# The action the agent asks the extension to perform on the tab. Loggable actions
# (click/input/navigation/scroll/keydown) become Workflow Graph steps; wait/done/
# fail are control flow only.
AgentActionName = Literal[
    "click", "input", "scroll", "navigate", "keydown", "wait", "done", "fail"
]


class AutoRecordCreate(BaseModel):
    project_id: str
    coverage_plan: str = Field(min_length=1)  # newline / bullet list of items
    transcript: str = ""
    start_url: str | None = None
    max_steps: int = Field(default=60, ge=1, le=300)
    viewport: Viewport | None = None


class PlanItemOut(BaseModel):
    id: str
    text: str
    status: str  # pending | active | done


class AutoRecordRunOut(BaseModel):
    run_id: str
    session_id: str
    project_id: str
    status: str
    plan: list[PlanItemOut] = []
    current_plan_item: str | None = None
    step_count: int = 0
    max_steps: int = 60
    error: dict | None = None
    session_status: SessionStatus | None = None  # embedded pipeline progress once processing


class ObservationElement(BaseModel):
    ref: str
    tag: str | None = None
    role: str | None = None
    text: str | None = None
    value: str | None = None
    selector: str | None = None
    bbox: Bbox | None = None
    disabled: bool = False


class Observation(BaseModel):
    url: str | None = None
    title: str | None = None
    scroll_y: float | None = None
    scroll_max: float | None = None
    elements: list[ObservationElement] = []
    screenshot_b64: str | None = None  # jpeg base64 (no data: prefix)


class ActionResult(BaseModel):
    """The extension's report of how the PRIOR decision executed."""

    index: int
    ok: bool
    error: str | None = None
    selector: str | None = None
    bbox: Bbox | None = None
    t_ms: int | None = None


class AgentStepIn(BaseModel):
    expected_index: int = Field(ge=0)  # must equal run.step_count (idempotency)
    observation: Observation
    results: list[ActionResult] = []  # outcomes of the prior decision(s)


class AgentAction(BaseModel):
    index: int
    action: AgentActionName
    ref: str | None = None
    text: str | None = None
    url: str | None = None
    key: str | None = None
    wait_ms: int | None = None
    scroll_to: Literal["up", "down"] | None = None
    clear: bool = False
    press_enter: bool = False
    # semantic labels (used to build the graph + anchor narration)
    target: str | None = None
    intent: str | None = None
    screen_name: str | None = None
    plan_item_id: str | None = None


class AgentStepOut(BaseModel):
    action: AgentAction
    done: bool = False
    progress_note: str | None = None
    plan: list[PlanItemOut] = []
    step_count: int
