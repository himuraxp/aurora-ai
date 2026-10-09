/**
 * GitLab API client for the Angular Elements repository.
 *
 * Reads files from a GitLab project — configured via the ANGULAR_ELEMENTS_*
 * variables (see below) — to extract component documentation, API, stories,
 * and package metadata.
 *
 * Also fetches the Storybook `index.json` for the full story catalog.
 *
 * Internal endpoints are deliberately NOT hard-coded in this public
 * repository: every value is resolved from the MCP `env` config / process
 * environment, then from ~/.config/opencode/.env (same fallback as
 * GITLAB_TOKEN):
 *
 *   ANGULAR_ELEMENTS_GITLAB_API      GitLab API base, e.g. https://gitlab.example.com/api/v4
 *   ANGULAR_ELEMENTS_PROJECT_ID      Numeric id of the GitLab project
 *   ANGULAR_ELEMENTS_STORYBOOK_BASE  Base URL exposing the Storybook index.json
 *   ANGULAR_ELEMENTS_REF             Git ref to read (default: master)
 *   GITLAB_TOKEN                     GitLab private token (required)
 */

import fs from "fs";
import path from "path";
import os from "os";

// ─── Config resolution (process.env → ~/.config/opencode/.env) ────────────────

let envFileValues: Record<string, string> | null = null;

function readEnvFile(): Record<string, string> {
  if (envFileValues) return envFileValues;
  const values: Record<string, string> = {};
  try {
    const envPath = path.join(os.homedir(), ".config", "opencode", ".env");
    const content = fs.readFileSync(envPath, "utf-8");
    for (const line of content.split("\n")) {
      const match = line.match(/^\s*([A-Za-z0-9_]+)\s*=\s*(.*?)\s*$/);
      if (match && match[2]) {
        values[match[1]] = match[2].replace(/^["']|["']$/g, "");
      }
    }
  } catch {
    // .env absent or unreadable — process.env only
  }
  envFileValues = values;
  return values;
}

function resolveConfig(name: string, fallback = ""): string {
  return process.env[name] || readEnvFile()[name] || fallback;
}

function requireConfig(name: string): string {
  const value = resolveConfig(name);
  if (!value) {
    throw new Error(
      `${name} is not set. Set it in ~/.config/opencode/.env or pass it via the MCP env config.`,
    );
  }
  return value;
}

function getGitlabApi(): string {
  return requireConfig("ANGULAR_ELEMENTS_GITLAB_API");
}

function getProjectId(): string {
  return requireConfig("ANGULAR_ELEMENTS_PROJECT_ID");
}

function getStorybookBase(): string {
  return requireConfig("ANGULAR_ELEMENTS_STORYBOOK_BASE");
}

function getRef(): string {
  return resolveConfig("ANGULAR_ELEMENTS_REF", "master");
}

function getToken(): string {
  return requireConfig("GITLAB_TOKEN");
}

/** Storybook index.json entry */
export interface StorybookEntry {
  id: string;
  title: string;
  name: string;
  importPath: string;
  type: "docs" | "story";
  tags: string[];
  storiesImports?: string[];
}

export interface StorybookIndex {
  v: number;
  entries: Record<string, StorybookEntry>;
}

// ─── GitLab file reader ────────────────────────────────────────────────────────

/**
 * Fetch a raw file from the GitLab repository.
 * @param filePath - Path within the repo (e.g. "projects/button/src/ik-button/ik-button.component.ts")
 * @returns Raw file content
 */
export async function getGitlabFile(filePath: string): Promise<string> {
  const token = getToken();
  const encodedPath = encodeURIComponent(filePath);
  const url = `${getGitlabApi()}/projects/${getProjectId()}/repository/files/${encodedPath}/raw?ref=${getRef()}`;

  const res = await fetch(url, {
    headers: { "PRIVATE-TOKEN": token },
  });

  if (!res.ok) {
    throw new Error(`GitLab API error ${res.status}: ${res.statusText} for path: ${filePath}`);
  }

  return res.text();
}

/**
 * List the contents of a directory in the repository.
 */
export async function getGitlabTree(dirPath: string, perPage = 100): Promise<GitlabTreeNode[]> {
  const token = getToken();
  const encodedPath = encodeURIComponent(dirPath);
  const url = `${getGitlabApi()}/projects/${getProjectId()}/repository/tree?ref=${getRef()}&path=${encodedPath}&per_page=${perPage}`;

  const res = await fetch(url, {
    headers: { "PRIVATE-TOKEN": token },
  });

  if (!res.ok) {
    throw new Error(`GitLab API error ${res.status}: ${res.statusText} for tree: ${dirPath}`);
  }

  return res.json() as Promise<GitlabTreeNode[]>;
}

export interface GitlabTreeNode {
  id: string;
  name: string;
  type: "tree" | "blob";
  path: string;
  mode: string;
}

// ─── Storybook index ──────────────────────────────────────────────────────────

/** Cached index.json */
let cachedIndex: StorybookIndex | null = null;
let cachedIndexTime = 0;
const INDEX_TTL_MS = 3600_000; // 1 hour

/**
 * Fetch the Storybook index.json containing all stories and docs entries.
 */
export async function getStorybookIndex(): Promise<StorybookIndex> {
  const now = Date.now();
  if (cachedIndex && now - cachedIndexTime < INDEX_TTL_MS) {
    return cachedIndex;
  }

  const url = `${getStorybookBase()}/index.json`;
  const res = await fetch(url);

  if (!res.ok) {
    throw new Error(`Failed to fetch Storybook index.json: ${res.status} ${res.statusText}`);
  }

  cachedIndex = (await res.json()) as StorybookIndex;
  cachedIndexTime = now;
  return cachedIndex;
}

// ─── File cache ───────────────────────────────────────────────────────────────

const fileCache = new Map<string, { content: string; time: number }>();
const treeCache = new Map<string, { data: GitlabTreeNode[]; time: number }>();
const CACHE_TTL_MS = 3600_000; // 1 hour

/**
 * Fetch a GitLab file with caching.
 */
export async function getCachedFile(filePath: string): Promise<string> {
  const now = Date.now();
  const cached = fileCache.get(filePath);
  if (cached && now - cached.time < CACHE_TTL_MS) {
    return cached.content;
  }

  const content = await getGitlabFile(filePath);
  fileCache.set(filePath, { content, time: now });
  return content;
}

/**
 * Fetch a GitLab tree with caching.
 */
export async function getCachedTree(dirPath: string): Promise<GitlabTreeNode[]> {
  const now = Date.now();
  const cached = treeCache.get(dirPath);
  if (cached && now - cached.time < CACHE_TTL_MS) {
    return cached.data;
  }

  const data = await getGitlabTree(dirPath);
  treeCache.set(dirPath, { data, time: now });
  return data;
}
