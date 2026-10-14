#!/usr/bin/env python3
"""Tests for the design-qa deterministic contract (fixtures only — no network,
no browser, no image processing). Python 3.9+, stdlib only."""
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

    def test_measured_vs_estimated_traced(self):
        # A screenshot reference cannot claim measured values — the flag is
        # what the report and the findings rely on; validator only enforces
        # its presence and type (documented, not enforced semantically here).
        reference = dict(valid_contract()["reference"], valuesAvailable=False, confidence="estimated")
        self.assertEqual(dq_contract.validate_contract(valid_contract(reference=reference)), [])


class TestFindingsValidation(unittest.TestCase):
    def test_valid_findings_pass(self):
        self.assertEqual(dq_contract.validate_findings([finding()]), [])

    def test_missing_required_key(self):
        entry = finding()
        del entry["expected"]
        problems = dq_contract.validate_findings([entry])
        self.assertTrue(any("expected" in p for p in problems))

    def test_evidence_required(self):
        # A correction or a waive must be backed by traceable evidence.
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

    def test_waived_requires_human_trace(self):
        problems = dq_contract.validate_findings(
            [finding(status="waived")])
        self.assertTrue(any("waivedBy" in p for p in problems))
        problems = dq_contract.validate_findings(
            [finding(status="waived", waivedBy="HUMAN")])
        self.assertTrue(any("waivedReason" in p for p in problems))
        problems = dq_contract.validate_findings(
            [finding(status="waived", waivedBy="HUMAN", waivedReason="PO accepts the delta, ticket XYZ")])
        self.assertEqual(problems, [])

    def test_fixed_requires_recheck_trace(self):
        problems = dq_contract.validate_findings([finding(status="fixed")])
        self.assertTrue(any("fixedAt" in p for p in problems))
        problems = dq_contract.validate_findings([finding(status="fixed", fixedAt=TS)])
        self.assertEqual(problems, [])


class TestGate(unittest.TestCase):
    def test_open_blocker_blocks(self):
        result = dq_contract.gate([finding()])
        self.assertEqual(result["verdict"], "BLOCKED")
        self.assertEqual(result["blocking"], ["F-01"])

    def test_open_major_blocks(self):
        result = dq_contract.gate([finding(id="F-02", severity="MAJOR")])
        self.assertEqual(result["verdict"], "BLOCKED")

    def test_minor_and_info_do_not_block(self):
        findings = [finding(id="F-03", severity="MINOR", category="spacing"),
                    finding(id="F-04", severity="INFO", category="data")]
        result = dq_contract.gate(findings)
        self.assertEqual(result["verdict"], "PASSED")
        self.assertEqual(result["remaining"]["MINOR"], 1)

    def test_waived_blocker_does_not_block(self):
        waived = finding(status="waived", waivedBy="HUMAN", waivedReason="PO decision")
        result = dq_contract.gate([waived])
        self.assertEqual(result["verdict"], "PASSED")

    def test_fixed_counts_as_applied(self):
        result = dq_contract.gate([finding(id="F-05", status="fixed", fixedAt=TS),
                                   finding(id="F-06", severity="MAJOR", status="fixed", fixedAt=TS)])
        self.assertEqual(result["verdict"], "PASSED")
        self.assertEqual(result["applied"], 2)

    def test_uncertain_major_still_blocks_and_is_flagged(self):
        # Fail-closed on the MR gate: an open MAJOR blocks even if uncertain —
        # confirmation must happen BEFORE deciding, not instead of blocking.
        uncertain = finding(id="F-07", severity="MAJOR", confidence="uncertain")
        result = dq_contract.gate([uncertain])
        self.assertEqual(result["verdict"], "BLOCKED")
        self.assertEqual(result["needsConfirmation"], ["F-07"])

    def test_unknown_status_counts_as_open_fail_closed(self):
        # R-06 defense in depth: gate() called directly on unvalidated data
        # can never under-block — an unrecognized status counts as open.
        typo = finding(id="F-10", status="OPEN")
        result = dq_contract.gate([typo])
        self.assertEqual(result["verdict"], "BLOCKED")

    def test_no_reference_skips(self):
        result = dq_contract.gate([finding()], reference_available=False)
        self.assertEqual(result["verdict"], "SKIPPED")


