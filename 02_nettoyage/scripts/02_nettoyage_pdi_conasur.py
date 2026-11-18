# -*- coding: utf-8 -*-
"""Agrege par province de l'ancien decoupage la situation des PDI (CONASUR, communes d'accueil, 31 decembre 2022).
Le CSV (issu d'Excel) porte des NOMS (region, province, commune) et pas de P-codes : les provinces sont rapprochees du referentiel
du CNS 530 (alias 'BALE' -> 'LES BALE', variantes proches corrigees). Controle : somme des communes par region = total par region du
feuillet STATISTIQUES.

Usage : python 02_nettoyage_pdi_conasur.py situation-...-31-decembre-2022-1__31122022.csv 02_nettoyage/cns530_annuaire_2024-25/02_nettoye_cns530_referentiel_provinces.csv
        [--stats situation-...-31-decembre-2022-1__STATISTIQUES.csv] [dossier_sortie]
Sorties : 02_nettoye_pdi_conasur_province_2022-12.csv, 02_controles_pdi_conasur_regions.csv, 02_journal_pdi_conasur.csv"""

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

csv.field_size_limit(10 ** 8)
ALIAS = {"BALE": "LES BALE", "BALES": "LES BALE"}


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
    return rows


def main():
    args = sys.argv[1:]
    if len(args) < 2:
        print(__doc__)
        return
    sortie = Path([a for a in args[2:] if not a.startswith("--") and not a.endswith(".csv")][-1]) if [a for a in args[2:] if not a.startswith("--") and not a.endswith(".csv")] else Path("02_nettoyage/pdi_conasur_2022-12")
    sortie.mkdir(parents=True, exist_ok=True)
    journal = []
    ref = pd.read_csv(args[1], sep=";")
    ref_prov = {norm_label(p): norm_label(r) for p, r in zip(ref.province, ref.region)}
    rows = lire(args[0])
    h = next(k for k, r in enumerate(rows[:15]) if any(norm_libre(c) == "provinces" for c in r))
    en_tete = [norm_libre(c) for c in rows[h]]
    def col(*mots):
        return next(i for i, c in enumerate(en_tete) if all(m in c for m in mots))
    i_reg, i_prov, i_com = col("regions"), col("provinces"), col("communes")
    i_h, i_f = col("hommes"), col("femmes")
    i_e5, i_e6, i_te, i_tot = col("moins de 5"), col("plus de 5"), col("total enfants"), col("nombre total")
    data = []
    non_apparies = {}
    for r in rows[h + 1:]:
        r = r + [""] * (len(en_tete) - len(r))
        prov, com = r[i_prov], r[i_com]
        if not prov or not com or prov.startswith("#") or norm_libre(prov).startswith("total"):
            continue
        n = ALIAS.get(norm_label(prov), norm_label(prov))
        if n not in ref_prov:
            p = difflib.get_close_matches(n, list(ref_prov), n=1, cutoff=0.85)
            if not p:
                non_apparies[prov] = non_apparies.get(prov, 0) + 1
                continue
            n = p[0]
        data.append(dict(region_source=norm_label(r[i_reg]), province=n, region=ref_prov[n], commune=norm_label(com),
                         hommes=to_number(r[i_h]), femmes=to_number(r[i_f]), enfants_moins5=to_number(r[i_e5]),
                         enfants_plus5=to_number(r[i_e6]), enfants_total=to_number(r[i_te]), pdi_total=to_number(r[i_tot])))
    d = pd.DataFrame(data)
    if non_apparies:
        journal.append(dict(gravite="ATTENTION", message="provinces non appariees (lignes ignorees) : %s" % non_apparies))
    manq = int(d[["pdi_total"]].isna().sum().sum())
    if manq:
        journal.append(dict(gravite="ATTENTION", message="%d communes sans total de PDI (comptees 0)" % manq))
    incoh = d[d.region_source != d.region]
    if len(incoh):
        journal.append(dict(gravite="ATTENTION", message="%d lignes dont la region du fichier differe de la region du referentiel (ex. %s)" % (len(incoh), sorted(set(incoh.province))[:5])))
    d = d.fillna({"pdi_total": 0, "enfants_total": 0, "hommes": 0, "femmes": 0, "enfants_moins5": 0, "enfants_plus5": 0})
    d["incoh_total"] = (d.hommes + d.femmes + d.enfants_total - d.pdi_total).abs() > 0.5
    prov = d.groupby(["region", "province"]).agg(communes_accueil=("commune", "nunique"), pdi_total=("pdi_total", "sum"),
                                                 pdi_enfants=("enfants_total", "sum"), pdi_hommes=("hommes", "sum"),
                                                 pdi_femmes=("femmes", "sum")).reset_index()
    toutes = pd.DataFrame({"province": sorted(ref_prov), "region": [ref_prov[p] for p in sorted(ref_prov)]})
    prov = toutes.merge(prov, on=["region", "province"], how="left").fillna(0)
    prov["situation"] = "2022-12-31"
    prov.to_csv(sortie / "02_nettoye_pdi_conasur_province_2022-12.csv", sep=";", index=False, encoding="utf-8")
    journal.append(dict(gravite="INFO", message="%d communes d'accueil, %d provinces avec PDI sur 45" % (d.commune.nunique(), int((prov.pdi_total > 0).sum()))))
    journal.append(dict(gravite="INFO", message="%d communes dont hommes + femmes + enfants differe du total (ecart > 0,5)" % int(d.incoh_total.sum())))
    # controle regions
    if "--stats" in args:
        st = lire(args[args.index("--stats") + 1])
        hs = next(k for k, r in enumerate(st[:8]) if any(norm_libre(c).startswith("region") for c in r))
        lignes = []
        for r in st[hs + 1:]:
            if len(r) >= 2 and r[0] and to_number(r[1]) is not None:
                lignes.append((norm_label(r[0]), to_number(r[1])))
        pub = dict(lignes)
        reg = d.groupby("region")["pdi_total"].sum()
        comp = []
        for g, v in reg.items():
            ref_g = pub.get(g)
            comp.append(dict(region=g, somme_communes=v, total_publie=ref_g, ecart_relatif=(v - ref_g) / ref_g if ref_g else None))
        c = pd.DataFrame(comp)
        c.to_csv(sortie / "02_controles_pdi_conasur_regions.csv", sep=";", index=False, encoding="utf-8")
        bad = c[c.ecart_relatif.abs() > 0.005]
        journal.append(dict(gravite="INFO", message="controle regions : %d regions comparees, %d ecart(s) > 0,5 %%" % (len(c.dropna(subset=['ecart_relatif'])), len(bad))))
        tot_nat = pub.get("BURKINA FASO")
        if tot_nat:
            journal.append(dict(gravite="INFO", message="somme des regions / total national publie : ecart relatif %.4f" % ((reg.sum() - tot_nat) / tot_nat)))
    if oc.NOTES_IGNOREES:
        journal.append(dict(gravite="ATTENTION", message="%d cellule(s) contenaient une note adressee a un assistant IA : texte ecarte, non execute" % len(oc.NOTES_IGNOREES)))
    pd.DataFrame(journal).to_csv(sortie / "02_journal_pdi_conasur.csv", sep=";", index=False, encoding="utf-8")
    for j in journal:
        print("  %-9s %s" % (j["gravite"], j["message"][:220]))
    print("Sorties dans :", sortie.resolve())


if __name__ == "__main__":
    main()
