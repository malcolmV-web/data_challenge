# -*- coding: utf-8 -*-
"""Extrait de l'annuaire primaire CNS 530 (CSV issu du PDF) les tableaux utiles au defi 3, en format long :
  I.1 (ecoles, salles, groupes, maitres, eleves, ratio ; province x statut)
  V.2 (ecoles et salles par milieu urbain / rural et statut)
  V.4 (equipement des ecoles : eau, electricite, latrines, ...)
  VI.4.1 (nature et etat des murs des salles de classe)
  VIII.1 (historique des effectifs par province, 2015-16 a 2024-25)
Usage : python 02_nettoyage_cns530_annuaire.py CNS530_....csv [dossier_sortie] [--pages I.1=12-16 V.2=263-268 V.4=279-293 VI.4=326-349 VIII.1=380-382]
Les numeros de pages sont ceux de la colonne 'page' du CSV (pas ceux de la table des matieres).
Sorties : 02_nettoye_cns530_long.csv, 02_nettoye_cns530_referentiel_provinces.csv, 02_journal_cns530.csv, 02_controles_cns530.csv  (';' UTF-8, decimale '.')"""

import csv
import re
import sys
from collections import OrderedDict
from pathlib import Path
import pandas as pd
import sys as _sys
from pathlib import Path as _P
_sys.path.insert(0, str(_P(__file__).resolve().parents[2] / 'communs'))
import outils_communs as oc
from outils_communs import *

PAGES = {"I.1": (12, 16), "V.2": (263, 268), "V.4": (279, 293), "VI.4": (326, 349), "VIII.1": (380, 382)}
IND_I1 = ["ecoles", "salles", "groupes", "maitres", "eleves", "ratio_eleves_maitre"]
IND_V2 = [("ecoles", "PUBLIC_PRIVE"), ("salles", "PUBLIC_PRIVE"), ("ecoles", "PUBLIC"), ("salles", "PUBLIC"), ("ecoles", "PRIVE"), ("salles", "PRIVE")]
IND_V4 = ["ecoles_fonctionnelles", "eau_potable", "electricite", "latrines", "jardins_scolaires", "cantines", "terrain_sport", "clotures"]
IND_VI4_MURS = ["murs_en_dur", "murs_semi_dur", "murs_paille_banco_autre", "murs_indetermine",
                "etat_bon_acceptable", "etat_mauvais", "etat_indetermine", "salles_total"]
IND_VI4_TOIT = ["toit_tole", "toit_tuiles_ciment", "toit_banco", "toit_paille", "toit_sans_toit",
                "etat_bon_acceptable", "etat_mauvais", "etat_indetermine", "salles_total"]
TOL = 0.005


def num(c):
    return to_number(c)


def lire_csv(chemin):
    with open(chemin, encoding="utf-8-sig", newline="") as f:
        lecteur = csv.reader(f, delimiter=";")
        en_tete = next(lecteur)
        i_page, i0 = en_tete.index("page"), en_tete.index("nb_cellules") + 1
        i_ligne = en_tete.index("ligne") if "ligne" in en_tete else None
        pages = OrderedDict()
        for r in lecteur:
            cells = []
            for k, v in enumerate(r[i0:]):
                v2, note = nettoyer_cellule(v)
                if note:
                    oc.NOTES_IGNOREES.append(("csv", r[i_ligne] if i_ligne is not None else "?", k + 1))
                cells.append("" if v2 is None else str(v2).strip())
            while cells and cells[-1] == "":
                cells.pop()
            try:
                p = int(r[i_page])
            except ValueError:
                continue
            pages.setdefault(p, []).append((r[i_ligne] if i_ligne is not None else "", cells))
    return pages


def nums_fin(cells, n):
    if len(cells) >= n and all(num(c) is not None for c in cells[-n:]):
        return cells[:-n], [num(c) for c in cells[-n:]]
    return None


def lignes_section(pages, p0, p1):
    for p in range(p0, p1 + 1):
        for ligne, cells in pages.get(p, []):
            if cells:
                yield p, ligne, cells


