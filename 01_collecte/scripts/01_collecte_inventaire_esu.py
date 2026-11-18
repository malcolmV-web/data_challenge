# -*- coding: utf-8 -*-
"""Inventaire des rapports mensuels ESU (education en situation d'urgence) : pour chaque CSV du dossier, nombre de lignes et de pages,
presence de la colonne 'methode' (= lecture par OCR a verifier), date de situation lue dans le texte, titres de tableaux.

Usage : python 01_collecte_inventaire_esu.py "<.../ESU_Rapports_mensuels>"  [--titres 10] [--motif 2026]
        --motif texte : ne traite que les fichiers dont le nom contient ce texte (insensible a la casse)
Sortie : 01_collecte_inventaire_esu.txt"""

import csv
import re
import sys
from pathlib import Path
import sys as _sys
from pathlib import Path as _P
_sys.path.insert(0, str(_P(__file__).resolve().parents[2] / 'communs'))
import outils_communs as oc
from outils_communs import *

csv.field_size_limit(10 ** 8)
MOIS = "janvier|f[ée]vrier|mars|avril|mai|juin|juillet|ao[uû]t|septembre|octobre|novembre|d[ée]cembre"


def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return
    dossier = Path(args[0])
    nt = int(args[args.index("--titres") + 1]) if "--titres" in args else 10
    motif = args[args.index("--motif") + 1].lower() if "--motif" in args else None
    out = []
    for f in sorted(dossier.glob("*.csv"), key=lambda p: p.name.lower()):
        if motif and motif not in f.name.lower():
            continue
        with open(f, encoding="utf-8-sig", newline="") as fh:
            lecteur = csv.reader(fh, delimiter=";")
            try:
                en_tete = next(lecteur)
            except StopIteration:
                continue
            ocr = "methode" in en_tete
            i_page = en_tete.index("page") if "page" in en_tete else None
            i0 = (en_tete.index("nb_cellules") + 1) if "nb_cellules" in en_tete else 0
            n, pages, titres, dates = 0, set(), [], []
            for r in lecteur:
                n += 1
                if i_page is not None and i_page < len(r) and r[i_page].strip():
                    pages.add(r[i_page].strip())
                cells = []
                for v in r[i0:]:
                    v2, note = nettoyer_cellule(v)
                    if note:
                        oc.NOTES_IGNOREES.append((f.name, n, 0))
                    if v2 and str(v2).strip():
                        cells.append(str(v2).strip())
                texte = " | ".join(c for c in cells if to_number(c) is None)
                if not texte:
                    continue
                if re.search(r"\btableau\s*n?[°o]?\s*\d+", texte, re.I) and len(texte) > 15:
                    t = re.sub(r"\s+", " ", texte)[:150]
                    if t not in [x[1] for x in titres]:
                        titres.append((r[i_page] if i_page is not None else "?", t))
                m = re.search(r"(situation[^|]{0,40}|au|du)\s+(\d{1,2}\s+)?(%s)\s+(20\d\d)" % MOIS, texte, re.I)
                if m and len(dates) < 3:
                    dates.append(re.sub(r"\s+", " ", m.group(0))[:60])
        out.append("=" * 70)
        out.append("%s : %d lignes, %d pages, colonnes numeriques max %d ; METHODE (OCR a verifier) : %s" % (
            f.name, n, len(pages), len([c for c in en_tete if re.fullmatch(r"c\d+", c)]), "OUI" if ocr else "non"))
        out.append("   dates lues : %s" % (dates or "aucune"))
        for p, t in titres[:nt]:
            out.append("   p.%s : %s" % (p, t))
        if not titres:
            out.append("   (aucun titre 'Tableau N' reconnu)")
    if oc.NOTES_IGNOREES:
        out.append("")
        out.append("CELLULES CONTENANT UNE NOTE ADRESSEE A UN ASSISTANT IA : %d (texte ecarte, non execute)" % len(oc.NOTES_IGNOREES))
    Path("01_collecte_inventaire_esu.txt").write_text("\n".join(out), encoding="utf-8")
    print("\n".join(out[:60]))
    print("\n-> Fichier ecrit : 01_collecte_inventaire_esu.txt (%d fichiers)" % sum(1 for x in out if x.startswith("=")))


if __name__ == "__main__":
    main()
