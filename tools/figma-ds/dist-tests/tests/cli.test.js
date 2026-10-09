/**
 * Tests for src/cli.ts — exit codes of the top-level --dry-run guard.
 *
 * The guard lives at module top level, BEFORE loadConfig(): spawning the real
 * CLI (`node dist/cli.js sync --dry-run`) must exit 2 even with an environment
 * that cannot produce a valid config (no FIGMA_TOKEN, missing env file).
 * No network is involved — the process exits before any HTTP call.
 *
 * Paired proof of the ordering: with the SAME token-less env, plain `sync`
 * reaches loadConfig() and exits 1 ("FIGMA_TOKEN not found"), while
 * `sync --dry-run` exits 2 from the guard without ever loading the config.
 *
 * Requires `npm run build` (dist/cli.js) — tests are skipped when the build
 * output is absent, so a bare `npm test` never fails on a missing artifact.
 */
import { describe, test } from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import * as fs from 'node:fs';
import * as path from 'node:path';
import { fileURLToPath } from 'node:url';
const here = path.dirname(fileURLToPath(import.meta.url));
// Compiled test lives in dist-tests/tests/ → project root is two levels up
const projectRoot = path.resolve(here, '..', '..');
const cliPath = path.join(projectRoot, 'dist', 'cli.js');
/** Env stripped of FIGMA_TOKEN, with OPENCODE_ENV_FILE pointing at a missing
 *  file — config resolution is impossible, proving the guard fires first. */
function envWithoutToken() {
    const env = { ...process.env };
    delete env.FIGMA_TOKEN;
    env.OPENCODE_ENV_FILE = path.join(projectRoot, 'tests', 'does-not-exist.env');
    return env;
}
function runCli(args) {
    return spawnSync(process.execPath, [cliPath, ...args], {
        cwd: projectRoot,
        env: envWithoutToken(),
        encoding: 'utf-8',
        timeout: 15_000
    });
}
describe('cli exit codes — --dry-run guard (avant loadConfig)', () => {
    test('sync --dry-run → exit 2, stderr explicite, même sans FIGMA_TOKEN', (t) => {
        if (!fs.existsSync(cliPath)) {
            t.skip('dist/cli.js absent — lancer `npm run build` d\'abord');
            return;
        }
        const res = runCli(['sync', '--dry-run']);
        assert.strictEqual(res.status, 2);
        assert.match(res.stderr, /--dry-run is only supported/);
        // The guard fires before any sync work starts — nothing on stdout
        assert.ok(!res.stdout.includes('Starting sync'));
    });
    test('même env sans token : `sync` (sans --dry-run) atteint loadConfig et sort en 1 — preuve de l\'ordre', (t) => {
        if (!fs.existsSync(cliPath)) {
            t.skip('dist/cli.js absent — lancer `npm run build` d\'abord');
            return;
        }
        const res = runCli(['sync']);
        assert.strictEqual(res.status, 1);
        assert.match(res.stderr, /FIGMA_TOKEN not found/);
    });
});
