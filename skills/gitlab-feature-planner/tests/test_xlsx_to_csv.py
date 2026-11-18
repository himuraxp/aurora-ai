"""Tests du helper xlsx-to-csv.py — fixtures .xlsx fabriquées à la main (stdlib only).

Cas couverts (dont le finding R-01 du review) :
- cellules fusionnées de la colonne Page -> valeur propagée sur toute la plage
- trous de colonnes remplis
- formule (chaîne cachée) et inlineStr
- sélection de feuille par nom ET par index
- mode --all avec collision de noms assainis
- fichier invalide -> message propre, pas de traceback

Run :
    python3 -m unittest discover -s skills/gitlab-feature-planner/tests -v
"""

import os
import subprocess
import sys
import tempfile
import unittest
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
HELPER = os.path.join(HERE, "..", "xlsx-to-csv.py")

M = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


def build_xlsx(path, sheets, sst_xml=None):
    """sheets: [(name, sheet_xml)] — écrit un xlsx minimal lisible par le helper."""
    entries = "".join(
        f'<sheet name="{name}" sheetId="{i}" r:id="rId{i}"/>'
        for i, (name, _) in enumerate(sheets, 1)
    )
    rels = "".join(
        f'<Relationship Id="rId{i}" Target="worksheets/sheet{i}.xml"/>'
        for i in range(1, len(sheets) + 1)
    )
    wb = (f'<?xml version="1.0"?><workbook xmlns="{M}" xmlns:r="{R}">'
          f'<sheets>{entries}</sheets></workbook>')
    rels_xml = (f'<?xml version="1.0"?><Relationships '
                f'xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                f'{rels}</Relationships>')
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("xl/workbook.xml", wb)
        z.writestr("xl/_rels/workbook.xml.rels", rels_xml)
        if sst_xml:
            z.writestr("xl/sharedStrings.xml", sst_xml)
        for i, (_, xml) in enumerate(sheets, 1):
            z.writestr(f"xl/worksheets/sheet{i}.xml", xml)


def run_helper(args, cwd):
    return subprocess.run(
        [sys.executable, HELPER] + args, cwd=cwd, capture_output=True, text=True
    )


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


class TestXlsxToCsv(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def test_merged_page_column_propagated(self):
        """R-01 : la colonne Page fusionnée doit être propagée sur chaque ligne."""
        sst = (f'<?xml version="1.0"?><sst xmlns="{M}">'
               f'<si><t>Page</t></si><si><t>Tache</t></si><si><t>Dashboard</t></si></sst>')
        sheet = (
            f'<?xml version="1.0"?><worksheet xmlns="{M}"><sheetData>'
            f'<row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1" t="s"><v>1</v></c></row>'
            f'<row r="2"><c r="A2" t="s"><v>2</v></c><c r="B2"><v>1</v></c></row>'
            f'<row r="3"><c r="A3" t="s"><v>2</v></c><c r="B3"><v>0.5</v></c></row>'
            f'<row r="4"><c r="B4"><v>2</v></c></row>'
            f'</sheetData>'
            f'<mergeCells count="1"><mergeCell ref="A2:A4"/></mergeCells>'
            f'</worksheet>'
        )
        xlsx = os.path.join(self.tmp, "table.xlsx")
        build_xlsx(xlsx, [("Estimation", sheet)], sst_xml=sst)
        out = os.path.join(self.tmp, "table.csv")
        r = run_helper([xlsx, "-o", out], self.tmp)
        self.assertEqual(r.returncode, 0, r.stderr)
        rows = read(out).splitlines()
        self.assertEqual(rows[1].split(",")[0], "Dashboard")
        self.assertEqual(rows[2].split(",")[0], "Dashboard")
        self.assertEqual(rows[3].split(",")[0], "Dashboard")  # ligne sans cellule A explicite

    def test_column_gap_and_formula_and_inline(self):
        sst = (f'<?xml version="1.0"?><sst xmlns="{M}">'
               f'<si><t>Page</t></si><si><t>Tache</t></si><si><t>Fait</t></si></sst>')
        sheet = (
            f'<?xml version="1.0"?><worksheet xmlns="{M}"><sheetData>'
            f'<row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1" t="s"><v>1</v></c>'
            f'<c r="D1" t="s"><v>2</v></c></row>'  # trou en C1
            f'<row r="2"><c r="A2" t="s"><v>0</v></c><c r="B2" t="str"><v>SUM(A1:A2)</v></c></row>'
            f'<row r="3"><c r="A3" t="inlineStr"><is><t>Univers Podcasts</t></is></c></row>'
            f'</sheetData></worksheet>'
        )
        xlsx = os.path.join(self.tmp, "table.xlsx")
        build_xlsx(xlsx, [("S1", sheet)], sst_xml=sst)
        r = run_helper([xlsx], self.tmp)
        self.assertEqual(r.returncode, 0, r.stderr)
        lines = r.stdout.splitlines()
        self.assertEqual(lines[0], "Page,Tache,,Fait")     # trou rempli
        self.assertEqual(lines[1].split(",")[1], "SUM(A1:A2)")  # chaîne de formule
        self.assertEqual(lines[2].split(",")[0], "Univers Podcasts")  # inlineStr

    def test_sheet_by_name_and_index(self):
        s1 = f'<?xml version="1.0"?><worksheet xmlns="{M}"><sheetData><row r="1"><c r="A1"><v>1</v></c></row></sheetData></worksheet>'
        s2 = f'<?xml version="1.0"?><worksheet xmlns="{M}"><sheetData><row r="1"><c r="A1"><v>2</v></c></row></sheetData></worksheet>'
        xlsx = os.path.join(self.tmp, "table.xlsx")
        build_xlsx(xlsx, [("Estimation Podcast", s1), ("Notes", s2)])
        by_name = run_helper([xlsx, "--sheet", "Estimation Podcast"], self.tmp)
        by_index = run_helper([xlsx, "--sheet", "2"], self.tmp)
        self.assertEqual(by_name.returncode, 0, by_name.stderr)
        self.assertEqual(by_index.returncode, 0, by_index.stderr)
        self.assertEqual(by_name.stdout.strip(), "1")
        self.assertEqual(by_index.stdout.strip(), "2")

    def test_all_mode_name_collision(self):
        """R-06 : deux feuilles aux noms assainis identiques ne s'écrasent pas."""
        s = f'<?xml version="1.0"?><worksheet xmlns="{M}"><sheetData></sheetData></worksheet>'
        xlsx = os.path.join(self.tmp, "table.xlsx")
        build_xlsx(xlsx, [("Budget 2024", s), ("Budget/2024", s), ("Autre", s)])
        r = run_helper([xlsx, "--all"], self.tmp)
        self.assertEqual(r.returncode, 0, r.stderr)
        files = sorted(os.listdir(self.tmp))
        self.assertIn("Budget_2024.csv", files)
        self.assertIn("Budget_2024_2.csv", files)  # collision -> suffixe position
        self.assertIn("Autre.csv", files)

    def test_invalid_file_clean_error(self):
        bad = os.path.join(self.tmp, "bad.xlsx")
        with open(bad, "w", encoding="utf-8") as f:
            f.write("not a zip")
        r = run_helper([bad], self.tmp)
        self.assertNotEqual(r.returncode, 0)
        self.assertTrue(r.stderr.startswith("error:"))
        self.assertNotIn("Traceback", r.stderr)  # message propre, pas de traceback brut


if __name__ == "__main__":
    unittest.main()
