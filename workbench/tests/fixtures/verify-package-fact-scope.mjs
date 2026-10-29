import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import assert from 'node:assert/strict';

function canonical(value) {
  if (Array.isArray(value)) return `[${value.map(canonical).join(',')}]`;
  if (value !== null && typeof value === 'object') {
    return `{${Object.keys(value).sort().map(key => `${JSON.stringify(key)}:${canonical(value[key])}`).join(',')}}`;
  }
  if (typeof value === 'number') assert(Number.isSafeInteger(value));
  return JSON.stringify(value);
}

const vectors = JSON.parse(readFileSync(new URL('./package-fact-scope-vectors.json', import.meta.url), 'utf8'));
for (const { name, expected } of vectors) {
  assert.equal(createHash('sha256').update(canonical(expected.manifest), 'utf8').digest('hex'), expected.digest, name);
  assert.equal(expected.manifest.facts_qualified, false);
  assert.equal(expected.manifest.launch_available, false);
}
assert.equal(vectors[1].expected.manifest.previous_digest, vectors[0].expected.digest);
assert.equal(vectors[2].expected.manifest.previous_digest, vectors[1].expected.digest);
process.stdout.write(`Verified ${vectors.length} independent scope identity vectors.\n`);
