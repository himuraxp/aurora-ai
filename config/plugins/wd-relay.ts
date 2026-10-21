import { execFile } from "node:child_process"
import { homedir } from "node:os"
import path from "node:path"

// WD-RELAY PLUGIN — Workflow Dashboard, niveau de garantie RELAIS NATIF (J4).
//
// Hook `tool.execute.after` filtré sur `todowrite` : mapping déterministe 1:1
// du payload vers le store progress VIA wd_relay.py (CLI-only — le plugin ne
// touche jamais au JSON du store lui-même).
//
// FORMAT DE HOOK PROUVÉ EN RUNTIME (E2E probe 2026-10-21, opencode v2.1.2) :
// le format V1 (fonction plugin retournant l'objet Hooks, clé
// "tool.execute.after") FIRE ; l'API v2 ctx.tool.hook("execute.after")
// s'enregistre SANS fire (seul execute.before est routé) — le probe a
// renvoyé exactement :
//   input = { tool, sessionID, agent, messageID, id, input, status, result }
//   output = { title, output, metadata } (format npm @opencode-ai/plugin)
// → sessionID PRÉSENT ✓ ; les args du tool (todos) vivent dans `input`.
// Le handler reste DÉFENSIF : il couvre payload.input.todos (runtime local
// v2.1.2 ET paquet npm via args) et skippe proprement sinon.
//
// INVARIANTS (critère E2E) :
// - Aucun crash du relais n'interrompt JAMAIS le workflow : try/catch total
//   sur le handler — jamais throw, jamais rethrow.
// - Sans payload exploitable : pas de topic, pas de donnée fictive (M2) —
//   chaque skip est LOGGUÉ (un relais inerte ne doit pas être muet).
// - Le plugin est un OBSERVATEUR : il ne mute jamais `output` du hook.
//
// Format de chargement : export default de la fonction plugin (format V1
// objet Hooks — seul format qui route execute.after en v2.1.2, voir probe).

type AfterHookInput = {
  tool?: string
  sessionID?: string
  /** Runtime v2.1.2 local : args du tool dans `input`. */
  input?: { todos?: unknown } | null
  /** Paquet @opencode-ai/plugin >= 1.3.3 : args du tool dans `args`. */
  args?: { todos?: unknown } | null
}

type AfterHookOutput = { title?: string; output?: string; metadata?: unknown }

const RELAY_SCRIPT = process.env.WD_RELAY_SCRIPT
  || path.join(homedir(), ".config", "opencode", "skills",
    "workflow-dashboard", "wd_relay.py")

function extractTodos(payload: AfterHookInput): unknown | null {
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

export const WdRelayPlugin = async () => ({
  "tool.execute.after": async (
    payload: AfterHookInput,
    _output: AfterHookOutput,
  ) => {
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
  },
})

export default WdRelayPlugin
