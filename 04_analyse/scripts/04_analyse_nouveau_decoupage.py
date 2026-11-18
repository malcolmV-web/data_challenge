# -*- coding: utf-8 -*-
"""Report des besoins sur le NOUVEAU decoupage (17 regions, 47 provinces).
Le calcul reste fait sur les 45 provinces anciennes (seul decoupage des effectifs et des projections). Chaque quantite
additive d'une province ancienne est repartie entre les provinces nouvelles au prorata des enfants de 6-11 ans du RGPH 2019
(02_nettoye_rgph2019_poids_ancien_nouveau.csv). C'est une ESTIMATION : elle suppose que les eleves, les salles et les
maitres se repartissent comme les enfants d'age scolaire au sein de la province ancienne.

Usage : python 04_analyse_nouveau_decoupage.py [--params parametres/parametres_modele.json] [--sortie 04_analyse/resultats]
Sorties : 04_besoins_nouveau_decoupage_provinces.csv, 04_besoins_nouveau_decoupage_regions.csv, 04_passage_ancien_nouveau.csv"""

import json
import sys
from pathlib import Path
import pandas as pd

DEFAUT = {"fichiers_nouveau_decoupage": {
    "besoins": "04_analyse/resultats/04_besoins_horizon.csv",
    "bilan": "04_analyse/resultats/04_bilan_province.csv",
    "poids": "02_nettoyage/rgph2019_localites/02_nettoye_rgph2019_poids_ancien_nouveau.csv"}}
ADD_B = ["pop_6_11_horizon", "eleves_horizon", "enfants_hors_ecole_horizon", "salles_actuelles", "salles_publiques_actuelles", "besoin_salles",
         "deficit_salles", "salles_a_remplacer", "maitres_publics_actuels", "besoin_maitres_public", "deficit_maitres_public", "excedent_maitres_public"]
ADD_S = ["maitres_recus", "maitres_cedes", "recrutements_necessaires", "salles_a_construire"]


def main():
    a = sys.argv[1:]
    F = dict(DEFAUT["fichiers_nouveau_decoupage"])
    if "--params" in a:
        F.update(json.load(open(a[a.index("--params") + 1], encoding="utf-8")).get("fichiers_nouveau_decoupage", {}))
    sortie = Path(a[a.index("--sortie") + 1]) if "--sortie" in a else Path("04_analyse/resultats")
    if not Path(F["poids"]).exists():
        print("Poids RGPH 2019 absents (%s) : etape ignoree. Lancer d'abord le nettoyage du fichier des localites." % F["poids"])
        return
    bes = pd.read_csv(F["besoins"], sep=";")
    bil = pd.read_csv(F["bilan"], sep=";")
    w = pd.read_csv(F["poids"], sep=";")
    w = w[["province_ancienne", "region_nouvelle", "province_nouvelle", "part_pop_6_11", "nb_communes"]].rename(columns={"province_ancienne": "province", "part_pop_6_11": "part"})
    manq = sorted(set(bes.province) - set(w.province))
    if manq:
        print("ATTENTION : provinces sans poids (reprises a 100 %% sans province nouvelle) :", manq)
    x = bes.merge(bil[["scenario", "province"] + ADD_S], on=["scenario", "province"], how="left").merge(w, on="province", how="inner")
    for c in ADD_B + ADD_S:
        x[c] = x[c] * x["part"]
    prov = x.groupby(["scenario", "region_nouvelle", "province_nouvelle"])[ADD_B + ADD_S].sum().round(0).astype(int).reset_index()
    origine = x.groupby(["scenario", "province_nouvelle"]).apply(lambda g: ", ".join("%s (%.0f %%)" % (p, 100 * s) for p, s in zip(g.province, g.part))).rename("provinces_anciennes").reset_index()
    prov = prov.merge(origine, on=["scenario", "province_nouvelle"])
    reg = prov.groupby(["scenario", "region_nouvelle"])[ADD_B + ADD_S].sum().reset_index()
    sortie.mkdir(parents=True, exist_ok=True)
    prov.to_csv(sortie / "04_besoins_nouveau_decoupage_provinces.csv", sep=";", index=False, encoding="utf-8")
    reg.to_csv(sortie / "04_besoins_nouveau_decoupage_regions.csv", sep=";", index=False, encoding="utf-8")
    w.rename(columns={"province": "province_ancienne"}).to_csv(sortie / "04_passage_ancien_nouveau.csv", sep=";", index=False, encoding="utf-8")
    # controle : les totaux nationaux sont conserves
    for sc, g in bes.groupby("scenario"):
        a0, a1 = int(g.deficit_salles.sum()), int(reg[reg.scenario == sc].deficit_salles.sum())
        m0, m1 = int(g.deficit_maitres_public.sum()), int(reg[reg.scenario == sc].deficit_maitres_public.sum())
        print("%-10s salles manquantes %6d -> %6d ; maitres manquants %6d -> %6d (ecart d'arrondi attendu < %d)" % (sc, a0, a1, m0, m1, len(prov[prov.scenario == sc])))
    print("%d provinces nouvelles, %d regions nouvelles ; sorties dans %s" % (prov.province_nouvelle.nunique(), reg.region_nouvelle.nunique(), sortie))


if __name__ == "__main__":
    main()
