/**
 * stage-submit — terminating tools for coding-agent-harness Pi runs.
 *
 * Registers submit_plan, submit_plan_review, submit_implementation,
 * submit_execute_review, and submit_direct_implementation. The relay allowlist
 * exposes exactly one per run.
 * Each tool validates its payload against a TypeBox schema that mirrors the
 * harness contracts, returns terminate:true, and exposes the validated
 * payload as tool-result details.
 *
 * Loaded only via an explicit -e (the relay also passes --no-extensions).
 */

import { StringEnum } from "@earendil-works/pi-ai";
import { defineTool, type ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Type, type TSchema } from "typebox";
import {
  CONTRACT_FIELD_KEYS,
  DEVIATION_FIELD_KEYS,
  DIRECT_IMPLEMENTATION_FIELD_KEYS,
  DIRECT_IMPLEMENTATION_SCHEMA_ID,
  EXECUTE_REVIEW_FIELD_KEYS,
  EXECUTE_REVIEW_FINDING_FIELD_KEYS,
  EXECUTE_REVIEW_SCHEMA_ID,
  FILE_CHANGE_FIELD_KEYS,
  IMPLEMENTATION_FIELD_KEYS,
  IMPLEMENTATION_SCHEMA_ID,
  PLAN_FIELD_KEYS,
  PLAN_REVIEW_FIELD_KEYS,
  PLAN_REVIEW_FINDING_FIELD_KEYS,
  PLAN_REVIEW_SCHEMA_ID,
  PLAN_SCHEMA_ID,
  PLAN_VERIFICATION_FIELD_KEYS,
  REQUIREMENT_FIELD_KEYS,
  RISK_FIELD_KEYS,
  SUBMIT_DIRECT_IMPLEMENTATION,
  SUBMIT_EXECUTE_REVIEW,
  SUBMIT_IMPLEMENTATION,
  SUBMIT_PLAN,
  SUBMIT_PLAN_REVIEW,
  WORK_PACKAGE_FIELD_KEYS,
  EXPECT_EXTENSIONS_ENV,
  buildAttestationLine,
} from "./keys.mjs";

const Requirement = Type.Object(
  {
    id: Type.String({ description: "Requirement id" }),
    text: Type.String({ description: "Requirement text" }),
  },
  { additionalProperties: false },
);

const Contract = Type.Object(
  {
    id: Type.String({ description: "Contract id, e.g. C1" }),
    requirementIds: Type.Array(Type.String(), { description: "Referenced requirement ids" }),
    text: Type.String({ description: "Contract text" }),
  },
  { additionalProperties: false },
);

const FileChange = Type.Object(
  {
    action: StringEnum(["create", "modify", "delete"] as const, {
      description: "File action",
    }),
    path: Type.String({ description: "Repo-relative path" }),
  },
  { additionalProperties: false },
);

const WorkPackage = Type.Object(
  {
    id: Type.String({ description: "Work package id" }),
    title: Type.String({ description: "Work package title" }),
    objective: Type.String({ description: "Work package objective" }),
    dependsOn: Type.Array(Type.String(), { description: "Upstream work package ids" }),
    contractIds: Type.Array(Type.String(), { description: "Covered contract ids" }),
    fileChanges: Type.Array(FileChange, { description: "Planned file changes" }),
    steps: Type.Array(Type.String(), { description: "Implementation steps" }),
    verificationIds: Type.Array(Type.String(), { description: "Verification ids" }),
  },
  { additionalProperties: false },
);

const PlanVerification = Type.Object(
  {
    id: Type.String({ description: "Verification id" }),
    kind: StringEnum(["focused", "integration", "smoke"] as const, {
      description: "Verification kind",
    }),
    cwd: Type.String({ description: "Repo-relative cwd or ." }),
    argv: Type.Array(Type.String(), { description: "Command argv" }),
    expected: Type.String({ description: "Expected outcome" }),
    contractIds: Type.Array(Type.String(), { description: "Covered contract ids" }),
  },
  { additionalProperties: false },
);

