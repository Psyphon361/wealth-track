#!/usr/bin/env node
// Deletes stale build artifacts for the web (Next.js) and api (FastAPI) apps.
// Run from anywhere with: npm run clean (from the repo root).
// Never touches node_modules (except web/node_modules/.cache), api/.venv, .env* files or web/next-env.d.ts.
import { existsSync, readdirSync, rmSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');

// Fixed targets, relative to the repo root.
const FIXED_TARGETS = [
  'web/.next',
  'web/tsconfig.tsbuildinfo',
  'web/node_modules/.cache',
  'api/.pytest_cache',
  'api/.ruff_cache',
  'api/.mypy_cache',
];

// Directory names the api walk never descends into.
const SKIP_DIRS = new Set(['.venv', 'node_modules']);

// Collects __pycache__ directories and stray *.pyc files under dir.
// Symlinks are not followed, so nothing outside the repo is reached.
function walkApi(dir, found) {
  let entries;
  try {
    entries = readdirSync(dir, { withFileTypes: true });
  } catch {
    return found;
  }
  for (const entry of entries) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      if (entry.name === '__pycache__') {
        found.push(full);
      } else if (!SKIP_DIRS.has(entry.name)) {
        walkApi(full, found);
      }
    } else if (entry.isFile() && entry.name.endsWith('.pyc')) {
      found.push(full);
    }
  }
  return found;
}

function rel(p) {
  return path.relative(ROOT, p).split(path.sep).join('/');
}

const candidates = [];
for (const p of FIXED_TARGETS) {
  const full = path.join(ROOT, p);
  if (existsSync(full)) candidates.push(full);
}

const apiDir = path.join(ROOT, 'api');
if (existsSync(apiDir)) walkApi(apiDir, candidates);

// Drop duplicates and anything nested inside another target (already removed with its parent).
const unique = [...new Set(candidates)];
const targets = unique.filter(
  (t) => !unique.some((o) => o !== t && t.startsWith(o + path.sep)),
);

for (const t of targets) {
  rmSync(t, { recursive: true, force: true });
  console.log(rel(t));
}

if (targets.length === 0) {
  console.log('Nothing to clean');
} else {
  console.log(`Removed ${targets.length} ${targets.length === 1 ? 'path' : 'paths'}`);
}
