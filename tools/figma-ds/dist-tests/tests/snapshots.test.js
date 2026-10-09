/**
 * Tests for src/snapshots.ts — loadExistingSnapshot, validateSnapshotIntegrity
 * (incl. the gated pages exemption), writeSnapshot (gated preservation +
 * variables guard) and CommitError. Only the public contract is tested (no fs
 * spying, no private access): files are real, written into throwaway temp dirs.
 */
import { describe, test } from 'node:test';
import assert from 'node:assert/strict';
import * as fs from 'node:fs';
import * as os from 'node:os';
import * as path from 'node:path';
import { loadExistingSnapshot, validateSnapshotIntegrity, createSnapshotWriter, writeSnapshot, CommitError, DataIntegrityError } from '../src/snapshots.js';
// ── Helpers ──────────────────────────────────────────────────────────────────
function makeTmpDir(prefix) {
    return fs.mkdtempSync(path.join(os.tmpdir(), `figma-ds-${prefix}-`));
}
function rmDir(dir) {
    fs.rmSync(dir, { recursive: true, force: true });
}
function writeFile(dir, name, content) {
    fs.writeFileSync(path.join(dir, name), typeof content === 'string' ? content : JSON.stringify(content));
}
/** Builds a NormalizedOutput-shaped object with controllable counts. */
function snap(counts, contentStatus = 'available') {
    const ids = (n, prefix) => Array.from({ length: n }, (_, i) => ({ id: `${prefix}${i}` }));
    return {
        meta: {
            file_key: 'KEY',
            file_name: 'DS',
            lastModified: '2026-01-01T00:00:00Z',
            version: '1',
            syncedAt: '2026-09-03T00:00:00Z',
            contentStatus,
            counts: { pages: 0, styles: 0, components: 0, componentSets: 0 },
            variables: { status: 'available' }
        },
        structure: { pages: counts.pages !== undefined ? ids(counts.pages, 'p') : [] },
        styles: counts.styles !== undefined ? ids(counts.styles, 's') : [],
        components: {
            components: counts.comps !== undefined ? ids(counts.comps, 'c') : [],
            componentSets: counts.sets !== undefined ? ids(counts.sets, 't') : [],
            componentProperties: [],
            componentPropertiesStatus: 'complete'
        },
        variables: { status: 'available', variables: [] }
    };
}
// ── loadExistingSnapshot ─────────────────────────────────────────────────────
describe('loadExistingSnapshot', () => {
    test('returns null when there is no meta.json', () => {
        const dir = makeTmpDir('empty');
        try {
            assert.strictEqual(loadExistingSnapshot(dir), null);
        }
        finally {
            rmDir(dir);
        }
    });
    test('throws with a "corrupted" message when meta.json is invalid JSON', () => {
        const dir = makeTmpDir('corrupt');
        try {
            writeFile(dir, 'meta.json', '{invalid json');
            assert.throws(() => loadExistingSnapshot(dir), /corrupted/);
        }
        finally {
            rmDir(dir);
        }
    });
    test('throws when meta.json is missing required fields', () => {
        const dir = makeTmpDir('nofields');
        try {
            writeFile(dir, 'meta.json', { counts: {} });
            assert.throws(() => loadExistingSnapshot(dir), /corrupted/);
        }
        finally {
            rmDir(dir);
        }
    });
    test('loads a valid snapshot', () => {
        const dir = makeTmpDir('valid');
        try {
            writeFile(dir, 'meta.json', {
                file_key: 'KEY',
                file_name: 'DS',
                lastModified: '2026-01-01T00:00:00Z',
                version: '9',
                syncedAt: '2026-09-03T00:00:00Z',
                contentStatus: 'available',
                counts: { pages: 1, styles: 1, components: 0, componentSets: 0 },
                variables: { status: 'available' }
            });
            writeFile(dir, 'structure.json', { pages: [{ name: 'Page 1', id: 'p1', depth: 0 }] });
            writeFile(dir, 'styles.json', [{ key: 'k', node_id: 'n1', name: 'Primary', style_type: 'fill' }]);
            writeFile(dir, 'components.json', {
                components: [],
                componentSets: [],
                componentProperties: [],
                componentPropertiesStatus: 'complete'
            });
            writeFile(dir, 'variables.json', { status: 'available', variables: [] });
            const loaded = loadExistingSnapshot(dir);
            assert.ok(loaded !== null);
            assert.strictEqual(loaded.meta.file_key, 'KEY');
            assert.strictEqual(loaded.structure.pages.length, 1);
            assert.strictEqual(loaded.styles.length, 1);
            assert.strictEqual(loaded.components.componentPropertiesStatus, 'complete');
            assert.strictEqual(loaded.variables.status, 'available');
        }
        finally {
            rmDir(dir);
        }
    });
    test('corrupted optional files are tolerated (null) — only meta.json corruption throws', () => {
        const dir = makeTmpDir('optional');
        try {
            writeFile(dir, 'meta.json', { file_key: 'KEY', file_name: 'DS' });
            writeFile(dir, 'styles.json', '{oops not json');
            const loaded = loadExistingSnapshot(dir);
            assert.ok(loaded !== null);
            assert.strictEqual(loaded.styles, null);
            assert.strictEqual(loaded.structure, null);
        }
        finally {
            rmDir(dir);
        }
    });
});
// ── validateSnapshotIntegrity ────────────────────────────────────────────────
describe('validateSnapshotIntegrity', () => {
    test('a drop > 50 % in a count throws DataIntegrityError', () => {
        const previous = snap({ styles: 10, comps: 10, sets: 10, pages: 10 });
        const current = snap({ styles: 4, comps: 10, sets: 10, pages: 10 });
        assert.throws(() => validateSnapshotIntegrity(current, previous), DataIntegrityError);
        assert.throws(() => validateSnapshotIntegrity(current, previous), /suspicious drop in styles/);
    });
    test('--force bypasses the check (warns instead of throwing)', () => {
        const previous = snap({ styles: 10, comps: 10, sets: 10, pages: 10 });
        const current = snap({ styles: 4, comps: 10, sets: 10, pages: 10 });
        assert.doesNotThrow(() => validateSnapshotIntegrity(current, previous, true));
    });
    test('stable counts pass', () => {
        const previous = snap({ styles: 10, comps: 10, sets: 10, pages: 10 });
        const current = snap({ styles: 10, comps: 10, sets: 10, pages: 10 });
        assert.doesNotThrow(() => validateSnapshotIntegrity(current, previous));
    });
    test('a drop of exactly 50 % is accepted (strictly-more-than-50 rule)', () => {
        const previous = snap({ styles: 10 });
        const current = snap({ styles: 5 });
        assert.doesNotThrow(() => validateSnapshotIntegrity(current, previous));
    });
    test('a suspicious pages drop is detected too', () => {
        const previous = snap({ styles: 2, comps: 2, sets: 2, pages: 4 });
        const current = snap({ styles: 2, comps: 2, sets: 2, pages: 1 });
        assert.throws(() => validateSnapshotIntegrity(current, previous), /suspicious drop in pages/);
    });
    test('no previous snapshot → no check, no throw', () => {
        assert.doesNotThrow(() => validateSnapshotIntegrity(snap({ styles: 2 }), null));
    });
});
// ── validateSnapshotIntegrity — exemption pages en gated ─────────────────────
describe('validateSnapshotIntegrity — exemption pages en gated', () => {
    test('previous 12 pages + current gated (0 pages) → pas de throw (pages exempté)', () => {
        const previous = snap({ styles: 4, comps: 4, sets: 4, pages: 12 });
        const current = snap({ styles: 4, comps: 4, sets: 4, pages: 0 }, 'gated');
        assert.doesNotThrow(() => validateSnapshotIntegrity(current, previous));
    });
    test('le garde styles reste actif en gated : 100 → 30 → DataIntegrityError', () => {
        const previous = snap({ styles: 100, comps: 10, sets: 10, pages: 12 });
        const current = snap({ styles: 30, comps: 10, sets: 10, pages: 0 }, 'gated');
        assert.throws(() => validateSnapshotIntegrity(current, previous), DataIntegrityError);
        assert.throws(() => validateSnapshotIntegrity(current, previous), /suspicious drop in styles/);
    });
    test('--force transforme le drop styles (gated) en warning, sans throw', () => {
        const previous = snap({ styles: 100, comps: 10, sets: 10, pages: 12 });
        const current = snap({ styles: 30, comps: 10, sets: 10, pages: 0 }, 'gated');
        assert.doesNotThrow(() => validateSnapshotIntegrity(current, previous, true));
    });
});
// ── writeSnapshot — préservation gated + garde variables ─────────────────────
/** Minimal raw payload accepted by writeSnapshot (null fileData is skipped). */
const emptyRaw = { fileData: null, stylesMeta: {}, componentsMeta: {}, componentSetsMeta: {} };
/** A complete, healthy snapshot — the "previous" side of gated scenarios. */
function completeSnapshot(overrides = {}) {
    return {
        meta: {
            file_key: 'KEY',
            file_name: 'DS',
            lastModified: '2026-01-01T00:00:00Z',
            version: '1',
            syncedAt: overrides.syncedAt ?? '2026-09-01T00:00:00Z',
            contentStatus: 'available',
            counts: { pages: 2, styles: 2, components: 2, componentSets: 1 },
            variables: { status: 'available' }
        },
        structure: {
            pages: [
                { name: 'Page 1', id: 'p1', childCount: 0, depth: 0 },
                { name: 'Page 2', id: 'p2', childCount: 3, depth: 0 }
            ]
        },
        styles: [
            { key: 'k1', file_key: 'KEY', node_id: 'n1', name: 'Primary', style_type: 'fill', resolvedValue: '#FF540B' },
            { key: 'k2', file_key: 'KEY', node_id: 'n2', name: 'Body', style_type: 'text', resolvedValue: { fontFamily: 'Inter' } }
        ],
        components: {
            components: [
                { key: 'c1', node_id: '1:1', name: 'Button' },
                { key: 'c2', node_id: '1:2', name: 'Badge' }
            ],
            componentSets: [{ key: 's1', node_id: '2:1', name: 'Button' }],
            componentProperties: [],
            componentPropertiesStatus: 'complete'
        },
        variables: overrides.variables ?? { status: 'available', count: 5 }
    };
}
/** The degraded snapshot a gated sync produces (content endpoints 429). */
function gatedSnapshot() {
    return {
        meta: {
            file_key: 'KEY',
            file_name: 'Manager Design System',
            lastModified: '2026-01-02T00:00:00Z',
            version: '2',
            syncedAt: '2026-09-03T00:00:00Z',
            contentStatus: 'gated',
            counts: { pages: 0, styles: 0, components: 0, componentSets: 0 },
            variables: { status: 'unavailable' }
        },
        structure: { pages: [] },
        styles: [],
        components: { components: [], componentSets: [], componentProperties: [], componentPropertiesStatus: 'complete' },
        variables: { status: 'unavailable', reason: 'Figma API quota exhausted' }
    };
}
function readJson(dir, name) {
    return JSON.parse(fs.readFileSync(path.join(dir, name), 'utf-8'));
}
describe('writeSnapshot — préservation gated (scénario central)', () => {
    test("meta gated + previous complet → structure/styles/variables préservés (contenus inchangés), meta.json réécrit", () => {
        const dir = makeTmpDir('gated-preserve');
        try {
            const writer = createSnapshotWriter(dir);
            const previous = completeSnapshot();
            const current = gatedSnapshot();
            // Phase 1 — a healthy sync writes the full snapshot to disk
            const first = writeSnapshot(writer, previous, emptyRaw, null);
            assert.deepEqual(first.preserved, []);
            // Phase 2 — the gated sync must not clobber the good data
            const result = writeSnapshot(writer, current, emptyRaw, previous);
            assert.deepEqual(result.preserved, ['structure.json', 'styles.json', 'variables.json']);
            assert.ok(result.written.includes('meta.json'));
            assert.ok(result.written.includes('components.json'));
            assert.ok(!result.written.includes('structure.json'));
            assert.ok(!result.written.includes('styles.json'));
            assert.ok(!result.written.includes('variables.json'));
            // Preserved = previous content on disk, NOT the empty gated payload
            assert.deepEqual(readJson(dir, 'structure.json'), previous.structure);
            assert.deepEqual(readJson(dir, 'styles.json'), previous.styles);
            assert.deepEqual(readJson(dir, 'variables.json'), { status: 'available', count: 5 });
            assert.ok(readJson(dir, 'styles.json').some((s) => s.resolvedValue !== undefined));
            // meta.json is always rewritten with the new (gated) meta
            const meta = readJson(dir, 'meta.json');
            assert.strictEqual(meta.contentStatus, 'gated');
            assert.strictEqual(meta.syncedAt, current.meta.syncedAt);
            assert.notStrictEqual(meta.syncedAt, previous.meta.syncedAt);
        }
        finally {
            rmDir(dir);
        }
    });
});
describe('writeSnapshot — garde variables', () => {
    test("new 'unavailable' + previous {available, count 5} → variables.json préservé (structure/styles écrits)", () => {
        const dir = makeTmpDir('vars-preserve');
        try {
            const writer = createSnapshotWriter(dir);
            const previous = completeSnapshot();
            const current = completeSnapshot({
                syncedAt: '2026-09-03T00:00:00Z',
                variables: { status: 'unavailable', reason: 'Token missing variables scope' }
            });
            writeSnapshot(writer, previous, emptyRaw, null);
            const result = writeSnapshot(writer, current, emptyRaw, previous);
            assert.deepEqual(result.preserved, ['variables.json']);
            assert.ok(result.written.includes('structure.json'));
            assert.ok(result.written.includes('styles.json'));
            assert.ok(!result.written.includes('variables.json'));
            assert.deepEqual(readJson(dir, 'variables.json'), { status: 'available', count: 5 });
        }
        finally {
            rmDir(dir);
        }
    });
    test("previous {unavailable, count 0} → variables.json écrasé par les nouvelles données", () => {
        const dir = makeTmpDir('vars-overwrite');
        try {
            const writer = createSnapshotWriter(dir);
            const previous = completeSnapshot({ variables: { status: 'unavailable', reason: 'older outage', count: 0 } });
            const current = completeSnapshot({
                syncedAt: '2026-09-03T00:00:00Z',
                variables: { status: 'unavailable', reason: 'Figma API quota exhausted' }
            });
            writeSnapshot(writer, previous, emptyRaw, null);
            const result = writeSnapshot(writer, current, emptyRaw, previous);
            assert.deepEqual(result.preserved, []);
            assert.ok(result.written.includes('variables.json'));
            assert.deepEqual(readJson(dir, 'variables.json'), { status: 'unavailable', reason: 'Figma API quota exhausted' });
        }
        finally {
            rmDir(dir);
        }
    });
});
// ── CommitError ──────────────────────────────────────────────────────────────
describe('CommitError', () => {
    test('is a named Error carrying the message', () => {
        const err = new CommitError('git commit failed');
        assert.ok(err instanceof Error);
        assert.ok(err instanceof CommitError);
        assert.strictEqual(err.name, 'CommitError');
        assert.strictEqual(err.message, 'git commit failed');
    });
});
