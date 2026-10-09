/**
 * Tests for src/mapping.ts
 *
 * Strategy: pure functions (scoreMatch) tested directly; generateMapping tested
 * through its public contract with throwaway fixture directories. The reference
 * file paths are injected via the optional MappingSourceOptions parameter so the
 * tests stay hermetic (the bundled references may evolve — the fixtures must not).
 */
import { describe, test } from 'node:test';
import assert from 'node:assert/strict';
import * as fs from 'node:fs';
import * as os from 'node:os';
import * as path from 'node:path';
import { generateMapping, scoreMatch } from '../src/mapping.js';
// ── Helpers ──────────────────────────────────────────────────────────────────
function makeTmpDir(prefix) {
    return fs.mkdtempSync(path.join(os.tmpdir(), `figma-ds-${prefix}-`));
}
function rmDir(dir) {
    fs.rmSync(dir, { recursive: true, force: true });
}
function writeFixture(dir, fixture) {
    fs.writeFileSync(path.join(dir, 'components.json'), JSON.stringify({ components: fixture.components ?? [], componentSets: fixture.componentSets ?? [] }));
    if (fixture.families !== undefined) {
        fs.writeFileSync(path.join(dir, 'figma-families.reference.json'), JSON.stringify({ families: fixture.families }));
    }
    fs.writeFileSync(path.join(dir, 'ik-components.reference.json'), JSON.stringify({ components: fixture.ikComponents ?? [] }));
    if (fixture.mapping) {
        fs.writeFileSync(path.join(dir, 'mapping.json'), JSON.stringify(fixture.mapping));
    }
}
function runMapping(dir, fixture, dryRun = true) {
    writeFixture(dir, fixture);
    return generateMapping(dir, dryRun, {
        referenceFile: path.join(dir, 'ik-components.reference.json'),
        familiesFile: path.join(dir, 'figma-families.reference.json')
    });
}
// ── scoreMatch ───────────────────────────────────────────────────────────────
describe('scoreMatch', () => {
    test('exact multi-word match scores 1.0 (case, capitalization and dash-insensitive)', () => {
        assert.strictEqual(scoreMatch('Radio buttons', 'radio-buttons'), 1);
        assert.strictEqual(scoreMatch('Actions menu', 'actions-menu'), 1);
    });
    test('plural family matches singular component (exact score)', () => {
        assert.strictEqual(scoreMatch('icons', 'icon'), 1);
    });
    test('1-char family name does not match anything (containment guard < 4 chars)', () => {
        assert.ok(scoreMatch('a', 'actions-menu') < 0.5);
    });
    test('2-char fragment does not match (containment guard < 4 chars)', () => {
        assert.ok(scoreMatch('in', 'click-or-link') < 0.5);
    });
    test('unrelated names stay below the 0.5 matching threshold', () => {
        assert.ok(scoreMatch('toast', 'badge') < 0.5);
    });
    test('3-char prefix gets no containment boost — plain token overlap only', () => {
        // tokenScore = 1/2 = 0.5; containment must NOT fire ("tab" is 3 chars < 4)
        assert.strictEqual(scoreMatch('tab', 'tab-panel'), 0.5);
    });
    test('full containment (>= 4 chars) gets the 0.8 boost', () => {
        assert.strictEqual(scoreMatch('side panel drawer', 'drawer'), 0.8);
    });
    test('accents and emoji in family names are handled without crashing', () => {
        const s = scoreMatch('Héros 🚀', 'hero');
        assert.ok(Number.isFinite(s), 'score must be a finite number');
        assert.ok(s >= 0 && s <= 1, `score must be in [0, 1], got ${s}`);
    });
    test('degenerate inputs score 0', () => {
        assert.strictEqual(scoreMatch('', 'button'), 0);
        assert.strictEqual(scoreMatch('...', 'button'), 0);
    });
});
// ── generateMapping ──────────────────────────────────────────────────────────
describe('generateMapping', () => {
    test('greedy: when two families claim the same ik, the best score wins', () => {
        const dir = makeTmpDir('greedy');
        try {
            // "Buttons" (1.0) and "Button group" (0.8 via containment) both target
            // "button" — Buttons must win. "Radio buttons" (in the reference) claims
            // "radio-buttons" at 1.0 before "Button group" can fall back on it.
            // NOTE: derived families (from components.json prefixes) are report-only
            // since the matching fix — they never enter the candidates pool.
            const result = runMapping(dir, {
                families: ['Buttons', 'Button group', 'Menu', 'Radio buttons'],
                ikComponents: [
                    { name: 'button', category: 'Elements' },
                    { name: 'menu', category: 'Elements' },
                    { name: 'radio-buttons', category: 'Elements' }
                ],
                components: [
                    { name: 'Button/Primary' },
                    { name: 'Button group/Basic' },
                    { name: 'Menu/Item' },
                    { name: 'Radio buttons/Option 1' }
                ]
            });
            assert.deepEqual(result.entries.map(e => ({ figma: e.figma, ik: e.ik, confidence: e.confidence })), [
                { figma: 'Buttons', ik: 'button', confidence: 'exact' },
                { figma: 'Menu', ik: 'menu', confidence: 'exact' },
                { figma: 'Radio buttons', ik: 'radio-buttons', confidence: 'exact' }
            ]);
            assert.deepEqual(result.figmaOnly, ['Button group']);
            assert.deepEqual(result.codeOnly, []);
            // Derived families missing from the reference are reported, never matched
            assert.deepEqual(result.unreferencedFamilies, ['button', 'menu', 'radio']);
        }
        finally {
            rmDir(dir);
        }
    });
    test('manual entries survive regeneration and reserve their figma family + ik', () => {
        const dir = makeTmpDir('manual');
        try {
            const result = runMapping(dir, {
                families: ['Buttons', 'Menu'],
                ikComponents: [
                    { name: 'button', category: 'Elements' },
                    { name: 'menu', category: 'Elements' }
                ],
                components: [{ name: 'Button/Primary' }, { name: 'Menu/Item' }],
                mapping: {
                    entries: [
                        { figma: 'Buttons', ik: 'button', confidence: 'manual' },
                        { figma: 'Menu', ik: 'menu', confidence: 'manual' }
                    ]
                }
            });
            assert.strictEqual(result.entries.length, 2);
            for (const entry of result.entries) {
                assert.strictEqual(entry.confidence, 'manual');
            }
            assert.ok(result.entries.some(e => e.figma === 'Buttons' && e.ik === 'button'));
            assert.ok(result.entries.some(e => e.figma === 'Menu' && e.ik === 'menu'));
            // No auto entry was generated on top of the manual ones
            assert.ok(result.entries.every(e => e.confidence === 'manual'));
        }
        finally {
            rmDir(dir);
        }
    });
    test('orphaned manual entries are excluded and listed in orphanedManualEntries', () => {
        const dir = makeTmpDir('orphans');
        try {
            const result = runMapping(dir, {
                families: ['Buttons'],
                ikComponents: [
                    { name: 'button', category: 'Elements' },
                    { name: 'menu', category: 'Elements' }
                ],
                components: [{ name: 'Button/Primary' }],
                mapping: {
                    entries: [
                        { figma: 'Buttons', ik: 'button', confidence: 'manual' }, // valid → kept
                        { figma: 'Ghost', ik: 'button', confidence: 'manual' }, // family gone → orphan
                        { figma: 'Menu', ik: 'nonexistent', confidence: 'manual' } // ik gone → orphan
                    ]
                }
            });
            assert.strictEqual(result.entries.length, 1);
            assert.strictEqual(result.entries[0].figma, 'Buttons');
            assert.strictEqual(result.entries[0].confidence, 'manual');
            assert.deepEqual(result.orphanedManualEntries, ['Ghost → ik-button', 'Menu → ik-nonexistent']);
            assert.deepEqual(result.figmaOnly, []);
            assert.deepEqual(result.codeOnly, ['menu']);
        }
        finally {
            rmDir(dir);
        }
    });
    test('derived families ("a", "menu", "select") missing from the reference are reported but NEVER matched', () => {
        const dir = makeTmpDir('unreferenced');
        try {
            // Regression guard: without the manual families reference as sole matching
            // source, "menu"/"select" derived from component names would create bogus
            // exact matches against ik-menu/ik-select.
            const result = runMapping(dir, {
                families: ['Buttons'],
                ikComponents: [
                    { name: 'button', category: 'Elements' },
                    { name: 'menu', category: 'Elements' },
                    { name: 'select', category: 'Elements' }
                ],
                components: [
                    { name: 'a thing' },
                    { name: 'menu bar item' },
                    { name: 'select row' },
                    { name: 'Button/Primary' }
                ]
            });
            assert.strictEqual(result.entries.length, 1);
            assert.strictEqual(result.entries[0].figma, 'Buttons');
            assert.strictEqual(result.entries[0].ik, 'button');
            assert.ok(!result.entries.some(e => ['a', 'menu', 'select'].includes(e.figma)));
            assert.deepEqual(result.unreferencedFamilies, ['a', 'menu', 'select', 'button']);
            assert.ok(result.codeOnly.includes('menu'));
            assert.ok(result.codeOnly.includes('select'));
        }
        finally {
            rmDir(dir);
        }
    });
    test('fallback: without a families reference, derived families are used for matching', () => {
        const dir = makeTmpDir('fallback');
        try {
            const result = runMapping(dir, {
                // no `families` → reference file absent
                ikComponents: [
                    { name: 'button', category: 'Elements' },
                    { name: 'menu', category: 'Elements' }
                ],
                components: [{ name: 'Button/Primary' }, { name: 'Random/Thing' }]
            });
            assert.strictEqual(result.entries.length, 1);
            assert.strictEqual(result.entries[0].figma, 'button');
            assert.strictEqual(result.entries[0].ik, 'button');
            assert.strictEqual(result.entries[0].confidence, 'exact');
            assert.deepEqual(result.figmaOnly, ['random']);
            assert.deepEqual(result.codeOnly, ['menu']);
            // In fallback mode every family is derived, hence flagged as unreferenced
            assert.deepEqual(result.unreferencedFamilies, ['button', 'random']);
        }
        finally {
            rmDir(dir);
        }
    });
    test('writes mapping.json when regenerating without dry-run', () => {
        const dir = makeTmpDir('write');
        try {
            const result = runMapping(dir, {
                families: ['Buttons'],
                ikComponents: [{ name: 'button', category: 'Elements' }],
                components: [{ name: 'Button/Primary' }]
            }, false);
            const mappingPath = path.join(dir, 'mapping.json');
            assert.ok(fs.existsSync(mappingPath), 'mapping.json should be written');
            const written = JSON.parse(fs.readFileSync(mappingPath, 'utf-8'));
            assert.deepEqual(written.entries.map((e) => ({ figma: e.figma, ik: e.ik, confidence: e.confidence })), [{ figma: 'Buttons', ik: 'button', confidence: 'exact' }]);
            assert.ok(typeof written.generatedAt === 'string');
            // Returned result matches what was written
            assert.strictEqual(result.entries.length, 1);
        }
        finally {
            rmDir(dir);
        }
    });
    test('throws when the snapshot directory has no components.json', () => {
        const dir = makeTmpDir('missing');
        try {
            assert.throws(() => generateMapping(dir, true, { referenceFile: path.join(dir, 'nope.json') }), /No snapshot found/);
        }
        finally {
            rmDir(dir);
        }
    });
});
