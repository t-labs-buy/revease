import { test } from "node:test";
import assert from "node:assert/strict";

import type { EditSegment, EditSpec } from "./api";
import {
  alignedWordTimes,
  mergeWithNext,
  packSegments,
  packedToSource,
  proportionalWordIndex,
  sourceToPacked,
  splitAt,
  wordSourceMs,
} from "./segments";

const seg = (id: string, words: string, start: number, end: number, extra: Partial<EditSegment> = {}): EditSegment => ({
  step_id: id,
  words: words.split(" ").filter(Boolean),
  removed: [],
  zoom: { enabled: false, scale: 1.6, cx: 0.5, cy: 0.5 },
  source_start_ms: start,
  source_end_ms: end,
  ...extra,
});

const spec = (segments: EditSegment[], extra: Partial<EditSpec> = {}): EditSpec =>
  ({ segments, ...extra }) as EditSpec;

test("merge keeps the first id, joins words, shifts filler indices, spans both windows", () => {
  const a = seg("s1", "Now click the", 0, 2000, { removed: [0], screenshot: "a.png" });
  const b = seg("s2", "um settings button.", 2000, 5000, { removed: [0], zoom: { enabled: true, scale: 1.6, cx: 0.2, cy: 0.3 } });
  const out = mergeWithNext(spec([a, b]), 0);
  assert.equal(out.segments.length, 1);
  const m = out.segments[0];
  assert.equal(m.step_id, "s1");
  assert.deepEqual(m.words, ["Now", "click", "the", "um", "settings", "button."]);
  assert.deepEqual(m.removed, [0, 3]);
  assert.equal(m.source_start_ms, 0);
  assert.equal(m.source_end_ms, 5000);
  assert.equal(m.screenshot, "a.png");
  // only the second scene framed a click, so its zoom survives
  assert.equal(m.zoom.enabled, true);
  assert.equal(m.zoom.cx, 0.2);
});

test("merge re-points an insert that followed the dropped scene", () => {
  const s = spec([seg("s1", "a", 0, 1000), seg("s2", "b", 1000, 2000), seg("s3", "c", 2000, 3000)], {
    inserts: [
      { id: "i1", type: "title", position: "after:s2", duration_ms: 1000 },
      { id: "i2", type: "title", position: "after:s3", duration_ms: 1000 },
    ],
  });
  const out = mergeWithNext(s, 0);
  assert.deepEqual(out.segments.map((x) => x.step_id), ["s1", "s3"]);
  assert.deepEqual(out.inserts!.map((i) => i.position), ["after:s1", "after:s3"]);
});

test("merge on the last scene is a no-op", () => {
  const s = spec([seg("s1", "a", 0, 1000)]);
  assert.equal(mergeWithNext(s, 0), s);
});

test("split at a word moves the tail and re-bases its filler indices", () => {
  const s = spec([seg("s1", "one two um three four", 0, 5000, { removed: [2] })]);
  const out = splitAt(s, 0, 2500, 2, "s1b");
  assert.equal(out.segments.length, 2);
  const [a, b] = out.segments;
  assert.deepEqual(a.words, ["one", "two"]);
  assert.deepEqual(a.removed, []);
  assert.equal(a.source_end_ms, 2500);
  assert.equal(b.step_id, "s1b");
  assert.deepEqual(b.words, ["um", "three", "four"]);
  assert.deepEqual(b.removed, [0]);
  assert.equal(b.source_start_ms, 2500);
});

test("split too close to either edge of the window is refused", () => {
  const s = spec([seg("s1", "a b c", 0, 1000)]);
  assert.equal(splitAt(s, 0, 100, 1), s);
  assert.equal(splitAt(s, 0, 950, 1), s);
});

test("merge then split restores the original two scenes' words", () => {
  const a = seg("s1", "first line.", 0, 2000);
  const b = seg("s2", "second line.", 2000, 4000);
  const merged = mergeWithNext(spec([a, b]), 0);
  const back = splitAt(merged, 0, 2000, 2, "s2");
  assert.deepEqual(back.segments.map((x) => x.words), [a.words, b.words]);
});

