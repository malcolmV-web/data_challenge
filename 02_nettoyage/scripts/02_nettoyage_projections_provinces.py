# -*- coding: utf-8 -*-
"""Extrait des projections demographiques INSD 2020-2035 (RGPH 2019, vol. 4 ; CSV issu du PDF) la population par
region et par province, annee civile, sexe et groupe d'ages. Sortie en format long + population cible (6-11 ans).

Mise en page attendue (a verifier avec le journal) : une page de donnees = un titre (« Region de ... » ou nom de province),
puis deux blocs superposes ; chaque bloc : ligne d'annees (3 annees), ligne Homme | Femme | Ensemble, puis une ligne par
groupe d'ages (« 0 an », « 1 - 4 ans », « 6 -11 ans », ...) avec 3 valeurs par annee. Le dernier bloc peut n'avoir qu'une annee.

Usage : python 02_nettoyage_projections_provinces.py INSD_RGPH2019_Vol4_Projections_demographiques_2020-2035.csv [dossier_sortie]
        [--referentiel 02_nettoyage/cns530_annuaire_2024-25/02_nettoye_cns530_referentiel_provinces.csv] [--pages 131-520]
Sorties : 02_nettoye_projections_provinces_long.csv, 02_nettoye_projections_population_cible_province.csv, 02_nettoye_projections_population_cible_region.csv, 02_journal_projections_provinces.csv,
          02_controles_projections_provinces.csv  (';' UTF-8, decimale '.')"""

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

PAGES = (131, 520)
PROVINCES_REGION = {
    "BOUCLE DU MOUHOUN": ["BANWA", "KOSSI", "LES BALE", "MOUHOUN", "NAYALA", "SOUROU"],
    "CASCADES": ["COMOE", "LERABA"], "CENTRE": ["KADIOGO"],
    "CENTRE EST": ["BOULGOU", "KOULPELOGO", "KOURITTENGA"], "CENTRE NORD": ["BAM", "NAMENTENGA", "SANMATENGA"],
    "CENTRE OUEST": ["BOULKIEMDE", "SANGUIE", "SISSILI", "ZIRO"], "CENTRE SUD": ["BAZEGA", "NAHOURI", "ZOUNDWEOGO"],
    "EST": ["GNAGNA", "GOURMA", "KOMONDJARI", "KOMPIENGA", "TAPOA"], "HAUTS BASSINS": ["HOUET", "KENEDOUGOU", "TUY"],
    "NORD": ["LOROUM", "PASSORE", "YATENGA", "ZONDOMA"], "PLATEAU CENTRAL": ["GANZOURGOU", "KOURWEOGO", "OUBRITENGA"],
    "SAHEL": ["OUDALAN", "SENO", "SOUM", "YAGHA"], "SUD OUEST": ["BOUGOURIBA", "IOBA", "NOUMBIEL", "PONI"]}
ALIAS = {"BALES": "LES BALE", "BALE": "LES BALE"}
SEXE = {"homme": "Garcons", "femme": "Filles", "ensemble": "Total"}
TOL = 0.005
PROV_REG = {}


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


def age_label(txt):
    n = norm_libre(txt).replace(" ", "")
    m = re.match(r"^(\d+)-(\d+)ans?$", n)
    if m:
        return "%d-%d" % (int(m.group(1)), int(m.group(2)))
    m = re.match(r"^(\d+)ans?(et\+|etplus|\+)$", n)
    if m:
        return "%d+" % int(m.group(1))
    m = re.match(r"^(\d+)ans?$", n)
    if m:
        return "%d" % int(m.group(1))
    if n in ("total", "ensemble", "tousages"):
        return "TOTAL"
    return None


def entite(txt, journal=None):
    """('region', nom) ou ('province', nom) ou None."""
    n = norm_label(txt)
    m = re.match(r"^REGION (?:DU |DE LA |DES |DE L |DE |D )?(.+)$", n)
    if m:
        cand = m.group(1)
        if cand in REGIONS_13:
            return "region", cand
        p = difflib.get_close_matches(cand, REGIONS_13, n=1, cutoff=0.88)
        return ("region", p[0]) if p else None
    m = re.match(r"^PROVINCE (?:DU |DE LA |DES |DE L |DE |D )?(.+)$", n)
    if m:
        n = m.group(1)
    n = ALIAS.get(n, n)
    if n in PROV_REG:
        return "province", n
    p = difflib.get_close_matches(n, list(PROV_REG), n=1, cutoff=0.85)
    if p:
        if journal is not None and (n, p[0]) not in oc.__dict__.setdefault("_CORR", set()):
            oc._CORR.add((n, p[0]))
            journal.append(dict(gravite="INFO", message="province corrigee : '%s' -> '%s'" % (n, p[0])))
        return "province", p[0]
    return None