def est_region(txt):
    n = norm_label(txt)
    return n in REGIONS_13 or bool(difflib.get_close_matches(n, REGIONS_13, n=1, cutoff=0.9))


def statut_depuis_texte(txt):
    n = norm_libre(txt)
    if re.search(r"public\s*(\+|et)\s*prive", n):
        return "PUBLIC_PRIVE"
    if "public" in n and "prive" not in n:
        return "PUBLIC"
    if "prive" in n:
        return "PRIVE"
    return None


def milieu_depuis_texte(txt):
    n = norm_libre(txt)
    return "URBAIN" if "urbain" in n else ("RURAL" if "rural" in n else None)


def rec(section, sous, p, ligne, region, province, statut, milieu, ctx, typ, ind, val, annee=None):
    return dict(section=section, sous_section=sous, page_csv=p, ligne_csv=ligne, annee_scolaire=annee or "2024-2025",
                region=region, province=province, statut=statut, milieu=milieu, contexte=ctx, type_ligne=typ,
                indicateur=ind, valeur=val)


PROV = set()   # provinces connues (remplies apres I.1) ; sert a reconnaitre les variantes d'orthographe
CORRIGEES = set()


def canon_province(n, journal=None):
    """Province reconnue (variante d'orthographe corrigee), ou None."""
    if n in PROV:
        return n
    proche = difflib.get_close_matches(n, sorted(PROV), n=1, cutoff=0.85) if PROV else []
    if proche:
        if journal is not None and (n, proche[0]) not in CORRIGEES:
            CORRIGEES.add((n, proche[0]))
            journal.append(dict(section="", gravite="INFO", message="province corrigee : '%s' -> '%s'" % (n, proche[0])))
        return proche[0]
    return None


def type_et_province(label, journal=None):
    """(type de ligne, province) ; type 'inconnu' si le libelle n'est ni une province connue ni un total."""
    n = norm_label(label)
    if n.startswith("TOTAL REGION") or n == "TOTAL":
        return "sous_total", None
    if n in NATIONAUX or n.startswith("TOTAL"):
        return "national", None
    if n.startswith("POURCENTAGE") or n.startswith("%") or "SALLES DE CLASSE" in n:
        return "pourcentage", None
    if PROV:
        c = canon_province(n, journal)
        return ("detail", c) if c else ("inconnu", n)
    return "detail", n


# ---------------------------------------------------------------- I.1
def extraire_i1(pages, journal):
    out, region, label = [], None, None
    totaux_vus, signale = set(), False
    for p, ligne, cells in lignes_section(pages, *PAGES["I.1"]):
        if len(cells) == 1:
            if num(cells[0]) is None and est_region(cells[0]):
                region, _ = normaliser_region(cells[0], journal, dict(cycle="I.1", tableau=p))
                label = None
            continue
        r = nums_fin(cells, 6)
        if r is None:
            continue
        prefix, vals = r
        if len(prefix) == 2:
            label, st = prefix
        elif len(prefix) == 1 and label is not None:
            st = prefix[0]
        else:
            continue
        statut = {"public": "PUBLIC", "prive": "PRIVE", "total": "PUBLIC_PRIVE"}.get(norm_libre(st))
        if statut is None:
            journal.append(dict(section="I.1", gravite="ATTENTION", message="statut inconnu '%s' page %s ligne %s" % (st, p, ligne)))
            continue
        typ, prov = type_et_province(label)
        if typ == "pourcentage":
            continue
        if typ == "sous_total":
            if (region, statut) in totaux_vus:      # 2e total pour la meme region : c'est le total national
                typ = "national"
                if not signale:
                    journal.append(dict(section="I.1", gravite="INFO", message="bloc de total supplementaire apres %s (page %s) traite comme total NATIONAL" % (region, p)))
                    signale = True
            else:
                totaux_vus.add((region, statut))
        for ind, v in zip(IND_I1, vals):
            out.append(rec("I.1", "I.1", p, ligne, region, prov, statut, None, "tous", typ, ind, v))
    return out


