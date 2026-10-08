import { type Plugin, tool } from "@opencode-ai/plugin"
import { readFileSync } from "node:fs"
import { homedir } from "node:os"
import { join } from "node:path"

/**
 * INFOMANIAK WRITE BRIDGE PLUGIN (Security Gate 2026-10-07, S-02 — pattern ADR-021)
 *
 * Purpose: mutating Infomaniak API calls (POST/PUT/PATCH/DELETE) are gated by
 * an orchestrator-only tool. The global MCP server (mcp/infomaniak) runs in
 * READ-ONLY mode (client.ts throws WriteBlockedError for mutating methods
 * unless INFOMANIAK_MCP_ALLOW_WRITES=1): every file agent gets broad reads,
 * but writes pass only through this bridge, exactly like the aurora_memory
 * bridge (ADR-021) — "broad reads, writes behind an explicit decision".
 *
 * Boundary model (do not relax):
 * - This tool executes ONLY for the orchestrator agent (`context.agent`,
 *   trustworthy at runtime). Any other agent gets a hard refusal + audit line.
 * - GET is deliberately refused here too: reads belong to the read-only MCP
 *   surface (named tools + generic GET). This bridge must not become a
 *   general-purpose bypass for non-orchestrator agents.
 * - Audit trail: one JSON line per attempt (who/when/what) — no payloads.
 */

const ORCHESTRATOR_AGENTS = new Set(["aurora", "orchestrator"])
const BASE_URL = "https://api.infomaniak.com"
const CALL_TIMEOUT_MS = 30_000
const WRITABLE_METHODS = new Set(["POST", "PUT", "PATCH", "DELETE"])

type InfomaniakResponse = {
  result: "success" | "error" | "asynchronous"
  data?: unknown
  error?: { code?: string; description?: string }
}

/** Same token resolution order as mcp/infomaniak/src/client.ts. */
function resolveToken(): string {
  const envToken = process.env.INFOMANIAK_API_TOKEN
  if (envToken) return envToken
  try {
    const envPath = join(homedir(), ".config", "opencode", ".env")
    const match = readFileSync(envPath, "utf-8").match(/^INFOMANIAK_API_TOKEN\s*=\s*(.+)$/m)
    const token = match?.[1]?.trim().replace(/^["']|["']$/g, "")
    if (token) return token
  } catch {
    // fall through
  }
  throw new Error("infomaniak_api_call: INFOMANIAK_API_TOKEN not resolvable (env or ~/.config/opencode/.env)")
}

export const InfomaniakBridgePlugin: Plugin = async () => {
  return {
    tool: {
      infomaniak_api_call: tool({
        description: `Call any Infomaniak API endpoint with a MUTATING method (orchestrator-only write bridge). Use this for POST/PUT/PATCH/DELETE on api.infomaniak.com — the global infomaniak MCP tools are read-only.

Reads (GET) are refused here: use the global infomaniak_* read tools or the generic GET tool instead.

Discipline:
- Writes are real, irreversible product mutations (DNS, newsletters, VOD, radio, accounts). Prefer a dedicated infomaniak_* tool when one exists; fall back to this bridge only for endpoints without a named tool.
- Confirm destructive intent with the user before delete/bulk operations.
- Capability agents cannot call this tool: route the need through aurora.`,
        args: {
          method: tool.schema
            .enum(["POST", "PUT", "PATCH", "DELETE"])
            .describe("HTTP method — mutating methods only (GET is refused: use the read-only MCP tools)"),
          path: tool.schema
            .string()
            .describe('API path starting with /, e.g. /2/vod/{product_id}/channels/{channel_id}/chapters'),
          body: tool.schema
            .record(tool.schema.string(), tool.schema.unknown())
            .optional()
            .describe("Request body (for POST/PUT/PATCH)"),
          params: tool.schema
            .record(tool.schema.string(), tool.schema.unknown())
            .optional()
            .describe("Query parameters"),
        },
        async execute(args, context) {
          const agent = String(context?.agent ?? "")
          const started = Date.now()
          const audit = (result: "allow" | "deny" | "error", extra?: Record<string, unknown>) => {
            console.log(JSON.stringify({
              plugin: "infomaniak_api_call",
              ts: new Date().toISOString(),
              sessionID: context?.sessionID,
              messageID: context?.messageID,
              agent,
              method: args.method,
              path: args.path,
              result,
              durationMs: Date.now() - started,
              ...extra,
            }))
          }
          if (!ORCHESTRATOR_AGENTS.has(agent)) {
            audit("deny")
            throw new Error(
              `infomaniak_api_call is restricted to the orchestrator (aurora). Current agent: '${agent}'. ` +
                `Infomaniak writes are brokered by aurora: request the action in your task output instead of calling this tool.`
            )
          }
          if (!WRITABLE_METHODS.has(args.method)) {
            audit("deny", { reason: "read-through-bridge" })
            throw new Error(
              `infomaniak_api_call accepts mutating methods only (${[...WRITABLE_METHODS].join("/")}). ` +
                `Use the read-only infomaniak MCP tools for GET.`
            )
          }
          try {
            const url = new URL(`${BASE_URL}${args.path}`)
            if (args.params) {
              for (const [k, v] of Object.entries(args.params)) {
                if (v !== undefined && v !== null) url.searchParams.set(k, String(v))
              }
            }
            const token = resolveToken()
            const controller = new AbortController()
            const timer = setTimeout(() => controller.abort(), CALL_TIMEOUT_MS)
            const response = await fetch(url, {
              method: args.method,
              headers: {
                Authorization: `Bearer ${token}`,
                "Content-Type": "application/json",
              },
              body: args.body && args.method !== "GET" ? JSON.stringify(args.body) : undefined,
              signal: controller.signal,
            })
            clearTimeout(timer)
            const json = (await response.json()) as InfomaniakResponse
            if (json.result === "error") {
              audit("error", { apiCode: json.error?.code })
              throw new Error(`Infomaniak API error [${json.error?.code ?? "unknown"}]: ${json.error?.description ?? "Unknown error"}`)
            }
            audit("allow")
            return JSON.stringify(json, null, 2)
          } catch (err) {
            audit("error", { error: err instanceof Error ? err.message : String(err) })
            throw err
          }
        },
      }),
    },
  }
}
