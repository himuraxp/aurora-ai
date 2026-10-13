import { createHash } from "node:crypto"
import { existsSync, readFileSync, appendFileSync, writeFileSync, mkdirSync, renameSync } from "node:fs"
import { homedir } from "node:os"
import { join } from "node:path"

/**
 * PRODUCT AUTHORITY CONTROLLER PLUGIN (Standard product-authority.md v1.1 — Étape 3)
 *
 * Deterministic, model-free enforcement of delegated product authority.
 * Source of truth: standards/product-authority.md (frozen v1.1). Any divergence
 * between this implementation and the standard is an implementation bug.
 *
 * Boundary model (pattern ADR-021, do not relax):
 * - All three tools execute ONLY for the orchestrator agent (`context.agent`,
 *   trustworthy at runtime). Any other agent gets a hard refusal + audit line.
 * - The controller owns: registry (~/.config/opencode/aurora-product-authority.json),
 *   append-only journal (…-journal.jsonl), attestations. No agent text can mint
 *   a `DELEGATED_APPROVED` status — only this controller emits attestations.
 * - `DELEGATED_APPROVED` never authorizes execution: it funds a content decision
 *   only (standard §2, invariant E/A).
 *
 * Testability: the pure logic is exported (`createProductAuthorityController`,
 * `canonJson`) and exercised by scripts/test-product-authority.mjs via Node 24
 * native type-stripping. The default export is the OpenCode v2 plugin wiring.
 *
 * Fail-closed everywhere: unknown state, malformed input, unverifiable context
 * never produce an authorization (standard §9, §11).
 */

// ---------------------------------------------------------------------------
// Types (TS strippable — no enums, no namespaces, no param properties)
// ---------------------------------------------------------------------------

type AuthorityLevel = "consultative" | "limited" | "extended"
type DelegableClass = "C1" | "C2" | "C3" | "C4" | "C5a" | "C6"
type AnyClass = DelegableClass | "C5b" | "F"

interface Impact {
  touches_existing_acceptance_criteria: boolean
  adds_removes_user_facing_behavior: boolean
  introduces_commitment: boolean
}

interface DecisionProposal {
  decision_id: string
  title: string
  final_text: string
  classification: { class: string; rationale: string }
  impact: Impact
  constraints: string[]
  project_key: string
  classified_at: string
}

interface Reclassification {
  decision_id: string
  reviewer_class: string
  reviewer_impact: Impact
  notes?: string
}

interface PolicyEnvelope {
  /** Reference only — the controller re-reads the registry itself and verifies hashes. */
  policy_id: string
}

interface AuthorizeContext {
  /**
   * Execution project key, resolved by the orchestrator from git (NOT from the
   * proposal — the proposal's project_key is forgeable agent text). The
   * controller cross-checks: registry identity.origin === context.project_key
   * === proposal.project_key (§4.3 anti-spoofing, never fuzzy).
   */
  project_key: string
  meeting_id?: string
  reviewer?: Reclassification
  /** Declared by Aurora when the classification itself is ambiguous (§5, §11) — never resolved mechanically. */
  ambiguous_classification?: boolean
  /** Declared by Aurora when the decision revises an already-ratified product decision (§5 last rule). */
  revising_ratified_decision?: boolean
}

interface Attestation {
  issuer: "product-authority-controller"
  authorization_id: string
  policy_id: string
  policy_hash: string
  decision_digest: string
  authorized_at: string
}

type AuthorizationResult =
  | { status: "DELEGATED_APPROVED"; attestation: Attestation; retained_class: DelegableClass; effective_impact: Impact }
  | { status: "HUMAN_REQUIRED"; reason: string; detail?: string; downgrade_recommended?: boolean }
  | { status: "PROPOSE_ONLY"; reason: string }
  | { status: "REFUSED"; reason: string; detail?: string }

interface DecisionUsageContext {
  project_key: string
  task_scope: string
  applicable_constraints: string[]
  known_conflicts: string[]
}

type VerificationResult =
  | { valid: true; applicable: true }
  | { valid: true; applicable: false; reason: string }
  | { valid: false; reason: "unknown_authorization" | "digest_mismatch" | "policy_expired" | "policy_revoked" }
  | "REQUIRES_REVALIDATION"

interface ProjectPolicy {
  type: string
  authority: string
  level: AuthorityLevel
  expires_at: string
  deferred_until?: string
  created_at: string
  provenance: string
  identity: { origin: string; main_path?: string }
  revoked?: boolean
}

interface Registry {
  schema_version: number
  global_policy: { default_level: AuthorityLevel }
  projects: Record<string, ProjectPolicy>
}

interface ControllerOptions {
  registryPath?: string
  journalPath?: string
  now?: () => Date
}

// ---------------------------------------------------------------------------
// Constants — frozen by standard v1.1
// ---------------------------------------------------------------------------