const Risk = Type.Object(
  {
    risk: Type.String({ description: "Risk" }),
    mitigation: Type.String({ description: "Mitigation" }),
  },
  { additionalProperties: false },
);

const PlanParams = Type.Object(
  {
    schema: StringEnum([PLAN_SCHEMA_ID] as const, { description: "plan.v1 schema id" }),
    outcome: StringEnum(["completed", "blocked"] as const, { description: "Plan outcome" }),
    title: Type.String({ description: "Plan title" }),
    goal: Type.String({ description: "Plan goal" }),
    architecture: Type.String({ description: "Architecture" }),
    techStack: Type.Array(Type.String(), { description: "Tech stack" }),
    requirements: Type.Array(Requirement, { description: "Requirements" }),
    contracts: Type.Array(Contract, {
      description: "Contract objects {id, requirementIds, text}, never a list of id strings",
    }),
    workPackages: Type.Array(WorkPackage, { description: "Work packages" }),
    verification: Type.Array(PlanVerification, { description: "Verification" }),
    risks: Type.Array(Risk, { description: "Risks" }),
    blockingIssues: Type.Array(Type.String(), { description: "Blocking issues" }),
  },
  { additionalProperties: false },
);

const PlanReviewFinding = Type.Object(
  {
    severity: StringEnum(["blocking", "warning"] as const, { description: "Finding severity" }),
    location: Type.String({ description: "Plan section or requirement" }),
    problem: Type.String({ description: "Problem" }),
    requiredChange: Type.String({ description: "Required change" }),
  },
  { additionalProperties: false },
);

const PlanReviewParams = Type.Object(
  {
    schema: StringEnum([PLAN_REVIEW_SCHEMA_ID] as const, { description: "plan-review.v1 schema id" }),
    verdict: StringEnum(["approved", "request_changes", "blocked"] as const, {
      description: "Plan-review verdict",
    }),
    summary: Type.String({ description: "Summary" }),
    findings: Type.Array(PlanReviewFinding, { description: "Findings" }),
  },
  { additionalProperties: false },
);

const Deviation = Type.Object(
  {
    workPackageId: Type.String({ description: "Work package id" }),
    summary: Type.String({ description: "Deviation summary" }),
  },
  { additionalProperties: false },
);

const ImplementationParams = Type.Object(
  {
    schema: StringEnum([IMPLEMENTATION_SCHEMA_ID] as const, {
      description: "implementation.v1 schema id",
    }),
    outcome: StringEnum(["completed", "blocked"] as const, { description: "Implementation outcome" }),
    summary: Type.String({ description: "Summary" }),
    completedWorkPackages: Type.Array(Type.String(), { description: "Completed work package ids" }),
    deviations: Type.Array(Deviation, { description: "Deviations" }),
    residualRisks: Type.Array(Type.String(), { description: "Residual risks" }),
    blockingIssues: Type.Array(Type.String(), { description: "Blocking issues" }),
  },
  { additionalProperties: false },
);

const NonEmptyString = (description: string) => Type.String({ minLength: 1, description });

const DirectImplementationCompleted = Type.Object(
  {
    schema: StringEnum([DIRECT_IMPLEMENTATION_SCHEMA_ID] as const, {
      description: "direct-implementation.v1 schema id",
    }),
    outcome: StringEnum(["completed"] as const, { description: "Direct implementation outcome" }),
    summary: NonEmptyString("Summary"),
    residualRisks: Type.Array(NonEmptyString("Residual risk"), { description: "Residual risks" }),
    blockingIssues: Type.Array(NonEmptyString("Blocking issue"), {
      description: "Blocking issues",
      maxItems: 0,
    }),
  },
  { additionalProperties: false },
);

