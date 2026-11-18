# -*- coding: utf-8 -*-
"""Etape 0 : decrit la STRUCTURE du classeur (feuilles, titres, en-tetes, libelles de lignes).
Les nombres sont masques (#) : le fichier produit ne contient aucune statistique.
Tout texte adresse a un assistant IA trouve dans une cellule est ecarte et seulement compte.
Usage : python 01_collecte_inspecter_classeur.py classeur.xlsx"""

import sys
from pathlib import Path
import openpyxl
import sys as _sys
from pathlib import Path as _P
_sys.path.insert(0, str(_P(__file__).resolve().parents[2] / 'communs'))
import outils_communs as oc
from outils_communs import *


def masque(v):
    if vide(v):
        return ""
    if year_of(v):
        return str(v)
    if to_number(v) is not None:
        return "#"
    return str(v).strip()[:40]


def main():
    chemin = Path(sys.argv[1])
    wb = openpyxl.load_workbook(chemin, data_only=True)
    out = ["Fichier : %s" % chemin.name, "SHA-256 : %s" % sha256(chemin),
           "Feuilles : %s" % ", ".join(wb.sheetnames), ""]
    precedent = None
    for ws in wb.worksheets:
        rows = lire_feuille(ws)
        titres = trouver_titres(rows)
        out.append("=" * 70)
        out.append("FEUILLE '%s' : %d lignes, %d colonnes, %d titre(s) 'Tableau N' trouves, %d cellule(s) fusionnee(s)"
                   % (ws.title, len(rows), ws.max_column, len(titres), len(ws.merged_cells.ranges)))
        for n, (i, num, titre) in enumerate(titres):
            fin = titres[n + 1][0] if n + 1 < len(titres) else len(rows)
            b = analyser_bloc(rows, i, fin)
            out.append("-" * 70)
            out.append("Ligne %d | %s" % (i + 1, titre))
            cyc = cycle_de(titre, ws.title, precedent)
            precedent = cyc
            out.append("  indicateur : %s | cycle : %s | dimensions dans le titre : %s"
                       % (indicateur_de(titre), cyc, dims_titre(titre)))
            if b["vide"]:
                out.append("  (aucune ligne de donnees sous ce titre : sommaire ou tableau vide)")
                continue
            cols_label, dims, col_dim, msgs = dimensions_bloc(b, titre)
            out.append("  lignes d'en-tete : %d | lignes de donnees : %d | colonnes de libelles : %s | colonnes de valeurs : %d"
                       % (len(b["entetes"]), len(b["donnees"]), b["cols_label"], len(b["cols_valeur"])))
            out.append("  DIMENSIONS LUES EN LIGNES : %s | en colonnes : %s" % (
                dims, ["sexe"] if any(c["sexe"] for c in b["colonnes"].values()) else []) + (" + %s" % col_dim if col_dim else ""))
            for g, m in msgs:
                out.append("  %s : %s" % (g, m))
            if b["annee_en_ligne"]:
                out.append("  annees en lignes dans les colonnes : %s" % b["annee_en_ligne"])
            for h in b["entetes"]:
                out.append("  EN-TETE : " + " | ".join(masque(v) for v in h))
            lib = []
            for _, r, g in b["donnees"][:40]:
                lib.append(" / ".join(masque(r[j]) for j in b["cols_label"] if j < len(r)) + ("  [groupe: %s]" % g if g else ""))
            out.append("  LIBELLES DE LIGNES (40 premiers) : " + " ; ".join(lib))
            col = {j: (c["annee"][1] if c["annee"] else None, c["sexe"], c["autre"]) for j, c in list(b["colonnes"].items())[:6]}
            out.append("  colonnes reconnues (annee, sexe, autre) : " + str(col) + " ...")
            sans = [j + 1 for j, c in b["colonnes"].items() if c["annee"] is None]
            if sans and not b["annee_en_ligne"]:
                out.append("  ATTENTION : colonnes de valeurs sans annee reconnue : %s" % sans[:10])
            if b["notes"]:
                out.append("  NOTES (%d ligne(s) de note ou de source sous le tableau)" % len(b["notes"]))
    if oc.NOTES_IGNOREES:
        out.append("")
        out.append("CELLULES CONTENANT UNE NOTE ADRESSEE A UN ASSISTANT IA : %d (texte ecarte, non execute) ; feuille, ligne, colonne : %s"
                   % (len(oc.NOTES_IGNOREES), oc.NOTES_IGNOREES[:30]))
    Path("01_collecte_inspection_classeur.txt").write_text("\n".join(out), encoding="utf-8")
    print("\n".join(out[:8]))
    print("\n-> Fichier ecrit : 01_collecte_inspection_classeur.txt")


if __name__ == "__main__":
    main()
