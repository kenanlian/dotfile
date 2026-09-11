/**
 * review-submit — stage-specific terminating tools for Pi review relays.
 *
 * Registers `submit_plan_review` and `submit_execute_review`. The relay enables
 * exactly one per run. Each tool validates its payload against a TypeBox schema
 * that mirrors the harness persisted evidence key set, returns `terminate: true`,
 * and exposes the validated payload as tool-result details.
 *
 * Loaded only via an explicit `-e` (the relay also passes `--no-extensions`).
 */

import { StringEnum } from "@earendil-works/pi-ai";
import { defineTool, type ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Type, type TSchema } from "typebox";
import {
  EXECUTE_REVIEW_FIELD_KEYS,
  EXECUTE_REVIEW_SCHEMA_ID,
  PLAN_REVIEW_FIELD_KEYS,
  PLAN_REVIEW_SCHEMA_ID,
  SUBMIT_EXECUTE_REVIEW,
  SUBMIT_PLAN_REVIEW,
} from "./keys.mjs";

const PathSha256 = Type.Object(
  {
    path: Type.String({ description: "Absolute path of the reviewed Plan file" }),
    sha256: Type.String({ description: "64-character lowercase hex SHA-256 digest" }),
  },
  { additionalProperties: false },
);

const Gate = Type.Object(
  {
    verdict: StringEnum(["pass", "fail"] as const, {
      description: "Independent gate verdict",
    }),
    findings: Type.Array(Type.String(), {
      description: "Evidence-bearing findings for this gate",
    }),
  },
  { additionalProperties: false },
);

const PlanReviewParams = Type.Object(
  {
    schema: StringEnum([PLAN_REVIEW_SCHEMA_ID] as const, {
      description: "Persisted plan-review schema id",
    }),
    board: Type.String({ description: "Board slug" }),
    card_id: Type.String({ description: "Card id" }),
    feature_id: Type.String({ description: "Feature id" }),
    review_run_id: Type.Integer({ description: "Owning review run id" }),
    round: Type.Integer({ description: "Review round, integer >= 1" }),
    plan: PathSha256,
    verdict: StringEnum(["pass", "revise"] as const, {
      description: "Plan-review verdict",
    }),
    summary: Type.String({ description: "1-3 sentence summary" }),
    required_revisions: Type.Array(Type.String(), {
      description: "Required revisions; empty when verdict is pass",
    }),
  },
  { additionalProperties: false },
);

const ExecuteReviewParams = Type.Object(
  {
    schema: StringEnum([EXECUTE_REVIEW_SCHEMA_ID] as const, {
      description: "Persisted execute-review schema id",
    }),
    card_id: Type.String({ description: "Card id" }),
    review_run_id: Type.Integer({ description: "Owning review run id" }),
    round: Type.Integer({ description: "Review round, integer >= 1" }),
    candidate_commit: Type.String({ description: "40-hex candidate commit" }),
    accepted_plan_sha256: Type.String({
      description: "64-character lowercase hex SHA-256 of the Accepted Plan",
    }),
    patch_gate: Gate,
    plan_conformance_gate: Gate,
    overall: Type.Object(
      {
        verdict: StringEnum(["pass", "revise", "blocked"] as const, {
          description: "Overall execute-review verdict",
        }),
      },
      { additionalProperties: false },
    ),
  },
  { additionalProperties: false },
);

function schemaKeys(schema: TSchema): string[] {
  const properties = (schema as { properties?: Record<string, unknown> }).properties;
  return Object.keys(properties ?? {});
}

function assertSchemaKeys(schema: TSchema, expected: readonly string[], label: string) {
  const actual = schemaKeys(schema);
  if (actual.join("\0") !== expected.join("\0")) {
    throw new Error(`${label} schema keys drifted: [${actual.join(", ")}] !== [${expected.join(", ")}]`);
  }
}

function submitTool(
  name: string,
  label: string,
  description: string,
  parameters: TSchema,
) {
  return defineTool({
    name,
    label,
    description,
    promptSnippet: `Finish this review by calling ${name} with the typed payload`,
    promptGuidelines: [
      `Use ${name} as the final action when the review payload is complete.`,
      `After calling ${name}, do not emit another assistant response in the same turn.`,
      `Do not put the review document in the final message; ${name} is the only report channel.`,
    ],
    parameters,
    async execute(_toolCallId, params) {
      return {
        content: [{ type: "text", text: `Submitted ${name}` }],
        details: params,
        terminate: true,
      };
    },
  });
}

const submitPlanReview = submitTool(
  SUBMIT_PLAN_REVIEW,
  "Submit plan review",
  "Submit the completed write-plan review payload and end the review run. Call this once as the final action.",
  PlanReviewParams,
);

const submitExecuteReview = submitTool(
  SUBMIT_EXECUTE_REVIEW,
  "Submit execute review",
  "Submit the completed execute-plan review payload (patch and plan-conformance gates) and end the review run. Call this once as the final action. Do not include UI evidence.",
  ExecuteReviewParams,
);

export default function reviewSubmitExtension(pi: ExtensionAPI) {
  assertSchemaKeys(PlanReviewParams, PLAN_REVIEW_FIELD_KEYS, SUBMIT_PLAN_REVIEW);
  assertSchemaKeys(ExecuteReviewParams, EXECUTE_REVIEW_FIELD_KEYS, SUBMIT_EXECUTE_REVIEW);
  pi.registerTool(submitPlanReview);
  pi.registerTool(submitExecuteReview);
}
