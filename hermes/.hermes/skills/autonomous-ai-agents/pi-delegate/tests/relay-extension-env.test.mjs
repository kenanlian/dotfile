import { test } from "node:test";
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import {
  existsSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const TEST_DIR = dirname(fileURLToPath(import.meta.url));
const RELAY = join(TEST_DIR, "..", "scripts", "relay.mjs");
const STUB = join(TEST_DIR, "fixtures", "stub-pi.mjs");

function dashEPaths(argv) {
  const paths = [];
  for (let i = 0; i < argv.length; i += 1) {
    if (argv[i] === "-e") paths.push(argv[i + 1]);
  }
  return paths;
}

function hermeticEnv(overrides = {}) {
  const env = { ...process.env, ...overrides };
  for (const key of Object.keys(env)) {
    if (key.startsWith("PI_AUTO_HANDOFF_") || (key.startsWith("PI_STUB_") && !(key in overrides))) {
      delete env[key];
    }
  }
  for (const [key, value] of Object.entries(overrides)) {
    if (value === undefined) delete env[key];
    else env[key] = value;
  }
  return env;
}

function runRelay(args, env) {
  return spawnSync(process.execPath, [RELAY, ...args], {
    env,
    encoding: "utf8",
    timeout: 30_000,
    stdio: ["ignore", "pipe", "pipe"],
  });
}

function setupRun() {
  const tmp = mkdtempSync(join(tmpdir(), "relay-extension-env-"));
  const workDir = join(tmp, "work");
  const outDir = join(tmp, "out");
  const dumpPath = join(tmp, "stub-dump.json");
  const delegateRoot = join(tmp, "delegate-agent");
  const extraRoot = join(tmp, "extra-ext");
  mkdirSync(workDir, { recursive: true });
  mkdirSync(outDir, { recursive: true });
  mkdirSync(delegateRoot, { recursive: true });
  mkdirSync(extraRoot, { recursive: true });
  writeFileSync(join(delegateRoot, "index.ts"), "export {};\n");
  writeFileSync(join(extraRoot, "index.ts"), "export {};\n");
  const briefPath = join(tmp, "brief.txt");
  writeFileSync(briefPath, "do the work\n");
  const env = hermeticEnv({
    PI_BIN: STUB,
    PI_DELEGATE_AGENT_ROOT: delegateRoot,
    PI_STUB_DUMP: dumpPath,
  });
  const args = ["--brief", briefPath, "--cd", workDir, "--out-dir", outDir];
  return {
    tmp, workDir, outDir, dumpPath, extraRoot, delegateRoot, env, args,
    cleanup() { rmSync(tmp, { recursive: true, force: true }); },
  };
}

test("--extension is appended as an extra -e and recorded in spawn.argv", () => {
  const ctx = setupRun();
  try {
    const spawned = runRelay([...ctx.args, "--extension", ctx.extraRoot], ctx.env);
    assert.equal(spawned.status, 0, spawned.stderr);
    const dump = JSON.parse(readFileSync(ctx.dumpPath, "utf8"));
    assert.deepEqual(dashEPaths(dump.argv), [ctx.delegateRoot, ctx.extraRoot]);
    const result = JSON.parse(readFileSync(join(ctx.outDir, "result.json"), "utf8"));
    assert.deepEqual(result.spawn.argv, dump.argv);
    assert.ok(Array.isArray(result.spawn.envKeys));
  } finally {
    ctx.cleanup();
  }
});

test("--extension fail-fast: relative or missing path exits 2 with no result", () => {
  const ctx = setupRun();
  try {
    const relative = runRelay([...ctx.args, "--extension", "relative/ext"], ctx.env);
    assert.equal(relative.status, 2, relative.stderr);
    assert.match(relative.stderr, /--extension must be an absolute path/);
    assert.equal(existsSync(join(ctx.outDir, "result.json")), false);

    const missing = runRelay([...ctx.args, "--extension", join(ctx.tmp, "no-such-ext")], ctx.env);
    assert.equal(missing.status, 2, missing.stderr);
    assert.match(missing.stderr, /--extension not found/);
  } finally {
    ctx.cleanup();
  }
});

test("--env injects child keys, audits key names only, and blacklists PATH/HOME", () => {
  const ctx = setupRun();
  try {
    const spawned = runRelay(
      [...ctx.args, "--env", "PI_HARNESS_EXPECT_EXTENSIONS=stage-submit", "--env", "FOO=secret-value"],
      ctx.env,
    );
    assert.equal(spawned.status, 0, spawned.stderr);
    const dump = JSON.parse(readFileSync(ctx.dumpPath, "utf8"));
    assert.equal(dump.expectExtensions, "stage-submit");
    const result = JSON.parse(readFileSync(join(ctx.outDir, "result.json"), "utf8"));
    assert.ok(result.spawn.envKeys.includes("FOO"));
    assert.ok(result.spawn.envKeys.includes("PI_HARNESS_EXPECT_EXTENSIONS"));
    const serialized = JSON.stringify(result);
    assert.doesNotMatch(serialized, /secret-value/);

    const blocked = runRelay([...ctx.args, "--env", "PATH=/tmp/evil"], ctx.env);
    assert.equal(blocked.status, 2, blocked.stderr);
    assert.match(blocked.stderr, /cannot override PATH/);

    const home = runRelay([...ctx.args, "--env", "HOME=/tmp/evil-home"], ctx.env);
    assert.equal(home.status, 2, home.stderr);
    assert.match(home.stderr, /cannot override HOME/);
  } finally {
    ctx.cleanup();
  }
});

test("--no-skills and --skill assemble -ns plus exact --skill paths", () => {
  const ctx = setupRun();
  try {
    const skillA = join(ctx.tmp, "skill-a");
    const skillB = join(ctx.tmp, "skill-b");
    mkdirSync(skillA);
    mkdirSync(skillB);
    writeFileSync(join(skillA, "SKILL.md"), "---\nname: skill-a\ndescription: a\n---\n");
    writeFileSync(join(skillB, "SKILL.md"), "---\nname: skill-b\ndescription: b\n---\n");
    const spawned = runRelay(
      [...ctx.args, "--no-skills", "--skill", skillA, "--skill", skillB],
      ctx.env,
    );
    assert.equal(spawned.status, 0, spawned.stderr);
    const dump = JSON.parse(readFileSync(ctx.dumpPath, "utf8"));
    assert.ok(dump.argv.includes("-ns"));
    const skills = [];
    for (let i = 0; i < dump.argv.length; i += 1) {
      if (dump.argv[i] === "--skill") skills.push(dump.argv[i + 1]);
    }
    assert.deepEqual(skills, [skillA, skillB]);
    const result = JSON.parse(readFileSync(join(ctx.outDir, "result.json"), "utf8"));
    assert.deepEqual(result.spawn.argv, dump.argv);

    const defaultRun = setupRun();
    try {
      const plain = runRelay(defaultRun.args, defaultRun.env);
      assert.equal(plain.status, 0, plain.stderr);
      const plainDump = JSON.parse(readFileSync(defaultRun.dumpPath, "utf8"));
      assert.ok(!plainDump.argv.includes("-ns"));
      assert.ok(!plainDump.argv.includes("--no-skills"));
      assert.ok(!plainDump.argv.includes("--skill"));
    } finally {
      defaultRun.cleanup();
    }
  } finally {
    ctx.cleanup();
  }
});

test("--skill fail-fast: relative, missing, or no SKILL.md exits 2", () => {
  const ctx = setupRun();
  try {
    const relative = runRelay([...ctx.args, "--skill", "skills/write-plan"], ctx.env);
    assert.equal(relative.status, 2, relative.stderr);
    assert.match(relative.stderr, /--skill must be an absolute path/);
    assert.equal(existsSync(join(ctx.outDir, "result.json")), false);

    const missing = runRelay([...ctx.args, "--skill", join(ctx.tmp, "no-such-skill")], ctx.env);
    assert.equal(missing.status, 2, missing.stderr);
    assert.match(missing.stderr, /--skill not found/);

    const emptyDir = join(ctx.tmp, "empty-skill");
    mkdirSync(emptyDir);
    const noMd = runRelay([...ctx.args, "--skill", emptyDir], ctx.env);
    assert.equal(noMd.status, 2, noMd.stderr);
    assert.match(noMd.stderr, /missing SKILL.md/);
  } finally {
    ctx.cleanup();
  }
});

function toolsArg(argv) {
  const index = argv.indexOf("--tools");
  return index >= 0 ? argv[index + 1] : null;
}

test("--extra-tools appends names onto the child --tools allowlist", () => {
  const ctx = setupRun();
  try {
    const spawned = runRelay([...ctx.args, "--write", "--extra-tools", "todo,todo"], ctx.env);
    assert.equal(spawned.status, 0, spawned.stderr);
    const dump = JSON.parse(readFileSync(ctx.dumpPath, "utf8"));
    const tools = (toolsArg(dump.argv) || "").split(",");
    assert.ok(tools.includes("todo"));
    assert.equal(tools.filter((name) => name === "todo").length, 1);
    assert.ok(tools.includes("bash"));
    assert.ok(!dump.argv.includes("--extra-tools"));
    const result = JSON.parse(readFileSync(join(ctx.outDir, "result.json"), "utf8"));
    assert.deepEqual(result.spawn.argv, dump.argv);
  } finally {
    ctx.cleanup();
  }
});

test("--extra-tools fail-fast: empty or invalid names exit 2 with no result", () => {
  const ctx = setupRun();
  try {
    const empty = runRelay([...ctx.args, "--extra-tools", ","], ctx.env);
    assert.equal(empty.status, 2, empty.stderr);
    assert.match(empty.stderr, /--extra-tools requires at least one tool name/);
    assert.equal(existsSync(join(ctx.outDir, "result.json")), false);

    const invalid = runRelay([...ctx.args, "--extra-tools", "todo!"], ctx.env);
    assert.equal(invalid.status, 2, invalid.stderr);
    assert.match(invalid.stderr, /--extra-tools invalid tool name: todo!/);
  } finally {
    ctx.cleanup();
  }
});
