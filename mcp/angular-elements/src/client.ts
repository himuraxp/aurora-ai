/**
 * GitLab API client for the Angular Elements repository.
 *
 * Reads files from a GitLab project — configured via the ANGULAR_ELEMENTS_*
 * variables (see below) — to extract component documentation, API, stories,
 * and package metadata.
 *
 * Also fetches the Storybook `index.json` for the full story catalog.
 *
 * Endpoints are deliberately NOT hard-coded: every value is resolved from
 * the MCP `env` config / process environment, then from
 * ~/.config/opencode/.env (same fallback as ANGULAR_ELEMENTS_GITLAB_TOKEN):
 *
 *   ANGULAR_ELEMENTS_GITLAB_API       GitLab API base, e.g. https://gitlab.example.com/api/v4
 *   ANGULAR_ELEMENTS_PROJECT_ID       Numeric id of the GitLab project
 *   ANGULAR_ELEMENTS_STORYBOOK_BASE   Base URL exposing the Storybook index.json
 *   ANGULAR_ELEMENTS_ALLOWED_ORIGINS  Comma-separated exact HTTPS origins the MCP may contact
 *   ANGULAR_ELEMENTS_REF              Git ref to read (default: master)
 *   ANGULAR_ELEMENTS_GITLAB_TOKEN     GitLab private token (required — dedicated, scope read_api)
 *   GITLAB_TOKEN                      Deprecated transitional fallback for the token
 *   ANGULAR_ELEMENTS_ENV_FILE         Advanced: override of the .env file path (tests, custom setups)
 *
 * Security policy (enforced at startup, fail-closed — no silent fallback):
 *   F-01  both endpoints must be exact HTTPS origins listed in
 *         ANGULAR_ELEMENTS_ALLOWED_ORIGINS, without embedded credentials;
 *         the GitLab API path must be exactly /api/v4 and the Storybook
 *         base must point at an application sub-path (never the host
 *         root); the project id must be numeric.
 *   F-02  every HTTP request uses redirect: "error" — a 3xx response is an
 *         explicit error, the redirect target is never followed (so the
 *         token can never leak to a redirected host).
 *   F-02+ token-bearing requests additionally assert the target origin
 *         equals the validated GitLab origin (assertGitlabUrl).
 *   F-05  git refs and query parameters are encoded via URLSearchParams;
 *         path segments via encodeURIComponent. Never double-encoded.
 */

import fs from "fs";
import path from "path";
import os from "os";

// ─── Config resolution (process.env → ~/.config/opencode/.env) ────────────────

let envFileCache: { path: string; values: Record<string, string> } | null = null;

/** .env source path — overridable (tests, custom setups) via ANGULAR_ELEMENTS_ENV_FILE. */
function envFilePath(): string {
  return (
    process.env.ANGULAR_ELEMENTS_ENV_FILE ||
    path.join(os.homedir(), ".config", "opencode", ".env")
  );
}

