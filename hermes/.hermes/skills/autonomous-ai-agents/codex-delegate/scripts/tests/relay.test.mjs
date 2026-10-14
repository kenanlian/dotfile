import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { chmodSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";

const RELAY = join(dirname(fileURLToPath(import.meta.url)), "..", "relay.mjs");

function setup() {
  const tmp = mkdtempSync(join(tmpdir(), "codex-relay-test-"));
  const bin = join(tmp, "bin");
  const repo = join(tmp, "repo");
  mkdirSync(bin);
  mkdirSync(repo);
  const stub = join(bin, "stub.mjs");
  writeFileSync(stub, `
import { readFileSync, writeFileSync } from "node:fs";
const argv = process.argv.slice(2);
if (argv.includes("--version")) { console.log("codex-test"); process.exit(0); }
const brief = readFileSync(0, "utf8");
writeFileSync(process.env.STUB_DUMP, JSON.stringify({argv, brief}));
writeFileSync(argv[argv.indexOf("-o") + 1], "test final");
console.log(JSON.stringify({type:"thread.started", thread_id:"test-thread"}));
process.exit(Number(process.env.STUB_EXIT || 0));
`);
  const executable = join(bin, "codex");
  writeFileSync(executable, `#!/bin/sh\nexec ${JSON.stringify(process.execPath)} ${JSON.stringify(stub)} "$@"\n`);
  chmodSync(executable, 0o755);
  const dumpPath = join(tmp, "dump.json");
  const env = { ...process.env, PATH: `${bin}:${process.env.PATH}`, STUB_DUMP: dumpPath };
  return {
    tmp, repo, env,
    run(extra = [], overrides = {}) {
      const out = mkdtempSync(join(tmp, "out-"));
      const child = spawnSync(process.execPath, [RELAY, "--cd", repo, "--out-dir", out, ...extra], {
        env: { ...env, ...overrides }, input: "read-only task: do not change any files\n", encoding: "utf8", timeout: 15000,
      });
      const result = JSON.parse(readFileSync(join(out, "result.json"), "utf8"));
      const dump = JSON.parse(readFileSync(dumpPath, "utf8"));
      return { child, result, ...dump };
    },
    cleanup() { rmSync(tmp, {recursive:true, force:true}); },
  };
}

test("explicit sandbox overrides apply to fresh and exact-thread resumes", () => {
  const ctx = setup();
  try {
    for (const extra of [["--read-only"], ["--sandbox", "workspace-write"], ["--sandbox", "read-only", "--session", "exact-thread"]]) {
      const {child, result, argv} = ctx.run(extra);
      assert.equal(child.status, 0, child.stderr);
      assert.equal(argv.includes("--dangerously-bypass-approvals-and-sandbox"), false);
      const expected = extra[0] === "--read-only" ? "read-only" : extra[1];
      assert.equal(argv[argv.indexOf("-s") + 1], expected);
      assert.equal(result.sandbox, expected);
      if (extra.includes("--session")) assert.ok(argv.indexOf("-s") < argv.indexOf("resume"));
    }
  } finally { ctx.cleanup(); }
});

test("documentation and help contain no retired development workflow", () => {
  const skill = join(dirname(RELAY), "..");
  for (const file of ["SKILL.md", "references/dispatch-and-poll.md", "scripts/relay.mjs"]) {
    const content = readFileSync(join(skill, file), "utf8");
    assert.doesNotMatch(content, /Development-Orchestrator|Origin grounding|write-plan|execute-plan|Card contract|Dispatcher worker|delegate-setup|review-and-land|re-run the project gates yourself|committing is always the/i);
  }
});

test("retired fleet lane option is rejected without loading another skill", () => {
  const child = spawnSync(process.execPath, [RELAY, "--lane", "old-lane"], {encoding:"utf8"});
  assert.equal(child.status, 2);
  assert.match(child.stderr, /unknown option: --lane/);
});

test("fresh and resumed runs default to full permissions", () => {
  const ctx = setup();
  try {
    for (const extra of [[], ["--session", "exact-thread"], ["--resume-last"]]) {
      const {child, result, argv, brief} = ctx.run(extra);
      assert.equal(child.status, 0, child.stderr);
      assert.equal(argv.includes("--dangerously-bypass-approvals-and-sandbox"), true);
      assert.equal(argv.includes("-s"), false);
      assert.equal(result.sandbox, "danger-full-access");
      assert.equal(result.threadId, "test-thread");
      assert.equal(result.status, "completed");
      assert.equal(result.finalMessage, "test final");
      assert.equal(argv.includes(brief), false);
      if (extra[0] === "--session") assert.equal(argv[argv.indexOf("resume") + 1], "exact-thread");
      if (extra[0] === "--resume-last") assert.equal(argv[argv.indexOf("resume") + 1], "--last");
    }
  } finally { ctx.cleanup(); }
});
