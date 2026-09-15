import { test } from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { renderPlanMarkdown, writeStageArtifacts } from "../src/artifacts.mjs";

function planPayload() {
  return {
    schema: "plan.v1",
    outcome: "completed",
    title: 'Greet: "hello" 你好',
    goal: "Add greet\nwith a newline",
    architecture: "```js\n// fence\n```",
    techStack: ["Node.js"],
    requirements: [{ id: "R1", text: "greet returns a greeting" }],
    contracts: [{ id: "C1", requirementIds: ["R1"], text: "contract" }],
    workPackages: [{
      id: "WP-01",
      title: "Implement greet",
      objective: "Add greet",
      dependsOn: [],
      contractIds: ["C1"],
      fileChanges: [{ action: "modify", path: "src/greet.mjs" }],
      steps: ["Write greet"],
      verificationIds: ["V1"],
    }],
    verification: [{
      id: "V1",
      kind: "focused",
      cwd: ".",
      argv: ["node", "--test"],
      expected: "pass",
      contractIds: ["C1"],
    }],
    risks: [{ risk: "none", mitigation: "tiny" }],
    blockingIssues: [],
  };
}

function context(outDir, extra = {}) {
  return {
    job: {
      jobId: "job_1",
      idempotencyKey: "task:plan:1",
      taskId: "task",
      stage: extra.stage || "plan",
      attempt: extra.attempt || 1,
      inputs: [{ kind: "requirement", path: "/abs/req.md", sha256: "b".repeat(64) }],
    },
    jobSha256: "c".repeat(64),
    sessionId: "sess-1",
    workspace: {
      repoRoot: "/abs/repo",
      branch: "main",
      head: "a".repeat(40),
      baselineSnapshotSha256: "d".repeat(64),
    },
    outDir,
  };
}

test("writeStageArtifacts binds host identity and writes canonical JSON plus plan markdown", () => {
  const tmp = mkdtempSync(join(tmpdir(), "artifacts-"));
  try {
    const payload = planPayload();
    const result = writeStageArtifacts(context(tmp), payload);
    assert.equal(result.ok, true);
    assert.equal(result.descriptors[0].canonical, true);
    assert.equal(result.descriptors[1].canonical, false);
    const artifact = JSON.parse(readFileSync(result.descriptors[0].path, "utf8"));
    assert.equal(artifact.schema, "coding-agent.artifact.v1");
    assert.equal(artifact.job.jobId, "job_1");
    assert.equal(artifact.sessionId, "sess-1");
    assert.deepEqual(artifact.payload, payload);
    const markdown = readFileSync(result.descriptors[1].path, "utf8");
    assert.match(markdown, /Greet: "hello" 你好/);
    assert.match(markdown, /WP-01/);
    assert.match(markdown, /Blocking issues/);
    const rendered = renderPlanMarkdown(payload);
    assert.match(rendered, /```js/);
  } finally {
    rmSync(tmp, { recursive: true, force: true });
  }
});

test("existing identical artifacts can be reread; different content is refused", () => {
  const tmp = mkdtempSync(join(tmpdir(), "artifacts-"));
  try {
    const first = writeStageArtifacts(context(tmp), planPayload());
    const second = writeStageArtifacts(context(tmp), planPayload());
    assert.equal(second.ok, true);
    assert.equal(second.descriptors[0].sha256, first.descriptors[0].sha256);
    writeFileSync(first.descriptors[0].path, "{}\n");
    const third = writeStageArtifacts(context(tmp), planPayload());
    assert.equal(third.ok, false);
    assert.equal(third.error.kind, "artifact_write_failed");
  } finally {
    rmSync(tmp, { recursive: true, force: true });
  }
});
