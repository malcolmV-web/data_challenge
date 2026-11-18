# -*- coding: utf-8 -*-
"""Recoupe le voisinage des provinces avec les LIGNES de limites COD-AB (bfa_admin_boundaries__bfa_adminlines.csv) :
chaque ligne de frontiere porte le code de l'unite a droite (right_pcod) et a gauche (left_pcod). Les frontieres entre COMMUNES
(adm3) sont rattachees a leur province ancienne : deux provinces sont voisines si une frontiere separe
une commune de l'une d'une commune de l'autre. Methode topologique, independante des sommets des polygones.

Usage : python 02_nettoyage_carte_voisins_adminlines.py bfa_admin_boundaries__bfa_adminlines.csv 02_nettoyage/cod_ab_limites_administratives/02_nettoye_cod_ab_communes_ancien_decoupage.csv
        [--polygones 02_nettoyage/carte_provinces_voisins/02_nettoye_carte_voisins_provinces.csv] [dossier_sortie]
Sorties : 02_nettoye_carte_voisins_provinces_adminlines.csv ; affichage : couples, comparaison avec la methode des polygones."""

import csv
import re
import sys
from collections import Counter
from pathlib import Path
import pandas as pd
import sys as _sys
from pathlib import Path as _P
_sys.path.insert(0, str(_P(__file__).resolve().parents[2] / 'communs'))
import outils_communs as oc
from outils_communs import *

csv.field_size_limit(10 ** 8)


def lire(chemin):
    with open(chemin, encoding="utf-8-sig", newline="") as f:
        echant = f.read(5000)
        f.seek(0)
        try:
            sep = csv.Sniffer().sniff(echant, delimiters=";,\t").delimiter
        except csv.Error:
            sep = ";"
        rows = []
        for i, r in enumerate(csv.reader(f, delimiter=sep), 1):
            ligne = []
            for j, v in enumerate(r, 1):
                v2, note = nettoyer_cellule(v)
                if note:
                    oc.NOTES_IGNOREES.append((Path(chemin).name, i, j))
                ligne.append("" if v2 is None else str(v2).strip())
            rows.append(ligne)
    h = next((k for k, r in enumerate(rows[:6]) if "right_pcod" in r and "left_pcod" in r), None)
    if h is None:
        raise SystemExit("Colonnes right_pcod / left_pcod introuvables dans %s" % chemin)
    en_tete = rows[h]
    return pd.DataFrame([r + [""] * (len(en_tete) - len(r)) for r in rows[h + 1:] if any(r)], columns=en_tete)


def main():
    args = sys.argv[1:]
    if len(args) < 2:
        print(__doc__)
        return
    lignes = lire(args[0])
    com = pd.read_csv(args[1], sep=";")
    col_prov = "province_cns530" if "province_cns530" in com.columns else "province_ancienne"
    dico = dict(zip(com["adm3_pcode"].astype(str).str.strip(), com[col_prov]))
    sortie = Path([a for a in args[2:] if not a.startswith("--") and not a.endswith(".csv")][-1]) if [a for a in args[2:] if not a.startswith("--") and not a.endswith(".csv")] else Path("02_nettoyage/carte_provinces_voisins")
    sortie.mkdir(parents=True, exist_ok=True)
    niveaux = Counter(lignes["adm_level"]) if "adm_level" in lignes.columns else {}
    print("Lignes de frontiere : %d ; niveaux : %s" % (len(lignes), dict(niveaux)))
    a = lignes["right_pcod"].map(dico)
    b = lignes["left_pcod"].map(dico)
    utiles = lignes[a.notna() & b.notna()].copy()
    print("Lignes entre deux communes connues : %d (%.0f %%)" % (len(utiles), 100 * len(utiles) / max(len(lignes), 1)))
    paires = Counter()
    for x, y in zip(a[a.notna() & b.notna()], b[a.notna() & b.notna()]):
        if x != y:
            paires[tuple(sorted((x, y)))] += 1
    lig = []
    for (p, q), k in sorted(paires.items()):
        lig += [dict(province=p, voisine=q, nb_segments=k), dict(province=q, voisine=p, nb_segments=k)]
    vp = pd.DataFrame(lig).sort_values(["province", "voisine"]) if lig else pd.DataFrame(columns=["province", "voisine", "nb_segments"])
    vp.to_csv(sortie / "02_nettoye_carte_voisins_provinces_adminlines.csv", sep=";", index=False, encoding="utf-8")
    nb = vp.groupby("province").size()
    print("Couples de provinces voisines (lignes COD-AB) : %d ; voisines par province : min %d, moyenne %.1f, max %d" % (
        len(paires), nb.min() if len(nb) else 0, nb.mean() if len(nb) else 0, nb.max() if len(nb) else 0))
    print("Provinces avec 1 ou 2 voisines :", {p: int(n) for p, n in nb[nb <= 2].items()})
    if "--polygones" in args:
        pol = pd.read_csv(args[args.index("--polygones") + 1], sep=";")
        sp = set(tuple(sorted(t)) for t in zip(pol.province, pol.voisine))
        sl = set(paires)
        print("\nComparaison avec la methode des polygones : %d couples en commun" % len(sp & sl))
        print("  seulement dans les polygones (%d) : %s" % (len(sp - sl), sorted(sp - sl)[:20]))
        print("  seulement dans les lignes     (%d) : %s" % (len(sl - sp), sorted(sl - sp)[:20]))
    if oc.NOTES_IGNOREES:
        print("%d cellule(s) contenaient une note adressee a un assistant IA : texte ecarte, non execute" % len(oc.NOTES_IGNOREES))
    print("Sorties dans :", sortie.resolve())


if __name__ == "__main__":
    main()
