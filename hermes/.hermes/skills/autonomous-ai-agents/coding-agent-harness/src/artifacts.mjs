import { existsSync, mkdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { ARTIFACT_SCHEMA_ID, STAGE_CONTRACTS, typedError } from "./contracts.mjs";
import { atomicWriteFile, sha256File, canonicalJson } from "./util.mjs";

const KIND_FILES = Object.freeze({
  plan: "plan",
  "plan-review": "plan-review",
  implementation: "implementation",
  "execute-review": "execute-review",
  "direct-implementation": "direct-implementation",
});

export function renderPlanMarkdown(payload) {
  const lines = [];
  lines.push(`# ${payload.title}`);
  lines.push("");
  lines.push("## Goal");
  lines.push("");
  lines.push(payload.goal);
  lines.push("");
  lines.push("## Architecture");
  lines.push("");
  lines.push(payload.architecture);
  lines.push("");
  lines.push("## Tech stack");
  lines.push("");
  for (const item of payload.techStack) lines.push(`- ${item}`);
  lines.push("");
  lines.push("## Requirements");
  lines.push("");
  for (const item of payload.requirements) lines.push(`- ${item.id}: ${item.text}`);
  lines.push("");
  lines.push("## Contracts");
  lines.push("");
  for (const item of payload.contracts) {
    lines.push(`- ${item.id} (${item.requirementIds.join(", ")}): ${item.text}`);
  }
  lines.push("");
  lines.push("## Work packages");
  lines.push("");
  for (const item of payload.workPackages) {
    lines.push(`### ${item.id}: ${item.title}`);
    lines.push("");
    lines.push(item.objective);
    lines.push("");
    if (item.dependsOn.length) lines.push(`Depends on: ${item.dependsOn.join(", ")}`);
    lines.push(`Contracts: ${item.contractIds.join(", ")}`);
    lines.push("");
    lines.push("Files:");
    for (const file of item.fileChanges) lines.push(`- ${file.action} ${file.path}`);
    lines.push("");
    lines.push("Steps:");
    for (const step of item.steps) lines.push(`- ${step}`);
    lines.push("");
    lines.push(`Verification: ${item.verificationIds.join(", ")}`);
    lines.push("");
  }
  lines.push("## Verification");
  lines.push("");
  for (const item of payload.verification) {
    lines.push(`- ${item.id} (${item.kind}): \`${item.argv.join(" ")}\` expected ${item.expected}`);
  }
  lines.push("");
  lines.push("## Risks");
  lines.push("");
  for (const item of payload.risks) lines.push(`- ${item.risk}: ${item.mitigation}`);
  lines.push("");
  lines.push("## Blocking issues");
  lines.push("");
  if (payload.blockingIssues.length === 0) lines.push("- none");
  else for (const item of payload.blockingIssues) lines.push(`- ${item}`);
  lines.push("");
  return lines.join("\n");
}

function artifactFileName(kind, attempt, ext = "json") {
  return `${KIND_FILES[kind]}-attempt-${attempt}.${ext}`;
}

function bindArtifact({ job, jobSha256, sessionId, workspace, payload }) {
  const contract = STAGE_CONTRACTS[job.stage];
  return {
    schema: ARTIFACT_SCHEMA_ID,
    kind: contract.outputKind,
    job: {
      jobId: job.jobId,
      idempotencyKey: job.idempotencyKey,
      taskId: job.taskId,
      stage: job.stage,
      attempt: job.attempt,
      jobSha256,
    },
    sessionId,
    inputs: job.inputs.map((item) => ({
      kind: item.kind,
      path: item.path,
      sha256: item.sha256,
    })),
    workspace: {
      repoRoot: workspace.repoRoot,
      branch: workspace.branch,
      head: workspace.head,
      baselineSnapshotSha256: workspace.baselineSnapshotSha256,
    },
    payload,
  };
}

function writeAtomicOrReuse(path, contents) {
  const payload = Buffer.from(contents);
  if (!existsSync(path)) {
    atomicWriteFile(path, contents);
    return { path, sha256: sha256File(path), reused: false };
  }
  const existing = readFileSync(path);
  if (Buffer.compare(existing, payload) !== 0) {
    return {
      ok: false,
      error: typedError("artifact_write_failed", path, "existing artifact content differs; refusing to overwrite"),
    };
  }
  return { path, sha256: sha256File(path), reused: true };
}

export function writeStageArtifacts(context, payload) {
  const { job, jobSha256, sessionId, workspace, outDir } = context;
  const contract = STAGE_CONTRACTS[job.stage];
  const artifactsDir = join(outDir, "artifacts");
  mkdirSync(artifactsDir, { recursive: true });
  const artifact = bindArtifact({ job, jobSha256, sessionId, workspace, payload });
  const jsonPath = join(artifactsDir, artifactFileName(contract.outputKind, job.attempt, "json"));
  const serialized = canonicalJson(artifact);
  const jsonWrite = writeAtomicOrReuse(jsonPath, serialized);
  if (jsonWrite.ok === false) return jsonWrite;
  const descriptors = [
    {
      kind: contract.outputKind,
      path: jsonPath,
      sha256: jsonWrite.sha256,
      schema: ARTIFACT_SCHEMA_ID,
      canonical: true,
    },
  ];
  if (contract.outputKind === "plan") {
    const mdPath = join(artifactsDir, artifactFileName("plan", job.attempt, "md"));
    const markdown = renderPlanMarkdown(payload);
    const mdContents = markdown.endsWith("\n") ? markdown : `${markdown}\n`;
    const mdWrite = writeAtomicOrReuse(mdPath, mdContents);
    if (mdWrite.ok === false) return mdWrite;
    descriptors.push({
      kind: "plan",
      path: mdPath,
      sha256: mdWrite.sha256,
      schema: "text/markdown",
      canonical: false,
    });
  }
  return { ok: true, artifact, descriptors };
}
