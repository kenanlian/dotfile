import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import test from 'node:test';

import {
  parseArgs,
  normalizeArtifact,
  matchesWhitelist,
  approvedWriteRoots,
  resolveCanonical,
  isPathContained,
  validateWritePaths,
  deriveTransportDir,
  extractRawReviewArtifact,
  checkFreshIdentity,
  checkResumeBinding,
  checkIdentity,
  splitEnvelope,
  renderReceipt,
  parseAgentModels,
  normalizeModelLabel,
  modelsMatch,
  decideOutcome,
  writeArtifactExclusive,
  run,
  COMPACT_DELIM,
  REPORT_DELIM,
  BINDING_NAME,
} from '../review-relay.mjs';

const here = path.dirname(fileURLToPath(import.meta.url));
const runner = path.resolve(here, '..', 'review-relay.mjs');

function tempDir(prefix = 'review-relay-') {
  return fs.mkdtempSync(path.join(os.tmpdir(), prefix));
}

function rmDir(dir) {
  fs.rmSync(dir, { recursive: true, force: true });
}

function makeRepo() {
  const repo = tempDir('review-relay-repo-');
  fs.mkdirSync(path.join(repo, '.dev', 'review', 'x'), { recursive: true });
  fs.mkdirSync(path.join(repo, '.dev', 'plan-review', 'x'), { recursive: true });
  return repo;
}

function envelope(compact = 'Outcome: review completed\n', report = '---\n# Raw\n') {
  return `${COMPACT_DELIM}\n${compact}${REPORT_DELIM}\n${report}`;
}

function completedResult(overrides = {}) {
  return {
    status: 'completed',
    resolvedModel: 'pinned-model',
    sessionId: 'sess-1',
    finalMessage: envelope(),
    ...overrides,
  };
}

function fakeSpawn(result, status = 0) {
  return ({ outDir }) => {
    fs.mkdirSync(outDir, { recursive: true });
    if (result) {
      fs.writeFileSync(path.join(outDir, 'result.json'), `${JSON.stringify(result, null, 2)}\n`);
    }
    return { status, stderr: '' };
  };
}

function contractFor(artifact) {
  return [
    'Required skill: review-patch',
    `Raw Review Artifact: ${artifact}`,
    '---TRANSPORT---',
    'read-only addendum',
  ].join('\n');
}

test('parseArgs rejects missing and illegal flags', () => {
  assert.equal(parseArgs([]).ok, false);
  assert.match(parseArgs([]).error, /missing --cd/);
  assert.equal(parseArgs(['--cd', '/tmp']).ok, false);
  assert.match(parseArgs(['--cd', '/tmp']).error, /missing --artifact/);
  assert.equal(parseArgs(['--cd', '/tmp', '--artifact', 'a']).ok, false);
  assert.match(parseArgs(['--cd', '/tmp', '--artifact', 'a']).error, /missing --model/);
  assert.equal(parseArgs(['--cd', '/tmp', '--artifact', 'a', '--model']).ok, false);
  assert.match(parseArgs(['--cd', '/tmp', '--artifact', 'a', '--model']).error, /requires a value/);
  assert.equal(parseArgs(['--cd', '/tmp', '--artifact', 'a', '--model', 'm', '--out-dir', 'x']).ok, false);
  assert.match(parseArgs(['--cd', '/tmp', '--artifact', 'a', '--model', 'm', '--out-dir', 'x']).error, /unknown option: --out-dir/);
  assert.equal(parseArgs(['--cd', '/tmp', '--artifact', 'a', '--model', 'm', '--from-result', 'x']).ok, false);
  assert.match(parseArgs(['--cd', '/tmp', '--artifact', 'a', '--model', 'm', '--from-result', 'x']).error, /unknown option: --from-result/);
  assert.equal(parseArgs(['--brief', 'x', '--cd', '/tmp', '--artifact', 'a', '--model', 'm']).ok, false);

  const ok = parseArgs(['--cd', '/tmp/repo', '--artifact', '.dev/review/x/round-01-review.md', '--model', 'm', '--session', 's1']);
  assert.equal(ok.ok, true);
  assert.equal(ok.cd, '/tmp/repo');
  assert.equal(ok.artifact, '.dev/review/x/round-01-review.md');
  assert.equal(ok.model, 'm');
  assert.equal(ok.session, 's1');
});

