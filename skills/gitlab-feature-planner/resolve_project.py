#!/usr/bin/env python3
"""Résolution déterministe d'un projet GitLab à partir du registry du skill.

Stratégie (SKILL.md — Project resolution) :
  1. alias exact (registry)
  2. project ID connu (registry)
  3. project path connu (registry)
  4. displayName exact (registry)
  5. sinon -> NotFound : recherche GitLab contrôlée autorisée, MAIS ambiguïté = STOP
     et confirmation humaine ; projet validé -> mémoriser via --record.

Le registry existe en trois variantes — repo public = template placeholder,
config privée = données réelles (pattern private-config / public-engine,
cf. mail-triage et deployment-changelog) :
  1. ~/.config/opencode/gitlab-feature-planner-registry.private.json (config privée, hors repo — données réelles)
  2. <script_dir>/projects-registry.json            (repo public — template placeholder, versionné)
  3. ~/.config/opencode/skills/gitlab-feature-planner/projects-registry.json (installation)
  4. <script_dir>/projects-registry.example.json    (template versionné, données d'exemple)

Le loader lit le registre privé en priorité. `--record` écrit toujours dans le
registre privé, jamais dans un fichier du repo public (les namespaces/IDs
réels ne doivent pas fuiter dans le repo).

Usage :
  resolve-project.py --list
  resolve-project.py --resolve <alias|path|displayName>
  resolve-project.py --validate            # vérifie projectId <-> gitlabPath en live
  resolve-project.py --record <alias> --path <p> --id <n> --display "<nom>"

Stdlib uniquement.
"""
import argparse
import json
import os
import subprocess
import sys


class AmbiguousProject(Exception):
    pass


class ProjectNotFound(Exception):
    pass


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REGISTRY_FILENAME = "projects-registry.json"
TEMPLATE_FILENAME = "projects-registry.example.json"
INSTALLED_REGISTRY = os.path.expanduser(
    os.path.join("~", ".config", "opencode", "skills", "gitlab-feature-planner", REGISTRY_FILENAME)
)
# Registre privé (données réelles) — hors de tout repo, première priorité.
PRIVATE_REGISTRY = os.path.expanduser(
    os.path.join("~", ".config", "opencode", "gitlab-feature-planner-registry.private.json")
)


def registry_candidates():
    """Emplacements du registry, par priorité : config privée (données réelles) en
    tête, template example en dernier recours."""
    return [
        PRIVATE_REGISTRY,
        os.path.join(SCRIPT_DIR, REGISTRY_FILENAME),
        INSTALLED_REGISTRY,
        os.path.join(SCRIPT_DIR, TEMPLATE_FILENAME),
    ]


def registry_path():
    """Premier registry existant. None si aucun (ni réel ni template)."""
    for path in registry_candidates():
        if os.path.exists(path):
            return path
    return None


def load_registry(path=None):
    resolved = path or registry_path()
    if resolved is None or not os.path.exists(resolved):
        raise FileNotFoundError(
            "Aucun registry trouvé (attendu : projects-registry.json local ou projects-registry.example.json template)"
        )
    with open(resolved, encoding="utf-8") as f:
        data = json.load(f)
    return data


def resolve(query, reg):
    """Résout alias | projectId | gitlabPath | displayName (insensible à la casse)."""
    q = str(query).strip()
    if not q:
        raise ProjectNotFound("requête vide")
    for p in reg["projects"]:
        if q.lower() == p["alias"].lower():
            return p
    if q.isdigit():
        for p in reg["projects"]:
            if int(p["projectId"]) == int(q):
                return p
    for p in reg["projects"]:
        if q.lower() == p["gitlabPath"].lower():
            return p
    matches = [p for p in reg["projects"] if q.lower() == p["displayName"].lower()]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        raise AmbiguousProject(f"« {q} » correspond à plusieurs projets : {[p['alias'] for p in matches]}")
    # recherche partielle (prefix/sous-chaîne) — unique seulement, jamais de choix arbitraire
    partial = [
        p
        for p in reg["projects"]
        if q.lower() in p["alias"].lower()
        or q.lower() in p["gitlabPath"].lower()
        or q.lower() in p["displayName"].lower()
    ]
    if len(partial) == 1:
        return partial[0]
    if len(partial) > 1:
        raise AmbiguousProject(
            f"« {q} » correspond à plusieurs projets : {[p['alias'] for p in partial]} — demander confirmation"
        )
    raise ProjectNotFound(
        f"« {q} » absent du registry — recherche GitLab contrôlée (namespaces connus), puis confirmer avec l'utilisateur et mémoriser via --record"
    )


