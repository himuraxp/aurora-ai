"""GraphScheduler of the Execution Graph Core (RFC §4, §5, §7, §11 M3).

Sequential scheduler for the JSON mono-executor pilot (RFC §0):
- topological execution order (Kahn), SEQUENTIAL (review technique F11 —
  concurrencyKey is reserved for M7+);
- continuous `flock` ownership per run (RFC §4.1): acquired before any
  scheduling decision, held for the whole orchestration session, released by
  the kernel on crash;
- the generation CHAIN lives in the LOCK FILE, append-only (RFC §4.4 + review
  F-01: never in the rebuildable projection — the journal must replay even
  if the snapshot disappears); the CURRENT token is verified at EVERY state
  write inside the same flock-protected critical section (fencing — TOCTOU
  closed, review PO itération 2);
- deterministic resume (RFC §5): journal reconciliation, orphan `running`
  re-pinning (review F-03), freshness re-check via inputFingerprint (I7,
  review F-06), THEN execution;
- effects go through the journaled EffectRecord protocol (RFC §7.2, review
  F-08) with an injectable dispatcher — test doubles simulate crashes
  between `prepared`, `dispatched` and the real emission (S5/S7, F19);
- evidence guard I2 at completion (review F-04) and permission enforcement
  at runtime (I9, review F-16).
"""
from __future__ import annotations

import errno
import fcntl
import hashlib
import json
import os
import uuid
from typing import Any, Callable, Dict, List, Optional

from .contracts import (
    validate_evidence_record, validate_graph_definition,
)
from .persistence import (
    EventLog, EvidenceStore, StateRepository, canonical_json, new_run_id,
)
from .transition_engine import (
    StaleCompletion, StaleGeneration, budget_exhausted, count_failure,
    invalidate_node, mark_transition, node_status, repin_orphan_running,
)


class LockHeld(RuntimeError):
    """Another orchestrator owns the run lock (RFC §4.1, scenario S6)."""


class PlanMismatch(RuntimeError):
    """The run is being resumed with a DIFFERENT plan (I6/F18, review F-09)."""


class EffectDispatcher:
    """Injectable effect emitter (RFC §7.2, review F-08/F-19).

    The pilot NEVER performs a real external call from the core: real
    executors are injected here (M5 runs them in sandbox). A test double
    raises from `dispatch` to simulate a crash between `dispatched` and the
    emission, or returns outcome="uncertain" for a mute API.
    """

    def dispatch(self, node_id: str, node: Dict[str, Any],
                 idempotency_key: str) -> Dict[str, Any]:
        raise NotImplementedError("real dispatch belongs to the M5 pilot sandbox")

    def reconcile(self, node_id: str, node: Dict[str, Any],
                  idempotency_key: str) -> Dict[str, Any]:
        """GET-before-POST / contentHash reconciliation (§7.1). Optional."""
        raise NotImplementedError("reconciliation belongs to the M5 pilot sandbox")


def derive_classification(effect_policy: Dict[str, Any]) -> str:
    """RFC §7.1 mapping (review F9): getBeforePost/contentHash → reconcile,
    none → block, explicitly safe operations → safe. Anything uncovered is
    block by default (débat tour 3)."""
    if effect_policy.get("classification") == "safe":
        return "safe"
    reconciliation = effect_policy.get("reconciliation")
    if reconciliation in ("getBeforePost", "contentHash"):
        return "reconcile"
    return "block"


