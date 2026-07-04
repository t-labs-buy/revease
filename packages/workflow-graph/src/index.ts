import Ajv2020 from "ajv/dist/2020.js";
import { type ErrorObject } from "ajv";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const __dirname = dirname(fileURLToPath(import.meta.url));

/** The raw JSON Schema (draft 2020-12) for the Workflow Graph IR. */
export const schema = JSON.parse(
  readFileSync(join(__dirname, "..", "schema", "workflow-graph.schema.json"), "utf-8"),
);

// ---- TypeScript types mirrored from the schema (kept in sync manually for V1) ----
export type StepAction =
  | "click"
  | "input"
  | "navigation"
  | "scroll"
  | "keydown"
  | "wait"
  | "custom";

export interface WorkflowStep {
  id: string;
  action: StepAction;
  target: string;
  intent?: string;
  screen_name?: string;
  selector?: string | null;
  screenshot?: string | null;
  bbox?: [number, number, number, number] | null;
  narration?: string | null;
  t_start?: number | null;
  t_end?: number | null;
  confidence?: number | null;
  review_status?: "auto" | "needs_review" | "accepted" | "edited";
}

export interface WorkflowEdge {
  from: string;
  to: string;
  condition?: string | null;
}

export interface WorkflowGraph {
  workflow_id: string;
  version: number;
  title: string;
  steps: WorkflowStep[];
  edges: WorkflowEdge[];
}

export interface ValidationResult {
  valid: boolean;
  errors: ErrorObject[];
}

const ajv = new Ajv2020({ allErrors: true, strict: false });
const validateFn = ajv.compile(schema);

/** Validate an unknown value against the Workflow Graph schema. */
export function validate(data: unknown): ValidationResult {
  const valid = validateFn(data) as boolean;
  return { valid, errors: valid ? [] : (validateFn.errors ?? []) };
}

/** Throwing variant — narrows the type on success. */
export function assertValid(data: unknown): asserts data is WorkflowGraph {
  const { valid, errors } = validate(data);
  if (!valid) {
    const msg = errors.map((e) => `${e.instancePath || "/"} ${e.message}`).join("; ");
    throw new Error(`Invalid Workflow Graph: ${msg}`);
  }
}
