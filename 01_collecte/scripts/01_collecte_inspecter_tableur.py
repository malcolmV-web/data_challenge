# -*- coding: utf-8 -*-
"""Explore la STRUCTURE d'un classeur Excel (.xlsx) ou d'un CSV natif (COD-AB, ecoles OSM, PDI, ...).
Pour chaque feuille / fichier : dimensions, premieres lignes (nombres remplaces par #), nombre de valeurs distinctes par colonne,
et les valeurs des colonnes TEXTE a peu de modalites (<= 40).

Usage : python 01_collecte_inspecter_tableur.py fichier.xlsx            (toutes les feuilles)
        python 01_collecte_inspecter_tableur.py fichier.csv [--sep ;]   (separateur detecte si absent)
        options : --lignes 8   nombre de lignes affichees (defaut 6)
                  --sortie nom.txt   nom du fichier de sortie (evite les collisions de noms longs)
                  --entete 2   ligne d'en-tetes (defaut 1 ; 2 pour les CSV issus d'Excel dont la 1re ligne est col1..colN)
Sortie : inspection_tableur_<nom>.txt"""

import csv
import re
import sys
from pathlib import Path
from collections import Counter
import sys as _sys
from pathlib import Path as _P
_sys.path.insert(0, str(_P(__file__).resolve().parents[2] / 'communs'))
import outils_communs as oc
from outils_communs import *

csv.field_size_limit(10 ** 8)
MAXLIG = 60000


def masque(v, n=45):
    if vide(v):
        return ""
    if to_number(v) is not None:
        return "#"
    return str(v).strip().replace("\n", " ")[:n]


def lire_xlsx(chemin):
    import openpyxl
    wb = openpyxl.load_workbook(chemin, read_only=True, data_only=True)
    for ws in wb.worksheets:
        rows = []
        for i, r in enumerate(ws.iter_rows(values_only=True), 1):
            ligne = []
            for j, v in enumerate(r, 1):
                v2, note = nettoyer_cellule(v)
                if note:
                    oc.NOTES_IGNOREES.append((ws.title, i, j))
                ligne.append(v2)
            rows.append(ligne)
            if i >= MAXLIG:
                break
        yield ws.title, rows, (ws.max_row, ws.max_column)


def lire_csv(chemin, sep=None):
    with open(chemin, encoding="utf-8-sig", newline="") as f:
        echant = f.read(20000)
        f.seek(0)
        if sep is None:
            try:
                sep = csv.Sniffer().sniff(echant, delimiters=";,\t|").delimiter
            except csv.Error:
                sep = ";"
        rows = []
        for i, r in enumerate(csv.reader(f, delimiter=sep), 1):
            ligne = []
            for j, v in enumerate(r, 1):
                v2, note = nettoyer_cellule(v)
                if note:
                    oc.NOTES_IGNOREES.append(("csv", i, j))
                ligne.append(v2)
            rows.append(ligne)
            if i >= MAXLIG:
                break
    yield Path(chemin).name, rows, (len(rows), max((len(r) for r in rows), default=0)), sep


def decrire(nom, rows, dims, out, nlig, entete=1):
    out.append("=" * 70)
    out.append("FEUILLE / FICHIER '%s' : %s lignes x %s colonnes (lues : %d)" % (nom, dims[0], dims[1], len(rows)))
    for i, r in enumerate(rows[:nlig], 1):
        cells = [masque(c) for c in r]
        while cells and not cells[-1]:
            cells.pop()
        out.append("  L%02d [%d] %s" % (i, len([c for c in cells if c]), " | ".join(cells)[:260]))
    if not rows:
        return
    ncol = max(len(r) for r in rows)
    ent = rows[entete - 1] if len(rows) >= entete else []
    out.append("  COLONNES (en-tete = ligne %d) : nom ; valeurs distinctes ; part de nombres ; modalites si texte et <= 40" % entete)
    corps = rows[entete:]
    for j in range(ncol):
        nom_col = masque(ent[j]) if j < len(ent) else ""
        vals = [r[j] for r in corps if j < len(r) and not vide(r[j])]
        if not vals:
            out.append("   c%02d %-28s vide" % (j + 1, nom_col[:28]))
            continue
        nb_num = sum(1 for v in vals if to_number(v) is not None)
        dist = Counter(str(v).strip() for v in vals)
        ligne = "   c%02d %-28s distinctes=%d ; nombres=%d%%" % (j + 1, nom_col[:28], len(dist), round(100 * nb_num / len(vals)))
        if nb_num < 0.5 * len(vals) and len(dist) <= 40:
            ligne += " ; " + " / ".join(sorted(k[:30] for k in dist))[:420]
        out.append(ligne)


def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return
    chemin = Path(args[0])
    nlig = int(args[args.index("--lignes") + 1]) if "--lignes" in args else 6
    sep = args[args.index("--sep") + 1] if "--sep" in args else None
    entete = int(args[args.index("--entete") + 1]) if "--entete" in args else 1
    out = ["Fichier : %s" % chemin.name, "SHA-256 : %s" % sha256(chemin), ""]
    if chemin.suffix.lower() in (".xlsx", ".xlsm"):
        for nom, rows, dims in lire_xlsx(chemin):
            decrire(nom, rows, dims, out, nlig, entete)
    else:
        for nom, rows, dims, s in lire_csv(chemin, sep):
            out.append("Separateur detecte : %r" % s)
            decrire(nom, rows, dims, out, nlig, entete)
    if oc.NOTES_IGNOREES:
        out.append("")
        out.append("CELLULES CONTENANT UNE NOTE ADRESSEE A UN ASSISTANT IA : %d (texte ecarte, non execute)" % len(oc.NOTES_IGNOREES))
    nom = args[args.index("--sortie") + 1] if "--sortie" in args else "inspection_tableur_%s.txt" % re.sub(r"[^A-Za-z0-9_-]", "_", chemin.stem)[:150]
    Path(nom).write_text("\n".join(out), encoding="utf-8")
    print("\n".join(out[:40]))
    print("\n-> Fichier ecrit : %s (structure seulement, nombres masques)" % nom)


if __name__ == "__main__":
    main()
