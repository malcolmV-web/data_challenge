# -*- coding: utf-8 -*-
"""Etape 04_analyse (1/2) : besoins a l'horizon et indice de priorite, a partir de la base par province (etape 03)
  1) besoins en salles et en maitres publics a l'horizon selon trois scenarios de scolarisation : maintien, reprise, universel ;
  2) sensibilite des deficits a la norme d'eleves par classe ;
  3) indice de priorite (5 piliers ponderes), rang par urgence et rang par volume ;
  4) sensibilite du classement aux ponderations (tirages de Dirichlet, graine fixee).

Usage : python 04_analyse_besoins_indice_priorite.py [--params parametres/parametres_modele.json] [--sortie 04_analyse/resultats]
Entree : 03_transformation/donnees_transformees/03_base_province.csv
Sorties : 04_besoins_horizon.csv, 04_sensibilite_normes.csv, 04_indice_priorite.csv, 04_sensibilite_classement.csv, 04_journal_analyse.csv"""

import json
import math
import sys
from pathlib import Path
import numpy as np
import pandas as pd

DEFAUT = {
    "fichiers": {"cns530": "02_nettoyage/cns530_annuaire_2024-25/02_nettoye_cns530_long.csv", "referentiel": "02_nettoyage/cns530_annuaire_2024-25/02_nettoye_cns530_referentiel_provinces.csv",
                 "population": "02_nettoyage/projections_insd_provinces_2020-2035/02_nettoye_projections_population_cible_province.csv",
                 "pdi": "02_nettoyage/pdi_idps4_serie/02_nettoye_pdi_idps4_province_derniere.csv", "osm": "02_nettoyage/osm_ecoles/02_nettoye_osm_couverture_vs_cns530.csv",
                 "esu": "02_nettoyage/esu_rapports_2026/02_nettoye_esu_2026_province_ancienne.csv"},
    "k_convention": 0,            # annee scolaire N-(N+1) <-> projection de l'annee civile N + k (a trancher avec 02_nettoyage_recoupements_convention.py)
    "annee_base": 2024,           # annee scolaire 2024-2025
    "annee_horizon": 2029,        # annee scolaire 2029-2030
    "norme_eleves_par_classe": None,   # None -> mediane nationale 2024-2025 des eleves par salle (public + prive)
    "norme_eleves_par_maitre": None,   # None -> mediane nationale 2024-2025 des eleves par maitre (public)
    "tbs_plafond": 1.10,          # plafond du TBS projete (proportion)
    "scenario_pour_indice": "maintien",
    "tbs_cible_reprise": None,    # None -> mediane nationale du TBS de l'annee de base ; scenario "reprise" = max(TBS actuel, cible)
    "tbs_cible_universel": 1.0,   # scenario "universel" = max(TBS actuel, 1,0)
    "normes_classe_testees": [45, 50, 55, 60, 75],
    "seuil_classe_multi_enseignants_primaire": 75,
    "poids": {"surcharge": 0.30, "deficit_projete": 0.25, "vetuste": 0.15, "equite": 0.15, "pression_pdi": 0.15},
    "tirages_sensibilite": 2000, "concentration_dirichlet": 20, "graine": 7,
}


def charger_params(chemin):
    p = json.loads(json.dumps(DEFAUT))
    if chemin:
        u = json.load(open(chemin, encoding="utf-8"))
        for k, v in u.items():
            if isinstance(v, dict) and isinstance(p.get(k), dict):
                p[k].update(v)
            else:
                p[k] = v
    return p


def piv(df, filtre, index, colonnes, valeurs="valeur"):
    d = df[filtre]
    return d.pivot_table(index=index, columns=colonnes, values=valeurs, aggfunc="sum")


def minmax(s):
    lo, hi = s.min(), s.max()
    return (s - lo) / (hi - lo) if hi > lo else s * 0.0


