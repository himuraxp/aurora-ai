#!/usr/bin/env python3
"""Report renderer for the task-workflow skill (stdlib only, Python 3.9+).

Renders two persistent, idempotent Markdown reports from the persisted state
file and its append-only events.jsonl chronicle:

- operational — compact (≤ 15 non-empty lines), printed at end of execution;
- detailed    — per-phase retro, written to disk, never printed in full.

Determinism contract: no clock reads, no invented data. Everything rendered
comes from the state file, the journal, or a measured git fact; anything not
recorded is rendered "non enregistré" or omitted. Same inputs → byte-identical
output. A merge request being open means the task is ready for REVIEW — it is
never reported as merged or deployed.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
from typing import Any, Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tw_state  # noqa: E402

PHASE_NAMES = {
    1: "Contexte", 2: "Worktree", 3: "Analyse", 4: "Code", 5: "QA",
    6: "Review", 7: "MR", 8: "Finalisation", 9: "Rapport",
}
ICONS = {"PASSED": "✅", "SKIPPED": "⏭️", "FAILED": "❌", "BLOCKED": "⛔",
         "WAITING_APPROVAL": "⏸️", "RUNNING": "🔄", "PENDING": "○"}
STATUS_FR = {"SKIPPED": "non exécutée", "BLOCKED": "bloquée", "FAILED": "échec",
             "WAITING_APPROVAL": "attente validation PO", "RUNNING": "en cours"}
SOURCE_FR = {"HUMAN": "validé humain", "policy": "politique produit"}
CHECK_ICONS = {"pass": "✅", "fail": "❌", "skipped": "⏭️", "not-run": "⏭️",
               "PASSED": "✅", "FAILED": "❌", "SKIPPED": "⏭️", "BLOCKED": "⛔",
               "WAITING_APPROVAL": "⏸️", "RUNNING": "🔄", "PENDING": "—"}
HANDOFF_FR = {
    "pending": "⏳ transférée au worktree — claim requis dans la session de reprise",
    "accepted": "✅ reprise confirmée",
    "failed": "❌ échec — suite dans la session courante",
    "uncertain": "❔ terminal créé mais handle absent — vérifier manuellement",
    "skipped": "⏭️ non applicable",
}


def _handoff_fate(state: dict) -> Optional[str]:
    """Fate of the Orca takeover (no prefix) — None when no handoff was recorded.

    A handoff is never silent: every attempted handoff leaves a status in the
    state (pending/accepted/failed/uncertain/skipped) and shows up here.
    A pending WITHOUT a recorded terminal handle is a crashed preparation,
    rendered as such — never as a healthy transfer.
    """
    handoff = state.get("handoff")
    if not isinstance(handoff, dict) or not handoff.get("status"):
        return None
    status = str(handoff["status"])
    if status == "pending" and not handoff.get("terminalHandle"):
        return "⏳ préparation interrompue (aucun terminal créé) — relancer " \
               "`tw_orca.py handoff` ou claim conscient"
    fate = HANDOFF_FR.get(status, f"❔ statut non reconnu ({status})")
    if status == "accepted" and handoff.get("session"):
        fate += f" ({handoff['session']})"
    why = handoff.get("why")
    if why and status != "accepted":
        fate += f" — {_truncate(why, 64)}"
    return fate


def _handoff_line(state: dict) -> Optional[str]:
    fate = _handoff_fate(state)
    return f"**Bascule Orca** : {fate}" if fate else None


def _truncate(text: str, limit: int) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[:limit - 1] + "…"


def _humanize_slug(url: str) -> str:
    """Last meaningful path segment as a fallback title."""
    slug = url.rstrip("/").split("/")[-1]
    slug = slug.split("-", 1)[1] if slug[:2].isdigit() and "-" in slug else slug
    return slug.replace("-", " ").strip().capitalize() if slug else ""


def _title(state: dict) -> str:
    plan = state.get("plan")
    if isinstance(plan, dict) and plan.get("title"):
        return str(plan["title"])
    urls = state.get("taskUrls") or []
    if urls and isinstance(urls[0], dict):
        humanized = _humanize_slug(str(urls[0].get("url", "")))
        if humanized:
            return humanized
    return state.get("workflowId", "tâche")


def _status_of(state: dict, phase: int) -> str:
    entry = (state.get("phaseStatuses") or {}).get(str(phase))
    return entry.get("status", "PENDING") if isinstance(entry, dict) else "PENDING"


def _at_of(state: dict, phase: int) -> Optional[str]:
    entry = (state.get("phaseStatuses") or {}).get(str(phase))
    return entry.get("at") if isinstance(entry, dict) else None


def _mr_number(url: str) -> str:
    match = re.search(r"merge_requests/(\d+)", url)
    return match.group(1) if match else "?"


def _segments(state: dict) -> List[List[Any]]:
    """Contiguous phase runs sharing one status: [[start, end, status], …]."""
    out: List[List[Any]] = []
    for phase in tw_state.PHASES:
        status = _status_of(state, phase)
        if out and out[-1][2] == status and out[-1][1] == phase - 1:
            out[-1][1] = phase
        else:
            out.append([phase, phase, status])
    return out


def _skip_reason(state: dict, phase: int) -> str:
    orphan_reasons: List[str] = []
    for key in ("qaResults", "blockers"):
        for entry in state.get(key, []):
            if not isinstance(entry, dict):
                continue
            reason = entry.get("reason") or entry.get("note") or entry.get("summary")
            if entry.get("phase") == phase and reason:
                return _truncate(reason, 42)
            if "phase" not in entry and reason:
                orphan_reasons.append(reason)
    # v1 fallback: an un-attributed reason is attachable only when the phase
    # requested is the single SKIPPED phase of the whole state (no guessing).
    skipped = [p for p in tw_state.PHASES if _status_of(state, p) == "SKIPPED"]
    if skipped == [phase] and orphan_reasons:
        return _truncate(orphan_reasons[0], 42)
    return ""


def _check_line(entry: dict, default_label: str = "contrôle",
                include_baseline: bool = True) -> Optional[str]:
    """One rendered check line — structured status wins over free-form result."""
    label = ""
    for key in ("name", "suites", "tsc", "lint"):
        if entry.get(key):
            label = str(entry[key])
            break
    if isinstance(entry.get("checks"), list):  # grouped checks (!565 style)
        parts = []
        for check in entry["checks"]:
            if not isinstance(check, dict):
                continue
            icon = CHECK_ICONS.get(str(check.get("result", "")), "•")
            detail = f" ({check['detail']})" if check.get("detail") else ""
            parts.append(f"{check.get('name', '?')} {icon}{detail}")
        return " · ".join(parts) if parts else None
    status = entry.get("status")
    if status is not None:
        if not label:
            label = f"phase {entry['phase']}" if entry.get("phase") else default_label
        suffix = f" (exit {entry['exitCode']})" if "exitCode" in entry else ""
        note = f" — {_truncate(entry['note'], 48)}" if entry.get("note") else ""
        baseline = (f" · baseline: {_truncate(entry['baseline'], 60)}"
                    if entry.get("baseline") and include_baseline else "")
        return f"{_truncate(label, 40)} {CHECK_ICONS.get(str(status), '•')}{suffix}{note}{baseline}"
    value = entry.get("result") or entry.get("detail") or entry.get("reason")
    if value and label:
        return f"{_truncate(label, 40)}: {_truncate(value, 52)}"
    return None


def _mr_evidence_fragment(state: dict) -> str:
    """Template + comparison table declared by the phase-7 MR evidence
    (mrResults[]) — rendered only from recorded facts, never invented:
    no mrResults entry, no fragment."""
    entries = [e for e in (state.get("mrResults") or [])
               if isinstance(e, dict) and str(e.get("phase", "")) == "7"]
    if not entries:
        return ""
    last = entries[-1]
    parts: List[str] = []
    template = last.get("templateUsed")
    if template:
        parts.append(f"template `{template}`")
    comparison = last.get("comparisonTable")
    if comparison == "none":
        reason = last.get("reason") or "raison non enregistrée"
        parts.append(f"tableau : non ({_truncate(reason, 80)})")
    elif comparison:
        parts.append(f"tableau : `{comparison}`")
    return f" · " + " · ".join(parts) if parts else ""


def _notify_fragment(state: dict) -> str:
    """Step-7bis notification outcome (notifyResults[]) — recorded facts only:
    no entry, no fragment; a skip shows its reason, never a bare silence."""
    entries = [e for e in (state.get("notifyResults") or []) if isinstance(e, dict)]
    if not entries:
        return ""
    last = entries[-1]
    channel = last.get("channel") or "?"
    status = last.get("status")
    if status in ("skipped", "not-run"):
        reason = last.get("reason") or "raison non enregistrée"
        return f" · notification trello : non exécutée ({_truncate(reason, 60)})"
    if status == "pass":
        return f" · notification trello ✅ ({channel})"
    return f" · notification trello ❌ ({channel})"


def _controls_line(state: dict) -> str:
    items: List[str] = []
    defaults = {"testResults": "tests", "reviewResults": "review", "qaResults": "QA"}
    for key in ("testResults", "reviewResults", "qaResults"):
        for entry in state.get(key, []):
            if isinstance(entry, dict):
                line = _check_line(entry, defaults[key], include_baseline=False)
                if line:
                    items.append(line)
    if len(items) > 3:
        items = items[:3] + [f"+{len(items) - 3} autres (voir état)"]
    blockers = state.get("blockers") or []
    if not items:
        # No recorded check at all — say it, never let a bare "bloqueurs : 0"
        # read as if checks had been run and passed.
        items.append(f"contrôles non enregistrés (voir journal) · bloqueurs : {len(blockers)}")
    else:
        items.append(f"bloqueurs : {len(blockers)}")
    for entry in state.get("testResults", []):
        if isinstance(entry, dict) and entry.get("baseline"):
            items.append(f"base {state.get('baseBranch', '?')} : {_truncate(entry['baseline'], 60)}")
            break
    return "**Contrôles** : " + (" · ".join(items) if items else "non enregistré")


def _phases_line(state: dict) -> str:
    parts = []
    for start, end, status in _segments(state):
        names = "·".join(PHASE_NAMES[phase] for phase in range(start, end + 1))
        if status == "PASSED":
            parts.append(f"{names} ✅")
        elif status == "PENDING":
            parts.append(f"{names} ○ à venir")
        elif status not in tw_state.STATUSES or status is None:
            raw = "inconnu" if status is None else _truncate(str(status), 20)
            parts.append(f"{names} ❔ statut non reconnu ({raw})")
        else:
            reason = _skip_reason(state, start)
            suffix = f" — {_truncate(reason, 42)}" if reason else ""
            parts.append(f"{names} {ICONS[status]} {STATUS_FR[status]}{suffix}")
    return "**Phases** : " + " · ".join(parts)


def _source_fr(source: Any) -> str:
    return SOURCE_FR.get(str(source), str(source))


def _decisions_line(state: dict, state_path: Optional[str] = None) -> str:
    decisions = state.get("decisions") or []
    vigilance = _vigilance(state, state_path)
    if not decisions:
        return f"**Décisions** : aucune · **Vigilance** : {vigilance}"
    first = decisions[0]
    answer = _truncate(str(first.get("answer", "?")), 60)
    rendered = f"«{answer}» ({_source_fr(first.get('source', '?'))})"
    if len(decisions) > 1:
        rendered += f" +{len(decisions) - 1} autres (voir état)"
    return f"**Décisions** : {rendered} · **Vigilance** : {vigilance}"


def _undecided(state: dict) -> List[int]:
    return [phase for phase in tw_state.PHASES
            if _status_of(state, phase) in ("SKIPPED", "BLOCKED", "FAILED", "WAITING_APPROVAL")]


AUTH_HINTS = ("auth", "connexion", "login", "manager")
ASSISTANCE_HINTS = ("browser-debug", "9222", "login", "connexion", "navigateur")


def _skip_gap_warning(state: dict, phase: int, state_path: Optional[str]) -> str:
    """Chronicle-informed honesty: a SKIPPED justified by authentication with
    NO recorded browser-debug attempt anywhere in the journal is a process
    deviation — surfaced, never silently accepted. States without a journal
    (v1) cannot be judged and are left alone."""
    if not state_path:
        return ""
    journal = tw_state.journal_path_for(state_path)
    if not os.path.isfile(journal):
        return ""
    reason = _skip_reason(state, phase).lower()
    if not any(hint in reason for hint in AUTH_HINTS):
        return ""
    chronicle = json.dumps(tw_state.read_events(state_path), ensure_ascii=False).lower()
    if any(hint in chronicle for hint in ASSISTANCE_HINTS):
        return ""
    return " ⚠️ aucune tentative browser-debug tracée (écart de process)"


def _vigilance(state: dict, state_path: Optional[str] = None) -> str:
    parts = []
    for phase in _undecided(state):
        status = _status_of(state, phase)
        label = STATUS_FR.get(status, f"statut non reconnu ({status})")
        reason = _skip_reason(state, phase)
        suffix = f" — {_truncate(reason, 48)}" if reason else ""
        if status == "SKIPPED":
            suffix += _skip_gap_warning(state, phase, state_path)
        parts.append(f"{PHASE_NAMES[phase]} : {label}{suffix}")
    return " · ".join(parts) if parts else "aucun"


def _global_status(state: dict) -> str:
    blocked = [p for p in tw_state.PHASES if _status_of(state, p) == "BLOCKED"]
    failed = [p for p in tw_state.PHASES if _status_of(state, p) == "FAILED"]
    if blocked:
        return f"⛔ bloqué (phase {PHASE_NAMES[blocked[0]]})"
    if failed:
        return f"❌ échec (phase {PHASE_NAMES[failed[0]]}, reprise possible)"
    if state.get("mergeRequestUrl"):
        return f"✅ MR !{_mr_number(state['mergeRequestUrl'])} prête"
    waiting = [p for p in tw_state.PHASES if _status_of(state, p) == "WAITING_APPROVAL"]
    if waiting:
        return f"⏸️ attente validation PO (phase {PHASE_NAMES[waiting[0]]})"
    current = state.get("currentPhase", 1)
    return f"🔄 en cours (phase {PHASE_NAMES.get(int(current), '?')})"


def _next_action(state: dict) -> str:
    blockers = state.get("blockers") or []
    if any(_status_of(state, p) == "BLOCKED" for p in tw_state.PHASES) and blockers:
        first = blockers[0]
        detail = first.get("note") or first.get("reason") if isinstance(first, dict) else str(first)
        return "lever le bloqueur — " + _truncate(detail or "voir état", 70)
    if state.get("mergeRequestUrl"):
        return f"revue humaine de la MR !{_mr_number(state['mergeRequestUrl'])} (jamais de merge automatique)"
    current = state.get("currentPhase", 1)
    return (f"reprendre à la phase {PHASE_NAMES.get(int(current), '?')} ({current})"
            f" — `tw_state.py resume {state.get('workflowId')}`")


def render_operational(state: dict, events: List[dict], context: Optional[dict] = None) -> str:
    context = context or {}
    status = _global_status(state)
    icon = status.split(" ", 1)[0]
    lines = [
        f"# {icon} {_title(state)} — {status[len(icon):].strip()} ({state.get('baseBranch', '?')})",
    ]
    plan = state.get("plan")
    objective = plan.get("objective") if isinstance(plan, dict) else None
    lines.append("Objectif : " + (_truncate(objective, 145) if objective else "non enregistré"))
    lines.append("")
    lines.append(_controls_line(state))
    lines.append(_phases_line(state))
    handoff_line = _handoff_line(state)
    if handoff_line:
        lines.append(handoff_line)
    lines.append(_decisions_line(state, context.get("state_path")))
    if state.get("mergeRequestUrl"):
        mr = f"**MR** : [!{_mr_number(state['mergeRequestUrl'])}]({state['mergeRequestUrl']}) → `{state.get('baseBranch', '?')}` · `{state.get('featureBranch', '?')}`"
        if context.get("head_commit"):
            mr += f" · commit `{context['head_commit']}`"
        if context.get("files_changed") is not None:
            mr += f" · {context['files_changed']} fichiers modifiés"
        mr += _mr_evidence_fragment(state)
        mr += _notify_fragment(state)
        lines.append(mr)
    lines.append(f"**Prochaine action** : {_next_action(state)}")
    if context.get("detail_path"):
        lines.append(f"📄 Détail par phase : `{context['detail_path']}`")
    return "\n".join(lines) + "\n"


def render_detailed(state: dict, events: List[dict], context: Optional[dict] = None) -> str:
    context = context or {}
    lines = [f"# Rapport détaillé — {state.get('workflowId', '?')}", ""]
    lines.append(f"Tâche : {_title(state)} · Dépôt : `{state.get('repository', '?')}`")
    created, updated = state.get("createdAt", "?"), state.get("updatedAt", "?")
    lines.append(f"Période : {created} → {updated} (intervalle entre horodatages persistés)")
    lines.append(f"Statut : {_global_status(state)} · Branche : `{state.get('featureBranch', '?')}` → `{state.get('baseBranch', '?')}`")
    lines.append("")
    lines.append("Généré depuis l'état persisté + journal — 0 donnée conversationnelle ; "
                 "ce qui n'a pas été enregistré est affiché « non enregistré ».")
    if not events:
        lines.append("Journal d'exécution absent (état v1) — chronique des actions non enregistrée.")
    lines.append("")
    for phase in tw_state.PHASES:
        entry = (state.get("phaseStatuses") or {}).get(str(phase))
        phase_events = [e for e in events if e.get("phase") == phase
                        and e.get("type") in ("command", "incident", "recovery", "note", "phase")]
        if (entry is None or entry.get("status") == "PENDING") and not phase_events:
            continue  # no empty sections — only phases with content
        lines.append(f"## Phase {phase} — {PHASE_NAMES[phase]}")
        if isinstance(entry, dict):
            status_line = f"**Statut** : {entry.get('status', '?')} à {entry.get('at', '?')}"
            signature = entry.get("codeSignature")
            if signature:
                status_line += f" · signature `{signature[:8]}…`"
            lines.append(status_line)
        actions = [e for e in phase_events if e["type"] in ("command", "note")]
        if actions:
            lines.append("**Actions enregistrées** :")
            for event in actions:
                summary = event.get("summary") or event.get("note") or "(sans détail)"
                attempt = f" (tentative {event['attempt']})" if event.get("attempt") else ""
                lines.append(f"- {_truncate(summary, 110)}{attempt} — {event.get('actor', '?')}")
        validations = []
        defaults = {"testResults": "tests", "reviewResults": "review",
                    "qaResults": "QA", "mrResults": "MR", "notifyResults": "trello"}
        for key in ("testResults", "reviewResults", "qaResults", "mrResults",
                    "notifyResults"):
            for check in state.get(key, []):
                if isinstance(check, dict) and check.get("phase") == phase:
                    line = _check_line(check, defaults[key])
                    if line:
                        validations.append(line)
        if validations:
            lines.append("**Validations** :")
            lines.extend(f"- {line}" for line in validations)
        incidents = [e for e in phase_events if e["type"] in ("incident", "recovery")]
        if incidents:
            lines.append("**Incidents & reprises** :")
            for event in incidents:
                lines.append(f"- {_truncate(event.get('summary') or event.get('note') or '?', 110)}")
        lines.append("")
    decisions = state.get("decisions") or []
    if decisions:
        lines.append("## Décisions")
        for decision in decisions:
            lines.append(f"- [{decision.get('source', '?')}] {decision.get('question', '?')} → {decision.get('answer', '?')}")
        lines.append("")
    state_path = context.get("state_path")
    gaps = [p for p in (tw_state.journal_problems(state, state_path) if state_path else [])
            if "no journal event" in p]
    skipped = [p for p in _undecided(state) if _status_of(state, p) == "SKIPPED"]
    lines.append("## Synthèse transversale")
    sources: Dict[str, int] = {}
    for decision in decisions:
        source = str(decision.get("source", "?"))
        sources[source] = sources.get(source, 0) + 1
    breakdown = ", ".join(f"{key} {value}" for key, value in sorted(sources.items())) or "0"
    lines.append(f"- Autonomie : {len(decisions)} décision(s) enregistrée(s) ({breakdown}) sur 9 phases")
    if skipped:
        lines.append("- Contrôles non exécutés : " + ", ".join(
            f"phase {p} {PHASE_NAMES[p]}" for p in skipped) + " (SKIPPED ≠ réussi)")
    if context.get("files_changed") is not None:
        lines.append(f"- Périmètre rendu : {context['files_changed']} fichier(s) modifié(s) (mesuré au rendu)")
    if events:
        gap_note = f", {len(gaps)} transition(s) sans événement" if gaps else ""
        lines.append(f"- Journal : {len(events)} événement(s){gap_note}")
    else:
        lines.append("- Journal : non enregistré (v1)")
    fate = _handoff_fate(state)
    if fate:
        lines.append(f"- Bascule Orca : {fate}")
    return "\n".join(lines) + "\n"


def git_context(state: dict) -> dict:
    """Measured git facts (never invented): changed-file count + HEAD commit."""
    context: Dict[str, Any] = {"files_changed": None, "head_commit": None}
    worktree = state.get("worktreePath")
    base = state.get("baseCommit")
    if not worktree or not os.path.isdir(worktree):
        return context
    try:
        if base:
            result = subprocess.run(
                ["git", "-C", worktree, "diff", "--name-only", f"{base}..HEAD"],
                capture_output=True, text=True, check=False, timeout=15)
            if result.returncode == 0:
                context["files_changed"] = len([l for l in result.stdout.splitlines() if l.strip()])
        result = subprocess.run(
            ["git", "-C", worktree, "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, check=False, timeout=15)
        if result.returncode == 0:
            context["head_commit"] = result.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        pass
    return context


def _write_atomic(path: str, content: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    handle, temp_path = tempfile.mkstemp(dir=os.path.dirname(path), suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as writer:
            writer.write(content)
        os.replace(temp_path, path)
    except BaseException:
        if os.path.exists(temp_path):
            os.unlink(temp_path)
        raise


def main(argv: List[str]) -> int:
    if not argv:
        print("usage: tw_report.py <state.json> [--kind operational|detailed|meetup]"
              " [--out PATH]", file=sys.stderr)
        return 2
    state_path = argv[0]
    kind, out = "operational", None
    rest = argv[1:]
    while rest:
        flag = rest.pop(0)
        if flag == "--kind":
            kind = rest.pop(0)
        elif flag == "--out":
            out = rest.pop(0)
    if kind not in ("operational", "detailed", "meetup"):
        print(f"ERROR: unknown kind {kind}", file=sys.stderr)
        return 2
    if kind == "meetup":
        print("not implemented — architecture ready (state + events.jsonl are sufficient "
              "to generate it later), see SKILL.md Phase 9", file=sys.stderr)
        return 2
    state = tw_state.load_state(state_path)
    problems = tw_state.validate_state(state, state_path)
    if problems:
        for problem in problems:
            print(f"INVALID: {problem}")
        return 1
    events = tw_state.read_events(state_path)
    context = git_context(state)
    context["state_path"] = os.path.abspath(state_path)
    artifacts = tw_state.artifacts_dir_for(state_path)
    context.setdefault("detail_path", os.path.join(artifacts, "report-detailed.md"))
    content = (render_operational(state, events, context) if kind == "operational"
               else render_detailed(state, events, context))
    target = out or os.path.join(artifacts, f"report-{kind}.md")
    _write_atomic(target, content)
    if kind == "operational":
        print(content, end="")  # compact report IS the end-of-run console output
    else:
        print(f"written: {target}")  # detailed report is never printed in full
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
