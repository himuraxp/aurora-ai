"""Tests des primitives ajoutées au skill : registry, resolver, transformations du sync.

Lancement : python3 -m unittest discover -s skills/gitlab-feature-planner/tests
Stdlib uniquement.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from resolve_project import AmbiguousProject, ProjectNotFound, load_registry, resolve  # noqa: E402
from sync_issues import (  # noqa: E402
    ensure_marker,
    enrich_dependencies,
    detect_wrong_project,
    insert_criteria,
    normalize_criteria_bullets,
    parse_dep_iids,
    split_sections,
    strip_empty_sections,
    transform,
)

# ---------------------------------------------------------------------- fixtures
REGISTRY = {
    "version": 1,
    "projects": [
        {"alias": "example-project", "displayName": "Example Project", "gitlabPath": "acme-group/example-project", "projectId": 2001, "validated": True, "role": ""},
        {"alias": "admin-app", "displayName": "Admin App", "gitlabPath": "acme-group/admin-app", "projectId": 2002, "validated": True, "role": ""},
        {"alias": "manager-element", "displayName": "Manager Element (design system)", "gitlabPath": "acme-group/front/design-system", "projectId": 2003, "validated": True, "role": ""},
        {"alias": "manager-page", "displayName": "Manager Page", "gitlabPath": "acme-group/front/page-builder", "projectId": 2004, "validated": True, "role": ""},
    ],
}

SAMPLE = """## Objectif
Page listant les épisodes d'un podcast.

## Checklist
- [ ] Composant — Filtre par diffusion — 0.25 j
- [ ] Composant — Tableau de listing — 0.5 j

**Total estimé : 0.75 j**

