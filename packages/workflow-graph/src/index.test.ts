import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { validate, assertValid } from "./index.ts";

const __dirname = dirname(fileURLToPath(import.meta.url));
const example = JSON.parse(
  readFileSync(join(__dirname, "..", "examples", "valid-example.json"), "utf-8"),
);

test("accepts the master §2 example graph", () => {
  const { valid, errors } = validate(example);
  assert.equal(valid, true, JSON.stringify(errors));
});

test("rejects a graph missing steps[].action", () => {
  const bad = structuredClone(example);
  delete bad.steps[0].action;
  const { valid } = validate(bad);
  assert.equal(valid, false);
});

test("rejects an unknown action enum value", () => {
  const bad = structuredClone(example);
  bad.steps[0].action = "teleport";
  assert.equal(validate(bad).valid, false);
});

test("rejects a bbox that is not length 4", () => {
  const bad = structuredClone(example);
  bad.steps[0].bbox = [1, 2, 3];
  assert.equal(validate(bad).valid, false);
});

test("assertValid throws on invalid, passes on valid", () => {
  assert.throws(() => assertValid({ workflow_id: "x" }));
  assert.doesNotThrow(() => assertValid(example));
});