def main():
    args = sys.argv[1:]
    params = charger_params(args[args.index("--params") + 1] if "--params" in args else None)
    sortie = Path(args[args.index("--sortie") + 1]) if "--sortie" in args else Path("04_analyse/resultats")
    sortie.mkdir(parents=True, exist_ok=True)
    journal = []
    def info(m, g="INFO"):
        journal.append(dict(gravite=g, message=m))
    base = pd.read_csv(params["fichiers"].get("base", "03_transformation/donnees_transformees/03_base_province.csv"), sep=";")
    k, ab, ah = int(params["k_convention"]), int(params["annee_base"]), int(params["annee_horizon"])
    ne = params["norme_eleves_par_classe"] or float(base.eleves_par_salle_total.median())
    nm = params["norme_eleves_par_maitre"] or float(base.eleves_par_maitre_public.median())
    info("normes : %.1f eleves par classe, %.1f eleves par maitre (public) ; horizon %d-%d" % (ne, nm, ah, ah + 1))

    # ------------------------------------------------------------ 3) besoins a l'horizon
    lignes = []
    cible_r = params.get("tbs_cible_reprise") or float(base.tbs_base.median())
    cible_u = float(params.get("tbs_cible_universel", 1.0))
    params["tbs_cible_reprise_utilisee"] = round(cible_r, 4)
    info("scenarios : maintien (TBS de l'annee de base) ; reprise (au moins le TBS median national, %.3f) ; universel (au moins %.2f) ; "
         "la tendance lineaire 2020-%d n'est pas utilisee pour les besoins (extrapolation instable : voir 03_validation_tbs.csv)" % (cible_r, cible_u, ab))
    tbs_sc = {"maintien": base.tbs_base, "reprise": base.tbs_base.clip(lower=cible_r), "universel": base.tbs_base.clip(lower=cible_u)}
    for sc in ("maintien", "reprise", "universel"):
        tbs_h = tbs_sc[sc]
        eh = base.pop_horizon * tbs_h
        besoin_salles = np.ceil(eh / ne)
        besoin_maitres = np.ceil(eh * base.part_public_eleves / nm)
        lignes.append(pd.DataFrame({
            "region": base.region, "province": base.province, "scenario": sc, "tbs_horizon": tbs_h.round(4), "pop_6_11_horizon": base.pop_horizon.round(0),
            "eleves_horizon": eh.round(0), "enfants_hors_ecole_horizon": (base.pop_horizon - eh).clip(lower=0).round(0),
            "salles_actuelles": base.salles_tot, "salles_publiques_actuelles": base.salles_pub, "besoin_salles": besoin_salles, "deficit_salles": (besoin_salles - base.salles_tot).clip(lower=0),
            "excedent_salles": (base.salles_tot - besoin_salles).clip(lower=0), "salles_a_remplacer": base.salles_mauvais_etat,
            "maitres_publics_actuels": base.maitres_pub, "besoin_maitres_public": besoin_maitres,
            "deficit_maitres_public": (besoin_maitres - base.maitres_pub).clip(lower=0), "excedent_maitres_public": (base.maitres_pub - besoin_maitres).clip(lower=0),
            "alerte_population": base.alerte_pop_horizon}))
    bes = pd.concat(lignes, ignore_index=True)
    bes.to_csv(sortie / "04_besoins_horizon.csv", sep=";", index=False, encoding="utf-8")
    # sensibilite des deficits a la norme d'eleves par classe
    sn = []
    for sc in tbs_sc:
        eh = base.pop_horizon * tbs_sc[sc]
        for n_ in params.get("normes_classe_testees", [45, 50, 55, 60, 75]):
            sn.append(dict(scenario=sc, norme_eleves_par_classe=n_, deficit_salles=float((np.ceil(eh / n_) - base.salles_tot).clip(lower=0).sum()),
                           provinces_en_deficit=int(((np.ceil(eh / n_) - base.salles_tot) > 0).sum())))
    pd.DataFrame(sn).to_csv(sortie / "04_sensibilite_normes.csv", sep=";", index=False, encoding="utf-8")
    for sc, g in bes.groupby("scenario", sort=False):
        info("horizon %d-%d, scenario %s : deficit national %d salles et %d maitres publics ; excedent %d salles et %d maitres (provinces excedentaires non compensees)" % (
            ah, ah + 1, sc, g.deficit_salles.sum(), g.deficit_maitres_public.sum(), g.excedent_salles.sum(), g.excedent_maitres_public.sum()))

    # ------------------------------------------------------------ 4) indice de priorite
    sc_i = params["scenario_pour_indice"]
    b = bes[bes.scenario == sc_i].set_index("province")
    bb = base.set_index("province")
    piliers = pd.DataFrame(index=bb.index)
    piliers["surcharge"] = (minmax(bb.eleves_par_maitre_public) + minmax(bb.eleves_par_salle_total)) / 2
    piliers["deficit_projete"] = (minmax(b.deficit_salles / bb.salles_tot) + minmax(b.deficit_maitres_public / bb.maitres_pub)) / 2
    piliers["vetuste"] = minmax(bb.vetuste)
    piliers["equite"] = (minmax(bb.part_salles_rurales) + minmax(bb.ecart_parite) + minmax(bb.part_ecoles_sans_latrines)) / 3
    if bb.edi_pour_100_eleves.notna().any():
        piliers["pression_pdi"] = (minmax(bb.pdi_pour_100_enfants_6_11.fillna(0)) + minmax(bb.edi_pour_100_eleves.fillna(0))) / 2
        info("pilier pression_pdi : moyenne des PDI pour 100 enfants (derniere situation disponible) et des EDI du primaire pour 100 eleves (ESU)")
    else:
        piliers["pression_pdi"] = minmax(bb.pdi_pour_100_enfants_6_11)
    w = pd.Series(params["poids"], dtype=float)
    w = w / w.sum()
    piliers = piliers[list(w.index)].fillna(0)
    score = (piliers * w).sum(axis=1) * 100
    ind = piliers.copy()
    ind["score"] = score.round(2)
    ind["rang"] = ind.score.rank(ascending=False, method="min").astype(int)
    for c in w.index:
        ind["contrib_" + c] = (piliers[c] * w[c] * 100).round(2)
    ind = ind.reset_index().merge(base[["region", "province"]], on="province")
    for sc in tbs_sc:
        x = bes[bes.scenario == sc].set_index("province")
        ind["deficit_salles_%s" % sc] = ind.province.map(x.deficit_salles)
        ind["deficit_maitres_%s" % sc] = ind.province.map(x.deficit_maitres_public)
    ind["rang_volume_salles"] = ind["deficit_salles_%s" % sc_i].rank(ascending=False, method="min").astype(int)
    ind = ind.sort_values("rang")
    ind.to_csv(sortie / "04_indice_priorite.csv", sep=";", index=False, encoding="utf-8")
    # sensibilite : poids tires dans une loi de Dirichlet centree sur les poids de base
    rng = np.random.default_rng(params["graine"])
    tirages = rng.dirichlet(w.values * params["concentration_dirichlet"], size=params["tirages_sensibilite"])
    scores = piliers.values @ tirages.T
    rangs = pd.DataFrame(scores, index=piliers.index).rank(ascending=False, method="min")
    base_rang = ind.set_index("province").rang
    corr = [pd.Series(rangs[j]).rank().corr(base_rang.reindex(rangs.index).rank()) for j in range(0, rangs.shape[1], max(1, rangs.shape[1] // 200))]
    sens = pd.DataFrame({"rang_base": base_rang.reindex(rangs.index), "rang_median": rangs.median(axis=1), "rang_p10": rangs.quantile(0.1, axis=1),
                         "rang_p90": rangs.quantile(0.9, axis=1), "freq_top10": (rangs <= 10).mean(axis=1).round(3)}).reset_index().sort_values("rang_base")
    sens.to_csv(sortie / "04_sensibilite_classement.csv", sep=";", index=False, encoding="utf-8")
    top10 = sens[sens.rang_base <= 10]
    info("indice : scenario %s, poids %s" % (sc_i, {k_: round(v, 2) for k_, v in w.items()}))
    info("sensibilite (%d tirages) : correlation de Spearman moyenne avec le classement de base %.3f ; %d des 10 premieres provinces restent dans le top 10 plus de 70 %% du temps" % (
        params["tirages_sensibilite"], float(np.mean(corr)), int((top10.freq_top10 > 0.7).sum())))
    pd.DataFrame(journal).to_csv(sortie / "04_journal_analyse.csv", sep=";", index=False, encoding="utf-8")
    for j in journal:
        print("  %-9s %s" % (j["gravite"], j["message"][:260]))
    print("Sorties dans :", sortie.resolve())


if __name__ == "__main__":
    main()
