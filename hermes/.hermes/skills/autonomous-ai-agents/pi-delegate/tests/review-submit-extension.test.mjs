import { test } from "node:test";
import assert from "node:assert/strict";
import { realpathSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

import {
  EXECUTE_REVIEW_FIELD_KEYS,
  EXECUTE_REVIEW_SCHEMA_ID,
  PLAN_REVIEW_FIELD_KEYS,
  PLAN_REVIEW_SCHEMA_ID,
  SUBMIT_EXECUTE_REVIEW,
  SUBMIT_PLAN_REVIEW,
} from "../extensions/review-submit/keys.mjs";

const TEST_DIR = dirname(fileURLToPath(import.meta.url));
const EXT_ROOT = join(TEST_DIR, "..", "extensions", "review-submit");

function piPackageRoot() {
  const bin = realpathSync(join(process.env.HOME || "", ".local", "bin", "pi"));
  return join(dirname(bin), "..", "..");
}

async function loadReviewSubmit() {
  const loaderUrl = pathToFileURL(join(piPackageRoot(), "dist/core/extensions/loader.js")).href;
  const { loadExtensions } = await import(loaderUrl);
  return loadExtensions([EXT_ROOT], TEST_DIR);
}

function planPayload() {
  return {
    schema: PLAN_REVIEW_SCHEMA_ID,
    board: "dotfile",
    card_id: "t_example",
    feature_id: "f_example",
    review_run_id: 1,
    round: 1,
    plan: {
      path: "/tmp/plan.md",
      sha256: "a".repeat(64),
    },
    verdict: "pass",
    summary: "Plan is decision-complete.",
    required_revisions: [],
  };
}

function executePayload() {
  return {
    schema: EXECUTE_REVIEW_SCHEMA_ID,
    card_id: "t_example",
    review_run_id: 2,
    round: 1,
    candidate_commit: "b".repeat(40),
    accepted_plan_sha256: "c".repeat(64),
    patch_gate: { verdict: "pass", findings: [] },
    plan_conformance_gate: { verdict: "pass", findings: [] },
    overall: { verdict: "pass" },
  };
}

test("review-submit extension loads under -e with --no-extensions", async () => {
  const loaded = await loadReviewSubmit();
  assert.deepEqual(loaded.errors, []);
  assert.equal(loaded.extensions.length, 1);
  const tools = loaded.extensions[0].tools;
  assert.ok(tools.has(SUBMIT_PLAN_REVIEW), "submit_plan_review must register");
  assert.ok(tools.has(SUBMIT_EXECUTE_REVIEW), "submit_execute_review must register");
});

test("submit_plan_review validates, terminates, and exposes the payload as details", async () => {
  const loaded = await loadReviewSubmit();
  assert.equal(loaded.errors.length, 0);
  const tool = loaded.extensions[0].tools.get(SUBMIT_PLAN_REVIEW);
  assert.deepEqual(Object.keys(tool.definition.parameters.properties), [...PLAN_REVIEW_FIELD_KEYS]);
  assert.equal(tool.definition.parameters.additionalProperties, false);
  const payload = planPayload();
  const result = await tool.definition.execute("call-plan", payload);
  assert.equal(result.terminate, true);
  assert.deepEqual(result.details, payload);
  assert.equal(result.content[0].text, `Submitted ${SUBMIT_PLAN_REVIEW}`);
});

test("submit_execute_review validates, terminates, and exposes the payload as details", async () => {
  const loaded = await loadReviewSubmit();
  assert.equal(loaded.errors.length, 0);
  const tool = loaded.extensions[0].tools.get(SUBMIT_EXECUTE_REVIEW);
  assert.deepEqual(Object.keys(tool.definition.parameters.properties), [...EXECUTE_REVIEW_FIELD_KEYS]);
  assert.equal(tool.definition.parameters.additionalProperties, false);
  assert.ok(!Object.hasOwn(tool.definition.parameters.properties, "ui_evidence"));
  const payload = executePayload();
  const result = await tool.definition.execute("call-execute", payload);
  assert.equal(result.terminate, true);
  assert.deepEqual(result.details, payload);
  assert.equal(result.content[0].text, `Submitted ${SUBMIT_EXECUTE_REVIEW}`);
});
