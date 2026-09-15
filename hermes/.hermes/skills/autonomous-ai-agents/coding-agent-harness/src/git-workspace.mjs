import {
  execFileSync,
} from "node:child_process";
import {
  existsSync,
  lstatSync,
  mkdirSync,
  readFileSync,
  readlinkSync,
  realpathSync,
  statSync,
  writeFileSync,
} from "node:fs";
import { dirname, isAbsolute, join } from "node:path";
import { typedError } from "./contracts.mjs";
import {
  canonicalJson,
  isPathInside,
  nearestExistingPath,
  sha256File,
  sha256Text,
} from "./util.mjs";

const GIT_TIMEOUT_MS = 15_000;
const GIT_MAX_BUFFER = 64 * 1024 * 1024;

function fail(kind, path, message, details) {
  return { ok: false, error: typedError(kind, path, message, details) };
}

function ok(value) {
  return { ok: true, value };
}

function git(repoRoot, args) {
  return execFileSync("git", args, {
    cwd: repoRoot,
    encoding: "buffer",
    timeout: GIT_TIMEOUT_MS,
    maxBuffer: GIT_MAX_BUFFER,
    killSignal: "SIGKILL",
    stdio: ["ignore", "pipe", "pipe"],
    shell: false,
  });
}

function gitText(repoRoot, args) {
  return git(repoRoot, args).toString("utf8").trimEnd();
}

export function parsePorcelainZ(buffer) {
  const raw = Buffer.isBuffer(buffer) ? buffer.toString("utf8") : String(buffer);
  const records = [];
  if (!raw) return records;
  const parts = raw.split("\0");
  let i = 0;
  while (i < parts.length) {
    const entry = parts[i];
    if (!entry) {
      i += 1;
      continue;
    }
    const xy = entry.slice(0, 2);
    const path = entry.charAt(2) === " " ? entry.slice(3) : entry.slice(2);
    const renameOrCopy = xy[0] === "R" || xy[0] === "C";
    if (renameOrCopy) {
      records.push({
        xy,
        path,
        origPath: parts[i + 1],
        copied: xy[0] === "C",
      });
      i += 2;
    } else {
      records.push({ xy, path, origPath: null, copied: false });
      i += 1;
    }
  }
  return records;
}

function describePath(repoRoot, relPath) {
  const abs = join(repoRoot, relPath);
  if (!existsSync(abs)) {
    return { path: relPath, type: "missing", mode: null, sha256: null };
  }
  const st = lstatSync(abs);
  const mode = (st.mode & 0o177777).toString(8).padStart(6, "0");
  if (st.isSymbolicLink()) {
    return {
      path: relPath,
      type: "symlink",
      mode,
      sha256: sha256Text(readlinkSync(abs)),
    };
  }
  if (st.isDirectory()) {
    return { path: relPath, type: "directory", mode, sha256: null };
  }
  if (st.isFile()) {
    return { path: relPath, type: "file", mode, sha256: sha256File(abs) };
  }
  return { path: relPath, type: "other", mode, sha256: null };
}

export function captureSnapshot(repoRoot) {
  let toplevel;
  try {
    toplevel = realpathSync(gitText(repoRoot, ["rev-parse", "--show-toplevel"]));
  } catch (error) {
    return fail("workspace_mismatch", "/workspace/repoRoot", "not a git repository", {
      stderr: String(error.stderr || error.message || error),
    });
  }
  let branch;
  try {
    branch = gitText(repoRoot, ["symbolic-ref", "--short", "HEAD"]);
  } catch {
    return fail("workspace_mismatch", "/workspace/branch", "detached HEAD is not allowed");
  }
  const head = gitText(repoRoot, ["rev-parse", "HEAD"]);
  const porcelain = git(repoRoot, ["status", "--porcelain=v1", "-z", "--untracked-files=all"]);
  const status = parsePorcelainZ(porcelain);
  const paths = new Set();
  for (const record of status) {
    paths.add(record.path);
    if (record.origPath) paths.add(record.origPath);
  }
  const entries = [...paths]
    .sort()
    .map((path) => {
      const statusRecord = status.find((item) => item.path === path || item.origPath === path) || null;
      return {
        ...describePath(repoRoot, path),
        xy: statusRecord?.xy ?? null,
        origPath: statusRecord?.origPath && statusRecord.path === path ? statusRecord.origPath : null,
        copied: Boolean(statusRecord?.copied),
      };
    });
  const snapshot = { branch, head, toplevel, entries, status };
  return ok({
    ...snapshot,
    sha256: sha256Text(canonicalJson({
      branch: snapshot.branch,
      head: snapshot.head,
      entries: snapshot.entries.map((item) => ({
        path: item.path,
        type: item.type,
        mode: item.mode,
        sha256: item.sha256,
        xy: item.xy ?? null,
        origPath: item.origPath ?? null,
        copied: Boolean(item.copied),
      })),
      status: snapshot.status.map((item) => ({
        xy: item.xy,
        path: item.path,
        origPath: item.origPath,
        copied: Boolean(item.copied),
      })),
    })),
  });
}

