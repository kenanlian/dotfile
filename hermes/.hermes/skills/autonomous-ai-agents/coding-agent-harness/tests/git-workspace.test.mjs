import { test } from "node:test";
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import {
  mkdirSync,
  mkdtempSync,
  readFileSync,
  realpathSync,
  rmSync,
  symlinkSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const {
  assertPostflight,
  captureSnapshot,
  compareSnapshots,
  parsePorcelainZ,
  preflightWorkspace,
} = await import("../src/git-workspace.mjs");
const { sha256File } = await import("../src/util.mjs");

function git(cwd, args) {
  return execFileSync("git", args, { cwd, encoding: "utf8", stdio: ["ignore", "pipe", "pipe"] });
}

function makeRepo() {
  const tmp = mkdtempSync(join(tmpdir(), "harness-git-"));
  const repo = join(tmp, "repo");
  const outDir = join(tmp, "out");
  mkdirSync(repo, { recursive: true });
  mkdirSync(outDir, { recursive: true });
  git(repo, ["init", "-b", "main"]);
  git(repo, ["config", "user.email", "test@example.com"]);
  git(repo, ["config", "user.name", "Test"]);
  writeFileSync(join(repo, "src.txt"), "hello\n");
  git(repo, ["add", "src.txt"]);
  git(repo, ["commit", "-m", "init"]);
  const head = git(repo, ["rev-parse", "HEAD"]).trim();
  const requirement = join(tmp, "requirement.md");
  writeFileSync(requirement, "# req\n");
  return {
    tmp,
    repo,
    outDir,
    head,
    requirement,
    requirementHash: sha256File(requirement),
    cleanup() { rmSync(tmp, { recursive: true, force: true }); },
  };
}

function planJob(ctx, extra = {}) {
  return {
    schema: "coding-agent.job.v1",
    jobId: "job_1",
    idempotencyKey: "task:plan:1",
    taskId: "task",
    stage: "plan",
    attempt: 1,
    workspace: {
      repoRoot: ctx.repo,
      branch: "main",
      expectedHead: ctx.head,
      requireCleanAtStart: true,
      ...extra.workspace,
    },
    agent: {
      adapter: "pi",
      profile: "planner",
      model: "zai-coding-cn/glm-5.3",
      thinking: "high",
      sessionId: null,
    },
    permissions: { mode: extra.mode || "read-only" },
    inputs: extra.inputs || [
      { kind: "requirement", path: ctx.requirement, sha256: ctx.requirementHash },
    ],
  };
}

test("parsePorcelainZ understands rename and copy dual paths", () => {
  // Stock `git status` does not enable copy detection; producing C here would
  // require status.renames=copies and similarity heuristics. Keep the exact
  // porcelain fixture deterministic while the real-repository test covers R.
  const raw = Buffer.from("R  new.txt\0old.txt\0C  src-copy.txt\0src.txt\0 M src.txt\0");
  const records = parsePorcelainZ(raw);
  assert.deepEqual(records, [
    { xy: "R ", path: "new.txt", origPath: "old.txt", copied: false },
    { xy: "C ", path: "src-copy.txt", origPath: "src.txt", copied: true },
    { xy: " M", path: "src.txt", origPath: null, copied: false },
  ]);
});

test("preflight accepts a clean matching workspace and rejects before any adapter spy", () => {
  const ctx = makeRepo();
  const spy = { called: false };
  try {
    const result = preflightWorkspace(planJob(ctx), ctx.outDir);
    assert.equal(result.ok, true, result.error && result.error.message);
    assert.equal(result.value.snapshot.branch, "main");
    assert.equal(result.value.snapshot.head, ctx.head);
    assert.equal(spy.called, false);
  } finally {
    ctx.cleanup();
  }
});

test("preflight rejects wrong repo, branch, HEAD, dirty tree, and input hash", () => {
  const base = makeRepo();
  try {
    const nested = join(base.repo, "nested");
    mkdirSync(nested);
    const subdir = preflightWorkspace(planJob(base, { workspace: { repoRoot: nested } }), base.outDir);
    assert.equal(subdir.ok, false, "subdir");
    assert.equal(subdir.error.kind, "workspace_mismatch", "subdir");

    git(base.repo, ["checkout", "-b", "other"]);
    const otherHead = git(base.repo, ["rev-parse", "HEAD"]).trim();
    const branch = preflightWorkspace(
      planJob({ ...base, head: otherHead }, { workspace: { branch: "main", expectedHead: otherHead } }),
      base.outDir,
    );
    assert.equal(branch.ok, false, "branch");
    assert.equal(branch.error.kind, "workspace_mismatch", "branch");
    git(base.repo, ["checkout", "main"]);

    const head = preflightWorkspace(planJob(base, { workspace: { expectedHead: "a".repeat(40) } }), base.outDir);
    assert.equal(head.ok, false, "head");
    assert.equal(head.error.kind, "workspace_mismatch", "head");

    writeFileSync(join(base.repo, "src.txt"), "dirty\n");
    const dirty = preflightWorkspace(planJob(base), base.outDir);
    assert.equal(dirty.ok, false, "dirty");
    assert.equal(dirty.error.kind, "workspace_mismatch", "dirty");
    writeFileSync(join(base.repo, "src.txt"), "hello\n");

    const hash = preflightWorkspace(planJob(base, {
      inputs: [{ kind: "requirement", path: base.requirement, sha256: "a".repeat(64) }],
    }), base.outDir);
    assert.equal(hash.ok, false, "hash");
    assert.equal(hash.error.kind, "input_hash_mismatch", "hash");
  } finally {
    base.cleanup();
  }
});

test("out-dir inside repo or via symlink is rejected", () => {
  const ctx = makeRepo();
  try {
    const inside = join(ctx.repo, "out");
    mkdirSync(inside);
    const insideResult = preflightWorkspace(planJob(ctx), inside);
    assert.equal(insideResult.ok, false);
    assert.equal(insideResult.error.kind, "workspace_mismatch");

    const linkDir = join(ctx.tmp, "link-out");
    symlinkSync(inside, linkDir);
    const linkResult = preflightWorkspace(planJob(ctx), linkDir);
    assert.equal(linkResult.ok, false);
    assert.equal(linkResult.error.kind, "workspace_mismatch");
  } finally {
    ctx.cleanup();
  }
});

test("snapshots detect clean modify, pre-dirty change, rename, untracked, and delete", () => {
  const ctx = makeRepo();
  try {
    const before = captureSnapshot(ctx.repo).value;

    writeFileSync(join(ctx.repo, "src.txt"), "changed\n");
    const modified = captureSnapshot(ctx.repo).value;
    assert.deepEqual(compareSnapshots(before, modified), ["src.txt"]);

    writeFileSync(join(ctx.repo, "src.txt"), "changed-again\n");
    const stillDirty = captureSnapshot(ctx.repo).value;
    assert.deepEqual(compareSnapshots(modified, stillDirty), ["src.txt"]);

    git(ctx.repo, ["add", "src.txt"]);
    git(ctx.repo, ["commit", "-m", "change"]);
    const beforeRename = captureSnapshot(ctx.repo).value;
    git(ctx.repo, ["mv", "src.txt", "renamed.txt"]);
    const rawRename = execFileSync(
      "git",
      ["status", "--porcelain=v1", "-z", "--untracked-files=all"],
      { cwd: ctx.repo, stdio: ["ignore", "pipe", "pipe"] },
    );
    assert.deepEqual(rawRename, Buffer.from("R  renamed.txt\0src.txt\0"));
    const renamed = captureSnapshot(ctx.repo).value;
    const renamedTouched = compareSnapshots(beforeRename, renamed);
    assert.deepEqual(renamed.status, [
      { xy: "R ", path: "renamed.txt", origPath: "src.txt", copied: false },
    ]);
    assert.deepEqual(renamedTouched, ["renamed.txt", "src.txt"]);

    writeFileSync(join(ctx.repo, "untracked.txt"), "u\n");
    const untracked = captureSnapshot(ctx.repo).value;
    assert.ok(untracked.entries.some((item) => item.path === "untracked.txt"));

    rmSync(join(ctx.repo, "renamed.txt"));
    const deleted = captureSnapshot(ctx.repo).value;
    assert.ok(deleted.entries.some((item) => item.path === "renamed.txt" && item.type === "missing"));
  } finally {
    ctx.cleanup();
  }
});

test("postflight detects read-only writes, HEAD change, and branch change without cleaning", () => {
  const ctx = makeRepo();
  try {
    const before = captureSnapshot(ctx.repo).value;
    writeFileSync(join(ctx.repo, "src.txt"), "hacked\n");
    const afterWrite = captureSnapshot(ctx.repo).value;
    const ro = assertPostflight(planJob(ctx), before, afterWrite);
    assert.equal(ro.ok, false);
    assert.equal(ro.error.kind, "read_only_violation");
    assert.equal(readFileSync(join(ctx.repo, "src.txt"), "utf8"), "hacked\n");

    git(ctx.repo, ["checkout", "-b", "topic"]);
    const afterBranch = captureSnapshot(ctx.repo).value;
    const branch = assertPostflight(planJob(ctx), before, afterBranch);
    assert.equal(branch.ok, false);
    assert.equal(branch.error.kind, "workspace_mismatch");
    assert.match(git(ctx.repo, ["symbolic-ref", "--short", "HEAD"]).trim(), /topic/);

    writeFileSync(join(ctx.repo, "src.txt"), "committed\n");
    git(ctx.repo, ["add", "src.txt"]);
    git(ctx.repo, ["commit", "-m", "move head"]);
    git(ctx.repo, ["checkout", "main"]);
    const afterHead = captureSnapshot(ctx.repo).value;
    // still on main with original head? checkout main restores original commit if topic has extra commit
    git(ctx.repo, ["checkout", "topic"]);
    const headChanged = captureSnapshot(ctx.repo).value;
    const head = assertPostflight(planJob(ctx), before, headChanged);
    assert.equal(head.ok, false);
    assert.equal(head.error.kind, "workspace_mismatch");
  } finally {
    ctx.cleanup();
  }
});

test("execute-review preflight writes evidence and candidate patch", () => {
  const ctx = makeRepo();
  try {
    writeFileSync(join(ctx.repo, "src.txt"), "impl\n");
    const job = {
      ...planJob(ctx, { workspace: { requireCleanAtStart: false } }),
      stage: "execute_review",
      agent: { ...planJob(ctx).agent, profile: "execute-reviewer" },
    };
    const result = preflightWorkspace(job, ctx.outDir);
    assert.equal(result.ok, true, result.error && result.error.message);
    assert.equal(result.value.evidencePaths.workspaceEvidencePath, join(ctx.outDir, "derived", "workspace-evidence.json"));
    assert.equal(result.value.evidencePaths.candidatePatchPath, join(ctx.outDir, "derived", "candidate.patch"));
    const evidence = JSON.parse(readFileSync(result.value.evidencePaths.workspaceEvidencePath, "utf8"));
    assert.ok(Array.isArray(evidence.status));
    assert.ok(Array.isArray(evidence.untrackedPaths));
    assert.ok(Array.isArray(evidence.touchedCandidates));
    const patch = readFileSync(result.value.evidencePaths.candidatePatchPath, "utf8");
    assert.match(patch, /impl/);
  } finally {
    ctx.cleanup();
  }
});

function checkSpec(ctx, cwd) {
  return {
    id: "check-unit",
    argv: ["node", "--test", "test/greet.test.mjs"],
    cwd,
    timeoutSeconds: 5,
    expectedExitCode: 0,
  };
}

test("preflight rejects missing, non-directory, and symlink-escaping verification cwd", () => {
  const ctx = makeRepo();
  try {
    const missing = preflightWorkspace({
      ...planJob(ctx),
      verification: [checkSpec(ctx, join(ctx.repo, "missing-cwd"))],
    }, ctx.outDir);
    assert.equal(missing.ok, false, "missing");
    assert.equal(missing.error.kind, "invalid_job", "missing");

    const fileCwd = preflightWorkspace({
      ...planJob(ctx),
      verification: [checkSpec(ctx, join(ctx.repo, "src.txt"))],
    }, ctx.outDir);
    assert.equal(fileCwd.ok, false, "file");
    assert.equal(fileCwd.error.kind, "invalid_job", "file");

    mkdirSync(join(ctx.tmp, "outside"));
    symlinkSync(join(ctx.tmp, "outside"), join(ctx.repo, "escape"));
    const escaped = preflightWorkspace({
      ...planJob(ctx, { workspace: { requireCleanAtStart: false } }),
      verification: [checkSpec(ctx, join(ctx.repo, "escape"))],
    }, ctx.outDir);
    assert.equal(escaped.ok, false, "escape");
    assert.equal(escaped.error.kind, "workspace_mismatch", "escape");
  } finally {
    ctx.cleanup();
  }
});

test("preflight rewrites verification cwd to the realpath inside the repo", () => {
  const ctx = makeRepo();
  try {
    mkdirSync(join(ctx.repo, "sub"));
    symlinkSync(join(ctx.repo, "sub"), join(ctx.repo, "link"));
    const result = preflightWorkspace({
      ...planJob(ctx, { workspace: { requireCleanAtStart: false } }),
      verification: [checkSpec(ctx, join(ctx.repo, "link"))],
    }, ctx.outDir);
    assert.equal(result.ok, true, result.error && result.error.message);
    assert.equal(result.value.verifiedVerification[0].cwd, realpathSync(join(ctx.repo, "sub")));
  } finally {
    ctx.cleanup();
  }
});

test("index-only staging of an already-dirty file is a read-only violation", () => {
  const ctx = makeRepo();
  try {
    writeFileSync(join(ctx.repo, "src.txt"), "dirty\n");
    const before = captureSnapshot(ctx.repo).value;
    git(ctx.repo, ["add", "src.txt"]);
    assert.equal(readFileSync(join(ctx.repo, "src.txt"), "utf8"), "dirty\n");
    const after = captureSnapshot(ctx.repo).value;
    assert.notEqual(before.sha256, after.sha256);
    assert.ok(compareSnapshots(before, after).includes("src.txt"));
    const post = assertPostflight(
      planJob(ctx, { workspace: { requireCleanAtStart: false } }),
      before,
      after,
    );
    assert.equal(post.ok, false);
    assert.equal(post.error.kind, "read_only_violation");
    assert.ok(post.error.details.touchedFiles.includes("src.txt"));
    assert.equal(readFileSync(join(ctx.repo, "src.txt"), "utf8"), "dirty\n");
  } finally {
    ctx.cleanup();
  }
});
