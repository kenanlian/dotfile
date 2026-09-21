import { test } from "node:test";
import assert from "node:assert/strict";
import {
  mkdirSync,
  mkdtempSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { basename, dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { STAGES } from "../src/contracts.mjs";
import { buildRelayArgs, tryBuildRelayArgs } from "../src/pi-adapter.mjs";
import { compileBrief, SKILL_PREFIX_LINE } from "../src/prompts.mjs";
import {
  ENV_INJECT_BLACKLIST,
  STAGE_PROFILES_SCHEMA,
  STAGE_SUBMIT_EXTENSION_ID,
  assertExtensionRootsExist,
  assertProfileResourcesExist,
  assertSkillPathsExist,
  expectedExtensionsEnvValue,
  loadProfiles,
  resolveStageProfile,
  verifyArgvConsistency,
  verifyHarnessAttestation,
} from "../src/stage-profiles.mjs";
import {
  ATTESTATION_VERSION,
  EXPECT_EXTENSIONS_ENV,
  buildAttestationLine,
} from "../extensions/stage-submit/keys.mjs";
import {
  ENV_INJECT_BLACKLIST as RELAY_ENV_BLACKLIST,
  assembleChildInvocation,
  makeAutoHandoffState,
  parseArgs,
} from "../../pi-delegate/scripts/relay.mjs";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const EXT = join(ROOT, "extensions", "stage-submit");
const PROFILES_PATH = join(ROOT, "stage-profiles.json");

function dashE(argv) {
  const paths = [];
  for (let i = 0; i < argv.length; i += 1) {
    if (argv[i] === "-e") paths.push(argv[i + 1]);
  }
  return paths;
}

function skillPathsFromArgv(argv) {
  const paths = [];
  for (let i = 0; i < argv.length; i += 1) {
    if (argv[i] === "--skill") paths.push(argv[i + 1]);
  }
  return paths;
}

const STAGE_SKILL_NAMES = Object.freeze({
  plan: ["write-plan", "delegate-work"],
  plan_review: ["review-plan", "delegate-work"],
  implement: ["execute-plan", "delegate-work", "audit-persistence"],
  execute_review: ["review-execute-candidate", "delegate-work"],
  direct_implement: ["delegate-work"],
});

const STAGE_INLINE = Object.freeze({
  plan: "write-plan",
  plan_review: "review-plan",
  implement: "execute-plan",
  execute_review: "review-execute-candidate",
  direct_implement: null,
});

function seedSkillsRoot(root) {
  const names = [...new Set(Object.values(STAGE_SKILL_NAMES).flat())];
  for (const name of names) {
    const dir = join(root, "skills", name);
    mkdirSync(dir, { recursive: true });
    writeFileSync(join(dir, "SKILL.md"), `---\nname: ${name}\ndescription: test\n---\n`);
  }
  return root;
}

function fakeJob(stage, { planPath } = {}) {
  const profiles = {
    plan: "planner",
    plan_review: "plan-reviewer",
    implement: "implementer",
    execute_review: "execute-reviewer",
    direct_implement: "implementer",
  };
  const permissions = stage === "implement" || stage === "direct_implement" ? "write" : "read-only";
  const job = {
    jobId: `job_${stage}`,
    idempotencyKey: `task:${stage}:1`,
    taskId: "task_1",
    stage,
    attempt: 1,
    workspace: { repoRoot: "/tmp/repo", branch: "main", expectedHead: "a".repeat(40) },
    agent: {
      adapter: "pi",
      profile: profiles[stage],
      model: "zai-coding-cn/glm-5.3-flash",
      thinking: "high",
      sessionId: null,
    },
    permissions: { mode: permissions },
    inputs: stage === "implement"
      ? [{ kind: "plan", path: planPath, sha256: "a".repeat(64) }]
      : [],
    limits: { timeoutSeconds: null },
  };
  return job;
}

function withEnv(overrides, fn) {
  const previous = {};
  for (const key of Object.keys(overrides)) {
    previous[key] = process.env[key];
    if (overrides[key] === undefined) delete process.env[key];
    else process.env[key] = overrides[key];
  }
  try {
    return fn();
  } finally {
    for (const key of Object.keys(overrides)) {
      if (previous[key] === undefined) delete process.env[key];
      else process.env[key] = previous[key];
    }
  }
}

test("env-inject blacklist matches the relay copy", () => {
  assert.deepEqual([...ENV_INJECT_BLACKLIST], [...RELAY_ENV_BLACKLIST]);
});

test("loadProfiles reads the checked-in v1 manifest and maps every stage", () => {
  const loaded = loadProfiles(PROFILES_PATH);
  assert.equal(loaded.ok, true, loaded.error && loaded.error.message);
  assert.equal(loaded.value.schema, STAGE_PROFILES_SCHEMA);
  for (const stage of STAGES) {
    const profileId = loaded.value.stageToProfile[stage];
    assert.equal(typeof profileId, "string", stage);
    assert.ok(loaded.value.profiles[profileId], `${stage} -> ${profileId}`);
  }
});

test("resolveStageProfile is data-driven: unknown stage/profile fail-fast, disabled roots are not checked", () => {
  const loaded = loadProfiles();
  const unknownStage = resolveStageProfile("not_a_stage", { manifest: loaded.value });
  assert.equal(unknownStage.ok, false);
  assert.equal(unknownStage.error.kind, "invalid_job");

  const missingProfile = resolveStageProfile("plan", {
    manifest: { ...loaded.value, stageToProfile: { ...loaded.value.stageToProfile, plan: "missing-profile" } },
  });
  assert.equal(missingProfile.ok, false);
  assert.equal(missingProfile.error.kind, "invalid_job");

  const plan = resolveStageProfile("plan");
  assert.equal(plan.ok, true);
  assert.equal(plan.value.profileId, "plan");
  assert.equal(plan.value.extensionRoots.length, 1);
  assert.equal(plan.value.extensionRoots[0].id, "pi-web-access");
  assert.deepEqual(plan.value.expectedExtensionIds, [STAGE_SUBMIT_EXTENSION_ID, "pi-web-access"]);
  assert.deepEqual(plan.value.toolsExtra, ["web_search", "fetch_content"]);
  assert.equal(plan.value.skills.mode, "explicit");
  assert.deepEqual(plan.value.skills.names, ["write-plan", "delegate-work"]);
  assert.equal(plan.value.skills.inline, "write-plan");

  const direct = resolveStageProfile("direct_implement");
  assert.equal(direct.ok, true);
  assert.equal(direct.value.profileId, "implement-direct");
  assert.equal(direct.value.extensionRoots.length, 2);
  assert.equal(direct.value.extensionRoots[0].id, "todos-tool");
  assert.equal(direct.value.extensionRoots[1].id, "pi-web-access");
  assert.deepEqual(direct.value.toolsExtra, ["todo", "web_search", "fetch_content"]);
  assert.equal(direct.value.skills.inline, null);
  assert.deepEqual(direct.value.disabledEntries, []);
  const roots = assertExtensionRootsExist(direct.value);
  assert.equal(roots.ok, true);
});

test("implement profile resolves auto-handoff via env and fail-closes when the root is missing", () => {
  const tmp = mkdtempSync(join(tmpdir(), "stage-profiles-"));
  try {
    const webRoot = join(tmp, "pi-web-access");
    mkdirSync(webRoot);
    const missing = resolveStageProfile("implement", {
      env: {
        PI_AUTO_HANDOFF_ROOT: join(tmp, "missing-auto-handoff"),
        PI_WEB_ACCESS_ROOT: webRoot,
      },
      home: tmp,
    });
    assert.equal(missing.ok, true);
    const absent = assertExtensionRootsExist(missing.value);
    assert.equal(absent.ok, false);
    assert.equal(absent.error.kind, "adapter_failed");

    const root = join(tmp, "pi-auto-handoff");
    mkdirSync(root);
    const present = resolveStageProfile("implement", {
      env: { PI_AUTO_HANDOFF_ROOT: root, PI_WEB_ACCESS_ROOT: webRoot },
      home: tmp,
    });
    assert.equal(present.ok, true);
    assert.equal(present.value.extensionRoots[0].id, "auto-handoff");
    assert.equal(present.value.extensionRoots[0].channel, "auto-handoff-plan");
    assert.equal(present.value.extensionRoots[0].root, root);
    assert.deepEqual(present.value.expectedExtensionIds, [
      STAGE_SUBMIT_EXTENSION_ID,
      "auto-handoff",
      "pi-web-access",
    ]);
    assert.equal(assertExtensionRootsExist(present.value).ok, true);
  } finally {
    rmSync(tmp, { recursive: true, force: true });
  }
});

test("attestation parser is grep-stable and fail-closed", () => {
  const expected = [STAGE_SUBMIT_EXTENSION_ID];
  const line = buildAttestationLine(expected.join(","));
  assert.match(line, /"harnessAttestation"/);
  const ok = verifyHarnessAttestation(line, expected);
  assert.equal(ok.ok, true);
  assert.equal(ok.value.version, ATTESTATION_VERSION);

  const missing = verifyHarnessAttestation('{"type":"session","id":"x"}\n', expected);
  assert.equal(missing.ok, false);
  assert.equal(missing.error.kind, "extension_manifest_mismatch");

  const mismatch = verifyHarnessAttestation(line, [STAGE_SUBMIT_EXTENSION_ID, "auto-handoff"]);
  assert.equal(mismatch.ok, false);
  assert.equal(mismatch.error.kind, "extension_manifest_mismatch");
});

test("golden: buildRelayArgs + relay assembleChildInvocation match the stage-profiles manifest", () => {
  const tmp = mkdtempSync(join(tmpdir(), "stage-profile-golden-"));
  const delegateRoot = join(tmp, "delegate-agent");
  const autoHandoffRoot = join(tmp, "pi-auto-handoff");
  const workDir = join(tmp, "work");
  const outDir = join(tmp, "out");
  mkdirSync(delegateRoot);
  writeFileSync(join(delegateRoot, "index.ts"), "export {};\n");
  mkdirSync(join(autoHandoffRoot, "src"), { recursive: true });
  writeFileSync(join(autoHandoffRoot, "package.json"), '{"name":"pi-auto-handoff"}\n');
  writeFileSync(join(autoHandoffRoot, "src", "index.ts"), "export {};\n");
  const todosRoot = join(tmp, "todos-tool", "src");
  mkdirSync(todosRoot, { recursive: true });
  writeFileSync(join(todosRoot, "index.ts"), "export {};\n");
  const webRoot = join(tmp, "pi-web-access");
  mkdirSync(webRoot);
  writeFileSync(join(webRoot, "index.ts"), "export {};\n");
  mkdirSync(workDir);
  mkdirSync(outDir);
  const skillsRoot = seedSkillsRoot(join(tmp, "agent_skills"));
  const briefPath = join(tmp, "brief.txt");
  const planPath = join(tmp, "plan.json");
  writeFileSync(briefPath, "/skill:write-plan \n\nplan it\n");
  writeFileSync(planPath, '{"schema":"plan.v1"}\n');
  const manifest = loadProfiles().value;

  try {
    withEnv({
      PI_DELEGATE_AGENT_ROOT: delegateRoot,
      PI_AUTO_HANDOFF_ROOT: autoHandoffRoot,
      PI_TODOS_TOOL_ROOT: todosRoot,
      PI_WEB_ACCESS_ROOT: webRoot,
      PI_AGENT_SKILLS_ROOT: skillsRoot,
      HOME: tmp,
    }, () => {
      for (const stage of STAGES) {
        const profileId = manifest.stageToProfile[stage];
        const spec = manifest.profiles[profileId];
        const resolved = resolveStageProfile(stage, {
          env: process.env,
          home: tmp,
        });
        assert.equal(resolved.ok, true, `${stage}: ${resolved.error && resolved.error.message}`);
        const rooted = assertProfileResourcesExist(resolved.value);
        assert.equal(rooted.ok, true, stage);
        const profile = rooted.value;
        const job = fakeJob(stage, { planPath });
        const relayArgs = buildRelayArgs({
          briefPath,
          repoRoot: workDir,
          outDir,
          job,
          extensionRoot: EXT,
          profile,
          env: process.env,
        });
        assert.ok(relayArgs.includes("--no-skills"), stage);
        assert.deepEqual(
          skillPathsFromArgv(relayArgs).map((item) => basename(item)),
          STAGE_SKILL_NAMES[stage],
          stage,
        );
        assert.deepEqual(skillPathsFromArgv(relayArgs), profile.skills.paths, stage);
        const brief = compileBrief(job, { env: process.env, profile });
        const firstLine = brief.split("\n", 1)[0];
        if (STAGE_INLINE[stage]) {
          assert.equal(profile.skills.inline, STAGE_INLINE[stage], stage);
          assert.ok(profile.skills.names.includes(profile.skills.inline), stage);
          assert.equal(firstLine, `/skill:${STAGE_INLINE[stage]} `, stage);
          assert.ok(SKILL_PREFIX_LINE.test(firstLine), stage);
        } else {
          assert.equal(stage, "direct_implement");
          assert.equal(profile.skills.inline, null);
          assert.ok(!firstLine.startsWith("/skill:"), stage);
        }
        const opts = parseArgs(relayArgs);
        const run = { autoHandoff: makeAutoHandoffState(opts, outDir) };
        const assembled = assembleChildInvocation(opts, run);
        assert.equal(assembled.ok, true, `${stage}: ${assembled.error}`);
        const argv = assembled.argv;
        const extraE = [];
        if (run.autoHandoff.enabled) extraE.push(autoHandoffRoot);
        extraE.push(EXT);
        for (const ext of profile.extensionRoots) {
          if (ext.channel === "extension") extraE.push(ext.root);
        }
        assert.deepEqual(dashE(argv), [delegateRoot, ...extraE], stage);
        assert.ok(argv.includes("-ns"), stage);
        assert.deepEqual(skillPathsFromArgv(argv), profile.skills.paths, stage);
        assert.deepEqual(
          skillPathsFromArgv(argv).map((item) => basename(item)),
          STAGE_SKILL_NAMES[stage],
          stage,
        );
        assert.equal(assembled.env[EXPECT_EXTENSIONS_ENV], expectedExtensionsEnvValue(profile), stage);
        assert.ok(assembled.envKeys.includes(EXPECT_EXTENSIONS_ENV), stage);
        assert.equal(verifyArgvConsistency(argv, profile).ok, true, stage);

        const enabledAutoHandoff = spec.extensions.some((item) => item.enabled && item.id === "auto-handoff");
        if (enabledAutoHandoff) {
          assert.equal(stage, "implement");
          assert.ok(relayArgs.includes("--auto-handoff-plan"), stage);
          assert.equal(relayArgs[relayArgs.indexOf("--auto-handoff-plan") + 1], planPath);
          assert.ok(assembled.envKeys.includes("PI_AUTO_HANDOFF_PLAN_FILE"), stage);
          assert.ok(dashE(argv).includes(autoHandoffRoot), stage);
        } else {
          assert.ok(!relayArgs.includes("--auto-handoff-plan"), stage);
          assert.ok(!assembled.envKeys.includes("PI_AUTO_HANDOFF_PLAN_FILE"), stage);
          assert.ok(!assembled.envKeys.includes("PI_AUTO_HANDOFF_HANDOFF_DIR"), stage);
          assert.ok(!argv.some((item) => /auto-handoff/i.test(item)), stage);
        }

        for (const disabled of spec.extensions.filter((item) => item.enabled !== true)) {
          assert.ok(!argv.some((item) => item === disabled.id || String(item).includes(disabled.id)), `${stage} ${disabled.id}`);
          assert.ok(profile.disabledEntries.some((item) => item.id === disabled.id), stage);
        }

        if (stage === "plan") {
          assert.equal(profileId, "plan");
          assert.deepEqual(dashE(argv), [delegateRoot, EXT, webRoot], stage);
        }
        if (stage === "plan_review") {
          assert.equal(profileId, "plan-review");
          assert.deepEqual(dashE(argv), [delegateRoot, EXT, webRoot], stage);
        }
        if (stage === "execute_review") {
          assert.equal(profileId, "execute-review");
          assert.deepEqual(dashE(argv), [delegateRoot, EXT, webRoot], stage);
        }
        if (stage === "direct_implement") {
          assert.equal(profileId, "implement-direct");
          const todosRoot = profile.extensionRoots.find((item) => item.id === "todos-tool")?.root;
          assert.ok(todosRoot, "direct_implement mounts todos-tool");
          assert.deepEqual(dashE(argv), [delegateRoot, EXT, todosRoot, webRoot], stage);
        }
        assert.ok(relayArgs.includes("--extra-tools"), stage);
        assert.equal(
          relayArgs[relayArgs.indexOf("--extra-tools") + 1],
          stage === "direct_implement" ? "todo,web_search,fetch_content" : "web_search,fetch_content",
          stage,
        );
        const toolsList = (argv[argv.indexOf("--tools") + 1] || "").split(",");
        for (const toolName of profile.toolsExtra) {
          assert.ok(toolsList.includes(toolName), `${stage} --tools missing ${toolName}`);
        }
        if (!profile.toolsExtra.includes("todo")) {
          assert.ok(!toolsList.includes("todo"), `${stage} must not expose todo`);
        }
        assert.ok(toolsList.includes("web_search"), `${stage} must expose web_search`);
        assert.ok(toolsList.includes("fetch_content"), `${stage} must expose fetch_content`);
      }
    });
  } finally {
    rmSync(tmp, { recursive: true, force: true });
  }
});

test("skills.mode=auto keeps discovery: no -ns and no --skill", () => {
  const tmp = mkdtempSync(join(tmpdir(), "stage-profile-auto-skills-"));
  const delegateRoot = join(tmp, "delegate-agent");
  const workDir = join(tmp, "work");
  const outDir = join(tmp, "out");
  mkdirSync(delegateRoot);
  writeFileSync(join(delegateRoot, "index.ts"), "export {};\n");
  mkdirSync(workDir);
  mkdirSync(outDir);
  const webRoot = join(tmp, "pi-web-access");
  mkdirSync(webRoot);
  writeFileSync(join(webRoot, "index.ts"), "export {};\n");
  const briefPath = join(tmp, "brief.txt");
  writeFileSync(briefPath, "plan it\n");
  const loaded = loadProfiles();
  const manifest = {
    ...loaded.value,
    profiles: {
      ...loaded.value.profiles,
      plan: {
        ...loaded.value.profiles.plan,
        skills: { mode: "auto", paths: ["skills/write-plan"] },
      },
    },
  };
  try {
    withEnv({
      PI_DELEGATE_AGENT_ROOT: delegateRoot,
      PI_WEB_ACCESS_ROOT: webRoot,
      HOME: tmp,
    }, () => {
      const resolved = resolveStageProfile("plan", { manifest, env: process.env, home: tmp });
      assert.equal(resolved.ok, true, resolved.error && resolved.error.message);
      assert.equal(resolved.value.skills.mode, "auto");
      assert.deepEqual(resolved.value.skills.paths, []);
      const relayArgs = buildRelayArgs({
        briefPath,
        repoRoot: workDir,
        outDir,
        job: fakeJob("plan"),
        extensionRoot: EXT,
        profile: resolved.value,
        env: process.env,
      });
      assert.ok(!relayArgs.includes("--no-skills"));
      assert.ok(!relayArgs.includes("--skill"));
      const opts = parseArgs(relayArgs);
      const assembled = assembleChildInvocation(opts, { autoHandoff: makeAutoHandoffState(opts, outDir) });
      assert.equal(assembled.ok, true, assembled.error);
      assert.ok(!assembled.argv.includes("-ns"));
      assert.ok(!assembled.argv.includes("--no-skills"));
      assert.deepEqual(skillPathsFromArgv(assembled.argv), []);
    });
  } finally {
    rmSync(tmp, { recursive: true, force: true });
  }
});

test("skills fail-fast: unknown mode, missing path, missing SKILL.md", () => {
  const tmp = mkdtempSync(join(tmpdir(), "stage-profile-skill-fail-"));
  try {
    const loaded = loadProfiles();
    const unknownMode = resolveStageProfile("plan", {
      manifest: {
        ...loaded.value,
        profiles: {
          ...loaded.value.profiles,
          plan: { ...loaded.value.profiles.plan, skills: { mode: "maybe", paths: [] } },
        },
      },
    });
    assert.equal(unknownMode.ok, false);
    assert.equal(unknownMode.error.kind, "invalid_job");
    assert.match(unknownMode.error.message, /explicit or auto/);

    const missingRoot = join(tmp, "empty-skills");
    mkdirSync(missingRoot);
    const missing = resolveStageProfile("plan", {
      env: { PI_AGENT_SKILLS_ROOT: missingRoot },
      home: tmp,
    });
    assert.equal(missing.ok, true);
    const absent = assertSkillPathsExist(missing.value);
    assert.equal(absent.ok, false);
    assert.equal(absent.error.kind, "adapter_failed");
    assert.match(absent.error.message, /skill path not found/);

    const built = tryBuildRelayArgs({
      briefPath: join(tmp, "brief.txt"),
      repoRoot: tmp,
      outDir: tmp,
      job: fakeJob("plan"),
      extensionRoot: EXT,
      env: { PI_AGENT_SKILLS_ROOT: missingRoot },
    });
    assert.equal(built.ok, false);
    assert.equal(built.error.kind, "adapter_failed");

    const brokenRoot = join(tmp, "broken-skills");
    const brokenDir = join(brokenRoot, "skills", "write-plan");
    mkdirSync(brokenDir, { recursive: true });
    mkdirSync(join(brokenRoot, "skills", "delegate-work"), { recursive: true });
    writeFileSync(join(brokenRoot, "skills", "delegate-work", "SKILL.md"), "---\nname: delegate-work\ndescription: x\n---\n");
    const noMd = resolveStageProfile("plan", {
      env: { PI_AGENT_SKILLS_ROOT: brokenRoot },
      home: tmp,
    });
    assert.equal(noMd.ok, true);
    const missingMd = assertSkillPathsExist(noMd.value);
    assert.equal(missingMd.ok, false);
    assert.equal(missingMd.error.kind, "adapter_failed");
    assert.match(missingMd.error.message, /missing SKILL.md/);
  } finally {
    rmSync(tmp, { recursive: true, force: true });
  }
});

test("toolsExtra fail-fast: non-array or invalid names", () => {
  const loaded = loadProfiles();
  const notArray = resolveStageProfile("plan", {
    manifest: {
      ...loaded.value,
      profiles: {
        ...loaded.value.profiles,
        plan: { ...loaded.value.profiles.plan, toolsExtra: "todo" },
      },
    },
  });
  assert.equal(notArray.ok, false);
  assert.equal(notArray.error.kind, "invalid_job");
  assert.match(notArray.error.message, /toolsExtra must be an array/);

  const invalid = resolveStageProfile("plan", {
    manifest: {
      ...loaded.value,
      profiles: {
        ...loaded.value.profiles,
        plan: { ...loaded.value.profiles.plan, toolsExtra: ["todo!"] },
      },
    },
  });
  assert.equal(invalid.ok, false);
  assert.equal(invalid.error.kind, "invalid_job");
  assert.match(invalid.error.message, /toolsExtra has invalid tool name: todo!/);
});

test("skills.inline not in paths fail-fast", () => {
  const loaded = loadProfiles();
  const unknown = resolveStageProfile("plan", {
    manifest: {
      ...loaded.value,
      profiles: {
        ...loaded.value.profiles,
        plan: {
          ...loaded.value.profiles.plan,
          skills: {
            mode: "explicit",
            inline: "execute-plan",
            paths: ["skills/write-plan", "skills/delegate-work"],
          },
        },
      },
    },
  });
  assert.equal(unknown.ok, false);
  assert.equal(unknown.error.kind, "invalid_job");
  assert.match(unknown.error.message, /skills.inline execute-plan is not in skills.paths/);
});
