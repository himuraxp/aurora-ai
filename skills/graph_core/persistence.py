"""Persistence layer of the Execution Graph Core (RFC I3, §2.6, §4, §5).

The append-only journal is the SOURCE OF TRUTH; the JSON snapshot is a
rebuildable PROJECTION (invariant I3 — review PO itération 2, P0.1). All
interfaces are injectable for test doubles (review technique F19).

- EventLog: JSONL, one TransitionRecord per line, per-record sha256 checksum,
  partial-write detection (incomplete tail ignored — never accepted as a
  confirmed transition), fsync of the file AND of the directory AFTER
  creation (review F-15 — the directory entry must be made durable once the
  file exists).
- StateRepository: atomic snapshot (write-to-temp + rename) rebuilt by
  idempotent replay from the journal — INCLUDING evidenceIds, output
  artifact refs and the transitive scope of invalidations (review F-05: the
  projection must carry everything the guards need after any restart).
- EvidenceStore: append-only evidence with INVALIDATION MARKERS — evidences
  are never physically deleted (invariant I5, review technique F2); the
  journal record of an invalidation carries the invalidated evidence ids
  (review F-13) so the journal alone suffices to re-apply the markers.
"""
from __future__ import annotations

import hashlib
import json
import os
import uuid
from typing import Any, Dict, List, Tuple

CHECKSUM_KEY = "checksum"


def canonical_json(payload: Any) -> str:
    """Canonical serialization: sorted keys, no trailing whitespace, UTF-8."""
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def record_checksum(record: Dict[str, Any]) -> str:
    """sha256 of the canonical body (every field except the checksum itself)."""
    body = {key: value for key, value in record.items() if key != CHECKSUM_KEY}
    return hashlib.sha256(canonical_json(body).encode("utf-8")).hexdigest()


def stamp_record(record: Dict[str, Any]) -> Dict[str, Any]:
    """Return a copy of the record carrying its checksum (RFC §2.6)."""
    stamped = dict(record)
    stamped[CHECKSUM_KEY] = record_checksum(stamped)
    return stamped