const DELEGABLE_CLASSES: readonly DelegableClass[] = ["C1", "C2", "C3", "C4", "C5a", "C6"]
/** Restriction order, least → most restrictive (§7: divergence → most restrictive wins). */
const CLASS_ORDER: readonly AnyClass[] = ["C1", "C2", "C3", "C4", "C5a", "C6", "C5b", "F"]
const FORBIDDEN_CLASSES: readonly string[] = ["C5b", "F"]
const LEVEL_CLASSES: Record<Exclude<AuthorityLevel, "consultative">, readonly DelegableClass[]> = {
  limited: ["C1", "C2", "C3", "C4"],
  extended: ["C1", "C2", "C3", "C4", "C5a", "C6"],
}
const MEETING_CAP = 3

const IMPACT_KEYS: readonly (keyof Impact)[] = [
  "touches_existing_acceptance_criteria",
  "adds_removes_user_facing_behavior",
  "introduces_commitment",
]

/**
 * Coherence matrix (§6): which (class, impact=true) combinations are coherent.
 * Derived from the class definitions — Limité classes (C1-C4) authorize no
 * impact; C5a authorizes only AC adjustment with unchanged functional goal;
 * C6 is pure cross-task ordering. Everything else → REFUSED (fail-closed).
 */
const COHERENT_TRUE_IMPACTS: Record<DelegableClass, readonly (keyof Impact)[]> = {
  C1: [],
  C2: [],
  C3: [],
  C4: [],
  C5a: ["touches_existing_acceptance_criteria"],
  C6: [],
}

// ---------------------------------------------------------------------------
// Canonical hashing
// ---------------------------------------------------------------------------

/** Deterministic JSON with fixed key order (never rely on object insertion order). */
export function canonJson(value: unknown): string {
  if (Array.isArray(value)) return "[" + value.map(canonJson).join(",") + "]"
  if (value !== null && typeof value === "object") {
    const obj = value as Record<string, unknown>
    return "{" + Object.keys(obj).sort().map((k) => JSON.stringify(k) + ":" + canonJson(obj[k])).join(",") + "}"
  }
  return JSON.stringify(value)
}

function sha256(text: string): string {
  return createHash("sha256").update(text).digest("hex")
}

/** Canonical digest binding the authorization to the exact decision content (§8.3). */
export function computeDecisionDigest(input: {
  final_text: string
  retained_class: string
  effective_impact: Impact
  constraints: string[]
  project_key: string
}): string {
  return sha256(canonJson(input))
}

// ---------------------------------------------------------------------------
// Pure controller logic
// ---------------------------------------------------------------------------

