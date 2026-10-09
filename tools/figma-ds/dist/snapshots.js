/**
 * Snapshot writer with git commit support
 */
import * as fs from 'node:fs';
import * as path from 'node:path';
import { execSync, execFileSync } from 'node:child_process';
export function createSnapshotWriter(dir) {
    return { dir };
}
/**
 * Initialize snapshots repository if not exists
 */
export function initSnapshotsRepo(dir) {
    if (!fs.existsSync(dir)) {
        console.log(`Creating snapshots directory: ${dir}`);
        fs.mkdirSync(dir, { recursive: true });
    }
    // Initialize git repo if not already
    if (!fs.existsSync(path.join(dir, '.git'))) {
        console.log('Initializing git repository...');
        execSync('git init', { cwd: dir, stdio: 'inherit' });
        // Create .gitignore
        const gitignore = path.join(dir, '.gitignore');
        if (!fs.existsSync(gitignore)) {
            fs.writeFileSync(gitignore, 'raw/*.json\n!.gitignore\n');
        }
        // Initial commit
        try {
            execSync('git add .gitignore', { cwd: dir, stdio: 'inherit' });
            execSync('git commit -m "Initial commit"', { cwd: dir, stdio: 'inherit' });
        }
        catch {
            // Git commit may fail without user config, that's ok for now
            console.log('Warning: Initial git commit skipped (git user config not configured)');
        }
    }
}
/**
 * Write snapshot files atomically
 * Preserves previous data when new capture is gated but old data exists
 */
export function writeSnapshot(writer, data, raw, previous = null) {
    const { dir } = writer;
    const written = [];
    const preserved = [];
    // Write meta.json (always updated)
    writeAtomic(path.join(dir, 'meta.json'), JSON.stringify(data.meta, null, 2));
    written.push('meta.json');
    // Write structure.json — preserve previous if gated and previous has pages
    const structurePath = path.join(dir, 'structure.json');
    if (data.meta.contentStatus === 'gated' && previous?.structure?.pages && previous.structure.pages.length > 0) {
        console.log('structure: gated — previous data preserved');
        preserved.push('structure.json');
    }
    else {
        writeAtomic(structurePath, JSON.stringify(data.structure, null, 2));
        written.push('structure.json');
    }
    // Write styles.json — preserve previous if gated and previous has styles with resolvedValue
    const stylesPath = path.join(dir, 'styles.json');
    if (data.meta.contentStatus === 'gated' && previous?.styles && previous.styles.length > 0) {
        const hasResolvedValues = previous.styles.some((s) => s.resolvedValue !== undefined);
        if (hasResolvedValues) {
            console.log('styles: gated — previous data preserved');
            preserved.push('styles.json');
        }
        else {
            writeAtomic(stylesPath, JSON.stringify(data.styles, null, 2));
            written.push('styles.json');
        }
    }
    else {
        writeAtomic(stylesPath, JSON.stringify(data.styles, null, 2));
        written.push('styles.json');
    }
    // Write components.json
    writeAtomic(path.join(dir, 'components.json'), JSON.stringify(data.components, null, 2));
    written.push('components.json');
    // Write variables.json — preserve previous if new has no data but previous did.
    // variables.json format is { status, reason, count } (no variables array) —
    // judge by status + count, coherent with what normalizeVariables writes.
    const variablesPath = path.join(dir, 'variables.json');
    if (data.variables.status === 'unavailable' && previous?.variables?.status === 'available' && (previous.variables.count ?? 0) > 0) {
        console.log('variables: unavailable — previous data preserved');
        preserved.push('variables.json');
    }
    else {
        writeAtomic(variablesPath, JSON.stringify(data.variables, null, 2));
        written.push('variables.json');
    }
    // Write raw data
    const rawDir = path.join(dir, 'raw');
    if (!fs.existsSync(rawDir)) {
        fs.mkdirSync(rawDir, { recursive: true });
    }
    // Write raw data — non-timestamped names (last write wins), skip null/undefined payloads
    if (raw.fileData != null) {
        writeAtomic(path.join(rawDir, 'file.json'), JSON.stringify(raw.fileData, null, 2));
    }
    writeAtomic(path.join(rawDir, 'styles-meta.json'), JSON.stringify(raw.stylesMeta, null, 2));
    writeAtomic(path.join(rawDir, 'components-meta.json'), JSON.stringify(raw.componentsMeta, null, 2));
    writeAtomic(path.join(rawDir, 'component-sets-meta.json'), JSON.stringify(raw.componentSetsMeta, null, 2));
    if (raw.nodesBatch && Object.keys(raw.nodesBatch).length > 0) {
        writeAtomic(path.join(rawDir, 'nodes-batch.json'), JSON.stringify(raw.nodesBatch, null, 2));
    }
    return { written, preserved };
}
/**
 * Write file atomically (write to tmp, then rename)
 */
function writeAtomic(filePath, content) {
    const tmpPath = `${filePath}.tmp.${process.pid}`;
    try {
        fs.writeFileSync(tmpPath, content);
        fs.renameSync(tmpPath, filePath);
    }
    catch (error) {
        // Cleanup tmp file on error
        if (fs.existsSync(tmpPath)) {
            fs.unlinkSync(tmpPath);
        }
        throw error;
    }
}
/**
 * Load existing snapshot data if available
 * Throws on corruption (JSON parse error or missing required meta fields)
 */
