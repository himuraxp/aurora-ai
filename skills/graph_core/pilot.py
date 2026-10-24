"""M5 pilot — MR analysis in shadow-run (RFC §11 M5, review F-12).

The pilot exercises the Execution Graph Core on a REAL workflow shape
(merge-request analysis) while staying in SHADOW of the current system:

- the analysis steps are READ-ONLY (gh pr diff is a read, not an effect);
- the single WRITE step (posting the analysis comment on the MR) goes
  through the journaled effect protocol (§7.2) with a SANDBOX dispatcher —
  the EffectRecords are journalized (prepared → dispatched → confirmed)
  but NO external call is ever emitted (idempotencyKey simulated, review
  F-12): the metrics therefore describe the simulation;
- the current skills stay untouched — this module adds nothing to their
  behavior (shadow-run only).

Metrics (comparison axis, RFC §11 M5): per-node status/duration/attempts,
global success rate, effects by classification and phase, human
interventions (0 expected in sandbox), total duration.

stdlib only — Python 3.9+.
"""
from __future__ import annotations

import datetime
import json
import re
import subprocess
from typing import Any, Callable, Dict, List, Optional

from .contracts import validate_graph_definition
from .scheduler import EffectDispatcher, GraphScheduler

CONVENTIONAL_COMMIT_RE = re.compile(
    r"^(feat|fix|docs|style|refactor|perf|test|build|ci|chore|revert)"
    r"(\([a-z0-9./_-]+\))?!?: .+")


class SandboxEffectDispatcher(EffectDispatcher):
    """Shadow effect emitter (RFC §11 M5): journalizes through the core's
    effect protocol but NEVER emits — the metrics describe the simulation."""

    def __init__(self):
        self.simulated: List[Dict[str, Any]] = []

    def dispatch(self, node_id: str, node: Dict[str, Any],
                 idempotency_key: str) -> Dict[str, Any]:
        self.simulated.append({"nodeId": node_id, "idempotencyKey": idempotency_key,
                               "sandbox": True})
        return {"outcome": "confirmed", "sandbox": True,
                "evidenceRef": f"sandbox-{node_id}"}


def build_mr_analysis_graph(pr_number: int, repo: str = "himuraxp/aurora-ai") -> dict:
    """The pilot's GraphDefinition: 4 read-only analysis steps converging on
    a report node, then ONE write node (sandboxed comment posting)."""
    def node(node_id: str, node_type: str, deps: list, **overrides) -> dict:
        base = {
            "schemaVersion": 1, "id": node_id, "type": node_type, "deps": deps,
            "inputs": {}, "outputSchema": {"type": "object"},
            "permissions": ["read:repo", "read:fs"],
            "successCriteria": [],
            "evidencePolicy": {"required": ["exitCode"],
                               "freshness": {"inputFingerprint": False}},
            "failureBudgets": {"technical": 2, "quality": 1},
            "retryPolicy": {"maxAttempts": 2, "backoff": "none"},
            "timeoutSeconds": 120,
            # effectPolicy omitted on read nodes (legal since R-05).
        }
        base.update(overrides)
        return base

    return {
        "schemaVersion": 1,
        "graphId": f"mr-analysis-{repo}-{pr_number}",
        "version": "1.0.0",
        "initialNodes": ["fetch-diff"],
        "nodes": [
            node("fetch-diff", "tool", []),
            node("analyze-diff", "agent", ["fetch-diff"]),
            node("check-conventions", "tool", ["fetch-diff"]),
            node("build-report", "agent", ["analyze-diff", "check-conventions"]),
            node("post-comment", "tool", ["build-report"],
                 permissions=["read:repo", "write:gitlab-comment"],
                 effectPolicy={
                     "mode": "write",
                     "idempotencyKey": f"mr-comment-{repo}-{pr_number}-v1",
                     "reconciliation": "getBeforePost",
                     "onUncertainOutcome": "block",
                 }),
        ],
    }


