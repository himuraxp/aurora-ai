#!/usr/bin/env python3
"""Tests for the design-qa deterministic contract v2 (convergence loop).

Fixtures only — no network, no browser, no image processing. Python 3.9+,
stdlib only. The convergence scenarios implement the 13 required cases:
new full audit after each fix round, observation-confirmed resolutions,
reopened regressions, no-progress stall, iteration limit, stale signature,
external limitations visibility and task-workflow compatibility.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import dq_contract  # noqa: E402

TS = "2026-10-14T10:00:00Z"
TS2 = "2026-10-14T11:00:00Z"
SIG = "a" * 40
SIG2 = "b" * 40
CLI = os.path.join(os.path.dirname(__file__), "..", "dq_contract.py")


def valid_contract(**overrides):
    contract = {
        "schemaVersion": 1,
        "page": "Distribution",
        "reference": {
            "source": "figma",
            "url": "https://www.figma.com/design/Kkfn3DQwE7rdTs1YPObRTd/Distribution?node-id=1421-40648",
            "fileKey": "Kkfn3DQwE7rdTs1YPObRTd",
            "nodeId": "1421:40648",
            "imagePath": "~/.config/opencode/design-qa/dq-ab12cd34/reference.png",
            "valuesAvailable": True,
            "confidence": "measured",
        },
        "viewport": {"width": 1440, "height": 900},
        "sections": [
            {"name": "Podcast public page", "order": 1, "required": True,
             "components": [], "texts": [], "actions": [], "states": []},
            {"name": "Connected platforms", "order": 2, "required": True,
             "components": ["platform row", "status badge"],
             "texts": ["Platform name", "Last synchronization"],
             "actions": ["external link", "contextual actions"],
             "states": ["active", "inactive", "warning", "error"]},
        ],
        "criteria": [
            {"id": "c1", "kind": "exact", "property": "row-gap", "expected": "16px"},
            {"id": "c2", "kind": "semantic", "note": "rows separated by borders"},
        ],
        "assumptions": [],
        "poQuestions": [],
        "dataDeps": ["platform list is business data"],
    }
    contract.update(overrides)
    return contract


def finding(**overrides):
    entry = {
        "id": "F-01", "category": "component", "severity": "BLOCKER",
        "component": "status badge", "description": "status badge missing",
        "expected": "status badge on each platform row",
        "actual": "no badge rendered", "evidence": "evaluate_script: .platform-row .badge -> null",
        "confidence": "measured", "recommendation": "add ik-badge with state mapping",
        "status": "open",
    }
    entry.update(overrides)
    return entry


class ConvergenceHarness(unittest.TestCase):
    """Builds iteration histories with real snapshot files on disk."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = self._tmp.name

    def history(self, iterations, run_id="dq-test1234", max_iterations=5):
        """iterations: list of dicts {signature, findings(list), audit(dict),
        criteria(list, optional)}. Writes findings-<N>.json snapshots."""
        entries = []
        for index, data in enumerate(iterations):
            snapshot = os.path.join(self.dir, f"findings-{index}.json")
            with open(snapshot, "w", encoding="utf-8") as handle:
                json.dump(data["findings"], handle)
            entry = {
                "index": index,
                "codeSignature": data.get("signature", SIG),
                "capturePath": os.path.join(self.dir, f"actual-{index}.png"),
                "diffPath": os.path.join(self.dir, f"diff-{index}.png"),
                "findingsPath": snapshot,
                "audit": data.get("audit", {"type": "full", "designerAnalysis": True,
                                            "domInspection": True}),
                "counts": dq_contract.observed_counts(data["findings"]),
            }
            if "criteria" in data:
                entry["criteriaVerified"] = data["criteria"]
            entries.append(entry)
        return {"schemaVersion": 1, "runId": run_id, "maxIterations": max_iterations,
                "iterations": entries}


class TestParseFigmaUrl(unittest.TestCase):
    def test_design_url_with_node_id(self):
        result = dq_contract.parse_figma_url(
            "https://www.figma.com/design/Kkfn3DQwE7rdTs1YPObRTd/Distribution?node-id=1421-40648&t=abc")
        self.assertEqual(result, {"fileKey": "Kkfn3DQwE7rdTs1YPObRTd", "nodeId": "1421:40648"})

    def test_file_url_without_node(self):
        result = dq_contract.parse_figma_url("https://www.figma.com/file/AbCdEf123456/Maquette")
        self.assertEqual(result, {"fileKey": "AbCdEf123456", "nodeId": None})

    def test_proto_url(self):
        result = dq_contract.parse_figma_url("https://www.figma.com/proto/AbCdEf123456/Maquette?node-id=1-2")
        self.assertEqual(result["fileKey"], "AbCdEf123456")
        self.assertEqual(result["nodeId"], "1:2")

    def test_non_figma_rejected(self):
        with self.assertRaises(ValueError):
            dq_contract.parse_figma_url("https://example.com/design/abc/x")

    def test_missing_file_key_rejected(self):
        with self.assertRaises(ValueError):
            dq_contract.parse_figma_url("https://www.figma.com/design/")


class TestRunId(unittest.TestCase):
    def test_deterministic_and_distinct(self):
        first = dq_contract.new_run_id("https://figma.com/design/k/n", "http://localhost:4200/p")
        self.assertEqual(first, dq_contract.new_run_id("https://figma.com/design/k/n", "http://localhost:4200/p"))
        self.assertNotEqual(first, dq_contract.new_run_id("https://figma.com/design/k/n", "http://localhost:4200/q"))
        self.assertTrue(first.startswith("dq-"))