export function loadExistingSnapshot(dir) {
    const metaPath = path.join(dir, 'meta.json');
    const structurePath = path.join(dir, 'structure.json');
    const stylesPath = path.join(dir, 'styles.json');
    const componentsPath = path.join(dir, 'components.json');
    const variablesPath = path.join(dir, 'variables.json');
    // Check if meta.json exists — if not, no previous snapshot (return null)
    if (!fs.existsSync(metaPath)) {
        return null;
    }
    // Parse meta.json — throw on corruption
    let meta;
    try {
        meta = JSON.parse(fs.readFileSync(metaPath, 'utf-8'));
    }
    catch (error) {
        throw new Error(`snapshot meta.json is corrupted — repair or delete ${dir} and re-sync. Original error: ${error.message}`);
    }
    if (!meta || typeof meta.file_key !== 'string') {
        throw new Error(`snapshot meta.json is corrupted (missing required fields) — repair or delete ${dir} and re-sync`);
    }
    // Parse other files — return null if missing/corrupted (they are optional)
    const parseOptional = (filePath) => {
        if (!fs.existsSync(filePath))
            return null;
        try {
            return JSON.parse(fs.readFileSync(filePath, 'utf-8'));
        }
        catch {
            return null;
        }
    };
    const structure = parseOptional(structurePath);
    const styles = parseOptional(stylesPath);
    const components = parseOptional(componentsPath);
    const variables = parseOptional(variablesPath);
    return { meta, structure, styles, components, variables };
}
/**
 * Update CHANGELOG.md with new entry
 */
export function updateChangelog(dir, entry, diff) {
    const changelogPath = path.join(dir, 'CHANGELOG.md');
    let content = '';
    if (fs.existsSync(changelogPath)) {
        content = fs.readFileSync(changelogPath, 'utf-8');
    }
    else {
        content = '# Figma Design System Snapshots Changelog\n\n';
    }
    // Only add entry if there are changes or it's the first sync
    if (diff.hasChanges || !content.includes('## Sync du')) {
        const newContent = `${entry}\n${content}`;
        writeAtomic(changelogPath, newContent);
    }
}
/**
 * Custom error for git commit failures
 */
export class CommitError extends Error {
    constructor(message) {
        super(message);
        this.name = 'CommitError';
    }
}
/**
 * Error for suspicious data drops
 */
export class DataIntegrityError extends Error {
    constructor(message) {
        super(message);
        this.name = 'DataIntegrityError';
    }
}
/**
 * Validate snapshot data integrity before commit
 * Checks for suspicious drops in counts (>50% decrease from previous snapshot)
 */
export function validateSnapshotIntegrity(current, previous, force = false) {
    if (!previous) {
        // No previous snapshot to compare against
        return;
    }
    const checks = [];
    // Check styles count
    if (previous.styles && current.styles) {
        checks.push({
            name: 'styles',
            prev: previous.styles.length,
            curr: current.styles.length
        });
    }
    // Check components count
    if (previous.components && current.components) {
        checks.push({
            name: 'components',
            prev: previous.components.components?.length || 0,
            curr: current.components.components?.length || 0
        });
    }
    // Check componentSets count
    if (previous.components && current.components) {
        checks.push({
            name: 'componentSets',
            prev: previous.components.componentSets?.length || 0,
            curr: current.components.componentSets?.length || 0
        });
    }
    // Check pages count — exempt in gated mode: pages are EXPECTED to be empty
    // (content endpoints 429), so a full pages list → [] is expected, not a drop.
    if (current.meta?.contentStatus !== 'gated' && previous.structure?.pages && current.structure?.pages) {
        checks.push({
            name: 'pages',
            prev: previous.structure.pages.length,
            curr: current.structure.pages.length
        });
    }
    // Validate each check
    for (const check of checks) {
        if (check.prev > 0) {
            const dropPercent = ((check.prev - check.curr) / check.prev) * 100;
            if (dropPercent > 50) {
                const errorMsg = `suspicious drop in ${check.name}: ${check.prev} → ${check.curr} (${dropPercent.toFixed(1)}% decrease — API response may be partial)`;
                if (!force) {
                    throw new DataIntegrityError(errorMsg);
                }
                else {
                    console.warn(`⚠️ WARNING: ${errorMsg} (--force flag used, proceeding)`);
                }
            }
        }
    }
}
/**
 * Commit snapshot to git
 * Stages only the snapshot files that exist on disk (meta.json, structure.json, styles.json, components.json, variables.json, CHANGELOG.md)
 */
export function commitSnapshot(dir, message) {
    const snapshotFiles = ['meta.json', 'structure.json', 'styles.json', 'components.json', 'variables.json', 'CHANGELOG.md'];
    try {
        // Stage only existing snapshot files (not all untracked files)
        for (const file of snapshotFiles) {
            const filePath = path.join(dir, file);
            if (fs.existsSync(filePath)) {
                execSync(`git add "${file}"`, { cwd: dir, stdio: 'inherit' });
            }
        }
        // execFileSync avoids shell interpolation of the commit message
        execFileSync('git', ['commit', '-m', message], { cwd: dir, stdio: 'inherit' });
        console.log(`Committed: ${message}`);
    }
    catch (error) {
        // If commit fails, throw explicit error so caller can handle it
        throw new CommitError(`git commit failed — repo may be dirty or misconfigured. Fix the issue and re-run. Original error: ${error.message}`);
    }
}
