# -*- coding: utf-8 -*-
"""Explore la STRUCTURE d'un CSV du Data Pack (CSV issu d'un PDF : document;page;ligne;nb_cellules;c1..cN,
ou CSV issu d'un Excel : col1..colN). Les nombres sont masques (#) : aucun chiffre statistique n'est ecrit.

Usage :
  python 01_collecte_inspecter_csv_pdf.py fichier.csv                      -> 01_collecte_inspection_csv_<nom>.txt (toutes les pages)
  python 01_collecte_inspecter_csv_pdf.py fichier.csv --chercher salles classe   -> pages dont le texte contient TOUS ces mots
  python 01_collecte_inspecter_csv_pdf.py fichier.csv --pages 249 254      -> detail des pages demandees (numero de la colonne page)
  python 01_collecte_inspecter_csv_pdf.py fichier.csv --pages 263 263 --lignes  -> + toutes les lignes de ces pages, cellule par
                                                                      cellule, nombres masques (#) : montre la mise en page
"""

import csv
import re
import sys
from pathlib import Path
from collections import OrderedDict
import sys as _sys
from pathlib import Path as _P
_sys.path.insert(0, str(_P(__file__).resolve().parents[2] / 'communs'))
import outils_communs as oc
from outils_communs import *

csv.field_size_limit(10 ** 8)


def lire(chemin):
    with open(chemin, encoding="utf-8-sig", newline="") as f:
        lecteur = csv.reader(f, delimiter=";")
        en_tete = next(lecteur)
        lignes = []
        for n, r in enumerate(lecteur, 2):
            lignes.append([nettoyer_ou_noter(v, n, j) for j, v in enumerate(r, 1)])
    return en_tete, lignes


def nettoyer_ou_noter(v, n, j):
    v2, note = nettoyer_cellule(v)
    if note:
        oc.NOTES_IGNOREES.append(("csv", n, j))
    return "" if v2 is None else v2


def masque(v):
    v = str(v).strip()
    if not v:
        return ""
    if to_number(v) is not None and year_of(v) is None:
        return "#"
    return v[:60]


def est_nombre(v):
    return to_number(v) is not None and year_of(v) is None


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return
    chemin = Path(sys.argv[1])
    args = sys.argv[2:]
    en_tete, lignes = lire(chemin)
    pdf = "page" in en_tete and "nb_cellules" in en_tete
    if pdf:
        i_page, i_cell0 = en_tete.index("page"), en_tete.index("nb_cellules") + 1
        i_ligne = en_tete.index("ligne") if "ligne" in en_tete else None
    else:
        i_page, i_cell0, i_ligne = None, 0, None
    pages = OrderedDict()
    for r in lignes:
        p = r[i_page] if (pdf and i_page < len(r)) else "1"
        pages.setdefault(p, []).append(r[i_cell0:])
    out = ["Fichier : %s" % chemin.name, "SHA-256 : %s" % sha256(chemin),
           "Type : %s | colonnes : %s" % ("CSV issu d'un PDF" if pdf else "CSV issu d'un Excel ou natif", ", ".join(en_tete[:8]) + (" ..." if len(en_tete) > 8 else "")),
           "Lignes : %d | pages : %d" % (len(lignes), len(pages)), ""]
    if "--chercher" in args:
        mots = [norm_libre(m) for m in args[args.index("--chercher") + 1:]]
        trouvees = []
        for p, rows in pages.items():
            texte = norm_libre(" ".join(" ".join(c for c in r if not est_nombre(c)) for r in rows))
            if all(m in texte for m in mots):
                trouvees.append(p)
        print("Pages contenant %s : %s" % (mots, ", ".join(trouvees) if trouvees else "aucune"))
        return
    selection = None
    if "--pages" in args:
        a = args[args.index("--pages") + 1:]
        deb, fin = int(a[0]), int(a[1] if len(a) > 1 else a[0])
        selection = {str(k) for k in range(deb, fin + 1)}
    for p, rows in pages.items():
        if selection is not None and p not in selection:
            continue
        titres, donnees, labels = [], 0, []
        for r in rows:
            cells = [c.strip() for c in r if c.strip()]
            if not cells:
                continue
            nb = sum(1 for c in cells if est_nombre(c))
            if nb >= 2:
                donnees += 1
                if len(labels) < (12 if selection else 5):
                    labels.append(cells[0][:35] if not est_nombre(cells[0]) else "#")
            elif nb == 0:
                titres.append(" | ".join(masque(c) for c in cells)[:110])
        sous_totaux = sum(1 for r in rows if r and r[0].strip().lower().startswith("total"))
        out.append("PAGE %s : %d lignes, %d lignes de donnees, %d ligne(s) 'Total...'" % (p, len(rows), donnees, sous_totaux))
        for t in titres[:(40 if selection else 4)]:
            out.append("   texte : " + t)
        if labels:
            out.append("   libelles : " + " ; ".join(labels))
        if selection is not None and "--lignes" in args:
            for n, r in enumerate(rows, 1):
                cells = [masque(c) for c in r]
                while cells and not cells[-1]:
                    cells.pop()
                if cells:
                    out.append("   L%02d [%d] %s" % (n, len([c for c in cells if c]), " | ".join(cells)[:230]))
    if oc.NOTES_IGNOREES:
        out.append("")
        out.append("CELLULES CONTENANT UNE NOTE ADRESSEE A UN ASSISTANT IA : %d (texte ecarte, non execute)" % len(oc.NOTES_IGNOREES))
    nom = "01_collecte_inspection_csv_%s.txt" % re.sub(r"[^A-Za-z0-9_-]", "_", chemin.stem)[:60]
    Path(nom).write_text("\n".join(out), encoding="utf-8")
    print("\n".join(out[:6]))
    print("\n-> Fichier ecrit : %s (structure seulement, nombres masques)" % nom)


if __name__ == "__main__":
    main()
