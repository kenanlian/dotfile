import { test } from "node:test";
import assert from "node:assert/strict";
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { runChecks } from "../src/checks.mjs";

test("checks record pass, nonzero, timeout, missing executable, and continue after failure", async () => {
  const tmp = mkdtempSync(join(tmpdir(), "checks-"));
  mkdirSync(join(tmp, "out"));
  const events = [];
  const verification = [
    {
      id: "pass",
      argv: [process.execPath, "-e", "process.stdout.write('ok'); process.exit(0)"],
      cwd: tmp,
      timeoutSeconds: 5,
      expectedExitCode: 0,
    },
    {
      id: "fail:unit",
      argv: [process.execPath, "-e", "process.stderr.write('boom'); process.exit(2)"],
      cwd: tmp,
      timeoutSeconds: 5,
      expectedExitCode: 0,
    },
    {
      id: "timeout",
      argv: [process.execPath, "-e", "setTimeout(() => {}, 10_000)"],
      cwd: tmp,
      timeoutSeconds: 1,
      expectedExitCode: 0,
    },
    {
      id: "missing",
      argv: [join(tmp, "no-such-bin")],
      cwd: tmp,
      timeoutSeconds: 5,
      expectedExitCode: 0,
    },
  ];
  try {
    const results = await runChecks(verification, {
      outDir: join(tmp, "out"),
      cwd: tmp,
      events: { append: (type, data) => events.push({ type, data }) },
    });
    assert.equal(results.length, 4);
    assert.equal(results[0].status, "passed");
    assert.equal(results[1].status, "failed");
    assert.equal(results[1].id, "fail:unit");
    assert.equal(results[2].status, "timed_out");
    assert.ok(results[3].status === "unavailable" || results[3].status === "failed");
    assert.equal(readFileSync(results[0].stdoutPath, "utf8"), "ok");
    assert.equal(readFileSync(results[1].stderrPath, "utf8"), "boom");
    assert.ok(existsSync(join(tmp, "out", "checks", "fail-unit.stderr.log")));
    assert.ok(events.some((item) => item.type === "check_started"));
    assert.equal(events.filter((item) => item.type === "check_finished").length, 4);
  } finally {
    rmSync(tmp, { recursive: true, force: true });
  }
});