# ---------------------------------------------------------------- V.2
def extraire_v2(pages, journal):
    out, region, province, total_region, national = [], None, None, False, False
    for p, ligne, cells in lignes_section(pages, *PAGES["V.2"]):
        if len(cells) == 1:
            if num(cells[0]) is not None:
                continue
            if est_region(cells[0]):
                region, _ = normaliser_region(cells[0], journal, dict(cycle="V.2", tableau=p))
                province, total_region, national = None, False, False
            elif norm_label(cells[0]).startswith("TOTAL"):
                province, total_region, national = None, False, True
            elif not re.match(r"^(BF/|V\.|V\s*\.|INFRA|PUBLIC|NB )", cells[0].strip(), re.I):
                n = norm_label(cells[0])
                province = canon_province(n, journal) if PROV else n
                total_region, national = False, False
                if province is None:
                    journal.append(dict(section="V.2", gravite="ATTENTION", message="titre de province non reconnu page %s ligne %s : '%s'" % (p, ligne, n)))
            continue
        if len(cells) == 2 and norm_label(cells[0]) == "TOTAL" and est_region(cells[1]):
            region, _ = normaliser_region(cells[1], journal, dict(cycle="V.2", tableau=p))
            province, total_region, national = None, True, False
            continue
        r = nums_fin(cells, 6)
        if r is None or len(r[0]) != 1:
            continue
        milieu = {"urbain": "URBAIN", "rural": "RURAL", "total": "TOTAL"}.get(norm_libre(r[0][0]))
        if milieu is None:
            continue
        typ = "national" if national else ("sous_total" if total_region else "detail")
        if typ == "detail" and province is None:
            journal.append(dict(section="V.2", gravite="ATTENTION", message="ligne sans province reconnue page %s ligne %s" % (p, ligne)))
            continue
        for (ind, st), v in zip(IND_V2, r[1]):
            out.append(rec("V.2", "V.2", p, ligne, region, province, st, milieu, "tous", typ, ind, v))
    return out


# ------------------------------------------------- V.4 et VI.4 (province x 8 colonnes)
def extraire_province_ligne(pages, section, key, indicateurs, journal, sous_ok=None):
    out, region, statut, milieu, sous = [], None, None, None, None
    ignorees = 0
    for p, ligne, cells in lignes_section(pages, *PAGES[key]):
        if len(cells) == 1 and num(cells[0]) is None:
            t = cells[0]
            if est_region(t):
                region, _ = normaliser_region(t, journal, dict(cycle=section, tableau=p))
                continue
            if re.match(r"^V?I?V?\.?\s?\d?\.?\d", t.strip()) or re.match(r"^(VI?\.\d)", t.strip(), re.I):
                n = norm_libre(t)
                if section == "VI.4":
                    if "mur" in n:
                        sous = "VI.4.1"
                    elif "toiture" in n:
                        sous = "VI.4.2"
                    elif "financement" in n or "origine" in n:
                        sous = "VI.4.3"
                st, mi = statut_depuis_texte(t), milieu_depuis_texte(t)
                if st or mi:
                    statut, milieu = (st or "PUBLIC_PRIVE"), mi
            continue
        if sous_ok is not None and sous not in sous_ok:
            if nums_fin(cells, 1):
                ignorees += 1
            continue
        liste = indicateurs[sous] if isinstance(indicateurs, dict) else indicateurs
        r = nums_fin(cells, len(liste))
        if r is None or len(r[0]) != 1:
            if nums_fin(cells, 1) and len(cells) > 3:
                journal.append(dict(section=section, gravite="ATTENTION", message="ligne a %d cellules ignoree page %s ligne %s : nombre de colonnes inattendu" % (len(cells), p, ligne)))
            continue
        typ, prov = type_et_province(r[0][0], journal)
        if typ == "inconnu":
            journal.append(dict(section=section, gravite="ATTENTION", message="libelle non reconnu page %s ligne %s : '%s'" % (p, ligne, prov)))
            continue
        ctx = milieu or statut or "?"
        if statut is None and milieu is None:
            journal.append(dict(section=section, gravite="ATTENTION", message="contexte (public/prive/urbain/rural) inconnu page %s ligne %s" % (p, ligne)))
            continue
        for ind, v in zip(liste, r[1]):
            out.append(rec(section, sous or section, p, ligne, region, prov, statut, milieu, ctx, typ, ind, v))
    if ignorees:
        journal.append(dict(section=section, gravite="INFO", message="%d ligne(s) de sous-sections non extraites (%s) : a traiter apres inspection" % (ignorees, "financement")))
    return out


