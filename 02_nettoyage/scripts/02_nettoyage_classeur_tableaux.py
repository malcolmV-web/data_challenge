# -*- coding: utf-8 -*-
"""Etape 1 (02_nettoyage) : transforme chaque 'Tableau N' du classeur en format long + controles.
Usage : python 02_nettoyage_classeur_tableaux.py classeur.xlsx [dossier_sortie]
Sorties : 02_nettoye_classeur_tableaux_long.csv, 02_nettoye_classeur_inventaire_tableaux.csv, 02_journal_classeur.csv, 02_controles_classeur_totaux.csv
Format : separateur ';', UTF-8, decimale '.'"""

import re
import sys
from pathlib import Path
import openpyxl
import pandas as pd
import sys as _sys
from pathlib import Path as _P
_sys.path.insert(0, str(_P(__file__).resolve().parents[2] / 'communs'))
import outils_communs as oc
from outils_communs import *

DIMS = ["region", "province", "commune", "statut", "milieu", "niveau_etudes"]
TAUX = ("TBA", "TBS", "TAUX_ACHEVEMENT", "TAUX_REUSSITE_CEP")
TOLERANCE = 0.005  # 0,5 %


def main():
    chemin = Path(sys.argv[1])
    sortie = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("02_nettoyage/classeur_primaire_2016-2025")
    sortie.mkdir(parents=True, exist_ok=True)
    wb = openpyxl.load_workbook(chemin, data_only=True)
    journal, inventaire, recs = [], [], []
    journal.append(dict(cycle="", tableau="", gravite="INFO", message="fichier %s, SHA-256 %s" % (chemin.name, sha256(chemin))))
    vus, precedent = set(), None
    for ws in wb.worksheets:
        rows = lire_feuille(ws)
        titres = trouver_titres(rows)
        for n, (i, num, titre) in enumerate(titres):
            fin = titres[n + 1][0] if n + 1 < len(titres) else len(rows)
            cycle = cycle_de(titre, ws.title, precedent)
            precedent = cycle
            ctx = dict(cycle=cycle, tableau=num)
            b = analyser_bloc(rows, i, fin)
            if b["vide"]:
                journal.append(dict(**ctx, gravite="INFO", message="titre sans donnees (sommaire ?) feuille '%s' ligne %d" % (ws.title, i + 1)))
                continue
            if (cycle, num) in vus:
                journal.append(dict(**ctx, gravite="ATTENTION", message="tableau deja lu ailleurs : doublon ignore (feuille '%s')" % ws.title))
                continue
            vus.add((cycle, num))
            indic = indicateur_de(titre)
            if indic == "INCONNU":
                journal.append(dict(**ctx, gravite="ATTENTION", message="indicateur non reconnu dans le titre : %s" % titre))
            cols_label, dims, col_dim, msgs = dimensions_bloc(b, titre)
            for g, m in msgs:
                journal.append(dict(**ctx, gravite=g, message=m))
            sans_annee = [j for j, c in b["colonnes"].items() if c["annee"] is None]
            if sans_annee and not b["annee_en_ligne"]:
                journal.append(dict(**ctx, gravite="ATTENTION", message="%d colonne(s) de valeurs sans annee reconnue : colonnes %s" % (len(sans_annee), [j + 1 for j in sans_annee][:8])))
            conv = bool(re.search(r"\d{4}\s*/\s*\d{4}", titre))
            conv_signale = False
            inventaire.append(dict(feuille=ws.title, cycle=cycle, tableau=num, indicateur=indic, titre=titre, ligne_titre=i + 1,
                                   lignes_donnees=len(b["donnees"]), colonnes_valeurs=len(b["cols_valeur"]),
                                   lignes_entete=len(b["entetes"]), dimensions_lignes=",".join(dims)))
            memo = {}
            for k, r, groupe in b["donnees"]:
                an_ligne = None
                for j in b["cols_label"]:
                    v = r[j] if j < len(r) else None
                    if not vide(v):
                        memo[j] = str(v).strip() if not isinstance(v, (int, float)) else v
                        for jj in b["cols_label"]:      # un nouveau libelle remet a zero les niveaux plus profonds
                            if jj > j:
                                memo[jj] = None
                    else:
                        memo.setdefault(j, None)
                    if j in b["annee_en_ligne"] and memo.get(j) is not None:
                        an_ligne = year_of(memo[j])
                valeurs_dim, types = {}, []
                for d, j in zip(dims, cols_label):
                    lib = memo.get(j)
                    if lib is None:
                        valeurs_dim[d] = None
                        continue
                    val, typ = classer_label(d, lib)
                    types.append(typ)
                    if d == "region" and typ != "national":
                        val, ok = normaliser_region(val, journal, ctx)
                        if not ok:
                            journal.append(dict(**ctx, gravite="ATTENTION", message="region non reconnue ligne %d : '%s'" % (k + 1, lib)))
                    valeurs_dim[d] = val
                type_ligne = "national" if "national" in types else ("sous_total" if "sous_total" in types else "detail")
                for j in b["cols_valeur"]:
                    v = r[j] if j < len(r) else None
                    if vide(v):
                        continue
                    val = to_number(v)
                    if val is None:
                        journal.append(dict(**ctx, gravite="INFO", message="valeur non numerique ignoree ligne %d colonne %d : '%s'" % (k + 1, j + 1, str(v)[:15])))
                        continue
                    c = b["colonnes"][j]
                    an = c["annee"] or an_ligne
                    converti = 0
                    if an and an[2] == "annee_civile" and conv:
                        an = (an[0] - 1, "%d-%d" % (an[0] - 1, an[0]), "annee_scolaire")
                        converti = 1
                        if not conv_signale:
                            journal.append(dict(**ctx, gravite="INFO", message="annees d'en-tete a une seule valeur lues comme annee de FIN de l'annee scolaire (2016 -> 2015-2016) d'apres le titre : a confirmer"))
                            conv_signale = True
                    rec = dict(cycle=cycle, tableau=num, indicateur=indic, feuille=ws.title, ligne_source=k + 1,
                               annee_debut=an[0] if an else None, annee_libelle=an[1] if an else None,
                               type_periode=an[2] if an else None, annee_convertie=converti,
                               sexe=c["sexe"], colonne_autre=c["autre"], type_ligne=type_ligne)
                    for d in DIMS:
                        rec[d] = None
                    for d, x in valeurs_dim.items():
                        if d == "sexe":
                            rec["sexe"] = x
                        else:
                            rec[d] = x
                    if col_dim and c["autre"]:
                        rec[col_dim] = norm_label(c["autre"])
                    rec["valeur"] = val
                    recs.append(rec)
    df = pd.DataFrame(recs)
    if oc.NOTES_IGNOREES:
        journal.append(dict(cycle="", tableau="", gravite="ATTENTION",
                            message="%d cellule(s) contenaient une note adressee a un assistant IA : texte ecarte, non execute (feuille, ligne, colonne) : %s"
                                    % (len(oc.NOTES_IGNOREES), oc.NOTES_IGNOREES[:20])))
    df.to_csv(sortie / "02_nettoye_classeur_tableaux_long.csv", sep=";", index=False, encoding="utf-8")
    pd.DataFrame(inventaire).to_csv(sortie / "02_nettoye_classeur_inventaire_tableaux.csv", sep=";", index=False, encoding="utf-8")
    controles = controler(df)
    controles.to_csv(sortie / "02_controles_classeur_totaux.csv", sep=";", index=False, encoding="utf-8")
    pd.DataFrame(journal).to_csv(sortie / "02_journal_classeur.csv", sep=";", index=False, encoding="utf-8")
    nb_att = sum(1 for x in journal if x["gravite"] == "ATTENTION")
    print("%d tableaux lus, %d valeurs, %d attention(s) dans le journal." % (len(inventaire), len(df), nb_att))
    if len(controles):
        print("Controles : %d ligne(s) comparee(s), %d ecart(s) au-dessus de %.1f %% -> 02_controles_classeur_totaux.csv" % (
            len(controles), int((controles["ecart_relatif"].abs() > TOLERANCE).sum()), TOLERANCE * 100))
    print("Sorties dans :", sortie.resolve())


