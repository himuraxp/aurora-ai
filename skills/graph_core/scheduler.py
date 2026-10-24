"""GraphScheduler of the Execution Graph Core (RFC §4, §5, §11 M3).

Minimal sequential scheduler for the JSON mono-executor pilot (RFC §0):
- topological execution order (Kahn), SEQUENTIAL (review technique F11 —
  concurrencyKey is reserved for M7+);
- continuous `flock` ownership per run (RFC §4.1): acquired before any
  scheduling decision, held for the whole orchestration session, released by
  the kernel on crash;
- generationToken stored IN the lock file (review technique F6) and verified
  at EVERY state write inside the same flock-protected critical section
  (fencing — TOCTOU closed, review PO itération 2);
- deterministic resume (RFC §5): journal reconciliation before anything else,
  completed-with-fresh-evidence nodes are skipped, stale evidence triggers
  the explicit transitive invalidation (I5).
"""
from __future__ import annotations

import fcntl
import json
import os
import uuid
from typing import Any, Callable, Dict, List, Optional

from .contracts import validate_graph_definition
from .persistence import EventLog, StateRepository, EvidenceStore
from .transition_engine import (
    StaleCompletion, StaleGeneration, invalidate_node, mark_transition,
    node_status,
)


class LockHeld(RuntimeError):
    """Another orchestrator owns the run lock (RFC §4.1, scenario S6)."""