test('C5(0) normalizes absolute spelling under --cd and rejects escapes', () => {
  const repo = makeRepo();
  try {
    const rel = '.dev/review/x/round-01-review-patch.md';
    const abs = path.join(repo, rel);
    const under = normalizeArtifact(repo, abs);
    assert.equal(under.ok, true);
    assert.equal(under.relative, rel);

    const given = normalizeArtifact(repo, rel);
    assert.equal(given.ok, true);
    assert.equal(given.relative, rel);

    const escapedRel = normalizeArtifact(repo, '../../x');
    assert.equal(escapedRel.ok, false);

    const escapedAbs = normalizeArtifact(repo, path.resolve(repo, '../../outside.md'));
    assert.equal(escapedAbs.ok, false);

    const audit = tempDir('review-relay-audit-');
    try {
      fs.rmSync(path.join(repo, '.dev'), { recursive: true, force: true });
      fs.symlinkSync(audit, path.join(repo, '.dev'));
      fs.mkdirSync(path.join(audit, 'review', 'x'), { recursive: true });
      const canonicalTarget = path.join(fs.realpathSync(audit), 'review', 'x', 'round-01-review-patch.md');
      const rejected = normalizeArtifact(repo, canonicalTarget);
      assert.equal(rejected.ok, false);
    } finally {
      rmDir(audit);
    }
  } finally {
    rmDir(repo);
  }
});

test('whitelist accepts audit forms and rejects others', () => {
  assert.equal(matchesWhitelist('.dev/plan-review/x/round-01-review.md'), true);
  assert.equal(matchesWhitelist('.dev/review/x/round-01-review-patch.md'), true);
  assert.equal(matchesWhitelist('.dev/other.md'), false);
  assert.equal(matchesWhitelist('src/x.md'), false);
  assert.equal(matchesWhitelist('.dev/review/x/y/round-01-review-patch.md'), false);
  assert.equal(matchesWhitelist('.dev/review/../round-01-review-patch.md'), false);
});

test('symlink fixtures: .dev link is contained; nested escape is rejected', () => {
  const repo = tempDir('review-relay-sym-repo-');
  const audit = tempDir('review-relay-sym-audit-');
  const outside = tempDir('review-relay-sym-out-');
  try {
    fs.symlinkSync(audit, path.join(repo, '.dev'));
    fs.mkdirSync(path.join(audit, 'review', 'ok'), { recursive: true });
    fs.mkdirSync(path.join(audit, 'review'), { recursive: true });
    fs.symlinkSync(outside, path.join(audit, 'review', 'escape'));

    const allowedRel = '.dev/review/ok/round-01-review-patch.md';
    const allowed = validateWritePaths(repo, allowedRel);
    assert.equal(allowed.ok, true, allowed.error);
    assert.equal(allowed.relative, allowedRel);
    const roots = approvedWriteRoots(repo);
    assert.equal(roots.length, 2);
    assert.equal(isPathContained(resolveCanonical(path.join(repo, allowedRel)), roots), true);

    const escapedRel = '.dev/review/escape/round-01-review-patch.md';
    const escaped = validateWritePaths(repo, escapedRel);
    assert.equal(escaped.ok, false);
    assert.match(escaped.error, /escapes approved write roots/);
  } finally {
    rmDir(repo);
    rmDir(audit);
    rmDir(outside);
  }
});

test('splitEnvelope accepts a valid pair and rejects missing, extra, or reversed delimiters', () => {
  const compact = 'Outcome: review completed\nArtifact: a';
  const report = '---\n# Raw report\n';
  const good = splitEnvelope(`${COMPACT_DELIM}\n${compact}\n${REPORT_DELIM}\n${report}`);
  assert.equal(good.ok, true);
  assert.equal(good.compact, compact);
  assert.equal(good.report, report);

  assert.equal(splitEnvelope(`${COMPACT_DELIM}\nonly compact\n`).ok, false);
  assert.equal(splitEnvelope(`${REPORT_DELIM}\n${report}\n${COMPACT_DELIM}\n${compact}`).ok, false);
  assert.equal(splitEnvelope(`${COMPACT_DELIM}\na\n${REPORT_DELIM}\nb\n${REPORT_DELIM}\nc\n`).ok, false);
  assert.equal(splitEnvelope(`preamble\n${COMPACT_DELIM}\n${compact}\n${REPORT_DELIM}\n${report}`).ok, false);
  assert.equal(splitEnvelope(`${COMPACT_DELIM}\n${compact}\n${COMPACT_DELIM}\n${REPORT_DELIM}\n${report}`).ok, false);
});

