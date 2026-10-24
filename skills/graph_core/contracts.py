"""Contracts of the Execution Graph Core (RFC 06-execution-graph-rfc.md §2).

Pure validation of the six formal contracts — schemaVersion compatibility
{N, N-1}, structural rules, and invariant I9 at contract level (a node of
type "agent" can never carry a write permission). stdlib only.

Spec source: docs/graph-engineering/06-execution-graph-rfc.md (merged PR #48).
Any divergence implementation/RFC is an implementation bug.
"""
from __future__ import annotations

from typing import Any, Dict, List

ENGINE_SCHEMA_VERSION = 1
NODE_TYPES = ("agent", "tool", "human", "gate")
NODE_STATUSES = ("pending", "running", "blocked", "completed", "failed", "cancelled")
EFFECT_CLASSES = ("safe", "reconcile", "block")
EFFECT_PHASES = ("prepared", "dispatched", "confirmed", "uncertain", "failed", "reconciled")
RECORD_KINDS = ("transition", "invalidation", "effect", "human-intervention")
PERMISSION_KINDS = ("read:", "write:")
FAILURE_COUNT_KEYS = ("technical", "quality", "invalidEvidence", "permission")
# Reserved for M7+ (review technique F15): not exercised by S1-S7 nor M1-M4
# at pilot stage — rejected at instantiation (fail-closed).
RESERVED_FIELDS = ("filiation", "concurrencyKey")


def validate_schema_version(version: Any) -> List[str]:
    """Moteur supports {N, N-1}; anything else is rejected (RFC §2.1, F18)."""
    if type(version) is not int:
        return [f"schemaVersion must be an integer (got {version!r})"]
    if version < 1:
        return ["schemaVersion must be >= 1"]
    if version not in (ENGINE_SCHEMA_VERSION, ENGINE_SCHEMA_VERSION - 1):
        return [
            f"schemaVersion {version} is not supported by engine v{ENGINE_SCHEMA_VERSION} "
            f"(compat window: {{N, N-1}} = {ENGINE_SCHEMA_VERSION - 1}..{ENGINE_SCHEMA_VERSION})"
        ]
    return []