def _fsync_directory(directory: str) -> None:
    """Durability of directory operations (creation, rotation) — RFC I3."""
    fd = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _append_line(path: str, line: str) -> None:
    """Shared append primitive: create dir, write one line, fsync file AND
    directory when the file was just created (review F-15/F-18)."""
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    created = not os.path.isfile(path)
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(line + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    if created:
        _fsync_directory(directory)  # AFTER creation — the entry is durable now


class EventLog:
    """Append-only JSONL journal — the transactional source of truth (I3)."""

    def __init__(self, path: str):
        self.path = path

    def append(self, record: Dict[str, Any]) -> Dict[str, Any]:
        """Append ONE record as a single line + fsync (the durable commit point)."""
        stamped = stamp_record(record)
        _append_line(self.path, canonical_json(stamped))
        return stamped

    def read(self) -> Tuple[List[Dict[str, Any]], List[str]]:
        """Load records with partial-write detection.

        Returns (records, problems). A NON-PARSABLE or CHECKSUM-FAILING line
        is treated as an incomplete tail when it is the last one — ignored,
        NEVER accepted as a confirmed transition (I3). The same failure on a
        middle line is surfaced as a corruption problem (never silently
        accepted either).
        """
        if not os.path.isfile(self.path):
            return [], []
        with open(self.path, "r", encoding="utf-8") as handle:
            lines = handle.read().splitlines()
        records: List[Dict[str, Any]] = []
        problems: List[str] = []
        for number, line in enumerate(lines, start=1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except ValueError:
                problems.append(f"line {number}: not parsable"
                                + (" (incomplete tail ignored)" if number == len(lines) else ""))
                continue
            if not isinstance(record, dict):
                problems.append(f"line {number}: not a JSON object")
                continue
            expected = record.get(CHECKSUM_KEY)
            if not expected or record_checksum(record) != expected:
                problems.append(f"line {number}: checksum mismatch"
                                + (" (incomplete tail ignored)" if number == len(lines) else ""))
                continue
            record["_revision"] = len(records) + 1  # journal revision (review F-11)
            records.append(record)
        return records, problems

    def replay(self, known_generations: List[str],
               run_id: Optional[str] = None) -> Dict[str, Any]:
        """Load + filter: records whose generationToken is foreign to the known
        chain are raised as rejected — never replayed as transitions (§4.4, F6).
        Records of another run are filtered out (review F-14)."""
        records, problems = self.read()
        known = set(known_generations)
        applied = [record for record in records
                   if str(record.get("generationToken")) in known
                   and (run_id is None or str(record.get("runId", "")) == run_id)]
        rejected = [record for record in records
                    if (run_id is None or str(record.get("runId", "")) == run_id)
                    and str(record.get("generationToken")) not in known]
        return {"applied": applied, "rejected": rejected, "problems": problems}


class StateRepository:
    """JSON snapshot as a REBUILDABLE PROJECTION of the journal (I3).

    Writes are atomic (write-to-temp + rename — RFC §4): a reader always sees
    a complete snapshot or the previous one, never a truncated state.
    """

    def __init__(self, path: str):
        self.path = path

    def save(self, run_state: Dict[str, Any]) -> None:
        directory = os.path.dirname(os.path.abspath(self.path))
        os.makedirs(directory, exist_ok=True)
        temp = self.path + ".tmp"
        with open(temp, "w", encoding="utf-8") as handle:
            json.dump(run_state, handle, indent=2, sort_keys=True, ensure_ascii=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.rename(temp, self.path)

    def load(self) -> Dict[str, Any]:
        if not os.path.isfile(self.path):
            return {}
        with open(self.path, "r", encoding="utf-8") as handle:
            return json.load(handle)

    def rebuild(self, run_id: str, log: EventLog,
                known_generations: List[str]) -> Dict[str, Any]:
        """Deterministic rebuild from the journal (RFC §5 step 2): in divergence,
        the journal decides — never the snapshot. The projection carries the
        full execution state the guards need (review F-05): statuses, attempts,
        evidenceIds, output artifact refs, invalidation revisions, transitive
        invalidation scope."""
        result = log.replay(known_generations, run_id=run_id)
        run_state: Dict[str, Any] = {"runId": run_id, "nodeExecutions": {},
                                     "invalidations": {},
                                     "projectedTransitionIds": []}
        for record in result["applied"]:
            self._project(run_state, record)
        self.save(run_state)
        run_state["rebuildProblems"] = result["problems"]
        run_state["rejectedRecords"] = result["rejected"]
        return run_state

    def _project(self, run_state: Dict[str, Any], record: Dict[str, Any]) -> None:
        """Apply one journal record to the projection (idempotent by transitionId)."""
        transition_id = str(record.get("transitionId", ""))
        projected = run_state.setdefault("projectedTransitionIds", [])
        if transition_id and transition_id in projected:
            return  # idempotent replay (I3, §5)
        node_id = str(record.get("nodeId", ""))
        executions = run_state.setdefault("nodeExecutions", {})
        entry = executions.setdefault(node_id, {
            "runId": record.get("runId", ""), "nodeId": node_id,
            "attempt": int(record.get("attempt", 1)), "status": "pending",
            "failureCounts": {"technical": 0, "quality": 0,
                              "invalidEvidence": 0, "permission": 0},
        })
        kind = record.get("kind")
        payload = record.get("payload") or {}
        if kind == "invalidation":
            # The invalidation record carries its resulting status, its
            # transitive scope (affected) and the invalidated evidence ids
            # (reviews F-05/F-12/F-13). It covers both the explicit I5
            # invalidation and the §5.3 orphan re-pin (payload.to = pending).
            entry["status"] = str(payload.get("to") or entry.get("status"))
            entry["attempt"] = int(record.get("attempt", 1))
            revisions = run_state.setdefault("invalidations", {})
            revisions[node_id] = record.get("_revision", 0)
            for affected in payload.get("affected", []) or []:
                # affected entries carry per-descendant arrival statuses
                # ({"nodeId", "to"}) — a running descendant lands on
                # cancelled, not pending (faithful projection, review F-05).
                if isinstance(affected, dict):
                    affected_id = str(affected.get("nodeId", ""))
                    affected_to = str(affected.get("to", "pending"))
                else:
                    affected_id, affected_to = str(affected), "pending"
                if not affected_id or affected_id == node_id:
                    continue
                affected_entry = executions.setdefault(affected_id, {
                    "runId": record.get("runId", ""), "nodeId": affected_id,
                    "attempt": 1, "status": "pending",
                    "failureCounts": {"technical": 0, "quality": 0,
                                      "invalidEvidence": 0, "permission": 0},
                })
                affected_entry["status"] = affected_to
                revisions[affected_id] = record.get("_revision", 0)
            for evidence_id in payload.get("invalidatedEvidenceIds", []) or []:
                markers = run_state.setdefault("invalidatedEvidenceIds", [])
                if evidence_id not in markers:
                    markers.append(evidence_id)
        elif kind == "effect":
            # An effect record carries the EFFECT PHASE (§7.2) — never a node
            # status: the projection stores it as a sub-state so that
            # prepared/dispatched/uncertain never corrupt the legal status
            # machine (I1).
            entry["effectPhase"] = str(payload.get("effectPhase") or record.get("to"))
        elif kind == "transition":
            entry["status"] = str(record.get("to") or entry.get("status"))
            # Each record describes the attempt it journalizes — the replay
            # stays faithful after a retry (review R-01).
            entry["attempt"] = int(record.get("attempt", entry.get("attempt", 1)))
            if record.get("to") == "running":
                entry["startedRevision"] = record.get("_revision", 0)
                # The input fingerprint travels in the running record (§6.2,
                # review F-05): the freshness guard (I7/§5.4) must work after
                # ANY rebuild.
                if payload.get("inputFingerprint"):
                    entry["inputFingerprint"] = str(payload["inputFingerprint"])
            if record.get("to") in ("completed", "failed", "cancelled"):
                entry["completedRevision"] = record.get("_revision", 0)
                # Evidence refs and artifact refs live in the completion payload
                # (review F-05 — the guards need them after any restart).
                if payload.get("evidenceIds"):
                    entry["evidenceIds"] = list(payload["evidenceIds"])
                if payload.get("outputArtifactRefs"):
                    entry["outputArtifactRefs"] = list(payload["outputArtifactRefs"])
            if record.get("to") == "failed" and payload.get("failureClass"):
                counts = entry.setdefault("failureCounts",
                                          {"technical": 0, "quality": 0,
                                           "invalidEvidence": 0, "permission": 0})
                counts[payload["failureClass"]] = counts.get(payload["failureClass"], 0) + 1
        if transition_id:
            projected.append(transition_id)


class EvidenceStore:
    """Append-only evidence persistence with invalidation markers (I5).

    Evidences are NEVER deleted: an invalidated evidence keeps its line plus
    a marker record (review technique F2). The journal record of an
    invalidation also carries the invalidated evidence ids (review F-13) —
    `reapply_from_journal` re-applies markers after a rebuild, from the
    source of truth alone.
    """

    def __init__(self, path: str, invalidations_path: str):
        self.path = path
        self.invalidations_path = invalidations_path

    def append(self, evidence: Dict[str, Any]) -> Dict[str, Any]:
        stamped = stamp_record(evidence)
        _append_line(self.path, canonical_json(stamped))
        return stamped

    def mark_invalidated(self, evidence_id: str, reason: str, at: str) -> Dict[str, Any]:
        if evidence_id in self._invalidated_ids():
            return {}  # idempotent marker (review F-13 re-application)
        marker = stamp_record({"evidenceId": evidence_id, "invalidatedAt": at,
                               "reason": reason, "marker": "evidence-invalidated"})
        _append_line(self.invalidations_path, canonical_json(marker))
        return marker

    def reapply_from_journal(self, evidence_ids: List[str], reason: str, at: str) -> int:
        """Re-apply invalidation markers after a journal-only rebuild (F-13)."""
        count = 0
        for evidence_id in evidence_ids:
            if self.mark_invalidated(evidence_id, reason, at):
                count += 1
        return count

    def _read_lines(self, path: str) -> List[Dict[str, Any]]:
        """Tolerant reader: a torn tail is skipped, never crash (review F-18)."""
        if not os.path.isfile(path):
            return []
        records: List[Dict[str, Any]] = []
        with open(path, "r", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                try:
                    record = json.loads(line)
                except ValueError:
                    continue
                if isinstance(record, dict):
                    records.append(record)
        return records

    def _invalidated_ids(self) -> set:
        return {str(record.get("evidenceId", ""))
                for record in self._read_lines(self.invalidations_path)}

    def list_valid(self) -> List[Dict[str, Any]]:
        """Valid (never-invalidated) evidences only."""
        invalidated = self._invalidated_ids()
        return [record for record in self._read_lines(self.path)
                if str(record.get("evidenceId", "")) not in invalidated]

    def list_all(self) -> List[Dict[str, Any]]:
        """Every evidence ever recorded — including invalidated ones (I5:
        history preserved, never deleted)."""
        return self._read_lines(self.path)


def new_run_id() -> str:
    """Run identity: unique, immutable once persisted (RFC §2.3, review F-14)."""
    return f"run-{uuid.uuid4().hex[:12]}"
