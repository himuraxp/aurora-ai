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

Stale-completion detection (I5/F3) uses JOURNAL REVISIONS (monotonic integer
indexes of journal records — review F-11), never wall-clock timestamps: an
invalidation recorded AFTER a node started is detected even within the same
second.
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
    """A write whose generationToken is not in the known generation chain
    (fencing, RFC §4.4) — rejected by the engine."""


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
                    attempt: int = 1,
                    started_revision: Optional[int] = None,
                    invalidation_revisions: Optional[Dict[str, int]] = None,
                    ancestors: Optional[List[str]] = None) -> Dict[str, Any]:
    """Apply a legal status transition and return the resulting execution entry.

    Raises IllegalTransition for any evolution outside the table (I1) and
    StaleCompletion when a `completed` commit fails the ancestor re-check
    (I5/F3): `invalidation_revisions` maps ancestor node ids to the JOURNAL
    REVISION of their invalidation record; `started_revision` is the journal
    revision of this node's pending→running record.
    """
    if to not in NODE_STATUSES:
        raise IllegalTransition(f"unknown node status: {to}")
    entry = _execution_of(run_state, node_id)
    current = str(entry.get("status", "pending"))
    if to not in NODE_TRANSITIONS[current]:
        raise IllegalTransition(f"illegal transition node {node_id}: {current} -> {to}")
    if to == "completed":
        revisions = invalidation_revisions or {}
        started = entry.get("startedRevision")
        for ancestor in ancestors or []:
            invalidated_revision = revisions.get(ancestor)
            if invalidated_revision is not None and (
                    started is None or int(invalidated_revision) > int(started)):
                raise StaleCompletion(
                    f"ancestor {ancestor} was invalidated at journal revision "
                    f"{invalidated_revision} (node started at revision {started}) "
                    f"— completion rejected (I5/F3)")
    if to == "running" and started_revision is not None:
        entry["startedRevision"] = int(started_revision)
    if to in ("completed", "failed", "cancelled"):
        entry["completedRevision"] = int(started_revision or 0)
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


def budget_exhausted(node: Dict[str, Any], run_state: Dict[str, Any],
                     node_id: str, failure_class: str) -> bool:
    """I8 (review F-07): compare the class counter to its budget.
    invalidEvidence/permission have NO budget — always 'exhausted' (blocked)."""
    if failure_class in ("invalidEvidence", "permission"):
        return True
    budgets = node.get("failureBudgets") or {}
    counts = ((run_state.get("nodeExecutions") or {}).get(node_id) or {}) \
        .get("failureCounts") or {}
    return counts.get(failure_class, 0) >= int(budgets.get(failure_class, 0))


def invalidate_node(run_state: Dict[str, Any], node_id: str, reason: str, *,
                    invalidation_revision: Optional[int] = None,
                    descendants: Optional[List[str]] = None) -> Dict[str, Any]:
    """Dedicated journaled invalidation operation (invariant I5, Écart A).

    - node `completed` → back to `pending`; node `running` → `cancelled`
      (review technique F3); node `failed`/`blocked` → `pending` (review
      F-12 — the full transitive scope is re-filed, RFC I5);
    - the node's invalidation JOURNAL REVISION enables the I5/F3 completion
      re-check for any downstream node still running;
    - transitive scope is applied by the caller over `descendants` (the engine
      handles one node per call — the scheduler owns the graph);
    - evidences are marked invalid by the EvidenceStore (never deleted);
    - NEVER cancels or replays an already-performed external effect (I5).
    """
    current = node_status(run_state, node_id)
    if current == "running":
        target = "cancelled"
    elif current == "completed":
        target = "pending"
    elif current in ("failed", "blocked"):
        target = "pending"
    else:
        # Nothing to invalidate: the node holds no consumable result.
        return {"nodeId": node_id, "from": current, "to": current,
                "skipped": True, "descendants": list(descendants or [])}
    entry = _execution_of(run_state, node_id)
    entry["status"] = target
    if target == "pending":
        # Back to pending = a NEW attempt will be required.
        entry["attempt"] = int(entry.get("attempt", 1)) + 1
        entry.pop("startedRevision", None)
        entry.pop("completedRevision", None)
    revision = invalidation_revision if invalidation_revision is not None else 0
    invalidations = run_state.setdefault("invalidations", {})
    invalidations[node_id] = revision
    for descendant in descendants or []:
        if descendant == node_id:
            continue
        desc_status = node_status(run_state, descendant)
        if desc_status in ("completed", "failed", "blocked"):
            _execution_of(run_state, descendant)["status"] = "pending"
        elif desc_status == "running":
            _execution_of(run_state, descendant)["status"] = "cancelled"
        invalidations[descendant] = revision
    return {"nodeId": node_id, "from": current, "to": target, "skipped": False,
            "reason": reason, "descendants": list(descendants or [])}


def repin_orphan_running(run_state: Dict[str, Any], node_id: str) -> Dict[str, Any]:
    """RFC §5.3 (review F-03) — RECOVERY protocol, not a normal transition
    (I1 exception owned by the resume path): an orphan `running` (its owner
    lost the lock — kernel guarantee) is re-pinned to `pending`. The
    scheduler journals it as kind=invalidation; the projection re-applies
    payload.to. A running with an unconcluded effect must go through
    `blocked` instead (a normal, legal transition)."""
    entry = _execution_of(run_state, node_id)
    current = str(entry.get("status", "pending"))
    if current != "running":
        return {"nodeId": node_id, "from": current, "skipped": True}
    entry["status"] = "pending"
    entry["attempt"] = int(entry.get("attempt", 1)) + 1
    entry.pop("startedRevision", None)
    return {"nodeId": node_id, "from": "running", "to": "pending",
            "skipped": False}


def replay_records(records: List[Dict[str, Any]], known_generations: List[str],
                   run_id: Optional[str] = None) -> Dict[str, Any]:
    """Idempotent journal replay (I3, §5): records already projected (by
    transitionId) are skipped; records whose generationToken is not in the
    known generation chain are RAISED as rejected — never replayed as
    transitions (fencing rétroactif, review technique F6). Records of ANOTHER
    run are filtered out (runId immutability — review F-14)."""
    seen: set = set()
    applied: List[Dict[str, Any]] = []
    rejected: List[Dict[str, Any]] = []
    generations = set(known_generations)
    for record in records:
        if run_id is not None and str(record.get("runId", "")) != run_id:
            continue  # another run's records never leak into this projection
        transition_id = str(record.get("transitionId", ""))
        if transition_id in seen:
            continue  # idempotent replay by transitionId
        if str(record.get("generationToken")) not in generations:
            rejected.append(record)
            continue
        seen.add(transition_id)
        applied.append(record)
    return {"applied": applied, "rejected": rejected}
