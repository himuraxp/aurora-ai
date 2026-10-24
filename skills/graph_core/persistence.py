"""Persistence layer of the Execution Graph Core (RFC I3, §2.6, §4, §5).

The append-only journal is the SOURCE OF TRUTH; the JSON snapshot is a
rebuildable PROJECTION (invariant I3 — review PO itération 2, P0.1). All
interfaces are injectable for test doubles (review technique F19).

- EventLog: JSONL, one TransitionRecord per line, per-record sha256 checksum,
  partial-write detection (incomplete tail ignored — never accepted as a
  confirmed transition), fsync of the file AND of the directory on
  creation/rotation.
- StateRepository: atomic snapshot (write-to-temp + rename) rebuilt by
  idempotent replay from the journal.
- EvidenceStore: append-only evidence with INVALIDATION MARKERS — evidences
  are never physically deleted (invariant I5, review technique F2).
"""
from __future__ import annotations

import hashlib
import json
import os
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


class EventLog:
    """Append-only JSONL journal — the transactional source of truth (I3)."""

    def __init__(self, path: str):
        self.path = path

    def append(self, record: Dict[str, Any]) -> Dict[str, Any]:
        """Append ONE record as a single line + fsync (the durable commit point)."""
        stamped = stamp_record(record)
        created = not os.path.isfile(self.path)
        directory = os.path.dirname(os.path.abspath(self.path))
        os.makedirs(directory, exist_ok=True)
        if created:
            _fsync_directory(directory)  # creation covered by directory fsync (I3)
        with open(self.path, "a", encoding="utf-8") as handle:
            handle.write(canonical_json(stamped) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
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
        lines = open(self.path, "r", encoding="utf-8").read().splitlines()
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
            records.append(record)
        return records, problems

    def replay(self, known_generations: List[str]) -> Dict[str, Any]:
        """Load + filter: records whose generationToken is foreign to the known
        chain are raised as rejected — never replayed as transitions (§4.4, F6)."""
        records, problems = self.read()
        known = set(known_generations)
        applied = [record for record in records
                   if str(record.get("generationToken")) in known]
        rejected = [record for record in records
                    if str(record.get("generationToken")) not in known]
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

    def rebuild(self, run_id: str, log: EventLog, known_generations: List[str]) -> Dict[str, Any]:
        """Deterministic rebuild from the journal (RFC §5 step 2): in divergence,
        the journal decides — never the snapshot."""
        result = log.replay(known_generations)
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
            # The invalidation record itself carries the resulting status.
            entry["status"] = str(payload.get("to") or entry.get("status"))
            run_state.setdefault("invalidations", {})[node_id] = record.get("timestamp", "")
        elif kind in ("transition", "effect"):
            entry["status"] = str(record.get("to") or entry.get("status"))
        if transition_id:
            projected.append(transition_id)


class EvidenceStore:
    """Append-only evidence persistence with invalidation markers (I5).

    Evidences are NEVER deleted: an invalidated evidence keeps its line plus
    a marker record (review technique F2). `is_valid` decides.
    """

    def __init__(self, path: str, invalidations_path: str):
        self.path = path
        self.invalidations_path = invalidations_path

    def append(self, evidence: Dict[str, Any]) -> Dict[str, Any]:
        stamped = stamp_record(evidence)
        directory = os.path.dirname(os.path.abspath(self.path))
        os.makedirs(directory, exist_ok=True)
        with open(self.path, "a", encoding="utf-8") as handle:
            handle.write(canonical_json(stamped) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        return stamped

    def mark_invalidated(self, evidence_id: str, reason: str, at: str) -> Dict[str, Any]:
        marker = stamp_record({"evidenceId": evidence_id, "invalidatedAt": at,
                               "reason": reason, "marker": "evidence-invalidated"})
        with open(self.invalidations_path, "a", encoding="utf-8") as handle:
            handle.write(canonical_json(marker) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        return marker

    def _invalidated_ids(self) -> set:
        if not os.path.isfile(self.invalidations_path):
            return set()
        ids: set = set()
        with open(self.invalidations_path, "r", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                try:
                    record = json.loads(line)
                except ValueError:
                    continue  # incomplete tail — same treatment as EventLog
                ids.add(str(record.get("evidenceId", "")))
        return ids

    def list_valid(self) -> List[Dict[str, Any]]:
        """Valid (never-invalidated) evidences only."""
        invalidated = self._invalidated_ids()
        valid: List[Dict[str, Any]] = []
        if not os.path.isfile(self.path):
            return valid
        with open(self.path, "r", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                try:
                    evidence = json.loads(line)
                except ValueError:
                    continue
                if isinstance(evidence, dict) \
                        and str(evidence.get("evidenceId", "")) not in invalidated:
                    valid.append(evidence)
        return valid

    def list_all(self) -> List[Dict[str, Any]]:
        """Every evidence ever recorded — including invalidated ones (I5:
        history preserved, never deleted)."""
        if not os.path.isfile(self.path):
            return []
        with open(self.path, "r", encoding="utf-8") as handle:
            return [json.loads(line) for line in handle if line.strip()]