const DirectImplementationBlocked = Type.Object(
  {
    schema: StringEnum([DIRECT_IMPLEMENTATION_SCHEMA_ID] as const, {
      description: "direct-implementation.v1 schema id",
    }),
    outcome: StringEnum(["blocked"] as const, { description: "Direct implementation outcome" }),
    summary: NonEmptyString("Summary"),
    residualRisks: Type.Array(NonEmptyString("Residual risk"), { description: "Residual risks" }),
    blockingIssues: Type.Array(NonEmptyString("Blocking issue"), {
      description: "Blocking issues",
      minItems: 1,
    }),
  },
  { additionalProperties: false },
);

const DirectImplementationParams = Type.Union([
  DirectImplementationCompleted,
  DirectImplementationBlocked,
]);

const ExecuteReviewFinding = Type.Object(
  {
    severity: StringEnum(["blocking", "warning"] as const, { description: "Finding severity" }),
    file: Type.String({ description: "Repo-relative file path" }),
    line: Type.Integer({ description: "Line number, integer >= 0" }),
    problem: Type.String({ description: "Problem" }),
    requiredChange: Type.String({ description: "Required change" }),
  },
  { additionalProperties: false },
);

const ExecuteReviewParams = Type.Object(
  {
    schema: StringEnum([EXECUTE_REVIEW_SCHEMA_ID] as const, {
      description: "execute-review.v1 schema id",
    }),
    verdict: StringEnum(["approved", "request_changes", "blocked"] as const, {
      description: "Execute-review verdict",
    }),
    summary: Type.String({ description: "Summary" }),
    findings: Type.Array(ExecuteReviewFinding, { description: "Findings" }),
    acceptanceCoverage: Type.Array(Type.String(), { description: "Acceptance coverage notes" }),
  },
  { additionalProperties: false },
);