def default_executors(pr_number: int, repo: str = "himuraxp/aurora-ai"
                      ) -> Dict[str, Callable[[str, dict], dict]]:
    """Read-only executors backed by the gh CLI (READS only — the write
    node's executor PREPARES the comment payload but never emits: the
    emission belongs to the dispatcher, which is the sandbox here)."""

    def fetch_diff(node_id: str, node: dict) -> dict:
        view = subprocess.run(
            ["gh", "pr", "view", str(pr_number), "--repo", repo,
             "--json", "title,author,additions,deletions,changedFiles,state"],
            capture_output=True, text=True, timeout=60)
        if view.returncode != 0:
            error = RuntimeError(f"gh pr view failed: {view.stderr.strip()[:200]}")
            error.failureClass = "technical"  # type: ignore[attr-defined]
            raise error
        diff = subprocess.run(
            ["gh", "pr", "diff", str(pr_number), "--repo", repo],
            capture_output=True, text=True, timeout=60)
        if diff.returncode != 0:  # review R4-05 — never a lying exitCode 0
            error = RuntimeError(f"gh pr diff failed: {diff.stderr.strip()[:200]}")
            error.failureClass = "technical"  # type: ignore[attr-defined]
            raise error
        payload = json.loads(view.stdout)
        payload["diffBytes"] = len(diff.stdout.encode("utf-8"))
        payload["diffFiles"] = len(set(
            line[4:] for line in diff.stdout.splitlines()
            if line.startswith("+++ b/") and line[6:] != "/dev/null"))
        return {"output": payload,
                "evidences": [{"evidenceId": "ev-fetch", "kind": "technical",
                               "exitCode": 0}],
                "artifactRefs": []}

    def analyze_diff(node_id: str, node: dict) -> dict:
        # Static analysis of the fetched metadata (the LLM-grade analysis is
        # the CURRENT system's job — M5 measures the execution skeleton).
        return {"output": {"analysis": "static", "status": "ok"},
                "evidences": [{"evidenceId": "ev-analyze", "kind": "technical",
                               "exitCode": 0}],
                "artifactRefs": []}

    def check_conventions(node_id: str, node: dict) -> dict:
        view = subprocess.run(
            ["gh", "pr", "view", str(pr_number), "--repo", repo, "--json", "title"],
            capture_output=True, text=True, timeout=60)
        if view.returncode != 0:
            error = RuntimeError(f"gh pr view failed: {view.stderr.strip()[:200]}")
            error.failureClass = "technical"  # type: ignore[attr-defined]
            raise error
        title = str(json.loads(view.stdout).get("title", ""))
        conforms = bool(CONVENTIONAL_COMMIT_RE.match(title))
        return {"output": {"title": title, "conventionalCommit": conforms},
                "evidences": [{"evidenceId": "ev-conventions", "kind": "technical",
                               "exitCode": 0}],
                "artifactRefs": []}

    def build_report(node_id: str, node: dict) -> dict:
        return {"output": {"report": "built"},
                "evidences": [{"evidenceId": "ev-report", "kind": "technical",
                               "exitCode": 0}],
                "artifactRefs": []}

    def prepare_comment(node_id: str, node: dict) -> dict:
        # PREPARE only — the emission is the dispatcher's job (sandboxed).
        return {"output": {"comment": "prepared (sandbox)"},
                "evidences": [{"evidenceId": "ev-comment", "kind": "technical",
                               "exitCode": 0}],
                "artifactRefs": []}

    return {
        "fetch-diff": fetch_diff,
        "analyze-diff": analyze_diff,
        "check-conventions": check_conventions,
        "build-report": build_report,
        "post-comment": prepare_comment,
    }