const transcript = [
  { w: "Now", t_start: 1.0, t_end: 1.2 },
  { w: "click", t_start: 1.3, t_end: 1.6 },
  { w: "settings.", t_start: 1.7, t_end: 2.1 },
  { w: "Then", t_start: 4.0, t_end: 4.2 },
];

test("verbatim script gets exact word timings", () => {
  const s = seg("s1", "Now click settings.", 0, 3000);
  assert.deepEqual(alignedWordTimes(s, transcript), [1000, 1300, 1700]);
  assert.equal(wordSourceMs(s, 2, transcript), 1700);
});

test("a corrected word still aligns; a rewrite falls back to proportional", () => {
  const typo = seg("s1", "Now click Settings", 0, 3000); // case + punctuation differ
  assert.deepEqual(alignedWordTimes(typo, transcript), [1000, 1300, 1700]);

  const rewritten = seg("s1", "Open the settings panel now.", 0, 3000);
  assert.equal(alignedWordTimes(rewritten, transcript), null);
  // 5 words over 3000ms: word 2 is estimated at 40% of the window
  assert.equal(wordSourceMs(rewritten, 2, transcript), 1200);
  assert.equal(proportionalWordIndex(rewritten, 1200), 2);
});

test("packing closes the cuts and keeps scenes in source order", () => {
  // s2 comes first on the source clock; a 2s cut sits between s2 and s1
  const layout = packSegments([seg("s1", "b", 5000, 8000), seg("s2", "a", 1000, 3000)]);
  assert.equal(layout.total, 5000);
  assert.deepEqual(layout.items.map((it) => [it.s.step_id, it.start, it.end]), [
    ["s2", 0, 2000],
    ["s1", 2000, 5000],
  ]);
  assert.equal(packSegments([]).total, 1);
});

test("packed <-> source round-trips inside a scene and closes over a cut", () => {
  const layout = packSegments([seg("s1", "a", 1000, 3000), seg("s2", "b", 5000, 8000)]);
  assert.equal(sourceToPacked(layout, 1500), 500);
  assert.equal(packedToSource(layout, 500), 1500);
  // the seam: the end of s1 and the start of s2 are the same packed instant
  assert.equal(sourceToPacked(layout, 3000), 2000);
  assert.equal(sourceToPacked(layout, 5000), 2000);
  assert.equal(packedToSource(layout, 2000), 5000);
  // a time inside the cut snaps to the seam; before the first scene to 0
  assert.equal(sourceToPacked(layout, 4000), 2000);
  assert.equal(sourceToPacked(layout, 200), 0);
  // the packed end maps to the last scene's source end, never past it
  assert.equal(packedToSource(layout, layout.total), 8000);
  assert.equal(packedToSource(layout, 99999), 8000);
});

test("a crop window spanning a cut keeps its source width but packs tighter", () => {
  const layout = packSegments([seg("s1", "a", 0, 4000), seg("s2", "b", 6000, 10000)]);
  const p0 = sourceToPacked(layout, 2000);
  const p1 = sourceToPacked(layout, 8000);
  assert.equal(p1 - p0, 4000); // 6000 of source, 2000 of it cut
  // moving that packed window right by 1000 re-maps both edges through the seam
  assert.equal(packedToSource(layout, p0 + 1000), 3000);
  assert.equal(packedToSource(layout, p1 + 1000), 9000);
  // a window entirely inside the cut has no packed width at all
  assert.equal(sourceToPacked(layout, 4500), sourceToPacked(layout, 5500));
});

test("no transcript at all means the proportional estimate", () => {
  const s = seg("s1", "a b c d", 1000, 3000);
  assert.equal(alignedWordTimes(s, []), null);
  assert.equal(wordSourceMs(s, 1, []), 1500);
});
