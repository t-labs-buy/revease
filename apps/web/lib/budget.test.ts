import { test } from "node:test";
import assert from "node:assert/strict";

import type { EditSegment, EditSpec } from "./api";
import { sceneOverrun, sceneWordBudget } from "./api";

const seg = (words: string, seconds: number, extra: Partial<EditSegment> = {}): EditSegment => ({
  step_id: "s1",
  words: words.split(" ").filter(Boolean),
  removed: [],
  zoom: { enabled: false, scale: 1.6, cx: 0.5, cy: 0.5 },
  source_start_ms: 0,
  source_end_ms: seconds * 1000,
  ...extra,
});

const spec = (extra: Partial<EditSpec> = {}): EditSpec =>
  ({ segments: [], voice: { voice_id: "af_sarah", speed: 1, use_original: false }, pace: 1, ...extra }) as EditSpec;

const words = (n: number) => Array.from({ length: n }, (_, i) => `w${i}`).join(" ");

test("budget mirrors the API: (seconds - gap) x 2.3 x speed", () => {
  assert.equal(sceneWordBudget(10), 21);
  assert.equal(sceneWordBudget(10, 1.3), 27);
  assert.equal(sceneWordBudget(0.5), 0);
});

test("a line within budget is not flagged; one over it is, with the numbers", () => {
  assert.equal(sceneOverrun(seg(words(21), 10), spec()), null);
  assert.deepEqual(sceneOverrun(seg(words(30), 10), spec()), { words: 30, budget: 21 });
});

test("struck fillers do not count; pauses eat footage time instead of words", () => {
  const s = seg(words(23), 10, { removed: [0, 1] }); // 21 spoken words -> fits
  assert.equal(sceneOverrun(s, spec()), null);
  const p = seg(`${words(20)} [pause:2]`, 10); // 20 words in 8 s of voice -> budget 16
  assert.deepEqual(sceneOverrun(p, spec()), { words: 20, budget: 16 });
});

test("faster voice or pace raises the budget; skipped and original-voice scenes are never flagged", () => {
  const s = seg(words(26), 10);
  assert.deepEqual(sceneOverrun(s, spec())?.budget, 21);
  assert.equal(sceneOverrun(s, spec({ voice: { voice_id: "af_sarah", speed: 1.3, use_original: false } })), null);
  assert.equal(sceneOverrun(s, spec({ pace: 1.3 })), null);
  assert.equal(sceneOverrun(seg(words(50), 2, { skipped: true }), spec()), null);
  assert.equal(sceneOverrun(seg(words(50), 2), spec({ voice: { voice_id: "af_sarah", speed: 1, use_original: true } })), null);
  assert.equal(sceneOverrun(seg("", 2), spec()), null);
});

test("scriptFit sums words and budgets over narrated, unskipped scenes", () => {
  const { scriptFit } = require("./api") as typeof import("./api");
  const s = spec({
    segments: [
      seg(words(30), 10), // budget 21
      seg(words(5), 10, { skipped: true }), // ignored
      seg("", 10), // silent: ignored
      seg(words(10), 5), // budget 9
    ],
  });
  const fit = scriptFit(s);
  assert.equal(fit.words, 40);
  assert.equal(fit.budget, 30);
  assert.equal(fit.ratio, 0.75);
  assert.equal(scriptFit(spec({ segments: [seg(words(10), 10)] })).ratio, 1);
});