def extraire(rows, journal):
    out, ent, annees = [], None, None
    ignorees = 0
    for p, ligne, cells in rows:
        if len(cells) == 1:
            y = year_of(cells[0])
            if y and ent is not None:              # bloc a une seule annee : l'annee est seule sur sa ligne (ex. 2035)
                annees = [y[0]]
                continue
            e = entite(cells[0], journal)
            if e:
                ent, annees = e, None
            continue
        ys = [year_of(c) for c in cells]
        if any(ys) and all(y is not None or re.match(r"^groupes?\s*d.?\s*a?g?es?$", norm_libre(c).replace("â", "a")) or norm_libre(c).startswith("groupes") for y, c in zip(ys, cells)):
            annees = [y[0] for y in ys if y]
            continue
        if ent is None or annees is None:
            continue
        lab = age_label(cells[0])
        if lab is None:
            continue
        nums = cells[1:]
        vals = [to_number(c) for c in nums]
        if len(vals) != 3 * len(annees) or any(v is None for v in vals):
            ignorees += 1
            journal.append(dict(gravite="ATTENTION", message="ligne '%s' page %s ligne %s : %d valeurs au lieu de %d (annees %s)" % (cells[0], p, ligne, len(vals), 3 * len(annees), annees)))
            continue
        for k, a in enumerate(annees):
            for j, sx in enumerate(("Garcons", "Filles", "Total")):
                kind, nom = ent
                if kind == "province":
                    region, province = PROV_REG[nom], nom
                else:
                    region, province = nom, None
                out.append(dict(niveau=kind, region=region, province=province, annee=a, sexe=sx, groupe_age=lab,
                                valeur=vals[3 * k + j], page_csv=p, ligne_csv=ligne))
    return out


def controler(df):
    res = []
    d = df.copy()
    d["province"] = d["province"].fillna("-")
    # Garcons + Filles = Total
    p = d.pivot_table(index=["niveau", "region", "province", "annee", "groupe_age"], columns="sexe", values="valeur", aggfunc="sum").reset_index()
    if {"Garcons", "Filles", "Total"} <= set(p.columns):
        p["a"], p["b"] = p["Garcons"] + p["Filles"], p["Total"]
        p["controle"] = "Garcons + Filles = Total"
        p["ecart_relatif"] = (p["a"] - p["b"]) / p["b"].replace(0, pd.NA)
        res.append(p[["niveau", "region", "province", "annee", "groupe_age", "a", "b", "controle", "ecart_relatif"]])
    # somme des provinces = region
    pr = d[d.niveau == "province"].groupby(["region", "annee", "sexe", "groupe_age"])["valeur"].sum().rename("a")
    rg = d[d.niveau == "region"].groupby(["region", "annee", "sexe", "groupe_age"])["valeur"].sum().rename("b")
    m = pd.concat([pr, rg], axis=1).dropna().reset_index()
    if len(m):
        m["controle"] = "somme des provinces = region"
        m["niveau"], m["province"] = "region", "-"
        m["ecart_relatif"] = (m["a"] - m["b"]) / m["b"].replace(0, pd.NA)
        res.append(m)
    return pd.concat(res, ignore_index=True) if res else pd.DataFrame()


