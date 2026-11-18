"""Contrat structurel du SKILL.md de gitlab-feature-planner.

Chaque assertion relie une exigence de brief (v1 + ajustement « regroupements MR »)
à un comportement observable du document. Les cas comportementaux du brief
(petites tâches liées -> groupe ; indépendantes -> pas de groupe arbitraire ;
tâche grosse -> seule ; idempotence) sont garantis par les règles qu'ils
nécessitent : critères de regroupement/éviction, priorité, heuristique 2-4,
invariant déterministe.

Run :
    python3 -m unittest discover -s skills/gitlab-feature-planner/tests -v
"""

import os
import re
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.join(HERE, "..", "SKILL.md")


class TestSkillContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(SKILL, encoding="utf-8") as f:
            cls.text = f.read()

    def frontmatter(self):
        m = re.match(r"^---\n(.*?)\n---\n", self.text, re.S)
        if m is None:
            self.fail("frontmatter manquant")
        return m.group(1)

    # ── Frontmatter ──────────────────────────────────────────────────────────

    def test_name(self):
        self.assertIn("name: gitlab-feature-planner", self.frontmatter())

    def test_yaml_safe_description(self):
        for line in self.frontmatter().splitlines():
            m = re.match(r"^(name|description):\s*(.*)$", line)
            if m is None:
                self.fail(f"ligne frontmatter inattendue : {line}")
            self.assertNotIn(": ", m.group(2), "colon-espace dans un scalaire YAML simple")

    def test_triggers_are_generic(self):
        """R-02 : pas de trigger lié à un projet privé."""
        self.assertNotIn("podcast", self.frontmatter().lower())

    # ── Philosophie / granularité ────────────────────────────────────────────

    def test_granularity_rule(self):
        self.assertIn(
            "1 issue GitLab = une page ou un bloc fonctionnel cohérent",
            self.text,
        )

    def test_three_level_model(self):
        self.assertIn("MR group  = unité cohérente d'implémentation/review (suggestion)", self.text)
        self.assertIn("Task      = unité de travail issue du backlog (ligne du tableau)", self.text)

    def test_issue_mr_relation(self):
        self.assertIn("MR        = lot cohérent d'une ou plusieurs tâches", self.text)

    def test_no_one_task_one_mr(self):
        """La relation 1 tâche = 1 MR ne doit exister que niée."""
        self.assertIn("Ne jamais modéliser « 1 tâche = 1 MR »", self.text)

    # ── Règles dures / pipeline ──────────────────────────────────────────────

    def test_human_stop(self):
        self.assertIn("ne rien créer", self.text)
        self.assertIn("STOP obligatoire", self.text)

    def test_only_issues_created(self):
        self.assertIn("Ne jamais créer de MR", self.text)
        self.assertIn("jamais créées automatiquement", self.text)

    def test_traceability_and_unmatched(self):
        self.assertIn("unmatched_rows", self.text)
        self.assertIn("ne compte PAS comme unmatched", self.text)

    def test_closed_type_enum(self):
        """R-04 : énumération fermée incluant feature."""
        self.assertIn("page | feature | component | infra", self.text)

    def test_merged_cells_handled(self):
        """R-01 : expansion des fusions + forward-fill CSV."""
        self.assertIn("expanse les cellules fusionnées", self.text)
        self.assertIn("forward-fill", self.text)

    def test_existing_issues_checked(self):
        """R-03 : vérification des issues existantes avant création."""
        self.assertIn('glab issue list --search "<feature>"', self.text)
        self.assertIn("ne jamais recréer une issue existante", self.text)

    def test_draft_body_precedence(self):
        """R-09 : le corps du draft prime sur le format gitlab-issues."""
        self.assertIn("Le **corps du draft prime**", self.text)
        self.assertIn("ne pas lui emprunter son format de description", self.text)

    # ── Regroupement MR ──────────────────────────────────────────────────────

    def test_mr_grouping_step_exists(self):
        self.assertIn("Step 4 — Suggestions de regroupement MR", self.text)

    def test_grouping_priority(self):
        for criterion in [
            "cohérence fonctionnelle",
            "dépendances",
            "proximité technique",
            "taille raisonnable de MR",
            "nombre de tâches",
        ]:
            self.assertIn(criterion, self.text, f"critère manquant : {criterion}")

    def test_grouping_criteria_and_eviction(self):
        for must in ["tâches petites", "même composant", "difficile à reviewer"]:
            self.assertIn(must, self.text)
        self.assertIn("2 à 4 petites tâches", self.text)  # heuristique de taille
        self.assertIn("peut rester seule dans sa MR", self.text)  # grosse tâche -> seule

    def test_mr_section_optional_and_plain_bullets(self):
        self.assertIn("## Suggestion de découpage des MR", self.text)
        self.assertIn("facultative", self.text)  # règle KISS d'omission
        self.assertIn("pas de cases à cocher", self.text)

    def test_issuespec_mr_fields(self):
        for field in ['"mrGroups"', '"taskIds"', '"reasoning"', '"tasks"', '"id"']:
            self.assertIn(field, self.text, f"champ IssueSpec manquant : {field}")

    def test_deterministic_grouping(self):
        self.assertIn("déterministe", self.text)

    # ── Format maison ────────────────────────────────────────────────────────

    def test_helper_referenced(self):
        self.assertIn("xlsx-to-csv.py", self.text)

    def test_pipeline_diagram_matches_steps(self):
        """Le diagramme numérote jusqu'à (9) comme les sections Step 1–9."""
        self.assertIn("(9) création des issues (seulement)", self.text)
        for n in range(1, 10):
            self.assertIn(f"({n})", self.text)

    def test_code_fences_balanced(self):
        self.assertEqual(self.text.count("```") % 2, 0, "clôtures de code déséquilibrées")


if __name__ == "__main__":
    unittest.main()
