# -*- coding: utf-8 -*-
"""Etape 03_transformation : assemble la base par province (45 lignes) a partir des donnees nettoyees
  - indicateurs de l'annee de base (CNS 530, 2024-2025) : ratios, etat des salles, equipement, ruralite, parite ;
  - population 6-11 ans de l'annee de base et de l'horizon (scenario moyen de l'INSD, convention k) ; TBS implicite ;
  - pression d'accueil : PDI (derniere situation) et eleves deplaces internes (ESU, dernier rapport) ;
  - historique du TBS et validation par retro-prediction (maintien contre tendance lineaire).
Aucun besoin ni classement n'est calcule ici : voir l'etape 04_analyse.

Usage : python 03_transformation_base_province.py [--params parametres/parametres_modele.json] [--sortie 03_transformation/donnees_transformees]
Sorties : 03_base_province.csv, 03_validation_tbs.csv, 03_parametres_utilises.json, 03_journal_transformation.csv"""

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
    sortie = Path(args[args.index("--sortie") + 1]) if "--sortie" in args else Path("03_transformation/donnees_transformees")
    sortie.mkdir(parents=True, exist_ok=True)
    journal = []
    def info(m, g="INFO"):
        journal.append(dict(gravite=g, message=m))
    F = params["fichiers"]
    cns = pd.read_csv(F["cns530"], sep=";")
    ref = pd.read_csv(F["referentiel"], sep=";")
    pop = pd.read_csv(F["population"], sep=";")
    k, ab, ah = int(params["k_convention"]), int(params["annee_base"]), int(params["annee_horizon"])
    info("convention k=%d ; annee de base %d-%d ; horizon %d-%d ; scenario de population : moyen (INSD)" % (k, ab, ab + 1, ah, ah + 1))

    # ------------------------------------------------------------ 1) base 2024-2025
    d = cns[(cns.section == "I.1") & (cns.type_ligne == "detail") & cns.province.notna()]
    i1 = d.pivot_table(index=["region", "province"], columns=["indicateur", "statut"], values="valeur", aggfunc="sum")
    base = pd.DataFrame(index=i1.index)
    for ind in ("ecoles", "salles", "groupes", "maitres", "eleves"):
        for st, suf in (("PUBLIC", "pub"), ("PRIVE", "priv"), ("PUBLIC_PRIVE", "tot")):
            if (ind, st) in i1.columns:
                base["%s_%s" % (ind, suf)] = i1[(ind, st)]
    base = base.reset_index()
    base["eleves_par_maitre_public"] = base.eleves_pub / base.maitres_pub
    base["eleves_par_maitre_total"] = base.eleves_tot / base.maitres_tot
    base["eleves_par_salle_total"] = base.eleves_tot / base.salles_tot
    base["eleves_par_salle_public"] = base.eleves_pub / base.salles_pub
    base["eleves_par_groupe_total"] = base.eleves_tot / base.groupes_tot
    base["part_public_eleves"] = base.eleves_pub / base.eleves_tot
    # milieu (V.2)
    v2 = cns[(cns.section == "V.2") & (cns.type_ligne == "detail") & (cns.statut == "PUBLIC_PRIVE") & cns.province.notna()]
    m = v2.pivot_table(index="province", columns=["indicateur", "milieu"], values="valeur", aggfunc="sum")
    base = base.merge(pd.DataFrame({"province": m.index, "part_salles_rurales": (m[("salles", "RURAL")] / m[("salles", "TOTAL")]).values,
                                    "part_ecoles_rurales": (m[("ecoles", "RURAL")] / m[("ecoles", "TOTAL")]).values}), on="province", how="left")
    # equipement (V.4, public + prive)
    v4 = cns[(cns.section == "V.4") & (cns.type_ligne == "detail") & (cns.statut == "PUBLIC_PRIVE") & cns.milieu.isna() & cns.province.notna()]
    e = v4.pivot_table(index="province", columns="indicateur", values="valeur", aggfunc="sum")
    equip = pd.DataFrame({"province": e.index, "part_ecoles_sans_eau": 1 - e["eau_potable"].values / e["ecoles_fonctionnelles"].values,
                          "part_ecoles_sans_latrines": 1 - e["latrines"].values / e["ecoles_fonctionnelles"].values,
                          "part_ecoles_sans_electricite": 1 - e["electricite"].values / e["ecoles_fonctionnelles"].values})
    base = base.merge(equip, on="province", how="left")
    # etat des salles (VI.4)
    v6 = cns[(cns.section == "VI.4") & (cns.type_ligne == "detail") & (cns.statut == "PUBLIC_PRIVE") & cns.milieu.isna() & cns.province.notna()]
    murs = v6[v6.sous_section == "VI.4.1"].pivot_table(index="province", columns="indicateur", values="valeur", aggfunc="sum")
    toit = v6[v6.sous_section == "VI.4.2"].pivot_table(index="province", columns="indicateur", values="valeur", aggfunc="sum")
    etat = pd.DataFrame({"province": murs.index,
                         "part_murs_precaires": (murs["murs_paille_banco_autre"] / murs["salles_total"]).values,
                         "part_etat_mauvais": (murs["etat_mauvais"] / murs["salles_total"]).values,
                         "salles_mauvais_etat": murs["etat_mauvais"].values})
    et2 = pd.DataFrame({"province": toit.index, "part_toits_precaires": ((toit["toit_banco"] + toit["toit_paille"] + toit["toit_sans_toit"]) / toit["salles_total"]).values})
    base = base.merge(etat, on="province", how="left").merge(et2, on="province", how="left")
    base["vetuste"] = base[["part_murs_precaires", "part_toits_precaires", "part_etat_mauvais"]].mean(axis=1)
    # historique des effectifs (VIII.1) : TBS implicite et parite
    h = cns[(cns.section == "VIII.1") & cns.province.notna()].copy()
    h["N"] = h.annee_scolaire.str[:4].astype(int)
    hh = h.pivot_table(index=["province", "N"], columns="indicateur", values="valeur", aggfunc="sum").reset_index()
    base = base.merge(hh[hh.N == ab][["province", "eleves_filles", "eleves_garcons"]], on="province", how="left")
    base["rapport_filles_garcons"] = base.eleves_filles / base.eleves_garcons
    base["ecart_parite"] = (1 - base.rapport_filles_garcons).clip(lower=0)
    # population (scenario moyen) ; total = garcons + filles (deja retenu dans le fichier)
    P = pop[["province", "annee", "pop_6_11_total", "alerte_controle"]].copy()
    def pop_annee(N):
        x = P[P.annee == N + k][["province", "pop_6_11_total", "alerte_controle"]]
        return x.rename(columns={"pop_6_11_total": "pop_%d" % N, "alerte_controle": "alerte_pop_%d" % N})
    base = base.merge(pop_annee(ab), on="province", how="left")
    base["tbs_base"] = base.eleves_tot / base["pop_%d" % ab]
    info("TBS implicite %d-%d (eleves CNS 530 / pop 6-11 ans) : min %.2f, mediane %.2f, max %.2f ; %d provinces > 1,20" % (
        ab, ab + 1, base.tbs_base.min(), base.tbs_base.median(), base.tbs_base.max(), int((base.tbs_base > 1.2).sum())))
    # PDI et OSM (optionnels)
    if Path(F["pdi"]).exists():
        pdi = pd.read_csv(F["pdi"], sep=";")[["province", "pdi_total", "pdi_enfants", "date"]]
        base = base.merge(pdi, on="province", how="left")
        base["pdi_pour_100_enfants_6_11"] = 100 * base.pdi_total / base["pop_%d" % ab]
        info("PDI : situation du %s" % pdi.date.iloc[0])
    else:
        base["pdi_pour_100_enfants_6_11"] = 0.0
        info("fichier PDI absent : pilier pression_pdi = 0", "ATTENTION")
    if Path(F["osm"]).exists():
        osm = pd.read_csv(F["osm"], sep=";")[["province", "couverture_osm_school", "couverture_osm_toutes_structures"] if "couverture_osm_toutes_structures" in pd.read_csv(F["osm"], sep=";", nrows=1).columns else ["province", "couverture_osm_school"]]
        base = base.merge(osm, on="province", how="left")

    # ESU : eleves deplaces internes (EDI) et structures delocalisees, dernier rapport, provinces anciennes
    base["edi_pour_100_eleves"] = np.nan
    if Path(F.get("esu", "")).exists():
        esu = pd.read_csv(F["esu"], sep=";")
        dernier = esu.mois.dropna().max()
        e1 = esu[esu.mois == dernier]
        edi = e1[(e1.indicateur == "edi") & (e1.sexe == "T")].pivot_table(index="province_ancienne", columns="ordre", values="valeur", aggfunc="sum")
        edi.columns = ["edi_%s" % c for c in edi.columns]
        base = base.merge(edi.reset_index().rename(columns={"province_ancienne": "province"}), on="province", how="left")
        for c in edi.columns:
            base[c] = base[c].fillna(0)
        if "edi_primaire" in base.columns:
            base["edi_pour_100_eleves"] = 100 * base.edi_primaire / base.eleves_tot
        deloc = e1[(e1.indicateur == "structures") & (e1.statut == "delocalisee") & (e1.ordre == "total")].groupby("province_ancienne").valeur.sum()
        rouv = e1[(e1.indicateur == "structures") & (e1.statut == "rouverte") & (e1.ordre == "total")].groupby("province_ancienne").valeur.sum()
        base["structures_delocalisees"] = base.province.map(deloc).fillna(0)
        base["structures_rouvertes"] = base.province.map(rouv).fillna(0)
        non = sorted(set(edi.index) - set(base.province))
        info("ESU %s : EDI du primaire pour 100 eleves : mediane %.1f, max %.1f ; %d provinces avec EDI%s" % (
            dernier, base.edi_pour_100_eleves.median(), base.edi_pour_100_eleves.max(), int((base.get("edi_primaire", 0) > 0).sum()),
            (" ; provinces ESU non rapprochees : %s" % non) if non else ""), "ATTENTION" if non else "INFO")
    else:
        info("fichier ESU absent : pilier pression_pdi calcule sur les PDI seuls", "ATTENTION")
    seuil = params.get("seuil_classe_multi_enseignants_primaire", 75)
    base["classe_moyenne_au_dessus_du_seuil"] = (base.eleves_par_salle_total > seuil).astype(int)
    info("provinces dont la classe moyenne depasse %d eleves : %d ; au-dessus de la norme : %d" % (seuil, int(base.classe_moyenne_au_dessus_du_seuil.sum()),
                                                                                              int((base.eleves_par_salle_total > (params["norme_eleves_par_classe"] or 50)).sum())))

    # normes
    ne = params["norme_eleves_par_classe"] or float(base.eleves_par_salle_total.median())
    nm = params["norme_eleves_par_maitre"] or float(base.eleves_par_maitre_public.median())
    params["norme_eleves_par_classe_utilisee"], params["norme_eleves_par_maitre_utilisee"] = round(ne, 2), round(nm, 2)
    hyp = "mediane nationale 2024-2025 (HYPOTHESE)"
    info("norme eleves par classe : %.1f (%s)" % (ne, "parametre" if params["norme_eleves_par_classe"] else hyp))
    info("norme eleves par maitre (public) : %.1f (%s)" % (nm, "parametre" if params["norme_eleves_par_maitre"] else hyp))

    # ------------------------------------------------------------ 2) TBS historique, tendance et validation
    hist = hh[(hh.N >= 2020) & (hh.N <= ab)].merge(P.assign(N=P.annee - k)[["province", "N", "pop_6_11_total"]], on=["province", "N"], how="inner")
    hist["tbs"] = hist.eleves_total / hist.pop_6_11_total
    pentes, retro = {}, []
    for prov, g in hist.groupby("province"):
        g = g.sort_values("N")
        if len(g) >= 4:
            sl = np.polyfit(g.N, g.tbs, 1)[0]
            pentes[prov] = sl
            g2 = g[g.N < ab]
            if len(g2) >= 3:
                c = np.polyfit(g2.N, g2.tbs, 1)
                pred = np.polyval(c, ab)
                reel = float(g[g.N == ab].tbs.iloc[0])
                retro.append(dict(province=prov, tbs_reel=reel, tbs_predit_tendance=pred, tbs_predit_maintien=float(g2.tbs.iloc[-1]),
                                  erreur_tendance=abs(pred - reel), erreur_maintien=abs(float(g2.tbs.iloc[-1]) - reel)))
    base["pente_tbs_par_an"] = base.province.map(pentes)
    val = pd.DataFrame(retro)
    val.to_csv(sortie / "03_validation_tbs.csv", sep=";", index=False, encoding="utf-8")
    if len(val):
        info("retro-prediction du TBS %d (ajuste sur %d-%d) : erreur absolue moyenne ; tendance %.3f, maintien %.3f (points de TBS en proportion)" % (
            ab, 2020, ab - 1, val.erreur_tendance.mean(), val.erreur_maintien.mean()))
        meilleur = "tendance" if val.erreur_tendance.mean() < val.erreur_maintien.mean() else "maintien"
        info("scenario le plus fiable en retro-prediction : %s" % meilleur)

    ph = pop_annee(ah)
    ph = ph.rename(columns={"pop_%d" % ah: "pop_horizon", "alerte_pop_%d" % ah: "alerte_pop_horizon"})
    base = base.merge(ph, on="province", how="left")
    base.to_csv(sortie / "03_base_province.csv", sep=";", index=False, encoding="utf-8")
    json.dump(params, open(sortie / "03_parametres_utilises.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    pd.DataFrame(journal).to_csv(sortie / "03_journal_transformation.csv", sep=";", index=False, encoding="utf-8")
    for j in journal:
        print("  %-9s %s" % (j["gravite"], j["message"][:260]))
    print("Sorties dans :", sortie.resolve())


if __name__ == "__main__":
    main()
