import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const RELAY = join(dirname(fileURLToPath(import.meta.url)), '..', 'scripts', 'relay.mjs');
const source = readFileSync(RELAY, 'utf8');

test('relay exists and is ESM javascript', () => {
  assert.ok(source.includes("import { spawn"), 'relay must import spawn');
  assert.ok(source.includes('delegate-relay.result.v1'), 'relay must write the v1 contract');
});

test('tool allowlists match the settled contract', () => {
  const readOnly = /const READ_ONLY_TOOLS = \[([^\]]+)\]/.exec(source)?.[1];
  const write = /const WRITE_TOOLS = \[([^\]]+)\]/.exec(source)?.[1];
  assert.equal(
    readOnly?.split(',').map((s) => s.trim().replace(/"/g, '')).join(','),
    'read,grep,find,ls,delegate_agent',
  );
  assert.equal(
    write?.split(',').map((s) => s.trim().replace(/"/g, '')).join(','),
    'read,grep,find,ls,bash,edit,write,delegate_agent',
  );
});

test('extension loading is deterministic: -ne plus explicit -e', () => {
  assert.ok(source.includes('"--no-extensions"'), 'must disable implicit extension discovery');
  assert.ok(/argv\.push\("-e", extensionRoot\)/.test(source), 'must explicitly load delegate-agent');
  assert.ok(!source.includes('"--no-skills"'), 'must NOT disable global skills');
});

test('completion requires exit 0 + agent_settled + session id', () => {
  const predicate = /const failedStop = state\.stopReason === "error" \|\| state\.stopReason === "aborted";[\s\S]*?const succeeded =\s*\n?\s*code === 0 && !watchdogFired && !failedStop && state\.settled\s*\n?\s*&& typeof state\.sessionId === "string" && state\.sessionId\.length > 0\s*\n?\s*&& sessionMatches;/;
  assert.ok(predicate.test(source), 'the completion predicate must be intact');
});

test('exact-session resume fails closed instead of creating a missing session', () => {
  assert.match(source, /argv\.push\("--session", opts\.session\)/);
  assert.doesNotMatch(source, /argv\.push\("--session-id", opts\.session\)/);
  assert.match(source, /const sessionMatches = !opts\.session \|\| state\.sessionId === opts\.session;/);
});

test('read-only is the fresh-run default; --write is explicit', () => {
  const defaults = /readOnly: true,\s*\n\s*write: false,/.exec(source);
  assert.ok(defaults, 'fresh runs default to read-only');
});

test('relay never commits', () => {
  assert.ok(!/\bgit\s+(commit|push)/.test(source), 'relay must not run git commit/push');
});

test('prompt rides the child stdin, not argv text', () => {
  assert.ok(!source.includes('prompt-attachment.tmp'), 'no temp prompt attachment');
  assert.ok(!/@\$\{promptFile\}/.test(source), 'no @file attachment syntax');
  assert.ok(!/argv\.push\("-"\)/.test(source), 'pi has no "-" positional; stdin alone is the prompt');
  assert.match(source, /stdio: \["pipe", "pipe", "pipe"\]/, 'stdin is a pipe so the relay can write the brief');
  assert.match(source, /child\.stdin\.end\(brief/, 'writes the brief to child stdin');
});

test('/skill: first line is validated fail-fast', () => {
  // Pi's _expandSkillCommand splits the skill name at the first SPACE; a name
  // followed by a newline silently fails to expand. The relay must reject that
  // shape instead of degrading to a pathless brief.
  assert.match(source, /function validateSkillPrefix/, 'validator exists');
  assert.match(source, /SKILL_PREFIX_LINE = \/\^\\\/skill:\[a-z0-9\]\[a-z0-9-\]\* \\r\?\$\//, 'exact first-line shape enforced');
  assert.match(source, /validateSkillPrefix\(readBrief\(opts\)\)/, 'validation runs before dispatch');
});
