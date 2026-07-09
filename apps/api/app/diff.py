"""Project memory: diff two Workflow Graph versions and migrate the edit-spec so a
re-record only regenerates the changed sections while preserving user edits on the
unchanged ones (master §1 moat: 'record once, diff, only changed sections regenerate')."""

from __future__ import annotations

from typing import Any

from app.editspec import build_edit_spec


def _sig(step: dict[str, Any]) -> str:
    """Identity of a step for matching across versions (ignores narration wording)."""
    action = (step.get("action") or "").strip().lower()
    target = (step.get("target") or "").strip().lower()
    selector = (step.get("selector") or "").strip().lower()
    return f"{action}|{target}|{selector}"


def _lcs_pairs(a: list[str], b: list[str]) -> list[tuple[int, int]]:
    """Longest common subsequence of two signature lists -> matched (i, j) index pairs."""
    n, m = len(a), len(b)
    dp = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n - 1, -1, -1):
        for j in range(m - 1, -1, -1):
            dp[i][j] = dp[i + 1][j + 1] + 1 if a[i] == b[j] else max(dp[i + 1][j], dp[i][j + 1])
    pairs: list[tuple[int, int]] = []
    i = j = 0
    while i < n and j < m:
        if a[i] == b[j]:
            pairs.append((i, j))
            i += 1
            j += 1
        elif dp[i + 1][j] >= dp[i][j + 1]:
            i += 1
        else:
            j += 1
    return pairs


def diff_graphs(old: dict[str, Any], new: dict[str, Any]) -> dict[str, Any]:
    """Per-new-step status (added | changed | unchanged) + removed old steps."""
    o = old.get("steps", [])
    n = new.get("steps", [])
    matched = _lcs_pairs([_sig(s) for s in o], [_sig(s) for s in n])
    new_to_old = {j: i for i, j in matched}
    matched_old = {i for i, _ in matched}

    steps = []
    for j, ns in enumerate(n):
        if j in new_to_old:
            os = o[new_to_old[j]]
            same = (ns.get("narration") or "").strip() == (os.get("narration") or "").strip()
            steps.append(
                {
                    "id": ns["id"],
                    "old_id": os["id"],
                    "status": "unchanged" if same else "changed",
                    "target": ns.get("target"),
                }
            )
        else:
            steps.append({"id": ns["id"], "old_id": None, "status": "added", "target": ns.get("target")})

    removed = [
        {"id": o[i]["id"], "target": o[i].get("target")}
        for i in range(len(o))
        if i not in matched_old
    ]
    summary = {
        "added": sum(1 for s in steps if s["status"] == "added"),
        "changed": sum(1 for s in steps if s["status"] == "changed"),
        "unchanged": sum(1 for s in steps if s["status"] == "unchanged"),
        "removed": len(removed),
    }
    return {
        "from_version": old.get("version"),
        "to_version": new.get("version"),
        "steps": steps,
        "removed": removed,
        "summary": summary,
    }


CARRY_KEYS = (
    "voice", "aspect", "intro", "outro", "captions", "music", "title",
    # user-level look/timing settings must survive a reprocess (e.g. trim keep-ranges)
    "crop", "elements", "brand", "motion_zoom", "pace", "background",
)


def migrate_edit_spec(
    old_spec: dict[str, Any],
    old_graph: dict[str, Any],
    new_graph: dict[str, Any],
    viewport: dict[str, int] | None = None,
) -> dict[str, Any]:
    """Build the new edit-spec from new_graph, but carry the user's edits onto
    unchanged steps and mark added/changed steps dirty (so only they re-render)."""
    diff = diff_graphs(old_graph, new_graph)
    new_spec = build_edit_spec(new_graph, viewport)
    # keep project-level settings the user configured
    for key in CARRY_KEYS:
        if key in old_spec:
            new_spec[key] = old_spec[key]

    old_segs = {s["step_id"]: s for s in old_spec.get("segments", [])}
    status_by_new = {d["id"]: d for d in diff["steps"]}

    for seg in new_spec["segments"]:
        d = status_by_new.get(seg["step_id"])
        old = old_segs.get(d["old_id"]) if d and d.get("old_id") else None
        if d and d["status"] == "unchanged" and old is not None:
            # preserve script edits, filler toggles, zoom nudges
            seg["words"] = old.get("words", seg["words"])
            seg["removed"] = old.get("removed", seg["removed"])
            seg["zoom"] = old.get("zoom", seg["zoom"])
            seg["dirty"] = False
        elif d and d["status"] == "changed" and old is not None:
            seg["dirty"] = True  # re-narrated -> regenerate this segment
        else:
            seg["dirty"] = True  # added -> new segment
    return new_spec