export function createProductAuthorityController(opts: ControllerOptions = {}) {
  const now = opts.now ?? (() => new Date())
  const registryPath = opts.registryPath ?? join(homedir(), ".config", "opencode", "aurora-product-authority.json")
  const journalPath = opts.journalPath ?? join(homedir(), ".config", "opencode", "aurora-product-authority-journal.jsonl")

  // -- journal helpers ------------------------------------------------------

  interface JournalEntry {
    type: string
    ts: string
    [key: string]: unknown
  }

  function readJournal(): JournalEntry[] {
    if (!existsSync(journalPath)) return []
    return readFileSync(journalPath, "utf8")
      .split("\n")
      .filter((line) => line.trim().length > 0)
      .map((line) => JSON.parse(line) as JournalEntry)
  }

  function appendJournal(entry: Omit<JournalEntry, "ts">): void {
    const line = JSON.stringify({ ...entry, ts: now().toISOString() })
    appendFileSync(journalPath, line + "\n", "utf8")
  }

  function lastRegistryHash(): string | null {
    const entries = readJournal().filter((e) => e.type === "registry_mutation")
    return entries.length === 0 ? null : (entries[entries.length - 1].registry_hash as string)
  }

  // -- registry helpers -----------------------------------------------------

  function readRegistry(): Registry | null {
    if (!existsSync(registryPath)) return null
    try {
      return JSON.parse(readFileSync(registryPath, "utf8")) as Registry
    } catch {
      return null
    }
  }

  function writeRegistry(registry: Registry): void {
    mkdirSync(join(registryPath, ".."), { recursive: true })
    // Atomic write (standard §13 P1-9): temp file + rename on the same
    // filesystem — a crash mid-write can never leave a truncated registry.
    const tmpPath = `${registryPath}.tmp`
    writeFileSync(tmpPath, JSON.stringify(registry, null, 2) + "\n", "utf8")
    renameSync(tmpPath, registryPath)
    appendJournal({ type: "registry_mutation", action: "write", registry_hash: fileHash() })
  }

  function fileHash(): string {
    return sha256(readFileSync(registryPath, "utf8"))
  }

  function projectHash(entry: ProjectPolicy): string {
    return sha256(canonJson(entry))
  }

  function nextAuthorizationId(): string {
    const issued = readJournal().filter((e) => e.type === "authorization_issued")
    const max = issued.reduce((acc, e) => {
      const id = String(e.authorization_id ?? "")
      const n = Number.parseInt(id.replace("AUTH-", ""), 10)
      return Number.isFinite(n) && n > acc ? n : acc
    }, 0)
    return "AUTH-" + String(max + 1).padStart(3, "0")
  }

  // -- validation helpers ---------------------------------------------------

  function isExactImpact(value: unknown): value is Impact {
    if (value === null || typeof value !== "object") return false
    const obj = value as Record<string, unknown>
    return IMPACT_KEYS.every((k) => typeof obj[k] === "boolean") && Object.keys(obj).length === IMPACT_KEYS.length
  }

  function isNonEmptyString(value: unknown): value is string {
    return typeof value === "string" && value.trim().length > 0
  }

  /** §9.1 malformed check — never lenient. Returns error detail or null. */
  function proposalMalformation(proposal: unknown): string | null {
    if (proposal === null || typeof proposal !== "object") return "proposal_not_an_object"
    const p = proposal as Record<string, unknown>
    if (!isNonEmptyString(p.decision_id)) return "missing_decision_id"
    if (!isNonEmptyString(p.title)) return "missing_title"
    if (!isNonEmptyString(p.final_text)) return "missing_final_text"
    if (p.classification === null || typeof p.classification !== "object") return "missing_classification"
    const c = p.classification as Record<string, unknown>
    if (!isNonEmptyString(c.class)) return "missing_class"
    if (!DELEGABLE_CLASSES.includes(c.class as DelegableClass) && !FORBIDDEN_CLASSES.includes(String(c.class))) {
      return "class_outside_enum"
    }
    if (!isNonEmptyString(c.rationale)) return "missing_classification_rationale"
    if (!isExactImpact(p.impact)) return "impact_booleans_missing_or_extra"
    if (!Array.isArray(p.constraints) || !p.constraints.every((x) => typeof x === "string")) {
      return "malformed_constraints"
    }
    if (!isNonEmptyString(p.project_key)) return "missing_project_key"
    if (!isNonEmptyString(p.classified_at)) return "missing_classified_at"
    return null
  }

  function reclassificationMalformation(reviewer: unknown, decisionId: string): string | null {
    if (reviewer === null || typeof reviewer !== "object") return "reclassification_not_an_object"
    const r = reviewer as Record<string, unknown>
    if (r.decision_id !== decisionId) return "reclassification_decision_id_mismatch"
    if (!isNonEmptyString(r.reviewer_class)) return "missing_reviewer_class"
    if (!DELEGABLE_CLASSES.includes(r.reviewer_class as DelegableClass) && !FORBIDDEN_CLASSES.includes(String(r.reviewer_class))) {
      return "reviewer_class_outside_enum"
    }
    if (!isExactImpact(r.reviewer_impact)) return "reviewer_impact_booleans_missing_or_extra"
    return null
  }

  function incoherentImpacts(cls: DelegableClass, impact: Impact): string | null {
    const allowed = COHERENT_TRUE_IMPACTS[cls]
    const offending = IMPACT_KEYS.filter((k) => impact[k] && !allowed.includes(k))
    return offending.length === 0 ? null : offending.join(",")
  }

  function mostRestrictive(a: AnyClass, b: AnyClass): AnyClass {
    return CLASS_ORDER.indexOf(a) >= CLASS_ORDER.indexOf(b) ? a : b
  }

  function levelCovers(level: AuthorityLevel, cls: DelegableClass): boolean {
    if (level === "consultative") return false
    return LEVEL_CLASSES[level].includes(cls)
  }

  // -- §9.1 authorizeProductDecision ---------------------------------------

  /**
   * Standard §9.1 signature is authorizeProductDecision(policy, decision, context).
   * `policy` is realized as a policy_id REFERENCE: the controller re-reads the
   * registry itself and verifies integrity + expiry + revocation at call time
   * (re-validation hash À LA RATIFICATION, §4.1). A pre-chewed policy object
   * would be a forgeable input — refused by design.
   */
  function authorizeProductDecision(
    policy: PolicyEnvelope,
    proposal: DecisionProposal,
    context: AuthorizeContext = {},
  ): AuthorizationResult {
    const ctx = { project_key: "", meeting_id: undefined as string | undefined, ...context }
    if (!isNonEmptyString(ctx.project_key)) {
      // Fail-closed: without an orchestrator-resolved execution context the
      // anti-spoofing cross-check cannot run — no lenient fallback (§4.3).
      appendJournal({ type: "decision_refused", decision_id: String((proposal as { decision_id?: unknown })?.decision_id ?? "unknown"), reason: "malformed_proposal", detail: "missing_execution_context_project_key" })
      return { status: "REFUSED", reason: "malformed_proposal", detail: "missing_execution_context_project_key" }
    }

    // 1. Malformed proposal → REFUSED, traced (fail-closed, never lenient).
    const malformation = proposalMalformation(proposal)
    if (malformation !== null) {
      appendJournal({ type: "decision_refused", decision_id: String((proposal as { decision_id?: unknown })?.decision_id ?? "unknown"), reason: "malformed_proposal", detail: malformation })
      return { status: "REFUSED", reason: "malformed_proposal", detail: malformation }
    }

    // 2. Registry state — read by the controller itself, integrity-checked.
    const registry = readRegistry()
    if (registry === null) {
      appendJournal({ type: "decision_blocked", decision_id: proposal.decision_id, reason: "registry_unreadable" })
      return { status: "HUMAN_REQUIRED", reason: "no_policy", detail: "registry unreadable or absent" }
    }
    const currentFileHash = fileHash()
    const expectedHash = lastRegistryHash()
    if (expectedHash !== null && currentFileHash !== expectedHash) {
      // §4.2 / §11: tampering detected → fail-closed consultative + alert.
      appendJournal({ type: "registry_integrity_violation", expected_hash: expectedHash, actual_hash: currentFileHash })
      return {
        status: "HUMAN_REQUIRED",
        reason: "registry_integrity_violation",
        detail: "registry hash does not match journal — fail-closed consultative, run reconcile with explicit confirmation",
        downgrade_recommended: true,
      }
    }
    const entry = registry.projects?.[ctx.project_key]
    if (!entry) {
      appendJournal({ type: "decision_blocked", decision_id: proposal.decision_id, project_key: ctx.project_key, reason: "no_policy" })
      return { status: "HUMAN_REQUIRED", reason: "no_policy", detail: `no policy for project ${ctx.project_key}` }
    }
    if (policy?.policy_id !== undefined && !isNonEmptyString(policy.policy_id)) {
      return { status: "REFUSED", reason: "malformed_proposal", detail: "policy envelope invalid" }
    }
    if (entry.revoked === true) {
      return { status: "HUMAN_REQUIRED", reason: "policy_revoked", detail: "policy was revoked — history stays append-only, new foundations blocked" }
    }
    const expiresMs = new Date(entry.expires_at).getTime()
    // Fail-closed: an unparsable date (NaN) must never read as "never expires".
    if (Number.isNaN(expiresMs) || expiresMs <= now().getTime()) {
      return { status: "HUMAN_REQUIRED", reason: "policy_expired", detail: `expired or unparsable at ${entry.expires_at} — no auto-renewal, fail-closed (§4.1)` }
    }
    if (entry.deferred_until !== undefined) {
      const deferredMs = new Date(entry.deferred_until).getTime()
      if (Number.isNaN(deferredMs) || deferredMs > now().getTime()) {
        return { status: "HUMAN_REQUIRED", reason: "onboarding_deferred", detail: `deferred or unparsable until ${entry.deferred_until} — no re-solicitation during TTL` }
      }
    }
    if (entry.level === "consultative") {
      return { status: "PROPOSE_ONLY", reason: "consultative_mode" }
    }

    // 3. Identity (anti-spoofing, §4.3) — exact cross-check of three sources:
    //    registry identity.origin === orchestrator-resolved context.project_key
    //    === proposal.project_key. Never fuzzy, no lenient fallback.
    if (entry.identity?.origin !== ctx.project_key || proposal.project_key !== ctx.project_key) {
      appendJournal({
        type: "identity_mismatch",
        project_key: ctx.project_key,
        registry_origin: entry.identity?.origin ?? null,
        proposal_project_key: proposal.project_key,
      })
      return {
        status: "HUMAN_REQUIRED",
        reason: "identity_mismatch",
        detail: `identity cross-check failed (registry ${entry.identity?.origin ?? "null"} vs context ${ctx.project_key} vs proposal ${proposal.project_key}) — downgrade consultative + 1 re-confirmation (§4.3)`,
        downgrade_recommended: true,
      }
    }

    // 4. Declared uncertainty (§11) — never resolved mechanically.
    if (ctx.ambiguous_classification === true) {
      return { status: "HUMAN_REQUIRED", reason: "ambiguous_classification", detail: "classification ambiguity is submitted to human validation (§5)" }
    }
    if (ctx.revising_ratified_decision === true) {
      return { status: "HUMAN_REQUIRED", reason: "ratified_decision_revision", detail: "a ratified product decision prevails — revision needs human validation (§5)" }
    }

    // 5. Forbidden classes — even before coherence checks.
    if (FORBIDDEN_CLASSES.includes(proposal.classification.class)) {
      return { status: "HUMAN_REQUIRED", reason: "class_forbidden", detail: `${proposal.classification.class} is never delegable (§5)` }
    }

    // 6. Layer 1 — declared-impact coherence for the PO class (§6).
    const poIncoherence = incoherentImpacts(proposal.classification.class as DelegableClass, proposal.impact)
    if (poIncoherence !== null) {
      appendJournal({ type: "decision_refused", decision_id: proposal.decision_id, reason: "incoherent_impact_combination", detail: `${proposal.classification.class} + true: ${poIncoherence}` })
      return { status: "REFUSED", reason: "incoherent_impact_combination", detail: `${proposal.classification.class} cannot coherently declare true: ${poIncoherence} (§6)` }
    }

    // 7. Layer 2 — independent re-classification REQUIRED for every delegable
    //    candidate, BEFORE the controller decides (§7 sequencing).
    const reviewer = ctx.reviewer
    if (reviewer === undefined) {
      appendJournal({ type: "decision_refused", decision_id: proposal.decision_id, reason: "missing_reclassification" })
      return { status: "REFUSED", reason: "missing_reclassification", detail: "every delegable candidate requires blind re-classification by the product-analyst (§7)" }
    }
    const reviewerMalformation = reclassificationMalformation(reviewer, proposal.decision_id)
    if (reviewerMalformation !== null) {
      appendJournal({ type: "decision_refused", decision_id: proposal.decision_id, reason: "malformed_reclassification", detail: reviewerMalformation })
      return { status: "REFUSED", reason: "malformed_reclassification", detail: reviewerMalformation }
    }

    // 8. Divergence → most restrictive; forbidden in play → HUMAN_REQUIRED (§7).
    const retained = mostRestrictive(proposal.classification.class as AnyClass, reviewer.reviewer_class as AnyClass)
    if (FORBIDDEN_CLASSES.includes(retained)) {
      return {
        status: "HUMAN_REQUIRED",
        reason: "divergence_on_forbidden_class",
        detail: `PO=${proposal.classification.class} vs reviewer=${reviewer.reviewer_class} → retained ${retained} is a forbidden class (§7)`,
      }
    }

    // 9. Effective impact = union of both declarations; coherence re-checked
    //    against the retained class (a reviewer flag can still break coherence).
    const effectiveImpact: Impact = {
      touches_existing_acceptance_criteria: proposal.impact.touches_existing_acceptance_criteria || reviewer.reviewer_impact.touches_existing_acceptance_criteria,
      adds_removes_user_facing_behavior: proposal.impact.adds_removes_user_facing_behavior || reviewer.reviewer_impact.adds_removes_user_facing_behavior,
      introduces_commitment: proposal.impact.introduces_commitment || reviewer.reviewer_impact.introduces_commitment,
    }
    const retainedIncoherence = incoherentImpacts(retained, effectiveImpact)
    if (retainedIncoherence !== null) {
      appendJournal({ type: "decision_refused", decision_id: proposal.decision_id, reason: "incoherent_impact_combination", detail: `retained ${retained} + union-true: ${retainedIncoherence}` })
      return { status: "REFUSED", reason: "incoherent_impact_combination", detail: `retained ${retained} cannot coherently carry union-true impacts: ${retainedIncoherence} (§6)` }
    }

    // 10. Level coverage — the retained class must be covered by the active level.
    if (!levelCovers(entry.level, retained)) {
      return {
        status: "HUMAN_REQUIRED",
        reason: "class_not_covered_by_policy",
        detail: `level ${entry.level} covers ${LEVEL_CLASSES[entry.level as "limited" | "extended"].join("/")} — retained ${retained} exceeds it`,
      }
    }

    // 11. Meeting circuit-breaker (§13): ~3 delegated decisions per meeting.
    if (ctx.meeting_id !== undefined) {
      const issued = readJournal().filter(
        (e) => e.type === "authorization_issued" && e.meeting_id === ctx.meeting_id,
      )
      if (issued.length >= MEETING_CAP) {
        return { status: "HUMAN_REQUIRED", reason: "meeting_cap_reached", detail: `${issued.length} decisions already delegated for this meeting (cap ${MEETING_CAP}, §13)` }
      }
    }

    // 12. All checks pass → attestation + append-only journal (§8.3).
    const pHash = projectHash(entry)
    const digest = computeDecisionDigest({
      final_text: proposal.final_text,
      retained_class: retained,
      effective_impact: effectiveImpact,
      constraints: proposal.constraints,
      project_key: proposal.project_key,
    })
    const attestation: Attestation = {
      issuer: "product-authority-controller",
      authorization_id: nextAuthorizationId(),
      policy_id: isNonEmptyString(policy?.policy_id) ? policy.policy_id : `PA-${proposal.project_key}`,
      policy_hash: pHash,
      decision_digest: digest,
      authorized_at: now().toISOString(),
    }
    appendJournal({
      type: "authorization_issued",
      authorization_id: attestation.authorization_id,
      decision_id: proposal.decision_id,
      project_key: ctx.project_key,
      policy_id: attestation.policy_id,
      policy_hash: pHash,
      decision_digest: digest,
      retained_class: retained,
      constraints: proposal.constraints,
      meeting_id: ctx.meeting_id ?? null,
    })
    return { status: "DELEGATED_APPROVED", attestation, retained_class: retained, effective_impact: effectiveImpact }
  }

  // -- §9.2 verifyAuthorization (point of consumption) ----------------------

  function verifyAuthorization(
    authorizationId: string,
    decisionDigest: string,
    currentContext?: DecisionUsageContext,
  ): VerificationResult {
    const issued = readJournal().filter((e) => e.type === "authorization_issued" && e.authorization_id === authorizationId)
    if (issued.length === 0) {
      return { valid: false, reason: "unknown_authorization" }
    }
    const record = issued[issued.length - 1]

    if (record.decision_digest !== decisionDigest) {
      return { valid: false, reason: "digest_mismatch" }
    }

    // Policy still funds authority at usage time — explicit result, never
    // masked behind REQUIRES_REVALIDATION (§9.2).
    const registry = readRegistry()
    const entry = registry?.projects?.[String(record.project_key)]
    if (!entry) return { valid: false, reason: "policy_revoked" }
    if (entry.revoked === true) return { valid: false, reason: "policy_revoked" }
    if (projectHash(entry) !== record.policy_hash) {
      // Policy replaced/modified since ratification → the original policy no
      // longer stands; covered by policy_revoked (explicit, §9.2 union).
      return { valid: false, reason: "policy_revoked" }
    }
    if (Number.isNaN(new Date(entry.expires_at).getTime()) || new Date(entry.expires_at).getTime() <= now().getTime()) {
      return { valid: false, reason: "policy_expired" }
    }

    // Current context must be verifiable — otherwise the controller cannot
    // assert applicability (§8.4/§9.2).
    if (currentContext === undefined || currentContext === null || typeof currentContext !== "object") {
      return "REQUIRES_REVALIDATION"
    }
    if (
      !isNonEmptyString(currentContext.project_key) ||
      !isNonEmptyString(currentContext.task_scope) ||
      !Array.isArray(currentContext.applicable_constraints) ||
      !Array.isArray(currentContext.known_conflicts) ||
      !currentContext.applicable_constraints.every((x) => typeof x === "string") ||
      !currentContext.known_conflicts.every((x) => typeof x === "string")
    ) {
      return "REQUIRES_REVALIDATION"
    }

    if (currentContext.project_key !== record.project_key) {
      return { valid: true, applicable: false, reason: "project_mismatch" }
    }
    if (currentContext.known_conflicts.includes(String(record.decision_id))) {
      return { valid: true, applicable: false, reason: "conflicting_recent_decision" }
    }
    const constraints = Array.isArray(record.constraints) ? (record.constraints as string[]) : []
    const unconfirmed = constraints.filter((c) => !currentContext.applicable_constraints.includes(c))
    if (unconfirmed.length > 0) {
      return { valid: true, applicable: false, reason: "constraints_not_confirmed", ...( { missing: unconfirmed } as object) }
    }
    return { valid: true, applicable: true }
  }

  // -- Registry mutations (skill product-authority, provenance USER_ASSERTION)

  type PolicyAction =
    | { action: "show" }
    | { action: "set"; project_key: string; level: AuthorityLevel; origin: string; main_path?: string; expires_at?: string }
    | { action: "revoke"; project_key: string }
    | { action: "defer"; project_key: string; until: string }
    | { action: "reconcile"; project_key: string; new_origin?: string; confirm: boolean }

  function mutatePolicy(action: PolicyAction, provenance: string): Record<string, unknown> {
    if (provenance !== "USER_ASSERTION") {
      return { ok: false, error: "provenance_must_be_USER_ASSERTION" }
    }
    const registry: Registry = readRegistry() ?? {
      schema_version: 1,
      global_policy: { default_level: "consultative" },
      projects: {},
    }

    if (action.action === "show") {
      return {
        ok: true,
        registry_hash: existsSync(registryPath) ? fileHash() : null,
        journal_hash: lastRegistryHash(),
        integrity_ok:
          !existsSync(registryPath) || lastRegistryHash() === null || fileHash() === lastRegistryHash(),
        registry,
      }
    }

    if (action.action === "set") {
      if (!isNonEmptyString(action.project_key) || !isNonEmptyString(action.origin)) {
        return { ok: false, error: "malformed_action" }
      }
      const level = action.level
      if (!["consultative", "limited", "extended"].includes(level)) {
        return { ok: false, error: "invalid_level" }
      }
      const expires = action.expires_at ?? new Date(now().getTime() + 90 * 24 * 3600 * 1000).toISOString()
      if (Number.isNaN(new Date(expires).getTime())) {
        return { ok: false, error: "malformed_action" }
      }
      const previous = registry.projects[action.project_key]
      registry.projects[action.project_key] = {
        type: "collaborative",
        authority: "shared",
        level,
        expires_at: expires,
        created_at: previous?.created_at ?? now().toISOString(),
        provenance: "USER_ASSERTION",
        identity: { origin: action.origin, ...(action.main_path ? { main_path: action.main_path } : {}) },
        ...(previous?.deferred_until ? { deferred_until: previous.deferred_until } : {}),
      }
      writeRegistry(registry)
      return { ok: true, project_key: action.project_key, level, expires_at: expires, registry_hash: fileHash() }
    }

    if (action.action === "revoke") {
      const entry = registry.projects[action.project_key]
      if (!entry) return { ok: false, error: "unknown_project" }
      entry.revoked = true
      writeRegistry(registry)
      return { ok: true, project_key: action.project_key, revoked: true, registry_hash: fileHash() }
    }

    if (action.action === "defer") {
      if (!isNonEmptyString(action.project_key) || !isNonEmptyString(action.until)) {
        return { ok: false, error: "malformed_action" }
      }
      if (Number.isNaN(new Date(action.until).getTime())) {
        return { ok: false, error: "malformed_action" }
      }
      registry.projects[action.project_key] = registry.projects[action.project_key] ?? {
        type: "collaborative",
        authority: "shared",
        level: "consultative",
        expires_at: new Date(now().getTime() + 90 * 24 * 3600 * 1000).toISOString(),
        created_at: now().toISOString(),
        provenance: "USER_ASSERTION",
        identity: { origin: action.project_key },
      }
      registry.projects[action.project_key].deferred_until = action.until
      writeRegistry(registry)
      return { ok: true, project_key: action.project_key, deferred_until: action.until, registry_hash: fileHash() }
    }

    // reconcile — explicit confirmation required (§4.2/§4.3).
    if (action.action === "reconcile") {
      if (action.confirm !== true) return { ok: false, error: "explicit_confirmation_required" }
      const entry = registry.projects[action.project_key]
      if (!entry) return { ok: false, error: "unknown_project" }
      if (action.new_origin !== undefined) {
        entry.identity = { ...entry.identity, origin: action.new_origin }
      }
      writeRegistry(registry)
      return { ok: true, project_key: action.project_key, reconciled: true, registry_hash: fileHash() }
    }

    return { ok: false, error: "unknown_action" }
  }

  return { authorizeProductDecision, verifyAuthorization, mutatePolicy, readJournal, readRegistry }
}

