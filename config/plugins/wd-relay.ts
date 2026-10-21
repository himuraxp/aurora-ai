import { execFile } from "node:child_process"
import { homedir } from "node:os"
import path from "node:path"

// WD-RELAY PLUGIN — Workflow Dashboard, niveau de garantie RELAIS NATIF (J4).
//
// Hook `tool.execute.after` filtré sur `todowrite` : mapping déterministe 1:1
// du payload vers le store progress VIA wd_relay.py (CLI-only — le plugin ne
// touche jamais au JSON du store lui-même).
//
// Signature officielle (@opencode-ai/plugin >= 1.3.3, vérifiée 2026-10-21) :
//   "tool.execute.after"(input: { tool, sessionID, callID, args },
//                        output: { title, output, metadata }) => Promise
// Le runtime local v2 (pattern rtk.ts, ctx.tool.hook) passe un objet mixte —
// le handler est DÉFENSIF : il couvre `input.input.todos` (runtime v2) ET
// `input.args.todos` (paquet npm 1.3.3) et skippe proprement sinon.
//
// INVARIANTS (critère E2E) :
// - Aucun crash du relais n'interrompt JAMAIS le workflow : try/catch total
//   (handler ET setup), jamais throw, jamais rethrow.
// - Sans payload exploitable : pas de topic, pas de donnée fictive (M2) —
//   chaque skip est LOGGUÉ (un relais inerte ne doit pas être muet).
// - Le plugin est un OBSERVATEUR : il ne mute jamais `output` du hook.
//
// OpenCode v2 plugin format: default export { id, setup }.

type V2AfterHookPayload = {
  tool?: string
  sessionID?: string
  callID?: string
  /** Runtime v2 local (pattern rtk.ts) : args du tool dans `input`. */
  input?: { todos?: unknown } | null
  /** Paquet @opencode-ai/plugin >= 1.3.3 : args du tool dans `args`. */
  args?: { todos?: unknown } | null
}

type V2ToolHooks = {
  hook: (
    name: "execute.after",
    handler: (payload: V2AfterHookPayload) => Promise<void> | void,
  ) => Promise<{ dispose: () => void }>
}

type V2SetupContext = { tool: V2ToolHooks }

const RELAY_SCRIPT = process.env.WD_RELAY_SCRIPT
  || path.join(homedir(), ".config", "opencode", "skills",
    "workflow-dashboard", "wd_relay.py")

function extractTodos(payload: V2AfterHookPayload): unknown | null {
  for (const source of [payload.input, payload.args]) {
    if (source && Array.isArray(source.todos)) return source.todos
  }
  return null
}

function publish(sessionID: string, todos: unknown[]): Promise<void> {
  return new Promise((resolve) => {
    // payload par STDIN (review J4 F4 : JSON.stringify en argv unique
    // échoue silencieusement en E2BIG au-delà de MAX_ARG_STRLEN) ;
    // wd_relay.py `reconcile <sessionID> -` lit le JSON sur stdin.
    const child = execFile(
      "python3",
      [RELAY_SCRIPT, "reconcile", sessionID, "-"],
      { timeout: 5000 },
      (error, stdout) => {
        // best-effort : un échec du relais n'est jamais une erreur de workflow
        if (error) {
          console.error(`[wd-relay] publish skipped: ${error.message}`)
        } else {
          try {
            console.log(`[wd-relay] ${String(stdout).trim().split("\n").at(-1)}`)
          } catch {
            /* log best-effort */
          }
        }
        resolve()
      },
    )
    child.stdin?.end(JSON.stringify(todos))
  })
}

export const WdRelayPlugin = async (ctx: V2SetupContext) => {
  let registration: { dispose: () => void } | null = null
  try {
    // review J4 F2 : le setup est DANS le try/catch total — un hook name
    // refusé par le runtime désactive le relais sans casser le chargement
    registration = await ctx.tool.hook("execute.after", async (payload) => {
      try {
        if (!payload) return
        if (String(payload.tool ?? "").toLowerCase() !== "todowrite") return
        const todos = extractTodos(payload)
        if (!Array.isArray(todos)) {
          console.error(
            "[wd-relay] skip: no todos array in payload (shapes input/args)",
          )
          return
        }
        if (!payload.sessionID) {
          console.error("[wd-relay] skip: no sessionID in hook payload")
          return // sans session : topicId non dérivable — jamais de fiction
        }
        await publish(payload.sessionID, todos)
      } catch (error) {
        // INVARIANT : le relais ne casse jamais le workflow (critère E2E)
        console.error(
          `[wd-relay] ignored: ${error instanceof Error ? error.message : error}`,
        )
      }
    })
  } catch (error) {
    console.error(
      "[wd-relay] hook registration failed — relay disabled:",
      error instanceof Error ? error.message : error,
    )
  }
  return () => registration?.dispose()
}

export default { id: "wd-relay", setup: WdRelayPlugin }