class TestContractValidation(unittest.TestCase):
    def test_valid_fixture_passes(self):
        self.assertEqual(dq_contract.validate_contract(valid_contract()), [])

    def test_missing_required_key(self):
        contract = valid_contract()
        del contract["viewport"]
        self.assertTrue(any("viewport" in p for p in dq_contract.validate_contract(contract)))

    def test_bad_reference_source(self):
        problems = dq_contract.validate_contract(valid_contract(reference={"source": "zeplin"}))
        self.assertTrue(any("reference.source" in p for p in problems))

    def test_reference_needs_url_or_image(self):
        reference = {"source": "image", "valuesAvailable": False}
        problems = dq_contract.validate_contract(valid_contract(reference=reference))
        self.assertTrue(any("imagePath" in p for p in problems))

    def test_values_available_must_be_boolean(self):
        reference = dict(valid_contract()["reference"], valuesAvailable="yes")
        problems = dq_contract.validate_contract(valid_contract(reference=reference))
        self.assertTrue(any("valuesAvailable" in p for p in problems))

    def test_empty_sections_rejected(self):
        problems = dq_contract.validate_contract(valid_contract(sections=[]))
        self.assertTrue(any("sections" in p for p in problems))

    def test_section_entries_validated(self):
        sections = [{"required": True}]
        problems = dq_contract.validate_contract(valid_contract(sections=sections))
        self.assertTrue(any("name" in p for p in problems))
        self.assertTrue(any("order" in p for p in problems))

    def test_criteria_kind_validated(self):
        criteria = [{"id": "c9", "kind": "guess"}]
        problems = dq_contract.validate_contract(valid_contract(criteria=criteria))
        self.assertTrue(any("criteria" in p for p in problems))


class TestFindingsValidation(unittest.TestCase):
    def test_valid_findings_pass(self):
        self.assertEqual(dq_contract.validate_findings([finding()]), [])

    def test_missing_required_key(self):
        entry = finding()
        del entry["expected"]
        problems = dq_contract.validate_findings([entry])
        self.assertTrue(any("expected" in p for p in problems))

    def test_evidence_required(self):
        entry = finding()
        del entry["evidence"]
        problems = dq_contract.validate_findings([entry])
        self.assertTrue(any("evidence" in p for p in problems))

    def test_duplicate_ids(self):
        problems = dq_contract.validate_findings([finding(), finding()])
        self.assertTrue(any("duplicate" in p for p in problems))

    def test_bad_severity(self):
        problems = dq_contract.validate_findings([finding(severity="HUGE")])
        self.assertTrue(any("severity" in p for p in problems))

    def test_bad_category(self):
        problems = dq_contract.validate_findings([finding(category="vibes")])
        self.assertTrue(any("category" in p for p in problems))

    def test_external_category_accepted(self):
        entry = finding(id="F-09", category="external", severity="MINOR",
                        description="'!' prefixes before translations",
                        evidence="screenshot actual-0.png zone header")
        self.assertEqual(dq_contract.validate_findings([entry]), [])

    def test_waived_requires_human_trace(self):
        problems = dq_contract.validate_findings([finding(status="waived")])
        self.assertTrue(any("waivedBy" in p for p in problems))
        problems = dq_contract.validate_findings([finding(status="waived", waivedBy="HUMAN")])
        self.assertTrue(any("waivedReason" in p for p in problems))
        problems = dq_contract.validate_findings(
            [finding(status="waived", waivedBy="HUMAN", waivedReason="PO accepts the delta, ticket XYZ")])
        self.assertEqual(problems, [])

    def test_fixed_requires_recheck_trace(self):
        problems = dq_contract.validate_findings([finding(status="fixed")])
        self.assertTrue(any("fixedAt" in p for p in problems))
        problems = dq_contract.validate_findings([finding(status="fixed", fixedAt=TS)])
        self.assertEqual(problems, [])

    def test_reopened_requires_trace(self):
        problems = dq_contract.validate_findings([finding(status="reopened")])
        self.assertTrue(any("reopenedAt" in p for p in problems))
        problems = dq_contract.validate_findings(
            [finding(status="reopened", reopenedAt=TS, origin="reopened")])
        self.assertEqual(problems, [])

    def test_invalid_requires_human_trace(self):
        # R1 pin: an untraceable `invalid` would be an escape hatch to PASSED.
        problems = dq_contract.validate_findings([finding(status="invalid")])
        self.assertTrue(any("invalidBy" in p for p in problems))
        problems = dq_contract.validate_findings([finding(status="invalid", invalidBy="HUMAN")])
        self.assertTrue(any("invalidReason" in p for p in problems))
        problems = dq_contract.validate_findings(
            [finding(status="invalid", invalidBy="HUMAN",
                     invalidReason="false positive: badge rendered by CSS pseudo-element, DOM selector wrong")])
        self.assertEqual(problems, [])

    def test_origin_and_confirmed_in_validated(self):
        problems = dq_contract.validate_findings([finding(origin="unknown")])
        self.assertTrue(any("origin" in p for p in problems))
        problems = dq_contract.validate_findings([finding(confirmedIn=-1)])
        self.assertTrue(any("confirmedIn" in p for p in problems))
        self.assertEqual(dq_contract.validate_findings(
            [finding(status="fixed", fixedAt=TS, origin="new", confirmedIn=1)]), [])


