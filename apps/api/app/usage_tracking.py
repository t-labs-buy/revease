"""Business usage spans for Usage Tracker — one span = one business action.

A span counts as usage only if it carries `usage.feature`; Usage Tracker ignores
everything else. Instrumented code calls exactly one helper, `track` (or its
decorator form `tracked`), so the attribute contract lives in one place:

    @tracked("project", "create_project", "project.created", "project", entity_id=lambda p: p.id)
    def create_project(payload, user: CurrentUser, ...): ...

    with track("video", "render_video", "video.rendered", "render_job") as u:
        u.identify(email); ...; u.entity(job.id); u.set(aspect="16:9")

Why the design looks like this:

- **Own TracerProvider, never the global one.** Langfuse installs the global
  provider for its Anthropic generations. Sharing it would ship LLM spans to
  Usage Tracker and usage spans to Langfuse. Langfuse passes its exporter an
  explicit endpoint + headers, so the `OTEL_EXPORTER_OTLP_*` vars below (which
  carry the Usage Tracker key) are read only by our exporter.
- **Configured only through standard OTEL_* env vars** (service name, resource
  attributes, endpoint, headers, sampler, batch delay). Off when
  `OTEL_EXPORTER_OTLP_ENDPOINT` is unset or `OTEL_SDK_DISABLED=true`, so local
  dev and the test suite export nothing unless asked to.
- **Never fails or slows the action.** Export is batched on a background thread;
  every telemetry call is wrapped so a tracing bug degrades to "not counted".
  The action's own exception is always re-raised, after marking the span
  `usage.result=failure`.
- **Usage attributes are set at the end**, once the entity id is known. A body
  that decides the action did not really happen (e.g. an existing share link
  was reused) calls `skip()`: the span then ends without `usage.*` and is not
  counted.
- **Never sampled away.** If the ambient trace is unsampled the usage span
  starts as a new root, so `parentbased_always_on` cannot drop usage.
- **Fork-safe.** The provider is built lazily per process and discarded in a
  forked child (Celery prefork), whose batch thread would otherwise be dead.
- **Failures say why, decided in one place.** Usage Tracker groups failures by
  `usage.error.code`, so the code ↔ category/handled/message table (`ERRORS`)
  and the exception → code mapping (`_classify`) live here, not at throw sites.
  A body names a specific rule with `failed("CODE")` (before raising, or for a
  failure it records on a row without raising) or hands over the exception it
  caught with `failed(exc=e)`. The message is the table's fixed sentence, never
  the exception text, which can carry user content — for the same reason the
  recorded exception event keeps the class and stack frames but not the message.

Only `user.id` (the login e-mail) is personal. Never pass payloads, prompts,
completions, file names or free text as attributes — ids, enums and counts only.
"""

from __future__ import annotations

import contextvars
import functools
import inspect
import logging
import os
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

log = logging.getLogger("refract.usage_tracking")

_MAX_EXTRA = 16  # Usage Tracker keeps at most 16 extra usage.* attributes per span
_TRACER_NAME = "refract.usage"

# code -> (category, handled, message). category: user (they can fix it) |
# system (our bug or our setup) | external (a dependency failed). handled: the
# code anticipated it and rejected/recorded on purpose. Codes are the grouping
# key on the dashboard — add new ones, never rename.
ERRORS: dict[str, tuple[str, bool, str]] = {
    "INVALID_REQUEST": ("user", True, "The request was rejected as invalid."),
    "UNAUTHENTICATED": ("user", True, "The user is not signed in."),
    "FORBIDDEN": ("user", True, "The user may not perform this action."),
    "NOT_FOUND": ("user", True, "The target does not exist or is not the user's."),
    "RUN_IN_PROGRESS": ("user", True, "The recording is still being processed."),
    "FILE_TOO_LARGE": ("user", True, "The file exceeds the size limit."),
    "PAYLOAD_INVALID": ("user", True, "The request payload failed validation."),
    "SOURCE_MISSING": ("user", True, "The source recording is no longer available."),
    "NO_SOURCE_VIDEO": ("user", True, "The project has no source video."),
    "IMAGE_MISSING": ("user", True, "The image to process is missing."),
    "AI_PROVIDER_FAILED": ("external", True, "The AI provider call failed."),
    "AI_PROVIDER_ERROR": ("external", False, "The AI provider raised an unexpected error."),
    "AI_EMPTY_RESULT": ("external", True, "The AI returned no usable output."),
    "AI_NOT_CONFIGURED": ("system", True, "No AI provider key is configured."),
    "AUTORECORD_FAILED": ("external", True, "The Auto Record agent reported a failed run."),
    "FFMPEG_FAILED": ("external", True, "The media encoder failed."),
    "FFMPEG_TIMEOUT": ("external", True, "The media encoder timed out."),
    "JOB_TIMEOUT": ("system", False, "The background job hit its time limit."),
    "PROCESSING_FAILED": ("system", True, "Processing the media failed."),
    "UNEXPECTED_ERROR": ("system", False, "An unexpected error occurred."),
}