# ---------------------------------------------------------------- VIII.1
def extraire_viii1(pages, journal):
    """Par province : trois lignes Garcons / (PROVINCE, Filles) / Total ; le nom de la province est sur la ligne Filles."""
    out, region, annees, groupe, prov = [], None, None, [], None

    def vider():
        for (p, ligne, sexe, vals) in groupe:
            for a, v in zip(annees, vals):
                out.append(rec("VIII.1", "VIII.1", p, ligne, region, prov, "PUBLIC_PRIVE", None, "historique", "detail",
                               "eleves_" + sexe, v, annee=a[1]))

    for p, ligne, cells in lignes_section(pages, *PAGES["VIII.1"]):
        ys = [year_of(c) for c in cells]
        if sum(1 for y in ys if y) >= 8:
            annees = [y for y in ys if y]
            continue
        if annees is None:
            continue
        if len(cells) == 1:
            if num(cells[0]) is None and est_region(cells[0]):
                region, _ = normaliser_region(cells[0], journal, dict(cycle="VIII.1", tableau=p))
            continue
        r = nums_fin(cells, len(annees))
        if r is None:
            continue
        prefix, vals = r
        n0 = norm_libre(prefix[0]) if prefix else ""
        if len(prefix) == 1 and n0 == "garcons":
            groupe, prov = [(p, ligne, "garcons", vals)], None
        elif len(prefix) == 2 and norm_libre(prefix[1]) == "filles":
            groupe.append((p, ligne, "filles", vals))
            prov = norm_label(prefix[0])
            prov = (canon_province(prov, journal) if PROV else None) or prov
        elif len(prefix) == 1 and n0 == "total" and prov is not None:
            groupe.append((p, ligne, "total", vals))
            vider()
            groupe, prov = [], None
        else:
            journal.append(dict(section="VIII.1", gravite="ATTENTION", message="ligne inattendue page %s ligne %s : %s" % (p, ligne, prefix[:2])))
    return out


# ---------------------------------------------------------------- controles
def comparer(nom, a, b, cles, col_a="a", col_b="b"):
    if a.empty or b.empty:
        return pd.DataFrame()
    sa = a.groupby(cles, dropna=False)["valeur"].sum().rename(col_a)
    sb = b.groupby(cles, dropna=False)["valeur"].sum().rename(col_b)
    m = pd.concat([sa, sb], axis=1).dropna().reset_index()
    m["controle"] = nom
    m["ecart_relatif"] = (m[col_a] - m[col_b]) / m[col_b].replace(0, pd.NA)
    return m


COMPTAGES_I1 = ["ecoles", "salles", "groupes", "maitres", "eleves"]


