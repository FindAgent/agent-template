/**
 * Interactive input layer for FindAgent code-bundle MCP tools.
 *
 * Goal: when a user calls a tool without knowing the exact array/object input
 * shape, the tool should NOT throw. Instead it returns a structured
 * `needs_input` payload — a brief, the missing fields, clarifying questions, a
 * JSON schema and a ready-to-edit example — so the host model can ask the user,
 * collect answers, and retry. Works on ANY MCP client.
 *
 * Where the client advertises the `elicitation` capability, server.ts upgrades
 * this into a native `elicitation/create` form (see tryElicit in server.ts).
 *
 * This module is pure (no SDK / no network) so it is trivially unit-testable.
 */

export type FieldType = "string" | "number" | "integer" | "boolean" | "array" | "object";

export interface FieldSpec {
  /** argument name as the tool reads it from args */
  name: string;
  type: FieldType;
  required?: boolean;
  /** description of the field */
  description: string;
  /** a realistic example value for this field */
  example: unknown;
  /** question to ask the user when the field is missing */
  question: string;
  /** for arrays/objects: human description of the item/shape, e.g. "{name, users}" */
  shape?: string;
  /** a closed set of allowed answers; a form renders them as a choice instead of a text box */
  options?: string[];
}

export interface InputQuestion {
  field: string;
  question: string;
  type: FieldType;
  required: boolean;
  example: unknown;
  shape?: string;
  options?: string[];
  /** why the question matters (the field's description) */
  why?: string;
}

export interface NeedsInput {
  status: "needs_input";
  tool: string;
  /** what the tool will do once it has the input */
  brief: string;
  /** required fields that are missing or invalid */
  missing: string[];
  /** questions to put to the user (missing required + optional refinements) */
  questions: InputQuestion[];
  /** JSON schema of the expected arguments object */
  schema: { type: "object"; properties: Record<string, unknown>; required: string[] };
  /** a ready-to-edit example arguments object */
  example: Record<string, unknown>;
  /** the one question to ask first: the first missing required field, else the first required one */
  next_question?: { field: string; question: string; why: string };
  /** guidance on how to proceed */
  hint: string;
}

/** Has this value gone missing / become the wrong shape for `type`? */
export function isMissing(v: unknown, type: FieldType): boolean {
  if (v === undefined || v === null) return true;
  switch (type) {
    case "array":
      return !Array.isArray(v) || v.length === 0;
    case "object":
      return typeof v !== "object" || Array.isArray(v) || Object.keys(v as object).length === 0;
    case "string":
      return typeof v !== "string" || v.length === 0;
    case "number":
    case "integer":
      return typeof v !== "number" || Number.isNaN(v);
    case "boolean":
      return typeof v !== "boolean";
    default:
      return false;
  }
}

function jsonSchemaFor(s: FieldSpec): Record<string, unknown> {
  const base: Record<string, unknown> = { type: s.type, description: s.description };
  if (s.shape) base["x-shape"] = s.shape;
  if (s.options) base["enum"] = s.options;
  return base;
}

export function buildSchema(specs: FieldSpec[]) {
  const properties: Record<string, unknown> = {};
  for (const s of specs) properties[s.name] = jsonSchemaFor(s);
  return {
    type: "object" as const,
    properties,
    required: specs.filter((s) => s.required).map((s) => s.name),
  };
}

export function buildExample(specs: FieldSpec[]): Record<string, unknown> {
  const ex: Record<string, unknown> = {};
  for (const s of specs) ex[s.name] = s.example;
  return ex;
}

/**
 * Build a needs_input payload. `present` is the args already supplied, so the
 * questions focus on what is missing (plus optional fields for refinement).
 */
export function needsInput(
  tool: string,
  brief: string,
  specs: FieldSpec[],
  present: Record<string, unknown> = {},
): NeedsInput {
  const missing = specs
    .filter((s) => (s.required ?? false) && isMissing(present[s.name], s.type))
    .map((s) => s.name);
  const questions: InputQuestion[] = specs
    .filter((s) => missing.includes(s.name) || !(s.required ?? false))
    .map((s) => ({
      field: s.name,
      question: s.question,
      type: s.type,
      required: s.required ?? false,
      example: s.example,
      why: s.description,
      ...(s.shape ? { shape: s.shape } : {}),
      ...(s.options ? { options: s.options } : {}),
    }));
  const lead = specs.find((s) => missing.includes(s.name)) ?? specs.find((s) => s.required);
  return {
    status: "needs_input",
    tool,
    brief,
    missing,
    questions,
    schema: buildSchema(specs),
    example: buildExample(specs),
    ...(lead
      ? { next_question: { field: lead.name, question: lead.question, why: lead.description } }
      : {}),
    hint: "Fill the example and call this tool again. Array/object args may be passed as JSON or as a JSON string — both are accepted.",
  };
}

/**
 * Guard helper for the dispatcher: returns a NeedsInput payload if any required
 * field is missing/invalid, else null. Call AFTER coerceJson so stringified
 * JSON has already been parsed.
 *
 *   const need = checkRequired("check_package", BRIEF, CHECK_PACKAGE_SPEC, { package: pkg });
 *   if (need) return need;            // ask the user instead of throwing
 */
export function checkRequired(
  tool: string,
  brief: string,
  specs: FieldSpec[],
  args: Record<string, unknown>,
): NeedsInput | null {
  const anyMissing = specs.some((s) => (s.required ?? false) && isMissing(args[s.name], s.type));
  return anyMissing ? needsInput(tool, brief, specs, args) : null;
}
