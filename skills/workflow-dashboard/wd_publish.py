#!/usr/bin/env python3
"""Workflow Dashboard — CLI de publication (garantie DÉCLARATIVE, niveau 3).

Chemin d'écriture contrôlé du contrat ProgressTopic (pattern tw_state notify :
l'agent publie au fil de l'eau, l'édition manuelle du JSON est interdite).
Toutes les sorties sont JSON ; exit 0 = ok, 1 = erreur (contrat/introuvable),
2 = usage.

Commandes :
  create   --title T --kind skill|plan|custom --source <s> --scope global|worktree|session
           [--worktree-path P] [--session-id ID] [--parent-topic-id PID]
           [--step "id=label"]... [--step-detail "id=detail"]...
  step     <topicId> <stepId> <status> [--detail D] [--label L]
  add-step <topicId> "id=label" [--parent-id PID] [--detail D]
  set-steps <topicId> "id=label" ["id=label"...]     (change-plan, états conservés)
  close    <topicId> --status DONE|FAILED|SKIPPED [--detail D]
  show     <topicId>
  list     [--scope global|worktree|session] [--source S] [--include-errors]
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Dict, List, Optional

import wd_core
import wd_taskworkflow


def _fail(message: str, code: int = 1) -> int:
    print(json.dumps({"ok": False, "error": message}, ensure_ascii=False))
    return code


def _ok(payload: Dict[str, Any]) -> int:
    print(json.dumps({"ok": True, **payload}, ensure_ascii=False, indent=2))
    return 0


def _parse_step_arg(raw: str) -> Dict[str, Any]:
    """Format "id=label" (1er '=' sépare ; le label peut contenir des '=')."""
    if "=" not in raw:
        raise ValueError(f'step spec must be "id=label" (got {raw!r})')
    step_id, _, label = raw.partition("=")
    step_id, label = step_id.strip(), label.strip()
    if not step_id or not label:
        raise ValueError(f'step spec requires non-empty id and label (got {raw!r})')
    return {"id": step_id, "label": label}


def cmd_create(args: argparse.Namespace) -> int:
    steps: List[Dict[str, Any]] = []
    for raw in args.step or []:
        try:
            steps.append(_parse_step_arg(raw))
        except ValueError as exc:
            return _fail(str(exc))
    detail_map: Dict[str, str] = {}
    for raw in args.step_detail or []:
        if "=" not in raw:
            return _fail(f'step-detail spec must be "id=detail" (got {raw!r})')
        step_id, _, detail = raw.partition("=")
        detail_map[step_id.strip()] = detail
    for step in steps:
        if step["id"] in detail_map:
            step["detail"] = detail_map[step["id"]]
    try:
        topic = wd_core.create_topic(
            title=args.title, kind=args.kind, source=args.source, scope=args.scope,
            steps=steps, session_id=args.session_id, worktree_path=args.worktree_path,
            parent_topic_id=args.parent_topic_id)
    except wd_core.ContractError as exc:
        return _fail(str(exc))
    return _ok({"topic": topic, "path": wd_core.topic_abspath(topic)})


def _resolve_topic(topic_id: str) -> Optional[Dict[str, Any]]:
    path = wd_core.find_topic_path(topic_id)
    return wd_core.read_topic(path) if path else None


def cmd_step(args: argparse.Namespace) -> int:
    try:
        topic = wd_core.update_step(args.topic_id, args.step_id, args.status,
                                    detail=args.detail, label=args.label)
    except wd_core.ContractError as exc:
        return _fail(str(exc))
    return _ok({"topic": topic})


def cmd_add_step(args: argparse.Namespace) -> int:
    try:
        spec = _parse_step_arg(args.spec)
    except ValueError as exc:
        return _fail(str(exc))
    if args.parent_id:
        spec["parentId"] = args.parent_id
    if args.detail:
        spec["detail"] = args.detail
    try:
        # append sous verrou (review J1 #2) : jamais de read-modify-write hors _mutate
        topic = wd_core.append_step(args.topic_id, spec)
    except wd_core.ContractError as exc:
        return _fail(str(exc))
    return _ok({"topic": topic})


def cmd_set_steps(args: argparse.Namespace) -> int:
    specs: List[Dict[str, Any]] = []
    for raw in args.spec:
        try:
            specs.append(_parse_step_arg(raw))
        except ValueError as exc:
            return _fail(str(exc))
    try:
        topic = wd_core.set_steps(args.topic_id, specs)
    except wd_core.ContractError as exc:
        return _fail(str(exc))
    return _ok({"topic": topic})


def cmd_close(args: argparse.Namespace) -> int:
    try:
        topic = wd_core.close_topic(args.topic_id, args.status, detail=args.detail)
    except wd_core.ContractError as exc:
        return _fail(str(exc))
    return _ok({"topic": topic})


def cmd_show(args: argparse.Namespace) -> int:
    topic = _resolve_topic(args.topic_id)
    if topic is None:
        return _fail(f"topic not found: {args.topic_id}")
    return _ok({"topic": topic, "progress": wd_core.compute_progress(topic)})


def cmd_list(args: argparse.Namespace) -> int:
    entries = wd_core.list_topics(scope=args.scope)
    topics: List[Dict[str, Any]] = []
    errors: List[Dict[str, Any]] = []
    for entry in entries:
        if entry["topic"] is None:
            errors.append({"path": entry["path"], "error": entry["error"]})
            continue
        if args.source and entry["topic"]["source"] != args.source:
            continue
        topics.append({"topic": entry["topic"],
                       "progress": wd_core.compute_progress(entry["topic"])})
    if args.source == wd_taskworkflow.SOURCE:
        native = wd_taskworkflow.list_topics()
        topics.extend({"topic": t, "progress": wd_core.compute_progress(t)}
                      for t in native["topics"]
                      if not args.scope or t["scope"] == args.scope)
        errors.extend({"path": f"task-workflow:{i['file']}", "error": i["reason"]}
                      for i in native["ignored"])
    payload: Dict[str, Any] = {"topics": topics}
    if args.include_errors:
        payload["errors"] = errors
    return _ok(payload)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="wd_publish",
                                     description="Progress publication CLI (contrat v1)")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("create", help="créer un sujet de progression")
    p.add_argument("--title", required=True)
    p.add_argument("--kind", required=True, choices=list(wd_core.KINDS))
    p.add_argument("--source", required=True, choices=list(wd_core.SOURCES))
    p.add_argument("--scope", required=True, choices=list(wd_core.SCOPES))
    p.add_argument("--worktree-path")
    p.add_argument("--session-id")
    p.add_argument("--parent-topic-id")
    p.add_argument("--step", action="append", metavar='"id=label"')
    p.add_argument("--step-detail", action="append", metavar='"id=detail"')
    p.set_defaults(func=cmd_create)

    p = sub.add_parser("step", help="mettre à jour une étape")
    p.add_argument("topic_id")
    p.add_argument("step_id")
    p.add_argument("status", choices=list(wd_core.PROGRESS_STATUSES))
    p.add_argument("--detail")
    p.add_argument("--label")
    p.set_defaults(func=cmd_step)

    p = sub.add_parser("add-step", help="ajouter une étape")
    p.add_argument("topic_id")
    p.add_argument("spec", metavar='"id=label"')
    p.add_argument("--parent-id")
    p.add_argument("--detail")
    p.set_defaults(func=cmd_add_step)

    p = sub.add_parser("set-steps", help="réécrire le plan (états conservés si ids stables)")
    p.add_argument("topic_id")
    p.add_argument("spec", nargs="+", metavar='"id=label"')
    p.set_defaults(func=cmd_set_steps)

    p = sub.add_parser("close", help="clôturer (steps non terminaux -> statut terminal)")
    p.add_argument("topic_id")
    p.add_argument("--status", required=True, choices=list(wd_core.TERMINAL_STATUSES))
    p.add_argument("--detail")
    p.set_defaults(func=cmd_close)

    p = sub.add_parser("show", help="afficher un sujet + progression dérivée")
    p.add_argument("topic_id")
    p.set_defaults(func=cmd_show)

    p = sub.add_parser("list", help="lister les sujets publiés")
    p.add_argument("--scope", choices=list(wd_core.SCOPES))
    p.add_argument("--source", choices=list(wd_core.SOURCES))
    p.add_argument("--include-errors", action="store_true")
    p.set_defaults(func=cmd_list)
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (wd_core.LockError, OSError) as exc:
        # garantie « toutes les sorties sont JSON » (review J1 #4)
        return _fail(f"{type(exc).__name__}: {exc}")


if __name__ == "__main__":
    sys.exit(main())
