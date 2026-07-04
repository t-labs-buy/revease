"""Langfuse tracing setup.

Best-practice observability for our LLM calls (Anthropic): we auto-instrument the
Anthropic SDK with OpenTelemetry so every `messages.create` is captured as a
generation (model, tokens, input/output, latency), and expose the Langfuse
`@observe` decorator to wrap our feature functions into named, filterable traces.

Everything degrades to a no-op when Langfuse isn't configured (no
LANGFUSE_PUBLIC_KEY), so the app runs unchanged without it. Import order matters:
`init_tracing()` must run before the Anthropic client is used.
"""

from __future__ import annotations

import logging
import os
from contextlib import contextmanager

log = logging.getLogger("refract.tracing")

_initialized = False
_enabled = False


def _load_env() -> None:
    """Load LANGFUSE_* from the repo-root .env into os.environ (pydantic-settings
    only populates our REFRACT_* Settings object, not the process env that the
    Langfuse SDK reads). Then map BASE_URL -> HOST for the SDK."""
    try:
        from dotenv import load_dotenv

        from app.config import REPO_ROOT

        load_dotenv(REPO_ROOT / ".env")
    except Exception as e:  # pragma: no cover
        log.debug("dotenv load skipped: %s", e)
    base = os.environ.get("LANGFUSE_BASE_URL")
    if base and not os.environ.get("LANGFUSE_HOST"):
        os.environ["LANGFUSE_HOST"] = base


def init_tracing() -> bool:
    """Initialize Langfuse + Anthropic auto-instrumentation once. Returns whether
    tracing is enabled. Safe to call multiple times / when Langfuse is absent."""
    global _initialized, _enabled
    if _initialized:
        return _enabled
    _initialized = True

    _load_env()
    if not os.environ.get("LANGFUSE_PUBLIC_KEY"):
        log.info("Langfuse not configured (no LANGFUSE_PUBLIC_KEY) — tracing disabled.")
        return False

    try:
        from langfuse import get_client

        client = get_client()  # sets up the Langfuse OTEL tracer provider

        from opentelemetry.instrumentation.anthropic import AnthropicInstrumentor

        AnthropicInstrumentor().instrument()

        if client.auth_check():
            log.info("Langfuse tracing enabled (Anthropic auto-instrumented).")
            _enabled = True
        else:
            log.warning("Langfuse auth check failed — verify keys/host; tracing off.")
    except Exception as e:  # pragma: no cover - env dependent
        log.warning("Langfuse init failed (%s); continuing without tracing.", e)
    return _enabled


def flush() -> None:
    """Flush buffered traces (best-effort) — useful on shutdown / short-lived jobs."""
    if not _enabled:
        return
    try:
        from langfuse import get_client

        get_client().flush()
    except Exception:  # pragma: no cover
        pass


# --- decorator / attribute helpers that no-op when Langfuse isn't installed ---
try:  # real implementations
    from langfuse import observe, propagate_attributes  # type: ignore  # noqa: F401
except Exception:  # pragma: no cover - fallback keeps call sites clean

    def observe(*d_args, **d_kwargs):  # type: ignore
        if d_args and callable(d_args[0]):
            return d_args[0]

        def deco(fn):
            return fn

        return deco

    @contextmanager
    def propagate_attributes(**_kwargs):  # type: ignore
        yield