def compute_input_fingerprint(node: Dict[str, Any],
                              dep_fingerprints: Dict[str, str],
                              code_signature: Optional[str] = None,
                              tool_versions: Optional[Dict[str, str]] = None) -> str:
    """RFC §6.2 (review F-06): sha256 over the canonical serialization of
    labeled, sorted components; irrelevant (empty) components are OMITTED; a
    node with no applicable component yields the CONSTANT string — never
    empty."""
    components: List[tuple] = []
    if code_signature:
        components.append(("codeSignature", code_signature))
    if dep_fingerprints:
        components.append(("deps", sorted(dep_fingerprints.items())))
    if tool_versions:
        components.append(("toolVersions", sorted(tool_versions.items())))
    declared_inputs = node.get("inputs") or {}
    if declared_inputs:
        components.append(("declaredInputs", declared_inputs))
    if not components:
        digest = hashlib.sha256(b"empty-input-fingerprint").hexdigest()
        return f"sha256:{digest}"
    digest = hashlib.sha256(canonical_json(components).encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


EMPTY_INPUT_FINGERPRINT = compute_input_fingerprint({"inputs": {}}, {})


class GraphScheduler:
    """Sequential executor of a GraphDefinition run under flock + fencing."""

    def __init__(self, graph: Dict[str, Any], run_dir: str, lock_path: str,
                 run_id: Optional[str] = None, session: str = "pilot",
                 dispatcher: Optional[EffectDispatcher] = None,
                 code_signature: Optional[str] = None,
                 tool_versions: Optional[Dict[str, str]] = None,
                 clock: Optional[Callable[[], str]] = None):
        problems = validate_graph_definition(graph)
        if problems:
            raise ValueError(f"invalid GraphDefinition: {'; '.join(problems)}")
        self.graph = graph
        self.nodes: Dict[str, dict] = {n["id"]: n for n in graph["nodes"]}
        self.run_id = run_id or new_run_id()
        # Run adoption (review F-14 ergonomics): resuming an existing run-dir
        # WITHOUT an explicit run_id adopts the persisted identity — the
        # run-dir IS the run. An explicit MISMATCHED run_id is still refused
        # at start() (immutability).
        run_id_path = os.path.join(run_dir, "run-id")
        if run_id is None and os.path.isfile(run_id_path):
            with open(run_id_path, "r", encoding="utf-8") as handle:
                persisted = handle.read().strip()
            if persisted:
                self.run_id = persisted
        self.run_dir = run_dir
        self.lock_path = lock_path
        self.session = session
        self.dispatcher = dispatcher or EffectDispatcher()
        self.code_signature = code_signature
        self.tool_versions = tool_versions or {}
        self._now = clock or _default_clock
        self.log = EventLog(os.path.join(run_dir, "journal.jsonl"))
        self.repository = StateRepository(os.path.join(run_dir, "snapshot.json"))
        self.evidence = EvidenceStore(
            os.path.join(run_dir, "evidences.jsonl"),
            os.path.join(run_dir, "evidence-invalidations.jsonl"))
        self._lock_handle: Optional[Any] = None
        self.generationToken: Optional[str] = None
        self._cached_state: Optional[Dict[str, Any]] = None

    # ------------------------------------------------------------------ lock

    def acquire_lock(self) -> str:
        """Acquire the exclusive flock and APPEND the new generation to the
        lock file (RFC §4.1 + §4.4/F6 — the chain lives here, review F-01)."""
        if self._lock_handle is not None:
            return self.generationToken or ""
        os.makedirs(os.path.dirname(os.path.abspath(self.lock_path)), exist_ok=True)
        handle = open(self.lock_path, "a+")
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            handle.close()
            if error.errno in (errno.EWOULDBLOCK, errno.EAGAIN, errno.EACCES):
                raise LockHeld(
                    f"run lock is held by another orchestrator ({self.lock_path}) — "
                    f"this session stops cleanly (RFC §4.1, S6)")
            raise  # a real I/O error is not a lock contention (review F-20)
        token = f"gen-{uuid.uuid4().hex[:16]}"
        handle.seek(0, os.SEEK_END)
        handle.write(canonical_json({
            "event": "acquire", "generationToken": token, "pid": os.getpid(),
            "session": self.session, "at": self._now(),
        }) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
        self._lock_handle = handle
        self.generationToken = token
        return token

    def generation_chain(self) -> List[str]:
        """Every generation that ever legitimately owned the lock (review F-01)."""
        if not os.path.isfile(self.lock_path):
            return []
        chain: List[str] = []
        with open(self.lock_path, "r", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                try:
                    payload = json.loads(line)
                except ValueError:
                    continue  # torn tail in the lock file — skipped
                token = payload.get("generationToken")
                if payload.get("event") == "acquire" and token:
                    chain.append(str(token))
        return chain

    def beat(self) -> None:
        """Heartbeat — DETECTION ONLY, never authorization (RFC §4.2). Append
        to the lock file; a frozen owner (SIGSTOP) keeps the flock and the
        heartbeat stops — documented escalation is HUMAN (review F13)."""
        if self._lock_handle is None:
            return
        self._lock_handle.seek(0, os.SEEK_END)
        self._lock_handle.write(canonical_json({
            "event": "heartbeat", "generationToken": self.generationToken,
            "at": self._now(),
        }) + "\n")
        self._lock_handle.flush()
        os.fsync(self._lock_handle.fileno())

    def release_lock(self) -> None:
        if self._lock_handle is not None:
            fcntl.flock(self._lock_handle.fileno(), fcntl.LOCK_UN)
            self._lock_handle.close()
            self._lock_handle = None
            self.generationToken = None

    def _critical(self, operation: Callable[[], Any]) -> Any:
        """Same-critical-section fencing (RFC §4.4): verify the lock file STILL
        ends with MY generation token, then write — one protected block. A
        stale owner whose lock was recovered by a new one is rejected by the
        ENGINE (StaleGeneration), not by convention. An unparsable lock file
        is treated as a generation mismatch (review F-20)."""
        if self._lock_handle is None:
            raise RuntimeError("lock must be acquired before any state write")
        handle = self._lock_handle
        handle.seek(0)
        last_token = None
        for line in handle.read().splitlines():
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except ValueError:
                last_token = None  # torn lock file — treat as mismatch
                break
            if payload.get("event") == "acquire":
                last_token = payload.get("generationToken")
        if last_token != self.generationToken:
            raise StaleGeneration(
                f"generationToken mismatch: lock's current generation is "
                f"{last_token!r}, writer holds {self.generationToken!r} — write "
                f"rejected by the engine (fencing)")
        return operation()

    # ------------------------------------------------------------- ordering

    def topo_order(self) -> List[str]:
        """Kahn topological order (deterministic: alphabetical tie-break)."""
        indegree = {node_id: 0 for node_id in self.nodes}
        dependents: Dict[str, List[str]] = {node_id: [] for node_id in self.nodes}
        for node_id, node in self.nodes.items():
            for dep in set(node.get("deps", [])):  # dedup (review F-17)
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
                if current in set(node.get("deps", [])) and candidate not in seen:
                    seen.add(candidate)
                    stack.append(candidate)
        return sorted(seen)

    # ------------------------------------------------------------- journaling

    def _next_revision(self) -> int:
        """Journal revision = position AFTER the last record (monotonic, F-11)."""
        records, _problems = self.log.read()
        return (records[-1]["_revision"] + 1) if records else 1

    def _journal(self, kind: str, node_id: str, attempt: int, to: str,
                 from_status: Optional[str] = None,
                 payload: Optional[dict] = None) -> Dict[str, Any]:
        """Journalize ONE record under the same critical section as the write
        it describes (I3 — the append + fsync IS the durable commit point).
        `from_status` is captured BEFORE any mutation (review F-10)."""
        record = {
            "transitionId": f"t-{uuid.uuid4().hex[:16]}",
            "runId": self.run_id,
            "nodeId": node_id,
            "attempt": attempt,
            "kind": kind,
            "from": from_status if from_status is not None
                    else node_status(self._state(), node_id),
            "to": to,
            "generationToken": self.generationToken or "",
            "timestamp": self._now(),
            "payload": payload or {},
        }

        def write() -> Dict[str, Any]:
            return self.log.append(record)

        return self._critical(write)

    def _state(self) -> Dict[str, Any]:
        if self._cached_state is None:
            self._cached_state = self.repository.load()
        return self._cached_state

    # ------------------------------------------------------- effects (§7.2)

    def _perform_effect(self, node_id: str, node: Dict[str, Any],
                        attempt: int) -> Dict[str, Any]:
        """Journaled effect protocol (RFC §7.2, review F-08): prepared + fsync →
        dispatched + fsync → emission → confirmed/failed (or uncertain). The
        dispatcher is injectable — crash simulation between phases is a test
        double concern (S5/S7). `block` classification never reaches emission
        without human approval."""
        policy = node.get("effectPolicy") or {}
        classification = derive_classification(policy)
        idempotency_key = str(policy.get("idempotencyKey") or f"{node_id}:{attempt}")
        if classification == "block":
            # Never automatic — blocked awaiting human intervention (§7.1).
            self._journal("effect", node_id, attempt, "blocked", payload={
                "effectPhase": "prepared", "classification": classification,
                "idempotencyKey": idempotency_key,
                "note": "block classification — human approval required",
            })
            return {"effect": "blocked"}
        if classification == "safe":
            # CONDENSED sequence (§7.1): ONE dispatched record + fsync BEFORE
            # the emission — the prepared phase is useless when the rejeu
            # under proven preconditions is parasite-free.
            self._journal("effect", node_id, attempt, "dispatched", payload={
                "effectPhase": "dispatched", "classification": classification,
                "idempotencyKey": idempotency_key,
            })
        else:
            # reconcile — full sequence: prepared, then dispatched + fsync
            # BEFORE the emission is allowed (P0.3 — closes the double-effect
            # window).
            self._journal("effect", node_id, attempt, "prepared", payload={
                "effectPhase": "prepared", "classification": classification,
                "idempotencyKey": idempotency_key,
            })
            self._journal("effect", node_id, attempt, "dispatched", payload={
                "effectPhase": "dispatched", "classification": classification,
                "idempotencyKey": idempotency_key,
            })
        try:
            outcome = self.dispatcher.dispatch(node_id, node, idempotency_key)
        except Exception as error:  # noqa: BLE001 — uncertain/failed by class
            self._journal("effect", node_id, attempt, "uncertain", payload={
                "effectPhase": "uncertain", "classification": classification,
                "idempotencyKey": idempotency_key, "error": str(error),
            })
            return {"effect": "uncertain"}
        effect_phase = str(outcome.get("outcome", "uncertain"))
        self._journal("effect", node_id, attempt, effect_phase, payload={
            "effectPhase": effect_phase, "classification": classification,
            "idempotencyKey": idempotency_key,
            "outcomeEvidenceRef": outcome.get("evidenceRef", ""),
        })
        return {"effect": effect_phase}

    def record_human_intervention(self, node_id: str, actor: str,
                                  decision: str, reason: str) -> Dict[str, Any]:
        """S5 trace: the human intervention is a journaled record with motive
        and identity (review F19 — makes the assertion automatable)."""
        return self._journal("human-intervention", node_id, 1, "resolved",
                             payload={"actor": actor, "decision": decision,
                                      "reason": reason})

    # ------------------------------------------------------------- resume

    def start(self) -> None:
        """Resume/start protocol (RFC §5): acquire lock, persist run identity
        and plan (I6/F18 — review F-09), reconcile the journal, re-apply the
        evidence markers (F-13), re-pin orphan runnings (F-03), re-check
        freshness (I7/§5.4) — THEN pick up the execution."""
        self.acquire_lock()
        os.makedirs(self.run_dir, exist_ok=True)
        # Run identity: unique, immutable (§2.3, review F-14).
        run_id_path = os.path.join(self.run_dir, "run-id")
        if os.path.isfile(run_id_path):
            with open(run_id_path, "r", encoding="utf-8") as handle:
                persisted = handle.read().strip()
            if persisted and persisted != self.run_id:
                self.release_lock()  # a refusal never keeps the lock held
                raise PlanMismatch(
                    f"run-dir belongs to run {persisted!r}, refusing to resume it "
                    f"as {self.run_id!r} (runId is immutable, review F-14)")
        else:
            with open(run_id_path, "w", encoding="utf-8") as handle:
                handle.write(self.run_id + "\n")
        # Plan identity: (graphId, version, plan hash) persisted and revalidated
        # at resume (review F-09).
        plan_path = os.path.join(self.run_dir, "plan.json")
        plan_digest = hashlib.sha256(canonical_json(self.graph).encode("utf-8")).hexdigest()
        if os.path.isfile(plan_path):
            with open(plan_path, "r", encoding="utf-8") as handle:
                persisted_plan = json.load(handle)
            if persisted_plan.get("planHash") != plan_digest:
                self.release_lock()  # a refusal never keeps the lock held
                raise PlanMismatch(
                    f"plan mismatch for run {self.run_id}: persisted "
                    f"(graphId={persisted_plan.get('graphId')}, "
                    f"version={persisted_plan.get('version')}) vs resumed graph "
                    f"— a run is immutable (I6, review F-09)")
        else:
            with open(plan_path, "w", encoding="utf-8") as handle:
                handle.write(canonical_json({
                    "graphId": self.graph.get("graphId"),
                    "version": self.graph.get("version"),
                    "planHash": plan_digest,
                }) + "\n")
        # Journal reconciliation — the chain comes from the LOCK FILE (F-01),
        # never from the rebuildable snapshot.
        chain = self.generation_chain()
        if self.generationToken and self.generationToken not in chain:
            chain.append(self.generationToken)
        self._cached_state = self.repository.rebuild(self.run_id, self.log, chain)
        self._cached_state["knownGenerations"] = chain
        self.repository.save(self._cached_state)
        self._reapply_evidence_markers()
        self._pin_orphan_runnings()
        self._refresh_fingerprints()

    def _reapply_evidence_markers(self) -> None:
        """Re-apply evidence invalidation markers from the journal alone
        (review F-13): the source of truth suffices after any rebuild."""
        records, _problems = self.log.read()
        invalidated: List[str] = []
        for record in records:
            if record.get("kind") == "invalidation":
                invalidated.extend(
                    (record.get("payload") or {}).get("invalidatedEvidenceIds", []))
        if invalidated:
            self.evidence.reapply_from_journal(invalidated, "journal invalidation",
                                               self._now())

    def _pin_orphan_runnings(self) -> None:
        """RFC §5 step 3 (review F-03): at a NEW acquisition, every `running`
        is orphaned (its owner lost the lock — kernel guarantee). Re-pin it
        to `pending` via the RECOVERY operation (repin_orphan_running —
        journaled kind=invalidation, NOT a table transition) — unless an
        effect of its execution is non-concluded (dispatched/uncertain):
        then `blocked` via the legal running→blocked transition, and
        reconciliation first (§7.2)."""
        state = self._state()
        effect_phases = self._unconcluded_effect_phases()
        for node_id, entry in list((state.get("nodeExecutions") or {}).items()):
            if entry.get("status") != "running":
                continue
            attempt = int(entry.get("attempt", 1))
            if effect_phases.get(node_id) in ("dispatched", "uncertain"):
                # Legal transition running→blocked (table §3.1): no rejeu on
                # an unconcluded effect — reconciliation first (§7.2).
                mark_transition(state, node_id, "blocked", attempt=attempt)
                self._journal("transition", node_id, attempt, "blocked",
                              from_status="running",
                              payload={"reason": "orphan running with unconcluded effect "
                                                 "— reconciliation required (§7.2)"})
            else:
                outcome = repin_orphan_running(state, node_id)  # VALIDATE first (F-02)
                attempt = int((state["nodeExecutions"][node_id]).get("attempt", 1))
                self._journal("invalidation", node_id, attempt, "pending",
                              from_status="running",
                              payload={"reason": "orphan running re-pinned (§5.3)",
                                       "affected": []})
                assert not outcome.get("skipped")  # guarded by the status check above
        self.repository.save(state)

    def _unconcluded_effect_phases(self) -> Dict[str, str]:
        """Latest effect phase per node from the journal (§7.2)."""
        records, _problems = self.log.read()
        phases: Dict[str, str] = {}
        for record in records:
            if record.get("kind") != "effect":
                continue
            phase = str((record.get("payload") or {}).get("effectPhase", ""))
            if phase in ("dispatched", "uncertain"):
                phases[str(record.get("nodeId"))] = phase
            elif phase in ("confirmed", "failed", "reconciled", "blocked"):
                phases.pop(str(record.get("nodeId")), None)
        return phases

    def _refresh_fingerprints(self) -> None:
        """RFC §5.4 (review F-06/I7): at resume, every completed node's
        fingerprint is recomputed — divergence = stale proof = explicit
        transitive invalidation (I5)."""
        state = self._state()
        for node_id in list((state.get("nodeExecutions") or {}).keys()):
            if node_status(state, node_id) != "completed":
                continue
            node = self.nodes[node_id]
            fresh = self._compute_fingerprint(node_id, state)
            stored = (state["nodeExecutions"][node_id].get("inputFingerprint") or "")
            if fresh != stored:
                self.invalidate(node_id, "input fingerprint divergent at resume (I7/§5.4)",
                                fingerprint_divergence=fresh)

    def _compute_fingerprint(self, node_id: str,
                             state: Optional[Dict[str, Any]] = None) -> str:
        state = state or self._state()
        node = self.nodes[node_id]
        dep_fingerprints = {
            dep: str(((state.get("nodeExecutions") or {}).get(dep) or {})
                     .get("inputFingerprint", ""))
            for dep in node.get("deps", [])
        }
        return compute_input_fingerprint(node, dep_fingerprints,
                                         code_signature=self.code_signature,
                                         tool_versions=self.tool_versions)

    # ------------------------------------------------------------- guards

    def _evidence_guards_ok(self, node_id: str, node: Dict[str, Any],
                            result: Dict[str, Any]) -> bool:
        """I2 at completion (review F-04): every required kind must be
        satisfied by a conforming evidence record — a pass technical proof
        requires exitCode == 0. Un contrôle ignoré n'est jamais présenté
        comme réussi."""
        required = ((node.get("evidencePolicy") or {}).get("required")) or []
        evidences = result.get("evidences") or []
        for evidence in evidences:
            problems = validate_evidence_record(evidence, required=required)
            if problems:
                return False
        return bool(evidences) or not required

    def _permissions_ok(self, node_id: str, node: Dict[str, Any]) -> bool:
        """I9 at runtime (review F-16): a write effect requires an explicit
        write: permission on a tool node — the engine REFUSES, it never
        assumes."""
        policy = node.get("effectPolicy") or {}
        if policy.get("mode") != "write":
            return True
        return any(str(p).startswith("write:")
                   for p in node.get("permissions", []))

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

    def _deps_fresh(self, node_id: str) -> bool:
        """I7 at consumption (review F-06): every dep's stored fingerprint
        must equal its recomputed one."""
        state = self._state()
        for dep in self.nodes[node_id].get("deps", []):
            stored = str(((state.get("nodeExecutions") or {}).get(dep) or {})
                         .get("inputFingerprint", ""))
            if stored and self._compute_fingerprint(dep, state) != stored:
                return False
        return True

    # ------------------------------------------------------------- execution

    def execute_node(self, node_id: str,
                     executor: Callable[[str, Dict[str, Any]], Dict[str, Any]]) -> Dict[str, Any]:
        """Run ONE node under the protocol (reviews F-02/F-04/F-06/F-07/F-08/
        F-16): validate the transition FIRST, journalize SECOND (never a
        phantom record — I1/I3); fingerprint computed and stored (P0.3);
        write effects go through the journaled protocol with permission
        enforcement (I9); completion guarded by I2; failures counted per
        class and routed to blocked at budget exhaustion (I8)."""
        node = self.nodes[node_id]
        state = self._state()
        entry = (state.get("nodeExecutions") or {}).get(node_id) or {}
        attempt = int(entry.get("attempt", 1))
        previous_status = node_status(state, node_id)  # captured BEFORE any mutation (F-10)
        if not self._permissions_ok(node_id, node):
            count_failure(state, node_id, "permission")
            mark_transition(state, node_id, "blocked", attempt=attempt)  # VALIDATE first (F-02)
            self._journal("transition", node_id, attempt, "blocked",
                          from_status=previous_status,
                          payload={"reason": "write effect without write: permission (I9)",
                                   "failureClass": "permission"})
            self.repository.save(state)
            return {"nodeId": node_id, "status": "blocked",
                    "reason": "permission refused by the engine (I9)"}
        revision = self._next_revision()
        fingerprint = self._compute_fingerprint(node_id, state)
        mark_transition(state, node_id, "running", attempt=attempt,
                        started_revision=revision)  # VALIDATE first (F-02)
        self._journal("transition", node_id, attempt, "running",
                      from_status=previous_status,
                      payload={"executor": self.session, "revision": revision,
                               "inputFingerprint": fingerprint})
        state["nodeExecutions"][node_id]["inputFingerprint"] = fingerprint
        self.repository.save(state)
        try:
            result = executor(node_id, node)
        except Exception as error:  # noqa: BLE001 — classified below
            failure_class = str(getattr(error, "failureClass", "technical"))
            count_failure(state, node_id, failure_class)
            next_status, reason = self._failure_destination(node_id, node, failure_class)
            mark_transition(state, node_id, next_status, attempt=attempt)  # VALIDATE first
            self._journal("transition", node_id, attempt, next_status,
                          from_status="running",
                          payload={"error": str(error), "failureClass": failure_class,
                                   "reason": reason})
            self.repository.save(state)
            return {"nodeId": node_id, "status": next_status, "error": str(error)}
        if node_status(state, node_id) != "running":
            # The node was INVALIDATED DURING its own execution (I5 — the
            # executor triggered the invalidation): the completion is void.
            # The invalidation record already covers the state change
            # (running → cancelled); no completion, no evidence persisted.
            return {"nodeId": node_id, "status": "invalidated",
                    "reason": "node invalidated during execution (I5)"}
        # Effect protocol (§7.2) BEFORE completion — a write node completes
        # only with a concluded effect.
        if (node.get("effectPolicy") or {}).get("mode") == "write":
            effect = self._perform_effect(node_id, node, attempt)
            if effect.get("effect") in ("uncertain", "blocked"):
                mark_transition(state, node_id, "blocked", attempt=attempt)
                self._journal("transition", node_id, attempt, "blocked",
                              from_status="running",
                              payload={"reason": "unconcluded effect — no rejeu on "
                                                 "uncertainty (§7.2)"})
                self.repository.save(state)
                return {"nodeId": node_id, "status": "blocked",
                        "reason": "effect uncertain — human intervention required"}
        # I2 evidence guard (review F-04) — BEFORE any evidence is persisted
        # as valid: a non-conforming proof is never recorded.
        if not self._evidence_guards_ok(node_id, node, result):
            count_failure(state, node_id, "invalidEvidence")
            mark_transition(state, node_id, "blocked", attempt=attempt)
            self._journal("transition", node_id, attempt, "blocked",
                          from_status="running",
                          payload={"reason": "evidence does not satisfy evidencePolicy (I2)",
                                   "failureClass": "invalidEvidence"})
            self.repository.save(state)
            return {"nodeId": node_id, "status": "blocked",
                    "reason": "evidence guard refused the completion (I2)"}
        evidence_ids = []
        for evidence in result.get("evidences", []):
            stamped = self.evidence.append(evidence)
            evidence_ids.append(stamped["evidenceId"])
        revision = self._next_revision()
        try:
            mark_transition(state, node_id, "completed", attempt=attempt,
                            started_revision=revision,
                            invalidation_revisions=state.get("invalidations") or {},
                            ancestors=self._ancestors(node_id))  # VALIDATE first (F-02)
            self._journal("transition", node_id, attempt, "completed",
                          from_status="running", payload={
                              "evidenceIds": evidence_ids,
                              "outputArtifactRefs": result.get("artifactRefs", []),
                              "output": result.get("output", {}),
                              "revision": revision,
                          })
        except StaleCompletion as error:
            # I5/F3: an ancestor was invalidated DURING execution — the
            # completion is REJECTED and the node goes through the dedicated
            # invalidation (running → cancelled). No completion record, no
            # evidence persisted as valid.
            outcome = self.invalidate(node_id, f"stale completion rejected: {error}")
            return {"nodeId": node_id, "status": "invalidated", "detail": outcome}
        entry = state["nodeExecutions"][node_id]
        entry["evidenceIds"] = evidence_ids
        entry["outputArtifactRefs"] = result.get("artifactRefs", [])
        self.repository.save(state)
        return {"nodeId": node_id, "status": "completed", "evidenceIds": evidence_ids}

    def _failure_destination(self, node_id: str, node: Dict[str, Any],
                             failure_class: str) -> tuple:
        """I8 routing (review F-07). Called while the node is RUNNING — the
        only legal exits from running are failed/blocked (table §3.1).
        technical → failed (TERMINAL when the budget is exhausted; re-filed
        pending by run() on the next pass otherwise); quality /
        invalidEvidence / permission → blocked (never auto-resolved, I8)."""
        state = self._state()
        if failure_class in ("invalidEvidence", "permission"):
            return "blocked", "failure class is never auto-resolved (I8)"
        if failure_class == "quality":
            return "blocked", "quality budget handling requires replanning (I8)"
        if budget_exhausted(node, state, node_id, failure_class):
            return "failed", "technical budget exhausted (I8 — terminal)"
        return "failed", "technical failure — retry under remaining budget (I8)"

    def invalidate(self, node_id: str, reason: str,
                   fingerprint_divergence: Optional[str] = None,
                   propagate: bool = True) -> Dict[str, Any]:
        """Explicit journaled invalidation (I5) with transitive scope applied
        by the scheduler (it owns the graph). `from` is captured BEFORE any
        mutation (review F-10) and the invalidated evidence ids travel in the
        record (review F-13)."""
        state = self._state()
        entry = (state.get("nodeExecutions") or {}).get(node_id) or {}
        attempt = int(entry.get("attempt", 1))
        descendants = self._descendants(node_id) if propagate else []
        from_status = node_status(state, node_id)
        revision = self._next_revision()
        outcome = invalidate_node(
            state, node_id, reason, invalidation_revision=revision,
            descendants=descendants)
        # The record carries the POST-mutation attempt (back to pending = a
        # new attempt was filed) so the projection replays it faithfully.
        # Defensive read (review R-02): a never-executed node has no entry —
        # the invalidation is still traced, nothing crashes.
        attempt = int((state.get("nodeExecutions") or {})
                      .get(node_id, {}).get("attempt", 1))
        invalidated_evidence_ids = list(
            (state.get("nodeExecutions") or {}).get(node_id, {}).get("evidenceIds", []))
        for descendant in outcome["descendants"]:
            invalidated_evidence_ids.extend(
                (state.get("nodeExecutions") or {}).get(descendant, {})
                .get("evidenceIds", []))
        self._journal("invalidation", node_id, attempt, outcome["to"],
                      from_status=from_status, payload={
                          "reason": reason,
                          "fingerprintDivergence": fingerprint_divergence,
                          # per-descendant arrival statuses (a running
                          # descendant lands on cancelled, not pending — the
                          # projection must be faithful, review F-05):
                          "affected": [{"nodeId": d,
                                        "to": node_status(state, d)}
                                       for d in outcome["descendants"]],
                          "invalidatedEvidenceIds": invalidated_evidence_ids,
                          "invalidationRevisions": state.get("invalidations", {}),
                      })
        # Evidences are MARKED invalid, never deleted (I5, review technique F2).
        now = self._now()
        for evidence_id in invalidated_evidence_ids:
            self.evidence.mark_invalidated(evidence_id, reason, now)
        self.repository.save(state)
        return outcome

    def runnable_nodes(self) -> List[str]:
        """Nodes runnable NOW: pending, deps completed with valid evidence and
        fresh fingerprints (I4 + I5 + I7)."""
        ready: List[str] = []
        for node_id in self.topo_order():
            if node_status(self._state(), node_id) != "pending":
                continue
            if not all(node_status(self._state(), dep) == "completed"
                       and self._dep_evidence_valid(dep)
                       and self._deps_fresh(node_id)
                       for dep in self.nodes[node_id].get("deps", [])):
                continue
            ready.append(node_id)
        return ready

    def run(self, executor: Callable[[str, Dict[str, Any]], Dict[str, Any]],
            max_nodes: Optional[int] = None) -> List[Dict[str, Any]]:
        """Sequential execution in topo-order (reviews F-07): pending nodes
        run; failed nodes are re-filed under remaining technical budget;
        blocked nodes are NEVER auto-resolved (I8)."""
        executed: List[Dict[str, Any]] = []
        for node_id in self.topo_order():
            if max_nodes is not None and len(executed) >= max_nodes:
                break
            state = self._state()
            status = node_status(state, node_id)
            node = self.nodes[node_id]
            if status == "failed":
                entry = (state.get("nodeExecutions") or {}).get(node_id) or {}
                if budget_exhausted(node, state, node_id, "technical"):
                    continue  # terminal failed (I8)
                attempt = int(entry.get("attempt", 1)) + 1
                mark_transition(state, node_id, "pending", attempt=attempt)  # failed→pending legal
                self._journal("transition", node_id, attempt, "pending",
                              from_status="failed",
                              payload={"reason": "retry under remaining budget (I8)"})
                self.repository.save(state)
                status = "pending"
            if status != "pending":
                continue  # blocked/running/completed/cancelled — never bypassed
            if not all(node_status(self._state(), dep) == "completed"
                       and self._dep_evidence_valid(dep)
                       and self._deps_fresh(node_id)
                       for dep in node.get("deps", [])):
                continue
            executed.append(self.execute_node(node_id, executor))
        return executed


def _default_clock() -> str:
    import datetime
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
