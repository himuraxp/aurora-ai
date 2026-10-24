"""M7 skill adapter — branch skills behind the Execution Graph Core.

RFC §11 M7 + PO delegated GO (2026-10-24): the existing skills stay THE
REFERENCE and are NEVER modified by this module — the Core orchestrates
work shaped like skill tasks BEHIND an adapter, progressively and
reversibly (the Core is purely additive, no existing entry point changes).

SHADOW-READ-FIRST contract (PO NO-GO on real external writes):
- every node is read-only: the adapter FORCES read: permissions and
  REFUSES any write effectPolicy (fail-closed at the adapter level, on
  top of the contracts' I9 rules);
- effects go through the sandbox dispatcher (journalized §7.2, zero real
  emission — see pilot.SandboxEffectDispatcher);
- process tasks run whitelisted-shaped READ-ONLY commands declared by the
  caller: the adapter executes what it is given and journals the exit
  code as evidence — the caller owns the read-only discipline, the
  adapter owns the no-write guarantee.

stdlib only — Python 3.9+.
"""
from __future__ import annotations

import subprocess
from typing import Any, Callable, Dict, List, Optional

from .contracts import validate_graph_definition
from .pilot import SandboxEffectDispatcher, collect_metrics
from .scheduler import GraphScheduler

READ_PERMISSIONS = ["read:fs", "read:repo"]
PROCESS_TIMEOUT_SECONDS = 120


class SkillSpecError(ValueError):
    """A task specification violates the M7 adapter contract."""


def build_graph_from_specs(graph_id: str, specs: List[Dict[str, Any]]) -> dict:
    """Task specs → a conforming GraphDefinition (shadow-read-first).

    Each spec: {id, kind: process|analysis, deps?, command? (process),
    timeoutSeconds?}. The adapter:
    - forces read-only permissions on EVERY node (no write: — the PO
      NO-GO is enforced here, not negotiated);
    - REFUSES any effectPolicy (a write effect is out of M7 scope — the
      sandbox journalizes nothing for read-only nodes anyway);
    - maps kind: process → tool node (the command runs as evidence), 
      analysis → agent node (I9: an agent never carries write:).
    """
    node_ids = [str(spec.get("id", "")) for spec in specs]
    if any(not node_id for node_id in node_ids):
        raise SkillSpecError("every task spec needs a non-empty id")
    if len(set(node_ids)) != len(node_ids):
        raise SkillSpecError(f"duplicated task ids: {node_ids}")
    known = set(node_ids)
    nodes: List[dict] = []
    for spec in specs:
        node_id = str(spec["id"])
        kind = str(spec.get("kind", "analysis"))
        if kind not in ("process", "analysis"):
            raise SkillSpecError(
                f"{node_id}: kind must be 'process' or 'analysis', got {kind!r}")
        deps = [str(dep) for dep in (spec.get("deps") or [])]
        unknown = [dep for dep in deps if dep not in known]
        if unknown:
            raise SkillSpecError(f"{node_id}: unknown deps {unknown}")
        if spec.get("effectPolicy"):
            # Fail-closed on the PO NO-GO (2026-10-24): no write effect is
            # expressible through the M7 shadow adapter.
            raise SkillSpecError(
                f"{node_id}: effectPolicy is refused by the M7 adapter "
                f"(shadow-read-first — real external writes are NO-GO)")
        if kind == "process" and not spec.get("command"):
            raise SkillSpecError(f"{node_id}: a process task needs a command")
        nodes.append({
            "schemaVersion": 1,
            "id": node_id,
            "type": "tool" if kind == "process" else "agent",
            "deps": deps,
            "inputs": {"command": spec.get("command")} if spec.get("command") else {},
            "outputSchema": {"type": "object"},
            "permissions": list(READ_PERMISSIONS),  # FORCED read-only
            "successCriteria": [],
            "evidencePolicy": {"required": ["exitCode"],
                               "freshness": {"inputFingerprint": False}},
            "failureBudgets": {"technical": int(spec.get("technicalBudget", 1)),
                               "quality": 1},
            "retryPolicy": {"maxAttempts": int(spec.get("technicalBudget", 1)) + 1,
                            "backoff": "none"},
            "timeoutSeconds": int(spec.get("timeoutSeconds", PROCESS_TIMEOUT_SECONDS)),
        })
    graph = {
        "schemaVersion": 1,
        "graphId": graph_id,
        "version": "1.0.0",
        "initialNodes": [node_id for node_id in node_ids
                         if not next(n for n in nodes if n["id"] == node_id)["deps"]],
        "nodes": nodes,
    }
    problems = validate_graph_definition(graph)
    if problems:
        raise SkillSpecError(f"adapted graph invalid: {'; '.join(problems)}")
    return graph