class TestReconcile(unittest.TestCase):
    """Spec scenarios 1–5: reconciliation against a NEW full audit."""

    def test_resolution_confirmed_by_new_audit(self):
        previous = [finding(status="fixed", fixedAt=TS)]
        reconciled, notes = dq_contract.reconcile(previous, [], 1, TS2)
        self.assertEqual(reconciled[0]["status"], "fixed")
        self.assertEqual(reconciled[0]["confirmedIn"], 1)
        self.assertTrue(any("confirmed" in note for note in notes))

    def test_open_confirmed_fixed_by_observation_not_code_change(self):
        # The fix round happened, the new audit does NOT observe the issue:
        # only then may the status become fixed (never by the code change alone).
        previous = [finding(status="open")]
        reconciled, _ = dq_contract.reconcile(previous, [], 1, TS2)
        self.assertEqual(reconciled[0]["status"], "fixed")
        self.assertEqual(reconciled[0]["confirmedIn"], 1)
        self.assertEqual(reconciled[0]["fixedAt"], TS2)

    def test_regression_reopens_fixed_finding(self):
        previous = [finding(status="fixed", fixedAt=TS)]
        observations = [finding()]
        reconciled, notes = dq_contract.reconcile(previous, observations, 2, TS2)
        self.assertEqual(reconciled[0]["status"], "reopened")
        self.assertEqual(reconciled[0]["reopenedAt"], TS2)
        self.assertEqual(reconciled[0]["origin"], "reopened")
        self.assertTrue(any("reopened" in note for note in notes))

    def test_still_open_stays_open(self):
        previous = [finding(status="open")]
        observations = [finding()]
        reconciled, _ = dq_contract.reconcile(previous, observations, 1, TS2)
        self.assertEqual(reconciled[0]["status"], "open")

    def test_new_finding_discovered(self):
        previous = []
        observations = [finding(id="F-07", severity="MAJOR", category="spacing")]
        reconciled, notes = dq_contract.reconcile(previous, observations, 1, TS2)
        self.assertEqual(reconciled[0]["origin"], "new")
        self.assertEqual(reconciled[0]["status"], "open")
        self.assertTrue(any("new finding" in note for note in notes))

    def test_waived_stands_even_if_observed_again(self):
        waived = finding(status="waived", waivedBy="HUMAN", waivedReason="PO decision")
        reconciled, _ = dq_contract.reconcile([waived], [finding()], 1, TS2)
        self.assertEqual(reconciled[0]["status"], "waived")

    def test_invalid_iteration_rejected(self):
        with self.assertRaises(ValueError):
            dq_contract.reconcile([], [], -1, TS2)


class TestCrossCheck(unittest.TestCase):
    """Anti-fake: the findings file may only diverge from the last audit
    snapshot by HUMAN decisions."""

    def test_fixed_without_audit_observation_rejected(self):
        snapshot = [finding(status="open")]  # the audit still saw F-01
        findings = [finding(status="fixed", fixedAt=TS2)]  # but the file says fixed
        problems = dq_contract.cross_check(findings, snapshot)
        self.assertTrue(any("without a new audit" in p for p in problems))

    def test_matching_statuses_pass(self):
        snapshot = [finding(status="open")]
        findings = [finding(status="open")]
        self.assertEqual(dq_contract.cross_check(findings, snapshot), [])

    def test_human_decision_divergence_allowed(self):
        snapshot = [finding(status="open")]
        findings = [finding(status="waived", waivedBy="HUMAN", waivedReason="PO accepts")]
        self.assertEqual(dq_contract.cross_check(findings, snapshot), [])

    def test_traced_invalid_divergence_allowed(self):
        snapshot = [finding(status="open")]
        findings = [finding(status="invalid", invalidBy="HUMAN", invalidReason="false positive")]
        self.assertEqual(dq_contract.cross_check(findings, snapshot), [])

    def test_untraced_invalid_divergence_rejected(self):
        # R1 pin: `invalid` without its human trace is not a human decision.
        snapshot = [finding(status="open")]
        findings = [finding(status="invalid")]
        problems = dq_contract.cross_check(findings, snapshot)
        self.assertTrue(any("require their trace" in p for p in problems))

    def test_severity_downgrade_after_audit_rejected(self):
        # R2 pin: a post-audit BLOCKER→INFO downgrade must never fake a PASSED.
        snapshot = [finding(status="open", severity="BLOCKER")]
        findings = [finding(status="open", severity="INFO")]
        problems = dq_contract.cross_check(findings, snapshot)
        self.assertTrue(any("severity changed after the last audit" in p for p in problems))

    def test_category_change_after_audit_rejected(self):
        snapshot = [finding(status="open", category="component")]
        findings = [finding(status="open", category="data")]
        problems = dq_contract.cross_check(findings, snapshot)
        self.assertTrue(any("category changed after the last audit" in p for p in problems))

    def test_confidence_change_after_audit_rejected(self):
        snapshot = [finding(status="open", confidence="measured")]
        findings = [finding(status="open", confidence="estimated")]
        problems = dq_contract.cross_check(findings, snapshot)
        self.assertTrue(any("confidence changed after the last audit" in p for p in problems))

    def test_finding_lost_after_audit_rejected(self):
        snapshot = [finding(status="open"), finding(id="F-02", severity="MAJOR")]
        findings = [finding(status="open")]
        problems = dq_contract.cross_check(findings, snapshot)
        self.assertTrue(any("missing from the findings file" in p for p in problems))

    def test_new_finding_without_audit_rejected(self):
        snapshot = [finding(status="open")]
        findings = [finding(status="open"), finding(id="F-03")]
        problems = dq_contract.cross_check(findings, snapshot)
        self.assertTrue(any("new findings require a new audit" in p for p in problems))


class TestHistory(ConvergenceHarness):
    def test_valid_history_passes(self):
        history = self.history([
            {"findings": [finding()]},
            {"findings": [], "signature": SIG2},
        ])
        self.assertEqual(dq_contract.validate_history(history), [])

    def test_empty_iterations_rejected(self):
        problems = dq_contract.validate_history(
            {"schemaVersion": 1, "runId": "dq-x", "iterations": []})
        self.assertTrue(any("non-empty" in p for p in problems))

    def test_index_must_ascending(self):
        history = self.history([{"findings": [finding()]}, {"findings": []}])
        history["iterations"][1]["index"] = 0
        self.assertTrue(any("ascending" in p for p in dq_contract.validate_history(history)))

    def test_full_audit_requires_designer_and_dom(self):
        history = self.history([{"findings": [finding()],
                                 "audit": {"type": "full", "designerAnalysis": True,
                                           "domInspection": False}}])
        self.assertTrue(any("full audit requires" in p for p in dq_contract.validate_history(history)))

    def test_audit_type_validated(self):
        history = self.history([{"findings": [], "audit": {"type": "vibes"}}])
        self.assertTrue(any("audit.type" in p for p in dq_contract.validate_history(history)))

    def test_evidence_paths_required(self):
        history = self.history([{"findings": [finding()]}])
        del history["iterations"][0]["capturePath"]
        self.assertTrue(any("capturePath" in p for p in dq_contract.validate_history(history)))

    def test_counts_validated(self):
        history = self.history([{"findings": [finding()]}])
        history["iterations"][0]["counts"] = {"BLOCKER": "1"}
        self.assertTrue(any("counts" in p for p in dq_contract.validate_history(history)))

    def test_bad_run_id_rejected(self):
        history = self.history([{"findings": []}], run_id="nope")
        self.assertTrue(any("runId" in p for p in dq_contract.validate_history(history)))


