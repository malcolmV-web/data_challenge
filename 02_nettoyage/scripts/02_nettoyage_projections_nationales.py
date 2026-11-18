# -*- coding: utf-8 -*-
"""Extrait des projections demographiques INSD 2020-2035 les tableaux NATIONAUX par age simple, sexe et milieu,
pour chaque scenario (moyen, haut, ...), puis identifie le scenario qui correspond aux tableaux regionaux.

Mise en page attendue : titre 'Scenario moyen' / 'Tableau A2. 2 : ...', annee seule sur sa ligne (ex. 2020), en-tetes
'Ages | Urbain | Rural | Ensemble' et 'Homme | Femme | Ensemble' x3, puis une ligne par age (0, 1, ..., 79, 80+, Total)
avec 9 valeurs : Urbain (H, F, E), Rural (H, F, E), Ensemble (H, F, E). Une annee occupe plusieurs pages.

Usage : python 02_nettoyage_projections_nationales.py INSD_RGPH2019_Vol4_Projections_demographiques_2020-2035.csv [dossier_sortie]
        [--pages 25-130] [--regional 02_nettoyage/projections_insd_provinces_2020-2035/02_nettoye_projections_provinces_long.csv]
Sorties : 02_nettoye_projections_nationales_long.csv, 02_nettoye_projections_population_nationale_6_11.csv, 02_journal_projections_nationales.csv,
          02_controles_projections_nationales.csv, 02_nettoye_projections_identification_scenario.csv  (';' UTF-8, decimale '.')"""

import csv
import re
import sys
from pathlib import Path
import pandas as pd
import sys as _sys
from pathlib import Path as _P
_sys.path.insert(0, str(_P(__file__).resolve().parents[2] / 'communs'))
import outils_communs as oc
from outils_communs import *

PAGES = (25, 130)
MILIEUX = ["URBAIN", "RURAL", "ENSEMBLE"]
SEXES3 = ["Garcons", "Filles", "Total"]
TOL = 0.005


def lire_csv(chemin, p0, p1):
    rows = []
    with open(chemin, encoding="utf-8-sig", newline="") as f:
        lecteur = csv.reader(f, delimiter=";")
        en_tete = next(lecteur)
        i_page, i0 = en_tete.index("page"), en_tete.index("nb_cellules") + 1
        i_ligne = en_tete.index("ligne") if "ligne" in en_tete else None
        for r in lecteur:
            try:
                p = int(r[i_page])
            except ValueError:
                continue
            if not (p0 <= p <= p1):
                continue
            cells = []
            for k, v in enumerate(r[i0:]):
                v2, note = nettoyer_cellule(v)
                if note:
                    oc.NOTES_IGNOREES.append(("csv", r[i_ligne] if i_ligne is not None else "?", k + 1))
                cells.append("" if v2 is None else str(v2).strip())
            while cells and cells[-1] == "":
                cells.pop()
            if cells:
                rows.append((p, r[i_ligne] if i_ligne is not None else "", cells))
    return rows


