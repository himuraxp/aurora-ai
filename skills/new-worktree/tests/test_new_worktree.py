"""Tests du skill new-worktree — nommage + opérations Git e2e (dépôts temporaires).

Cas couverts :
- les 5 scénarios de nommage canoniques (feat podcast desc FR, trello, rm-XXXX,
  rm-XXXX + desc FR, desc déjà anglaise)
- slugify : accents, apostrophes, ponctuation, majuscules d'identifiants,
  troncature des noms trop longs
- e2e git : création, réutilisation worktree/branche, branche remote-only,
  sans remote (fallback develop), sous-dossier, worktree existant (repo
  principal résolu), dépôt dirty, collision de chemin, dry-run, type invalide
- e2e orca (fake CLI) : création + chat lié, passthrough --prompt/--orca-agent,
  fallback Git (runtime fermé, échec create, réponse illisible), --no-orca,
  réutilisation prioritaire (jamais d'appel orca), dry-run

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
        # Herméticité : les e2e Git ne doivent jamais toucher un Orca réel —
        # NW_ORCA_BIN pointe sur un binaire inexistant (bascule Git immédiate).
        self._old_env = {
            k: os.environ.get(k) for k in ("NW_ORCA_BIN", "NW_FAKE_DIR", "NW_ORCA_AGENT")
        }
        os.environ["NW_ORCA_BIN"] = "nw-no-such-orca-binary"
        os.environ.pop("NW_FAKE_DIR", None)
        os.environ.pop("NW_ORCA_AGENT", None)
        self.addCleanup(self._restore_env)

    def _restore_env(self):
        for key, value in self._old_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

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
        self.assertEqual(block["Base"], "develop")  # convention gitflow avant main/master

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


# ----------------------------------------------------------------- e2e orca


class OrcaFixture(GitFixture):
    """GitFixture + fake `orca` (NW_ORCA_BIN -> fixtures/fake_orca.sh)."""

    def setUp(self):
        super().setUp()
        self.fake_dir = os.path.join(self.tmp, "fake-orca")
        os.makedirs(self.fake_dir)
        os.environ["NW_FAKE_DIR"] = self.fake_dir
        os.environ["NW_ORCA_BIN"] = os.path.join(HERE, "fixtures", "fake_orca.sh")

    def fake_args(self):
        path = os.path.join(self.fake_dir, "args.log")
        if not os.path.exists(path):
            return []
        with open(path, encoding="utf-8") as f:
            return [line.strip() for line in f if line.strip()]


class TestOrcaMode(OrcaFixture):
    """Mode Orca natif : création + chat lié, fallback Git, réutilisation prioritaire."""

    BRANCH = "feat/podcast--dynamic-form-and-config-management"
    NAME = "feat-podcast--dynamic-form-and-config-management"
    STD = ["--type", "feat", "--context", "podcast", "--desc", "dynamic form and config management"]

    def test_orca_create_success_chat_linked(self):
        repo = self.make_repo("oa")
        proc = self.script(self.STD, cwd=repo)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        block = parse_block(proc.stdout)
        self.assertEqual(block["Branch"], self.BRANCH)
        self.assertEqual(block["Status"], "created")
        self.assertIn("structured chat", block["Chat"])
        self.assertIn("opened as chat", block["Chat"])
        expected_wt = os.path.join(self.fake_dir, "orca-ws", self.NAME)
        self.assertEqual(os.path.realpath(block["Worktree"]), os.path.realpath(expected_wt))
        # aucune création Git : le worktree Orca n'apparaît pas dans le dépôt
        listing = git(["worktree", "list", "--porcelain"], cwd=repo)
        self.assertNotIn(self.BRANCH, listing)
        # les flags exacts transmis à orca
        [create_line] = [line for line in self.fake_args() if line.startswith("worktree create")]
        self.assertIn("--repo name:repo-oa", create_line)
        self.assertIn(f"--name {self.NAME}", create_line)
        self.assertIn(f"--branch {self.BRANCH}", create_line)
        self.assertIn("--agent opencode", create_line)
        self.assertIn("--base-branch main", create_line)  # origin/HEAD du clone
        self.assertIn("--json", create_line)

    def test_orca_prompt_passthrough(self):
        repo = self.make_repo("ob")
        proc = self.script(self.STD + ["--prompt", "Brief autonome de tache"], cwd=repo)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        [create_line] = [line for line in self.fake_args() if line.startswith("worktree create")]
        self.assertIn("--prompt Brief autonome de tache", create_line)

    def test_orca_runtime_down_falls_back_to_git(self):
        repo = self.make_repo("oc")
        open(os.path.join(self.fake_dir, "runtime-down"), "w").close()
        proc = self.script(self.STD, cwd=repo)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        block = parse_block(proc.stdout)
        self.assertEqual(block["Status"], "created")
        self.assertNotIn("Chat", block)
        self.assertTrue(os.path.isdir(block["Worktree"]))  # layout Git classique
        self.assertEqual(self.fake_args(), ["status"])  # jamais de création orca

    def test_orca_create_failure_falls_back_to_git(self):
        repo = self.make_repo("od")
        open(os.path.join(self.fake_dir, "create-fails"), "w").close()
        proc = self.script(self.STD, cwd=repo)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        block = parse_block(proc.stdout)
        self.assertEqual(block["Status"], "created")
        self.assertNotIn("Chat", block)
        self.assertTrue(os.path.isdir(block["Worktree"]))
        self.assertIn("création Git classique", proc.stderr)

    def test_orca_bad_json_falls_back_to_git(self):
        repo = self.make_repo("oe")
        open(os.path.join(self.fake_dir, "create-badjson"), "w").close()
        proc = self.script(self.STD, cwd=repo)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(parse_block(proc.stdout)["Status"], "created")

    def test_orca_response_without_path_falls_back_to_git(self):
        repo = self.make_repo("of")
        open(os.path.join(self.fake_dir, "create-no-path"), "w").close()
        proc = self.script(self.STD, cwd=repo)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(parse_block(proc.stdout)["Status"], "created")

    def test_orca_malformed_receipts_fall_back_to_git(self):
        """JSON valide de forme inattendue -> warning + fallback Git, exit 0, pas de traceback."""
        cases = [
            "create-json-null",
            "create-json-array",
            "create-json-result-string",
            "create-json-worktree-string",
            "create-ghost-path",
        ]
        for i, case in enumerate(cases):
            repo = self.make_repo(f"oq{i}")
            open(os.path.join(self.fake_dir, case), "w").close()
            proc = self.script(self.STD, cwd=repo)
            os.unlink(os.path.join(self.fake_dir, case))
            self.assertEqual(proc.returncode, 0, proc.stderr)
            block = parse_block(proc.stdout)
            self.assertEqual(block["Status"], "created")
            self.assertNotIn("Chat", block)
            self.assertTrue(os.path.isdir(block["Worktree"]))

    def test_orca_branch_created_then_failure_reuses_it(self):
        """Orca crée la branche puis échoue : la branche est réutilisée, jamais de doublon."""
        repo = self.make_repo("op")
        open(os.path.join(self.fake_dir, "create-then-fail"), "w").close()
        proc = self.script(self.STD, cwd=repo)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        block = parse_block(proc.stdout)
        self.assertEqual(block["Branch"], self.BRANCH)
        self.assertEqual(block["Status"], "branch reused")
        self.assertTrue(os.path.isdir(block["Worktree"]))
        listing = git(["worktree", "list", "--porcelain"], cwd=repo)
        self.assertEqual(listing.count("branch refs/heads/" + self.BRANCH), 1)

    def test_no_orca_flag_skips_orca_entirely(self):
        repo = self.make_repo("og")
        proc = self.script(self.STD + ["--no-orca"], cwd=repo)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(parse_block(proc.stdout)["Status"], "created")
        self.assertEqual(self.fake_args(), [])  # orca jamais appelé

    def test_existing_worktree_reuse_skips_orca(self):
        repo = self.make_repo("oh")
        first = self.script(self.STD + ["--no-orca"], cwd=repo)
        self.assertEqual(first.returncode, 0, first.stderr)
        second = self.script(self.STD, cwd=repo)  # orca actif cette fois
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(parse_block(second.stdout)["Status"], "existing worktree reused")
        self.assertEqual(self.fake_args(), [])  # réutilisation : pas d'appel orca

    def test_local_branch_reuse_skips_orca(self):
        repo = self.make_repo("oi")
        git(["branch", "fix/rm-42"], cwd=repo)
        proc = self.script(["--type", "fix", "--context", "rm-42"], cwd=repo)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(parse_block(proc.stdout)["Status"], "branch reused")
        self.assertEqual(self.fake_args(), [])

    def test_orca_agent_flag_overrides_default(self):
        repo = self.make_repo("oj")
        proc = self.script(self.STD + ["--orca-agent", "opencode2"], cwd=repo)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        [create_line] = [line for line in self.fake_args() if line.startswith("worktree create")]
        self.assertIn("--agent opencode2", create_line)

    def test_orca_agent_env_fallback(self):
        repo = self.make_repo("ok")
        old = os.environ.get("NW_ORCA_AGENT")
        os.environ["NW_ORCA_AGENT"] = "aurora"
        try:
            proc = self.script(self.STD, cwd=repo)
        finally:
            if old is None:
                os.environ.pop("NW_ORCA_AGENT", None)
            else:
                os.environ["NW_ORCA_AGENT"] = old
        self.assertEqual(proc.returncode, 0, proc.stderr)
        [create_line] = [line for line in self.fake_args() if line.startswith("worktree create")]
        self.assertIn("--agent aurora", create_line)

    def test_dry_run_announces_orca_mode(self):
        repo = self.make_repo("ol")
        proc = self.script(self.STD + ["--dry-run"], cwd=repo)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("Orca: actif", proc.stdout)
        self.assertEqual(parse_block(proc.stdout)["Status"], "dry-run")

    def test_dry_run_no_orca_no_announce(self):
        repo = self.make_repo("om")
        proc = self.script(self.STD + ["--dry-run", "--no-orca"], cwd=repo)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertNotIn("Orca:", proc.stdout)

    def test_prompt_ignored_warning_on_git_fallback(self):
        repo = self.make_repo("on")
        open(os.path.join(self.fake_dir, "create-fails"), "w").close()
        proc = self.script(self.STD + ["--prompt", "Brief"], cwd=repo)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("--prompt ignoré", proc.stderr)


if __name__ == "__main__":
    unittest.main()