def controler(df):
    """Comptages seulement : somme des details = total (region/national, statut, milieu, niveau) ; filles + garcons = total."""
    if df.empty:
        return pd.DataFrame()
    cpt = df[~df["indicateur"].str.startswith("IPS") & ~df["indicateur"].isin(TAUX)].copy()
    dimcols = [c for c in DIMS if c in cpt.columns]
    base = ["cycle", "tableau", "indicateur", "annee_debut", "sexe", "colonne_autre"]
    for c in base + dimcols:
        cpt[c] = cpt[c].fillna("-")
    TOT = {"TOTAL", "NATIONAL"}
    res = []
    for (cycle, tab), sub in cpt.groupby(["cycle", "tableau"]):
        for dim in dimcols:
            if (sub[dim] == "-").all():
                continue
            det = sub[(sub["type_ligne"] == "detail") & (sub[dim] != "-") & ~sub[dim].isin(TOT)]
            tot = sub[sub[dim].isin(TOT) | ((sub["type_ligne"] != "detail") & (sub[dim] == "-"))]
            cles = [c for c in base + dimcols if c != dim]
            if det.empty or tot.empty:
                continue
            s = det.groupby(cles)["valeur"].sum().rename("somme_details")
            t = tot.groupby(cles)["valeur"].first().rename("ligne_total")
            m = pd.concat([s, t], axis=1).dropna().reset_index()
            m["controle"] = "somme_%s_vs_total" % dim
            m["ecart_relatif"] = (m["somme_details"] - m["ligne_total"]) / m["ligne_total"].replace(0, pd.NA)
            res.append(m)
    sx = cpt[cpt["sexe"] != "-"]
    if len(sx):
        idx = [c for c in base if c != "sexe"] + dimcols + ["type_ligne"]
        p = sx.pivot_table(index=idx, columns="sexe", values="valeur", aggfunc="sum").reset_index()
        if {"Total", "Filles", "Garcons"} <= set(p.columns):
            p = p.dropna(subset=["Total", "Filles", "Garcons"])
            p["controle"] = "filles_plus_garcons_vs_total"
            p["ecart_relatif"] = (p["Filles"] + p["Garcons"] - p["Total"]) / p["Total"].replace(0, pd.NA)
            res.append(p)
    return pd.concat(res, ignore_index=True) if res else pd.DataFrame()


if __name__ == "__main__":
    main()