class GraphScheduler:
    """Sequential executor of a GraphDefinition run under flock + fencing."""

    def __init__(self, graph: Dict[str, Any], run_dir: str, lock_path: str,
                 run_id: Optional[str] = None, session: str = "pilot"):
        problems = validate_graph_definition(graph)
        if problems:
            raise ValueError(f"invalid GraphDefinition: {'; '.join(problems)}")
        self.graph = graph
        self.nodes: Dict[str, dict] = {n["id"]: n for n in graph["nodes"]}
        self.run_id = run_id or f"run-{uuid.uuid4().hex[:12]}"
        self.run_dir = run_dir
        self.lock_path = lock_path
        self.session = session
        self.log = EventLog(os.path.join(run_dir, "journal.jsonl"))
        self.repository = StateRepository(os.path.join(run_dir, "snapshot.json"))
        self.evidence = EvidenceStore(
            os.path.join(run_dir, "evidences.jsonl"),
            os.path.join(run_dir, "evidence-invalidations.jsonl"))
        self._lock_handle: Optional[Any] = None
        self.generationToken: Optional[str] = None
        self._now: Callable[[], str] = _default_clock

    # ------------------------------------------------------------------ lock

    def acquire_lock(self) -> str:
        """Acquire the exclusive flock and stamp the lock file with the NEW
        generation token (RFC §4.1 + §4.4/F6). Raises LockHeld if owned."""
        if self._lock_handle is not None:
            return self.generationToken or ""
        os.makedirs(os.path.dirname(os.path.abspath(self.lock_path)), exist_ok=True)
        handle = open(self.lock_path, "a+")
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            handle.close()
            raise LockHeld(
                f"run lock is held by another orchestrator ({self.lock_path}) — "
                f"this session stops cleanly (RFC §4.1, S6)")
        token = f"gen-{uuid.uuid4().hex[:16]}"
        handle.seek(0)
        handle.truncate()
        handle.write(json.dumps({
            "generationToken": token, "pid": os.getpid(), "session": self.session,
        }, sort_keys=True) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
        self._lock_handle = handle
        self.generationToken = token
        return token

    def release_lock(self) -> None:
        if self._lock_handle is not None:
            fcntl.flock(self._lock_handle.fileno(), fcntl.LOCK_UN)
            self._lock_handle.close()
            self._lock_handle = None
            self.generationToken = None

    def _critical(self, operation: Callable[[], Dict[str, Any]]) -> Dict[str, Any]:
        """Same-critical-section fencing (RFC §4.4): verify the lock file STILL
        carries MY generation token, then write — one protected block. A stale
        owner whose lock was recovered by a new one is rejected by the ENGINE
        (StaleGeneration), not by convention."""
        if self._lock_handle is None:
            raise RuntimeError("lock must be acquired before any state write")
        handle = self._lock_handle
        handle.seek(0)
        lock_payload = json.loads(handle.read() or "{}")
        if lock_payload.get("generationToken") != self.generationToken:
            raise StaleGeneration(
                f"generationToken mismatch: lock now owned by "
                f"{lock_payload.get('generationToken')!r}, writer holds "
                f"{self.generationToken!r} — write rejected by the engine (fencing)")
        return operation()

    # ------------------------------------------------------------- ordering

    def topo_order(self) -> List[str]:
        """Kahn topological order (deterministic: alphabetical tie-break)."""
        indegree = {node_id: 0 for node_id in self.nodes}
        dependents: Dict[str, List[str]] = {node_id: [] for node_id in self.nodes}
        for node_id, node in self.nodes.items():
            for dep in node.get("deps", []):
                indegree[node_id] += 1
                dependents[dep].append(node_id)
        ready = sorted(node_id for node_id, degree in indegree.items() if degree == 0)
        order: List[str] = []
        while ready:
            current = ready.pop(0)
            order.append(current)
            new_ready = []
            for dependent in dependents[current]:
                indegree[dependent] -= 1
                if indegree[dependent] == 0:
                    new_ready.append(dependent)
            ready = sorted(ready + new_ready)
        if len(order) != len(self.nodes):
            raise ValueError("graph contains a cycle (invariant I4)")
        return order

    def _ancestors(self, node_id: str) -> List[str]:
        """Transitive upstream ids of a node (I5/F3 completion re-check)."""
        seen: set = set()
        stack = list(self.nodes[node_id].get("deps", []))
        while stack:
            current = stack.pop()
            if current in seen:
                continue
            seen.add(current)
            stack.extend(self.nodes[current].get("deps", []))
        return sorted(seen)

    def _descendants(self, node_id: str) -> List[str]:
        """Transitive downstream ids (I5 invalidation scope)."""
        seen: set = set()
        stack = [node_id]
        while stack:
            current = stack.pop()
            for candidate, node in self.nodes.items():
                if current in node.get("deps", []) and candidate not in seen:
                    seen.add(candidate)
                    stack.append(candidate)
        return sorted(seen)

    # ------------------------------------------------------------- journaling

    def _journal(self, kind: str, node_id: str, attempt: int, to: str,
                 payload: Optional[dict] = None, at: Optional[str] = None) -> Dict[str, Any]:
        """Journalize ONE record under the same critical section as the write
        it describes (I3 — the append + fsync IS the durable commit point)."""
        record = {
            "transitionId": f"t-{uuid.uuid4().hex[:16]}",
            "runId": self.run_id,
            "nodeId": node_id,
            "attempt": attempt,
            "kind": kind,
            "from": node_status(self._state(), node_id),
            "to": to,
            "generationToken": self.generationToken or "",
            "timestamp": at or self._now(),
            "payload": payload or {},
        }

        def write() -> Dict[str, Any]:
            return self.log.append(record)

        return self._critical(write)

    def _state(self) -> Dict[str, Any]:
        if getattr(self, "_cached_state", None) is None:
            self._cached_state = self.repository.load()
        return self._cached_state

    # ------------------------------------------------------------- execution

    def start(self) -> None:
        """Resume/start protocol (RFC §5): acquire lock, reconcile the journal,
        THEN pick up the execution — never before."""
        self.acquire_lock()
        # The KNOWN GENERATION CHAIN lives in the projection (RFC §4.4/F6): a
        # record is only foreign if its token is outside the whole chain of
        # legitimate lock owners — the previous session's records are part of
        # the truth and MUST replay (scenario S2). A foreign token (a stale
        # owner that was never a legitimate generation) is still rejected.
        previous = self.repository.load()
        chain: List[str] = list(previous.get("knownGenerations") or [])
        if self.generationToken and self.generationToken not in chain:
            chain.append(self.generationToken)
        result = self.log.replay(chain)
        self._cached_state = self.repository.rebuild(
            self.run_id, self.log, chain)
        self._cached_state["knownGenerations"] = chain
        self.repository.save(self._cached_state)
        # Foreign-generation records found in the journal are surfaced, never
        # replayed (fencing retroactif — §4.4/F6).
        if result["rejected"]:
            self._cached_state["rejectedRecords"] = result["rejected"]

    def runnable_nodes(self) -> List[str]:
        """Nodes whose deps are all completed with valid evidence (I4)."""
        ready: List[str] = []
        for node_id in self.topo_order():
            status = node_status(self._state(), node_id)
            if status != "pending":
                continue
            if all(node_status(self._state(), dep) == "completed"
                   and self._dep_evidence_valid(dep)
                   for dep in self.nodes[node_id].get("deps", [])):
                ready.append(node_id)
        return ready

    def _dep_evidence_valid(self, dep_id: str) -> bool:
        """A dependency counts only if its evidence is not marked invalidated
        (I5 — no descendant may execute over a stale proof, scenario S3)."""
        executions = self._state().get("nodeExecutions") or {}
        entry = executions.get(dep_id) or {}
        for evidence in entry.get("evidenceIds", []) or []:
            for valid in self.evidence.list_valid():
                if valid.get("evidenceId") == evidence:
                    break
            else:
                return False  # recorded evidence invalidated (or missing)
        return True

    def execute_node(self, node_id: str, executor: Callable[[str, Dict[str, Any]], Dict[str, Any]]) -> Dict[str, Any]:
        """Run ONE node under the protocol: pending→running (journalized),
        executor injected (test doubles — review technique F19), completion
        with the I5/F3 ancestor re-check, failures counted per class (I8)."""
        node = self.nodes[node_id]
        state = self._state()
        entry = (state.get("nodeExecutions") or {}).get(node_id) or {}
        attempt = int(entry.get("attempt", 1))
        self._journal("transition", node_id, attempt, "running",
                      {"executor": self.session})
        mark_transition(state, node_id, "running", attempt=attempt,
                        timestamp=self._now())
        self.repository.save(state)
        try:
            result = executor(node_id, node)
        except Exception as error:  # noqa: BLE001 — failure classification below
            counts = (state["nodeExecutions"][node_id].setdefault("failureCounts",
                      {"technical": 0, "quality": 0, "invalidEvidence": 0, "permission": 0}))
            failure_class = str(getattr(error, "failureClass", "technical"))
            counts[failure_class] = counts.get(failure_class, 0) + 1
            self._journal("transition", node_id, attempt, "failed",
                          {"error": str(error), "failureClass": failure_class})
            mark_transition(state, node_id, "failed", attempt=attempt,
                            timestamp=self._now())
            self.repository.save(state)
            return {"nodeId": node_id, "status": "failed", "error": str(error)}
        evidence_ids = []
        for evidence in result.get("evidences", []):
            stamped = self.evidence.append(evidence)
            evidence_ids.append(stamped["evidenceId"])
        try:
            self._journal("transition", node_id, attempt, "completed",
                          {"evidenceIds": evidence_ids,
                           "output": result.get("output", {})})
            mark_transition(state, node_id, "completed", attempt=attempt,
                            timestamp=self._now(), ancestors=self._ancestors(node_id))
        except StaleCompletion as error:
            # An ancestor was invalidated DURING execution (I5/F3): the
            # completion is rejected and the node invalidated transitively.
            outcome = self.invalidate(node_id, reason=f"stale completion rejected: {error}")
            return {"nodeId": node_id, "status": "invalidated", "detail": outcome}
        entry = state["nodeExecutions"][node_id]
        entry["evidenceIds"] = evidence_ids
        entry["outputArtifactRefs"] = result.get("artifactRefs", [])
        self.repository.save(state)
        return {"nodeId": node_id, "status": "completed", "evidenceIds": evidence_ids}

    def invalidate(self, node_id: str, reason: str,
                   fingerprint_divergence: Optional[str] = None,
                   propagate: bool = True) -> Dict[str, Any]:
        """Explicit journaled invalidation (I5) with transitive scope applied
        by the scheduler (it owns the graph)."""
        state = self._state()
        attempt = int(((state.get("nodeExecutions") or {}).get(node_id) or {})
                      .get("attempt", 1))
        descendants = self._descendants(node_id) if propagate else []
        outcome = invalidate_node(
            state, node_id, reason, timestamp=self._now(),
            fingerprint_divergence=fingerprint_divergence, descendants=descendants)
        self._journal("invalidation", node_id, attempt, outcome["to"], {
            "reason": reason,
            "fingerprintDivergence": fingerprint_divergence,
            "affected": outcome["descendants"],
            "invalidations": state.get("invalidations", {}),
        })
        # Evidences are MARKED invalid, never deleted (I5, review technique F2).
        entry = (state.get("nodeExecutions") or {}).get(node_id) or {}
        for evidence_id in entry.get("evidenceIds", []) or []:
            self.evidence.mark_invalidated(evidence_id, reason, self._now())
        for descendant in outcome["descendants"]:
            desc_entry = (state.get("nodeExecutions") or {}).get(descendant) or {}
            for evidence_id in desc_entry.get("evidenceIds", []) or []:
                self.evidence.mark_invalidated(evidence_id, reason, self._now())
        self.repository.save(state)
        return outcome

    def run(self, executor: Callable[[str, Dict[str, Any]], Dict[str, Any]],
            max_nodes: Optional[int] = None) -> List[Dict[str, Any]]:
        """Sequential execution in topo-order until nothing is runnable."""
        executed: List[Dict[str, Any]] = []
        for node_id in self.topo_order():
            if max_nodes is not None and len(executed) >= max_nodes:
                break
            if node_status(self._state(), node_id) != "pending":
                continue
            if not all(node_status(self._state(), dep) == "completed"
                       and self._dep_evidence_valid(dep)
                       for dep in self.nodes[node_id].get("deps", [])):
                continue
            executed.append(self.execute_node(node_id, executor))
        return executed


def _default_clock() -> str:
    import datetime
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