test('identity binding: missing or mismatched field is contract-violation; resume needs binding', () => {
  const artifact = '.dev/review/x/round-01-review-patch.md';
  assert.equal(extractRawReviewArtifact('no field here\n'), null);
  assert.equal(checkFreshIdentity('hello', artifact).ok, false);
  assert.equal(checkFreshIdentity(`Raw Review Artifact: other.md\n`, artifact).ok, false);
  assert.equal(checkFreshIdentity(`Raw Review Artifact: ${artifact}\n`, artifact).ok, true);

  assert.equal(checkResumeBinding(null, { session: 's', artifact, cd: '/repo' }).ok, false);
  assert.equal(checkResumeBinding(
    { sessionId: 's', artifact, cd: '/repo' },
    { session: 's', artifact, cd: '/repo' },
  ).ok, true);
  assert.equal(checkResumeBinding(
    { sessionId: 'other', artifact, cd: '/repo' },
    { session: 's', artifact, cd: '/repo' },
  ).ok, false);
  assert.equal(checkResumeBinding(
    { sessionId: 's', artifact: 'other.md', cd: '/repo' },
    { session: 's', artifact, cd: '/repo' },
  ).ok, false);

  const resume = checkIdentity({
    session: 's',
    artifact,
    cd: '/repo',
    stdin: 'delta only',
    binding: null,
  });
  assert.equal(resume.ok, false);
});

test('resume with missing or mismatched binding does not spawn', () => {
  const repo = makeRepo();
  try {
    const artifact = '.dev/review/x/round-01-review-patch.md';
    let spawned = 0;
    const spy = () => {
      spawned += 1;
      return { status: 0, stderr: '' };
    };

    const missing = run(
      ['--cd', repo, '--artifact', artifact, '--model', 'pinned-model', '--session', 'sess-1'],
      'delta brief',
      { spawnRelay: spy },
    );
    assert.equal(missing.exitCode, 2);
    assert.equal(spawned, 0);
    assert.match(missing.stdout, /^Outcome: contract-violation$/m);
    assert.equal(missing.stdout.includes(`Artifact: ${artifact}`), true);

    const transport = deriveTransportDir(path.join(repo, artifact));
    fs.mkdirSync(transport, { recursive: true });
    fs.writeFileSync(path.join(transport, BINDING_NAME), `${JSON.stringify({
      sessionId: 'sess-1',
      artifact,
      cd: repo,
    }, null, 2)}\n`);

    const mismatch = run(
      ['--cd', repo, '--artifact', artifact, '--model', 'pinned-model', '--session', 'sess-OTHER'],
      'delta brief',
      { spawnRelay: spy },
    );
    assert.equal(mismatch.exitCode, 2);
    assert.equal(spawned, 0);
    assert.match(mismatch.stdout, /^Outcome: contract-violation$/m);
  } finally {
    rmDir(repo);
  }
});

test('fresh dispatch with missing or mismatched Raw Review Artifact does not spawn', () => {
  const repo = makeRepo();
  try {
    const artifact = '.dev/review/x/round-01-review-patch.md';
    let spawned = 0;
    const spy = () => {
      spawned += 1;
      return { status: 0 };
    };

    const missing = run(
      ['--cd', repo, '--artifact', artifact, '--model', 'pinned-model'],
      'no artifact field',
      { spawnRelay: spy },
    );
    assert.equal(missing.exitCode, 2);
    assert.equal(spawned, 0);

    const mismatch = run(
      ['--cd', repo, '--artifact', artifact, '--model', 'pinned-model'],
      'Raw Review Artifact: .dev/review/x/round-01-other.md\n',
      { spawnRelay: spy },
    );
    assert.equal(mismatch.exitCode, 2);
    assert.equal(spawned, 0);
  } finally {
    rmDir(repo);
  }
});

test('result pipeline: completed matching model writes artifact; mismatch and exists fail', () => {
  const matching = decideOutcome({
    result: completedResult(),
    requestedModel: 'pinned-model',
    artifactExists: false,
    relayStatus: 0,
  });
  assert.equal(matching.outcome, 'completed');
  assert.equal(matching.exitCode, 0);
  assert.equal(matching.writeArtifact, true);

  const mismatch = decideOutcome({
    result: completedResult({ resolvedModel: 'other-model' }),
    requestedModel: 'pinned-model',
    artifactExists: false,
    relayStatus: 0,
  });
  assert.equal(mismatch.outcome, 'blocked');
  assert.equal(mismatch.exitCode, 1);
  assert.equal(mismatch.writeArtifact, false);
  assert.equal(mismatch.modelMatch, false);

  const exists = decideOutcome({
    result: completedResult(),
    requestedModel: 'pinned-model',
    artifactExists: true,
    relayStatus: 0,
  });
  assert.equal(exists.outcome, 'persistence-failure');
  assert.equal(exists.exitCode, 1);
  assert.equal(exists.writeArtifact, false);
});

