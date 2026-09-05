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
  const predicate = /const failedStop = state\.stopReason === "error" \|\| state\.stopReason === "aborted";[\s\S]*?const succeeded =\s*\n?\s*code === 0 && !watchdogFired && !failedStop && state\.settled\s*\n?\s*&& typeof sessionId === "string" && sessionId\.length > 0;/;
  assert.ok(predicate.test(source), 'the completion predicate must be intact');
});

test('read-only is the fresh-run default; --write is explicit', () => {
  const defaults = /readOnly: true,\s*\n\s*write: false,/.exec(source);
  assert.ok(defaults, 'fresh runs default to read-only');
});

test('relay never commits', () => {
  assert.ok(!/\bgit\s+(commit|push)/.test(source), 'relay must not run git commit/push');
});

test('prompt rides a temp attachment file, not argv text', () => {
  assert.ok(source.includes('prompt-attachment.tmp'), 'uses a temp prompt attachment');
  assert.ok(/`@\$\{promptFile\}`/.test(source) || /argv\.push\("--", `@\$\{promptFile\}`\)/.test(source), 'attaches via @file syntax');
});
