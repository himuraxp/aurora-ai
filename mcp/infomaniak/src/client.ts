/**
 * Shared HTTP client for the Infomaniak API.
 *
 * Handles:
 * - Bearer token authentication
 * - Rate limiting (60 req/min — queues requests if needed)
 * - Pagination (page/per_page, offset/limit)
 * - Error parsing (result: success | error)
 * - Multipart/form-data upload (file upload via FormData)
 * - Base URL: https://api.infomaniak.com
 */

import { readFileSync } from "fs";
import { join } from "path";
import { homedir } from "os";

const BASE_URL = "https://api.infomaniak.com";
const RATE_LIMIT_PER_MIN = 60;
const RATE_WINDOW_MS = 60_000;

/** Infomaniak API error response. */
export interface InfomaniakError {
  code: string;
  description: string;
  context?: Record<string, unknown>;
  errors?: Array<{
    code: string;
    description: string;
    context?: Record<string, unknown>;
  }>;
}

/** Infomaniak API success response. */
export interface InfomaniakResponse<T = unknown> {
  result: "success" | "error" | "asynchronous";
  data?: T;
  error?: InfomaniakError;
  total?: number;
  page?: number;
  pages?: number;
  items_per_page?: number;
}

/** Parameters for a generic API call. */
export interface ApiCallParams {
  method: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  path: string;
  body?: Record<string, unknown>;
  params?: Record<string, string | number | boolean | undefined>;
}

// ─── Rate limiter ─────────────────────────────────────────────────────────────

let requestTimestamps: number[] = [];

function waitForRateLimit(): void {
  const now = Date.now();
  // Remove timestamps older than the rate window
  requestTimestamps = requestTimestamps.filter(
    (ts) => now - ts < RATE_WINDOW_MS,
  );
  if (requestTimestamps.length >= RATE_LIMIT_PER_MIN) {
    const oldest = requestTimestamps[0];
    const waitMs = RATE_WINDOW_MS - (now - oldest) + 10; // +10ms buffer
    if (waitMs > 0) {
      // Sleep synchronously — MCP tools can block
      Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, waitMs);
    }
    requestTimestamps = requestTimestamps.filter(
      (ts) => Date.now() - ts < RATE_WINDOW_MS,
    );
  }
  requestTimestamps.push(Date.now());
}

// ─── Core request function ────────────────────────────────────────────────────

// ─── Token resolution ─────────────────────────────────────────────────────────

/**
 * Resolve the Infomaniak API token.
 *
 * Resolution order:
 * 1. process.env.INFOMANIAK_API_TOKEN (injected by OpenCode via `env` config)
 * 2. ~/.config/opencode/.env file (fallback — robust across installations)
 *
 * This fallback ensures the MCP server works even when the host process does not
 * receive the environment variable from OpenCode's `{env:...}` substitution.
 */
