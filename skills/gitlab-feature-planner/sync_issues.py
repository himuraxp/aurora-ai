#!/usr/bin/env python3
"""Audit / sync des issues GitLab créées par le feature planner.

Modes :
  --mode audit  : compare les descriptions actuelles au rendu attendu, ne modifie rien.
  --mode sync   : applique les mises à jour (description) et crée les relations manquantes.

Correspondance issue <-> IssueSpec : marqueur HTML invisible en tête de description
`<!-- aurora:planner <feature>/<key> -->` (stable ID, cf. SKILL.md — Idempotence).

Transformations idempotentes appliquées :
  1. insertion du marqueur stable ;
  2. insertion/remplacement de « Critères d'acceptation » (après Checklist) ;
  3. suppression des sections sans contenu et des placeholders purs ;
  4. enrichissement des dépendances `- #N` en `- #N — [titre]`.

Relations : chaque dépendance `- #N` intra-projet crée un lien GitLab
`is_blocked_by` (idempotent : les liens existants sont ignorés).

Stdlib uniquement. Le renderer reste déterministe : deux runs successifs -> unchanged.
"""
from __future__ import annotations  # noqa: F401 (compat 3.9: X | Y en annotation)

import argparse
import json
import os
import re
import subprocess
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

from resolve_project import AmbiguousProject, ProjectNotFound, load_registry, resolve  # noqa: E402

MARKER_TAG = "aurora:planner"

# Sections supprimées si vides ou placeholder pur (SKILL.md — sections vides interdites)
CANDIDATE_EMPTY_HEADERS = (
    "Notes",
    "Dépendances",
    "Points à clarifier",
    "Notes techniques",
    "Maquettes",
    "Critères particuliers",
    "Suggestion de découpage des MR",
)
PLACEHOLDER_RE = re.compile(r"^- (Pas de maquette spécifique|Aucune\b)", re.M)
DEP_REF_RE = re.compile(r"^-\s+#(\d+)\s*$")
DEP_REF_ANY_RE = re.compile(r"^-\s+#(\d+)\b")


# --------------------------------------------------------------------------- utils
def glab_api(path: str, method: str = "GET", body: dict | None = None):
    cmd = ["glab", "api"]
    if method != "GET":
        cmd += ["-X", method]
    cmd.append(path)
    if body:
        for key, value in body.items():
            cmd += ["-f", f"{key}={value}"]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=90, check=True)
    return json.loads(result.stdout) if result.stdout.strip() else None


def split_sections(desc: str):
    """-> (prelude_lines, [(header_line, body_lines)]) — les sections commencent par '## '."""
    prelude, sections, header, body = [], [], None, []
    for line in desc.splitlines():
        if line.startswith("## "):
            if header is None:
                prelude = body
            else:
                sections.append((header, body))
            header, body = line, []
        else:
            body.append(line)
    if header is not None:
        sections.append((header, body))
    return prelude, sections


def join_sections(prelude, sections) -> str:
    lines = list(prelude)
    for header, body in sections:
        lines.append(header)
        lines.extend(body)
    return "\n".join(lines).rstrip()


# ------------------------------------------------------------------ transformations
def ensure_marker(desc: str, feature: str, key: str) -> str:
    marker = f"<!-- {MARKER_TAG} {feature}/{key} -->"
    lines = [
        line
        for line in desc.splitlines()
        if not (line.strip().startswith("<!--") and MARKER_TAG in line)
    ]
    while lines and not lines[0].strip():
        lines.pop(0)
    return "\n".join([marker] + lines).rstrip()


def build_criteria_block(criteria: list[str]) -> list[str]:
    """Bullets SANS checkbox — les critères d'acceptation sont la Definition of Done,
    pas des tâches de développement : ils ne doivent pas compter dans la
    progression native GitLab (cf. SKILL.md — Step 7).
    Seule la Checklist des tâches produit des checkboxes Markdown."""
    return ["## Critères d'acceptation", ""] + [f"- {c}" for c in criteria]


CHECKBOX_RE = re.compile(r"^-\s+\[[xX ]\]\s+(.*)$")


def normalize_criteria_bullets(desc: str) -> str:
    """Convertit en bullet toute checkbox restée dans la section Critères d'acceptation.

    Migration ciblée et idempotente : ne touche à AUCUNE autre section — la
    Checklist des tâches conserve ses `[ ]`/`[x]` (seul indicateur de progression).
    Préserve le contenu exact des critères (modifications manuelles incluses)."""
    prelude, sections = split_sections(desc)
    changed = False
    for idx, (header, body) in enumerate(sections):
        if header[3:].strip() != "Critères d'acceptation":
            continue
        new_body = []
        for line in body:
            m = CHECKBOX_RE.match(line.strip())
            if m:
                indent = line[: len(line) - len(line.lstrip())]
                new_body.append(f"{indent}- {m.group(1)}")
                changed = True
            else:
                new_body.append(line)
        sections[idx] = (header, new_body)
    if not changed:
        return desc.rstrip()
    return join_sections(prelude, sections)


