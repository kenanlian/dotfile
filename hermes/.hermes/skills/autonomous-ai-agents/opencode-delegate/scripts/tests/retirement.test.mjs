import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import test from 'node:test';

const skill = join(dirname(fileURLToPath(import.meta.url)), '..', '..');
let repo = skill;
while (!existsSync(join(repo, '.git'))) {
  const parent = dirname(repo);
  if (parent === repo) throw new Error('Run retirement tests from the versioned dotfile skill tree');
  repo = parent;
}

test('retired OpenCode backend configuration and workflow roles are absent', () => {
  const config = join(repo, 'opencode', '.config', 'opencode');
  for (const file of ['delegation.json', 'agents/reviewer.md', 'agents/junior-worker.md', 'agents/senior-worker.md', 'agents/expert-worker.md']) {
    assert.equal(existsSync(join(config, file)), false, `Retired entry remains: ${file}`);
  }
  for (const file of [join(skill, 'SKILL.md'), join(skill, 'references/dispatch-and-poll.md'), join(skill, '..', 'opencode-plugins', 'SKILL.md')]) {
    assert.doesNotMatch(readFileSync(file, 'utf8'), /Cross-host delegation boundary|OpenCode-host adapter|external Cursor execution|allowed roles, access mode, nesting depth|The OpenCode parent owns|Hermes owns product|never push, create a PR|Preserve discussion sessions separately from execution sessions/);
  }
  assert.ok(existsSync(join(skill, 'scripts/relay.mjs')), 'Ordinary CLI transport must remain');
  assert.ok(existsSync(join(config, 'opencode.jsonc')), 'Ordinary OpenCode configuration must remain');
});
