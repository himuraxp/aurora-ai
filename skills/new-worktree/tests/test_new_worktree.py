"""Tests du skill new-worktree — nommage + opérations Git e2e (dépôts temporaires).

Cas couverts :
- les 5 scénarios de nommage canoniques (feat podcast desc FR, trello, rm-XXXX,
  rm-XXXX + desc FR, desc déjà anglaise)
- slugify : accents, apostrophes, ponctuation, majuscules d'identifiants,
  troncature des noms trop longs
- e2e git : création, réutilisation worktree/branche, branche remote-only,
  sans remote (fallback develop), sous-dossier, worktree existant (repo
  principal résolu), dépôt dirty, collision de chemin, dry-run, type invalide

Run :
    python3 -m unittest discover -s skills/new-worktree/tests -v
"""

import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.join(HERE, "..")
SCRIPT = os.path.join(SKILL_DIR, "new_worktree.py")


# ----------------------------------------------------------------- helpers


def run_script(args, cwd=None):
    return subprocess.run(
        [sys.executable, SCRIPT] + args, cwd=cwd, capture_output=True, text=True
    )


def git(args, cwd=None, expect=0):
    # Sécurité : cwd par défaut = tmp système (jamais le repo courant du process)
    if cwd is None:
        cwd = tempfile.gettempdir()
    proc = subprocess.run(["git"] + args, cwd=cwd, capture_output=True, text=True)
    if expect is not None and proc.returncode != expect:
        raise AssertionError(
            f"git {' '.join(args)} -> rc={proc.returncode}\n{proc.stdout}\n{proc.stderr}"
        )
    return proc.stdout.strip()


def parse_block(stdout):
    """'Branch: x\nBase: y\n...' -> dict."""
    block = {}
    for line in stdout.strip().splitlines():
        if ": " in line:
            key, value = line.split(": ", 1)
            block[key.strip()] = value.strip()
    return block