def controler(df):
    res = []
    f = df.fillna({"province": "-", "region": "-", "statut": "-", "milieu": "-", "contexte": "-"})
    i1 = f[(f.section == "I.1") & f.indicateur.isin(COMPTAGES_I1)]
    det, sub = i1[i1.type_ligne == "detail"], i1[i1.type_ligne == "sous_total"]
    res.append(comparer("I.1 somme des provinces = Total Region", det, sub, ["region", "statut", "indicateur"]))
    pub, priv, tot = [det[det.statut == s] for s in ("PUBLIC", "PRIVE", "PUBLIC_PRIVE")]
    cles = ["region", "province", "indicateur"]
    res.append(comparer("I.1 Public + Prive = Total (province)", pd.concat([pub, priv]), tot, cles))
    v2 = f[(f.section == "V.2")]
    d2, s2 = v2[v2.type_ligne == "detail"], v2[v2.type_ligne == "sous_total"]
    res.append(comparer("V.2 Urbain + Rural = Total (province)", d2[d2.milieu != "TOTAL"], d2[d2.milieu == "TOTAL"], ["region", "province", "statut", "indicateur"]))
    res.append(comparer("V.2 somme des provinces = Total Region", d2[d2.milieu == "TOTAL"], s2[s2.milieu == "TOTAL"], ["region", "statut", "indicateur"]))
    x = d2[(d2.milieu == "TOTAL")]
    ii = i1[(i1.type_ligne == "detail") & i1.indicateur.isin(["ecoles", "salles"])]
    res.append(comparer("V.2 Total = I.1 (ecoles, salles par province et statut)", x, ii, ["region", "province", "statut", "indicateur"]))
    for sec in ("V.4", "VI.4"):
        s = f[(f.section == sec) & (f.type_ligne.isin(["detail", "sous_total"]))]
        res.append(comparer("%s somme des provinces = Total Region" % sec, s[s.type_ligne == "detail"], s[s.type_ligne == "sous_total"], ["region", "contexte", "indicateur"]))
    for sous, liste, cuts in (("VI.4.1", IND_VI4_MURS, (("murs (4 modalites)", slice(0, 4)), ("etat (3 modalites)", slice(4, 7)))),
                              ("VI.4.2", IND_VI4_TOIT, (("toitures (5 modalites)", slice(0, 5)), ("etat (3 modalites)", slice(5, 8))))):
        m = f[(f.section == "VI.4") & (f.sous_section == sous) & (f.type_ligne == "detail")]
        if m.empty:
            continue
        p = m.pivot_table(index=["region", "province", "contexte"], columns="indicateur", values="valeur", aggfunc="sum")
        if "salles_total" in p.columns:
            for nom, cut in cuts:
                q = p[liste[cut]].sum(axis=1).rename("a")
                t = p["salles_total"].rename("b")
                mm = pd.concat([q, t], axis=1).dropna().reset_index()
                mm["controle"] = "%s %s = salles" % (sous, nom)
                mm["ecart_relatif"] = (mm["a"] - mm["b"]) / mm["b"].replace(0, pd.NA)
                res.append(mm)
    mu = f[(f.section == "VI.4") & (f.sous_section == "VI.4.1") & (f.type_ligne == "detail") & (f.indicateur == "salles_total")]
    to = f[(f.section == "VI.4") & (f.sous_section == "VI.4.2") & (f.type_ligne == "detail") & (f.indicateur == "salles_total")]
    res.append(comparer("VI.4.1 salles = VI.4.2 salles (province, contexte)", mu, to, ["region", "province", "contexte"]))
    h = f[f.section == "VIII.1"]
    if len(h):
        pv = h.pivot_table(index=["region", "province", "annee_scolaire"], columns="indicateur", values="valeur", aggfunc="sum").reset_index()
        if {"eleves_garcons", "eleves_filles", "eleves_total"} <= set(pv.columns):
            pv["a"], pv["b"] = pv["eleves_garcons"] + pv["eleves_filles"], pv["eleves_total"]
            pv["controle"] = "VIII.1 Garcons + Filles = Total"
            pv["ecart_relatif"] = (pv["a"] - pv["b"]) / pv["b"].replace(0, pd.NA)
            res.append(pv[["region", "province", "annee_scolaire", "a", "b", "controle", "ecart_relatif"]])
        last = h[(h.annee_scolaire == "2024-2025") & (h.indicateur == "eleves_total")]
        eleves = i1[(i1.type_ligne == "detail") & (i1.statut == "PUBLIC_PRIVE") & (i1.indicateur == "eleves")]
        res.append(comparer("VIII.1 (2024-2025) = I.1 eleves (province)", last, eleves, ["region", "province"]))
    res = [r for r in res if len(r)]
    return pd.concat(res, ignore_index=True) if res else pd.DataFrame()