export function compareSnapshots(before, after) {
  const beforeMap = new Map(before.entries.map((item) => [item.path, item]));
  const afterMap = new Map(after.entries.map((item) => [item.path, item]));
  const paths = new Set([...beforeMap.keys(), ...afterMap.keys()]);
  const touched = [];
  for (const path of paths) {
    const left = beforeMap.get(path);
    const right = afterMap.get(path);
    if (!left || !right) {
      touched.push(path);
      continue;
    }
    if (
      left.type !== right.type
      || left.mode !== right.mode
      || left.sha256 !== right.sha256
      || left.xy !== right.xy
      || left.origPath !== right.origPath
      || Boolean(left.copied) !== Boolean(right.copied)
    ) {
      touched.push(path);
    }
  }
  return [...new Set(touched)].sort();
}

export function assertOutDirOutsideRepo(outDir, repoRoot) {
  if (!isAbsolute(outDir)) {
    return fail("invalid_job", "/outDir", "out-dir must be an absolute path");
  }
  const repoReal = realpathSync(repoRoot);
  if (isPathInside(outDir, repoReal)) {
    return fail("workspace_mismatch", "/outDir", "out-dir must not be located inside repoRoot");
  }
  const existing = nearestExistingPath(outDir);
  const existingReal = realpathSync(existing);
  if (isPathInside(existingReal, repoReal)) {
    return fail("workspace_mismatch", "/outDir", "out-dir resolves inside repoRoot");
  }
  if (existsSync(outDir)) {
    const outReal = realpathSync(outDir);
    if (isPathInside(outReal, repoReal)) {
      return fail("workspace_mismatch", "/outDir", "out-dir realpath is inside repoRoot");
    }
  }
  return ok(true);
}

function verifyInputs(inputs) {
  for (let i = 0; i < inputs.length; i += 1) {
    const item = inputs[i];
    const path = `/inputs/${i}`;
    if (!existsSync(item.path)) {
      return fail("input_hash_mismatch", `${path}/path`, `input file not found: ${item.path}`);
    }
    let st;
    try {
      st = lstatSync(item.path);
    } catch (error) {
      return fail("input_hash_mismatch", `${path}/path`, `input file not readable: ${item.path}`, {
        message: String(error.message || error),
      });
    }
    const readablePath = st.isSymbolicLink() ? realpathSync(item.path) : item.path;
    try {
      const digest = sha256File(readablePath);
      if (digest !== item.sha256) {
        return fail(
          "input_hash_mismatch",
          `${path}/sha256`,
          `input hash mismatch for ${item.path}`,
          { expected: item.sha256, actual: digest },
        );
      }
    } catch (error) {
      return fail("input_hash_mismatch", `${path}/path`, `input file not readable: ${item.path}`, {
        message: String(error.message || error),
      });
    }
  }
  return ok(true);
}

export function writeExecuteReviewEvidence(job, outDir, snapshot) {
  const derivedDir = join(outDir, "derived");
  mkdirSync(derivedDir, { recursive: true });
  const evidencePath = join(derivedDir, "workspace-evidence.json");
  const patchPath = join(derivedDir, "candidate.patch");
  const untrackedPaths = snapshot.status
    .filter((item) => item.xy === "??")
    .map((item) => item.path)
    .sort();
  const evidence = {
    branch: snapshot.branch,
    head: snapshot.head,
    status: snapshot.status,
    untrackedPaths,
    touchedCandidates: snapshot.entries.map((item) => item.path).sort(),
  };
  writeFileSync(evidencePath, canonicalJson(evidence));
  const patch = git(job.workspace.repoRoot, ["diff", "--binary", job.workspace.expectedHead, "--"]);
  writeFileSync(patchPath, patch);
  return { workspaceEvidencePath: evidencePath, candidatePatchPath: patchPath };
}

