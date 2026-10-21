"""Workflow Dashboard — adaptateur task-workflow (source NATIVE, niveau 1).

Traduit à la volée la persistance task-workflow (tw_state.py) en ProgressTopic
du contrat v1. Règle validée (t3 improvement 3) : adaptateur DIRECT, AUCUN
miroir progress/ — le JSON task-workflow reste la seule source d'autorité de
ses exécutions ; ce module n'écrit jamais.

- pivot de corrélation : worktreePath (champ réel du state, 21 états inspectés)
- topicId : UUID v5 déterministe (workflow) — même workflow => même topic,
  pas de doublon au rafraîchissement, jamais dérivé du titre
- normalisation d'affichage : PASSED→DONE, WAITING_APPROVAL→BLOCKED (+detail
  préservant la valeur originale) — les originaux ne sont JAMAIS touchés
- lecture tolérante : fichier corrompu ou nom != workflowId => signalé, pas de
  crash (un état réel corrompu a été observé en conditions réelles).
"""

from __future__ import annotations

import os
import uuid
from typing import Any, Dict, List, Optional

import wd_core

DEFAULT_STATE_DIR = os.path.expanduser("~/.config/opencode/task-workflows")
ENV_STATE_DIR = "WD_TASKWORKFLOW_DIR"

# Namespace fixé (déterminisme entre runs — pas un secret, pas une identité machine).
TASKWORKFLOW_TOPIC_NS = uuid.UUID("3e5a1c74-9d2b-4f60-8a71-6c0b5e9d2f41")

# Miroir de tw_report.PHASE_NAMES (source : skills/task-workflow/tw_report.py).
PHASE_NAMES = {
    1: "Contexte", 2: "Worktree", 3: "Analyse", 4: "Code", 5: "QA",
    6: "Review", 7: "MR", 8: "Finalisation", 9: "Rapport",
}

# Normalisation d'affichage : (statut contrat, detail de préservation ou None).
STATUS_MAP = {
    "PASSED": ("DONE", None),
    "RUNNING": ("RUNNING", None),
    "PENDING": ("PENDING", None),
    "FAILED": ("FAILED", None),
    "BLOCKED": ("BLOCKED", None),
    "SKIPPED": ("SKIPPED", None),
    "WAITING_APPROVAL": ("BLOCKED", "WAITING_APPROVAL — attente validation PO"),
}

KIND = "skill"
SOURCE = "task-workflow"


def state_dir() -> str:
    return os.environ.get(ENV_STATE_DIR) or DEFAULT_STATE_DIR


def _topic_title(state: Dict[str, Any]) -> str:
    plan = state.get("plan")
    objective = plan.get("objective") if isinstance(plan, dict) else None
    for candidate in (objective, state.get("featureBranch"), state.get("workflowId")):
        if isinstance(candidate, str) and candidate.strip():
            return candidate
    return state.get("workflowId") or "task-workflow"


def state_to_topic(state: Dict[str, Any]) -> Dict[str, Any]:
    """Traduit un état task-workflow valide en ProgressTopic (à la volée)."""
    workflow_id = state.get("workflowId")
    if not isinstance(workflow_id, str) or not workflow_id.strip():
        raise wd_core.ContractError("state has no workflowId")
    phase_statuses = state.get("phaseStatuses")
    if not isinstance(phase_statuses, dict):
        phase_statuses = {}
    steps: List[Dict[str, Any]] = []
    for phase in sorted(PHASE_NAMES):
        entry = phase_statuses.get(str(phase)) or {}
        if not isinstance(entry, dict):
            entry = {}
        raw_status = entry.get("status") or "PENDING"
        status, detail = STATUS_MAP.get(raw_status, ("PENDING", f"statut non reconnu: {raw_status}"))
        step: Dict[str, Any] = {"id": f"phase-{phase}", "label": PHASE_NAMES[phase],
                                "status": status}
        if detail:
            step["detail"] = detail
        updated = entry.get("at")
        if isinstance(updated, str) and wd_core.is_iso_datetime(updated):
            step["updatedAt"] = updated
        steps.append(step)
    worktree_path = state.get("worktreePath")
    created = state.get("createdAt") if wd_core.is_iso_datetime(state.get("createdAt")) \
        else wd_core.now_iso()
    updated = state.get("updatedAt") if wd_core.is_iso_datetime(state.get("updatedAt")) \
        else created
    topic: Dict[str, Any] = {
        "schemaVersion": wd_core.SCHEMA_VERSION,
        "topicId": str(uuid.uuid5(TASKWORKFLOW_TOPIC_NS, f"task-workflow:{workflow_id}")),
        "title": _topic_title(state),
        "kind": KIND,
        "source": SOURCE,
        "scope": "worktree" if worktree_path else "global",
        "steps": steps,
        "createdAt": created,
        "updatedAt": updated,
        "revision": 1,
    }
    if worktree_path:
        topic["worktreePath"] = worktree_path
    # review J1 #3 : la session de claim réelle vit dans handoff.session
    # (tw_state.claim_handoff) — le champ top-level "claimSession" n'existe pas.
    handoff = state.get("handoff")
    session_id = handoff.get("session") if isinstance(handoff, dict) else None
    if isinstance(session_id, str) and session_id.strip():
        topic["sessionId"] = session_id
    wd_core.validate_topic(topic)  # le topic traduit respecte le contrat
    return topic


def iter_state_files(directory: Optional[str] = None) -> List[str]:
    """Fichiers d'état candidats : *.json dont le nom (sans .json) == workflowId
    — exclut les artefacts (ex. *.design.json) par construction."""
    directory = directory or state_dir()
    if not os.path.isdir(directory):
        return []
    paths: List[str] = []
    for name in sorted(os.listdir(directory)):
        if not name.endswith(".json") or name.startswith("."):
            continue
        path = os.path.join(directory, name)
        if not os.path.isfile(path):
            continue
        data = wd_core._read_json(path)
        if data is None:
            paths.append(path)  # corrompu : laissé à list_topics pour le signalement
            continue
        if isinstance(data, dict) and data.get("workflowId") == os.path.splitext(name)[0]:
            paths.append(path)
    return paths


def list_topics(directory: Optional[str] = None) -> Dict[str, Any]:
    """Tous les sujets task-workflow traduits + fichiers ignorés/corrompus."""
    directory = directory or state_dir()
    topics: List[Dict[str, Any]] = []
    ignored: List[Dict[str, Any]] = []
    for path in iter_state_files(directory):
        data = wd_core._read_json(path)
        if data is None:
            ignored.append({"file": os.path.basename(path), "reason": "unreadable JSON"})
            continue
        if not isinstance(data, dict) or data.get("workflowId") != \
                os.path.splitext(os.path.basename(path))[0]:
            ignored.append({"file": os.path.basename(path), "reason": "not a workflow state"})
            continue
        try:
            topics.append(state_to_topic(data))
        except (wd_core.ContractError, KeyError, TypeError) as exc:
            ignored.append({"file": os.path.basename(path), "reason": str(exc)})
    return {"topics": topics, "ignored": ignored}
