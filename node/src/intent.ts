/**
 * Intent-discovery layer for FindAgent code-bundle MCP tools.
 *
 * This EXTENDS the interactive input layer (src/interactive.ts). Where
 * `needs_input` reacts to a missing argument, intent discovery is proactive: the
 * user states a freeform GOAL, and the agent (a) restates that goal in one line,
 * (b) asks 2–4 targeted clarifying questions to pin down scope/inputs/output,
 * (c) proposes a concrete input object (matching the target tool's schema) with
 * realistic values, and (d) asks the user to confirm or edit before running.
 *
 * The scaffold is DETERMINISTIC — derived purely from the FieldSpec[] already
 * defined in tools.ts — so it is trivially unit-testable with no network and
 * involves no model.
 *
 * Pure module: no SDK, no network.
 */

import { buildSchema, buildExample, type FieldSpec } from "./interactive.js";

export interface IntentQuestion {
  field: string;
  question: string;
  /** why this matters for the analysis */
  why: string;
}

export interface IntentDiscovery {
  status: "intent_discovery";
  tool: string;
  /** the user's goal, restated in one line */
  restated_goal: string;
  /** 2–4 targeted clarifying questions */
  questions: IntentQuestion[];
  /** a concrete, ready-to-run input object matching `schema` */
  proposed_input: Record<string, unknown>;
  /** JSON schema of the target tool's arguments */
  schema: { type: "object"; properties: Record<string, unknown>; required: string[] };
  /** ask the user to confirm or edit, then call the run tool */
  confirm_prompt: string;
}

/** A restated goal is one line; anything longer is cut, never echoed whole. */
export const MAX_GOAL_CHARS = 300;

/** Restate a freeform goal in one line, defaulting when none is supplied. */
function restate(goal: string | undefined, tool: string): string {
  const g = (goal ?? "").trim();
  if (g.length === 0) {
    return `Plan and run \`${tool}\` for you.`;
  }
  return `You want to: ${g.length > MAX_GOAL_CHARS ? `${g.slice(0, MAX_GOAL_CHARS)}...` : g}`;
}

/**
 * Merge realistic example values with any partial args the user already gave.
 * Provided values win; every other field is seeded from the FieldSpec example so
 * the proposed input is always concrete and runnable.
 */
function proposeInput(
  specs: FieldSpec[],
  provided: Record<string, unknown>,
): Record<string, unknown> {
  const proposed = buildExample(specs);
  // Only fields the tool declares are carried over: a caller cannot make the agent echo arbitrary keys.
  for (const spec of specs) {
    const v = provided[spec.name];
    if (v !== undefined && v !== null) proposed[spec.name] = v;
  }
  return proposed;
}

/**
 * Build the deterministic intent-discovery scaffold from a tool's FieldSpec[].
 * Questions focus on the fields not yet supplied; when everything is supplied we
 * still ask a confirmation-oriented question so the user can course-correct.
 */
export function buildIntentDialogue(
  tool: string,
  goal: string | undefined,
  specs: FieldSpec[],
  provided: Record<string, unknown> = {},
): IntentDiscovery {
  const unspecified = specs.filter((s) => {
    const v = provided[s.name];
    return v === undefined || v === null;
  });
  const source = unspecified.length > 0 ? unspecified : specs;
  const questions: IntentQuestion[] = source.slice(0, 4).map((s) => ({
    field: s.name,
    question: s.question,
    why: s.description,
  }));

  return {
    status: "intent_discovery",
    tool,
    restated_goal: restate(goal, tool),
    questions,
    proposed_input: proposeInput(specs, provided),
    schema: buildSchema(specs),
    confirm_prompt: `Review the proposed input above. Reply "run" to proceed, or edit any field, then call \`${tool}\`.`,
  };
}