function readEnvFile(): Record<string, string> {
  const envPath = envFilePath();
  if (envFileCache && envFileCache.path === envPath) return envFileCache.values;
  const values: Record<string, string> = {};
  try {
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
  envFileCache = { path: envPath, values };
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

function getProjectId(): string {
  const id = requireConfig("ANGULAR_ELEMENTS_PROJECT_ID");
  if (!/^\d+$/.test(id)) {
    throw new Error(
      `ANGULAR_ELEMENTS_PROJECT_ID must be a numeric GitLab project id, got: "${id}"`,
    );
  }
  return id;
}

function getRef(): string {
  return resolveConfig("ANGULAR_ELEMENTS_REF", "master");
}

const TOKEN_VAR = "ANGULAR_ELEMENTS_GITLAB_TOKEN";
const LEGACY_TOKEN_VAR = "GITLAB_TOKEN";
let legacyTokenWarned = false;

/**
 * Resolve the GitLab token. Nominal path: the dedicated ANGULAR_ELEMENTS_GITLAB_TOKEN
 * (least privilege — scope read_api, not shared with other tooling). GITLAB_TOKEN is
 * accepted as a deprecated transitional fallback: it is the canonical variable of
 * other tooling (e.g. glab) and usually carries a broader scope than read_api.
 */
export function getToken(): string {
  const dedicated = resolveConfig(TOKEN_VAR);
  if (dedicated) return dedicated;
  const legacy = resolveConfig(LEGACY_TOKEN_VAR);
  if (legacy) {
    if (!legacyTokenWarned) {
      legacyTokenWarned = true;
      console.error(
        `[angular-elements-mcp] Warning: ${LEGACY_TOKEN_VAR} is used as a deprecated transitional ` +
          `fallback. Create a dedicated GitLab token (scope read_api, with expiry) and set ` +
          `${TOKEN_VAR} instead — ${LEGACY_TOKEN_VAR} is shared with other tooling and usually has a ` +
          `broader scope. The fallback will be removed in a future release.`,
      );
    }
    return legacy;
  }
  throw new Error(
    `${TOKEN_VAR} is not set. Create a dedicated GitLab token (scope read_api, with expiry) and set it ` +
      `in ~/.config/opencode/.env or pass it via the MCP env config. ` +
      `(${LEGACY_TOKEN_VAR} is still accepted as a deprecated transitional fallback.)`,
  );
}

// ─── Endpoint policy (F-01 — validated at startup, fail-closed) ───────────────

/**
 * Validate a configured endpoint against the startup policy:
 * exact HTTPS origin listed in ANGULAR_ELEMENTS_ALLOWED_ORIGINS,
 * no embedded credentials, and a path within the expected scope.
 * Throws otherwise.
 */
export function validateEndpoint(
  rawUrl: string,
  label: string,
  allowedOrigins: string[],
  opts: { requirePath?: string; forbidRootPath?: boolean } = {},
): URL {
  let url: URL;
  try {
    url = new URL(rawUrl);
  } catch {
    throw new Error(`${label} is not a valid URL: "${rawUrl}"`);
  }
  if (url.protocol !== "https:") {
    throw new Error(`${label} must use HTTPS, got "${url.protocol}//${url.host}"`);
  }
  if (url.username || url.password) {
    throw new Error(`${label} must not embed credentials (user:password)`);
  }
  if (!allowedOrigins.includes(url.origin)) {
    throw new Error(
      `${label} origin "${url.origin}" is not in ANGULAR_ELEMENTS_ALLOWED_ORIGINS ` +
        `(allowed: ${allowedOrigins.join(", ")})`,
    );
  }
  const pathname = url.pathname.replace(/\/+$/, "");
  if (opts.requirePath && pathname !== opts.requirePath) {
    throw new Error(
      `${label} path must be exactly "${opts.requirePath}" (GitLab API contract), got "${pathname}"`,
    );
  }
  if (opts.forbidRootPath && pathname === "") {
    throw new Error(
      `${label} must point at the application sub-path (e.g. https://host/front/angular-elements), not the host root`,
    );
  }
  return url;
}

/** Parse the allowlist — required, explicit, no default. */
export function getAllowedOrigins(): string[] {
  const raw = requireConfig("ANGULAR_ELEMENTS_ALLOWED_ORIGINS");
  const origins = raw
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);
  const invalid = origins.filter((o) => {
    try {
      return new URL(o).origin !== o || new URL(o).protocol !== "https:";
    } catch {
      return true;
    }
  });
  if (origins.length === 0 || invalid.length > 0) {
    throw new Error(
      `ANGULAR_ELEMENTS_ALLOWED_ORIGINS must be a comma-separated list of exact HTTPS origins ` +
        `(e.g. "https://gitlab.example.com,https://pages.example.com"). Got: "${raw}"`,
    );
  }
  return origins;
}

// Validated once per process — first call happens at startup.
let gitlabBase: URL | null = null;
let storybookBase: URL | null = null;

function getGitlabBase(): URL {
  if (!gitlabBase) {
    gitlabBase = validateEndpoint(
      requireConfig("ANGULAR_ELEMENTS_GITLAB_API"),
      "ANGULAR_ELEMENTS_GITLAB_API",
      getAllowedOrigins(),
      { requirePath: "/api/v4" },
    );
  }
  return gitlabBase;
}

function getStorybookBase(): URL {
  if (!storybookBase) {
    storybookBase = validateEndpoint(
      requireConfig("ANGULAR_ELEMENTS_STORYBOOK_BASE"),
      "ANGULAR_ELEMENTS_STORYBOOK_BASE",
      getAllowedOrigins(),
      { forbidRootPath: true },
    );
  }
  return storybookBase;
}

/**
 * Validate the full startup configuration. Called once by the server entry
 * point BEFORE any tool is registered or used — a misconfigured endpoint
 * must never reach the network layer.
 */
export function validateStartupConfig(): void {
  getAllowedOrigins();
  getGitlabBase();
  getStorybookBase();
  getProjectId();
  getToken();
}

/** Join the validated base path with a relative API path (no URL surprises). */
function withBasePath(base: URL, relative: string): URL {
  const basePath = base.pathname.replace(/\/+$/, "");
  return new URL(`${base.origin}${basePath}${relative}`);
}

// ─── URL builders (F-05 — encoded via URLSearchParams, never hand-built) ──────

/** Build the raw-file URL for a repo path. `filePath` is a path segment (GitLab API contract: "/" encoded as %2F). */
export function buildGitlabFileUrl(filePath: string): URL {
  const url = withBasePath(
    getGitlabBase(),
    `/projects/${getProjectId()}/repository/files/${encodeURIComponent(filePath)}/raw`,
  );
  url.searchParams.set("ref", getRef());
  return url;
}

/** Build the tree URL for a directory path. Query values encoded once by URLSearchParams. */
export function buildGitlabTreeUrl(dirPath: string, perPage: number): URL {
  const url = withBasePath(getGitlabBase(), `/projects/${getProjectId()}/repository/tree`);
  url.searchParams.set("ref", getRef());
  url.searchParams.set("path", dirPath);
  url.searchParams.set("per_page", String(perPage));
  return url;
}

/** Build the Storybook index.json URL (path scope = the configured base itself). */
export function buildStorybookIndexUrl(): URL {
  return withBasePath(getStorybookBase(), "/index.json");
}

// ─── Shared fetch (F-02 — redirect: "error") ──────────────────────────────────

/**
 * Defense in depth: assert an URL belongs to the validated GitLab base
 * origin before it can be called with the token. The invariant is already
 * structural (all token URLs come from buildGitlabFileUrl/buildGitlabTreeUrl);
 * this guard makes it explicit and testable.
 */
export function assertGitlabUrl(url: URL): void {
  if (url.origin !== getGitlabBase().origin) {
    throw new Error(
      `Refusing to send the GitLab token to a non-GitLab origin: "${url.origin}" (expected "${getGitlabBase().origin}")`,
    );
  }
}

/** GET with the GitLab token; a 3xx response is an explicit error, never followed. */
async function fetchWithToken(url: URL): Promise<Response> {
  assertGitlabUrl(url);
  return fetch(url, {
    headers: { "PRIVATE-TOKEN": getToken() },
    redirect: "error",
  });
}

/** GET without token (public/internal storybook assets); redirects refused as well. */
async function fetchPublic(url: URL): Promise<Response> {
  return fetch(url, { redirect: "error" });
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
  const url = buildGitlabFileUrl(filePath);
  const res = await fetchWithToken(url);

  if (!res.ok) {
    throw new Error(`GitLab API error ${res.status}: ${res.statusText} for path: ${filePath}`);
  }

  return res.text();
}

/**
 * List the contents of a directory in the repository.
 */
export async function getGitlabTree(dirPath: string, perPage = 100): Promise<GitlabTreeNode[]> {
  const url = buildGitlabTreeUrl(dirPath, perPage);
  const res = await fetchWithToken(url);

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

  const res = await fetchPublic(buildStorybookIndexUrl());

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
