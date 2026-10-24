"""Execution Graph Core (pilot, RFC docs/graph-engineering/06-execution-graph-rfc.md).

Modules:
- contracts: formal contract validation (M4)
- transition_engine: legal NodeExecution transitions + invalidation (M1)
- persistence: EventLog / StateRepository / EvidenceStore (M2)
- scheduler: sequential flock+fencing scheduler with the journaled effect
  protocol (M3)

stdlib only — Python 3.9+.
"""
from .contracts import (
    ENGINE_SCHEMA_VERSION, NODE_STATUSES, validate_evidence_record,
    validate_effect_record, validate_graph_definition,
    validate_node_definition, validate_node_execution,
    validate_schema_version, validate_transition_record,
)
from .transition_engine import (
    IllegalTransition, NODE_TRANSITIONS, StaleCompletion, StaleGeneration,
    budget_exhausted, count_failure, invalidate_node, mark_transition,
    node_status, repin_orphan_running, replay_records,
)
from .persistence import (
    EventLog, EvidenceStore, StateRepository, new_run_id, record_checksum,
    stamp_record,
)
from .scheduler import (
    EffectDispatcher, GraphScheduler, LockHeld, PlanMismatch,
    compute_input_fingerprint, derive_classification,
)

__all__ = [
    "ENGINE_SCHEMA_VERSION", "NODE_STATUSES", "NODE_TRANSITIONS",
    "EffectDispatcher", "EventLog", "EvidenceStore", "GraphScheduler",
    "IllegalTransition", "LockHeld", "PlanMismatch", "StateRepository",
    "StaleCompletion", "StaleGeneration", "budget_exhausted",
    "compute_input_fingerprint", "count_failure", "derive_classification",
    "invalidate_node", "mark_transition", "new_run_id", "node_status",
    "record_checksum", "repin_orphan_running", "replay_records",
    "stamp_record", "validate_evidence_record", "validate_effect_record",
    "validate_graph_definition", "validate_node_definition",
    "validate_node_execution", "validate_schema_version",
    "validate_transition_record",
]
