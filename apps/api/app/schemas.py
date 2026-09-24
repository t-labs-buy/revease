"""Pydantic request/response models."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

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


class PasswordResetIn(BaseModel):
    """Admin-set password for another account (no current password needed)."""

    new_password: str = Field(min_length=8, max_length=200)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    email: str
    name: str
    role: str | None = "user"  # "user" | "admin" (NULL rows predate the column)
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
    # queued | running | ready | error, or None when no document exists yet.
    document_status: str | None = None
    capture_count: int = 0
    # Populated when the project is someone else's: for admins browsing across
    # spaces, and for collaborators on a project shared with them.
    owner_email: str | None = None
    owner_name: str | None = None
    # True when the caller was invited to edit this project rather than owning it.
    shared_with_me: bool = False


class CollaboratorCreate(BaseModel):
    email: str = Field(min_length=3, max_length=320)


class CollaboratorOut(BaseModel):
    user_id: str
    email: str
    name: str
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
    progress: float | None = None  # 0..1 within this stage
    message: str | None = None
    started_at: datetime | None = None
    updated_at: datetime | None = None


class SessionStatus(BaseModel):
    session_id: str
    status: str
    latest_version: int | None = None
    jobs: list[JobOut] = []
    # Whole-pipeline view for the UI (stages weighted by typical cost).
    progress: float | None = None  # 0..1
    stage: str | None = None  # the stage running now
    message: str | None = None
    elapsed_s: float | None = None
    eta_s: float | None = None  # None until there is enough signal to estimate
    # True when the running stage has not reported for a while (worker busy or gone).
    stalled: bool = False


class ActivityItem(BaseModel):
    kind: Literal["processing", "document", "render"]
    project_id: str
    project_name: str
    status: str
    progress: float | None = None
    message: str | None = None
    href: str
    started_at: datetime | None = None
    updated_at: datetime | None = None


# ---- workflow graph ----
class GraphOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    version: int
    graph_json: dict
    created_at: datetime


# ---- video editor / render ----
class RenderJobOut(BaseModel):
    id: str
    status: str
    output_key: str | None = None
    output_url: str | None = None
    stats_json: dict | None = None
    error_json: dict | None = None
    progress: float | None = None
    message: str | None = None


class VideoSpecOut(BaseModel):
    video_project_id: str
    project_id: str
    graph_version: int
    edit_spec: dict
    source_video: str | None = None  # storage key of the project's raw recording
    # 540p preview copy for the editor/scrubbers (None until processed, or for
    # older recordings — then preview falls back to source_video).
    source_proxy: str | None = None
    latest_render: RenderJobOut | None = None  # newest finished render, shown on open


class EditSpecPatch(BaseModel):
    edit_spec: dict


class DocumentOut(BaseModel):
    document_id: str | None
    project_id: str
    graph_version: int | None
    doc: dict | None
    # none (no row yet) | queued | running | ready | error
    status: str = "ready"
    doc_version: int = 0
    latest_graph_version: int | None = None
    # True when the recording was reprocessed after this doc was generated.
    stale: bool = False
    error: dict | None = None
    progress: float | None = None
    message: str | None = None


class AutoEditStart(BaseModel):
    aggressiveness: Literal["gentle", "balanced", "aggressive"] = "balanced"
    captions: bool = True
    zoom: bool = True


class ShareCreate(BaseModel):
    kind: Literal["video", "doc"] = "video"
    # None = leave as-is when reusing an existing link (a new link defaults to off).
    allow_download: bool | None = None


class ShareUpdate(BaseModel):
    allow_download: bool


class ShareOut(BaseModel):
    token: str
    kind: str
    revoked: bool
    allow_download: bool
    created_at: datetime
    project_id: str


class SharePublic(BaseModel):
    kind: str
    title: str
    project_id: str
    allow_download: bool = False
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


# ---- documents v2 ----
# The editable document model. Text carries only two inline markups — **bold**
# for UI labels and `code` for typed values — and every renderer (web, MD, PDF,
# DOCX) handles exactly those. Step ids equal the graph step id for generated
# steps (so snapshots can be re-grabbed from the recording) and "u_…" for steps
# the user adds. Order is positional: reordering is a list mutation, never a
# renumbering.
_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
STORAGE_KEY_RE = r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,300}$"


def clean_text(value: Any, limit: int) -> str:
    """Strip control characters, collapse runs of spaces and blank lines, cap length.
    Truncates rather than rejects — a too-long body is still the user's text."""
    s = _CTRL.sub("", str(value if value is not None else ""))
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n{3,}", "\n\n", s).strip()
    return s[:limit]