def _non_empty_str(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def validate_effect_policy(policy: Any, node_type: str, node_id: str) -> List[str]:
    """effectPolicy rules (RFC §2.2, §7.1): mandatory write rules, I9 for agents."""
    problems: List[str] = []
    if not isinstance(policy, dict):
        return [f"nodes[{node_id}].effectPolicy must be an object"]
    mode = policy.get("mode")
    if mode not in ("read", "write"):
        problems.append(f"nodes[{node_id}].effectPolicy.mode must be 'read' or 'write'")
    if node_type == "agent":
        # I9 (review technique F4): an agent node must not be a write surface.
        if mode == "write":
            problems.append(
                f"nodes[{node_id}]: agent nodes cannot declare effectPolicy.mode=write "
                f"(invariant I9 — external writes go through a tool node)")
        for permission in policy.get("_", []) or []:
            if str(permission).startswith("write:"):
                problems.append(f"nodes[{node_id}]: agent carries a write permission (I9)")
    if mode == "write":
        if not _non_empty_str(policy.get("idempotencyKey")):
            problems.append(
                f"nodes[{node_id}]: effectPolicy.idempotencyKey is mandatory when mode=write")
        reconciliation = policy.get("reconciliation")
        if reconciliation not in ("getBeforePost", "contentHash", "none"):
            problems.append(
                f"nodes[{node_id}].effectPolicy.reconciliation must be "
                f"getBeforePost | contentHash | none")
        if policy.get("onUncertainOutcome") not in ("reconcile", "block"):
            problems.append(
                f"nodes[{node_id}].effectPolicy.onUncertainOutcome must be reconcile | block")
    return problems


def validate_node_definition(node: Any, index: int) -> List[str]:
    """NodeDefinition contract (RFC §2.2)."""
    problems: List[str] = []
    if not isinstance(node, dict):
        return [f"nodes[{index}] must be an object"]
    node_id = str(node.get("id", f"<index {index}>"))
    problems.extend(
        f"nodes[{node_id}].{problem}" for problem in validate_schema_version(node.get("schemaVersion")))
    if not _non_empty_str(node.get("id")):
        problems.append("node id must be a non-empty string")
    if node.get("type") not in NODE_TYPES:
        problems.append(f"nodes[{node_id}].type must be one of {list(NODE_TYPES)}")
    deps = node.get("deps")
    if not isinstance(deps, list) or not all(_non_empty_str(dep) for dep in deps):
        problems.append(f"nodes[{node_id}].deps must be a list of non-empty strings")
    permissions = node.get("permissions")
    if not isinstance(permissions, list) or not all(
            isinstance(p, str) and p.startswith(PERMISSION_KINDS) for p in permissions):
        problems.append(
            f"nodes[{node_id}].permissions must be typed 'read:<domain>'/'write:<domain>' "
            f"(review technique F4/I9)")
    elif node.get("type") == "agent" and any(str(p).startswith("write:") for p in permissions):
        problems.append(
            f"nodes[{node_id}]: agent nodes cannot carry a write permission (invariant I9)")
    evidence_policy = node.get("evidencePolicy")
    if not isinstance(evidence_policy, dict):
        problems.append(f"nodes[{node_id}].evidencePolicy must be an object")
    else:
        required = evidence_policy.get("required")
        if not isinstance(required, list) or not all(
                r in ("exitCode", "artifact", "structuredVerdict", "humanApproval")
                for r in required):
            problems.append(f"nodes[{node_id}].evidencePolicy.required has unknown entries")
        freshness = evidence_policy.get("freshness")
        if not isinstance(freshness, dict) or not isinstance(
                freshness.get("inputFingerprint"), bool):
            problems.append(
                f"nodes[{node_id}].evidencePolicy.freshness.inputFingerprint must be a boolean")
    budgets = node.get("failureBudgets")
    if not isinstance(budgets, dict):
        problems.append(f"nodes[{node_id}].failureBudgets must be an object (invariant I8)")
    else:
        for key in ("technical", "quality"):
            value = budgets.get(key)
            if type(value) is not int or value < 0:
                problems.append(
                    f"nodes[{node_id}].failureBudgets.{key} must be a non-negative integer")
        for reserved in ("invalidEvidence", "permission"):
            if reserved in budgets:
                problems.append(
                    f"nodes[{node_id}].failureBudgets.{reserved}: no budget exists for "
                    f"never-auto-resolved failure classes (I8)")
    retry = node.get("retryPolicy")
    if not isinstance(retry, dict) or type(retry.get("maxAttempts")) is not int \
            or retry.get("maxAttempts", 0) < 1 \
            or retry.get("backoff") not in ("none", "fixed", "exponential"):
        problems.append(f"nodes[{node_id}].retryPolicy is invalid")
    if type(node.get("timeoutSeconds")) is not int or node.get("timeoutSeconds", 0) < 1:
        problems.append(f"nodes[{node_id}].timeoutSeconds must be a positive integer")
    resource_policy = node.get("resourcePolicy")
    if resource_policy is not None:
        if not isinstance(resource_policy, dict):
            problems.append(f"nodes[{node_id}].resourcePolicy must be an object or absent")
        elif "concurrencyKey" in resource_policy:
            problems.append(
                f"nodes[{node_id}].resourcePolicy.concurrencyKey is RESERVED for M7+ "
                f"(review technique F15 — the pilot executes sequentially in topo-order)")
    if not isinstance(node.get("outputSchema"), dict):
        problems.append(f"nodes[{node_id}].outputSchema must be an object (JSON schema)")
    problems.extend(validate_effect_policy(node.get("effectPolicy"),
                                           str(node.get("type")), node_id))
    return problems


def _reachable_from(nodes: Dict[str, dict], start_ids: List[str]) -> set:
    seen: set = set()
    stack = list(start_ids)
    while stack:
        current = stack.pop()
        if current in seen:
            continue
        seen.add(current)
        stack.extend(nodes.get(current, {}).get("deps", []))
    return seen


def _has_cycle(nodes: Dict[str, dict]) -> bool:
    """Kahn's algorithm — a DAG is mandatory (RFC §2.1, invariant I4)."""
    indegree = {node_id: 0 for node_id in nodes}
    for node in nodes.values():
        for dep in node.get("deps", []):
            if dep in indegree:
                indegree[node["id"]] += 1
    queue = [node_id for node_id, degree in indegree.items() if degree == 0]
    visited = 0
    while queue:
        current = queue.pop()
        visited += 1
        for node in nodes.values():
            if current in node.get("deps", []):
                indegree[node["id"]] -= 1
                if indegree[node["id"]] == 0:
                    queue.append(node["id"])
    return visited != len(nodes)


def validate_graph_definition(graph: Any) -> List[str]:
    """GraphDefinition contract (RFC §2.1): schemaVersion window, multi-root
    initialNodes, DAG check (I4), reserved fields rejected, I9 at contract level."""
    problems: List[str] = []
    if not isinstance(graph, dict):
        return ["GraphDefinition is not an object"]
    problems.extend(validate_schema_version(graph.get("schemaVersion")))
    for key in ("graphId", "version"):
        if not _non_empty_str(graph.get(key)):
            problems.append(f"GraphDefinition.{key} must be a non-empty string")
    if "filiation" in graph:
        problems.append(
            "GraphDefinition.filiation is RESERVED for M7+ (review technique F15) — "
            "rejected at pilot stage")
    nodes_list = graph.get("nodes")
    if not isinstance(nodes_list, list) or not nodes_list:
        return problems + ["GraphDefinition.nodes must be a non-empty list"]
    nodes: Dict[str, dict] = {}
    for index, node in enumerate(nodes_list):
        problems.extend(validate_node_definition(node, index))
        node_id = node.get("id") if isinstance(node, dict) else None
        if _non_empty_str(node_id):
            if node_id in nodes:
                problems.append(f"duplicate node id: {node_id}")
            nodes[node_id] = node
    initial_nodes = graph.get("initialNodes")
    if not isinstance(initial_nodes, list) or not initial_nodes \
            or not all(_non_empty_str(n) for n in initial_nodes):
        problems.append("GraphDefinition.initialNodes must be a non-empty list of node ids "
                        "(multi-root, review technique F7)")
    else:
        for root in initial_nodes:
            if root not in nodes:
                problems.append(f"GraphDefinition.initialNodes references unknown node: {root}")
        if len(set(initial_nodes)) != len(initial_nodes):
            problems.append("GraphDefinition.initialNodes contains duplicates")
        # Roots must have no deps (they ARE the roots of the DAG).
        for root in initial_nodes:
            if root in nodes and nodes[root].get("deps"):
                problems.append(f"initial node {root} declares deps — roots must be dependency-free")
    # Unknown deps.
    for node in nodes.values():
        for dep in node.get("deps", []):
            if dep not in nodes:
                problems.append(f"node {node.get('id')} references unknown dependency: {dep}")
    # I4: acyclic.
    if len(nodes) == len(nodes_list) and not any(
            str(dep) not in nodes for node in nodes.values() for dep in node.get("deps", [])):
        if _has_cycle(nodes):
            problems.append("GraphDefinition.nodes contains a cycle (invariant I4 — DAG mandatory)")
    return problems


def validate_node_execution(execution: Any) -> List[str]:
    """NodeExecution contract (RFC §2.3): status enum, attempt >= 1,
    complete failureCounts (invariant I8, review technique F8)."""
    problems: List[str] = []
    if not isinstance(execution, dict):
        return ["NodeExecution is not an object"]
    if not _non_empty_str(execution.get("runId")):
        problems.append("NodeExecution.runId must be a non-empty string")
    if not _non_empty_str(execution.get("nodeId")):
        problems.append("NodeExecution.nodeId must be a non-empty string")
    attempt = execution.get("attempt")
    if type(attempt) is not int or attempt < 1:
        problems.append("NodeExecution.attempt must be a positive integer (1-based)")
    if execution.get("status") not in NODE_STATUSES:
        problems.append(f"NodeExecution.status must be one of {list(NODE_STATUSES)}")
    fingerprint = execution.get("inputFingerprint")
    if not isinstance(fingerprint, str) or not fingerprint:
        problems.append("NodeExecution.inputFingerprint must be a non-empty string "
                        "(constant string when no component applies, RFC §6.2)")
    counts = execution.get("failureCounts")
    if not isinstance(counts, dict) or set(counts.keys()) != set(FAILURE_COUNT_KEYS) \
            or not all(type(counts.get(key)) is int and counts[key] >= 0
                       for key in FAILURE_COUNT_KEYS):
        problems.append(
            f"NodeExecution.failureCounts must carry exactly {list(FAILURE_COUNT_KEYS)} "
            f"as non-negative integers (invariant I8)")
    return problems


def validate_effect_record(record: Any) -> List[str]:
    """EffectRecord contract (RFC §2.5): idempotencyKey, classification, phase."""
    problems: List[str] = []
    if not isinstance(record, dict):
        return ["EffectRecord is not an object"]
    if not _non_empty_str(record.get("effectId")):
        problems.append("EffectRecord.effectId must be a non-empty string")
    if not _non_empty_str(record.get("idempotencyKey")):
        problems.append("EffectRecord.idempotencyKey must be a non-empty string")
    if record.get("classification") not in EFFECT_CLASSES:
        problems.append(f"EffectRecord.classification must be one of {list(EFFECT_CLASSES)}")
    if record.get("phase") not in EFFECT_PHASES:
        problems.append(f"EffectRecord.phase must be one of {list(EFFECT_PHASES)}")
    if not _non_empty_str(record.get("requestedAt")):
        problems.append("EffectRecord.requestedAt must be a non-empty ISO timestamp")
    return problems


def validate_transition_record(record: Any) -> List[str]:
    """TransitionRecord contract (RFC §2.6): the journal's source-of-truth unit."""
    problems: List[str] = []
    if not isinstance(record, dict):
        return ["TransitionRecord is not an object"]
    for key in ("transitionId", "runId", "nodeId", "generationToken", "timestamp", "checksum"):
        if not _non_empty_str(record.get(key)):
            problems.append(f"TransitionRecord.{key} must be a non-empty string")
    if record.get("kind") not in RECORD_KINDS:
        problems.append(f"TransitionRecord.kind must be one of {list(RECORD_KINDS)}")
    attempt = record.get("attempt")
    if type(attempt) is not int or attempt < 1:
        problems.append("TransitionRecord.attempt must be a positive integer")
    if "to" not in record:
        problems.append("TransitionRecord.to is required (arrival status or invalidation scope)")
    return problems
