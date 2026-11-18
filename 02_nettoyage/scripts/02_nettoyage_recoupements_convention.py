# -*- coding: utf-8 -*-
"""Recoupements entre les sources nettoyees et choix de la convention d'annee (scolaire / civile).

1) Effectifs du primaire par region, annee scolaire et sexe : classeur DGESS (tableau 1)  vs  somme des provinces du CNS 530
   (section VIII.1). Remplace le controle contre les depliants, absents pour 2024-2025.
2) Convention d'annee : TBS publie (classeur, tableau 7)  vs  effectifs (classeur) / population de 6 a 11 ans (projections INSD).
   On compare l'annee scolaire N-(N+1) a l'annee civile N (k = 0) puis N+1 (k = 1) et on retient celle dont l'ecart est le plus petit.

Usage : python 02_nettoyage_recoupements_convention.py classeur_long.csv 02_nettoye_cns530_long.csv 02_nettoye_projections_provinces_long.csv [dossier_sortie]
  classeur_long.csv  = sortie/02_nettoye_classeur_tableaux_long.csv            (script 01)
  02_nettoye_cns530_long.csv    = 02_nettoyage/cns530_annuaire_2024-25/02_nettoye_cns530_long.csv        (script 20)
  02_nettoye_projections_provinces_long.csv = 02_nettoyage/projections_insd_provinces_2020-2035/02_nettoye_projections_provinces_long.csv (script 30)
Sorties : 02_controles_recoupement_effectifs.csv, 02_controles_convention_annee.csv (';' UTF-8) ; l'affichage ne contient que des ecarts relatifs."""

import sys
from pathlib import Path
import pandas as pd

TOL = 0.005


def lire(p):
    return pd.read_csv(p, sep=";")


def recoupement_effectifs(cl, cns):
    a = cl[(cl.cycle == "primaire") & (cl.indicateur == "EFFECTIFS") & (cl.tableau == 1) & (cl.type_ligne == "detail")]
    a = a.groupby(["region", "annee_debut", "sexe"])["valeur"].sum().rename("classeur")
    b = cns[(cns.section == "VIII.1") & (cns.type_ligne == "detail")].copy()
    b["sexe"] = b.indicateur.map({"eleves_garcons": "Garcons", "eleves_filles": "Filles", "eleves_total": "Total"})
    b["annee_debut"] = b.annee_scolaire.str[:4].astype(int)
    b = b.groupby(["region", "annee_debut", "sexe"])["valeur"].sum().rename("cns530_provinces")
    m = pd.concat([a, b], axis=1).dropna().reset_index()
    m["ecart_relatif"] = (m["classeur"] - m["cns530_provinces"]) / m["cns530_provinces"]
    return m


def convention_annee(cl, proj):
    eff = cl[(cl.cycle == "primaire") & (cl.indicateur == "EFFECTIFS") & (cl.tableau == 1) & (cl.type_ligne == "detail")]
    eff = eff.groupby(["region", "annee_debut", "sexe"])["valeur"].sum().rename("effectifs")
    tbs = cl[(cl.cycle == "primaire") & (cl.indicateur == "TBS") & (cl.type_ligne == "detail")]
    tbs = tbs.groupby(["region", "annee_debut", "sexe"])["valeur"].mean().rename("tbs_publie")
    p = proj[(proj.niveau == "region") & (proj.groupe_age == "6-11")].copy()
    p = p.groupby(["region", "annee", "sexe"])["valeur"].sum().rename("pop_6_11").reset_index()
    base = pd.concat([eff, tbs], axis=1).dropna().reset_index()
    if base.empty:
        return pd.DataFrame()
    echelle = 100 if base["tbs_publie"].median() > 5 else 1   # TBS en % ou en proportion
    res = []
    for k in (0, 1):
        q = base.copy()
        q["annee"] = q["annee_debut"] + k
        q = q.merge(p, on=["region", "annee", "sexe"], how="inner")
        if q.empty:
            continue
        q["tbs_implicite"] = q["effectifs"] / q["pop_6_11"] * echelle
        q["ecart_points"] = q["tbs_implicite"] - q["tbs_publie"]
        q["k"] = k
        res.append(q)
    return pd.concat(res, ignore_index=True) if res else pd.DataFrame()


def main():
    if len(sys.argv) < 4:
        print(__doc__)
        return
    cl, cns, proj = lire(sys.argv[1]), lire(sys.argv[2]), lire(sys.argv[3])
    sortie = Path(sys.argv[4]) if len(sys.argv) > 4 else Path("02_nettoyage/recoupements_classeur_cns530_projections")
    sortie.mkdir(parents=True, exist_ok=True)
    m = recoupement_effectifs(cl, cns)
    m.to_csv(sortie / "02_controles_recoupement_effectifs.csv", sep=";", index=False, encoding="utf-8")
    bad = m[m.ecart_relatif.abs() > TOL]
    print("1) Effectifs classeur = somme des provinces CNS 530 : %d comparaisons, %d ecart(s) > %.1f %%" % (len(m), len(bad), TOL * 100))
    if len(bad):
        print(bad.groupby(["annee_debut"]).size().to_string())
        print(bad.groupby(["region"]).size().to_string())
        print("ecart relatif max : %.4f" % bad.ecart_relatif.abs().max())
    c = convention_annee(cl, proj)
    if c.empty:
        print("2) Convention d'annee : aucune comparaison possible (annees 2020-2024 attendues).")
        return
    c.to_csv(sortie / "02_controles_convention_annee.csv", sep=";", index=False, encoding="utf-8")
    cs = c[c.sexe == "Total"]
    libelle = "sexe Total"
    if cs.empty:
        cs, libelle = c, "garcons et filles"
    t = cs.groupby("k")["ecart_points"].agg(ecart_moyen="mean", ecart_absolu_moyen=lambda x: x.abs().mean(), n="size").round(2)
    print("\n2) Convention d'annee (%s ; ecart entre TBS implicite et TBS publie, en points) :" % libelle)
    print("   k = 0 : annee scolaire N-(N+1)  <->  projection de l'annee civile N")
    print("   k = 1 : annee scolaire N-(N+1)  <->  projection de l'annee civile N+1")
    print(t.to_string())
    print(cs.groupby(["k", "annee_debut"])["ecart_points"].apply(lambda x: x.abs().mean()).round(2).unstack(0).to_string())
    meilleur = t["ecart_absolu_moyen"].idxmin()
    print("\n=> convention retenue : k = %d (ecart absolu moyen le plus faible)" % meilleur)
    print("Sorties dans :", sortie.resolve())


if __name__ == "__main__":
    main()