function getToken(): string {
  // 1. Direct environment variable (injected by OpenCode via `env` config)
  const envToken = process.env.INFOMANIAK_API_TOKEN;
  if (envToken) {
    return envToken;
  }

  // 2. Fallback: read from ~/.config/opencode/.env
  //    Uses ESM imports (not require) — critical for "type": "module" packages.
  try {
    const envPath = join(homedir(), ".config", "opencode", ".env");
    const envContent = readFileSync(envPath, "utf-8");

    const match = envContent.match(/^INFOMANIAK_API_TOKEN\s*=\s*(.+)$/m);
    if (match) {
      const token = match[1].trim().replace(/^["']|["']$/g, "");
      if (token) {
        return token;
      }
    }
  } catch {
    // File not found or unreadable — fall through to error
  }

  throw new Error(
    "INFOMANIAK_API_TOKEN environment variable is not set. Get a token at https://manager.infomaniak.com/v3/ng/accounts/token/list",
  );
}

function buildUrl(
  path: string,
  params?: Record<string, string | number | boolean | undefined>,
): string {
  const url = new URL(`${BASE_URL}${path}`);
  if (params) {
    for (const [key, value] of Object.entries(params)) {
      if (value !== undefined && value !== null) {
        url.searchParams.set(key, String(value));
      }
    }
  }
  return url.toString();
}

// ─── Write gate (Security Gate 2026-10-07, S-02) ─────────────────────────────
//
// The MCP server is registered GLOBALLY in OpenCode, and client-side filtering
// (permission denies, tool hiding) is empirically inoperative for file agents
// (ADR-021). Therefore the write boundary must live HERE, at the single choke
// point every tool handler goes through: the HTTP client itself.
//
// Policy: mutating methods (POST/PUT/PATCH/DELETE) are refused unless the
// operator explicitly opts in with INFOMANIAK_MCP_ALLOW_WRITES=1. The
// orchestrator performs writes through the `infomaniak_api_call` bridge plugin
// (config/plugins/infomaniak-bridge.ts), which is orchestrator-scoped.
//
// This mirrors the aurora-memory bridge model (ADR-021): broad reads,
// writes behind an explicit decision. The gate keys on the real HTTP method,
// not on tool names, so no naming convention can bypass it.

export class WriteBlockedError extends Error {
  constructor(method: string, path: string) {
    super(
      `Write blocked (read-only MCP mode): ${method} ${path}. ` +
        `Mutating calls are gated by INFOMANIAK_MCP_ALLOW_WRITES. ` +
        `The orchestrator must use the infomaniak_api_call bridge tool instead.`,
    );
    this.name = "WriteBlockedError";
  }
}

function isMutatingMethod(method: string): boolean {
  return method !== "GET";
}

function assertWriteAllowed(method: string, path: string): void {
  if (!isMutatingMethod(method)) {
    return;
  }
  if (process.env.INFOMANIAK_MCP_ALLOW_WRITES === "1") {
    return;
  }
  throw new WriteBlockedError(method, path);
}

export async function apiCall<T = unknown>(
  params: ApiCallParams,
): Promise<InfomaniakResponse<T>> {
  assertWriteAllowed(params.method, params.path);
  waitForRateLimit();

  const url = buildUrl(params.path, params.params);
  const token = getToken();

  const fetchOptions: RequestInit = {
    method: params.method,
    headers: {
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json",
    },
  };

  if (params.body && params.method !== "GET") {
    fetchOptions.body = JSON.stringify(params.body);
  }

  const response = await fetch(url, fetchOptions);
  const json = (await response.json()) as InfomaniakResponse<T>;

  if (json.result === "error") {
    const err = json.error;
    const desc = err?.description || "Unknown error";
    const code = err?.code || "unknown";
    throw new Error(`Infomaniak API error [${code}]: ${desc}`);
  }

  return json;
}

// ─── Pagination helpers ──────────────────────────────────────────────────────

export interface PaginatedParams {
  page?: number;
  per_page?: number;
  limit?: number;
  skip?: number;
  order_by?: string;
  order?: "asc" | "desc";
}

export async function paginate<T>(
  path: string,
  params: PaginatedParams = {},
): Promise<{
  data: T[];
  total: number;
  page: number;
  pages: number;
}> {
  const response = await apiCall<T[]>({
    method: "GET",
    path,
    params: params as Record<string, string | number | boolean | undefined>,
  });

  return {
    data: response.data || [],
    total: response.total ?? 0,
    page: response.page ?? 1,
    pages: response.pages ?? 1,
  };
}

// ─── Multipart upload ────────────────────────────────────────────────────────

/** Parameters for a multipart/form-data API call (file upload). */
export interface MultipartCallParams {
  method: "POST" | "PUT";
  path: string;
  /** Path to the local file to upload. */
  filePath: string;
  /** Optional fields to include alongside the file (folder, name, etc.). */
  fields?: Record<string, string>;
  /** Optional content-type override for the file (default: auto-detect). */
  contentType?: string;
}

/**
 * Make a multipart/form-data API call for file uploads.
 *
 * Uses Node's Blob (Node 18+) + FormData to construct the multipart body.
 * Does NOT set Content-Type manually — the runtime sets it with the correct
 * boundary automatically.
 *
 * @example
 * await apiCallMultipart({
 *   method: "POST",
 *   path: "/1/vod/channel/14733/upload",
 *   filePath: "/tmp/upload.mp3",
 *   fields: { folder: "1jijk03un7ebc", name: "01 The Prelude.mp3" },
 * });
 */
export async function apiCallMultipart<T = unknown>(
  params: MultipartCallParams,
): Promise<InfomaniakResponse<T>> {
  assertWriteAllowed(params.method, params.path);
  waitForRateLimit();

  const url = `${BASE_URL}${params.path}`;
  const token = getToken();

  // Read file into a Blob (Node 18+: Buffer is a valid BlobPart)
  const fileBuffer = readFileSync(params.filePath);
  const blob = new Blob([fileBuffer], {
    type: params.contentType || "application/octet-stream",
  });

  const formData = new FormData();
  formData.append("file", blob);

  if (params.fields) {
    for (const [key, value] of Object.entries(params.fields)) {
      formData.append(key, value);
    }
  }

  const fetchOptions: RequestInit = {
    method: params.method,
    headers: {
      Authorization: `Bearer ${token}`,
      // Do NOT set Content-Type — FormData sets the multipart boundary
    },
    body: formData,
  };

  const response = await fetch(url, fetchOptions);
  const json = (await response.json()) as InfomaniakResponse<T>;

  if (json.result === "error") {
    const err = json.error;
    const desc = err?.description || "Unknown error";
    const code = err?.code || "unknown";
    throw new Error(`Infomaniak API error [${code}]: ${desc}`);
  }

  return json;
}