class GitFixture(unittest.TestCase):
    """Dépôt clone d'une origine bare (origin/HEAD positionné par le clone)."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="nwt-test-")

    def tearDown(self):
        subprocess.run(["rm", "-rf", self.tmp], check=False)

    def _commit(self, repo, message="init"):
        path = os.path.join(repo, "file.txt")
        with open(path, "a", encoding="utf-8") as f:
            f.write(message + "\n")
        git(["add", "."], cwd=repo)
        git(
            ["-c", "commit.gpgsign=false", "commit", "-m", message],
            cwd=repo,
        )

    def make_repo(self, name, default="main", with_develop=False, with_remote=True):
        seed = os.path.join(self.tmp, f"seed-{name}")
        git(["init", "-b", default, seed])
        git(["config", "user.email", "test@test.local"], cwd=seed)
        git(["config", "user.name", "test"], cwd=seed)
        self._commit(seed)
        if with_develop:
            git(["branch", "develop"], cwd=seed)
        if with_remote:
            origin = os.path.join(self.tmp, f"origin-{name}.git")
            git(["init", "--bare", "-b", default, origin])
            git(["remote", "add", "origin", origin], cwd=seed)
            git(["push", "-u", "origin", "HEAD"], cwd=seed)
            clone_from = origin
        else:
            clone_from = seed
        repo = os.path.join(self.tmp, f"repo-{name}")
        git(["clone", clone_from, repo])
        git(["config", "user.email", "test@test.local"], cwd=repo)
        git(["config", "user.name", "test"], cwd=repo)
        return repo

    def script(self, args, cwd):
        return run_script(args, cwd=cwd)

    # arguments standard du test en cours
    def std(self, type_="feat", context="podcast", desc=None):
        args = ["--type", type_, "--context", context]
        if desc is not None:
            args += ["--desc", desc]
        return args


# ----------------------------------------------------------------- nommage pur


class TestNaming(unittest.TestCase):
    """compose_branch / slugify — les 5 scénarios + robustesse.

    Contrat : l'AGENT traduit la description FR → EN (étape 2 du SKILL.md),
    le script reçoit l'anglais et le slugifie. La map AGENT_TRANSLATIONS
    simule l'étape LLM pour vérifier le pipeline complet intention → branche.
    """

    AGENT_TRANSLATIONS = {
        "Gestion des formulaires et config dynamique": "dynamic form and config management",
        "Corriger le chargement infini des playlists": "fix infinite playlist loading",
        "Dynamic configuration management": "Dynamic configuration management",  # déjà EN : inchangé
    }

    def agent_desc(self, text):
        return self.AGENT_TRANSLATIONS[text]

    def import_script(self):
        sys.path.insert(0, SKILL_DIR)
        import new_worktree  # noqa

        return new_worktree

    def test_scenario_podcast_fr(self):
        nwt = self.import_script()
        desc = self.agent_desc("Gestion des formulaires et config dynamique")
        self.assertEqual(
            nwt.compose_branch("feat", "podcast", desc),
            "feat/podcast--dynamic-form-and-config-management",
        )

    def test_scenario_trello_id(self):
        nwt = self.import_script()
        self.assertEqual(nwt.compose_branch("feat", "trello-EX12345", None), "feat/trello-EX12345")

    def test_scenario_rm_id(self):
        nwt = self.import_script()
        self.assertEqual(nwt.compose_branch("fix", "rm-1234", None), "fix/rm-1234")

    def test_scenario_rm_with_fr_desc(self):
        nwt = self.import_script()
        desc = self.agent_desc("Corriger le chargement infini des playlists")
        self.assertEqual(
            nwt.compose_branch("fix", "rm-1234", desc),
            "fix/rm-1234--fix-infinite-playlist-loading",
        )

    def test_scenario_english_not_retranslated(self):
        nwt = self.import_script()
        desc = self.agent_desc("Dynamic configuration management")
        self.assertEqual(
            nwt.compose_branch("feat", "podcast", desc),
            "feat/podcast--dynamic-configuration-management",
        )

    def test_slugify_accents_apostrophes_punctuation(self):
        nwt = self.import_script()
        self.assertEqual(nwt.slugify("Création d'espaces — UI/UX !"), "creation-despaces-ui-ux")
        self.assertEqual(nwt.slugify("Configuration dynamique & robuste"), "configuration-dynamique-robuste")

    def test_slugify_preserves_id_case(self):
        nwt = self.import_script()
        self.assertEqual(nwt.slugify("trello-EX12345", lowercase=False), "trello-EX12345")
        self.assertEqual(nwt.slugify("rm-1234", lowercase=False), "rm-1234")

    def test_long_branch_truncated_with_digest(self):
        nwt = self.import_script()
        long_desc = " ".join(["very long functional description word"] * 12)
        branch = nwt.compose_branch("feat", "podcast", long_desc)
        self.assertLessEqual(len(branch), nwt.MAX_BRANCH_LEN)
        self.assertTrue(branch.startswith("feat/podcast--very-long-functional"))
        self.assertRegex(branch, r"-[0-9a-f]{8}$")

    def test_invalid_type_rejected(self):
        nwt = self.import_script()
        with self.assertRaises(SystemExit):
            nwt.compose_branch("feat/podcast", "x", None)
        with self.assertRaises(SystemExit):
            nwt.compose_branch("FeAt", "x", None)


# ----------------------------------------------------------------- e2e git


class TestGitOps(GitFixture):
    def test_created_branch_and_worktree(self):
        repo = self.make_repo("a")
        proc = self.script(self.std(desc="dynamic form and config management"), cwd=repo)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        block = parse_block(proc.stdout)
        self.assertEqual(block["Branch"], "feat/podcast--dynamic-form-and-config-management")
        self.assertEqual(block["Base"], "main")  # origin/HEAD du clone
        self.assertEqual(block["Status"], "created")
        self.assertTrue(os.path.isdir(block["Worktree"]))
        # real path (symlinks macOS : /var -> /private/var)
        self.assertEqual(
            os.path.dirname(os.path.realpath(block["Worktree"])),
            os.path.join(os.path.realpath(os.path.dirname(repo)), "repo-a.worktrees"),
        )
        # la branche existe et le worktree pointe dessus
        self.assertEqual(
            git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=block["Worktree"]),
            block["Branch"],
        )

    def test_existing_worktree_reused(self):
        repo = self.make_repo("b")
        first = parse_block(self.script(self.std(desc="dynamic form and config management"), cwd=repo).stdout)
        second = parse_block(self.script(self.std(desc="dynamic form and config management"), cwd=repo).stdout)
        self.assertEqual(second["Status"], "existing worktree reused")
        self.assertEqual(first["Worktree"], second["Worktree"])
        # un seul worktree pour cette branche
        listing = git(["worktree", "list", "--porcelain"], cwd=repo)
        self.assertEqual(listing.count("branch refs/heads/" + first["Branch"]), 1)

    def test_existing_local_branch_reused_no_worktree(self):
        repo = self.make_repo("c")
        git(["branch", "fix/rm-99"], cwd=repo)
        proc = self.script(self.std(type_="fix", context="rm-99"), cwd=repo)
        block = parse_block(proc.stdout)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(block["Branch"], "fix/rm-99")
        self.assertEqual(block["Status"], "branch reused")
        self.assertTrue(os.path.isdir(block["Worktree"]))

    def test_remote_only_branch_created_local_dwim(self):
        repo = self.make_repo("d")
        # branche poussée depuis l'origine, jamais fetchée en local -> simulé :
        # on pousse une branche directement dans l'origin bare puis on fetch
        origin = os.path.join(self.tmp, "origin-d.git")
        tmp_clone = os.path.join(self.tmp, "tmp-clone-d")
        git(["clone", origin, tmp_clone])
        git(["config", "user.email", "t@t"], cwd=tmp_clone)
        git(["config", "user.name", "t"], cwd=tmp_clone)
        git(["checkout", "-b", "fix/rm-77"], cwd=tmp_clone)
        self._commit(tmp_clone, "remote work")
        git(["push", "-u", "origin", "fix/rm-77"], cwd=tmp_clone)
        git(["fetch", "origin", "--prune"], cwd=repo)  # refs remote présentes, pas de branche locale
        proc = self.script(self.std(type_="fix", context="rm-77"), cwd=repo)
        block = parse_block(proc.stdout)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(block["Status"], "branch reused")
        self.assertEqual(
            git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=block["Worktree"]), "fix/rm-77"
        )

    def test_no_remote_fallback_develop_priority(self):
        # git clone (même d'un dossier) crée un remote origin -> repo 100% local
        repo = os.path.join(self.tmp, "repo-no-remote")
        git(["init", "-b", "master", repo])
        git(["config", "user.email", "test@test.local"], cwd=repo)
        git(["config", "user.name", "test"], cwd=repo)
        self._commit(repo)
        git(["branch", "develop"], cwd=repo)
        proc = self.script(self.std(desc="dynamic form and config management"), cwd=repo)
        block = parse_block(proc.stdout)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(block["Base"], "develop")  # convention Infomaniak avant main/master

    def test_base_explicit_override(self):
        repo = self.make_repo("f", default="main", with_develop=True)
        proc = self.script(self.std(desc="x") + ["--base", "main"], cwd=repo)
        block = parse_block(proc.stdout)
        self.assertEqual(block["Base"], "main")

    def test_invocation_from_subdirectory(self):
        repo = self.make_repo("g")
        subdir = os.path.join(repo, "src", "deep")
        os.makedirs(subdir, exist_ok=True)
        proc = self.script(self.std(desc="dynamic form and config management"), cwd=subdir)
        block = parse_block(proc.stdout)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(block["Status"], "created")
        self.assertTrue(os.path.isdir(block["Worktree"]))

    def test_dirty_main_repo_not_blocked(self):
        repo = self.make_repo("h")
        dirty_file = os.path.join(repo, "file.txt")
        with open(dirty_file, "a", encoding="utf-8") as f:
            f.write("uncommitted local change\n")
        proc = self.script(self.std(desc="dynamic form and config management"), cwd=repo)
        block = parse_block(proc.stdout)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(block["Status"], "created")
        # la modification locale est intacte
        with open(dirty_file, encoding="utf-8") as f:
            self.assertIn("uncommitted local change", f.read())

    def test_invocation_from_inside_existing_worktree(self):
        repo = self.make_repo("i")
        first = parse_block(self.script(self.std(context="one"), cwd=repo).stdout)
        second = parse_block(self.script(self.std(context="two"), cwd=first["Worktree"]).stdout)
        self.assertEqual(second["Status"], "created")
        # le 2e worktree sort du repo principal, pas du 1er worktree
        self.assertEqual(
            os.path.dirname(os.path.realpath(second["Worktree"])),
            os.path.join(os.path.realpath(os.path.dirname(repo)), "repo-i.worktrees"),
        )

    def test_path_collision_clean_error(self):
        repo = self.make_repo("j")
        expected_dir = os.path.join(
            os.path.realpath(os.path.dirname(repo)), "repo-j.worktrees", "feat-podcast"
        )
        os.makedirs(expected_dir, exist_ok=True)
        with open(os.path.join(expected_dir, "keep-me.txt"), "w", encoding="utf-8") as f:
            f.write("precious\n")
        proc = self.script(self.std(), cwd=repo)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("existe déjà", proc.stderr)
        # rien n'a été supprimé
        self.assertTrue(os.path.isfile(os.path.join(expected_dir, "keep-me.txt")))

    def test_dry_run_creates_nothing(self):
        repo = self.make_repo("k")
        proc = self.script(self.std(desc="dynamic form and config management") + ["--dry-run"], cwd=repo)
        block = parse_block(proc.stdout)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(block["Status"], "dry-run")
        self.assertFalse(os.path.exists(block["Worktree"]))
        self.assertEqual(git(["branch", "--list", "feat/podcast*"], cwd=repo), "")

    def test_list_worktrees(self):
        repo = self.make_repo("l")
        self.script(self.std(), cwd=repo)
        proc = self.script(["--list"], cwd=repo)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("feat/podcast", proc.stdout)

    def test_invalid_type_fails_clean(self):
        repo = self.make_repo("m")
        proc = self.script(["--type", "feat/x", "--context", "podcast"], cwd=repo)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("invalide", proc.stderr)

    def test_not_a_repo_fails_clean(self):
        outside = os.path.join(self.tmp, "not-a-repo")
        os.makedirs(outside)
        proc = self.script(self.std(), cwd=outside)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("Git", proc.stderr)

    # --- mode --branch (passthrough) — R-03

    def test_branch_passthrough_create_and_reuse(self):
        repo = self.make_repo("n")
        args = ["--branch", "feat/podcast--dynamic-form-and-config-management"]
        first = parse_block(self.script(args, cwd=repo).stdout)
        self.assertEqual(first["Status"], "created")
        self.assertTrue(os.path.isdir(first["Worktree"]))
        second = parse_block(self.script(args, cwd=repo).stdout)
        self.assertEqual(second["Status"], "existing worktree reused")
        self.assertEqual(first["Worktree"], second["Worktree"])

    def test_branch_passthrough_invalid_fails_without_creating(self):
        repo = self.make_repo("o")
        proc = self.script(["--branch", "a..b"], cwd=repo)
        self.assertEqual(proc.returncode, 1)
        self.assertEqual(git(["branch", "--list", "a*"], cwd=repo), "")
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "repo-o.worktrees")))

    # --- remote inaccessible — R-04

    def test_remote_inaccessible_warns_and_continues(self):
        repo = self.make_repo("p")
        git(["remote", "set-url", "origin", os.path.join(self.tmp, "gone.git")], cwd=repo)
        proc = self.script(self.std(desc="dynamic form and config management"), cwd=repo)
        block = parse_block(proc.stdout)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("warning", proc.stderr)
        self.assertIn("inaccessible", proc.stderr)
        self.assertEqual(block["Status"], "created")

    # --- dépôt bare — R-10 partiel

    def test_bare_repo_worktree_sibling(self):
        seed = os.path.join(self.tmp, "seed-bare")
        git(["init", "-b", "main", seed])
        git(["config", "user.email", "t@t"], cwd=seed)
        git(["config", "user.name", "t"], cwd=seed)
        self._commit(seed)
        bare = os.path.join(self.tmp, "project-bare.git")
        git(["clone", "--bare", seed, bare])
        proc = self.script(self.std(), cwd=bare)
        block = parse_block(proc.stdout)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(block["Status"], "created")
        self.assertEqual(
            os.path.dirname(os.path.realpath(block["Worktree"])),
            os.path.join(os.path.realpath(self.tmp), "project-bare.worktrees"),
        )


if __name__ == "__main__":
    unittest.main()