class TestProgress(unittest.TestCase):
    def test_progress_when_total_decreases_without_regression(self):
        prev = {"BLOCKER": 0, "MAJOR": 5, "MINOR": 2, "INFO": 1}
        curr = {"BLOCKER": 0, "MAJOR": 2, "MINOR": 3, "INFO": 1}
        self.assertTrue(dq_contract.has_progress(prev, curr))

    def test_no_progress_when_total_grows(self):
        prev = {"BLOCKER": 0, "MAJOR": 2, "MINOR": 2, "INFO": 0}
        curr = {"BLOCKER": 0, "MAJOR": 2, "MINOR": 3, "INFO": 0}
        self.assertFalse(dq_contract.has_progress(prev, curr))

    def test_critical_regression_negates_progress(self):
        # A global score would show improvement; per-severity does not.
        prev = {"BLOCKER": 0, "MAJOR": 5, "MINOR": 2, "INFO": 0}
        curr = {"BLOCKER": 1, "MAJOR": 2, "MINOR": 2, "INFO": 0}
        self.assertFalse(dq_contract.has_progress(prev, curr))

    def test_per_severity_not_a_global_score(self):
        # MAJOR fixed but a new BLOCKER appeared: no progress.
        prev = {"BLOCKER": 0, "MAJOR": 5, "MINOR": 2, "INFO": 0}
        curr = {"BLOCKER": 1, "MAJOR": 0, "MINOR": 2, "INFO": 0}
        self.assertFalse(dq_contract.has_progress(prev, curr))


