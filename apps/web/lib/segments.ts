/**
 * Pure scene (edit-spec segment) surgery for the video editor: merge two
 * adjacent scenes, split one at a word, and map a word to the instant it was
 * spoken.
 *
 * Why this is its own module: the editor only ever edits the edit spec, never
 * the Workflow Graph, so a merge or split is a list transform plus a save. Kept
 * free of React and I/O so it can be tested with node's test runner the way
 * the Python pipeline tests its own pure functions.
 *
 * Invariants that matter downstream:
 * - A merge keeps the FIRST scene's step_id. mark_dirty (api/editspec.py) diffs
 *   by step_id, so the merged scene is the only one that re-renders — the
 *   other clips are reused. A fresh id would be correct too, but would read
 *   as "new scene" in the diff for no gain.
 * - Inserts are placed `after:<step_id>`; one that pointed at the dropped
 *   scene is re-pointed at the survivor, or it would be silently appended to
 *   the end (effective_inserts' fallback for an unknown id).
 * - Filler indices (`removed`) index into `words`; the second scene's shift by
 *   the first's word count.
 * - A split's second half gets a fresh id. Spec scenes are not graph steps, so
 *   the never-renumber rule for graph ids does not apply.
 */

import type { EditSegment, EditSpec } from "@/lib/api";

export interface TimedWord {
  w: string;
  t_start: number; // seconds, raw recording clock
  t_end: number;
}

