"""TransitionEngine of the Execution Graph Core (RFC §3, invariants I1-I9).

Pure transition logic for NodeExecution states — extracted from the
task-workflow state contract (skills/task-workflow/tw_state.py, mark_phase /
invalidate_phase / evidence_guard) and generalized from the phase level to
the node level. stdlib only. The engine VALIDATES and MUTATES an in-memory
run state; the journal/projection commit belongs to the persistence layer
(persistence.py) and the orchestration to the scheduler (scheduler.py).

Key differences with tw_state.py (deliberate, RFC §3.1):
- `completed` is terminal — invalidation goes through the dedicated journaled
  operation invalidate_node (Écart A), not through a normal transition;
- `blocked → running` is legal under full deterministic guards (Écart B);
- the invalidation exception LIVES in the transition predicate (invariant I1),
  not in a table comment (review technique F1).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from .contracts import NODE_STATUSES

# RFC §3.1 — the closed transition table. completed/cancelled are terminal.
NODE_TRANSITIONS: Dict[str, set] = {
    "pending": {"running", "blocked", "cancelled"},
    "running": {"completed", "failed", "blocked", "cancelled"},
    "blocked": {"running", "pending", "cancelled"},
    "failed": {"pending", "cancelled"},
    "completed": set(),  # only invalidate_node may move out of completed (I5/Écart A)
    "cancelled": set(),
}


class IllegalTransition(ValueError):
    """Raised for any evolution outside the legal table (invariant I1)."""


class StaleCompletion(IllegalTransition):
    """A completion whose ancestor was invalidated since the node started
    (invariant I5, review technique F3) — rejected at commit."""


class StaleGeneration(IllegalTransition):
    """A write whose generationToken is not the current lock owner's
    generation (fencing, RFC §4.4) — rejected by the engine."""


def node_status(run_state: Dict[str, Any], node_id: str) -> str:
    """Current status of a node execution (defaults to 'pending')."""
    executions = run_state.get("nodeExecutions") or {}
    entry = executions.get(node_id)
    if not isinstance(entry, dict):
        return "pending"
    return str(entry.get("status", "pending"))


def _execution_of(run_state: Dict[str, Any], node_id: str) -> Dict[str, Any]:
    executions = run_state.setdefault("nodeExecutions", {})
    entry = executions.setdefault(node_id, {
        "runId": run_state.get("runId", ""),
        "nodeId": node_id,
        "attempt": 1,
        "status": "pending",
        "failureCounts": {"technical": 0, "quality": 0,
                          "invalidEvidence": 0, "permission": 0},
    })
    if "failureCounts" not in entry:
        entry["failureCounts"] = {"technical": 0, "quality": 0,
                                  "invalidEvidence": 0, "permission": 0}
    return entry


def mark_transition(run_state: Dict[str, Any], node_id: str, to: str, *,
                    attempt: int = 1, timestamp: str = "",
                    ancestors: Optional[List[str]] = None) -> Dict[str, Any]:
    """Apply a legal status transition and return the resulting execution entry.

    Raises IllegalTransition for any evolution outside the table (I1) and
    StaleCompletion when a `completed` commit fails the ancestor re-check
    (I5/F3): `ancestors` carries the node's transitive upstream ids and
    `run_state["invalidations"]` maps ancestor ids to their invalidation
    timestamps.
    """
    if to not in NODE_STATUSES:
        raise IllegalTransition(f"unknown node status: {to}")
    entry = _execution_of(run_state, node_id)
    current = str(entry.get("status", "pending"))
    if to not in NODE_TRANSITIONS[current]:
        raise IllegalTransition(f"illegal transition node {node_id}: {current} -> {to}")
    if to == "completed":
        invalidations = run_state.get("invalidations") or {}
        started_at = str(entry.get("startedAt") or "")
        for ancestor in ancestors or []:
            invalidated_at = invalidations.get(ancestor)
            if invalidated_at and (not started_at or str(invalidated_at) > started_at):
                raise StaleCompletion(
                    f"ancestor {ancestor} was invalidated at {invalidated_at} "
                    f"(node started at {started_at}) — completion rejected (I5/F3)")
    if to == "running":
        entry["startedAt"] = timestamp or entry.get("startedAt") or ""
    if to in ("completed", "failed", "cancelled"):
        entry["completedAt"] = timestamp or ""
    entry["status"] = to
    entry["attempt"] = attempt
    return entry


def count_failure(run_state: Dict[str, Any], node_id: str, failure_class: str) -> None:
    """Increment the failure counter of ONE class (invariant I8 — never merged)."""
    entry = _execution_of(run_state, node_id)
    counts = entry["failureCounts"]
    if failure_class not in counts:
        raise ValueError(f"unknown failure class: {failure_class}")
    counts[failure_class] += 1


def invalidate_node(run_state: Dict[str, Any], node_id: str, reason: str, *,
                    fingerprint_divergence: Optional[str] = None,
                    timestamp: str = "",
                    descendants: Optional[List[str]] = None) -> Dict[str, Any]:
    """Dedicated journaled invalidation operation (invariant I5, Écart A).

    - node `completed` → back to `pending`; node `running` → `cancelled`
      (review technique F3 — its evidence would be stale anyway);
    - the node's recorded invalidation timestamp enables the I5/F3 completion
      re-check for any downstream node still running;
    - transitive scope is applied by the caller over `descendants` (the engine
      handles one node per call — the scheduler owns the graph);
    - evidences are marked invalid by the EvidenceStore (never deleted);
    - NEVER cancels or replays an already-performed external effect (I5).
    """
    current = node_status(run_state, node_id)
    if current == "completed":
        target = "pending"
    elif current == "running":
        target = "cancelled"
    else:
        # Nothing to invalidate: the node holds no consumable result.
        return {"nodeId": node_id, "from": current, "to": current,
                "skipped": True, "descendants": list(descendants or [])}
    entry = _execution_of(run_state, node_id)
    entry["status"] = target
    if target == "pending":
        # Back to pending = a NEW attempt will be required.
        entry["attempt"] = int(entry.get("attempt", 1)) + 1
        entry["startedAt"] = None
        entry["completedAt"] = None
    invalidations = run_state.setdefault("invalidations", {})
    invalidations[node_id] = timestamp or invalidations.get(node_id) or ""
    for descendant in descendants or []:
        if descendant == node_id:
            continue
        desc_status = node_status(run_state, descendant)
        if desc_status == "completed":
            _execution_of(run_state, descendant)["status"] = "pending"
        elif desc_status == "running":
            _execution_of(run_state, descendant)["status"] = "cancelled"
        invalidations[descendant] = invalidations[node_id]
    return {"nodeId": node_id, "from": current, "to": target, "skipped": False,
            "reason": reason,
            "fingerprintDivergence": fingerprint_divergence,
            "descendants": list(descendants or [])}


def replay_records(records: List[Dict[str, Any]], known_generations: List[str]) -> Dict[str, Any]:
    """Idempotent journal replay (I3, §5): records already projected (by
    transitionId) are skipped; records whose generationToken does not belong
    to the known generation chain are RAISED as rejected — never replayed as
    transitions (fencing retroactif, review technique F6)."""
    seen: set = set()
    applied: List[Dict[str, Any]] = []
    rejected: List[Dict[str, Any]] = []
    for record in records:
        transition_id = str(record.get("transitionId", ""))
        if transition_id in seen:
            continue  # idempotent replay by transitionId
        if str(record.get("generationToken")) not in set(known_generations):
            rejected.append(record)
            continue
        seen.add(transition_id)
        applied.append(record)
    return {"applied": applied, "rejected": rejected}
