"""Turn per-stage Job rows into one progress figure, a current step and an ETA.

Pure over plain values so it is exhaustively testable. Weights reflect where the
time actually goes on a long recording: converting the video and transcribing
it dominate; segmenting is instant; labelling is one LLM call.

The ETA extrapolates the running stage from its own rate (elapsed / progress)
and prices the stages still ahead by their weight relative to it. It is
withheld until the running stage has made a little progress, because the first
seconds of an encode (probing, model loading) wildly overstate the remaining time.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable, Protocol

STAGE_WEIGHTS: dict[str, float] = {"media": 0.5, "whisper": 0.3, "merge": 0.02, "extract": 0.18}
STAGE_ORDER = list(STAGE_WEIGHTS)
MIN_PROGRESS_FOR_ETA = 0.03
MIN_ELAPSED_FOR_ETA_S = 10.0


class JobLike(Protocol):
    stage: str
    status: str
    progress: float | None
    message: str | None
    started_at: datetime | None
    updated_at: datetime | None


@dataclass
class Summary:
    progress: float
    stage: str | None
    message: str | None
    elapsed_s: float | None
    eta_s: float | None
    stalled: bool


def _utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)  # SQLite drops the zone


def summarize(jobs: Iterable[JobLike], *, now: datetime | None = None, stale_after_s: float = 180) -> Summary:
    now = now or datetime.now(timezone.utc)
    by_stage = {j.stage: j for j in jobs}
    total = 0.0
    running: JobLike | None = None
    for stage, w in STAGE_WEIGHTS.items():
        j = by_stage.get(stage)
        if j is None:
            continue
        if j.status in ("done", "error"):  # error stages are skipped past (media/whisper degrade)
            total += w
        elif j.status == "running":
            total += w * min(1.0, max(0.0, j.progress or 0.0))
            running = running or j

    first_start = min((s for s in (_utc(j.started_at) for j in by_stage.values()) if s), default=None)
    elapsed = (now - first_start).total_seconds() if first_start else None

    eta = None
    stalled = False
    message = None
    stage = None
    if running is not None:
        stage = running.stage
        message = running.message
        updated = _utc(running.updated_at)
        stalled = bool(updated and (now - updated).total_seconds() > stale_after_s)
        started = _utc(running.started_at)
        p = running.progress or 0.0
        if started and p >= MIN_PROGRESS_FOR_ETA:
            stage_elapsed = (now - started).total_seconds()
            if stage_elapsed >= MIN_ELAPSED_FOR_ETA_S:
                w_run = STAGE_WEIGHTS.get(running.stage, 0.1)
                stage_left = stage_elapsed / p * (1 - p)
                seconds_per_weight = stage_elapsed / p / w_run
                later = STAGE_ORDER[STAGE_ORDER.index(running.stage) + 1:] if running.stage in STAGE_ORDER else []
                ahead = sum(STAGE_WEIGHTS[s] for s in later if (by_stage.get(s) is None or by_stage[s].status != "done"))
                eta = round(stage_left + seconds_per_weight * ahead)
    elif all(by_stage.get(s) and by_stage[s].status in ("done", "error") for s in STAGE_ORDER):
        total = 1.0

    return Summary(progress=round(min(1.0, total), 4), stage=stage, message=message,
                   elapsed_s=round(elapsed, 1) if elapsed is not None else None, eta_s=eta, stalled=stalled)