## Maquettes
- [Maquette](https://figma.com/file/x?node-id=1-1)

## Dépendances
- #6

## Notes
- Note utile à conserver.
"""

TECH_ISSUE = """## Objectif
Issue technique sans maquette.

## Checklist
- [x] Tâche — 1 j

**Total estimé : 1 j**

## Maquettes

- Pas de maquette spécifique (issue technique)

## Dépendances
- Aucune

## Notes
"""


class TestProjectResolution(unittest.TestCase):
    def test_alias_connu(self):
        self.assertEqual(resolve("example-project", REGISTRY)["projectId"], 2001)

    def test_project_path_connu(self):
        self.assertEqual(resolve("acme-group/admin-app", REGISTRY)["projectId"], 2002)

    def test_project_id_connu(self):
        self.assertEqual(resolve("2003", REGISTRY)["alias"], "manager-element")

    def test_display_name(self):
        self.assertEqual(resolve("Admin App", REGISTRY)["alias"], "admin-app")

    def test_recherche_partielle_unique(self):
        self.assertEqual(resolve("admin-app", REGISTRY)["alias"], "admin-app")

    def test_plusieurs_resultats_ambigus(self):
        with self.assertRaises(AmbiguousProject):
            resolve("manager", REGISTRY)

    def test_aucun_resultat(self):
        with self.assertRaises(ProjectNotFound):
            resolve("unknown-repo", REGISTRY)

    def test_mapping_memorise(self):
        import copy
        reg = copy.deepcopy(REGISTRY)
        reg["projects"].append({"alias": "podcast-suite", "displayName": "Podcast Suite", "gitlabPath": "acme-group/media/player-suite", "projectId": 9999, "validated": True, "role": ""})
        self.assertEqual(resolve("podcast-suite", reg)["projectId"], 9999)

    def test_registry_reel_charge(self):
        reg = load_registry()
        self.assertGreaterEqual(len(reg["projects"]), 4)


class TestTransformations(unittest.TestCase):
    def test_marqueur_ajoute_puis_idempotent(self):
        once = ensure_marker(SAMPLE, "podcast", "listing-episodes")
        twice = ensure_marker(once, "podcast", "listing-episodes")
        self.assertTrue(once.startswith("<!-- aurora:planner podcast/listing-episodes -->"))
        self.assertEqual(once, twice)

    def test_marqueur_duplique_impossible(self):
        once = ensure_marker(SAMPLE, "podcast", "dashboard")
        other = ensure_marker(ensure_marker(once, "podcast", "dashboard"), "podcast", "dashboard")
        self.assertEqual(once.count("aurora:planner"), 1)
        self.assertEqual(other, once)

    def test_criteres_inseres_apres_checklist(self):
        out = insert_criteria(SAMPLE, ["Le listing correspond à la maquette.", "La recherche fonctionne."])
        self.assertIn("**Total estimé : 0.75 j**\n\n## Critères d'acceptation\n- Le listing", out)

    def test_criteres_sans_checkbox(self):
        """Les critères d'acceptation = Definition of Done : bullets, jamais de checkbox
        (sinon ils faussent la progression GitLab de l'issue)."""
        out = insert_criteria(SAMPLE, ["Le filtre fonctionne.", "La recherche fonctionne."])
        self.assertIn("- Le filtre fonctionne.", out)
        self.assertIn("- La recherche fonctionne.", out)
        self.assertNotIn("- [ ] Le filtre fonctionne.", out)

    def test_criteres_remplaces_idempotent(self):
        once = insert_criteria(SAMPLE, ["Critère A"])
        twice = insert_criteria(once, ["Critère A"])
        self.assertEqual(once, twice)
        replaced = insert_criteria(once, ["Critère B"])
        self.assertIn("Critère B", replaced)
        self.assertNotIn("Critère A", replaced)

    def test_criteres_absents_de_l_issue_technique_sans_checklist_post_total(self):
        out = insert_criteria(TECH_ISSUE, ["Critère X"])
        self.assertIn("## Critères d'acceptation\n- Critère X", out)

    def test_sections_vides_supprimees(self):
        out = strip_empty_sections(TECH_ISSUE)
        self.assertNotIn("## Maquettes", out)
        self.assertNotIn("Pas de maquette spécifique", out)
        self.assertNotIn("## Dépendances", out)
        self.assertNotIn("## Notes", out)
        self.assertIn("## Objectif", out)  # les sections utiles restent

    def test_sections_avec_contenu_conservees(self):
        out = strip_empty_sections(SAMPLE)
        self.assertIn("## Maquettes", out)
        self.assertIn("## Notes", out)
        self.assertIn("Note utile à conserver", out)

    def test_dependance_enrichie_avec_titre(self):
        out = enrich_dependencies(SAMPLE, {"6": "[Podcast] Composants partagés du manager"})
        self.assertIn("- #6 — [Podcast] Composants partagés du manager", out)

    def test_dependance_enrichie_idempotent(self):
        once = enrich_dependencies(SAMPLE, {"6": "[Podcast] Composants partagés du manager"})
        twice = enrich_dependencies(once, {"6": "[Podcast] Composants partagés du manager"})
        self.assertEqual(once.count("[Podcast] Composants partagés du manager"), 1)
        self.assertEqual(once, twice)

    def test_total_estime_et_mr_suggestions_preserves(self):
        full = """## Objectif
X.

## Checklist
- [ ] A — 1 j

**Total estimé : 1 j**

## Suggestion de découpage des MR

### MR — Lot
- A

## Dépendances
- #6
"""
        out = strip_empty_sections(full)
        self.assertIn("**Total estimé : 1 j**", out)
        self.assertIn("## Suggestion de découpage des MR", out)

    def test_parse_deps(self):
        self.assertEqual(parse_dep_iids(SAMPLE), [6])
        self.assertEqual(parse_dep_iids(TECH_ISSUE), [])

    def test_transform_complet_idempotent(self):
        once = transform(SAMPLE, "podcast", "listing-episodes", ["Critère 1"], {"6": "[Podcast] Composants"})
        twice = transform(once, "podcast", "listing-episodes", ["Critère 1"], {"6": "[Podcast] Composants"})
        self.assertEqual(once, twice)
        self.assertIn("aurora:planner podcast/listing-episodes", once)
        self.assertIn("## Critères d'acceptation", once)
        self.assertIn("- #6 — [Podcast] Composants", once)

    def test_split_sections_forme(self):
        prelude, sections = split_sections(SAMPLE)
        self.assertEqual(prelude, [])
        titles = [h[3:].strip() for h, _ in sections]
        self.assertEqual(titles, ["Objectif", "Checklist", "Maquettes", "Dépendances", "Notes"])


class TestSyncSafety(unittest.TestCase):
    def test_wrong_project_detecte(self):
        self.assertTrue(detect_wrong_project("acme-group/example-project", "acme-group/admin-app"))
        self.assertFalse(detect_wrong_project("acme-group/example-project", "acme-group/example-project"))

    def test_update_si_diff_uniquement(self):
        criteria = ["Critère 1"]
        base = transform(SAMPLE, "podcast", "listing-episodes", criteria, {})
        synced = transform(base, "podcast", "listing-episodes", criteria, {})
        self.assertEqual(base, synced)  # un 2e run ne détecte aucun diff -> unchanged


class TestCriteriaProgression(unittest.TestCase):
    """Convention : Checklist = progression GitLab (checkboxes) ; Critères = DoD (bullets)."""

    SIX_TASKS_SIX_CRITERIA = """## Objectif
Page listant les épisodes d'un podcast.

## Checklist
- [ ] Composant — Filtre par diffusion — 0.25 j
- [ ] Composant — Input de recherche — 0.25 j
- [ ] Composant — Tableau de listing — 0.5 j
- [ ] Composant — Actions — 0.125 j
- [ ] Modale — Suppression — 0.25 j
- [ ] Architecture — Aperçu overlay — 0.5 j

**Total estimé : 1.875 j**

## Critères d'acceptation
- [ ] Le listing correspond à la maquette Figma.
- [ ] Les filtres fonctionnent ensemble.
- [ ] Le filtre propose les états attendus.
- [ ] Les actions correspondent à l'état.
- [ ] La suppression passe par la modale.
- [ ] L'aperçu s'affiche dans l'overlay.
"""

    def test_migration_ciblée_convertit_uniquement_les_critères(self):
        out = normalize_criteria_bullets(self.SIX_TASKS_SIX_CRITERIA)
        self.assertIn("- Le listing correspond à la maquette Figma.", out)
        self.assertNotIn("- [ ] Le listing", out)
        # la Checklist des tâches reste inchangée (progression GitLab)
        self.assertIn("- [ ] Composant — Filtre par diffusion — 0.25 j", out)
        self.assertEqual(len(__import__("re").findall(r"^-\s+\[[xX ]\]", out, __import__("re").M)), 6)

    def test_taches_terminees_preservees(self):
        desc = self.SIX_TASKS_SIX_CRITERIA.replace(
            "- [ ] Composant — Filtre par diffusion — 0.25 j", "- [x] Composant — Filtre par diffusion — 0.25 j"
        ).replace("- [ ] Les filtres fonctionnent ensemble.", "- [x] Les filtres fonctionnent ensemble.")
        out = normalize_criteria_bullets(desc)
        self.assertIn("- [x] Composant — Filtre par diffusion — 0.25 j", out)  # tâche faite : intouchée
        self.assertIn("- Les filtres fonctionnent ensemble.", out)  # critère converti même en [x]

    def test_progression_exclusivement_les_taches(self):
        """6 tasks + 6 critères -> exactement 6 checkboxes Markdown dans l'issue."""
        out = transform(self.SIX_TASKS_SIX_CRITERIA, "podcast", "listing-episodes", ["C1", "C2", "C3", "C4", "C5", "C6"], {})
        checkboxes = len(__import__("re").findall(r"^-\s+\[[xX ]\]", out, __import__("re").M))
        self.assertEqual(checkboxes, 6)

    def test_migration_idempotente(self):
        once = normalize_criteria_bullets(self.SIX_TASKS_SIX_CRITERIA)
        twice = normalize_criteria_bullets(once)
        self.assertEqual(once, twice)  # 2e exécution : aucune modification -> unchanged
        self.assertNotIn("- [ ] Le listing", twice)
        self.assertIn("- Le listing", twice)
        # transform avec les mêmes critères : idempotent également
        t_once = transform(self.SIX_TASKS_SIX_CRITERIA, "podcast", "listing-episodes",
                           ["Le listing correspond à la maquette Figma."], {})
        t_twice = transform(t_once, "podcast", "listing-episodes",
                            ["Le listing correspond à la maquette Figma."], {})
        self.assertEqual(t_once, t_twice)


if __name__ == "__main__":
    unittest.main()
