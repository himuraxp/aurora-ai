#!/usr/bin/env python3
"""Workflow Dashboard — Terminal renderer (J2, LECTURE SEULE STRICTE).

Affiche tous les sujets de progression (adaptateur task-workflow + store
publié) en trois catégories : EN COURS · NÉCESSITE UNE ACTION · TERMINÉS
RÉCEMMENT. Ce module n'écrit JAMAIS (aucun fichier, stdout uniquement) et ne
décide jamais qu'une tâche est terminée — il interprète les transitions
publiées.

Zéro dépendance (stdlib). Un frame par appel ; `--watch <secondes>` redessine
(clear + frame, latence de propagation maîtrisée par l'intervalle).

La SOURCE est toujours affichée (task-workflow | todowrite-relay |
orchestrator-cli) : les garanties natives ne se dégradent jamais en
déclaratif. L'âge d'updatedAt est un INDICATEUR, pas une garantie.
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import wd_core
import wd_taskworkflow

# Catégories d'affichage (contrat t3/t4) — dérivées du statut global,
# jamais stockées.
ACTION_STATUSES = ("BLOCKED", "FAILED")          # NÉCESSITE UNE ACTION
DONE_STATUSES = ("DONE", "SKIPPED")              # TERMINÉS (fenêtre récente)
RECENT_WINDOW_SECONDS = 48 * 3600                # au-delà : compteur d'archive

BAR_WIDTH = 10

ANSI = {
    "reset": "\033[0m",
    "bold": "\033[1m",
    "dim": "\033[2m",
    "red": "\033[31m",
    "green": "\033[32m",
    "yellow": "\033[33m",
    "blue": "\033[34m",
    "magenta": "\033[35m",
    "cyan": "\033[36m",
    "gray": "\033[90m",
}
STATUS_ICONS = {
    "RUNNING": "◐", "PENDING": "○", "DONE": "●", "FAILED": "✗",
    "BLOCKED": "⊘", "SKIPPED": "↷",
}
STATUS_COLORS = {
    "RUNNING": "cyan", "PENDING": "gray", "DONE": "green", "FAILED": "red",
    "BLOCKED": "yellow", "SKIPPED": "gray",
}
CATEGORY_TITLES = {
    "running": "EN COURS",
    "action": "NÉCESSITE UNE ACTION",
    "done": "TERMINÉS RÉCEMMENT",
}

# Dégradation gracieuse aux faibles largeurs (la source reste TOUJOURS
# affichée : forme abrégée documentée dans le README).
SOURCE_ABBREV = {
    "task-workflow": "tw",
    "todowrite-relay": "tr",
    "orchestrator-cli": "oc",
}
WIDTH_FULL = 64       # en dessous : âge masqué
WIDTH_SHORT_SOURCE = 48  # en dessous : source abrégée + barre réduite
BAR_WIDTH_NARROW = 5


def _c(text: str, color: Optional[str], enabled: bool) -> str:
    if not enabled or not color:
        return text
    return f"{ANSI[color]}{text}{ANSI['reset']}"


def _parse_iso(value: str) -> Optional[datetime]:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, AttributeError, TypeError):
        return None
    if parsed.tzinfo is None:
        # timestamp naïf = valide au contrat (wd_core.is_iso_datetime) :
        # interprété en UTC, jamais de TypeError naive/aware (review J2 #1)
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def age_label(updated_at: str, now: datetime) -> Optional[str]:
    """Indicateur d'âge d'updatedAt — ≠ garantie (improvement t4 #4)."""
    updated = _parse_iso(updated_at)
    if updated is None:
        return None
    seconds = max(0.0, (now - updated).total_seconds())
    if seconds < 90:
        return "à l'instant"
    if seconds < 3600:
        return f"{int(seconds // 60)}m"
    if seconds < 24 * 3600:
        return f"{int(seconds // 3600)}h"
    return f"{int(seconds // (24 * 3600))}j"


def categorize(topic: Dict[str, Any]) -> str:
    """Catégorie d'affichage dérivée du statut global (jamais stockée)."""
    derived = wd_core.derive_status(topic)
    if derived in ACTION_STATUSES:
        return "action"
    if derived in DONE_STATUSES:
        return "done"
    return "running"


def _progress_bar(ratio: float, enabled: bool, bar_width: int = BAR_WIDTH) -> str:
    filled = round(ratio * bar_width)
    bar = "▓" * filled + "░" * (bar_width - filled)
    return _c(bar, "blue", enabled)


def _truncate(text: str, width: int) -> str:
    if width <= 1:
        return text[:1] if text else ""
    return text if len(text) <= width else text[: width - 1] + "…"


def render_topic_line(topic: Dict[str, Any], progress: Dict[str, Any],
                      width: int, now: datetime, colors: bool) -> str:
    """Une ligne compacte : icône statut · titre · source · barre n/total · âge.

    Dégradation aux faibles largeurs : < 56 l'âge est masqué ; < 48 la source
    est abrégée ([tw]/[tr]/[oc]) et la barre réduite — jamais absente."""
    derived = progress["derivedStatus"]
    icon = _c(STATUS_ICONS.get(derived, "·"), STATUS_COLORS.get(derived), colors)
    if width >= WIDTH_SHORT_SOURCE:
        tag = f"[{topic['source']}]"
        bar_width = BAR_WIDTH
    else:
        tag = f"[{SOURCE_ABBREV.get(topic['source'], '?')}]"
        bar_width = BAR_WIDTH_NARROW
    source_tag = _c(tag, "magenta", colors)
    age = age_label(topic["updatedAt"], now) if width >= WIDTH_FULL else None
    total = progress["total"]
    ratio = f"{progress['terminalCount']}/{total}" if total else "0/0"
    # largeur fixe consommée hors titre (codes ANSI = 0 en largeur) ;
    # 4 séparateurs : icon␠ / title␠ / tag␠ / bar␠ (review J2 #3)
    fixed = 1 + 1 + len(tag) + 1 + bar_width + 1 + len(ratio) + 1
    if age:
        fixed += 3 + len(age)
    title_width = max(10, width - fixed)
    title = _truncate(topic["title"].replace("\n", " "), title_width)
    line = (f"{icon} {title} {source_tag} "
            f"{_progress_bar(progress['terminalRatio'], colors, bar_width)} {ratio}")
    if age:
        line += f" {_c('· ' + age, 'gray', colors)}"
    return line


def render_steps(topic: Dict[str, Any], indent: str, now: datetime,
                 colors: bool, width: int = 80) -> List[str]:
    """Vue détaillée : les steps publiés (largeur respectée — review J2 #4).

    Le détail partage la ligne uniquement si label + détail tiennent dans
    le budget ; sinon le détail est omis (jamais de wrap garanti)."""
    lines: List[str] = []
    budget = max(16, width - len(indent) - 4)  # indent + icon + espace + marge
    for step in topic["steps"]:
        status = step["status"]
        icon = _c(STATUS_ICONS.get(status, "·"), STATUS_COLORS.get(status), colors)
        label = step["label"].replace("\n", " ")
        detail = step.get("detail")
        suffix = ""
        if detail and len(label) + 15 <= budget:
            room = budget - len(label) - 3
            suffix = f" {_c('— ' + _truncate(detail, room), 'gray', colors)}"
        lines.append(f"{indent}{icon} {_truncate(label, budget)}{suffix}")
    return lines


def gather() -> Tuple[List[Tuple[Dict[str, Any], Dict[str, Any]]], int]:
    """Toutes les sources : adaptateur natif + topics publiés (lecture seule).
    Retourne aussi le nombre de sources illisibles/ignorées — le dashboard
    EST la surface d'observabilité : rien ne disparaît sans signal
    (review J2 #5)."""
    entries: List[Tuple[Dict[str, Any], Dict[str, Any]]] = []
    dropped = 0
    native = wd_taskworkflow.list_topics()
    for topic in native["topics"]:
        entries.append((topic, wd_core.compute_progress(topic)))
    dropped += len(native["ignored"])
    for entry in wd_core.list_topics():
        if entry["topic"] is not None:
            entries.append((entry["topic"], wd_core.compute_progress(entry["topic"])))
        else:
            dropped += 1
    return entries, dropped


def sort_entries(entries: List[Tuple[Dict[str, Any], Dict[str, Any]]],
                 session_id: Optional[str]) -> List[Tuple[Dict[str, Any], Dict[str, Any]]]:
    """Session courante prioritaire, puis mise à jour la plus récente d'abord."""

    def key(pair: Tuple[Dict[str, Any], Dict[str, Any]]):
        topic, _ = pair
        stamp = _parse_iso(topic.get("updatedAt") or "") or datetime.min.replace(tzinfo=timezone.utc)
        current = 0 if (session_id and topic.get("sessionId") == session_id) else 1
        return (current, -stamp.timestamp())

    return sorted(entries, key=key)


def render(width: int = 80, now: Optional[datetime] = None,
           session_id: Optional[str] = None, colors: bool = False,
           verbose: bool = False) -> str:
    """Un frame complet du dashboard (aucune écriture, stdout only).

    Choix documenté (review J2) : un topic DONE dont updatedAt est
    unparseable part à l'archive (compteur +N) — conservateur, jamais
    trompeur sur la fenêtre « récents ».
    """
    now = now or datetime.now(timezone.utc)
    entries, dropped = gather()
    entries = sort_entries(entries, session_id)
    if not entries and not dropped:
        return "Aucun suivi en cours.\n"
    buckets: Dict[str, List[Tuple[Dict[str, Any], Dict[str, Any]]]] = {
        "running": [], "action": [], "done": [],
    }
    archived = 0
    for pair in entries:
        category = categorize(pair[0])
        if category == "done":
            age = (now - (_parse_iso(pair[0].get("updatedAt") or "")
                          or datetime.min.replace(tzinfo=timezone.utc))).total_seconds()
            if age > RECENT_WINDOW_SECONDS:
                archived += 1
                continue
        buckets[category].append(pair)
    lines: List[str] = []
    for category in ("running", "action", "done"):
        if not buckets[category]:
            continue
        lines.append(_c(CATEGORY_TITLES[category], "bold", colors))
        for topic, progress in buckets[category]:
            lines.append(render_topic_line(topic, progress, width, now, colors))
            if verbose:
                lines.extend(render_steps(topic, "   ", now, colors, width=width))
    if archived:
        lines.append(_c(f"+ {archived} sujet(s) terminé(s) antérieur(s)", "gray", colors))
    if dropped:
        lines.append(_c(f"· {dropped} source(s) illisible(s)/ignorée(s)", "gray", colors))
    return "\n".join(lines) + "\n"


def current_session_id() -> Optional[str]:
    """Session courante : --session-id prioritaire, sinon WD_SESSION_ID (J3/J4)."""
    return os.environ.get("WD_SESSION_ID") or None


def _clear() -> None:
    if sys.stdout.isatty():
        sys.stdout.write("\033[2J\033[H")


def _watch_interval(value: str) -> float:
    try:
        seconds = float(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"--watch must be a number (got {value!r})")
    if not 0.2 <= seconds <= 86400:  # plancher propagation, plafond anti-Overflow
        raise argparse.ArgumentTypeError("--watch must be in [0.2, 86400]")
    return seconds


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="wd_dashboard",
        description="Workflow Dashboard — terminal renderer (lecture seule)")
    parser.add_argument("--watch", type=_watch_interval, metavar="SECONDS",
                        default=None,
                        help="redessine toutes les N secondes (0.2..86400 ; défaut : un frame)")
    parser.add_argument("--verbose", action="store_true",
                        help="affiche les steps sous chaque sujet")
    parser.add_argument("--session-id", default=None,
                        help="priorise le sujet de cette session")
    parser.add_argument("--width", type=int, default=None,
                        help="largeur du frame (défaut : terminal)")
    args = parser.parse_args(argv)
    colors = sys.stdout.isatty()
    width = args.width or shutil.get_terminal_size((80, 24)).columns

    def frame() -> str:
        return render(width=width, session_id=args.session_id
                      or current_session_id(), colors=colors, verbose=args.verbose)

    if args.watch is None:
        sys.stdout.write(frame())
        return 0
    try:
        while True:
            _clear()
            sys.stdout.write(frame())
            sys.stdout.flush()
            time.sleep(max(0.2, args.watch))
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())
