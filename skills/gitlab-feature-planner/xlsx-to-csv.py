#!/usr/bin/env python3
"""Convert a sheet of an .xlsx file to CSV — Python stdlib only.

Usage:
    xlsx-to-csv.py <file.xlsx> [-o out.csv] [--sheet SHEET]
    xlsx-to-csv.py <file.xlsx> --all

--sheet accepts a 1-based index (default 1) or a sheet name.
--all dumps every sheet as <sanitized-name>.csv into the current directory;
cannot be combined with -o. On sanitized-name collision, the sheet position
is appended (Budget_2024.csv, then Budget_2024_2.csv).
Merged cells are expanded: the top-left value of a merged range is
propagated to every cell of the range (estimation tables typically merge
the Page column across rows).

Limitations: legacy .xls / .xlsb are not supported (export as CSV or
re-save as .xlsx); dates/styles are emitted as raw stored values. Fails
loudly with clean messages rather than guessing.
"""

from __future__ import annotations  # annotations lazy: compatible Python 3.9 (X | Y en annotation)

import argparse
import csv
import re
import sys
import zipfile
import xml.etree.ElementTree as ET

NS_MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
NS_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
M = f"{{{NS_MAIN}}}"


def col_index(ref: str) -> int:
    """'BC12' -> column index (0-based) of BC."""
    m = re.match(r"([A-Z]+)", ref or "")
    if not m:
        return -1
    n = 0
    for ch in m.group(1):
        n = n * 26 + (ord(ch) - 64)
    return n - 1


def cell_ref(ref: str):
    """'BC12' -> (row0, col0) or None."""
    m = re.match(r"([A-Z]+)(\d+)$", ref or "")
    if not m:
        return None
    row = int(m.group(2)) - 1
    col = 0
    for ch in m.group(1):
        col = col * 26 + (ord(ch) - 64)
    return row, col - 1


def cell_at(rows, r, c):
    return rows[r][c] if 0 <= r < len(rows) and 0 <= c < len(rows[r]) else ""


def cell_set(rows, r, c, val):
    while len(rows) <= r:
        rows.append([])
    row = rows[r]
    while len(row) <= c:
        row.append("")
    row[c] = val


def load_sheets(z: zipfile.ZipFile):
    """Return ordered [(name, rid)] from workbook.xml."""
    wb = ET.fromstring(z.read("xl/workbook.xml"))
    return [(s.get("name", f"Sheet{i+1}"), s.get(f"{{{NS_REL}}}id"))
            for i, s in enumerate(wb.findall(f"{M}sheets/{M}sheet"))]


def load_rels(z: zipfile.ZipFile):
    try:
        rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
    except KeyError:
        return {}
    return {r.get("Id"): r.get("Target") for r in rels}


def resolve_target(target: str | None, position: int) -> str:
    if target:
        t = target.lstrip("/")
        if not t.startswith("xl/"):
            t = "xl/" + t
        return t
    return f"xl/worksheets/sheet{position}.xml"


def read_shared_strings(z: zipfile.ZipFile):
    if "xl/sharedStrings.xml" not in z.namelist():
        return []
    sst = ET.fromstring(z.read("xl/sharedStrings.xml"))
    return ["".join(t.text or "" for t in si.iter(f"{M}t"))
            for si in sst.findall(f"{M}si")]


def parse_cells(root, shared):
    """Rows of raw cell values (unpadded, gaps possible)."""
    rows = []
    for row in root.iter(f"{M}row"):
        cells = {}
        for c in row.findall(f"{M}c"):
            ref, t = c.get("r", ""), c.get("t", "n")
            idx = col_index(ref)
            if idx < 0:
                idx = len(cells)
            v = c.find(f"{M}v")
            if t == "s":
                val = shared[int(v.text)] if v is not None and v.text else ""
            elif t == "inlineStr":
                is_el = c.find(f"{M}is")
                val = "".join(t2.text or "" for t2 in is_el.iter(f"{M}t")) if is_el is not None else ""
            elif t == "b":
                val = "TRUE" if (v is not None and v.text == "1") else "FALSE"
            else:  # n (number) or str (cached formula string)
                val = (v.text or "") if v is not None else ""
            cells[idx] = val
        width = max(cells) + 1 if cells else 0
        rows.append([cells.get(i, "") for i in range(width)])
    return rows


