/**
 * CHATGPT AUTOCOWORK PLUGIN
 *
 * Purpose: when the user sends a message containing a ChatGPT conversation
 * link (chatgpt.com/c/…, chatgpt.com/share/…, chatgpt.com/g/<gid>/c/…,
 * chat.openai.com/c/…), append a deterministic instruction telling the model
 * to invoke the `ai-cowork` skill with that URL — so the user never has to
 * repeat "fais ça en cowork avec ChatGPT".
 *
 * Boundary model:
 * - The hook NEVER rewrites user text: it only APPENDS a `<system-reminder>`
 *   block after the original message (live prompt; the persisted session
 *   transcript may include the reminder — accepted for transparency).
 * - Root-session gate (best effort): when ctx.session.get is available, the
 *   reminder is only injected when the session has NO parentID — subagent
 *   delegation briefs (task tool child sessions) are never touched. Any
 *   lookup failure falls back to injecting (fail-open: the main use case
 *   must never be blocked by a contract drift).
 * - Idempotent: a text already carrying the marker is never re-annotated
 *   (hook re-fire on retry / double registration).
 * - agents/aurora.md (« Règles strictes ») is the semantic source of truth;
 *   this plugin only adds deterministic enforcement. An explicit user
 *   refusal ("pas de cowork cette fois") always takes precedence.
 * - Graceful degradation: no `session` hook namespace → plugin disabled
 *   silently. Handler errors swallowed: this plugin can never break prompt
 *   submission.
 *
 * Runtime contract (verified against the opencode v2.1.4 bundle):
 *   ctx.session.hook("prompt", (event) => …) with event =
 *   { sessionID, messageID, prompt: { text, files?, agents?, skills? },
 *     metadata, delivery } — the runtime reads event.prompt back after the
 *   hook (mutation-style, same engine as tool.execute.before). The single
 *   `.trigger("session","prompt")` site also serves task-tool child sessions
 *   (p.create({parentID}) then p.prompt) — hence the root-session gate.
 *
 * OpenCode v2 plugin format: default export { id, setup }.
 * Reception suite: scripts/test-chatgpt-autocowork.mjs (wired into
 * scripts/health-check.sh, pattern test-product-authority.mjs).
 */

type V2SessionPromptEvent = {
  sessionID?: string
  messageID?: string
  prompt?: {
    text?: string
    files?: unknown
    agents?: unknown
    skills?: unknown
  }
  metadata?: unknown
  delivery?: unknown
}

type V2SessionHooks = {
  hook: (
    name: "prompt",
    handler: (event: V2SessionPromptEvent) => Promise<void> | void,
  ) => Promise<{ dispose: () => void } | undefined>
  /** Optional in the plugin ctx — used best-effort for the root-session gate. */
  get?: (args: { sessionID: string }) => Promise<unknown>
}

type V2SetupContext = {
  session?: V2SessionHooks
}

/** ChatGPT conversation links: /c/<id>, /g/<gid>/c/<id> (projects),
 * /share/<id> (public snapshot), legacy chat.openai.com/c/<id>.
 * The lookbehind rejects lookalike hosts (mychatgpt.com, evil-chatgpt.com).
 * All variable segments use the strict [A-Za-z0-9_-] charset (security
 * review F-01): no whitespace, no < > " ' / etc. can cross into the
 * appended reminder. */
export const CHATGPT_CONVERSATION_URL =
  /(?<![\w-])(?:chatgpt\.com|chat\.openai\.com)\/(?:c|share|g\/[A-Za-z0-9_-]+\/c)\/[A-Za-z0-9_-]+/i

export const REMINDER_MARKER = "<system-reminder>chatgpt-autocowork"

export function reminderFor(url: string): string {
  return (
    "\n\n" +
    REMINDER_MARKER +
    " — a ChatGPT conversation link was detected in this message (" +
    url +
    "). Standing user instruction: hand this conversation off to the `ai-cowork` loop — do NOT answer the message content directly and do NOT ask for confirmation. " +
    "Invoke the `ai-cowork` skill now (Skill tool, id \"ai-cowork\"), using this URL as the « URL conversation ChatGPT » parameter (initial context + loop thread), then follow that skill's phases. " +
    "If the message also contains an explicit objective, use it as the cowork goal. " +
    "If the user is merely asking a question ABOUT the link (not handing off work), answer normally instead; an explicit refusal of cowork always takes precedence." +
    "</system-reminder>"
  )
}

/** Pure decision: returns the annotated prompt text, or null when nothing
 * should be appended (no link, already annotated, empty text). */
export function buildPromptPatch(text: string): string | null {
  if (typeof text !== "string" || text.length === 0) return null
  if (text.includes(REMINDER_MARKER)) return null
  const matched = text.match(CHATGPT_CONVERSATION_URL)
  if (!matched) return null
  return text + reminderFor(matched[0])
}

/** Warn-once flag: the fail-open path surfaces a single contract-drift
 * notice (security review F-02 — observability without spam). */
let gateFailureWarned = false

/** Best-effort root-session gate: subagent sessions (task tool) carry a
 * parentID and must never receive the reminder. Fail-open by design. */
async function isRootSession(
  session: V2SessionHooks | undefined,
  sessionID: string | undefined,
): Promise<boolean> {
  if (!sessionID || typeof session?.get !== "function") return true
  try {
    const res = (await session.get({ sessionID })) as
      | { info?: { parentID?: string | null }; parentID?: string | null }
      | undefined
    const info = res?.info ?? res
    return info?.parentID == null
  } catch {
    if (!gateFailureWarned) {
      gateFailureWarned = true
      console.warn(
        "[chatgpt-autocowork] root-session lookup failed — fail-open (reminder injected)",
      )
    }
    return true
  }
}

const chatgptAutocoworkPlugin = {
  id: "chatgpt-autocowork",
  setup: async (ctx: V2SetupContext) => {
    if (!ctx?.session || typeof ctx.session.hook !== "function") {
      console.warn(
        "[chatgpt-autocowork] session hook namespace unavailable — plugin disabled",
      )
      return
    }

    const registration = await ctx.session.hook("prompt", async (event) => {
      try {
        const prompt = event?.prompt
        const text = prompt?.text
        if (!prompt || typeof text !== "string" || text.length === 0) return
        const patched = buildPromptPatch(text)
        if (patched === null) return
        if (!(await isRootSession(ctx.session, event.sessionID))) return
        prompt.text = patched
      } catch {
        // Never let this plugin break prompt submission.
      }
    })
    return () => registration?.dispose()
  },
}

export default chatgptAutocoworkPlugin