def validate_live(reg):
    """Vérifie en live que chaque projectId répond et que le path_with_namespace correspond."""
    errors = []
    for p in reg["projects"]:
        try:
            r = subprocess.run(
                ["glab", "api", f"projects/{p['projectId']}"],
                capture_output=True, text=True, timeout=30, check=True,
            )
            live = json.loads(r.stdout)
            if live.get("path_with_namespace") != p["gitlabPath"]:
                errors.append(
                    f"{p['alias']}: path live « {live.get('path_with_namespace')} » != registry « {p['gitlabPath']} »"
                )
            else:
                print(f"  ok  {p['alias']:18} {p['gitlabPath']} ({p['projectId']})")
        except subprocess.CalledProcessError as e:
            errors.append(f"{p['alias']}: accès impossible au projet {p['projectId']} — {e.stderr.strip()[:80]}")
        except (OSError, json.JSONDecodeError) as e:
            errors.append(f"{p['alias']}: erreur d'exécution — {e}")
    return errors


def record(reg, alias, gitlab_path, project_id, display):
    """Écrit DANS LE REGISTRE PRIVÉ (hors repo) : les données réelles (namespaces,
    IDs) ne vont jamais dans un fichier versionné du repo public."""
    target = PRIVATE_REGISTRY
    for p in reg["projects"]:
        if p["alias"] == alias:
            sys.exit(
                f"alias « {alias} » déjà présent dans le registry — rien à faire (modifier le fichier à la main si la valeur a changé)."
            )
    reg["projects"].append(
        {
            "alias": alias,
            "displayName": display or alias,
            "gitlabPath": gitlab_path,
            "projectId": int(project_id),
            "validated": True,
            "role": "",
        }
    )
    with open(target, "w", encoding="utf-8") as f:
        json.dump(reg, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(f"enregistré dans {target} : {alias} -> {gitlab_path} ({project_id})")


def main():
    ap = argparse.ArgumentParser(description="Résolution de projets GitLab via le registry du planner")
    ap.add_argument("--resolve", metavar="QUERY", help="alias, projectId, path ou displayName")
    ap.add_argument("--list", action="store_true", help="lister le registry")
    ap.add_argument("--validate", action="store_true", help="vérifier le registry en live (glab)")
    ap.add_argument("--record", metavar="ALIAS", help="mémoriser un projet validé (après confirmation humaine)")
    ap.add_argument("--path", help="gitlabPath du projet à enregistrer")
    ap.add_argument("--id", dest="project_id", help="projectId du projet à enregistrer")
    ap.add_argument("--display", help="displayName du projet à enregistrer")
    args = ap.parse_args()

    source = registry_path()
    reg = load_registry()
    if source:
        print(f"registry: {source}", file=sys.stderr)

    if args.list:
        for p in reg["projects"]:
            print(f"{p['alias']:18} {p['gitlabPath']:40} {p['projectId']}")
        return
    if args.resolve:
        try:
            p = resolve(args.resolve, reg)
            print(json.dumps(p, ensure_ascii=False, indent=2))
        except AmbiguousProject as e:
            sys.exit(f"AMBIGU — {e}\n→ ne rien créer, demander confirmation à l'utilisateur")
        except ProjectNotFound as e:
            sys.exit(f"INTROUVABLE — {e}")
        return
    if args.validate:
        errors = validate_live(reg)
        if errors:
            print("\n".join(f"ERREUR {e}" for e in errors), file=sys.stderr)
            sys.exit(1)
        print("Registry validé : tous les projets répondent avec le bon path.")
        return
    if args.record:
        if not (args.path and args.project_id):
            sys.exit("--record exige --path et --id")
        record(reg, args.record, args.path, args.project_id, args.display)
        return
    ap.print_help()


if __name__ == "__main__":
    main()