// ---------------------------------------------------------------------------
// OpenCode v2 plugin wiring (orchestrator-only, pattern ADR-021)
// ---------------------------------------------------------------------------

const ORCHESTRATOR_AGENTS = new Set(["aurora"])

interface V2SetupContext {
  tool: {
    transform: (callback: (draft: V2ToolDraft) => void) => Promise<{ dispose: () => void }>
  }
}

interface V2ToolDraft {
  add: (tool: {
    name: string
    description: string
    input: Record<string, unknown>
    options?: { codemode?: boolean }
    execute: (args: unknown, context: { agent?: string; sessionID?: string; messageID?: string }) => Promise<unknown> | unknown
  }) => void
}

function requireOrchestrator(
  agent: string,
  toolName: string,
  context?: { sessionID?: string; messageID?: string },
): void {
  if (!ORCHESTRATOR_AGENTS.has(agent)) {
    // Audit line (same pattern as infomaniak-bridge): a gate bypass attempt on
    // an authority tool is the alarm signal of a prompt injection — never silent.
    console.log(JSON.stringify({
      plugin: "product-authority",
      ts: new Date().toISOString(),
      sessionID: context?.sessionID,
      messageID: context?.messageID,
      agent,
      tool: toolName,
      result: "deny",
      reason: "orchestrator_gate",
    }))
    throw new Error(
      `${toolName} is restricted to the orchestrator (aurora). Current agent: '${agent}'. ` +
        `Product authority is brokered by aurora: request it in your task output instead of calling this tool.`,
    )
  }
}