def apply_merged_cells(root, rows):
    """Propagate the top-left value of every merged range (in-place)."""
    mc = root.find(f"{M}mergeCells")
    if mc is None:
        return rows
    for el in mc.findall(f"{M}mergeCell"):
        parts = (el.get("ref") or "").split(":")
        if len(parts) != 2:
            continue
        a, b = cell_ref(parts[0]), cell_ref(parts[1])
        if a is None or b is None:
            continue
        (r1, c1), (r2, c2) = a, b
        if r1 > r2:
            r1, r2 = r2, r1
        if c1 > c2:
            c1, c2 = c2, c1
        val = cell_at(rows, r1, c1)
        for r in range(r1, r2 + 1):
            for c in range(c1, c2 + 1):
                cell_set(rows, r, c, val)
    return rows


def parse_sheet(z: zipfile.ZipFile, target: str, shared: list):
    root = ET.fromstring(z.read(target))
    rows = apply_merged_cells(root, parse_cells(root, shared))
    if rows:
        w = max(len(r) for r in rows)
        rows = [r + [""] * (w - len(r)) for r in rows]
    return rows


def write_csv(rows, out_path: str):
    out = sys.stdout if out_path == "-" else open(out_path, "w", newline="", encoding="utf-8")
    csv.writer(out).writerows(rows)
    if out is not sys.stdout:
        out.close()


def sanitize_name(name: str, position: int, used: set) -> str:
    safe = re.sub(r"[^\w.-]+", "_", name) or f"sheet{position}"
    if safe in used:
        safe = f"{safe}_{position}"
    used.add(safe)
    return safe


def main():
    ap = argparse.ArgumentParser(description="xlsx sheet -> CSV (stdlib only)")
    ap.add_argument("xlsx")
    ap.add_argument("-o", "--out", default="-", help="output CSV path (default stdout)")
    ap.add_argument("--sheet", default="1", help="1-based index or sheet name (default 1)")
    ap.add_argument("--all", action="store_true", help="dump every sheet as <name>.csv in cwd")
    args = ap.parse_args()

    try:
        with zipfile.ZipFile(args.xlsx) as z:
            sheets = load_sheets(z)
            rels = load_rels(z)
            shared = read_shared_strings(z)

            if args.all:
                if args.out != "-":
                    sys.exit("error: --all cannot be combined with -o (it writes <name>.csv in cwd)")
                used = set()
                for i, (name, rid) in enumerate(sheets, 1):
                    target = resolve_target(rels.get(rid), i)
                    safe = sanitize_name(name, i, used)
                    write_csv(parse_sheet(z, target, shared), f"{safe}.csv")
                    print(f"{safe}.csv", file=sys.stderr)
                return

            # pick sheet by 1-based index or name
            sel = args.sheet
            position = None
            if sel.isdigit():
                pos = int(sel)
                if pos < 1 or pos > len(sheets):
                    sys.exit(f"error: sheet {pos} out of range (1..{len(sheets)})")
                position = pos
            else:
                for i, (name, _) in enumerate(sheets, 1):
                    if name.strip().lower() == sel.strip().lower():
                        position = i
                        break
                if position is None:
                    names = ", ".join(n for n, _ in sheets)
                    sys.exit(f"error: sheet '{sel}' not found. Available: {names}")

            name, rid = sheets[position - 1]
            target = resolve_target(rels.get(rid), position)
            write_csv(parse_sheet(z, target, shared), args.out)
            if args.out != "-":
                print(f"written: {args.out} (sheet {position}: {name})", file=sys.stderr)
    except zipfile.BadZipFile:
        sys.exit(f"error: '{args.xlsx}' is not a valid .xlsx (zip) file — export it as CSV instead")
    except KeyError as e:
        sys.exit(f"error: missing part in xlsx archive: {e}")
    except ET.ParseError as e:
        sys.exit(f"error: cannot parse xlsx XML: {e} — the file may be corrupt; export it as CSV instead")
    except (IndexError, ValueError) as e:
        sys.exit(f"error: unexpected cell content: {e}")
    except OSError as e:
        sys.exit(f"error: filesystem: {e}")


if __name__ == "__main__":
    main()