def insert_criteria(desc: str, criteria: list[str]) -> str:
    """Insère (ou remplace) la section Critères d'acceptation après la Checklist."""
    if not criteria:
        return desc
    prelude, sections = split_sections(desc)
    already = any(header[3:].strip() == "Critères d'acceptation" for header, _ in sections)
    rebuilt = []
    for header, body in sections:
        title = header[3:].strip()
        if title == "Critères d'acceptation":
            rebuilt.append((header, build_criteria_block(criteria)[2:] + [""]))
            continue
        if title == "Checklist" and not already:
            if body and body[-1].strip():
                body = body + [""]
            rebuilt.append((header, body))
            rebuilt.append(("## Critères d'acceptation", build_criteria_block(criteria)[2:] + [""]))
            continue
        rebuilt.append((header, body))
    if not already and not any(header[3:].strip() == "Checklist" for header, _ in sections):
        rebuilt.append(("## Critères d'acceptation", build_criteria_block(criteria)[2:] + [""]))
    return join_sections(prelude, rebuilt)


def strip_empty_sections(desc: str) -> str:
    """Supprime les sections candidates sans contenu et les placeholders purs."""
    prelude, sections = split_sections(desc)
    kept = []
    for header, body in sections:
        title = header[3:].strip()
        content = [line for line in body if line.strip()]
        if title in CANDIDATE_EMPTY_HEADERS and (
            not content or (len(content) == 1 and PLACEHOLDER_RE.match(content[0]))
        ):
            continue
        kept.append((header, body))
    return join_sections(prelude, kept)


def enrich_dependencies(desc: str, title_map: dict[str, str]) -> str:
    """- #6  ->  - #6 — [titre de l'issue] (idempotent)."""
    prelude, sections = split_sections(desc)
    for idx, (header, body) in enumerate(sections):
        if header[3:].strip() != "Dépendances":
            continue
        new_body = []
        for line in body:
            m = DEP_REF_RE.match(line.strip())
            title = title_map.get(m.group(1)) if m else None
            if m and title:
                new_body.append(f"- #{m.group(1)} — {title}")
            else:
                new_body.append(line)
        sections[idx] = (header, new_body)
    return join_sections(prelude, sections)


def detect_wrong_project(expected_path: str, actual_path: str) -> bool:
    """True si l'issue ne vit pas dans le projet attendu par l'IssueSpec."""
    return expected_path.rstrip("/") != actual_path.rstrip("/")


def parse_dep_iids(desc: str) -> list[int]:
    """Numéros des dépendances intra-projet dans la section Dépendances."""
    _, sections = split_sections(desc)
    for header, body in sections:
        if header[3:].strip() == "Dépendances":
            return [int(m.group(1)) for line in body if (m := DEP_REF_ANY_RE.match(line.strip()))]
    return []


def transform(desc: str, feature: str, key: str, criteria: list[str], title_map: dict[str, str]) -> str:
    desc = ensure_marker(desc, feature, key)
    desc = insert_criteria(desc, criteria)
    desc = strip_empty_sections(desc)
    desc = enrich_dependencies(desc, title_map)
    desc = normalize_criteria_bullets(desc)
    return desc.rstrip()


# ----------------------------------------------------------------------- relations
def existing_links(pid: int, iid: int) -> set[tuple[int, int]]:
    links = glab_api(f"projects/{pid}/issues/{iid}/links") or []
    return {(l["project_id"], l["iid"]) for l in links}


def missing_relations(pid: int, iid: int, dep_iids: list[int]):
    known = existing_links(pid, iid)
    return [d for d in dep_iids if (pid, d) not in known]