class TestGate(ConvergenceHarness):
    def proven(self, findings=None, signature=SIG, history=None, contract=None):
        """Default: converged history — iter0 open findings, iter1 clean."""
        if findings is None:
            findings = []
        if history is None:
            open_iter = [finding(status="open", fixedAt=TS, confirmedIn=1)]
            if findings:
                open_iter = findings
            history = self.history([
                {"findings": open_iter, "signature": SIG},
                {"findings": findings, "signature": signature},
            ])
        return dq_contract.gate(findings, reference_available=True,
                                history=history, current_signature=signature,
                                contract=contract)

    def test_no_history_cannot_pass(self):
        result = dq_contract.gate([finding(status="fixed", fixedAt=TS)])
        self.assertEqual(result["verdict"], "BLOCKED")
        self.assertFalse(result["convergence"]["proven"])
        self.assertIn("iteration history", result["reason"])

    def test_converged_clean_run_passes(self):
        resolved = [finding(id="F-01", status="fixed", fixedAt=TS, confirmedIn=1)]
        result = self.proven(findings=resolved)
        self.assertEqual(result["verdict"], "PASSED")
        self.assertTrue(result["convergence"]["proven"])
        self.assertEqual(result["applied"], 1)

    def test_open_major_blocks_even_converged(self):
        resolved = [finding(id="F-01", severity="MAJOR", status="fixed",
                            fixedAt=TS, confirmedIn=1),
                    finding(id="F-02", severity="MAJOR", status="open")]
        result = self.proven(findings=resolved)
        self.assertEqual(result["verdict"], "BLOCKED")
        self.assertEqual(result["blocking"], ["F-02"])

    def test_reopened_blocks(self):
        reopened = [finding(status="reopened", reopenedAt=TS2, origin="reopened")]
        result = self.proven(findings=reopened)
        self.assertEqual(result["verdict"], "BLOCKED")
        self.assertEqual(result["remaining"]["BLOCKER"], 1)

    def test_waived_blocker_does_not_block(self):
        waived = [finding(status="waived", waivedBy="HUMAN", waivedReason="PO accepts")]
        result = self.proven(findings=waived)
        self.assertEqual(result["verdict"], "PASSED")

    def test_minor_and_info_do_not_block(self):
        findings = [finding(id="F-01", severity="MINOR", status="fixed",
                            fixedAt=TS, confirmedIn=1),
                    finding(id="F-02", severity="INFO", status="open")]
        result = self.proven(findings=findings)
        self.assertEqual(result["verdict"], "PASSED")

    def test_unknown_status_counts_as_open_fail_closed(self):
        findings = [finding(status="mystery")]
        result = self.proven(findings=findings)
        self.assertEqual(result["verdict"], "BLOCKED")

    def test_no_reference_skips(self):
        result = dq_contract.gate([finding()], reference_available=False)
        self.assertEqual(result["verdict"], "SKIPPED")

    # ── Spec scenario 6: a conforming DOM result alone proves nothing ──
    def test_dom_only_final_audit_cannot_pass(self):
        history = self.history([
            {"findings": [finding()]},
            {"findings": [], "signature": SIG2,
             "audit": {"type": "dom-only", "designerAnalysis": False, "domInspection": True}},
        ])
        result = dq_contract.gate([], history=history, current_signature=SIG2)
        self.assertEqual(result["verdict"], "BLOCKED")
        self.assertIn("full visual audit", result["reason"])

    # ── Spec scenario 7: a visual diff alone proves nothing ──
    def test_visual_only_final_audit_cannot_pass(self):
        history = self.history([
            {"findings": [finding()]},
            {"findings": [], "signature": SIG2,
             "audit": {"type": "visual-only", "designerAnalysis": True, "domInspection": False}},
        ])
        result = dq_contract.gate([], history=history, current_signature=SIG2)
        self.assertEqual(result["verdict"], "BLOCKED")
        self.assertIn("full visual audit", result["reason"])

    # ── Spec scenario 8: two iterations without progress stop the loop ──
    def test_two_iterations_without_progress_block(self):
        stable = [finding(id="F-02", severity="MAJOR", status="open")]
        history = self.history([
            {"findings": stable},
            {"findings": stable, "signature": SIG2},
            {"findings": stable, "signature": SIG2},
        ])
        result = dq_contract.gate(stable, history=history, current_signature=SIG2)
        self.assertEqual(result["verdict"], "BLOCKED")
        self.assertIn("without measurable progress", result["reason"])

    def test_single_no_progress_iteration_does_not_stop(self):
        findings = [finding(id="F-02", severity="MAJOR", status="fixed",
                            fixedAt=TS, confirmedIn=2)]
        history = self.history([
            {"findings": [finding(status="open"),
                          finding(id="F-02", severity="MAJOR", status="open")]},
            {"findings": [finding(status="open"),
                          finding(id="F-02", severity="MAJOR", status="open")],
             "signature": SIG2},
            {"findings": findings, "signature": SIG2},
        ])
        result = dq_contract.gate(findings, history=history, current_signature=SIG2)
        self.assertEqual(result["verdict"], "PASSED")

    # ── Spec scenario 9: the iteration limit never fakes success ──
    def test_max_iterations_with_open_findings_block(self):
        blocker = [finding(status="open")]
        history = self.history([{"findings": blocker}] * 5, max_iterations=5)
        result = dq_contract.gate(blocker, history=history, current_signature=SIG)
        self.assertEqual(result["verdict"], "BLOCKED")
        self.assertIn("max iterations", result["reason"])

    def test_convergence_exactly_at_limit_is_legitimate(self):
        resolved = [finding(status="fixed", fixedAt=TS, confirmedIn=4)]
        history = self.history([
            {"findings": [finding()]}, {"findings": [], "signature": SIG2},
            {"findings": [], "signature": SIG2}, {"findings": [], "signature": SIG2},
            {"findings": resolved, "signature": SIG2},
        ], max_iterations=5)
        result = dq_contract.gate(resolved, history=history, current_signature=SIG2)
        self.assertEqual(result["verdict"], "PASSED")

    # ── Spec scenario 10: a code change invalidates the final verification ──
    def test_code_change_after_final_audit_stales(self):
        resolved = [finding(status="fixed", fixedAt=TS, confirmedIn=1)]
        history = self.history([
            {"findings": [finding(status="open", fixedAt=TS, confirmedIn=1)]},
            {"findings": resolved, "signature": SIG2},
        ])
        result = dq_contract.gate(resolved, history=history, current_signature=SIG2 + "x")
        self.assertEqual(result["verdict"], "BLOCKED")
        self.assertIn("code changed after the final audit", result["reason"])

    def test_missing_signature_cannot_bind(self):
        history = self.history([{"findings": []}])
        result = dq_contract.gate([], history=history, current_signature=None)
        self.assertEqual(result["verdict"], "BLOCKED")
        self.assertIn("signature", result["reason"])

    def test_invalid_history_blocks(self):
        history = self.history([{"findings": []}])
        history["iterations"][0]["audit"]["type"] = "nope"
        result = dq_contract.gate([], history=history, current_signature=SIG)
        self.assertEqual(result["verdict"], "BLOCKED")
        self.assertIn("invalid iteration history", result["reason"])

    def test_missing_snapshot_blocks(self):
        history = self.history([{"findings": []}])
        history["iterations"][0]["findingsPath"] = "/nonexistent/findings-0.json"
        result = dq_contract.gate([], history=history, current_signature=SIG)
        self.assertEqual(result["verdict"], "BLOCKED")
        self.assertIn("snapshot not found", result["reason"])

    def test_findings_diverging_from_snapshot_block(self):
        # Spec scenario 5: an old `fixed` does not mask a current problem.
        # Audit 1 STILL observed F-01 (open) — the file claims fixed anyway.
        history = self.history([
            {"findings": [finding(status="open")]},
            {"findings": [finding(status="open")], "signature": SIG2},
        ])
        tampered = [finding(status="fixed", fixedAt=TS2)]
        result = dq_contract.gate(tampered, history=history, current_signature=SIG2)
        self.assertEqual(result["verdict"], "BLOCKED")
        self.assertIn("without a new audit", result["reason"])

    def test_criteria_coverage_enforced(self):
        resolved = [finding(status="fixed", fixedAt=TS, confirmedIn=1)]
        history = self.history([
            {"findings": [finding(status="open", fixedAt=TS, confirmedIn=1)]},
            {"findings": resolved, "signature": SIG2, "criteria": ["c1"]},
        ])
        result = self.proven(findings=resolved, signature=SIG2,
                             history=history, contract=valid_contract())
        self.assertEqual(result["verdict"], "BLOCKED")
        self.assertIn("c2", result["reason"])

    def test_criteria_all_verified_passes(self):
        resolved = [finding(status="fixed", fixedAt=TS, confirmedIn=1)]
        history = self.history([
            {"findings": [finding(status="open", fixedAt=TS, confirmedIn=1)]},
            {"findings": resolved, "signature": SIG2, "criteria": ["c1", "c2"]},
        ])
        result = self.proven(findings=resolved, signature=SIG2,
                             history=history, contract=valid_contract())
        self.assertEqual(result["verdict"], "PASSED")

    def test_counts_tamper_rejected(self):
        # R3 pin: claimed counts must match the snapshot, recomputed.
        resolved = [finding(status="fixed", fixedAt=TS, confirmedIn=1)]
        history = self.history([
            {"findings": [finding(status="open", fixedAt=TS, confirmedIn=1)]},
            {"findings": resolved, "signature": SIG2},
        ])
        history["iterations"][1]["counts"]["MAJOR"] = 99  # claim something else
        result = dq_contract.gate(resolved, history=history, current_signature=SIG2)
        self.assertEqual(result["verdict"], "BLOCKED")
        self.assertIn("do not match its snapshot", result["reason"])

    def test_max_iterations_one_single_clean_audit_passes(self):
        # R6 pin: a single full audit at the current signature, nothing
        # observed — legitimate PASSED even with maxIterations=1.
        history = self.history([{"findings": []}], max_iterations=1)
        result = dq_contract.gate([], history=history, current_signature=SIG)
        self.assertEqual(result["verdict"], "PASSED")