_HTTP_CODES = {
    400: "INVALID_REQUEST", 401: "UNAUTHENTICATED", 403: "FORBIDDEN", 404: "NOT_FOUND",
    409: "RUN_IN_PROGRESS", 413: "FILE_TOO_LARGE", 422: "PAYLOAD_INVALID",
    502: "AI_PROVIDER_FAILED",  # every tracked 502 wraps an AI provider failure
}

# usage.error.stage when the body doesn't name one: from the event's verb.
_STAGE_BY_VERB = {
    "created": "create", "deleted": "delete", "added": "create", "revoked": "delete",
    "completed": "capture", "reprocessed": "extract", "started": "execute", "finished": "execute",
    "generated": "generate", "rewritten": "generate", "suggested": "generate",
    "rendered": "render", "auto_edited": "render", "regrabbed": "extract",
    "exported": "export", "uploaded": "load", "imported": "load",
    "background_removed": "transform",
}

_lock = threading.Lock()
_provider: Any = None  # TracerProvider | False (disabled) | None (not built yet)
_current: contextvars.ContextVar[UsageSpan | None] = contextvars.ContextVar(
    "usage_span", default=None
)


# --------------------------------------------------------------------------- #
# provider
# --------------------------------------------------------------------------- #
def _enabled_by_env() -> bool:
    try:
        from dotenv import load_dotenv

        from app.config import REPO_ROOT

        load_dotenv(REPO_ROOT / ".env")  # never overrides vars already set
    except Exception:  # pragma: no cover
        pass
    if os.environ.get("OTEL_SDK_DISABLED", "").strip().lower() == "true":
        return False
    return bool(os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT"))


def _build_provider() -> Any:
    if not _enabled_by_env():
        log.info("Usage tracking off (no OTEL_EXPORTER_OTLP_ENDPOINT).")
        return False
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    # Resource.create() reads OTEL_SERVICE_NAME + OTEL_RESOURCE_ATTRIBUTES; the
    # sampler comes from OTEL_TRACES_SAMPLER; exporter and batch settings from
    # their OTEL_* vars.
    provider = TracerProvider(resource=Resource.create())
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    log.info("Usage tracking on -> %s", os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT"))
    return provider


def _get_tracer() -> Any:
    global _provider
    if _provider is None:
        with _lock:
            if _provider is None:
                try:
                    _provider = _build_provider()
                except Exception:
                    log.warning("usage tracking init failed; disabled", exc_info=True)
                    _provider = False
    return _provider.get_tracer(_TRACER_NAME) if _provider else None


def init_usage_tracking() -> None:
    """Build the provider now (API startup, each Celery child) so the first
    tracked request doesn't pay the SDK import + exporter setup."""
    _get_tracer()


def set_provider(provider: Any) -> None:
    """Install a specific TracerProvider (tests use one with an in-memory exporter)."""
    global _provider
    _provider = provider


def flush(timeout_ms: int = 5000) -> None:
    """Export what is buffered — call on worker-process shutdown. Never raises."""
    try:
        if _provider:
            _provider.force_flush(timeout_ms)
    except Exception:  # pragma: no cover
        log.debug("usage flush failed", exc_info=True)


def _reset_after_fork() -> None:
    global _provider
    _provider = None


if hasattr(os, "register_at_fork"):
    os.register_at_fork(after_in_child=_reset_after_fork)


# --------------------------------------------------------------------------- #
# the span handle
# --------------------------------------------------------------------------- #
class UsageSpan:
    """What instrumented code may say about its action. Every method is a no-op
    safe call; nothing here can raise into the caller."""

    def __init__(self, feature: str, action: str, event: str, entity_type: str) -> None:
        self.feature, self.action, self.event, self.entity_type = (
            feature, action, event, entity_type,
        )
        self.entity_id: str | None = None
        self.user_email: str | None = None
        self.session_id: str | None = None
        self.result = "success"
        self.extra: dict[str, Any] = {}
        self.skipped = False
        self.error_code: str | None = None
        self.error_exc: BaseException | None = None
        self.error_stage: str | None = None
        self.error_target: str | None = None

    def entity(self, entity_id: Any) -> UsageSpan:
        if entity_id is not None:
            self.entity_id = str(entity_id)
        return self

    def identify(self, user_email: str | None, session_id: str | None = None) -> UsageSpan:
        if user_email:
            self.user_email = user_email
        if session_id:
            self.session_id = session_id
        return self

    def set(self, **attrs: Any) -> UsageSpan:
        """Feature-specific facts, e.g. set(format="pdf") -> usage.format. None is dropped."""
        for k, v in attrs.items():
            if v is not None:
                self.extra[k] = v
        return self

    def item_count(self, n: int | None) -> UsageSpan:
        return self.set(item_count=n)

    def cancelled(self) -> UsageSpan:
        self.result = "cancelled"
        return self

    def failed(
        self,
        code: str | None = None,
        *,
        exc: BaseException | None = None,
        stage: str | None = None,
        target: str | None = None,
    ) -> UsageSpan:
        """Mark the action failed and say why. `code` is a key of `ERRORS`;
        without one the code comes from `exc` (or, if the action then raises,
        from that exception). Call it before raising to name the specific rule."""
        self.result = "failure"
        if code:
            self.error_code = code
        if exc is not None:
            self.error_exc = exc
        if stage:
            self.error_stage = stage
        if target:
            self.error_target = target
        return self

    def error_attributes(self, exc: BaseException | None) -> dict[str, Any]:
        """The `usage.error.*` facts for a failed span."""
        exc = exc or self.error_exc
        code = self.error_code or (_classify(exc) if exc is not None else "UNEXPECTED_ERROR")
        category, handled, message = ERRORS.get(code, ERRORS["UNEXPECTED_ERROR"])
        stage = self.error_stage
        if stage is None:
            status = getattr(exc, "status_code", None)
            if isinstance(status, int) and 400 <= status < 500:
                stage = "validate"  # rejected before any work was done
            else:
                verb = self.event.split(".", 1)[-1]
                stage = _STAGE_BY_VERB.get(verb, "execute")
        attrs = {
            "usage.error.code": code,
            "usage.error.category": category,
            "usage.error.handled": handled,
            "usage.error.stage": stage,
            "usage.error.target": self.error_target or self.entity_type,
            "usage.error.message": message,
        }
        if exc is not None:
            attrs["error.type"] = type(exc).__name__
        return attrs

    def skip(self) -> UsageSpan:
        """The action did not really happen; end the span without usage attributes."""
        self.skipped = True
        return self

    def attributes(self) -> dict[str, Any]:
        attrs: dict[str, Any] = {
            "usage.feature": self.feature,
            "usage.action": self.action,
            "usage.event.name": self.event,
            "usage.entity.type": self.entity_type,
            "usage.result": self.result,
        }
        if self.entity_id:
            attrs["usage.entity.id"] = self.entity_id
        if self.user_email:
            attrs["user.id"] = self.user_email
        if self.session_id:
            attrs["session.id"] = self.session_id
        for k, v in list(self.extra.items())[:_MAX_EXTRA]:
            if isinstance(v, bool | int | float):
                attrs[f"usage.{k}"] = v
            else:
                attrs[f"usage.{k}"] = str(v)[:64]
        return attrs


class _NoopSpan(UsageSpan):
    def __init__(self) -> None:
        super().__init__("", "", "", "")


def current() -> UsageSpan:
    """The usage span of the action running in this context (no-op if none), so a
    `@tracked` function body can add facts without threading a handle through."""
    return _current.get() or _NoopSpan()


def identity_of(user: Any) -> tuple[str | None, str | None]:
    """(login e-mail, session id) for a `CurrentUser` — see `app.auth.get_current_user`."""
    if user is None:
        return None, None
    return getattr(user, "email", None), getattr(user, "usage_session_id", None)


def email_for_user_id(db: Any, user_id: str | None) -> str | None:
    """Worker-side identity: jobs carry an owner id, Usage Tracker wants the login."""
    if not user_id:
        return None
    try:
        from app.models import User

        u = db.get(User, user_id)
        return u.email if u else None
    except Exception:
        return None


# --------------------------------------------------------------------------- #
# the helper
# --------------------------------------------------------------------------- #
def _classify(exc: BaseException) -> str:
    """Exception -> `ERRORS` code. Matched by class name / module so this module
    imports neither FastAPI, Celery nor the AI SDKs."""
    name = type(exc).__name__
    module = type(exc).__module__ or ""
    status = getattr(exc, "status_code", None)
    if name == "HTTPException" and isinstance(status, int):
        return _HTTP_CODES.get(status, "INVALID_REQUEST" if status < 500 else "UNEXPECTED_ERROR")
    if name in ("RequestValidationError", "ValidationError"):
        return "PAYLOAD_INVALID"
    if name == "FFmpegError":
        return "FFMPEG_FAILED"
    if name == "TimeoutExpired":
        return "FFMPEG_TIMEOUT"
    if name in ("SoftTimeLimitExceeded", "TimeLimitExceeded"):
        return "JOB_TIMEOUT"
    if module.split(".", 1)[0] in ("anthropic", "openai", "httpx"):
        return "AI_PROVIDER_ERROR"
    return "UNEXPECTED_ERROR"


def _record_exception(span: Any, exc: BaseException) -> None:
    """span.record_exception without the message (it can hold user content).
    Frames are locations only — a frame's source line can carry a literal."""
    import traceback

    frames = "".join(
        f'  File "{f.filename}", line {f.lineno}, in {f.name}\n'
        for f in traceback.extract_tb(exc.__traceback__)
    )
    span.record_exception(
        exc,
        attributes={
            "exception.message": type(exc).__name__,
            "exception.stacktrace": f"{frames}{type(exc).__name__}",
        },
    )


def _start(tracer: Any, event: str) -> Any:
    from opentelemetry import context as otel_context
    from opentelemetry import trace
    from opentelemetry.trace import SpanKind

    parent = trace.get_current_span().get_span_context()
    # An unsampled ambient trace must not drop usage: start a new root instead.
    ctx = otel_context.Context() if parent.is_valid and not parent.trace_flags.sampled else None
    return tracer.start_span(f"usage {event}", context=ctx, kind=SpanKind.INTERNAL)


@contextmanager
def track(
    feature: str,
    action: str,
    event: str,
    entity_type: str,
    *,
    user: Any = None,
    entity_id: Any = None,
    **extra: Any,
) -> Iterator[UsageSpan]:
    """Wrap one business action in one INTERNAL usage span. Re-raises whatever
    the action raises, after recording `usage.result=failure`."""
    handle = UsageSpan(feature, action, event, entity_type)
    handle.entity(entity_id).set(**extra).identify(*identity_of(user))
    span = None
    try:
        tracer = _get_tracer()
        if tracer is not None:
            span = _start(tracer, event)
    except Exception:
        log.debug("usage span start failed", exc_info=True)
    token = _current.set(handle)
    try:
        yield handle
    except BaseException as exc:
        _current.reset(token)
        handle.result = "failure"
        _finish(span, handle, exc)
        raise
    _current.reset(token)
    _finish(span, handle, None)


def _finish(span: Any, handle: UsageSpan, exc: BaseException | None) -> None:
    if span is None:
        return
    try:
        from opentelemetry.trace import Status, StatusCode

        if not handle.skipped:
            span.set_attributes(handle.attributes())
            if handle.result == "failure":
                span.set_attributes(handle.error_attributes(exc))
                span.set_status(Status(StatusCode.ERROR))
                recorded = exc or handle.error_exc
                if recorded is not None:
                    _record_exception(span, recorded)
    except Exception:
        log.debug("usage span finish failed", exc_info=True)
    finally:
        try:
            span.end()
        except Exception:
            pass


def tracked(
    feature: str,
    action: str,
    event: str,
    entity_type: str,
    *,
    entity_id: str | Callable[[Any], Any] | None = None,
) -> Callable:
    """Decorator form of `track` for route handlers. Identity comes from the
    handler's `user` argument (a `CurrentUser`). `entity_id` is either the name
    of a handler argument holding the id, or a function of the return value.
    The wrapper keeps the signature, so FastAPI still sees the real parameters."""

    def deco(fn: Callable) -> Callable:
        sig = inspect.signature(fn)

        def _args(args: tuple, kwargs: dict) -> dict:
            try:
                return dict(sig.bind_partial(*args, **kwargs).arguments)
            except TypeError:
                return dict(kwargs)

        def _resolve(u: UsageSpan, bound: dict, result: Any) -> None:
            try:
                if isinstance(entity_id, str):
                    u.entity(bound.get(entity_id))
                elif entity_id is not None and u.entity_id is None:
                    u.entity(entity_id(result))
            except Exception:
                log.warning("usage entity id unresolved for %s", event, exc_info=True)

        if inspect.iscoroutinefunction(fn):

            @functools.wraps(fn)
            async def awrapper(*args: Any, **kwargs: Any) -> Any:
                bound = _args(args, kwargs)
                with track(feature, action, event, entity_type, user=bound.get("user")) as u:
                    if isinstance(entity_id, str):
                        _resolve(u, bound, None)
                    result = await fn(*args, **kwargs)
                    _resolve(u, bound, result)
                    return result

            return awrapper

        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            bound = _args(args, kwargs)
            with track(feature, action, event, entity_type, user=bound.get("user")) as u:
                if isinstance(entity_id, str):
                    _resolve(u, bound, None)
                result = fn(*args, **kwargs)
                _resolve(u, bound, result)
                return result

        return wrapper

    return deco
