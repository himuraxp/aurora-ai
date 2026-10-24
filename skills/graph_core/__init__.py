"""Execution Graph Core (pilot, RFC docs/graph-engineering/06-execution-graph-rfc.md).

Modules:
- contracts: formal contract validation (M4)
- transition_engine: legal NodeExecution transitions + invalidation (M1)
- persistence: EventLog / StateRepository / EvidenceStore (M2)
- scheduler: sequential flock+fencing scheduler (M3)

stdlib only — Python 3.9+.
"""
from .contracts import (
    ENGINE_SCHEMA_VERSION, NODE_STATUSES, validate_effect_record,
    validate_graph_definition, validate_node_definition, validate_node_execution,
    validate_schema_version, validate_transition_record,
)
from .transition_engine import (
    IllegalTransition, NODE_TRANSITIONS, StaleCompletion, StaleGeneration,
    count_failure, invalidate_node, mark_transition, node_status, replay_records,
)
from .persistence import EventLog, EvidenceStore, StateRepository, record_checksum, stamp_record
from .scheduler import GraphScheduler, LockHeld

__all__ = [
    "ENGINE_SCHEMA_VERSION", "NODE_STATUSES", "NODE_TRANSITIONS",
    "EventLog", "EvidenceStore", "GraphScheduler", "IllegalTransition",
    "LockHeld", "StateRepository", "StaleCompletion", "StaleGeneration",
    "count_failure", "invalidate_node", "mark_transition", "node_status",
    "record_checksum", "replay_records", "stamp_record",
    "validate_effect_record", "validate_graph_definition",
    "validate_node_definition", "validate_node_execution",
    "validate_schema_version", "validate_transition_record",
]