class TestReport(ConvergenceHarness):
    def summary(self, **overrides):
        entry = {
            "processStatus": "ok", "application": "http://localhost:4200/podcast/distribution",
            "componentsChecked": 8, "tests": "passed", "signature": SIG,
            "contract": "contract.json", "findings": "findings.json",
            "captures": {"reference": "reference.png", "actual": "actual.png", "diff": "diff.png"},
        }
        entry.update(overrides)
        return entry

    def resolved(self):
        return [finding(id="F-01", status="fixed", fixedAt=TS, confirmedIn=1)]

    def converged(self, findings):
        open_iter = [dict(f, status="open", fixedAt=None, confirmedIn=None) for f in findings]
        return self.history([
            {"findings": open_iter, "signature": SIG},
            {"findings": findings, "signature": SIG, "criteria": ["c1", "c2"]},
        ])

    def test_passed_report(self):
        findings = self.resolved()
        report = dq_contract.render_report(
            self.summary(), valid_contract(), findings, self.converged(findings))
        self.assertIn("DESIGN QA — PASSED", report)
        self.assertIn("Iterations:", report)
        self.assertIn("Convergence:", report)
        self.assertIn("PROVEN", report)

    def test_iteration_timeline_rendered(self):
        findings = self.resolved()
        report = dq_contract.render_report(
            self.summary(), valid_contract(), findings, self.converged(findings))
        self.assertIn("#0: BLOCKER 1 · MAJOR 0 · MINOR 0", report)
        self.assertIn("#1: BLOCKER 0 · MAJOR 0 · MINOR 0", report)

    def test_unproven_convergence_blocks_report(self):
        report = dq_contract.render_report(self.summary(), valid_contract(), self.resolved(), None)
        self.assertIn("BLOCKED", report)
        self.assertIn("UNPROVEN", report)

    def test_external_limitations_stay_visible(self):
        # Spec scenario 11: a visible external defect is never silent.
        findings = self.resolved() + [finding(
            id="F-09", category="external", severity="MINOR",
            description="'!' prefixes before translations (i18n keys missing)",
            evidence="screenshot actual-1.png header", status="open")]
        report = dq_contract.render_report(
            self.summary(), valid_contract(), findings, self.converged(findings))
        self.assertIn("External limitations visible:", report)
        self.assertIn("F-09", report)
        self.assertIn("i18n keys missing", report)

    def test_waived_findings_listed_as_po_decisions(self):
        findings = self.resolved() + [finding(
            id="F-10", severity="MAJOR", status="waived", waivedBy="HUMAN",
            waivedReason="PO accepts the 4px delta")]
        report = dq_contract.render_report(
            self.summary(), valid_contract(), findings, self.converged(findings))
        self.assertIn("Accepted risks / PO decisions:", report)
        self.assertIn("F-10", report)
        self.assertIn("PO accepts", report)

    def test_invalid_findings_listed_with_reason(self):
        # R1 pin: invalidated findings stay visible in the report.
        findings = self.resolved() + [finding(
            id="F-11", severity="BLOCKER", status="invalid", invalidBy="HUMAN",
            invalidReason="false positive: pseudo-element badge")]
        report = dq_contract.render_report(
            self.summary(), valid_contract(), findings, self.converged(findings))
        self.assertIn("Invalidated findings (human-confirmed false positives):", report)
        self.assertIn("F-11", report)
        self.assertIn("pseudo-element badge", report)

    def test_external_no_limitations_line(self):
        report = dq_contract.render_report(
            self.summary(), valid_contract(), self.resolved(), self.converged(self.resolved()))
        self.assertIn("External limitations visible:\n  none", report)

    def test_tests_failure_fails_the_run(self):
        findings = self.resolved()
        report = dq_contract.render_report(
            self.summary(tests="failed"), valid_contract(), findings, self.converged(findings))
        self.assertIn("DESIGN QA — FAILED", report)

    def test_skipped_reference_never_hides_failed_tests(self):
        report = dq_contract.render_report(
            self.summary(tests="failed"), valid_contract(reference={}), [], None)
        self.assertIn("FAILED", report)

    def test_process_failure_reported(self):
        report = dq_contract.render_report(
            self.summary(processStatus="failed", processReason="Figma 429"),
            valid_contract(), [], None)
        self.assertIn("DESIGN QA — FAILED", report)
        self.assertIn("Figma 429", report)

    def test_invalid_summary_rejected(self):
        self.assertIn("FAILED", dq_contract.render_report("oops", valid_contract(), [], None))