test('C7 matches live agent-models label and blocks 300K silent fallback', () => {
  const catalog = [
    'claude-opus-5-thinking-high - Claude Opus 5 1M Thinking',
    'claude-opus-5-high - Claude Opus 5 1M',
  ].join('\n');
  const labels = parseAgentModels(catalog);
  assert.equal(labels.get('claude-opus-5-thinking-high'), 'Claude Opus 5 1M Thinking');
  const lookup = (slug) => labels.get(slug) ?? null;

  assert.equal(modelsMatch('claude-opus-5-thinking-high', 'claude-opus-5-thinking-high', lookup), true);
  assert.equal(modelsMatch('claude-opus-5-thinking-high', 'Claude Opus 5 1M Thinking', lookup), true);
  assert.equal(modelsMatch('claude-opus-5-thinking-high', 'Claude Opus 5 300K High', lookup), false);

  const ok = decideOutcome({
    result: completedResult({
      resolvedModel: 'Claude Opus 5 1M Thinking',
    }),
    requestedModel: 'claude-opus-5-thinking-high',
    artifactExists: false,
    relayStatus: 0,
    lookupLabel: lookup,
  });
  assert.equal(ok.outcome, 'completed');
  assert.equal(ok.modelMatch, true);

  const fallback = decideOutcome({
    result: completedResult({
      resolvedModel: 'Claude Opus 5 300K High',
    }),
    requestedModel: 'claude-opus-5-thinking-high',
    artifactExists: false,
    relayStatus: 0,
    lookupLabel: lookup,
  });
  assert.equal(fallback.outcome, 'blocked');
  assert.equal(fallback.modelMatch, false);
  assert.equal(fallback.writeArtifact, false);
  assert.match(fallback.blockers, /300K High/);
  assert.match(fallback.blockers, /1M Thinking/);
});

test('C7 strips catalog (current) status marker and still rejects 300K fallback', () => {
  assert.equal(normalizeModelLabel('Composer 2.5 (current)'), 'Composer 2.5');
  assert.equal(normalizeModelLabel('Claude Opus 5 1M Thinking'), 'Claude Opus 5 1M Thinking');

  const catalog = [
    'composer-2.5 - Composer 2.5 (current)',
    'claude-opus-5-thinking-high - Claude Opus 5 1M Thinking',
  ].join('\n');
  const labels = parseAgentModels(catalog);
  assert.equal(labels.get('composer-2.5'), 'Composer 2.5');
  const lookup = (slug) => labels.get(slug) ?? null;

  assert.equal(modelsMatch('composer-2.5', 'Composer 2.5', lookup), true);
  assert.equal(modelsMatch('composer-2.5', 'Composer 2.5 (current)', lookup), false);

  const pinned = decideOutcome({
    result: completedResult({ resolvedModel: 'Composer 2.5' }),
    requestedModel: 'composer-2.5',
    artifactExists: false,
    relayStatus: 0,
    lookupLabel: lookup,
  });
  assert.equal(pinned.outcome, 'completed');
  assert.equal(pinned.modelMatch, true);

  const fallback = decideOutcome({
    result: completedResult({ resolvedModel: 'Claude Opus 5 300K High' }),
    requestedModel: 'claude-opus-5-thinking-high',
    artifactExists: false,
    relayStatus: 0,
    lookupLabel: lookup,
  });
  assert.equal(fallback.outcome, 'blocked');
  assert.equal(fallback.modelMatch, false);
  assert.equal(fallback.writeArtifact, false);
});