def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return
    chemin = Path(args[0])
    sortie = Path(args[1]) if len(args) > 1 and "=" not in args[1] else Path("02_nettoyage/cns530_annuaire_2024-25")
    for a in args:
        if "=" in a and re.match(r"^[IVX]+\.\d+(\.\d+)?=\d+-\d+$", a):
            k, v = a.split("=")
            PAGES[k] = tuple(int(x) for x in v.split("-"))
    sortie.mkdir(parents=True, exist_ok=True)
    journal = [dict(section="", gravite="INFO", message="fichier %s, SHA-256 %s" % (chemin.name, sha256(chemin)))]
    pages = lire_csv(chemin)
    recs = []
    recs += extraire_i1(pages, journal)
    PROV.update(r["province"] for r in recs if r["type_ligne"] == "detail" and r["province"])
    recs += extraire_v2(pages, journal)
    recs += extraire_province_ligne(pages, "V.4", "V.4", IND_V4, journal)
    recs += extraire_province_ligne(pages, "VI.4", "VI.4", {"VI.4.1": IND_VI4_MURS, "VI.4.2": IND_VI4_TOIT}, journal, sous_ok={"VI.4.1", "VI.4.2"})
    recs += extraire_viii1(pages, journal)
    df = pd.DataFrame(recs)
    if df.empty:
        print("Aucune ligne extraite : verifiez les numeros de pages (--pages) et le fichier.")
        return
    ref = df[(df.section == "I.1") & (df.type_ligne == "detail")][["region", "province"]].drop_duplicates()
    if len(ref) != 45 or ref.region.nunique() != 13:
        journal.append(dict(section="I.1", gravite="ATTENTION", message="referentiel : %d provinces dans %d regions (attendu 45 et 13)" % (len(ref), ref.region.nunique())))
    inconnues = sorted(set(df[(df.type_ligne == "detail") & df.province.notna()].province) - set(ref.province))
    if inconnues:
        journal.append(dict(section="", gravite="ATTENTION", message="provinces absentes de I.1 : %s" % inconnues[:10]))
    if oc.NOTES_IGNOREES:
        journal.append(dict(section="", gravite="ATTENTION", message="%d cellule(s) contenaient une note adressee a un assistant IA : texte ecarte, non execute" % len(oc.NOTES_IGNOREES)))
    for sec, grp in df.groupby("section"):
        journal.append(dict(section=sec, gravite="INFO", message="%d valeurs, %d provinces, pages %s-%s" % (
            len(grp), grp.province.nunique(), grp.page_csv.min(), grp.page_csv.max())))
    df.to_csv(sortie / "02_nettoye_cns530_long.csv", sep=";", index=False, encoding="utf-8")
    ref.sort_values(["region", "province"]).to_csv(sortie / "02_nettoye_cns530_referentiel_provinces.csv", sep=";", index=False, encoding="utf-8")
    ctrl = controler(df)
    ctrl.to_csv(sortie / "02_controles_cns530.csv", sep=";", index=False, encoding="utf-8")
    pd.DataFrame(journal).to_csv(sortie / "02_journal_cns530.csv", sep=";", index=False, encoding="utf-8")
    print("%d valeurs extraites ; %d provinces dans %d regions." % (len(df), len(ref), ref.region.nunique()))
    print("Journal : %d ATTENTION" % sum(1 for j in journal if j["gravite"] == "ATTENTION"))
    if len(ctrl):
        bad = ctrl[ctrl.ecart_relatif.abs() > TOL]
        print("Controles : %d comparaisons, %d ecart(s) > %.1f %%" % (len(ctrl), len(bad), TOL * 100))
        print(bad.groupby("controle").size().to_string() if len(bad) else "aucun ecart")
    print("Sorties dans :", sortie.resolve())


if __name__ == "__main__":
    main()