class DocSnapshot(BaseModel):
    # None only while a re-grab is pending and no earlier snapshot existed.
    key: str | None = Field(default=None, pattern=STORAGE_KEY_RE)
    raw_key: str | None = Field(default=None, pattern=STORAGE_KEY_RE)
    t: float | None = Field(default=None, ge=0)  # seconds into the source video
    bbox_norm: list[float] | None = None  # [x, y, w, h] normalised to the frame
    pending: bool = False

    @field_validator("bbox_norm")
    @classmethod
    def _unit_box(cls, v: list[float] | None) -> list[float] | None:
        if v is None:
            return None
        if len(v) != 4:
            raise ValueError("bbox_norm must have 4 numbers")
        return [min(1.0, max(0.0, float(x))) for x in v]


class DocSource(BaseModel):
    graph_step_id: str | None = None
    t_start: float | None = None
    t_end: float | None = None


class DocStepV2(BaseModel):
    id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    title: str = Field(default="", max_length=200)
    body: str = Field(default="", max_length=4000)
    tip: str | None = Field(default=None, max_length=600)
    snapshot: DocSnapshot | None = None
    source: DocSource = Field(default_factory=DocSource)

    @field_validator("title", mode="before")
    @classmethod
    def _clean_title(cls, v: Any) -> str:
        return clean_text(v, 200)

    @field_validator("body", mode="before")
    @classmethod
    def _clean_body(cls, v: Any) -> str:
        return clean_text(v, 4000)

    @field_validator("tip", mode="before")
    @classmethod
    def _clean_tip(cls, v: Any) -> str | None:
        if v is None:
            return None
        t = clean_text(v, 600)
        return t or None


class DocMeta(BaseModel):
    model_config = ConfigDict(extra="allow")

    generated_at: str | None = None
    edited_at: str | None = None
    writer: Literal["llm", "fallback", "legacy"] = "fallback"
    model: str | None = None
    instruction: str | None = Field(default=None, max_length=2000)
    skill_id: str | None = None
    graph_version: int | None = None
    # Steps the model skipped that were filled with mechanical text (observability).
    missing_steps: int | None = None
    snapshots: bool = True


class DocV2(BaseModel):
    version: Literal[2] = 2
    title: str = Field(default="Untitled document", max_length=200)
    overview: str = Field(default="", max_length=4000)
    prerequisites: list[str] = Field(default_factory=list, max_length=20)
    steps: list[DocStepV2] = Field(default_factory=list, max_length=300)
    tips: list[str] = Field(default_factory=list, max_length=20)
    meta: DocMeta = Field(default_factory=DocMeta)

    @field_validator("title", mode="before")
    @classmethod
    def _clean_doc_title(cls, v: Any) -> str:
        return clean_text(v, 200) or "Untitled document"

    @field_validator("overview", mode="before")
    @classmethod
    def _clean_overview(cls, v: Any) -> str:
        return clean_text(v, 4000)

    @field_validator("prerequisites", "tips", mode="before")
    @classmethod
    def _clean_list(cls, v: Any) -> list[str]:
        items = v if isinstance(v, list) else []
        out = [clean_text(x, 300) for x in items if isinstance(x, str)]
        return [x for x in out if x][:20]

    @field_validator("steps")
    @classmethod
    def _unique_ids(cls, v: list[DocStepV2]) -> list[DocStepV2]:
        seen: set[str] = set()
        for s in v:
            if s.id in seen:
                raise ValueError(f"duplicate step id {s.id!r}")
            seen.add(s.id)
        return v


class DocGenerateIn(BaseModel):
    instruction: str | None = Field(default=None, max_length=2000)
    skill_id: str | None = None


class DocPatchIn(BaseModel):
    doc: DocV2


class DocSnapshotIn(BaseModel):
    t: float = Field(ge=0)  # seconds into the source video


# ---- multipart uploads ----
class UploadCreate(BaseModel):
    kind: Literal["raw_video", "audio"] = "raw_video"
    ext: str = Field(pattern=r"^[a-z0-9]{1,5}$")
    size: int = Field(gt=0, le=50 * 1024**3)  # 50 GB ceiling


class UploadOut(BaseModel):
    upload_id: str
    storage_key: str
    size: int
    part_size: int
    part_count: int
    status: str
    parts: list[dict] = []  # [{number, etag, size}] already received


class PartSignIn(BaseModel):
    numbers: list[int] = Field(min_length=1, max_length=100)


class PartDoneIn(BaseModel):
    number: int = Field(ge=1, le=10000)
    etag: str = Field(min_length=1, max_length=200)


class UploadCompleteIn(BaseModel):
    parts: list[PartDoneIn] = Field(min_length=1, max_length=10000)