test('modelsMatch accepts effort-tier catalog labels with a matching resolved tier', () => {
  const catalog = [
    'cursor-grok-4.6-high - Cursor Grok 4.6',
    'cursor-grok-4.6-low - Cursor Grok 4.6',
    'cursor-grok-4.6-medium - Cursor Grok 4.6',
    'cursor-grok-4.6-xhigh - Cursor Grok 4.6',
    'cursor-grok-4.6-high-fast - Cursor Grok 4.6',
    'cursor-grok-4.6-low-fast - Cursor Grok 4.6',
    'composer-2.5 - Composer 2.5',
    'claude-opus-5-thinking-high - Claude Opus 5 1M Thinking',
  ].join('\n');
  const labels = parseAgentModels(catalog);
  const lookup = (slug) => labels.get(slug) ?? null;

  assert.equal(modelsMatch('cursor-grok-4.6-high', 'Cursor Grok 4.6 High', lookup), true);
  assert.equal(modelsMatch('cursor-grok-4.6-high', 'Cursor Grok 4.6 HIGH', lookup), true);
  assert.equal(modelsMatch('cursor-grok-4.6-high', 'Cursor Grok 4.6', lookup), true);
  assert.equal(modelsMatch('cursor-grok-4.6-low', 'Cursor Grok 4.6 Low', lookup), true);
  assert.equal(modelsMatch('cursor-grok-4.6-medium', 'Cursor Grok 4.6 Medium', lookup), true);
  assert.equal(modelsMatch('cursor-grok-4.6-xhigh', 'Cursor Grok 4.6 XHigh', lookup), true);

  assert.equal(modelsMatch('cursor-grok-4.6-high', 'Cursor Grok 4.6 Low', lookup), false);
  assert.equal(modelsMatch('cursor-grok-4.6-high', 'Cursor Grok 4.6 Medium', lookup), false);
  assert.equal(modelsMatch('cursor-grok-4.6-high', 'Cursor Grok 4.6 XHigh', lookup), false);

  assert.equal(modelsMatch('cursor-grok-4.6-high', 'Composer 2.5 High', lookup), false);
  assert.equal(modelsMatch('cursor-grok-4.6-high', 'Composer 2.5', lookup), false);

  assert.equal(modelsMatch('composer-2.5', 'Composer 2.5', lookup), true);
  assert.equal(modelsMatch('composer-2.5', 'Composer 2.5 High', lookup), false);
  assert.equal(modelsMatch('claude-opus-5-thinking-high', 'Claude Opus 5 1M Thinking', lookup), true);

  assert.equal(modelsMatch('cursor-grok-4.6-high-fast', 'Cursor Grok 4.6 High', lookup), true);
  assert.equal(modelsMatch('cursor-grok-4.6-high-fast', 'Cursor Grok 4.6 Low', lookup), false);
  assert.equal(modelsMatch('cursor-grok-4.6-low-fast', 'Cursor Grok 4.6 Low', lookup), true);
  assert.equal(modelsMatch('cursor-grok-4.6-high-fast', 'Cursor Grok 4.6', lookup), true);

  const smoke = decideOutcome({
    result: completedResult({ resolvedModel: 'Cursor Grok 4.6 High' }),
    requestedModel: 'cursor-grok-4.6-high',
    artifactExists: false,
    relayStatus: 0,
    lookupLabel: lookup,
  });
  assert.equal(smoke.outcome, 'completed');
  assert.equal(smoke.modelMatch, true);

  const downgrade = decideOutcome({
    result: completedResult({ resolvedModel: 'Cursor Grok 4.6 Low' }),
    requestedModel: 'cursor-grok-4.6-high',
    artifactExists: false,
    relayStatus: 0,
    lookupLabel: lookup,
  });
  assert.equal(downgrade.outcome, 'blocked');
  assert.equal(downgrade.modelMatch, false);
  assert.equal(downgrade.writeArtifact, false);
});

test('run writes REPORT verbatim, reprints exact --artifact, and maps exits', () => {
  const repo = makeRepo();
  try {
    const artifact = '.dev/review/x/round-01-review-patch.md';
    const report = '---\nexecution_id: demo\n---\n# Raw patch review\nbody\n';
    const compact = 'Outcome: review completed\nVerdict: correct\n';
    const result = completedResult({
      finalMessage: envelope(compact, report),
    });

    const done = run(
      ['--cd', repo, '--artifact', artifact, '--model', 'pinned-model'],
      contractFor(artifact),
      { spawnRelay: fakeSpawn(result) },
    );
    assert.equal(done.exitCode, 0, done.stderr);
    assert.equal(done.spawned, true);
    assert.match(done.stdout, /^Outcome: completed$/m);
    assert.equal(done.stdout.includes(`Artifact: ${artifact}`), true);
    assert.match(done.stdout, /^Session: sess-1$/m);
    assert.match(done.stdout, /^Model: pinned-model$/m);
    assert.match(done.stdout, /artifact-written: PASS/);
    assert.match(done.stdout, /model-match: PASS/);
    assert.equal(fs.readFileSync(path.join(repo, artifact), 'utf8'), report);

    const binding = JSON.parse(fs.readFileSync(path.join(repo, path.dirname(artifact), 'transport', BINDING_NAME), 'utf8'));
    assert.equal(binding.sessionId, 'sess-1');
    assert.equal(binding.artifact, artifact);
    assert.equal(binding.cd, repo);

    const again = run(
      ['--cd', repo, '--artifact', artifact, '--model', 'pinned-model'],
      contractFor(artifact),
      { spawnRelay: fakeSpawn(result) },
    );
    assert.equal(again.exitCode, 1);
    assert.match(again.stdout, /^Outcome: persistence-failure$/m);
    assert.equal(fs.readFileSync(path.join(repo, artifact), 'utf8'), report);
  } finally {
    rmDir(repo);
  }
});