def extraire(rows, journal):
    out = []
    st = dict(scenario="CHAPITRE_1_SANS_TITRE", table="", annee=None)
    vus = {}
    for p, ligne, cells in rows:
        if len(cells) == 1:
            txt = cells[0]
            n = norm_libre(txt)
            y = year_of(txt)
            if y:
                st["annee"] = y[0]
                continue
            m = re.match(r"^scenario\s+(\w+)", n)
            if m:
                st["scenario"] = "SCENARIO_" + m.group(1).upper()
                continue
            if n.startswith("tableau"):
                st["table"] = re.sub(r"\s+", " ", txt.split(":")[0]).strip()
            continue
        lab = cells[0]
        nums = [to_number(c) for c in cells[1:]]
        if len(nums) != 9 or any(v is None for v in nums):
            continue
        n = norm_libre(lab)
        if re.fullmatch(r"\d+", n):
            age = int(n)
        elif n.replace(" ", "") in ("80+", "80etplus"):
            age = "80+"
        elif n == "total":
            age = "TOTAL"
        else:
            continue
        if st["annee"] is None:
            journal.append(dict(gravite="ATTENTION", message="ligne d'age sans annee page %s ligne %s" % (p, ligne)))
            continue
        cle = (st["scenario"], st["table"])
        vus.setdefault(cle, [p, p, set()])
        vus[cle][1] = p
        vus[cle][2].add(st["annee"])
        for k, v in enumerate(nums):
            out.append(dict(scenario=st["scenario"], table=st["table"], annee=st["annee"], age=age,
                            milieu=MILIEUX[k // 3], sexe=SEXES3[k % 3], valeur=v, page_csv=p, ligne_csv=ligne))
    for (sc, tb), (a, b, ys) in vus.items():
        journal.append(dict(gravite="INFO", message="%s | %s : pages %s-%s, %d annees (%s-%s)" % (sc, tb, a, b, len(ys), min(ys), max(ys))))
    return out


def controler(df):
    res = []
    d = df.copy()
    d["age"] = d["age"].astype(str)
    p = d.pivot_table(index=["scenario", "table", "annee", "milieu", "age"], columns="sexe", values="valeur", aggfunc="sum").reset_index()
    p["a"], p["b"] = p["Garcons"] + p["Filles"], p["Total"]
    p["controle"] = "Homme + Femme = Ensemble"
    p["ecart_relatif"] = (p["a"] - p["b"]) / p["b"].replace(0, pd.NA)
    res.append(p[["scenario", "table", "annee", "milieu", "age", "a", "b", "controle", "ecart_relatif"]])
    q = d.pivot_table(index=["scenario", "table", "annee", "sexe", "age"], columns="milieu", values="valeur", aggfunc="sum").reset_index()
    q["a"], q["b"] = q["URBAIN"] + q["RURAL"], q["ENSEMBLE"]
    q["controle"] = "Urbain + Rural = Ensemble"
    q["ecart_relatif"] = (q["a"] - q["b"]) / q["b"].replace(0, pd.NA)
    res.append(q[["scenario", "table", "annee", "sexe", "age", "a", "b", "controle", "ecart_relatif"]])
    det = d[d.age != "TOTAL"].groupby(["scenario", "table", "annee", "milieu", "sexe"])["valeur"].sum().rename("a")
    tot = d[d.age == "TOTAL"].groupby(["scenario", "table", "annee", "milieu", "sexe"])["valeur"].sum().rename("b")
    m = pd.concat([det, tot], axis=1).dropna().reset_index()
    m["controle"] = "somme des ages = Total"
    m["ecart_relatif"] = (m["a"] - m["b"]) / m["b"].replace(0, pd.NA)
    res.append(m)
    return pd.concat(res, ignore_index=True)


def identifier_scenario(nat, reg):
    """Compare la somme des 13 regions (TOTAL et 6-11 ans) a chaque scenario national (ages simples, milieu ENSEMBLE)."""
    r = reg[(reg.niveau == "region")]
    r_tot = r[r.groupe_age == "TOTAL"].groupby(["annee", "sexe"])["valeur"].sum().rename("regions")
    r_611 = r[r.groupe_age == "6-11"].groupby(["annee", "sexe"])["valeur"].sum().rename("regions")
    n = nat[(nat.milieu == "ENSEMBLE")].copy()
    n["age_txt"] = n["age"].astype(str)
    res = []
    for sc, g in n.groupby("scenario"):
        n_tot = g[g.age_txt == "TOTAL"].groupby(["annee", "sexe"])["valeur"].sum().rename("national")
        ag = g[g.age_txt.str.fullmatch(r"\d+")].copy()
        ag["age_i"] = ag.age_txt.astype(int)
        n_611 = ag[(ag.age_i >= 6) & (ag.age_i <= 11)].groupby(["annee", "sexe"])["valeur"].sum().rename("national")
        for nom, a, b in (("TOTAL", r_tot, n_tot), ("6-11 ans", r_611, n_611)):
            m = pd.concat([a, b], axis=1).dropna()
            if len(m):
                gap = ((m["regions"] - m["national"]) / m["national"]).abs()
                res.append(dict(scenario=sc, groupe=nom, comparaisons=len(m), ecart_moyen=round(gap.mean(), 5), ecart_max=round(gap.max(), 5)))
    return pd.DataFrame(res)


def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return
    chemin = Path(args[0])
    sortie = Path(args[1]) if len(args) > 1 and not args[1].startswith("--") else Path("02_nettoyage/projections_insd_nationales")
    p0, p1 = PAGES
    if "--pages" in args:
        a, b = args[args.index("--pages") + 1].split("-")
        p0, p1 = int(a), int(b)
    sortie.mkdir(parents=True, exist_ok=True)
    journal = [dict(gravite="INFO", message="fichier %s, SHA-256 %s" % (chemin.name, sha256(chemin)))]
    df = pd.DataFrame(extraire(lire_csv(chemin, p0, p1), journal))
    if df.empty:
        print("Aucune ligne extraite : verifiez --pages et la mise en page.")
        return
    if oc.NOTES_IGNOREES:
        journal.append(dict(gravite="ATTENTION", message="%d cellule(s) contenaient une note adressee a un assistant IA : texte ecarte, non execute" % len(oc.NOTES_IGNOREES)))
    df.to_csv(sortie / "02_nettoye_projections_nationales_long.csv", sep=";", index=False, encoding="utf-8")
    ag = df[(df.milieu == "ENSEMBLE") & df.age.astype(str).str.fullmatch(r"\d+")].copy()
    ag["age_i"] = ag.age.astype(int)
    p611 = ag[(ag.age_i >= 6) & (ag.age_i <= 11)].pivot_table(index=["scenario", "annee"], columns="sexe", values="valeur", aggfunc="sum").reset_index()
    p611.to_csv(sortie / "02_nettoye_projections_population_nationale_6_11.csv", sep=";", index=False, encoding="utf-8")
    ctrl = controler(df)
    ctrl.to_csv(sortie / "02_controles_projections_nationales.csv", sep=";", index=False, encoding="utf-8")
    pd.DataFrame(journal).to_csv(sortie / "02_journal_projections_nationales.csv", sep=";", index=False, encoding="utf-8")
    print("%d valeurs ; scenarios/tables : %s" % (len(df), sorted(set(zip(df.scenario, df.table)))))
    for j in journal:
        if j["gravite"] == "INFO" and "pages" in j["message"]:
            print("  ", j["message"])
    bad = ctrl[ctrl.ecart_relatif.abs() > TOL]
    print("Controles : %d comparaisons, %d ecart(s) > %.1f %%" % (len(ctrl), len(bad), TOL * 100))
    if len(bad):
        print(bad.groupby(["controle", "scenario"]).size().to_string())
    if "--regional" in args:
        reg = pd.read_csv(args[args.index("--regional") + 1], sep=";")
        ident = identifier_scenario(df, reg)
        ident.to_csv(sortie / "02_nettoye_projections_identification_scenario.csv", sep=";", index=False, encoding="utf-8")
        print("\nIdentification du scenario des tableaux regionaux (ecart relatif entre la somme des 13 regions et le national) :")
        print(ident.to_string(index=False))
    print("Sorties dans :", sortie.resolve())


if __name__ == "__main__":
    main()