/** v2 tool contract: execute must resolve to `{content, metadata?}` — a raw object surfaces as `undefined` to the model. */
function asContent(value: unknown): { content: string } {
  return { content: JSON.stringify(value, null, 2) }
}

const controller = createProductAuthorityController()

export default {
  id: "product-authority",
  setup: async (ctx: V2SetupContext) => {
    const registration = await ctx.tool.transform((draft) => {
      draft.add({
        name: "authorizeProductDecision",
        description: `Authorize (or fail-closed refuse) a delegated product decision — Standard product-authority.md §9.1, orchestrator-only.

Emits DELEGATED_APPROVED + attestation, HUMAN_REQUIRED, PROPOSE_ONLY or REFUSED. The controller re-reads the registry itself and verifies integrity, expiry, revocation, identity, impact coherence and the blind re-classification (§7 sequencing). A DELEGATED_APPROVED never authorizes execution — it funds a content decision only.`,
        input: {
          type: "object",
          properties: {
            policy_id: { type: "string", description: "Policy reference — the controller re-reads the registry itself" },
            project_key: { type: "string", description: "Execution project key resolved by the orchestrator from git (NOT the proposal's — anti-spoofing cross-check §4.3). Required." },
            proposal: { type: "object", additionalProperties: true, description: "Decision Proposal (§8.1) produced by the product-owner agent" },
            meeting_id: { type: "string", description: "Current meeting id (enables the 3-decision circuit breaker, §13)" },
            reviewer: { type: "object", additionalProperties: true, description: "Reclassification (§8.5) — blind, from the product-analyst, BEFORE authorization (§7)" },
            ambiguous_classification: { type: "boolean", description: "Set true when the classification itself is ambiguous (§5) → HUMAN_REQUIRED" },
            revising_ratified_decision: { type: "boolean", description: "Set true when the decision revises an already-ratified product decision (§5) → HUMAN_REQUIRED" },
          },
          required: ["policy_id", "project_key", "proposal"],
        },
        options: { codemode: false },
        async execute(rawArgs, context) {
          const args = (rawArgs ?? {}) as Record<string, unknown>
          requireOrchestrator(String(context?.agent ?? ""), "authorizeProductDecision", context)
          const result = controller.authorizeProductDecision(
            { policy_id: String(args.policy_id ?? "") },
            args.proposal as DecisionProposal,
            {
              project_key: String(args.project_key ?? ""),
              meeting_id: args.meeting_id === undefined ? undefined : String(args.meeting_id),
              reviewer: args.reviewer as Reclassification | undefined,
              ambiguous_classification: args.ambiguous_classification === true,
              revising_ratified_decision: args.revising_ratified_decision === true,
            },
          )
          return asContent(result)
        },
      })

      draft.add({
        name: "verifyAuthorization",
        description: `Re-verify a delegated decision's attestation at the point of consumption — Standard §9.2, orchestrator-only.

Returns the full frozen union: {valid,applicable} | {valid,applicable:false,reason} | {valid:false,reason:unknown_authorization|digest_mismatch|policy_expired|policy_revoked} | "REQUIRES_REVALIDATION". Invoke at EVERY use of a delegated decision as authority. A DELEGATED_APPROVED text without a controller-known authorization_id is refused by construction.`,
        input: {
          type: "object",
          properties: {
            authorization_id: { type: "string", description: "Authorization id from the attestation (e.g. AUTH-001)" },
            decision_digest: { type: "string", description: "Digest of the content being consumed — recomputed by the consumer, must match exactly" },
            current_context: {
              type: "object",
              additionalProperties: true,
              description: "DecisionUsageContext (§8.4): project_key, task_scope, applicable_constraints, known_conflicts — omit only if truly unverifiable (→ REQUIRES_REVALIDATION)",
            },
          },
          required: ["authorization_id", "decision_digest"],
        },
        options: { codemode: false },
        async execute(rawArgs, context) {
          const args = (rawArgs ?? {}) as Record<string, unknown>
          requireOrchestrator(String(context?.agent ?? ""), "verifyAuthorization", context)
          return asContent(
            controller.verifyAuthorization(
              String(args.authorization_id ?? ""),
              String(args.decision_digest ?? ""),
              args.current_context as DecisionUsageContext | undefined,
            ),
          )
        },
      })

      draft.add({
        name: "productAuthorityPolicy",
        description: `Mutate or inspect the private product-authority registry — Standard §4.2, orchestrator-only, via the skill 'product-authority' protocol.

Actions: show (integrity cross-check included), set (onboarding: level + identity origin, +90d expiry, provenance USER_ASSERTION mandatory), revoke, defer (TTL 14d), reconcile (explicit confirmation required). Policies NEVER live in shared repos.`,
        input: {
          type: "object",
          properties: {
            action: { type: "string", enum: ["show", "set", "revoke", "defer", "reconcile"], description: "Mutation or inspection action" },
            project_key: { type: "string", description: "Project key — normalized host/owner/repo" },
            level: { type: "string", enum: ["consultative", "limited", "extended"], description: "Authority level (set)" },
            origin: { type: "string", description: "Normalized git origin (set)" },
            main_path: { type: "string", description: "Main worktree path cross-checked at onboarding (set, optional)" },
            until: { type: "string", description: "ISO-8601 — defer TTL end (defer)" },
            new_origin: { type: "string", description: "New identity origin (reconcile, optional)" },
            confirm: { type: "boolean", description: "Explicit human confirmation (reconcile — mandatory true)" },
            provenance: { type: "string", enum: ["USER_ASSERTION"], description: "Mandatory for all mutations — the assertion MUST come from a direct user message" },
          },
          required: ["action", "provenance"],
        },
        options: { codemode: false },
        async execute(rawArgs, context) {
          const args = (rawArgs ?? {}) as Record<string, unknown>
          requireOrchestrator(String(context?.agent ?? ""), "productAuthorityPolicy", context)
          const action = String(args.action ?? "")
          if (action === "show") {
            return asContent(controller.mutatePolicy({ action: "show" }, String(args.provenance ?? "")))
          }
          if (action === "set") {
            return asContent(
              controller.mutatePolicy(
                {
                  action: "set",
                  project_key: String(args.project_key ?? ""),
                  level: args.level as AuthorityLevel,
                  origin: String(args.origin ?? ""),
                  ...(args.main_path !== undefined ? { main_path: String(args.main_path) } : {}),
                },
                String(args.provenance ?? ""),
              ),
            )
          }
          if (action === "revoke") {
            return asContent(controller.mutatePolicy({ action: "revoke", project_key: String(args.project_key ?? "") }, String(args.provenance ?? "")))
          }
          if (action === "defer") {
            return asContent(controller.mutatePolicy({ action: "defer", project_key: String(args.project_key ?? ""), until: String(args.until ?? "") }, String(args.provenance ?? "")))
          }
          if (action === "reconcile") {
            return asContent(
              controller.mutatePolicy(
                {
                  action: "reconcile",
                  project_key: String(args.project_key ?? ""),
                  ...(args.new_origin !== undefined ? { new_origin: String(args.new_origin) } : {}),
                  confirm: args.confirm === true,
                },
                String(args.provenance ?? ""),
              ),
            )
          }
          return asContent({ ok: false, error: "unknown_action" })
        },
      })
    })
    return () => registration.dispose()
  },
}
