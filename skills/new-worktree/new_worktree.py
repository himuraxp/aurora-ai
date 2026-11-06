#!/usr/bin/env python3
"""new-worktree — création déterministe d'une branche Git + worktree associé.

Responsabilités (SKILL.md — new-worktree) :
  - composer le nom de branche depuis --type/--context/--desc (ou --branch en passthrough)
  - détecter la branche de base SANS hardcode (origin/HEAD > ls-remote > glab > local)
  - vérifier branche locale/remote et worktree existant ; réutiliser au lieu de dupliquer
  - créer le worktree sous <parent-du-repo>/<repo>.worktrees/<branche-sans-/>
  - ne JAMAIS détruire : pas de reset/clean/stash/branch -D/worktree remove/prune

Usage :
  new_worktree.py --type feat --context podcast --desc "Dynamic form and config management"
  new_worktree.py --type feat --context trello-EX12345
  new_worktree.py --type fix --context rm-1234 --desc "Fix infinite playlist loading"
  new_worktree.py --branch "feat/podcast--dynamic-form-and-config-management"
  new_worktree.py --type feat --context podcast --dry-run
  new_worktree.py --list

Options : --repo <path> (défaut cwd), --base <name>, --remote <name>, --dry-run, --list.

Sortie (stdout) :
  Branch: <branche>
  Base: <branche de base — affichée quand pertinente (création, dry-run)>
  Worktree: <chemin absolu>
  Status: created | branch reused | existing worktree reused | dry-run

Avertissements et erreurs -> stderr. Exit 0 succès, 1 erreur propre.
Stdlib uniquement, compatible Python 3.9.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import unicodedata
from typing import NoReturn

MAX_BRANCH_LEN = 100
DIGEST_LEN = 8
FETCH_TIMEOUT = 30
NETWORK_TIMEOUT = 10
# Ordre du fallback local : convention Infomaniak (develop = branche d'intégration,
# cf. check_workspace.sh qui protège develop comme main/master) puis main puis master.
LOCAL_BASE_CANDIDATES = ["develop", "main", "master"]


def warn(message: str) -> None:
    print(f"warning: {message}", file=sys.stderr)


def die(message: str) -> "NoReturn":
    print(f"error: {message}", file=sys.stderr)
    sys.exit(1)


from typing import NoReturn


def run_git(
    args, cwd, timeout=None, check=True
):
    """Lance git -C cwd args ; renvoie stdout ou None (check=False + échec)."""
    try:
        proc = subprocess.run(
            ["git", "-C", cwd] + args,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        if check:
            die(f"git {' '.join(args)} a échoué : {exc}")
        return None
    if check and proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip().splitlines()
        die(f"git {' '.join(args)} a échoué : {detail[0] if detail else 'erreur inconnue'}")
    return proc.stdout if proc.returncode == 0 else None


# ---------------------------------------------------------------- slug & branche


def slugify(text: str, lowercase: bool = True) -> str:
    """Accents/apostrophes/ponctuation -> kebab ; casse conservée si lowercase=False."""
    s = unicodedata.normalize("NFKD", text)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.replace("\u2019", "").replace("\u2018", "").replace("'", "")
    s = re.sub(r"[^A-Za-z0-9]+", "-", s)
    s = re.sub(r"-{2,}", "-", s).strip("-")
    return s.lower() if lowercase else s


def compose_branch(branch_type: str, context: str, desc: "str | None" = None) -> str:
    """<type>/<contexte> [-- <desc kebab lowercase>]. Identifiants : casse préservée."""
    if not re.fullmatch(r"[a-z][a-z0-9]*", branch_type or ""):
        die(
            f"type de branche invalide : « {branch_type} » — attendu un token simple "
            f"(feat, fix, refactor, chore, docs, test...). Pour un nom complet, utiliser --branch."
        )
    context_slug = slugify(context or "", lowercase=False)
    if not context_slug:
        die("contexte absent ou invalide (1er token après le type) — ou utiliser --branch")
    branch = f"{branch_type}/{context_slug}"
    desc_slug = slugify(desc or "", lowercase=True)
    if desc_slug:
        branch += f"--{desc_slug}"
    if len(branch) <= MAX_BRANCH_LEN:
        return branch
    # Trop long : tronquer la description + suffixe digest pour rester unique.
    digest = hashlib.sha256(branch.encode("utf-8")).hexdigest()[:DIGEST_LEN]
    if desc_slug:
        prefix = f"{branch_type}/{context_slug}--"
        budget = MAX_BRANCH_LEN - len(prefix) - DIGEST_LEN - 1
        if budget <= 0:
            die(
                f"préfixe « {prefix} » trop long pour une branche de {MAX_BRANCH_LEN} chars — raccourcir le contexte"
            )
        branch = f"{prefix}{desc_slug[:budget].rstrip('-')}-{digest}"
    else:
        prefix = f"{branch_type}/"
        budget = MAX_BRANCH_LEN - len(prefix) - DIGEST_LEN - 1
        branch = f"{prefix}{context_slug[:budget].rstrip('-')}-{digest}"
    return branch


# ---------------------------------------------------------------- repo & refs


def resolve_main_toplevel(repo_arg: str | None) -> tuple[str, str]:
    """Retourne (main_toplevel, cwd_repo).

    Un worktree lié est détecté par --git-dir != --git-common-dir (robuste :
    submodule, --separate-git-dir et worktree imbriqué restent corrects).
    """
    cwd_repo = os.path.abspath(repo_arg or os.getcwd())
    if not os.path.isdir(cwd_repo):
        die(f"répertoire introuvable : {cwd_repo}")

    def git_path(flag: str) -> str | None:
        out = run_git(["rev-parse", "--path-format=absolute", flag], cwd_repo, check=False)
        if out is None:
            out = run_git(["rev-parse", flag], cwd_repo, check=False)
            if out is None:
                return None
            return os.path.abspath(os.path.join(cwd_repo, out.strip()))
        return os.path.abspath(out.strip())

    toplevel_out = run_git(["rev-parse", "--show-toplevel"], cwd_repo, check=False)
    toplevel = os.path.abspath(toplevel_out.strip()) if toplevel_out else None
    gitdir = git_path("--git-dir")
    common = git_path("--git-common-dir")

    if toplevel and gitdir and common and gitdir != common:
        # worktree lié -> le repo principal est le parent du .git commun
        return os.path.dirname(common), cwd_repo
    if toplevel:
        return toplevel, cwd_repo
    if common:
        # dépôt bare : /x/repo.git -> main = /x, nom = repo (sans .git)
        name = os.path.basename(common.rstrip("/"))
        if name.endswith(".git"):
            name = name[: -len(".git")]
        return os.path.join(os.path.dirname(common.rstrip("/")), name), cwd_repo
    die(f"pas un dépôt Git (ni cwd ni parent) : {cwd_repo}")


def pick_remote(cwd_repo: str, remote_arg: str | None) -> str | None:
    remotes = (run_git(["remote"], cwd_repo, check=False) or "").split()
    if not remotes:
        return None
    if remote_arg:
        if remote_arg not in remotes:
            die(f"remote « {remote_arg} » introuvable — remotes : {', '.join(remotes)}")
        return remote_arg
    if "origin" in remotes:
        return "origin"
    return sorted(remotes)[0]


def fetch_remote(cwd_repo: str, remote: str | None) -> None:
    if not remote:
        return
    stdout = run_git(["fetch", remote, "--prune", "--quiet"], cwd_repo, timeout=FETCH_TIMEOUT, check=False)
    if stdout is None:
        warn(f"remote « {remote} » inaccessible — poursuite avec les références locales")


def ref_exists(cwd_repo: str, ref: str) -> bool:
    return run_git(["show-ref", "--verify", "--quiet", ref], cwd_repo, check=False) is not None


# ---------------------------------------------------------------- base branch


def detect_base(cwd_repo: str, remote: str | None, explicit: str | None) -> str:
    """--base > origin/HEAD symref > ls-remote symref > glab > candidats locaux > HEAD.

    Chaque candidat est validé (la ref doit exister) avant d'être retenu.
    """
    if explicit:
        if ref_exists(cwd_repo, f"refs/heads/{explicit}"):
            return explicit
        if remote and ref_exists(cwd_repo, f"refs/remotes/{remote}/{explicit}"):
            return explicit
        die(f"--base « {explicit} » introuvable en local ni sur « {remote or 'aucun remote'} »")

    if remote:
        sym = run_git(["symbolic-ref", f"refs/remotes/{remote}/HEAD"], cwd_repo, check=False)
        if sym:
            name = sym.strip()
            prefix = f"refs/remotes/{remote}/"
            if name.startswith(prefix) and ref_exists(cwd_repo, name):
                return name[len(prefix):]
        # réseau : universel (GitLab, GitHub...) — symref de HEAD
        ls = run_git(
            ["ls-remote", "--symref", remote, "HEAD"], cwd_repo, timeout=NETWORK_TIMEOUT, check=False
        )
        if ls:
            match = re.search(r"^ref:\s+refs/heads/(\S+)\s+HEAD\s*$", ls, re.MULTILINE)
            if match:
                return match.group(1)
        # GitLab : glab (même logique que scripts/create-mr/detect_target_branch.sh)
        if _glab_available():
            out = run_other(
                ["glab", "repo", "view", "--output", "json"], cwd_repo, NETWORK_TIMEOUT, check=False
            )
            if out:
                try:
                    name = json.loads(out).get("default_branch") or ""
                except json.JSONDecodeError:
                    name = ""
                if name:
                    return name

    for candidate in LOCAL_BASE_CANDIDATES:
        if ref_exists(cwd_repo, f"refs/heads/{candidate}"):
            return candidate
        if remote and ref_exists(cwd_repo, f"refs/remotes/{remote}/{candidate}"):
            return candidate
    head = (run_git(["rev-parse", "--abbrev-ref", "HEAD"], cwd_repo, check=False) or "").strip()
    return head or "HEAD"


def _glab_available() -> bool:
    try:
        subprocess.run(["glab", "--version"], capture_output=True, timeout=5)
        return True
    except (OSError, subprocess.SubprocessError):
        return False


def run_other(args, cwd, timeout=None, check=True):
    try:
        proc = subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as exc:
        if check:
            die(f"{' '.join(args)} a échoué : {exc}")
        return None
    if check and proc.returncode != 0:
        detail = (proc.stderr or "").strip().splitlines()
        die(f"{' '.join(args)} a échoué : {detail[0] if detail else 'erreur inconnue'}")
    return proc.stdout if proc.returncode == 0 else None


# ---------------------------------------------------------------- worktrees


def parse_worktrees(cwd_repo: str):
    """git worktree list --porcelain -> [{path, branch}] (branch=None si détaché)."""
    out = run_git(["worktree", "list", "--porcelain"], cwd_repo, check=False) or ""
    entries, current = [], {}
    for line in out.splitlines():
        if line.startswith("worktree "):
            current = {"path": line[len("worktree "):].strip(), "branch": None}
            entries.append(current)
        elif line.startswith("branch ") and current:
            current["branch"] = line[len("branch "):].strip()
    return entries


def worktree_for_branch(cwd_repo: str, branch: str):
    for entry in parse_worktrees(cwd_repo):
        if entry["branch"] == f"refs/heads/{branch}" and os.path.isdir(entry["path"]):
            return entry["path"]
    return None


def worktree_root(main_toplevel: str) -> str:
    name = os.path.basename(main_toplevel.rstrip("/"))
    if name.endswith(".git"):
        name = name[: -len(".git")]
    parent = os.path.dirname(main_toplevel.rstrip("/"))
    return os.path.join(parent, f"{name}.worktrees")


def branch_dirname(branch: str) -> str:
    """Le « / » du nom de branche ne crée PAS de dossier : remplacé par « - »."""
    return branch.replace("/", "-")


def ensure_valid_branch_name(cwd_repo: str, branch: str) -> None:
    out = run_other(["git", "check-ref-format", "--branch", branch], cwd_repo, check=False)
    if out is None:
        die(f"nom de branche invalide pour Git : « {branch} »")


# ---------------------------------------------------------------- pipeline


def create_worktree(args) -> None:
    main_toplevel, cwd_repo = resolve_main_toplevel(args.repo)

    if args.list:
        for entry in parse_worktrees(cwd_repo):
            label = entry["branch"] or "(détaché)"
            print(f"{entry['path']}  {label}")
        return

    if args.branch:
        branch = args.branch.strip()
        ensure_valid_branch_name(cwd_repo, branch)
    else:
        branch = compose_branch(args.type, args.context, args.desc)
        ensure_valid_branch_name(cwd_repo, branch)

    remote = pick_remote(cwd_repo, args.remote)
    fetch_remote(cwd_repo, remote)

    local_exists = ref_exists(cwd_repo, f"refs/heads/{branch}")
    remote_exists = bool(remote) and ref_exists(cwd_repo, f"refs/remotes/{remote}/{branch}")

    root = worktree_root(main_toplevel)
    wt_path = os.path.join(root, branch_dirname(branch))

    existing = worktree_for_branch(cwd_repo, branch)
    if existing:
        emit(branch, "", existing, "existing worktree reused")
        return

    if os.path.exists(wt_path):
        die(
            f"le chemin existe déjà et n'est pas le worktree de « {branch} » : {wt_path}\n"
            f"  -> vérifier l'état manuellement (jamais de suppression automatique)"
        )

    if local_exists:
        # branche locale existante : on la réutilise telle quelle (jamais de reset/force)
        run_git(["worktree", "add", wt_path, branch], cwd_repo)
        emit(branch, "", wt_path, "branch reused")
        return
    if remote_exists:
        # branche uniquement sur le remote : -b + start-point explicite évite
        # l'ambiguïté quand la branche existe sur plusieurs remotes (R-05)
        run_git(["worktree", "add", "-b", branch, wt_path, f"{remote}/{branch}"], cwd_repo)
        emit(branch, "", wt_path, "branch reused")
        return

    if not ref_exists(cwd_repo, "HEAD"):
        die("dépôt sans aucun commit — créer un commit initial avant de créer une branche")
    base = detect_base(cwd_repo, remote, args.base)
    startpoint = base
    if not ref_exists(cwd_repo, f"refs/heads/{base}"):
        if remote and ref_exists(cwd_repo, f"refs/remotes/{remote}/{base}"):
            startpoint = f"{remote}/{base}"
        elif base == "HEAD":
            startpoint = "HEAD"
        else:
            die(
                f"branche de base « {base} » introuvable (local + remote) — préciser --base ou vérifier le remote"
            )
    run_git(["worktree", "add", "-b", branch, wt_path, startpoint], cwd_repo)
    emit(branch, base, wt_path, "created")


def emit(branch: str, base: str, path: str, status: str) -> None:
    print(f"Branch: {branch}")
    if base:
        print(f"Base: {base}")
    print(f"Worktree: {path}")
    print(f"Status: {status}")


def dry_run(args) -> None:
    main_toplevel, cwd_repo = resolve_main_toplevel(args.repo)
    if args.branch:
        branch = args.branch.strip()
        ensure_valid_branch_name(cwd_repo, branch)
    else:
        branch = compose_branch(args.type, args.context, args.desc)
        ensure_valid_branch_name(cwd_repo, branch)
    remote = pick_remote(cwd_repo, args.remote)
    base = detect_base(cwd_repo, remote, args.base)
    wt_path = os.path.join(worktree_root(main_toplevel), branch_dirname(branch))
    existing = worktree_for_branch(cwd_repo, branch)
    if existing:
        emit(branch, "", existing, "existing worktree reused")
        return
    if os.path.exists(wt_path):
        die(
            f"(dry-run) le chemin existe déjà et n'est pas le worktree de « {branch} » : {wt_path}\n"
            f"  -> le run réel échouera ; vérifier l'état manuellement (jamais de suppression automatique)"
        )
    emit(branch, base, wt_path, "dry-run")


def main() -> None:
    ap = argparse.ArgumentParser(
        description="new-worktree : branche Git + worktree associé (aucune opération destructive)"
    )
    ap.add_argument("--type", help="type de branche : feat, fix, refactor, chore, docs, test...")
    ap.add_argument("--context", help="contexte principal ou identifiant (podcast, rm-1234, trello-XXX)")
    ap.add_argument("--desc", help="description en anglais (traduite par l'agent avant l'appel)")
    ap.add_argument("--branch", help="nom de branche complet (passthrough, écrase --type/--context/--desc)")
    ap.add_argument("--base", help="branche de base explicite (sinon détection automatique)")
    ap.add_argument("--remote", help="remote explicite (défaut : origin, sinon premier remote)")
    ap.add_argument("--repo", help="chemin du dépôt (défaut : répertoire courant)")
    ap.add_argument("--dry-run", action="store_true", help="afficher le plan sans rien créer")
    ap.add_argument("--list", action="store_true", help="lister les worktrees du dépôt")
    args = ap.parse_args()

    if not args.list and not args.branch:
        if not args.type:
            die("--type requis (ou --branch pour un nom complet)")
        if not args.context and not args.desc:
            die("--context requis (contexte ou identifiant) — ou utiliser --branch")

    if args.dry_run:
        dry_run(args)
    else:
        create_worktree(args)


if __name__ == "__main__":
    main()