export function preflightWorkspace(job, outDir) {
  let repoReal;
  try {
    repoReal = realpathSync(job.workspace.repoRoot);
  } catch {
    return fail("workspace_mismatch", "/workspace/repoRoot", "repoRoot is not an existing directory");
  }
  const outErr = assertOutDirOutsideRepo(outDir, repoReal);
  if (!outErr.ok) return outErr;

  const snapshotResult = captureSnapshot(repoReal);
  if (!snapshotResult.ok) return snapshotResult;
  const snapshot = snapshotResult.value;
  if (snapshot.toplevel !== repoReal) {
    return fail(
      "workspace_mismatch",
      "/workspace/repoRoot",
      "repoRoot realpath must equal the git top-level",
      { toplevel: snapshot.toplevel, repoRoot: repoReal },
    );
  }
  if (snapshot.branch !== job.workspace.branch) {
    return fail(
      "workspace_mismatch",
      "/workspace/branch",
      `branch ${snapshot.branch} does not match ${job.workspace.branch}`,
    );
  }
  if (snapshot.head !== job.workspace.expectedHead) {
    return fail(
      "workspace_mismatch",
      "/workspace/expectedHead",
      `HEAD ${snapshot.head} does not match expectedHead`,
    );
  }
  if (job.workspace.requireCleanAtStart && snapshot.status.length > 0) {
    return fail("workspace_mismatch", "/workspace/requireCleanAtStart", "working tree is not clean");
  }
  const inputErr = verifyInputs(job.inputs);
  if (!inputErr.ok) return inputErr;

  const cwdErr = verifyVerificationCwds(job.verification, repoReal);
  if (!cwdErr.ok) return cwdErr;

  let evidencePaths = null;
  if (job.stage === "execute_review") {
    evidencePaths = writeExecuteReviewEvidence(job, outDir, snapshot);
  }
  return ok({ snapshot, evidencePaths, verifiedVerification: cwdErr.value });
}

export function assertPostflight(job, before, after) {
  if (after.branch !== before.branch || after.branch !== job.workspace.branch) {
    return fail(
      "workspace_mismatch",
      "/workspace/branch",
      "branch changed during the run; leaving the working tree as-is",
      { before: before.branch, after: after.branch },
    );
  }
  if (after.head !== before.head || after.head !== job.workspace.expectedHead) {
    return fail(
      "workspace_mismatch",
      "/workspace/expectedHead",
      "HEAD changed during the run; leaving the working tree as-is",
      { before: before.head, after: after.head },
    );
  }
  const touchedFiles = compareSnapshots(before, after);
  if (job.permissions.mode === "read-only" && touchedFiles.length > 0) {
    return fail(
      "read_only_violation",
      "/permissions/mode",
      "read-only stage produced a net workspace change",
      { touchedFiles },
    );
  }
  return ok({ touchedFiles });
}

export function verifyVerificationCwds(verification, repoReal) {
  const verified = [];
  for (let i = 0; i < (verification || []).length; i += 1) {
    const item = verification[i];
    const path = `/verification/${i}/cwd`;
    if (!existsSync(item.cwd)) {
      return fail("invalid_job", path, `verification cwd not found: ${item.cwd}`);
    }
    let real;
    try {
      real = realpathSync(item.cwd);
    } catch (error) {
      return fail("invalid_job", path, `verification cwd is not resolvable: ${item.cwd}`, {
        message: String(error.message || error),
      });
    }
    let st;
    try {
      st = statSync(real);
    } catch (error) {
      return fail("invalid_job", path, `verification cwd is not readable: ${item.cwd}`, {
        message: String(error.message || error),
      });
    }
    if (!st.isDirectory()) {
      return fail("invalid_job", path, `verification cwd is not a directory: ${item.cwd}`);
    }
    if (!isPathInside(real, repoReal)) {
      return fail(
        "workspace_mismatch",
        path,
        "verification cwd realpath must equal repoRoot or be inside it",
        { cwd: item.cwd, realpath: real, repoRoot: repoReal },
      );
    }
    verified.push({ ...item, cwd: real });
  }
  return ok(verified);
}
