# -*- coding: utf-8 -*-
"""Agrege par province de l'ancien decoupage la serie des PDI du fichier idps4__Tableau.csv .
Le fichier porte des P-codes ANCIENS (region BF46.., province BF5603, commune BF560301) : la province est obtenue par jointure
directe sur prov_code_ancien (table du script 51), sans rapprochement de noms.
Les colonnes sont reperees par la ligne d'etiquettes (#adm2+code, #adm3+code, #date, #inneed+idps+total, ...).

Usage : python 02_nettoyage_pdi_idps4.py idps4__Tableau.csv 02_nettoyage/cod_ab_limites_administratives/02_nettoye_cod_ab_communes_ancien_decoupage.csv
        [--stats "...31-decembre-2022-1__STATISTIQUES.csv"] [dossier_sortie]
Sorties : 02_nettoye_pdi_idps4_province_serie.csv (province x date), 02_nettoye_pdi_idps4_province_derniere.csv (derniere date), 02_nettoye_pdi_idps4_dates.csv
          (une ligne par date), 02_controles_pdi_idps4_vs_conasur_2022-12.csv (si --stats), 02_journal_pdi_idps4.csv"""

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


def tag(c):
    return re.sub(r"\s+", "", c.lower())


def main():
    args = sys.argv[1:]
    if len(args) < 2:
        print(__doc__)
        return
    sortie = Path([a for a in args[2:] if not a.startswith("--") and not a.endswith(".csv")][-1]) if [a for a in args[2:] if not a.startswith("--") and not a.endswith(".csv")] else Path("02_nettoyage/pdi_idps4_serie")
    sortie.mkdir(parents=True, exist_ok=True)
    journal = []
    rows = lire(args[0])
    k = next(i for i, r in enumerate(rows[:8]) if any(tag(c).startswith("#adm2+code") for c in r))
    tags = [tag(c) for c in rows[k]]
    def col(t):
        return tags.index(t)
    i_prov, i_com, i_date = col("#adm2+code"), col("#adm3+code"), col("#date")
    i_h, i_f, i_e, i_t = col("#inneed+idps+m"), col("#inneed+idps+f"), col("#inneed+idps+children"), col("#inneed+idps+total")
    com = pd.read_csv(args[1], sep=";", dtype=str)
    col_prov = "province_cns530" if "province_cns530" in com.columns else "province_ancienne"
    col_reg = "region_cns530" if "region_cns530" in com.columns else "region_ancienne"
    code2prov = dict(zip(com["prov_code_ancien"], com[col_prov]))
    code2reg = dict(zip(com["prov_code_ancien"], com[col_reg]))
    data = []
    for r in rows[k + 1:]:
        r = r + [""] * (len(tags) - len(r))
        if not re.match(r"^\d{4}-\d{2}-\d{2}", r[i_date]) or not r[i_prov]:
            continue
        data.append(dict(date=r[i_date][:10], code_province=r[i_prov], code_commune=r[i_com], hommes=to_number(r[i_h]), femmes=to_number(r[i_f]),
                         enfants=to_number(r[i_e]), total=to_number(r[i_t])))
    d = pd.DataFrame(data)
    journal.append(dict(gravite="INFO", message="%d lignes ; %d dates (%s a %s)" % (len(d), d.date.nunique(), d.date.min(), d.date.max())))
    d["province"] = d.code_province.map(code2prov)
    d["region"] = d.code_province.map(code2reg)
    sans = d[d.province.isna()]
    if len(sans):
        journal.append(dict(gravite="ATTENTION", message="%d lignes dont le code province est inconnu de la table COD-AB : %s" % (len(sans), {k_: int(v) for k_, v in sans.code_province.value_counts().head(6).items()})))
    manq_tot = int(d.total.isna().sum())
    if manq_tot:
        journal.append(dict(gravite="ATTENTION", message="%d lignes sans total d'individus (comptees 0)" % manq_tot))
    d = d.dropna(subset=["province"]).fillna({"total": 0, "hommes": 0, "femmes": 0, "enfants": 0})
    dup = int(d.duplicated(["date", "code_commune"]).sum())
    if dup:
        journal.append(dict(gravite="INFO", message="%d lignes partagent la meme commune et la meme date (sites ou sources multiples) : sommees" % dup))
    # serie province x date
    s = d.groupby(["region", "province", "date"]).agg(communes=("code_commune", "nunique"), pdi_total=("total", "sum"),
                                                      pdi_enfants=("enfants", "sum"), pdi_hommes=("hommes", "sum"), pdi_femmes=("femmes", "sum")).reset_index()
    s.to_csv(sortie / "02_nettoye_pdi_idps4_province_serie.csv", sep=";", index=False, encoding="utf-8")
    derniere = s[s.date == s.date.max()]
    toutes = com[[col_reg, col_prov]].drop_duplicates().rename(columns={col_reg: "region", col_prov: "province"})
    der = toutes.merge(derniere.drop(columns="region"), on="province", how="left").fillna(0)
    der["date"] = s.date.max()
    der.to_csv(sortie / "02_nettoye_pdi_idps4_province_derniere.csv", sep=";", index=False, encoding="utf-8")
    dd = d.groupby("date").agg(lignes=("code_commune", "size"), communes=("code_commune", "nunique"), provinces=("province", "nunique"),
                               pdi_total=("total", "sum"), enfants_renseignes=("enfants", lambda x: int((x > 0).sum()))).reset_index()
    dd.to_csv(sortie / "02_nettoye_pdi_idps4_dates.csv", sep=";", index=False, encoding="utf-8")
    journal.append(dict(gravite="INFO", message="derniere date %s : %d communes, %d provinces avec PDI sur 45" % (s.date.max(), int(derniere.communes.sum()), len(derniere[derniere.pdi_total > 0]))))
    part_enf = (d[d.date == d.date.max()].enfants > 0).mean()
    journal.append(dict(gravite="INFO", message="derniere date : enfants renseignes pour %.0f %% des lignes" % (100 * part_enf)))
    # controle contre la situation CONASUR de decembre 2022
    if "--stats" in args:
        st = lire(args[args.index("--stats") + 1])
        hs = next(i for i, r in enumerate(st[:8]) if any(norm_libre(c).startswith("region") for c in r))
        pub = {norm_label(r[0]): to_number(r[1]) for r in st[hs + 1:] if len(r) >= 2 and r[0] and to_number(r[1]) is not None}
        x = d[d.date == "2022-12-31"].groupby("region")["total"].sum()
        comp = pd.DataFrame([dict(region=g, idps4_2022_12_31=v, conasur_stat=pub.get(g), ecart_relatif=((v - pub[g]) / pub[g] if pub.get(g) else None)) for g, v in x.items()])
        comp.to_csv(sortie / "02_controles_pdi_idps4_vs_conasur_2022-12.csv", sep=";", index=False, encoding="utf-8")
        bad = comp[comp.ecart_relatif.abs() > 0.02]
        journal.append(dict(gravite="INFO", message="controle 2022-12-31 : %d regions comparees, %d ecart(s) > 2 %%" % (len(comp.dropna(subset=["ecart_relatif"])), len(bad))))
    if oc.NOTES_IGNOREES:
        journal.append(dict(gravite="ATTENTION", message="%d cellule(s) contenaient une note adressee a un assistant IA : texte ecarte, non execute" % len(oc.NOTES_IGNOREES)))
    pd.DataFrame(journal).to_csv(sortie / "02_journal_pdi_idps4.csv", sep=";", index=False, encoding="utf-8")
    for j in journal:
        print("  %-9s %s" % (j["gravite"], j["message"][:230]))
    print("Sorties dans :", sortie.resolve())


if __name__ == "__main__":
    main()
