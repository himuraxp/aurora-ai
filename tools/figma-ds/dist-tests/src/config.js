/**
 * Configuration — token loading, paths, defaults
 */
import * as fs from 'node:fs';
// The DS file key is internal metadata — never hard-code it in this public repo
// (audited 2026-10-09). Resolution: FIGMA_DS_FILE_KEY env var, then the
// FIGMA_DS_FILE_KEY line in the local env file, then fail with instructions.
// Fallback name when the /files endpoint is gated by Figma's API quota
// (the dedicated endpoints /styles, /components, /versions stay available).
export const DEFAULT_FILE_NAME = 'Manager Design System';
export const DEFAULT_SNAPSHOTS_DIR = `${process.env.HOME}/dev/infomaniak-ds-snapshots`;
export const DEFAULT_ENV_FILE = `${process.env.HOME}/.config/opencode/.env`;
/**
 * Load token from environment or env file
 */
export function loadConfig() {
    const figmaToken = process.env.FIGMA_TOKEN || loadTokenFromFile();
    const fileKey = process.env.FIGMA_DS_FILE_KEY || loadEnvFileValue('FIGMA_DS_FILE_KEY') || '';
    const snapshotsDir = process.env.FIGMA_DS_SNAPSHOTS_DIR || DEFAULT_SNAPSHOTS_DIR;
    const envFilePath = process.env.OPENCODE_ENV_FILE || DEFAULT_ENV_FILE;
    if (!figmaToken) {
        throw new Error('FIGMA_TOKEN not found. Set environment variable FIGMA_TOKEN or add FIGMA_TOKEN=... to ~/.config/opencode/.env');
    }
    if (!fileKey) {
        throw new Error('FIGMA_DS_FILE_KEY not found. Set environment variable FIGMA_DS_FILE_KEY or add FIGMA_DS_FILE_KEY=... to ~/.config/opencode/.env');
    }
    return { figmaToken, fileKey, snapshotsDir, envFilePath };
}
function loadTokenFromFile() {
    return loadEnvFileValue('FIGMA_TOKEN');
}
function loadEnvFileValue(name) {
    const envFilePath = process.env.OPENCODE_ENV_FILE || DEFAULT_ENV_FILE;
    try {
        if (!fs.existsSync(envFilePath)) {
            return undefined;
        }
        const content = fs.readFileSync(envFilePath, 'utf-8');
        const match = content.match(new RegExp(`^${name}=(.+)$`, 'm'));
        const value = match?.[1]?.trim() ?? '';
        // Strip wrapping quotes — a quoted value would be rejected by Figma as an opaque 403
        const unquoted = value.replace(/^["']|["']$/g, '');
        return unquoted || undefined;
    }
    catch {
        return undefined;
    }
}