# ----------------------------------------------------------------------------- run
def run(mode: str, feature_dir: str, criteria_path: str | None, relations: bool = True) -> int:
    with open(os.path.join(feature_dir, "created.json"), encoding="utf-8") as f:
        created = json.load(f)
    registry = load_registry()
    feature = os.path.basename(os.path.normpath(feature_dir))
    criteria_map = {}
    if criteria_path and os.path.exists(criteria_path):
        with open(criteria_path, encoding="utf-8") as f:
            criteria_map = json.load(f).get("criteria", {})

    projects: dict[str, list[str]] = {}
    for key, entry in created.items():
        projects.setdefault(entry["project"], []).append(key)

    stats = {"updated": [], "unchanged": [], "errors": [], "relations_to_add": 0, "relations_added": 0}
    for project_path, keys in sorted(projects.items()):
        try:
            reg_entry = resolve(project_path, registry)
        except (AmbiguousProject, ProjectNotFound) as exc:
            for key in keys:
                stats["errors"].append(f"{key}: projet non résolu — {exc}")
            continue
        pid = reg_entry["projectId"]

        title_map: dict[str, str] = {}
        issues = glab_api(f"projects/{pid}/issues?per_page=100&state=opened") or []
        for i in issues:
            title_map[str(i["iid"])] = i["title"]

        for key in keys:
            entry = created[key]
            iid = entry["iid"]
            try:
                issue = glab_api(f"projects/{pid}/issues/{iid}")
            except subprocess.CalledProcessError as exc:
                stats["errors"].append(f"{key}: issue {pid}#{iid} inaccessible — {exc.stderr.strip()[:80]}")
                continue
            if not isinstance(issue, dict):
                stats["errors"].append(f"{key}: réponse inattendue pour {pid}#{iid}")
                continue
            old = issue.get("description") or ""
            new = transform(old, feature, key, criteria_map.get(key, []), title_map)
            changes = describe_changes(old, new)
            if new != old:
                stats["updated"].append(f"{project_path}#{iid} ({key}) — {changes}")
                if mode == "sync":
                    glab_api(f"projects/{pid}/issues/{iid}", method="PUT", body={"description": new})
            else:
                stats["unchanged"].append(f"{project_path}#{iid} ({key})")

            if relations:
                deps = [d for d in parse_dep_iids(new) if d != iid]
                if deps:
                    missing = missing_relations(pid, iid, deps)
                    stats["relations_to_add"] += len(missing)
                    if mode == "sync":
                        for dep in missing:
                            glab_api(
                                f"projects/{pid}/issues/{iid}/links",
                                method="POST",
                                body={
                                    "target_project_id": pid,
                                    "target_issue_iid": dep,
                                    "link_type": "is_blocked_by",
                                },
                            )
                            stats["relations_added"] += 1

    # ------------------------------------------------------------------ rapport
    print(f"Feature « {feature} » — {len(created)} issues — mode {mode}")
    print(f"Projets résolus via registry : {len(projects)}/{len(projects)}")
    for line in stats["updated"]:
        print(f"  ~ {line}" + ("" if mode == "audit" else "  [applied]"))
    for line in stats["unchanged"]:
        print(f"  = {line}")
    for line in stats["errors"]:
        print(f"  ! {line}")
    if relations:
        print(f"Relations is_blocked_by : {stats['relations_added'] if mode == 'sync' else stats['relations_to_add']} à traiter, {stats['relations_added']} créées")
    print(f"Résumé : {len(stats['updated'])} update(s), {len(stats['unchanged'])} unchanged, {len(stats['errors'])} erreur(s)")
    return 1 if stats["errors"] else 0


def describe_changes(old: str, new: str) -> str:
    changes = []
    if "<!--" not in old:
        changes.append("marqueur ajouté")
    if "## Critères d'acceptation" not in old:
        changes.append("critères d'acceptation ajoutés")
    old_secs = {h[3:].strip() for h, _ in split_sections(old)[1]}
    new_secs = {h[3:].strip() for h, _ in split_sections(new)[1]}
    removed = old_secs - new_secs
    if removed:
        changes.append(f"sections vides/placeholder supprimées ({', '.join(sorted(removed))})")
    bare_old = len(re.findall(r"^- #\d+\s*$", old, re.M))
    bare_new = len(re.findall(r"^- #\d+\s*$", new, re.M))
    if bare_new < bare_old:
        changes.append("dépendances enrichies")

    def criteria_checkboxes(text: str) -> int:
        for header, body in split_sections(text)[1]:
            if header[3:].strip() == "Critères d'acceptation":
                return sum(1 for line in body if CHECKBOX_RE.match(line.strip()))
        return 0

    if criteria_checkboxes(old) > criteria_checkboxes(new):
        changes.append("critères convertis en bullets (hors progression)")
    return ", ".join(changes) or "description normalisée"


def main():
    ap = argparse.ArgumentParser(description="Audit / sync des issues du feature planner")
    ap.add_argument("--feature-dir", required=True, help="dossier planning/<feature> contenant created.json")
    ap.add_argument("--mode", choices=["audit", "sync"], default="audit")
    ap.add_argument("--criteria", default=None, help="JSON {key: [critères]} (défaut: <feature-dir>/acceptance-criteria.json)")
    ap.add_argument("--no-relations", action="store_true", help="ne pas traiter les relations GitLab")
    args = ap.parse_args()

    criteria_path = args.criteria or os.path.join(args.feature_dir, "acceptance-criteria.json")
    sys.exit(run(args.mode, args.feature_dir, criteria_path, relations=not args.no_relations))


if __name__ == "__main__":
    main()
