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
         "WAITING_APPROVAL": "⏸️", "RUNNING": "🔄", "PENDING": "—"}
CHECK_ICONS = {"pass": "✅", "fail": "❌", "skipped": "⏭️", "not-run": "⏭️",
               "PASSED": "✅", "FAILED": "❌", "SKIPPED": "⏭️", "BLOCKED": "⛔",
               "WAITING_APPROVAL": "⏸️", "RUNNING": "🔄", "PENDING": "—"}


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


def _check_line(entry: dict, default_label: str = "contrôle") -> Optional[str]:
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
        baseline = f" · baseline: {_truncate(entry['baseline'], 60)}" if entry.get("baseline") else ""
        return f"{_truncate(label, 40)} {CHECK_ICONS.get(str(status), '•')}{suffix}{note}{baseline}"
    value = entry.get("result") or entry.get("detail") or entry.get("reason")
    if value and label:
        return f"{_truncate(label, 40)}: {_truncate(value, 52)}"
    return None


def _controls_line(state: dict) -> str:
    items: List[str] = []
    defaults = {"testResults": "tests", "reviewResults": "review", "qaResults": "QA"}
    for key in ("testResults", "reviewResults", "qaResults"):
        for entry in state.get(key, []):
            if isinstance(entry, dict):
                line = _check_line(entry, defaults[key])
                if line:
                    items.append(line)
    if len(items) > 3:
        items = items[:3] + [f"+{len(items) - 3} autres (voir état)"]
    blockers = state.get("blockers") or []
    items.append(f"blockers {len(blockers)}")
    for entry in state.get("testResults", []):
        if isinstance(entry, dict) and entry.get("baseline"):
            items.append(f"baseline: {_truncate(entry['baseline'], 60)}")
            break
    return "**Contrôles** : " + (" · ".join(items) if items else "non enregistré")


def _phases_line(state: dict) -> str:
    parts = []
    for start, end, status in _segments(state):
        label = f"{start}-{end}" if end > start else f"{start}"
        if status in ("PASSED", "PENDING"):
            parts.append(f"{label} {ICONS[status]}")
        else:
            reason = _skip_reason(state, start)
            suffix = f" ({reason})" if reason else ""
            parts.append(f"{label} {ICONS[status]} {PHASE_NAMES[start]}{suffix}")
    return "**Phases** : " + " · ".join(parts)


def _decisions_line(state: dict) -> str:
    decisions = state.get("decisions") or []
    if not decisions:
        return "**Décisions** : 0 · **Vigilance** : " + _vigilance(state)
    sources: Dict[str, int] = {}
    for decision in decisions:
        source = str(decision.get("source", "?"))
        sources[source] = sources.get(source, 0) + 1
    breakdown = ", ".join(f"{key}:{value}" for key, value in sorted(sources.items()))
    return f"**Décisions** : {len(decisions)} ({breakdown}) · **Vigilance** : " + _vigilance(state)


def _undecided(state: dict) -> List[int]:
    return [phase for phase in tw_state.PHASES
            if _status_of(state, phase) in ("SKIPPED", "BLOCKED", "FAILED", "WAITING_APPROVAL")]


def _vigilance(state: dict) -> str:
    parts = [f"phase {phase} {PHASE_NAMES[phase]}" for phase in _undecided(state)]
    return " · ".join(parts) if parts else "aucune"


def _global_status(state: dict) -> str:
    blocked = [p for p in tw_state.PHASES if _status_of(state, p) == "BLOCKED"]
    failed = [p for p in tw_state.PHASES if _status_of(state, p) == "FAILED"]
    if blocked:
        return f"⛔ bloqué (phase {blocked[0]} {PHASE_NAMES[blocked[0]]})"
    if failed:
        return f"❌ échec phase {failed[0]} {PHASE_NAMES[failed[0]]} (reprise possible)"
    if state.get("mergeRequestUrl"):
        return f"✅ MR !{_mr_number(state['mergeRequestUrl'])} prête"
    waiting = [p for p in tw_state.PHASES if _status_of(state, p) == "WAITING_APPROVAL"]
    if waiting:
        return f"⏸️ attente validation (phase {waiting[0]} {PHASE_NAMES[waiting[0]]})"
    current = state.get("currentPhase", 1)
    return f"🔄 en cours (phase {current} {PHASE_NAMES.get(int(current), '?')})"


def _next_action(state: dict) -> str:
    blockers = state.get("blockers") or []
    if any(_status_of(state, p) == "BLOCKED" for p in tw_state.PHASES) and blockers:
        first = blockers[0]
        detail = first.get("note") or first.get("reason") if isinstance(first, dict) else str(first)
        return "lever le blocker — " + _truncate(detail or "voir état", 70)
    if state.get("mergeRequestUrl"):
        return f"revue humaine de MR !{_mr_number(state['mergeRequestUrl'])} (jamais de merge automatique)"
    current = state.get("currentPhase", 1)
    return f"reprendre à la phase {current} (`tw_state.py resume {state.get('workflowId')}`)"


def render_operational(state: dict, events: List[dict], context: Optional[dict] = None) -> str:
    context = context or {}
    status = _global_status(state)
    icon = status.split(" ", 1)[0]
    lines = [
        f"# {icon} {_title(state)} — {status[len(icon):].strip()} ({state.get('baseBranch', '?')})",
    ]
    plan = state.get("plan")
    objective = plan.get("objective") if isinstance(plan, dict) else None
    lines.append(_truncate(objective, 150) if objective else "Objectif : non enregistré")
    lines.append("")
    lines.append(_controls_line(state))
    lines.append(_phases_line(state))
    lines.append(_decisions_line(state))
    if state.get("mergeRequestUrl"):
        mr = f"**MR** : [!{_mr_number(state['mergeRequestUrl'])}]({state['mergeRequestUrl']}) → `{state.get('baseBranch', '?')}` · `{state.get('featureBranch', '?')}`"
        if context.get("head_commit"):
            mr += f" · commit `{context['head_commit']}`"
        if context.get("files_changed") is not None:
            mr += f" · {context['files_changed']} fichiers"
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
        defaults = {"testResults": "tests", "reviewResults": "review", "qaResults": "QA"}
        for key in ("testResults", "reviewResults", "qaResults"):
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
