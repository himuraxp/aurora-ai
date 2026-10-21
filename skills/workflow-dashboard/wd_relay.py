#!/usr/bin/env python3
"""Workflow Dashboard — relais todowrite (J4, niveau RELAIS NATIF).

Mapping déterministe 1:1 du payload `todowrite` vers un ProgressTopic :

- **topicId = UUID v5** (namespace relais dérivé du namespace adaptateur,
  seed `todowrite:<sessionID>`) — l'association session→topic est stable
  SANS état : la réconciliation après reprise retombe sur le même topic
  (improvement t4 #3).
- **pending→PENDING, in_progress→RUNNING, completed→DONE** — statut inconnu
  → PENDING + detail `statut non reconnu` (jamais d'invention : le mapping
  d'inférence M2 a été rejeté au tour 1 du consensus).
- **Réconciliation COMPLÈTE à chaque event** : le payload est la source de
  vérité — les statuts fournis GAGNENT (set_steps avec statut forcé), les
  todos absentes disparaissent, les nouvelles apparaissent.

Ce module est la voie d'écriture du relais (CLI-only, appelé par le plugin
`wd-relay.ts` via execFile argv-array — jamais d'édition directe du JSON).
Sorties JSON garanties ; exit `0` ok · `1` erreur · `2` usage.

Limite assumée : `todos: []` (payload vidé) → topic sans steps, dérivé
« 0/0 » EN COURS à l'affichage — le payload ne permet pas d'inventer une
clôture ; l'âge d'updatedAt reste l'indicateur.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import uuid
from typing import Any, Dict, List, Optional

import wd_core

RELAY_SOURCE = "todowrite-relay"
STATUS_MAP = {"pending": "PENDING", "in_progress": "RUNNING",
              "completed": "DONE"}
# Namespace racine du Workflow Dashboard (adaptateur task-workflow) ;
# le namespace du relais en est dérivé de façon déterministe.
ROOT_NAMESPACE = uuid.UUID("3e5a1c74-9d2b-4f60-8a71-6c0b5e9d2f41")

# Le label vient du LLM (donnée NON fiable) et traverse JSON → argv →
# disque → renderer → terminal : les caractères de contrôle/ANSI sont
# neutralisés (review J4 F3 — un \x1b[ ou \r corrompt le pane).
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")


def relay_namespace() -> uuid.UUID:
    return uuid.uuid5(ROOT_NAMESPACE, "todowrite-relay")


def topic_id_for_session(session_id: str) -> str:
    """Association session→topic stable SANS état (UUID v5)."""
    return str(uuid.uuid5(relay_namespace(), f"todowrite:{session_id}"))


def map_todo(index: int, todo: Any) -> Dict[str, Any]:
    """Mapping 1:1 d'un todo : id d'index, label = content, statut mappé."""
    if not isinstance(todo, dict):
        raise wd_core.ContractError(f"todo #{index} is not an object")
    content = _CONTROL_CHARS.sub(" ", str(todo.get("content") or ""))
    content = re.sub(r"\s+", " ", content).strip()
    if not content:
        raise wd_core.ContractError(f"todo #{index} has empty content")
    status_raw = todo.get("status")
    mapped = STATUS_MAP.get(str(status_raw or "").lower())
    step: Dict[str, Any] = {"id": f"todo-{index}", "label": content}
    if mapped is not None:
        step["status"] = mapped
    else:
        # jamais d'invention : statut inconnu = PENDING + trace du brut
        step["status"] = "PENDING"
        step["detail"] = f"statut non reconnu: {status_raw!r}"
    return step


def reconcile(session_id: str, todos: List[Any],
              root: Optional[str] = None) -> Dict[str, Any]:
    """Réconcilie COMPLÈTEMENT le topic de session avec le payload."""
    if not session_id or not str(session_id).strip():
        raise wd_core.ContractError("session_id is required")
    topic_id = topic_id_for_session(str(session_id))
    steps = [map_todo(index, todo) for index, todo in enumerate(todos)]
    title = f"Todos — session {str(session_id)[:8]}"
    created = False
    if wd_core.find_topic_path(topic_id, root=root) is None:
        try:
            wd_core.create_topic(title=title, kind="plan", source=RELAY_SOURCE,
                                 scope="session", session_id=str(session_id),
                                 topic_id=topic_id, root=root)
            created = True
        except wd_core.TopicExistsError:
            # course perdue : l'autre writer a créé le topic → réconcilier
            created = False
    wd_core.set_steps(topic_id, steps, root=root)  # statuts forcés : payload gagne
    return {"ok": True, "topicId": topic_id, "created": created}


def _emit(payload: Dict[str, Any]) -> int:
    print(json.dumps(payload, ensure_ascii=False))
    return 0 if payload.get("ok") else 1


def _fail(message: str) -> int:
    return _emit({"ok": False, "error": message})


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="wd_relay",
        description="Workflow Dashboard — relais todowrite (mapping 1:1)")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser(
        "reconcile",
        help="réconcilie le topic de session avec le payload todowrite")
    p.add_argument("session_id", help="sessionID opencode (context.sessionID)")
    p.add_argument("todos", help="payload todowrite : JSON array, ou '-' = stdin")
    args = parser.parse_args(argv)
    # contrat des sorties : reconcile OK/erreur = JSON sur stdout (exit 0/1) ;
    # l'usage argparse = texte sur stderr (exit 2), pattern wd_publish identique
    try:
        raw = sys.stdin.read() if args.todos == "-" else args.todos
    except OSError as exc:
        return _fail(f"stdin unreadable: {exc}")
    try:
        todos = json.loads(raw)
    except ValueError as exc:
        return _fail(f"todos is not valid JSON: {exc}")
    if not isinstance(todos, list):
        return _fail("todos must be a JSON array")
    try:
        return _emit(reconcile(args.session_id, todos))
    except (wd_core.ContractError, wd_core.LockError, OSError) as exc:
        # garantie « toutes les sorties sont JSON » (le plugin parse toujours)
        return _fail(f"{type(exc).__name__}: {exc}")


if __name__ == "__main__":
    sys.exit(main())
