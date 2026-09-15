import { spawn } from "node:child_process";
import { mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";

function safeCheckId(id) {
  return id.replace(/[^A-Za-z0-9._-]+/g, "-");
}

function runOneCheck(check, { cwd, stdoutPath, stderrPath, onSpawn }) {
  return new Promise((resolve) => {
    const startedAt = new Date().toISOString();
    writeFileSync(stdoutPath, "");
    writeFileSync(stderrPath, "");
    let stdout = "";
    let stderr = "";
    let settled = false;
    let timedOut = false;
    let child;
    try {
      child = spawn(check.argv[0], check.argv.slice(1), {
        cwd: check.cwd || cwd,
        env: process.env,
        shell: false,
        stdio: ["ignore", "pipe", "pipe"],
        detached: true,
      });
    } catch (error) {
      const finishedAt = new Date().toISOString();
      return resolve({
        id: check.id,
        status: error.code === "ENOENT" ? "unavailable" : "failed",
        argv: check.argv,
        cwd: check.cwd,
        expectedExitCode: check.expectedExitCode,
        exitCode: null,
        signal: null,
        startedAt,
        finishedAt,
        stdoutPath,
        stderrPath,
      });
    }
    onSpawn?.(child);
    child.stdout.on("data", (chunk) => {
      stdout += chunk;
      writeFileSync(stdoutPath, stdout);
    });
    child.stderr.on("data", (chunk) => {
      stderr += chunk;
      writeFileSync(stderrPath, stderr);
    });
    const timeoutMs = check.timeoutSeconds * 1000;
    const killTimer = setTimeout(() => {
      timedOut = true;
      try { process.kill(-child.pid, "SIGTERM"); } catch { child.kill("SIGTERM"); }
      setTimeout(() => {
        if (!settled) {
          try { process.kill(-child.pid, "SIGKILL"); } catch { child.kill("SIGKILL"); }
        }
      }, 200);
    }, timeoutMs);

    const finish = (exitCode, signal) => {
      if (settled) return;
      settled = true;
      clearTimeout(killTimer);
      const finishedAt = new Date().toISOString();
      let status = "failed";
      if (timedOut) status = "timed_out";
      else if (exitCode === check.expectedExitCode) status = "passed";
      resolve({
        id: check.id,
        status,
        argv: check.argv,
        cwd: check.cwd,
        expectedExitCode: check.expectedExitCode,
        exitCode,
        signal,
        startedAt,
        finishedAt,
        stdoutPath,
        stderrPath,
      });
    };
    child.on("error", (error) => {
      finish(null, null);
      if (error.code === "ENOENT") {
        /* status set below via exit */
      }
    });
    child.on("close", (code, signal) => {
      if (child.exitCode === null && child.signalCode === null && !timedOut) {
        finish(null, signal ?? null);
        return;
      }
      finish(code, signal ?? null);
    });
  });
}

export async function runChecks(verification, context) {
  const { outDir, cwd, events } = context;
  const checksDir = join(outDir, "checks");
  mkdirSync(checksDir, { recursive: true });
  const results = [];
  for (const check of verification) {
    const safeId = safeCheckId(check.id);
    const stdoutPath = join(checksDir, `${safeId}.stdout.log`);
    const stderrPath = join(checksDir, `${safeId}.stderr.log`);
    events?.append?.("check_started", { id: check.id, argv: check.argv });
    const result = await runOneCheck(check, { cwd, stdoutPath, stderrPath });
    if (result.exitCode === null && result.status === "failed" && result.signal === null) {
      result.status = "unavailable";
    }
    events?.append?.("check_finished", { id: result.id, status: result.status });
    results.push(result);
  }
  return results;
}
