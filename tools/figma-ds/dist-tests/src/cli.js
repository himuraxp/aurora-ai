#!/usr/bin/env node
/**
 * Figma Design System Sync CLI
 *
 * Commands:
 *   check   - Check if sync is needed
 *   sync    - Perform full sync
 *   diff    - Show diff between snapshots
 *   mapping - Generate Figma ↔ ik-* component mapping
 */
import { execSync } from 'node:child_process';
import { loadConfig } from './config.js';
import { FigmaClient, FigmaQuotaError } from './figma-client.js';
import { captureAll } from './capture.js';
import { normalizeCapture, computeDiff, generateChangelogEntry } from './normalize.js';
import { generateMapping } from './mapping.js';
import { createSnapshotWriter, initSnapshotsRepo, writeSnapshot, loadExistingSnapshot, updateChangelog, commitSnapshot, validateSnapshotIntegrity, CommitError, DataIntegrityError } from './snapshots.js';
function emitJsonResult(result) {
    console.log(`##JSON## ${JSON.stringify(result)}`);
}
const args = process.argv.slice(2);
const command = args[0];
const fileKeyArg = args.find(a => a.startsWith('--file='))?.split('=')[1];
const dryRun = args.includes('--dry-run');
const force = args.includes('--force');
if (!command || !['check', 'sync', 'diff', 'mapping'].includes(command)) {
    console.error('Usage: figma-ds-sync <command> [--file=<key>] [--dry-run | --force]');
    console.error('Commands: check, sync, diff, mapping');
    console.error('Options:');
    console.error('  --file=<key>   Figma file key to sync');
    console.error('  --dry-run      Only supported by mapping command');
    console.error('  --force        Skip data integrity checks (use with caution)');
    process.exit(1);
}
// Reject --dry-run before anything else (documented exit 2, even without FIGMA_TOKEN)
if (dryRun && command !== 'mapping') {
    console.error('Error: --dry-run is only supported by the mapping command');
    process.exit(2);
}
async function main() {
    let config;
    try {
        config = loadConfig();
    }
    catch (error) {
        console.error(`Error: ${error.message}`);
        process.exit(1);
    }
    const fileKey = fileKeyArg || config.fileKey;
    const client = new FigmaClient(config.figmaToken);
    const writer = createSnapshotWriter(config.snapshotsDir);
    switch (command) {
        case 'check':
            await checkCommand(client, fileKey, config.snapshotsDir);
            break;
        case 'sync':
            await syncCommand(client, fileKey, writer, config.snapshotsDir);
            break;
        case 'diff':
            await diffCommand(client, fileKey, config.snapshotsDir);
            break;
        case 'mapping':
            // Local-only operation: snapshot data + ik reference, never hits the Figma API
            const mappingResult = generateMapping(config.snapshotsDir, dryRun);
            emitJsonResult({
                command: 'mapping',
                ok: true,
                written: dryRun ? [] : ['mapping.json'],
                exactMatches: mappingResult.entries.filter(e => e.confidence === 'exact').length,
                fuzzyMatches: mappingResult.entries.filter(e => e.confidence === 'fuzzy').length,
                manualMatches: mappingResult.entries.filter(e => e.confidence === 'manual').length,
                dryRun
            });
            break;
    }
}
async function checkCommand(client, fileKey, snapshotsDir) {
    console.log(`Checking sync status for file ${fileKey}...`);
    try {
        // /versions is lightweight and never gated by Figma's plan quota
        // (unlike /files/{key} which can 429 for days on plan-tier paywalls).
        // Note: version created_at can slightly trail the exact lastModified (autosaves).
        const versions = await client.getVersions(fileKey);
        const lastModified = versions.versions?.[0]?.created_at;
        if (!lastModified) {
            console.error('Error: /versions returned no version — cannot determine last modification date');
            process.exit(1);
        }
        // Load existing meta
        const existing = loadExistingSnapshot(snapshotsDir);
        if (!existing || !existing.meta) {
            console.log('SYNC REQUIS — aucun snapshot local trouvé');
            process.exitCode = 1;
            return;
        }
        // Check fileKey mismatch
        if (existing.meta.file_key && existing.meta.file_key !== fileKey) {
            console.error(`Error: snapshot dir contains data for file ${existing.meta.file_key}, refusing to mix with ${fileKey}`);
            process.exit(2);
        }
        const localLastModified = existing.meta.lastModified;
        // Compare as real timestamps — lexicographic comparison breaks on mixed ISO precisions
        if (Date.parse(lastModified) > Date.parse(localLastModified)) {
            console.log(`SYNC REQUIS (lastModified ${lastModified} > sync du ${localLastModified})`);
            process.exitCode = 1;
            return;
        }
        console.log('À JOUR');
        emitJsonResult({ command: 'check', ok: true, dryRun });
        // Natural exit (no process.exit): piped stdout is async — process.exit would
        // truncate the log lines above (observed: empty output with exit 0).
    }
    catch (error) {
        if (error instanceof FigmaQuotaError) {
            console.error(`Quota Figma épuisé — impossible de vérifier maintenant. ${error.message}`);
            process.exit(2);
        }
        console.error(`Error checking sync status: ${error.message}`);
        process.exit(1);
    }
}
async function syncCommand(client, fileKey, writer, snapshotsDir) {
    console.log(`Starting sync for file ${fileKey}...`);
    const startTime = Date.now();
    try {
        // Initialize repo if needed
        initSnapshotsRepo(snapshotsDir);
        // Load existing snapshot for diff
        const existing = loadExistingSnapshot(snapshotsDir);
        // Check fileKey mismatch
        if (existing?.meta?.file_key && existing.meta.file_key !== fileKey) {
            console.error(`Error: snapshot dir contains data for file ${existing.meta.file_key}, refusing to mix with ${fileKey}`);
            process.exit(2);
        }
        // Capture all data
        const captureResult = await captureAll(client, fileKey);
        // Normalize
        const normalized = normalizeCapture(captureResult);
        // Guard against lastModified regression in gated mode (version date < autosave date)
        if (existing?.meta && normalized.meta.contentStatus === 'gated') {
            const maxDate = [existing.meta.lastModified, normalized.meta.lastModified]
                .map(d => Date.parse(d))
                .sort()
                .pop();
            normalized.meta.lastModified = new Date(maxDate).toISOString();
        }
        // Validate data integrity before writing
        try {
            validateSnapshotIntegrity(normalized, existing, force);
        }
        catch (error) {
            if (error instanceof DataIntegrityError) {
                console.error(`Error: ${error.message}`);
                process.exit(3);
            }
            throw error;
        }
        // Compute diff
        const diff = existing
            ? computeDiff({
                styles: existing.styles,
                components: existing.components?.components,
                componentSets: existing.components?.componentSets,
                pages: existing.structure?.pages,
                meta: existing.meta
            }, {
                styles: normalized.styles,
                components: normalized.components.components,
                componentSets: normalized.components.componentSets,
                pages: normalized.structure.pages,
                meta: normalized.meta
            }, { newGated: normalized.meta.contentStatus === 'gated' })
            : {
                styles: { added: normalized.styles.length, removed: 0, changed: 0 },
                components: { added: normalized.components.components.length, removed: 0, changed: 0 },
                componentSets: { added: normalized.components.componentSets.length, removed: 0, changed: 0 },
                pages: { added: normalized.structure.pages.length, removed: 0, changed: 0 },
                hasChanges: true
            };
        // Write snapshot only when something changed — keeps the git repo clean
        // (no dirty meta.json with a fresh syncedAt and no commit to explain it).
        if (diff.hasChanges) {
            const written = writeSnapshot(writer, normalized, captureResult.raw, existing);
            // Update changelog
            const changelogEntry = generateChangelogEntry(diff, normalized.meta);
            updateChangelog(snapshotsDir, changelogEntry, diff);
            // Commit
            const commitMessage = `sync: ${normalized.meta.syncedAt} lastModified=${normalized.meta.lastModified}`;
            try {
                commitSnapshot(snapshotsDir, commitMessage);
            }
            catch (error) {
                if (error instanceof CommitError) {
                    console.error(`Error: ${error.message}`);
                    process.exit(3);
                }
                throw error;
            }
            // Machine-readable: only files actually rewritten (+ CHANGELOG, updated above)
            const jsonWritten = [...written.written, 'CHANGELOG.md'];
            if (written.preserved.length > 0) {
                console.log(`Preserved (gated): ${written.preserved.join(', ')}`);
            }
            const duration = ((Date.now() - startTime) / 1000).toFixed(2);
            console.log('');
            console.log('=== SYNC COMPLETE ===');
            console.log(`Duration: ${duration}s`);
            console.log(`Requests made: ${client.getRequestCount()}`);
            console.log(`Pages: ${normalized.meta.counts.pages}`);
            console.log(`Styles: ${normalized.meta.counts.styles}`);
            console.log(`Components: ${normalized.meta.counts.components}`);
            console.log(`Component Sets: ${normalized.meta.counts.componentSets}`);
            console.log(`Variables: ${normalized.variables.status} ${normalized.variables.reason ? `(${normalized.variables.reason})` : ''}`);
            console.log(`Content: ${normalized.meta.contentStatus}`);
            console.log(`Changes: yes (committed)`);
            // Get commit hash if a commit was made
            let commitHash = null;
            try {
                commitHash = execSync('git rev-parse HEAD', { cwd: snapshotsDir, encoding: 'utf-8' }).trim();
            }
            catch {
                commitHash = null;
            }
            emitJsonResult({
                command: 'sync',
                ok: true,
                written: jsonWritten,
                preserved: written.preserved,
                commit: commitHash,
                requests: client.getRequestCount(),
                dryRun
            });
        }
        else {
            const duration = ((Date.now() - startTime) / 1000).toFixed(2);
            console.log('');
            console.log('=== SYNC COMPLETE ===');
            console.log(`Duration: ${duration}s`);
            console.log(`Requests made: ${client.getRequestCount()}`);
            console.log(`Pages: ${normalized.meta.counts.pages}`);
            console.log(`Styles: ${normalized.meta.counts.styles}`);
            console.log(`Components: ${normalized.meta.counts.components}`);
            console.log(`Component Sets: ${normalized.meta.counts.componentSets}`);
            console.log(`Variables: ${normalized.variables.status} ${normalized.variables.reason ? `(${normalized.variables.reason})` : ''}`);
            console.log(`Content: ${normalized.meta.contentStatus}`);
            console.log(`Changes: no (snapshot kept as-is)`);
            emitJsonResult({
                command: 'sync',
                ok: true,
                written: [],
                commit: null,
                requests: client.getRequestCount(),
                dryRun
            });
        }
    }
    catch (error) {
        console.error(`Sync failed: ${error.message}`);
        process.exit(1);
    }
}
async function diffCommand(client, fileKey, snapshotsDir) {
    console.log(`Computing diff for file ${fileKey}...`);
    try {
        const existing = loadExistingSnapshot(snapshotsDir);
        if (!existing) {
            console.log('No local snapshot found. Run "sync" first.');
            process.exit(1);
        }
        // Check fileKey mismatch
        if (existing.meta.file_key && existing.meta.file_key !== fileKey) {
            console.error(`Error: snapshot dir contains data for file ${existing.meta.file_key}, refusing to mix with ${fileKey}`);
            process.exit(2);
        }
        // Try to get previous commit from git
        try {
            const prevMeta = JSON.parse(execSync(`git show HEAD~1:meta.json 2>/dev/null || echo "null"`, { cwd: snapshotsDir, encoding: 'utf-8' }));
            if (prevMeta) {
                console.log('Previous snapshot (git HEAD~1):');
                console.log(`  lastModified: ${prevMeta.lastModified}`);
                console.log(`  syncedAt: ${prevMeta.syncedAt}`);
                console.log(`  pages: ${prevMeta.counts.pages}`);
                console.log(`  styles: ${prevMeta.counts.styles}`);
                console.log(`  components: ${prevMeta.counts.components}`);
                console.log(`  componentSets: ${prevMeta.counts.componentSets}`);
            }
        }
        catch {
            console.log('No previous git commit found.');
        }
        console.log('');
        console.log('Current snapshot:');
        console.log(`  lastModified: ${existing.meta.lastModified}`);
        console.log(`  syncedAt: ${existing.meta.syncedAt}`);
        console.log(`  pages: ${existing.meta.counts.pages}`);
        console.log(`  styles: ${existing.meta.counts.styles}`);
        console.log(`  components: ${existing.meta.counts.components}`);
        console.log(`  componentSets: ${existing.meta.counts.componentSets}`);
        emitJsonResult({ command: 'diff', ok: true, dryRun });
    }
    catch (error) {
        console.error(`Diff failed: ${error.message}`);
        process.exit(1);
    }
}
main().catch((error) => {
    console.error(`Unexpected error: ${error.message}`);
    process.exit(1);
});