class TestCLI(ConvergenceHarness):
    def run_cli(self, *args):
        return subprocess.run([sys.executable, CLI, *args],
                              capture_output=True, text=True)

    def test_parse_figma_url_cli(self):
        result = self.run_cli("parse-figma-url", "https://www.figma.com/design/AbCd/X?node-id=1-2")
        self.assertEqual(result.returncode, 0)
        self.assertIn("fileKey", result.stdout)

    def test_validate_history_cli(self):
        history = self.history([{"findings": [finding()]}])
        path = os.path.join(self.dir, "history.json")
        with open(path, "w") as handle:
            json.dump(history, handle)
        self.assertEqual(self.run_cli("validate-history", path).returncode, 0)

    def test_reconcile_cli(self):
        prev_path = os.path.join(self.dir, "prev.json")
        obs_path = os.path.join(self.dir, "obs.json")
        with open(prev_path, "w") as handle:
            json.dump([finding(status="fixed", fixedAt=TS)], handle)
        with open(obs_path, "w") as handle:
            json.dump([], handle)
        result = self.run_cli("reconcile", prev_path, obs_path, "--iteration=1", f"--at={TS2}")
        self.assertEqual(result.returncode, 0)
        self.assertIn("confirmed", result.stderr)  # audit trail on stderr
        payload = json.loads(result.stdout)
        self.assertEqual(payload[0]["status"], "fixed")
        self.assertEqual(payload[0]["confirmedIn"], 1)

    def test_full_convergence_loop_cli(self):
        """End-to-end: audit 0 → fix → audit 1 → history → gate PASSED."""
        findings_path = os.path.join(self.dir, "findings.json")
        history_path = os.path.join(self.dir, "history.json")
        for name in ("actual-0.png", "diff-0.png", "actual-1.png", "diff-1.png"):
            with open(os.path.join(self.dir, name), "w") as handle:
                handle.write("png")

        # Iteration 0: two open findings.
        initial = [finding(id="F-01"), finding(id="F-02", severity="MAJOR")]
        with open(findings_path, "w") as handle:
            json.dump(initial, handle)
        result = self.run_cli("history-append", findings_path, f"--history={history_path}",
                              f"--signature={SIG}", f"--capture={self.dir}/actual-0.png",
                              f"--diff={self.dir}/diff-0.png", "--run-id=dq-e2e",
                              "--designer-analysis", "--dom-inspection")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(os.path.exists(os.path.join(self.dir, "findings-0.json")))

        # Fixes applied → audit 1 observes nothing → reconcile marks fixed.
        empty_obs = os.path.join(self.dir, "obs-1.json")
        with open(empty_obs, "w") as handle:
            json.dump([], handle)
        result = self.run_cli("reconcile", findings_path, empty_obs, "--iteration=1", f"--at={TS2}")
        self.assertEqual(result.returncode, 0)
        with open(findings_path, "w") as handle:
            handle.write(result.stdout)

        # Append iteration 1 with the new signature.
        result = self.run_cli("history-append", findings_path, f"--history={history_path}",
                              f"--signature={SIG2}", f"--capture={self.dir}/actual-1.png",
                              f"--diff={self.dir}/diff-1.png",
                              "--designer-analysis", "--dom-inspection")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

        # Gate: PASSED bound to the current signature.
        result = self.run_cli("gate", findings_path, f"--iterations={history_path}",
                              f"--signature={SIG2}")
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual(json.loads(result.stdout)["verdict"], "PASSED")

    def test_gate_cli_blocks_without_history(self):
        path = os.path.join(self.dir, "findings.json")
        with open(path, "w") as handle:
            json.dump([finding(status="fixed", fixedAt=TS)], handle)
        result = self.run_cli("gate", path)
        self.assertEqual(result.returncode, 3)
        self.assertEqual(json.loads(result.stdout)["verdict"], "BLOCKED")

    def test_gate_cli_stale_signature_exit_3(self):
        history = self.history([{"findings": [finding()]}, {"findings": [], "signature": SIG2}])
        path = os.path.join(self.dir, "history.json")
        findings_path = os.path.join(self.dir, "findings.json")
        with open(path, "w") as handle:
            json.dump(history, handle)
        with open(findings_path, "w") as handle:
            json.dump([], handle)
        result = self.run_cli("gate", findings_path, f"--iterations={path}",
                              f"--signature={SIG2}x")
        self.assertEqual(result.returncode, 3)

    def test_gate_cli_rejects_invalid_findings(self):
        path = os.path.join(self.dir, "findings.json")
        with open(path, "w") as handle:
            json.dump([{"id": "F-01"}], handle)
        result = self.run_cli("gate", path)
        self.assertEqual(result.returncode, 1)
        self.assertIn("INVALID", result.stdout)

    def test_history_append_requires_signature(self):
        path = os.path.join(self.dir, "findings.json")
        with open(path, "w") as handle:
            json.dump([], handle)
        result = self.run_cli("history-append", path, f"--history={self.dir}/h.json",
                              "--run-id=dq-x")
        self.assertEqual(result.returncode, 2)

    def test_history_append_full_without_analysis_flags_fails(self):
        # R6 pin: a "full" audit without Designer/DOM flags is invalid.
        path = os.path.join(self.dir, "findings.json")
        capture = os.path.join(self.dir, "actual-0.png")
        diff = os.path.join(self.dir, "diff-0.png")
        for name in (path, capture, diff):
            with open(name, "w") as handle:
                handle.write("[]" if name == path else "x")
        result = self.run_cli("history-append", path, f"--history={self.dir}/h.json",
                              f"--signature={SIG}", f"--capture={capture}", f"--diff={diff}",
                              "--run-id=dq-noflags")
        self.assertEqual(result.returncode, 1)
        self.assertIn("INVALID", result.stdout)

    def test_history_append_requires_existing_evidence(self):
        # R3 pin: evidence paths must exist on disk (fail-closed).
        path = os.path.join(self.dir, "findings.json")
        with open(path, "w") as handle:
            json.dump([], handle)
        result = self.run_cli("history-append", path, f"--history={self.dir}/h.json",
                              f"--signature={SIG}", "--capture=/nonexistent/a.png",
                              "--diff=/nonexistent/d.png", "--run-id=dq-ghost")
        self.assertEqual(result.returncode, 2)
        self.assertIn("not found", result.stdout + result.stderr)

    def test_history_append_never_overwrites_snapshot(self):
        # R4 pin: a snapshot already on disk at the next index (crash orphan
        # from a partial append) is never silently overwritten.
        path = os.path.join(self.dir, "findings.json")
        history_path = os.path.join(self.dir, "history.json")
        capture = os.path.join(self.dir, "actual-0.png")
        diff = os.path.join(self.dir, "diff-0.png")
        for name, content in ((path, "[]"), (capture, "x"), (diff, "x")):
            with open(name, "w") as handle:
                handle.write(content)
        # Simulate the crash orphan: the snapshot exists, the history doesn't.
        with open(os.path.join(self.dir, "findings-0.json"), "w") as handle:
            handle.write("[]")
        result = self.run_cli("history-append", path, f"--history={history_path}",
                              f"--signature={SIG}", f"--capture={capture}", f"--diff={diff}",
                              "--run-id=dq-twice", "--designer-analysis", "--dom-inspection")
        self.assertEqual(result.returncode, 1)
        self.assertIn("refusing to overwrite", result.stdout + result.stderr)

    def test_history_append_persists_notes(self):
        # R7: the reconcile audit trail is persisted in the iteration.
        path = os.path.join(self.dir, "findings.json")
        history_path = os.path.join(self.dir, "history.json")
        capture = os.path.join(self.dir, "actual-0.png")
        diff = os.path.join(self.dir, "diff-0.png")
        for name, content in ((path, "[]"), (capture, "x"), (diff, "x")):
            with open(name, "w") as handle:
                handle.write(content)
        result = self.run_cli("history-append", path, f"--history={history_path}",
                              f"--signature={SIG}", f"--capture={capture}", f"--diff={diff}",
                              "--run-id=dq-notes", "--designer-analysis", "--dom-inspection",
                              "--notes=F-01 fixed confirmed by audit 1")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        with open(history_path) as handle:
            history = json.load(handle)
        self.assertEqual(history["iterations"][0]["notes"], "F-01 fixed confirmed by audit 1")

    def test_gate_corrupt_snapshot_exit_2_not_pass(self):
        # R6 pin: a corrupt snapshot is an input error (exit 2), never a pass.
        history = self.history([{"findings": []}])
        history_path = os.path.join(self.dir, "history.json")
        with open(history_path, "w") as handle:
            json.dump(history, handle)
        with open(history["iterations"][0]["findingsPath"], "w") as handle:
            handle.write("{corrupt")
        findings_path = os.path.join(self.dir, "findings.json")
        with open(findings_path, "w") as handle:
            json.dump([], handle)
        result = self.run_cli("gate", findings_path, f"--iterations={history_path}",
                              f"--signature={SIG}")
        self.assertEqual(result.returncode, 2)

    def test_history_append_writes_snapshot(self):
        path = os.path.join(self.dir, "findings.json")
        history_path = os.path.join(self.dir, "history.json")
        capture = os.path.join(self.dir, "a.png")
        diff = os.path.join(self.dir, "d.png")
        for name, content in ((path, json.dumps([finding()])), (capture, "x"), (diff, "x")):
            with open(name, "w") as handle:
                handle.write(content)
        result = self.run_cli("history-append", path, f"--history={history_path}",
                              f"--signature={SIG}", f"--capture={capture}",
                              f"--diff={diff}", "--run-id=dq-snap",
                              "--designer-analysis", "--dom-inspection")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        with open(os.path.join(self.dir, "findings-0.json")) as handle:
            snapshot = json.load(handle)
        self.assertEqual(snapshot[0]["id"], "F-01")

    def test_report_cli(self):
        contract_path = os.path.join(self.dir, "contract.json")
        findings_path = os.path.join(self.dir, "findings.json")
        history_path = os.path.join(self.dir, "history.json")
        summary_path = os.path.join(self.dir, "summary.json")
        findings = [finding(id="F-01", status="fixed", fixedAt=TS, confirmedIn=1)]
        open_iter = [dict(f, status="open", fixedAt=None, confirmedIn=None) for f in findings]
        for path, data in ((contract_path, valid_contract()),
                           (findings_path, findings),
                           (history_path, self.history([
                               {"findings": open_iter, "signature": SIG},
                               {"findings": findings, "signature": SIG,
                                "criteria": ["c1", "c2"]}]))):
            with open(path, "w") as handle:
                json.dump(data, handle)
        with open(summary_path, "w") as handle:
            json.dump({"processStatus": "ok", "tests": "passed", "signature": SIG,
                       "contract": "contract.json", "findings": "findings.json",
                       "history": "history.json", "componentsChecked": 3,
                       "application": "http://localhost:4200",
                       "captures": {"reference": "reference.png", "actual": "actual.png",
                                    "diff": "diff.png"}}, handle)
        result = self.run_cli("report", summary_path)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("DESIGN QA — PASSED", result.stdout)
        self.assertIn("PROVEN", result.stdout)