function schemaKeys(schema: TSchema): string[] {
  const union = (schema as { anyOf?: TSchema[]; oneOf?: TSchema[] }).anyOf
    ?? (schema as { anyOf?: TSchema[]; oneOf?: TSchema[] }).oneOf;
  if (union && union.length > 0) {
    const keys = schemaKeys(union[0]);
    for (const arm of union) {
      if (schemaKeys(arm).join("\0") !== keys.join("\0")) {
        throw new Error("union arm schema keys drifted");
      }
    }
    return keys;
  }
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
  shapeHint: string,
) {
  return defineTool({
    name,
    label,
    description,
    promptSnippet: `Finish this run by calling ${name} with the typed object payload. ${shapeHint}`,
    promptGuidelines: [
      `Use ${name} as the final action when the payload is complete.`,
      shapeHint,
      `Nested fields such as contracts, workPackages, findings, and fileChanges are objects, never bare id strings.`,
      `Call ${name} exactly once with a schema-valid payload. An error result from ${name} fails the run; a later corrected call is not accepted.`,
      `After a successful ${name} call, do not emit another assistant response in the same turn.`,
      `Do not put the report in the final message; ${name} is the only report channel.`,
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

const submitPlan = submitTool(
  SUBMIT_PLAN,
  "Submit plan",
  "Submit the completed plan payload and end the planner run. Call this once as the final action. contracts and workPackages are object arrays, not id strings.",
  PlanParams,
  "plan.v1 fields: schema, outcome, title, goal, architecture, techStack[], requirements[{id,text}], contracts[{id,requirementIds,text}], workPackages[{id,title,objective,dependsOn,contractIds,fileChanges[{action,path}],steps,verificationIds}], verification[{id,kind,cwd,argv,expected,contractIds}], risks[{risk,mitigation}], blockingIssues[].",
);

const submitPlanReview = submitTool(
  SUBMIT_PLAN_REVIEW,
  "Submit plan review",
  "Submit the completed plan-review payload and end the reviewer run. Call this once as the final action. findings are objects, not strings.",
  PlanReviewParams,
  "plan-review.v1 fields: schema, verdict, summary, findings[{severity,location,problem,requiredChange}].",
);

const submitImplementation = submitTool(
  SUBMIT_IMPLEMENTATION,
  "Submit implementation",
  "Submit the completed implementation payload and end the implementer run. Call this once as the final action.",
  ImplementationParams,
  "implementation.v1 fields: schema, outcome, summary, completedWorkPackages[], deviations[{workPackageId,summary}], residualRisks[], blockingIssues[].",
);

const submitDirectImplementation = submitTool(
  SUBMIT_DIRECT_IMPLEMENTATION,
  "Submit direct implementation",
  "Submit the completed direct-implementation payload and end the implementer run. Call this once as the final action.",
  DirectImplementationParams,
  "direct-implementation.v1 fields: schema, outcome, summary, residualRisks[], blockingIssues[].",
);

const submitExecuteReview = submitTool(
  SUBMIT_EXECUTE_REVIEW,
  "Submit execute review",
  "Submit the completed execute-review payload and end the reviewer run. Call this once as the final action. findings are objects, not strings.",
  ExecuteReviewParams,
  "execute-review.v1 fields: schema, verdict, summary, findings[{severity,file,line,problem,requiredChange}], acceptanceCoverage[].",
);

export default function stageSubmitExtension(pi: ExtensionAPI) {
  assertSchemaKeys(Requirement, REQUIREMENT_FIELD_KEYS, "requirement");
  assertSchemaKeys(Contract, CONTRACT_FIELD_KEYS, "contract");
  assertSchemaKeys(FileChange, FILE_CHANGE_FIELD_KEYS, "fileChange");
  assertSchemaKeys(WorkPackage, WORK_PACKAGE_FIELD_KEYS, "workPackage");
  assertSchemaKeys(PlanVerification, PLAN_VERIFICATION_FIELD_KEYS, "planVerification");
  assertSchemaKeys(Risk, RISK_FIELD_KEYS, "risk");
  assertSchemaKeys(PlanParams, PLAN_FIELD_KEYS, SUBMIT_PLAN);
  assertSchemaKeys(PlanReviewFinding, PLAN_REVIEW_FINDING_FIELD_KEYS, "planReviewFinding");
  assertSchemaKeys(PlanReviewParams, PLAN_REVIEW_FIELD_KEYS, SUBMIT_PLAN_REVIEW);
  assertSchemaKeys(Deviation, DEVIATION_FIELD_KEYS, "deviation");
  assertSchemaKeys(ImplementationParams, IMPLEMENTATION_FIELD_KEYS, SUBMIT_IMPLEMENTATION);
  assertSchemaKeys(DirectImplementationParams, DIRECT_IMPLEMENTATION_FIELD_KEYS, SUBMIT_DIRECT_IMPLEMENTATION);
  assertSchemaKeys(ExecuteReviewFinding, EXECUTE_REVIEW_FINDING_FIELD_KEYS, "executeReviewFinding");
  assertSchemaKeys(ExecuteReviewParams, EXECUTE_REVIEW_FIELD_KEYS, SUBMIT_EXECUTE_REVIEW);
  pi.registerTool(submitPlan);
  pi.registerTool(submitPlanReview);
  pi.registerTool(submitImplementation);
  pi.registerTool(submitDirectImplementation);
  pi.registerTool(submitExecuteReview);
  // Presence proof for the Harness fail-closed check. Pi 0.85.1 print/json
  // mode already exits 1 on a bad `-e`, but argv still cannot prove this
  // factory ran; session_start writes one grep-stable JSON line onto the
  // NDJSON event stream. Third-party extension presence (todos-tool) is a
  // follow-up: Pi silently ignores unknown `-t` names, so allowlist membership
  // is not a load proof.
  pi.on("session_start", () => {
    const line = buildAttestationLine(process.env[EXPECT_EXTENSIONS_ENV]);
    if (line) process.stdout.write(line);
  });
}