class TestReport(unittest.TestCase):
    def base_summary(self):
        return {
            "contract": "contract.json", "findings": "findings.json",
            "application": "http://localhost:4200/distribution",
            "captures": {"reference": "reference.png", "actual": "actual.png", "diff": "diff.png"},
            "iterations": 2, "tests": "passed", "componentsChecked": 12,
        }

    def render(self, findings, summary=None):
        return dq_contract.render_report(summary or self.base_summary(), valid_contract(), findings)

    def test_passed_report_format(self):
        findings = [finding(id="F-05", status="fixed", fixedAt=TS),
                    finding(id="F-08", severity="MINOR", category="spacing")]
        report = self.render(findings)
        self.assertIn("DESIGN QA — PASSED", report)
        # Totals count every detected finding; Corrections separates applied
        # from remaining (here: 1 fixed BLOCKER + 1 open MINOR → remaining 1).
        self.assertIn("BLOCKER: 1  MAJOR: 0  MINOR: 1  INFO: 0", report)
        self.assertIn("Applied: 1  Remaining: 1", report)
        self.assertIn("Iterations:", report)
        self.assertIn("  passed", report)
        self.assertIn("reference.png", report)

    def test_blocked_report_lists_blockers(self):
        report = self.render([finding()])
        self.assertIn("DESIGN QA — BLOCKED", report)
        self.assertIn("Blocking findings: F-01", report)

    def test_tests_failure_fails_the_run(self):
        summary = self.base_summary()
        summary["tests"] = "failed"
        report = self.render([finding(id="F-09", severity="MINOR", category="spacing")], summary)
        self.assertIn("DESIGN QA — FAILED", report)

    def test_skipped_report_never_hides_failed_tests(self):
        # R-02: a missing reference yields SKIPPED, but a functional test
        # failure must surface as FAILED in the final evidence, never hidden.
        contract = valid_contract(reference={"source": "image", "valuesAvailable": False})
        summary = self.base_summary()
        summary["tests"] = "failed"
        report = dq_contract.render_report(summary, contract, [])
        self.assertIn("DESIGN QA — FAILED", report)

    def test_waived_findings_are_not_reported_as_remaining(self):
        # R-01: Remaining derives from the gate (open findings only) — a
        # waived BLOCKER never appears as "Remaining: 1" on a PASSED report.
        findings = [finding(status="waived", waivedBy="HUMAN", waivedReason="PO decision, ticket XYZ")]
        report = self.render(findings)
        self.assertIn("DESIGN QA — PASSED", report)
        self.assertIn("Applied: 0  Remaining: 0", report)

    def test_process_failure_reported(self):
        summary = self.base_summary()
        summary["processStatus"] = "failed"
        summary["processReason"] = "application unreachable"
        report = dq_contract.render_report(summary, valid_contract(), [])
        self.assertIn("DESIGN QA — FAILED", report)
        self.assertIn("application unreachable", report)

    def test_no_reference_skips(self):
        contract = valid_contract(reference={"source": "image", "valuesAvailable": False})
        report = dq_contract.render_report(self.base_summary(), contract, [])
        self.assertIn("DESIGN QA — SKIPPED", report)


class TestCli(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.contract_path = os.path.join(self.tmp.name, "contract.json")
        self.findings_path = os.path.join(self.tmp.name, "findings.json")
        with open(self.contract_path, "w", encoding="utf-8") as handle:
            json.dump(valid_contract(), handle)
        with open(self.findings_path, "w", encoding="utf-8") as handle:
            json.dump([finding()], handle)

    def tearDown(self):
        self.tmp.cleanup()

    def _run(self, *args):
        script = os.path.join(os.path.dirname(__file__), "..", "dq_contract.py")
        return subprocess.run([sys.executable, script, *args], capture_output=True, text=True, check=False)

    def test_parse_figma_url_cli(self):
        result = self._run("parse-figma-url",
                           "https://www.figma.com/design/Kkfn3DQwE7rdTs1YPObRTd/X?node-id=1421-40648")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(json.loads(result.stdout)["nodeId"], "1421:40648")

    def test_validate_contract_cli(self):
        result = self._run("validate-contract", self.contract_path)
        self.assertEqual(result.returncode, 0)
        with open(self.contract_path, "w", encoding="utf-8") as handle:
            json.dump({"schemaVersion": 9}, handle)
        self.assertEqual(self._run("validate-contract", self.contract_path).returncode, 1)

    def test_gate_cli_blocks_on_open_blocker(self):
        result = self._run("gate", self.findings_path)
        # Exit 3 = BLOCKED (composable: 'gate f.json && create-mr' can never
        # pass a blocked gate in shell chaining).
        self.assertEqual(result.returncode, 3)
        self.assertEqual(json.loads(result.stdout)["verdict"], "BLOCKED")

    def test_gate_cli_rejects_invalid_findings(self):
        with open(self.findings_path, "w", encoding="utf-8") as handle:
            json.dump([{"id": "F-99"}], handle)
        self.assertEqual(self._run("gate", self.findings_path).returncode, 1)

    def test_gate_cli_no_reference(self):
        result = self._run("gate", self.findings_path, "--no-reference")
        self.assertEqual(json.loads(result.stdout)["verdict"], "SKIPPED")

    def test_report_cli(self):
        summary_path = os.path.join(self.tmp.name, "summary.json")
        with open(summary_path, "w", encoding="utf-8") as handle:
            json.dump({"contract": "contract.json", "findings": "findings.json",
                       "application": "http://localhost:4200/p", "iterations": 1,
                       "tests": "passed", "componentsChecked": 3}, handle)
        result = self._run("report", summary_path)
        self.assertEqual(result.returncode, 0)
        self.assertIn("DESIGN QA — BLOCKED", result.stdout)


if __name__ == "__main__":
    unittest.main()
