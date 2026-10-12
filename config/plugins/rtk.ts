import { execFile } from "node:child_process"

// RTK OpenCode plugin — rewrites commands to use rtk for token savings.
// Requires: rtk >= 0.23.0 in PATH.
//
// This is a thin delegating plugin: all rewrite logic lives in `rtk rewrite`,
// which is the single source of truth (src/discover/registry.rs).
// To add or change rewrite rules, edit the Rust registry — not this file.
//
// OpenCode v2 plugin format: default export { id, setup }.
// The bash-command rewrite hooks into ctx.tool.hook("execute.before").

/** Minimal structural types for the OpenCode v2 plugin context (types are
 * stripped by the runtime; they document the contract used here). */
type V2ToolHookInput = {
  tool: string
  /** Tool arguments object — reassignment is read back by the runtime. */
  input?: Record<string, unknown> | null
}

type V2ToolHooks = {
  hook: (
    name: "execute.before",
    handler: (input: V2ToolHookInput) => Promise<void> | void,
  ) => Promise<{ dispose: () => void }>
}

type V2SetupContext = {
  tool: V2ToolHooks
}

/** v2.0.27 tool ids seen for shell execution (bash legacy, shell current). */
const REWRITABLE_TOOLS = new Set(["bash", "shell"])

function exec(command: string, args: string[]): Promise<string> {
  return new Promise((resolve, reject) => {
    execFile(command, args, { encoding: "utf-8", timeout: 5_000 }, (err, stdout) => {
      if (err) reject(err)
      else resolve(String(stdout))
    })
  })
}

const rtkPlugin = {
  id: "rtk",
  setup: async (ctx: V2SetupContext) => {
    try {
      await exec("which", ["rtk"])
    } catch {
      console.warn("[rtk] rtk binary not found in PATH — plugin disabled")
      return
    }

    const registration = await ctx.tool.hook("execute.before", async (hookInput) => {
      const tool = String(hookInput?.tool ?? "").toLowerCase()
      if (!REWRITABLE_TOOLS.has(tool)) return
      const args = hookInput?.input
      if (!args || typeof args !== "object") return

      const command = args.command
      if (typeof command !== "string" || !command) return

      try {
        const stdout = await exec("rtk", ["rewrite", command])
        const rewritten = stdout.trim()
        if (rewritten && rewritten !== command) {
          hookInput.input = { ...args, command: rewritten }
        }
      } catch {
        // rtk rewrite failed — pass through unchanged
      }
    })
    return () => registration?.dispose()
  },
}

export default rtkPlugin