def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return
    chemin = Path(args[0])
    sortie = Path(args[1]) if len(args) > 1 and not args[1].startswith("--") else Path("02_nettoyage/projections_insd_provinces_2020-2035")
    p0, p1 = PAGES
    ref = None
    if "--pages" in args:
        a, b = args[args.index("--pages") + 1].split("-")
        p0, p1 = int(a), int(b)
    if "--referentiel" in args:
        ref = pd.read_csv(args[args.index("--referentiel") + 1], sep=";")
        for _, r in ref.iterrows():
            PROV_REG[norm_label(r["province"])] = norm_label(r["region"])
    else:
        for rg, provs in PROVINCES_REGION.items():
            for pv in provs:
                PROV_REG[pv] = rg
    sortie.mkdir(parents=True, exist_ok=True)
    journal = [dict(gravite="INFO", message="fichier %s, SHA-256 %s" % (chemin.name, sha256(chemin)))]
    rows = lire_csv(chemin, p0, p1)
    recs = extraire(rows, journal)
    df = pd.DataFrame(recs)
    if df.empty:
        print("Aucune ligne extraite : verifiez --pages et la mise en page (pages de donnees, titres).")
        return
    nr, npv = df[df.niveau == "region"].region.nunique(), df[df.niveau == "province"].province.nunique()
    if nr != 13 or npv != 45:
        journal.append(dict(gravite="ATTENTION", message="%d regions et %d provinces extraites (attendu 13 et 45)" % (nr, npv)))
    for niv in ("region", "province"):
        s = df[df.niveau == niv]
        cle = "region" if niv == "region" else "province"
        incompl = [e for e, g in s.groupby(cle) if g.annee.nunique() != 16]
        if incompl:
            journal.append(dict(gravite="ATTENTION", message="%s sans les 16 annees 2020-2035 : %s" % (niv, incompl[:10])))
    if oc.NOTES_IGNOREES:
        journal.append(dict(gravite="ATTENTION", message="%d cellule(s) contenaient une note adressee a un assistant IA : texte ecarte, non execute" % len(oc.NOTES_IGNOREES)))
    df.to_csv(sortie / "02_nettoye_projections_provinces_long.csv", sep=";", index=False, encoding="utf-8")
    ctrl = controler(df)
    alertes = set()
    if len(ctrl):
        for _, r in ctrl[ctrl.ecart_relatif.abs() > TOL].iterrows():
            alertes.add((r["niveau"], r["region"], r["province"] if isinstance(r["province"], str) else "-", int(r["annee"])))
    cible = df[df.groupe_age.isin(["3-5", "6-11", "12-15"])]
    for niv, cle in (("province", ["region", "province"]), ("region", ["region"])):
        t = cible[cible.niveau == niv].pivot_table(index=cle + ["annee"], columns=["groupe_age", "sexe"], values="valeur", aggfunc="sum")
        t.columns = ["pop_%s_%s" % (a.replace("-", "_"), s.lower()) for a, s in t.columns]
        for a in ("3_5", "6_11", "12_15"):
            g, f_, tp = "pop_%s_garcons" % a, "pop_%s_filles" % a, "pop_%s_total" % a
            if {g, f_, tp} <= set(t.columns):
                t = t.rename(columns={tp: tp + "_publie"})
                t[tp] = t[g] + t[f_]                      # total retenu = garcons + filles
                t["ecart_total_publie_" + a] = (t[tp + "_publie"] - t[tp]) / t[tp]
        t = t.reset_index()
        t["alerte_controle"] = [int((niv, r.region, getattr(r, "province", "-"), int(r.annee)) in alertes or
                                    ("region", r.region, "-", int(r.annee)) in alertes) for r in t.itertuples()]
        t.to_csv(sortie / ("02_nettoye_projections_population_cible_%s.csv" % niv), sep=";", index=False, encoding="utf-8")
    ctrl.to_csv(sortie / "02_controles_projections_provinces.csv", sep=";", index=False, encoding="utf-8")
    pd.DataFrame(journal).to_csv(sortie / "02_journal_projections_provinces.csv", sep=";", index=False, encoding="utf-8")
    print("%d valeurs ; %d regions, %d provinces, annees %s-%s ; groupes d'ages : %d" % (
        len(df), nr, npv, int(df.annee.min()), int(df.annee.max()), df.groupe_age.nunique()))
    print("Journal : %d ATTENTION" % sum(1 for j in journal if j["gravite"] == "ATTENTION"))
    if len(ctrl):
        bad = ctrl[ctrl.ecart_relatif.abs() > TOL]
        print("Controles : %d comparaisons, %d ecart(s) > %.1f %%" % (len(ctrl), len(bad), TOL * 100))
        print(bad.groupby("controle").size().to_string() if len(bad) else "aucun ecart")
    print("Groupes d'ages lus :", sorted(df.groupe_age.unique(), key=lambda x: (x == "TOTAL", int(re.match(r"\d+", x).group()) if re.match(r"\d+", x) else 999))[:30])
    print("Sorties dans :", sortie.resolve())


if __name__ == "__main__":
    main()
