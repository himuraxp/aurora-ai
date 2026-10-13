#!/usr/bin/env node
/**
 * test-product-authority.mjs — Reception test matrix (standard product-authority.md §12)
 *
 * Exercises the PURE controller logic (createProductAuthorityController) via
 * Node 24 native type-stripping: no OpenCode runtime required. Each test uses
 * an isolated temp registry + journal. ~30 scenarios covering §12 mandatory
 * cases plus the review extensions (malformed → traced REFUSED, expired/
 * revoked at usage → explicit result, ambiguity → HUMAN_REQUIRED, C5a+AC
 * verdict, digest mismatch, tampering, morphing e2e).
 *
 * Run: node scripts/test-product-authority.mjs
 */

import { mkdtempSync, writeFileSync, readFileSync, rmSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import plugin, {
  createProductAuthorityController,
  computeDecisionDigest,
} from "../config/plugins/product-authority.ts"

const T0 = new Date("2026-10-13T10:00:00.000Z")
const NOW = () => new Date(T0.getTime())
const REG = join(mkdtempSync(join(tmpdir(), "pa-test-")), "registry.json")
const JRN = REG.replace("registry.json", "journal.jsonl")

function freshController() {
  return createProductAuthorityController({ registryPath: REG, journalPath: JRN, now: NOW })
}

function writeRawRegistry(obj) {
  writeFileSync(REG, JSON.stringify(obj, null, 2) + "\n", "utf8")
}

function setPolicy(c, level, overrides = {}) {
  return c.mutatePolicy(
    {
      action: "set",
      project_key: "github.com/himuraxp/demo",
      level,
      origin: "github.com/himuraxp/demo",
      ...(overrides.expires_at ? { expires_at: overrides.expires_at } : {}),
    },
    "USER_ASSERTION",
  )
}

const IMPACT_NONE = {
  touches_existing_acceptance_criteria: false,
  adds_removes_user_facing_behavior: false,
  introduces_commitment: false,
}

function mkProposal(overrides = {}) {
  return {
    decision_id: "PD-001",
    title: "Clarify acceptance criteria wording",
    final_text: "Clarify the wording of acceptance criterion 3: 'user is logged in' becomes 'user holds a valid session'. Functional intent unchanged.",
    classification: { class: "C1", rationale: "wording only, intent unchanged" },
    impact: { ...IMPACT_NONE },
    constraints: ["no behavioral change"],
    project_key: "github.com/himuraxp/demo",
    classified_at: T0.toISOString(),
    ...overrides,
  }
}

const PROJECT = "github.com/himuraxp/demo"

const REVIEWER_OK = (cls = "C1", impact = {}, decisionId = "PD-001") => ({
  decision_id: decisionId,
  reviewer_class: cls,
  reviewer_impact: { ...IMPACT_NONE, ...impact },
  notes: "independent blind re-classification",
})

// -- mini runner ---------------------------------------------------------------

let pass = 0
let failCount = 0
const failures = []

function test(name, fn) {
  try {
    fn()
    pass++
    console.log(`  ok   ${name}`)
  } catch (e) {
    failCount++
    failures.push({ name, error: e.message })
    console.log(`  FAIL ${name} — ${e.message}`)
  }
}

function assert(cond, msg) {
  if (!cond) throw new Error(msg)
  pass++
}

function eq(actual, expected, msg) {
  assert(actual === expected, `${msg} (expected ${JSON.stringify(expected)}, got ${JSON.stringify(actual)})`)
}

console.log(`Registry: ${REG}\n`)

// ─── A. Malformed proposals → traced REFUSED (§9.1) ──────────────────────────

console.log("A. malformed proposals")
{
  const c = freshController()
  setPolicy(c, "limited")
  const { touches_existing_acceptance_criteria, ...missingImpact } = IMPACT_NONE
  let r = c.authorizeProductDecision({ policy_id: "PA-1" }, mkProposal({ impact: missingImpact }), { project_key: PROJECT, reviewer: REVIEWER_OK() })
  eq(r.status, "REFUSED", "A1 missing impact boolean")
  eq(r.reason, "malformed_proposal", "A1 reason")
  r = c.authorizeProductDecision({ policy_id: "PA-1" }, mkProposal({ classification: { class: "C9", rationale: "x" } }), { project_key: PROJECT, reviewer: REVIEWER_OK() })
  eq(r.status, "REFUSED", "A2 class outside enum")
  eq(r.reason, "malformed_proposal", "A2 reason")
  eq(r.detail, "class_outside_enum", "A2 detail")
  r = c.authorizeProductDecision({ policy_id: "PA-1" }, mkProposal({ final_text: "" }), { project_key: PROJECT, reviewer: REVIEWER_OK() })
  eq(r.reason, "malformed_proposal", "A3 empty final_text")
  const journal = c.readJournal().filter((e) => e.type === "decision_refused")
  assert(journal.length >= 3, "A4 refusals traced in append-only journal")
}

// ─── B. Policy state → fail-closed HUMAN_REQUIRED (§11) ──────────────────────

console.log("B. policy state")
{
  rmSync(REG, { force: true }); rmSync(JRN, { force: true })
  const c = freshController()
  let r = c.authorizeProductDecision({ policy_id: "PA-1" }, mkProposal(), { project_key: PROJECT, reviewer: REVIEWER_OK() })
  eq(r.status, "HUMAN_REQUIRED", "B1 no policy")
  eq(r.reason, "no_policy", "B1 reason")

  setPolicy(c, "limited")
  r = c.authorizeProductDecision({ policy_id: "PA-1" }, mkProposal(), { project_key: PROJECT, reviewer: REVIEWER_OK() })
  eq(r.status, "DELEGATED_APPROVED", "B2 happy path limited/C1")

  setPolicy(c, "limited", { expires_at: "2026-10-01T00:00:00.000Z" })
  r = c.authorizeProductDecision({ policy_id: "PA-1" }, mkProposal(), { project_key: PROJECT, reviewer: REVIEWER_OK() })
  eq(r.status, "HUMAN_REQUIRED", "B3 expired")
  eq(r.reason, "policy_expired", "B3 reason")

  setPolicy(c, "limited")
  c.mutatePolicy({ action: "revoke", project_key: "github.com/himuraxp/demo" }, "USER_ASSERTION")
  r = c.authorizeProductDecision({ policy_id: "PA-1" }, mkProposal(), { project_key: PROJECT, reviewer: REVIEWER_OK() })
  eq(r.status, "HUMAN_REQUIRED", "B4 revoked")
  eq(r.reason, "policy_revoked", "B4 reason")

  rmSync(REG, { force: true }); rmSync(JRN, { force: true })
  setPolicy(c, "consultative")
  r = c.authorizeProductDecision({ policy_id: "PA-1" }, mkProposal(), { project_key: PROJECT, reviewer: REVIEWER_OK() })
  eq(r.status, "PROPOSE_ONLY", "B5 consultative")
  eq(r.reason, "consultative_mode", "B5 reason")

  c.mutatePolicy({ action: "defer", project_key: "github.com/himuraxp/demo", until: "2026-10-20T00:00:00.000Z" }, "USER_ASSERTION")
  r = c.authorizeProductDecision({ policy_id: "PA-1" }, mkProposal(), { project_key: PROJECT, reviewer: REVIEWER_OK() })
  eq(r.status, "HUMAN_REQUIRED", "B6 onboarding deferred (TTL active)")
  eq(r.reason, "onboarding_deferred", "B6 reason")
}

// ─── C. Identity anti-spoofing (§4.3) ────────────────────────────────────────

console.log("C. identity")
{
  rmSync(REG, { force: true }); rmSync(JRN, { force: true })
  const c = freshController()
  setPolicy(c, "extended")
  let r = c.authorizeProductDecision({ policy_id: "PA-1" }, mkProposal({ project_key: "github.com/attacker/demo" }), { project_key: PROJECT, reviewer: REVIEWER_OK() })
  eq(r.status, "HUMAN_REQUIRED", "C1 spoofed proposal project_key")
  eq(r.reason, "identity_mismatch", "C1 reason")
  eq(r.downgrade_recommended, true, "C1 downgrade recommended")

  // No policy borrowing: a different execution project cannot reuse another
  // project's policy (no fuzzy matching, §4.3) — fail-closed no_policy.
  r = c.authorizeProductDecision(
    { policy_id: "PA-1" },
    mkProposal(),
    { project_key: "github.com/other/repo", reviewer: REVIEWER_OK() },
  )
  eq(r.status, "HUMAN_REQUIRED", "C2 no policy borrowing (no fuzzy)")
  eq(r.reason, "no_policy", "C2 reason")

  // Missing execution context → no lenient fallback on the forgeable proposal field.
  r = c.authorizeProductDecision({ policy_id: "PA-1" }, mkProposal(), { reviewer: REVIEWER_OK() })
  eq(r.status, "REFUSED", "C3 missing execution context")
  eq(r.reason, "malformed_proposal", "C3 reason")
  eq(r.detail, "missing_execution_context_project_key", "C3 detail")
}

// ─── D. Forbidden classes + declared uncertainty (§5, §11) ───────────────────

console.log("D. forbidden classes & uncertainty")
{
  rmSync(REG, { force: true }); rmSync(JRN, { force: true })
  const c = freshController()
  setPolicy(c, "extended")
  let r = c.authorizeProductDecision({ policy_id: "PA-1" }, mkProposal({ classification: { class: "F", rationale: "x" } }), { project_key: PROJECT, reviewer: REVIEWER_OK("F") })
  eq(r.status, "HUMAN_REQUIRED", "D1 class F")
  eq(r.reason, "class_forbidden", "D1 reason")
  r = c.authorizeProductDecision({ policy_id: "PA-1" }, mkProposal({ classification: { class: "C5b", rationale: "x" } }), { project_key: PROJECT, reviewer: REVIEWER_OK("C5b") })
  eq(r.reason, "class_forbidden", "D2 class C5b")
  r = c.authorizeProductDecision({ policy_id: "PA-1" }, mkProposal(), { project_key: PROJECT, reviewer: REVIEWER_OK(), ambiguous_classification: true })
  eq(r.status, "HUMAN_REQUIRED", "D3 ambiguous classification")
  eq(r.reason, "ambiguous_classification", "D3 reason")
  r = c.authorizeProductDecision({ policy_id: "PA-1" }, mkProposal(), { project_key: PROJECT, reviewer: REVIEWER_OK(), revising_ratified_decision: true })
  eq(r.status, "HUMAN_REQUIRED", "D4 ratified decision revision")
  eq(r.reason, "ratified_decision_revision", "D4 reason")
}

// ─── E. Impact coherence layer 1 (§6) ────────────────────────────────────────

console.log("E. impact coherence")
{
  rmSync(REG, { force: true }); rmSync(JRN, { force: true })
  const c = freshController()
  setPolicy(c, "extended")
  let r = c.authorizeProductDecision({ policy_id: "PA-1" }, mkProposal({ impact: { ...IMPACT_NONE, adds_removes_user_facing_behavior: true } }), { project_key: PROJECT, reviewer: REVIEWER_OK() })
  eq(r.status, "REFUSED", "E1 C1 + user-facing behavior")
  eq(r.reason, "incoherent_impact_combination", "E1 reason")
  r = c.authorizeProductDecision({ policy_id: "PA-1" }, mkProposal({ impact: { ...IMPACT_NONE, introduces_commitment: true } }), { project_key: PROJECT, reviewer: REVIEWER_OK() })
  eq(r.reason, "incoherent_impact_combination", "E2 C1 + commitment")
  r = c.authorizeProductDecision(
    { policy_id: "PA-1" },
    mkProposal({ classification: { class: "C2", rationale: "local ordering" }, impact: { ...IMPACT_NONE, introduces_commitment: true } }),
    { project_key: PROJECT, reviewer: REVIEWER_OK("C2") },
  )
  eq(r.reason, "incoherent_impact_combination", "E3 C2 + commitment")
}

// ─── F. Independent re-classification (§7) ───────────────────────────────────

console.log("F. re-classification")
{
  rmSync(REG, { force: true }); rmSync(JRN, { force: true })
  const c = freshController()
  setPolicy(c, "extended")
  let r = c.authorizeProductDecision({ policy_id: "PA-1" }, mkProposal(), { project_key: PROJECT })
  eq(r.status, "REFUSED", "F1 missing re-classification")
  eq(r.reason, "missing_reclassification", "F1 reason")

  r = c.authorizeProductDecision(
    { policy_id: "PA-1" },
    mkProposal(),
    { project_key: PROJECT, reviewer: { decision_id: "PD-999", reviewer_class: "C1", reviewer_impact: { ...IMPACT_NONE } } },
  )
  eq(r.reason, "malformed_reclassification", "F2 decision_id mismatch")

  // Divergence on delegable classes → most restrictive wins, approved on it.
  r = c.authorizeProductDecision({ policy_id: "PA-1" }, mkProposal(), { project_key: PROJECT, reviewer: REVIEWER_OK("C3") })
  eq(r.status, "DELEGATED_APPROVED", "F3 divergence C1 vs C3 → most restrictive")
  eq(r.retained_class, "C3", "F3 retained class")

  // Divergence reaching a forbidden class → HUMAN_REQUIRED.
  r = c.authorizeProductDecision(
    { policy_id: "PA-1" },
    mkProposal({ classification: { class: "C3", rationale: "minor UX" } }),
    { project_key: PROJECT, reviewer: REVIEWER_OK("C5b") },
  )
  eq(r.status, "HUMAN_REQUIRED", "F4 divergence C3 vs C5b → forbidden in play")
  eq(r.reason, "divergence_on_forbidden_class", "F4 reason")

  // Reviewer impact union can break coherence of the retained class.
  r = c.authorizeProductDecision(
    { policy_id: "PA-1" },
    mkProposal(),
    { project_key: PROJECT, reviewer: REVIEWER_OK("C3", { adds_removes_user_facing_behavior: true }) },
  )
  eq(r.status, "REFUSED", "F5 reviewer impact union breaks coherence")
  eq(r.reason, "incoherent_impact_combination", "F5 reason")
}

// ─── G. C5a + touches_existing_acceptance_criteria (§6 edge case) ────────────

console.log("G. C5a + AC edge case")
{
  rmSync(REG, { force: true }); rmSync(JRN, { force: true })
  const c = freshController()
  setPolicy(c, "extended")
  const proposal = mkProposal({
    decision_id: "PD-002",
    classification: { class: "C5a", rationale: "realization adjustment, functional goal unchanged" },
    impact: { ...IMPACT_NONE, touches_existing_acceptance_criteria: true },
  })
  // Reviewer converges (non-essential AC) → defined verdict: delegable.
  let r = c.authorizeProductDecision(
    { policy_id: "PA-1" },
    proposal,
    { project_key: PROJECT, reviewer: REVIEWER_OK("C5a", { touches_existing_acceptance_criteria: true }, "PD-002") },
  )
  eq(r.status, "DELEGATED_APPROVED", "G1 C5a + AC=true, convergent, extended level")
  eq(r.retained_class, "C5a", "G1 retained")

  // Reviewer deems the AC essential (C5b) → forbidden divergence.
  rmSync(REG, { force: true }); rmSync(JRN, { force: true })
  setPolicy(c, "extended")
  r = c.authorizeProductDecision(
    { policy_id: "PA-1" },
    proposal,
    { project_key: PROJECT, reviewer: REVIEWER_OK("C5b", { touches_existing_acceptance_criteria: true }, "PD-002") },
  )
  eq(r.status, "HUMAN_REQUIRED", "G2 C5a + AC essential (reviewer C5b)")
  eq(r.reason, "divergence_on_forbidden_class", "G2 reason")

  // Same C5a+AC=true at limited level → class not covered.
  rmSync(REG, { force: true }); rmSync(JRN, { force: true })
  setPolicy(c, "limited")
  r = c.authorizeProductDecision(
    { policy_id: "PA-1" },
    proposal,
    { project_key: PROJECT, reviewer: REVIEWER_OK("C5a", { touches_existing_acceptance_criteria: true }, "PD-002") },
  )
  eq(r.status, "HUMAN_REQUIRED", "G3 C5a exceeds limited level")
  eq(r.reason, "class_not_covered_by_policy", "G3 reason")
}

// ─── H. Morphing C1→C5b e2e (§12 mandatory scenario) ─────────────────────────

console.log("H. morphing e2e")
{
  rmSync(REG, { force: true }); rmSync(JRN, { force: true })
  const c = freshController()
  setPolicy(c, "limited")
  const morphing = mkProposal({
    decision_id: "PD-003",
    final_text: "Clarify acceptance criterion 3 by removing the legacy CSV export formats the UI still supports.",
    classification: { class: "C1", rationale: "just clarifying the AC" },
    impact: { ...IMPACT_NONE },
  })
  // Blind reviewer sees the final text only → reclassifies C5b.
  const r = c.authorizeProductDecision(
    { policy_id: "PA-1" },
    morphing,
    { project_key: PROJECT, reviewer: REVIEWER_OK("C5b", { adds_removes_user_facing_behavior: true }, "PD-003") },
  )
  eq(r.status, "HUMAN_REQUIRED", "H1 C5b disguised as C1 → never approved")
  eq(r.reason, "divergence_on_forbidden_class", "H1 reason")
}

// ─── I. Meeting cap (§13) ────────────────────────────────────────────────────

console.log("I. meeting cap")
{
  rmSync(REG, { force: true }); rmSync(JRN, { force: true })
  const c = freshController()
  setPolicy(c, "limited")
  for (let i = 1; i <= 3; i++) {
    const r = c.authorizeProductDecision(
      { policy_id: "PA-1" },
      mkProposal({ decision_id: `PD-0${i}`, title: `d${i}`, final_text: `text ${i}` }),
      { project_key: PROJECT, meeting_id: "MT-1", reviewer: { ...REVIEWER_OK(), decision_id: `PD-0${i}` } },
    )
    eq(r.status, "DELEGATED_APPROVED", `I${i} approved within cap`)
  }
  const r4 = c.authorizeProductDecision(
    { policy_id: "PA-1" },
    mkProposal({ decision_id: "PD-004", title: "d4", final_text: "text 4" }),
    { project_key: PROJECT, meeting_id: "MT-1", reviewer: { ...REVIEWER_OK(), decision_id: "PD-004" } },
  )
  eq(r4.status, "HUMAN_REQUIRED", "I4 4th decision hits cap")
  eq(r4.reason, "meeting_cap_reached", "I4 reason")
  // Another meeting is unaffected (cap is per meeting).
  const rOther = c.authorizeProductDecision(
    { policy_id: "PA-1" },
    mkProposal({ decision_id: "PD-005", title: "d5", final_text: "text 5" }),
    { project_key: PROJECT, meeting_id: "MT-2", reviewer: { ...REVIEWER_OK(), decision_id: "PD-005" } },
  )
  eq(rOther.status, "DELEGATED_APPROVED", "I5 cap is per-meeting")
}

// ─── J. verifyAuthorization — point of consumption (§9.2) ────────────────────

console.log("J. verifyAuthorization")
{
  rmSync(REG, { force: true }); rmSync(JRN, { force: true })
  const c = freshController()
  setPolicy(c, "limited")
  const proposal = mkProposal()
  const auth = c.authorizeProductDecision({ policy_id: "PA-1" }, proposal, { project_key: PROJECT, reviewer: REVIEWER_OK() })
  eq(auth.status, "DELEGATED_APPROVED", "J0 setup authorization")
  const digest = auth.attestation.decision_digest
  const ctx = {
    project_key: "github.com/himuraxp/demo",
    task_scope: "implement acceptance-criteria wording",
    applicable_constraints: ["no behavioral change"],
    known_conflicts: [],
  }

  eq(JSON.stringify(c.verifyAuthorization("AUTH-999", digest, ctx)), JSON.stringify({ valid: false, reason: "unknown_authorization" }), "J1 unknown id")
  const v2 = c.verifyAuthorization(auth.attestation.authorization_id, "deadbeef", ctx)
  eq(v2.valid, false, "J2 digest mismatch invalid")
  eq(v2.reason, "digest_mismatch", "J2 reason")

  // Fabricated agent-text status without controller attestation → unknown.
  const v3 = c.verifyAuthorization("AUTH-FABRICATED-BY-AGENT", digest, ctx)
  eq(v3.valid, false, "J3 fabricated status → unknown_authorization")
  eq(v3.reason, "unknown_authorization", "J3 reason")

  // Happy path.
  const v4 = c.verifyAuthorization(auth.attestation.authorization_id, digest, ctx)
  eq(v4.valid, true, "J4 happy path valid")
  eq(v4.applicable, true, "J4 applicable")

  // Modified decision after authorization → digest mismatch.
  const modifiedDigest = computeDecisionDigest({
    final_text: proposal.final_text + " (edited later)",
    retained_class: "C1",
    effective_impact: IMPACT_NONE,
    constraints: proposal.constraints,
    project_key: proposal.project_key,
  })
  const v5 = c.verifyAuthorization(auth.attestation.authorization_id, modifiedDigest, ctx)
  eq(v5.valid, false, "J5 modified decision")
  eq(v5.reason, "digest_mismatch", "J5 reason")

  // Unverifiable context → REQUIRES_REVALIDATION (string, not object).
  eq(c.verifyAuthorization(auth.attestation.authorization_id, digest, undefined), "REQUIRES_REVALIDATION", "J6 no context")
  eq(c.verifyAuthorization(auth.attestation.authorization_id, digest, { project_key: "x", task_scope: "y", applicable_constraints: "not-array", known_conflicts: [] }), "REQUIRES_REVALIDATION", "J7 malformed context")

  // Applicability failures: project mismatch, conflict, unconfirmed constraints.
  const v8 = c.verifyAuthorization(auth.attestation.authorization_id, digest, { ...ctx, project_key: "github.com/other/repo" })
  eq(v8.valid, true, "J8 project mismatch stays valid")
  eq(v8.applicable, false, "J8 not applicable")
  const v9 = c.verifyAuthorization(auth.attestation.authorization_id, digest, { ...ctx, known_conflicts: ["PD-001"] })
  eq(v9.applicable, false, "J9 conflicting recent decision")
  const v10 = c.verifyAuthorization(auth.attestation.authorization_id, digest, { ...ctx, applicable_constraints: ["something else"] })
  eq(v10.applicable, false, "J10 constraints not confirmed")
}

// ─── K. verifyAuthorization — policy state at usage time (explicit, §9.2) ────

console.log("K. verifyAuthorization policy state")
{
  rmSync(REG, { force: true }); rmSync(JRN, { force: true })
  const c = freshController()
  setPolicy(c, "limited")
  const auth = c.authorizeProductDecision({ policy_id: "PA-1" }, mkProposal(), { project_key: PROJECT, reviewer: REVIEWER_OK() })
  const digest = auth.attestation.decision_digest
  const ctx = {
    project_key: "github.com/himuraxp/demo",
    task_scope: "s",
    applicable_constraints: ["no behavioral change"],
    known_conflicts: [],
  }

  // Revoke after issuance → explicit policy_revoked (never REQUIRES_REVALIDATION).
  c.mutatePolicy({ action: "revoke", project_key: "github.com/himuraxp/demo" }, "USER_ASSERTION")
  const v1 = c.verifyAuthorization(auth.attestation.authorization_id, digest, ctx)
  eq(v1.valid, false, "K1 revoked at usage")
  eq(v1.reason, "policy_revoked", "K1 reason")

  // Replace policy (level change → different hash) → policy_revoked (explicit).
  rmSync(REG, { force: true }); rmSync(JRN, { force: true })
  setPolicy(c, "limited")
  const auth2 = c.authorizeProductDecision({ policy_id: "PA-1" }, mkProposal(), { project_key: PROJECT, reviewer: REVIEWER_OK() })
  setPolicy(c, "consultative")
  const v2 = c.verifyAuthorization(auth2.attestation.authorization_id, auth2.attestation.decision_digest, ctx)
  eq(v2.valid, false, "K2 policy replaced (hash mismatch)")
  eq(v2.reason, "policy_revoked", "K2 reason")

  // Expire naturally after issuance → policy_expired at usage (clock moves,
  // file unchanged — this is the no-auto-renewal case, §4.1).
  rmSync(REG, { force: true }); rmSync(JRN, { force: true })
  let driftMs = 0
  const c2 = createProductAuthorityController({
    registryPath: REG,
    journalPath: JRN,
    now: () => new Date(T0.getTime() + driftMs),
  })
  setPolicy(c2, "limited")
  const auth3 = c2.authorizeProductDecision({ policy_id: "PA-1" }, mkProposal(), { project_key: PROJECT, reviewer: REVIEWER_OK() })
  driftMs = 100 * 24 * 3600 * 1000 // 100 days later — past the 90d expiry
  const v3 = c2.verifyAuthorization(auth3.attestation.authorization_id, auth3.attestation.decision_digest, ctx)
  eq(v3.valid, false, "K3 expired at usage")
  eq(v3.reason, "policy_expired", "K3 reason")
}

// ─── L. Registry tampering → integrity fail-closed (§4.2) ────────────────────

console.log("L. registry tampering")
{
  rmSync(REG, { force: true }); rmSync(JRN, { force: true })
  const c = freshController()
  setPolicy(c, "limited")
  // Direct file edit OUTSIDE the controller (agent tampering).
  const raw = JSON.parse(readFileSync(REG, "utf8"))
  raw.projects["github.com/himuraxp/demo"].level = "extended"
  writeFileSync(REG, JSON.stringify(raw, null, 2) + "\n", "utf8")
  const r = c.authorizeProductDecision({ policy_id: "PA-1" }, mkProposal(), { project_key: PROJECT, reviewer: REVIEWER_OK() })
  eq(r.status, "HUMAN_REQUIRED", "L1 tampering detected")
  eq(r.reason, "registry_integrity_violation", "L1 reason")
  eq(r.downgrade_recommended, true, "L1 fail-closed consultative recommended")
}

// ─── M. Provenance enforcement (skill mutations) ─────────────────────────────

console.log("M. provenance")
{
  rmSync(REG, { force: true }); rmSync(JRN, { force: true })
  const c = freshController()
  const bad = c.mutatePolicy({ action: "set", project_key: "github.com/himuraxp/demo", level: "limited", origin: "github.com/himuraxp/demo" }, "LLM_INFERENCE")
  eq(bad.ok, false, "M1 non-USER_ASSERTION provenance refused")
  eq(bad.error, "provenance_must_be_USER_ASSERTION", "M1 error")
  const rec = c.mutatePolicy({ action: "reconcile", project_key: "github.com/himuraxp/demo", confirm: false }, "USER_ASSERTION")
  eq(rec.ok, false, "M2 reconcile without explicit confirmation refused")
}

// Plugin lifecycle: OpenCode calls the setup result during a hot reload.
// Exercise two registrations so a controller-only test cannot hide a broken
// cleanup contract. Never execute a tool against the live policy registry.
console.log("N. plugin lifecycle and orchestrator gate")
for (let cycle = 0; cycle < 2; cycle++) {
  let disposals = 0
  const tools = []
  const cleanup = await plugin.setup({
    tool: {
      async transform(register) {
        register({ add: (tool) => tools.push(tool) })
        return { dispose: () => { disposals++ } }
      },
    },
  })
  eq(typeof cleanup, "function", "N1 setup returns a callable cleanup")
  eq(tools.map((tool) => tool.name).sort().join(","),
    "authorizeProductDecision,productAuthorityPolicy,verifyAuthorization",
    "N2 all three tools remain registered")
  for (const tool of tools) {
    let denied = false
    try {
      await tool.execute({}, { agent: "reviewer" })
    } catch (error) {
      denied = error.message.includes("restricted to the orchestrator")
    }
    assert(denied, `N3 ${tool.name} refuses a capability agent`)
  }
  eq(disposals, 0, "N4 registration remains active until cleanup")
  const show = tools.find((tool) => tool.name === "productAuthorityPolicy")
  const payload = await show.execute(
    { action: "show", provenance: "USER_ASSERTION" },
    { agent: "aurora" },
  )
  eq(
    payload !== null && typeof payload === "object" && typeof payload.content === "string",
    true,
    "N6 execute resolves to the v2 {content} contract — raw objects surface as undefined to the model",
  )
  eq(JSON.parse(payload.content).ok, true, "N7 content parses back to the controller payload")
  await cleanup()
  eq(disposals, 1, "N5 cleanup disposes its registration exactly once")
}

// ─── Summary ─────────────────────────────────────────────────────────────────

console.log(`\n=== ${pass} assertions passed, ${failCount} test groups failed ===`)
if (failCount > 0) {
  for (const f of failures) console.error(`  ${f.name}: ${f.error}`)
  rmSync(join(REG, ".."), { recursive: true, force: true })
  process.exit(1)
}
rmSync(join(REG, ".."), { recursive: true, force: true })
console.log("All reception tests passed.")