def build_executors(specs: List[Dict[str, Any]],
                    extra: Optional[Dict[str, Callable[[str, dict], dict]]] = None
                    ) -> Dict[str, Callable[[str, dict], dict]]:
    """Executors per spec. process → subprocess (read-only command, the
    exit code IS the evidence); analysis → caller-provided callable or a
    stub completing with an explicit 'static analysis' output."""
    executors: Dict[str, Callable[[str, dict], dict]] = {}
    for spec in specs:
        node_id = str(spec["id"])
        if spec.get("kind") == "process":
            command = [str(part) for part in spec["command"]]
            timeout = int(spec.get("timeoutSeconds", PROCESS_TIMEOUT_SECONDS))

            def process_executor(_node_id: str, _node: dict,
                                 _command=command, _timeout=timeout) -> dict:
                try:
                    completed = subprocess.run(
                        _command, capture_output=True, text=True, timeout=_timeout)
                except subprocess.TimeoutExpired as error:
                    failure = RuntimeError(
                        f"command timed out after {_timeout}s: {' '.join(_command)}")
                    failure.failureClass = "technical"  # type: ignore[attr-defined]
                    raise failure from error
                if completed.returncode != 0:
                    failure = RuntimeError(
                        f"command failed ({completed.returncode}): "
                        f"{completed.stderr.strip()[:200]}")
                    failure.failureClass = "technical"  # type: ignore[attr-defined]
                    raise failure
                return {"output": {"stdout": completed.stdout[-2000:]},
                        "evidences": [{"evidenceId": f"ev-{_node_id}",
                                       "kind": "technical",
                                       "exitCode": 0,
                                       "artifactRef": f"stdout:{_node_id}"}],
                        "artifactRefs": []}

            executors[node_id] = process_executor
        else:
            override = (extra or {}).get(node_id)
            if override is not None:
                executors[node_id] = override
            else:
                def analysis_executor(node_id: str, _node: dict) -> dict:
                    return {"output": {"analysis": "static", "node": node_id},
                            "evidences": [{"evidenceId": f"ev-{node_id}",
                                           "kind": "technical", "exitCode": 0}],
                            "artifactRefs": []}
                executors[node_id] = analysis_executor
    return executors


def run_skill_graph(graph_id: str, specs: List[Dict[str, Any]], run_dir: str,
                    lock_path: str,
                    extra_executors: Optional[Dict[str, Callable[[str, dict], dict]]] = None
                    ) -> dict:
    """Build the graph from the task specs and run it in SHADOW mode
    (sandbox dispatcher, zero real emission). Returns the shadow result in
    the same shape as the M5 pilot."""
    graph = build_graph_from_specs(graph_id, specs)
    dispatcher = SandboxEffectDispatcher()
    scheduler = GraphScheduler(graph, run_dir, lock_path,
                               session="m7-skill-adapter",
                               dispatcher=dispatcher,
                               clock=_millisecond_clock)
    scheduler.start()
    try:
        executors = build_executors(specs, extra_executors)
        executor = lambda node_id, node: executors[node_id](node_id, node)  # noqa: E731
        for _pass in range(4):
            if not scheduler.run(executor):
                break
        metrics = collect_metrics(scheduler, dispatcher)
    finally:
        scheduler.release_lock()
    return {"graphId": graph_id, "runId": scheduler.run_id, "metrics": metrics}


def _millisecond_clock() -> str:
    import datetime
    return datetime.datetime.now(datetime.timezone.utc).isoformat(
        timespec="milliseconds")