test('run blocks on model mismatch and does not write the artifact', () => {
  const repo = makeRepo();
  try {
    const artifact = '.dev/plan-review/x/round-01-review.md';
    const done = run(
      ['--cd', repo, '--artifact', artifact, '--model', 'pinned-model'],
      contractFor(artifact),
      { spawnRelay: fakeSpawn(completedResult({ resolvedModel: 'downgraded' })), lookupLabel: () => null },
    );
    assert.equal(done.exitCode, 1);
    assert.match(done.stdout, /^Outcome: blocked$/m);
    assert.match(done.stdout, /model-match: FAIL/);
    assert.equal(fs.existsSync(path.join(repo, artifact)), false);
  } finally {
    rmDir(repo);
  }
});

test('run maps invalid envelope to invalid-return and keeps Session', () => {
  const repo = makeRepo();
  try {
    const artifact = '.dev/review/x/round-01-review-patch.md';
    const done = run(
      ['--cd', repo, '--artifact', artifact, '--model', 'pinned-model'],
      contractFor(artifact),
      { spawnRelay: fakeSpawn(completedResult({ finalMessage: 'no delimiters' })) },
    );
    assert.equal(done.exitCode, 1);
    assert.match(done.stdout, /^Outcome: invalid-return$/m);
    assert.match(done.stdout, /^Session: sess-1$/m);
    assert.equal(fs.existsSync(path.join(repo, artifact)), false);
    const binding = JSON.parse(fs.readFileSync(path.join(deriveTransportDir(path.join(repo, artifact)), BINDING_NAME), 'utf8'));
    assert.equal(binding.sessionId, 'sess-1');
  } finally {
    rmDir(repo);
  }
});

test('run passes through missing agent as 127', () => {
  const repo = makeRepo();
  try {
    const artifact = '.dev/review/x/round-01-review-patch.md';
    const done = run(
      ['--cd', repo, '--artifact', artifact, '--model', 'pinned-model'],
      contractFor(artifact),
      { spawnRelay: () => ({ status: 127, stderr: 'agent not found\n' }) },
    );
    assert.equal(done.exitCode, 127);
    assert.equal(done.stdout, '');
    assert.equal(fs.existsSync(path.join(repo, artifact)), false);
  } finally {
    rmDir(repo);
  }
});

test('renderReceipt reprints the original Artifact spelling and attaches compact', () => {
  const text = renderReceipt({
    outcome: 'completed',
    artifact: '.dev/review/x/round-01-review-patch.md',
    session: 'sess-1',
    model: 'pinned-model',
    artifactWritten: true,
    modelMatch: true,
    blockers: null,
    compact: 'Outcome: review completed\n',
  });
  assert.match(text, /^Artifact: \.dev\/review\/x\/round-01-review-patch\.md$/m);
  assert.match(text, /^---$/m);
  assert.match(text, /^Outcome: review completed$/m);
});

test('writeArtifactExclusive uses wx and leaves no partial file on EEXIST', () => {
  const dir = tempDir('review-relay-wx-');
  try {
    const file = path.join(dir, 'round-01-review.md');
    fs.writeFileSync(file, 'original\n');
    const first = writeArtifactExclusive(file, 'new\n');
    assert.equal(first.ok, false);
    assert.equal(fs.readFileSync(file, 'utf8'), 'original\n');
  } finally {
    rmDir(dir);
  }
});

test('CLI usage errors exit 2 without a receipt', () => {
  const result = spawnSync(process.execPath, [runner, '--model', 'm'], { encoding: 'utf8' });
  assert.equal(result.status, 2);
  assert.equal(result.stdout, '');
  assert.match(result.stderr, /missing --cd/);
});