def collect_metrics(scheduler: GraphScheduler,
                    dispatcher: SandboxEffectDispatcher) -> dict:
    """Comparison metrics from the journal + the projection (RFC §11 M5).

    Fidelity rules (review R4-03/R4-04): every GRAPH node is reported (never
    scheduled ones included as pending — the success rate is over the
    GRAPH, not over the touched nodes); `durationsSeconds` covers the LAST
    attempt per node; `wallClockSeconds` is the journal's first→last span."""
    records, problems = scheduler.log.read()
    per_node: Dict[str, dict] = {
        node_id: {"attempts": 0, "transitions": 0, "effects": 0,
                  "startedAt": None, "completedAt": None, "status": "pending",
                  "scheduled": False}
        for node_id in scheduler.nodes}
    for record in records:
        if record.get("kind") != "transition":
            continue
        if str(record.get("runId", "")) != scheduler.run_id:
            continue  # a foreign run's record — never counted (review R4-03)
        node_id = str(record.get("nodeId"))
        if node_id not in per_node:  # not a graph node — never counted
            continue
        entry = per_node[node_id]
        entry["transitions"] += 1
        to = str(record.get("to"))
        if to == "running":
            entry["attempts"] += 1
            entry["scheduled"] = True
            entry["startedAt"] = record.get("timestamp")  # last attempt (R4-04)
        if to in ("completed", "failed", "blocked", "cancelled"):
            entry["completedAt"] = record.get("timestamp")
        entry["status"] = to
        if record.get("from") == "failed" and to == "pending":
            entry["retried"] = True
    for record in records:
        if record.get("kind") == "effect":
            node_id = str(record.get("nodeId"))
            if node_id in per_node:
                per_node[node_id]["effects"] += 1
    state = scheduler._state()
    for node_id, execution in (state.get("nodeExecutions") or {}).items():
        if node_id in per_node:
            per_node[node_id]["status"] = execution.get("status")
    durations = {}
    for node_id, entry in per_node.items():
        if entry.get("startedAt") and entry.get("completedAt"):
            durations[node_id] = _duration_seconds(entry["startedAt"],
                                                   entry["completedAt"])
    statuses = [entry["status"] for entry in per_node.values()]
    completed = statuses.count("completed")
    total = len(per_node)
    effect_phases = [str((r.get("payload") or {}).get("effectPhase"))
                     for r in records if r.get("kind") == "effect"]
    timestamps = [str(r.get("timestamp")) for r in records if r.get("timestamp")]
    return {
        "mode": "shadow-run/sandbox",
        "nodes": {
            "total": total,  # every graph node (R4-03)
            "scheduled": sum(1 for e in per_node.values() if e["scheduled"]),
            "completed": completed,
            "failed": statuses.count("failed"),
            "blocked": statuses.count("blocked"),
            "successRate": round(completed / total, 3) if total else 0.0,
        },
        "perNode": per_node,
        "durationsSeconds": durations,  # last attempt per node (R4-04)
        "wallClockSeconds": (_duration_seconds(min(timestamps), max(timestamps))
                             if len(timestamps) >= 2 else 0.0),
        "retries": sum(1 for e in per_node.values() if e.get("retried")),
        "effects": {
            "records": len(effect_phases),
            "phases": effect_phases,
            "simulatedDispatches": len(dispatcher.simulated),
            "realEffectEmissions": 0,  # sandbox — always zero before the flip
        },
        "humanInterventions": sum(
            1 for r in records if r.get("kind") == "human-intervention"),
        "journalProblems": problems,
        "journalRecords": len(records),
    }


def _duration_seconds(start: str, end: str) -> float:
    def parse(ts: str) -> datetime.datetime:
        return datetime.datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    return round((parse(end) - parse(start)).total_seconds(), 3)


def _millisecond_clock() -> str:
    """Pilot clock (review R4-09): the default clock truncates to SECONDS —
    sub-second node durations would all read 0.0 and the comparison metrics
    would be blind. The pilot measures at MILLISECOND precision."""
    return datetime.datetime.now(datetime.timezone.utc).isoformat(
        timespec="milliseconds")


def run_shadow_pilot(pr_number: int, run_dir: str, lock_path: str,
                     repo: str = "himuraxp/aurora-ai",
                     executors: Optional[Dict[str, Callable[[str, dict], dict]]] = None
                     ) -> dict:
    """Run the MR-analysis graph in shadow mode and return the metrics."""
    graph = build_mr_analysis_graph(pr_number, repo)
    problems = validate_graph_definition(graph)
    if problems:
        raise ValueError(f"pilot graph invalid: {'; '.join(problems)}")
    dispatcher = SandboxEffectDispatcher()
    scheduler = GraphScheduler(graph, run_dir, lock_path,
                               session="m5-shadow-pilot",
                               dispatcher=dispatcher,
                               clock=_millisecond_clock)
    scheduler.start()
    try:
        executors = executors or default_executors(pr_number, repo)
        executor = lambda node_id, node: executors[node_id](node_id, node)  # noqa: E731
        # Bounded passes: failed-under-budget nodes are re-filed by the NEXT
        # pass (the topo loop does not revisit them in the same pass). The
        # loop stops when nothing runnable remains.
        for _pass in range(4):
            if not scheduler.run(executor):
                break
        metrics = collect_metrics(scheduler, dispatcher)
    finally:
        scheduler.release_lock()  # a crash in the run never keeps the lock
    return {"graphId": graph["graphId"], "runId": scheduler.run_id,
            "metrics": metrics, "output": scheduler._state()
            .get("nodeExecutions", {}).get("build-report", {}).get("outputArtifactRefs")}