/** Punctuation/case-insensitive form, mirroring editspec._bare on the API. */
export function bare(word: string): string {
  return word.replace(/[^\w']/g, "").toLowerCase();
}

/** Merge scene `idx` with the one after it. Returns the spec unchanged when
 * there is no next scene. */
export function mergeWithNext(spec: EditSpec, idx: number): EditSpec {
  const a = spec.segments[idx];
  const b = spec.segments[idx + 1];
  if (!a || !b) return spec;
  const merged = mergeSegments(a, b);
  const segments = [...spec.segments];
  segments.splice(idx, 2, merged);
  if (!spec.inserts) return { ...spec, segments };
  const inserts = spec.inserts.map((it) =>
    it.position === `after:${b.step_id}` ? { ...it, position: `after:${a.step_id}` as const } : it,
  );
  return { ...spec, segments, inserts };
}

export function mergeSegments(a: EditSegment, b: EditSegment): EditSegment {
  const words = [...a.words, ...b.words];
  const removed = [...a.removed, ...b.removed.map((r) => r + a.words.length)];
  // Keep the first scene's zoom unless only the second had one — the merged
  // clip starts on the first scene's footage, so its click is what to frame.
  const zoom = a.zoom.enabled || !b.zoom.enabled ? a.zoom : b.zoom;
  return {
    ...a,
    words,
    removed,
    zoom,
    source_start_ms: Math.min(a.source_start_ms, b.source_start_ms),
    source_end_ms: Math.max(a.source_end_ms, b.source_end_ms),
    screenshot: a.screenshot ?? b.screenshot ?? null,
    // Skipping is per scene; a merged scene plays unless BOTH halves were skipped.
    skipped: !!a.skipped && !!b.skipped,
  };
}

/** Split scene `idx` so that words [0, wordIdx) stay and [wordIdx, …) move to
 * a new scene starting at `atMs`. Returns the spec unchanged for a cut at
 * either edge of the words or of the window. */
export function splitAt(
  spec: EditSpec,
  idx: number,
  atMs: number,
  wordIdx: number,
  newId: string = `split_${Date.now()}`,
): EditSpec {
  const seg = spec.segments[idx];
  if (!seg) return spec;
  if (atMs <= seg.source_start_ms + 150 || atMs >= seg.source_end_ms - 150) return spec;
  const wi = Math.max(0, Math.min(seg.words.length, Math.round(wordIdx)));
  const a: EditSegment = {
    ...seg,
    source_end_ms: Math.round(atMs),
    words: seg.words.slice(0, wi),
    removed: seg.removed.filter((r) => r < wi),
  };
  const b: EditSegment = {
    ...seg,
    step_id: newId,
    source_start_ms: Math.round(atMs),
    words: seg.words.slice(wi),
    removed: seg.removed.filter((r) => r >= wi).map((r) => r - wi),
  };
  const segments = [...spec.segments];
  segments.splice(idx, 1, a, b);
  return { ...spec, segments };
}

/** Word index a time-based cut lands on, assuming speech is spread evenly across
 * the window — the fallback when there are no word timings to consult. */
export function proportionalWordIndex(seg: EditSegment, atMs: number): number {
  const len = Math.max(1, seg.source_end_ms - seg.source_start_ms);
  const frac = (atMs - seg.source_start_ms) / len;
  return Math.round(seg.words.length * frac);
}

/** Start time (ms) of each of the scene's words, when the scene's script is
 * still the verbatim transcript. Returns null when the script no longer lines
 * up with what was spoken (AI rewrite, manual edit, a scene added by hand), in
 * which case callers fall back to the proportional estimate.
 *
 * "Lines up" = the transcript words inside the scene's window are the same
 * count, and at least 80% match ignoring punctuation and case. The slack
 * tolerates a corrected typo or two without losing the real timings. */
export function alignedWordTimes(seg: EditSegment, transcript: TimedWord[]): number[] | null {
  if (!seg.words.length || !transcript.length) return null;
  const t0 = seg.source_start_ms / 1000;
  const t1 = seg.source_end_ms / 1000;
  const inWindow = transcript.filter((w) => w.t_start >= t0 && w.t_start < t1);
  if (inWindow.length !== seg.words.length) return null;
  let same = 0;
  for (let i = 0; i < inWindow.length; i++) if (bare(inWindow[i].w) === bare(seg.words[i])) same++;
  if (same < Math.ceil(inWindow.length * 0.8)) return null;
  return inWindow.map((w) => Math.round(w.t_start * 1000));
}

// ---- packed ("effective") clock -------------------------------------------
//
// Trim and Crop mode draw the kept scenes back to back with no gaps, so a cut
// disappears and its neighbours touch — the timeline then shows only what the
// render will use. Positions on that clock are "packed ms"; every scene's own
// window still lives in raw source ms, and these two maps convert between them.
// Skipped scenes are packed too (greyed by the caller) so they can be unskipped.

export interface PackedItem {
  s: EditSegment;
  idx: number; // index in spec.segments
  start: number; // packed ms
  end: number;
  d: number; // duration (same on both clocks)
}

export interface PackedLayout {
  items: PackedItem[];
  total: number; // packed length, >= 1 so divisions are safe
}

export function packSegments(segments: EditSegment[]): PackedLayout {
  const sorted = segments
    .map((s, idx) => ({ s, idx }))
    .sort((a, b) => a.s.source_start_ms - b.s.source_start_ms);
  let off = 0;
  const items: PackedItem[] = sorted.map(({ s, idx }) => {
    const d = Math.max(0, s.source_end_ms - s.source_start_ms);
    const it = { s, idx, start: off, end: off + d, d };
    off += d;
    return it;
  });
  return { items, total: Math.max(off, 1) };
}

/** The scene under a packed position; past the end, the last scene. */
export function packedItemAt(layout: PackedLayout, packedMs: number): PackedItem | null {
  return (
    layout.items.find((it) => packedMs >= it.start && packedMs < it.end) ??
    layout.items[layout.items.length - 1] ??
    null
  );
}

/** Packed ms -> raw source ms. Clamped to the owning scene's window, so the
 * packed end maps to the last scene's source end rather than past it. */
export function packedToSource(layout: PackedLayout, packedMs: number): number {
  const it = packedItemAt(layout, packedMs);
  if (!it) return 0;
  return Math.min(it.s.source_end_ms, it.s.source_start_ms + (packedMs - it.start));
}

/** Raw source ms -> packed ms. A time inside a cut (no scene covers it) snaps
 * to the end of the previous kept scene, i.e. the seam where the cut closed. */
export function sourceToPacked(layout: PackedLayout, srcMs: number): number {
  const it =
    layout.items.find((x) => srcMs >= x.s.source_start_ms && srcMs < x.s.source_end_ms) ??
    [...layout.items].reverse().find((x) => x.s.source_end_ms <= srcMs);
  if (!it) return 0;
  return srcMs >= it.s.source_start_ms && srcMs < it.s.source_end_ms
    ? it.start + (srcMs - it.s.source_start_ms)
    : it.end;
}

/** Source time (ms) where word `wi` of the scene starts: the exact spoken
 * instant when timings align, else the proportional estimate. `wi` equal to
 * the word count means "just past the last word". */
export function wordSourceMs(seg: EditSegment, wi: number, transcript: TimedWord[]): number {
  const times = alignedWordTimes(seg, transcript);
  if (times && wi < times.length) return times[wi];
  const start = seg.source_start_ms;
  const end = Math.max(seg.source_end_ms, start + 300);
  const n = Math.max(1, seg.words.length);
  return Math.round(start + ((end - start) * wi) / n);
}
