/**
 * Tests for src/normalize.ts — computeDiff and generateChangelogEntry.
 *
 * Fixtures use the exact payload shape the CLI passes to computeDiff
 * (see syncCommand in cli.ts): { styles, components, componentSets, pages, meta }.
 */
import { describe, test } from 'node:test';
import assert from 'node:assert/strict';
import { computeDiff, generateChangelogEntry } from '../src/normalize.js';
const AVAILABLE_META = { variables: { status: 'available' }, contentStatus: 'available' };
const GATED_META = { variables: { status: 'unavailable' }, contentStatus: 'gated' };
function side(overrides = {}) {
    return {
        styles: [],
        components: [],
        componentSets: [],
        pages: [],
        meta: AVAILABLE_META,
        ...overrides
    };
}
const NO_CHANGES = {
    styles: { added: 0, removed: 0, changed: 0 },
    components: { added: 0, removed: 0, changed: 0 },
    componentSets: { added: 0, removed: 0, changed: 0 },
    pages: { added: 0, removed: 0, changed: 0 },
    hasChanges: false
};
// ── computeDiff ──────────────────────────────────────────────────────────────
describe('computeDiff', () => {
    test('gated → available: new pages are counted as added', () => {
        const oldSide = side({ pages: [], meta: GATED_META });
        const newSide = side({ pages: [{ id: 'p1', name: 'A' }, { id: 'p2', name: 'B' }] });
        const diff = computeDiff(oldSide, newSide);
        assert.strictEqual(diff.pages.added, 2);
        assert.strictEqual(diff.pages.removed, 0);
        assert.strictEqual(diff.hasChanges, true);
    });
    test('available → gated: with newGated the empty page tree is excluded from the diff', () => {
        const oldSide = side({ pages: [{ id: 'p1' }, { id: 'p2' }] });
        const newSide = side({ pages: [], meta: GATED_META });
        const gated = computeDiff(oldSide, newSide, { newGated: true });
        assert.strictEqual(gated.pages.added, 0);
        assert.strictEqual(gated.pages.removed, 0, 'pages must NOT be reported as removed when the new capture is gated');
        assert.strictEqual(gated.hasChanges, true, 'quota transition alone marks the diff as changed');
        // Contrast: without the gate flag, the empty page tree would fake removals
        const naive = computeDiff(oldSide, newSide);
        assert.strictEqual(naive.pages.removed, 2);
    });
    test('styles / components / componentSets added, removed and changed', () => {
        const oldSide = side({
            styles: [
                { node_id: 's1', name: 'A', style_type: 'FILL' },
                { node_id: 's2', name: 'B', style_type: 'TEXT' },
                { node_id: 's4', name: 'D', style_type: 'EFFECT' }
            ],
            components: [
                { key: 'k1', description: 'd1' },
                { key: 'k2', description: 'd2' }
            ],
            componentSets: [{ key: 'cs1', description: 'x' }]
        });
        const newSide = side({
            styles: [
                { node_id: 's1', name: 'A', style_type: 'FILL' },
                { node_id: 's2', name: 'B2', style_type: 'TEXT' },
                { node_id: 's3', name: 'C', style_type: 'GRID' }
            ],
            components: [
                { key: 'k1', description: 'd1b' },
                { key: 'k3', description: 'd3' }
            ],
            componentSets: [{ key: 'cs1', description: 'x2' }]
        });
        const diff = computeDiff(oldSide, newSide);
        assert.deepEqual(diff.styles, { added: 1, removed: 1, changed: 1 });
        assert.deepEqual(diff.components, { added: 1, removed: 1, changed: 1 });
        assert.deepEqual(diff.componentSets, { added: 0, removed: 0, changed: 1 });
        assert.strictEqual(diff.hasChanges, true);
    });
    test('identical snapshots produce an all-zero diff with hasChanges false', () => {
        const same = side({
            styles: [{ node_id: 's1', name: 'A', style_type: 'FILL' }],
            components: [{ key: 'k1', description: 'd' }],
            componentSets: [],
            pages: [{ id: 'p1' }]
        });
        const diff = computeDiff(same, JSON.parse(JSON.stringify(same)));
        assert.deepEqual(diff, NO_CHANGES);
    });
    test('a variables status transition alone (quota/token) marks hasChanges', () => {
        const oldSide = side({ meta: { variables: { status: 'unavailable' }, contentStatus: 'available' } });
        const newSide = side({ meta: { variables: { status: 'available' }, contentStatus: 'available' } });
        const diff = computeDiff(oldSide, newSide);
        assert.deepEqual(diff.styles, { added: 0, removed: 0, changed: 0 });
        assert.deepEqual(diff.components, { added: 0, removed: 0, changed: 0 });
        assert.strictEqual(diff.hasChanges, true);
    });
});
// ── generateChangelogEntry ───────────────────────────────────────────────────
describe('generateChangelogEntry', () => {
    const meta = {
        syncedAt: '2026-09-03T10:00:00.000Z',
        file_name: 'Manager Design System',
        file_key: 'KEY123',
        lastModified: '2026-09-02T18:00:00.000Z',
        variables: { status: 'available', reason: 'ok' },
        contentStatus: 'gated'
    };
    test('gated snapshot is mentioned and counts are coherent', () => {
        const diff = {
            styles: { added: 2, removed: 1, changed: 1 },
            components: { added: 1, removed: 0, changed: 0 },
            componentSets: { added: 0, removed: 0, changed: 0 },
            pages: { added: 1, removed: 0, changed: 0 },
            hasChanges: true
        };
        const entry = generateChangelogEntry(diff, meta);
        assert.ok(entry.includes('## Sync du 2026-09-03'), 'date header');
        assert.ok(entry.includes('**Fichier**: Manager Design System (KEY123)'));
        assert.ok(entry.includes('**Variables**: ✓ (ok)'));
        assert.ok(entry.includes('> ⚠️ Snapshot dégradé (quota Figma) : structure des pages et valeurs résolues non comparées.'), 'gated warning must be mentioned');
        // Styles: 2 + 1 + 1 = 4 changements
        assert.ok(entry.includes('#### Styles (4 changements)'));
        assert.ok(entry.includes('- ✚ 2 ajouté(s)'));
        assert.ok(entry.includes('- ✖ 1 supprimé(s)'));
        assert.ok(entry.includes('- ~ 1 modifié(s)'));
        // Composants: 1 ajout
        assert.ok(entry.includes('#### Composants (1 changements)'));
        // Pages: 1 ajout
        assert.ok(entry.includes('#### Pages (1 changements)'));
        // ComponentSets: 0 changement → section absente
        assert.ok(!entry.includes('Variant Sets'));
    });
    test('non-gated snapshot does not carry the degraded mention', () => {
        const entry = generateChangelogEntry(NO_CHANGES, { ...meta, contentStatus: 'available' });
        assert.ok(!entry.includes('dégradé'));
    });
    test('empty diff produces the "Aucun changement" line and no changelog section', () => {
        const entry = generateChangelogEntry(NO_CHANGES, { ...meta, contentStatus: 'available' });
        assert.ok(entry.includes('Aucun changement structurel détecté.'));
        assert.ok(!entry.includes('### Changelog'));
    });
});