class TestTaskWorkflowCompatibility(unittest.TestCase):
    """Spec scenario 13: additive evolution, v1 states stay valid."""

    def test_state_v1_design_contract_fields_untouched(self):
        # task-workflow stores the designQa summary in qaResults (type "design");
        # nothing in dq v2 changes the task-workflow state schema.
        from_path = os.path.join(os.path.dirname(__file__), "..", "..", "task-workflow")
        sys.path.insert(0, from_path)
        try:
            import tw_state  # noqa: F401
        finally:
            sys.path.remove(from_path)
        # Additive optional fields only — tw_state.validate_state ignores unknown keys.
        state = {
            "schemaVersion": 1, "workflowId": "tw-demo--12345678",
            "taskUrls": [{"source": "gitlab", "url": "https://gitlab.example.com/g/i/-/issues/1"}],
            "repository": "/tmp/repo", "baseBranch": "main", "baseCommit": "abc",
            "featureBranch": "feat/x", "worktreePath": "/tmp/repo.worktrees/feat-x",
            "currentPhase": 5,
            "phaseStatuses": {str(n): {"status": "PASSED"} for n in range(1, 5)},
            "createdAt": TS, "updatedAt": TS,
            "designContract": "~/.config/opencode/design-qa/dq-x/contract.json",
            "qaResults": [{"type": "design", "status": "passed",
                           "convergence": {"iterations": 3, "finalAudit": "full"}}],
        }
        self.assertEqual(tw_state.validate_state(state), [])

    def test_history_run_id_accepts_tw_prefix(self):
        harness = TestGate("test_converged_clean_run_passes")
        harness.setUp()
        history = harness.history([{"findings": []}], run_id="tw-demo--12345678")
        self.assertEqual(dq_contract.validate_history(history), [])


if __name__ == "__main__":
    unittest.main()
