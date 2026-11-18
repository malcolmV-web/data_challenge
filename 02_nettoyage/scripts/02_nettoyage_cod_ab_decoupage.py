# -*- coding: utf-8 -*-
"""Reconstitue les provinces (45) et regions (13) de l'ANCIEN decoupage a partir des CSV COD-AB (admin1, admin2, admin3) :
chaque commune porte un code ancien (adm3_pcode_old) ; on en deduit son code de province ancienne (prefixe), puis le nom de la
province ancienne (adm2_name_old) et on l'aligne sur le referentiel du CNS 530.

Usage : python 02_nettoyage_cod_ab_decoupage.py DOSSIER_COD_AB [--referentiel 02_nettoyage/cns530_annuaire_2024-25/02_nettoye_cns530_referentiel_provinces.csv] [sortie]
  DOSSIER_COD_AB : dossier contenant bfa_admin_boundaries__bfa_admin1.csv, ..._admin2.csv, ..._admin3.csv
  (CSV issus d'Excel : 1re ligne col1..colN, 2e ligne = en-tetes ; decimales a la virgule)
Sorties : 02_nettoye_cod_ab_communes_ancien_decoupage.csv, 02_nettoye_cod_ab_provinces_anciennes.csv, 02_nettoye_cod_ab_correspondance_provinces_ancien_nouveau.csv,
          02_journal_cod_ab.csv, 02_controles_cod_ab.csv"""

import csv
import re
import sys
from collections import Counter
from pathlib import Path
import pandas as pd
import sys as _sys
from pathlib import Path as _P
_sys.path.insert(0, str(_P(__file__).resolve().parents[2] / 'communs'))
import outils_communs as oc
from outils_communs import *

csv.field_size_limit(10 ** 8)
ALIAS = {"BALES": "LES BALE", "BALE": "LES BALE"}


def lire_cod(chemin):
    """CSV COD-AB : trouve la ligne d'en-tetes (celle qui contient adm?_pcode) puis lit les donnees."""
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
    h = next((k for k, r in enumerate(rows[:6]) if any(re.fullmatch(r"adm\d_pcode", c) for c in r)), None)
    if h is None:
        raise SystemExit("En-tetes adm?_pcode introuvables dans %s" % chemin)
    en_tete = rows[h]
    data = [r + [""] * (len(en_tete) - len(r)) for r in rows[h + 1:] if any(r)]
    return pd.DataFrame([r[:len(en_tete)] for r in data], columns=en_tete)


def nombre(s):
    return to_number(s)


def meilleur_prefixe(codes, codes_parents, journal, nom):
    """Longueur de prefixe L telle que les prefixes des codes de communes soient des codes de niveau superieur."""
    ens = set(c for c in codes_parents if c)
    meilleur = None
    for L in range(3, 12):
        pre = [c[:L] for c in codes if len(c) > L]
        if not pre:
            continue
        part = sum(1 for p in pre if p in ens) / len(pre)
        if meilleur is None or part > meilleur[1] + 1e-9:
            meilleur = (L, part)
    journal.append(dict(gravite="INFO", message="%s : longueur de prefixe retenue %s (part de correspondance %.1f %%)" % (nom, meilleur[0], 100 * meilleur[1])))
    if meilleur[1] < 0.95:
        journal.append(dict(gravite="ATTENTION", message="%s : correspondance de prefixe faible (%.1f %%) : le code ancien n'est peut-etre pas hierarchique" % (nom, 100 * meilleur[1])))
    return meilleur[0]


def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return
    dossier = Path(args[0])
    sortie = Path([a for a in args[1:] if not a.startswith("--") and not a.endswith(".csv")][-1]) if [a for a in args[1:] if not a.startswith("--") and not a.endswith(".csv")] else Path("02_nettoyage/cod_ab_limites_administratives")
    sortie.mkdir(parents=True, exist_ok=True)
    journal = []
    a1, a2, a3 = [lire_cod(next(dossier.glob("*admin%d.csv" % k))) for k in (1, 2, 3)]
    journal.append(dict(gravite="INFO", message="admin1 : %d, admin2 : %d, admin3 : %d lignes" % (len(a1), len(a2), len(a3))))
    # prefixes
    Lp = meilleur_prefixe(list(a3["adm3_pcode_old"]), list(a2["adm2_pcode_old"]), journal, "commune -> province ancienne")
    Lr = meilleur_prefixe(list(a3["adm3_pcode_old"]), list(a1["adm1_pcode_old"]), journal, "commune -> region ancienne")
    a3["prov_code_ancien"] = a3["adm3_pcode_old"].str[:Lp]
    a3["region_code_ancien"] = a3["adm3_pcode_old"].str[:Lr]
    # noms des provinces et regions anciennes
    def noms(df, code, nom):
        d = df[(df[code] != "")].groupby(code)[nom].agg(lambda x: Counter(x).most_common(1)[0][0])
        conflit = df[(df[code] != "")].groupby(code)[nom].nunique()
        if (conflit > 1).any():
            journal.append(dict(gravite="ATTENTION", message="codes %s avec plusieurs noms : %s" % (code, list(conflit[conflit > 1].index)[:8])))
        return d.to_dict()
    nom_prov = noms(a2, "adm2_pcode_old", "adm2_name_old")
    nom_reg = noms(a1, "adm1_pcode_old", "adm1_name_old")
    a3["province_ancienne"] = a3["prov_code_ancien"].map(nom_prov).map(lambda x: norm_label(x) if isinstance(x, str) else None)
    a3["region_ancienne"] = a3["region_code_ancien"].map(nom_reg).map(lambda x: norm_label(x) if isinstance(x, str) else None)
    manq_p, manq_r = int(a3.province_ancienne.isna().sum()), int(a3.region_ancienne.isna().sum())
    if manq_p or manq_r:
        journal.append(dict(gravite="ATTENTION", message="communes sans province ancienne : %d ; sans region ancienne : %d" % (manq_p, manq_r)))
    # alignement sur le referentiel CNS 530
    if "--referentiel" in args:
        ref = pd.read_csv(args[args.index("--referentiel") + 1], sep=";")
        ref_prov = {norm_label(p): norm_label(r) for p, r in zip(ref.province, ref.region)}
        def aligner(n):
            if not isinstance(n, str):
                return None
            n = ALIAS.get(n, n)
            if n in ref_prov:
                return n
            p = difflib.get_close_matches(n, list(ref_prov), n=1, cutoff=0.85)
            return p[0] if p else None
        a3["province_cns530"] = a3["province_ancienne"].map(aligner)
        non = sorted(set(a3.loc[a3.province_cns530.isna() & a3.province_ancienne.notna(), "province_ancienne"]))
        if non:
            journal.append(dict(gravite="ATTENTION", message="provinces COD-AB sans correspondance dans le CNS 530 : %s" % non))
        absentes = sorted(set(ref_prov) - set(a3.province_cns530.dropna()))
        if absentes:
            journal.append(dict(gravite="ATTENTION", message="provinces du CNS 530 sans commune COD-AB : %s" % absentes))
        a3["region_cns530"] = a3["province_cns530"].map(ref_prov)
        incoh = a3[a3.region_ancienne.notna() & a3.region_cns530.notna() & (a3.region_ancienne != a3.region_cns530)]
        if len(incoh):
            journal.append(dict(gravite="ATTENTION", message="%d communes dont la region ancienne differe du referentiel CNS 530 (ex. %s)" % (len(incoh), sorted(set(incoh.province_ancienne))[:5])))
    # superficie et centroides
    for c in ("area_sqkm", "center_lat", "center_lon"):
        a3[c] = a3[c].map(nombre)
    cle = "province_cns530" if "province_cns530" in a3.columns else "province_ancienne"
    cols = ["adm3_pcode", "adm3_name", "adm2_pcode", "adm2_name", "adm1_pcode", "adm1_name", "adm3_pcode_old", "prov_code_ancien",
            "province_ancienne", "region_ancienne"] + (["province_cns530", "region_cns530"] if cle == "province_cns530" else []) + ["area_sqkm", "center_lat", "center_lon"]
    cols = [c for c in cols if c in a3.columns]
    a3[cols].to_csv(sortie / "02_nettoye_cod_ab_communes_ancien_decoupage.csv", sep=";", index=False, encoding="utf-8")
    grp = a3.groupby([c for c in (["region_cns530"] if cle == "province_cns530" else ["region_ancienne"]) + [cle]]).agg(
        nb_communes=("adm3_pcode", "size"), superficie_km2=("area_sqkm", "sum")).reset_index()
    grp.to_csv(sortie / "02_nettoye_cod_ab_provinces_anciennes.csv", sep=";", index=False, encoding="utf-8")
    # correspondance ancien <-> nouveau decoupage (les communes sont le pivot commun)
    cle_n = "adm2_name" if "adm2_name" in a3.columns else "adm2_pcode"
    cles_cor = [cle, "adm2_pcode"] + ([cle_n] if cle_n != "adm2_pcode" else [])
    cor = a3.groupby(cles_cor).size().rename("nb_communes").reset_index()
    cor["part_de_la_province_ancienne"] = cor["nb_communes"] / cor.groupby(cle)["nb_communes"].transform("sum")
    cor.to_csv(sortie / "02_nettoye_cod_ab_correspondance_provinces_ancien_nouveau.csv", sep=";", index=False, encoding="utf-8")
    nb_nouv = cor.groupby(cle)["adm2_pcode"].nunique()
    scindees = list(nb_nouv[nb_nouv > 1].index)
    journal.append(dict(gravite="INFO", message="%d provinces anciennes sur %d tiennent entierement dans une seule province nouvelle ; %d sont reparties sur plusieurs : %s" % (
        int((nb_nouv == 1).sum()), len(nb_nouv), len(scindees), scindees[:12])))
    nb_ancien_par_nouv = cor.groupby("adm2_pcode")[cle].nunique()
    fusion = int((nb_ancien_par_nouv > 1).sum())
    journal.append(dict(gravite="INFO", message="%d provinces nouvelles regroupent plusieurs provinces anciennes (ou parties de plusieurs)" % fusion))
    if "adm1_name" in a3.columns:
        cr = a3.groupby(["region_ancienne", "adm1_name"]).size().reset_index()
        n_reg = cr.groupby("region_ancienne")["adm1_name"].nunique()
        journal.append(dict(gravite="INFO", message="regions anciennes sur plusieurs regions nouvelles : %d sur %d" % (int((n_reg > 1).sum()), len(n_reg))))
    ctrl = []
    ctrl.append(dict(controle="communes", valeur=len(a3), attendu=351))
    ctrl.append(dict(controle="provinces anciennes distinctes", valeur=a3[cle].nunique(), attendu=45))
    ctrl.append(dict(controle="regions anciennes distinctes", valeur=a3.region_ancienne.nunique(), attendu=13))
    ctrl.append(dict(controle="codes communes anciens uniques", valeur=a3.adm3_pcode_old.nunique(), attendu=351))
    pd.DataFrame(ctrl).to_csv(sortie / "02_controles_cod_ab.csv", sep=";", index=False, encoding="utf-8")
    if oc.NOTES_IGNOREES:
        journal.append(dict(gravite="ATTENTION", message="%d cellule(s) contenaient une note adressee a un assistant IA : texte ecarte, non execute" % len(oc.NOTES_IGNOREES)))
    pd.DataFrame(journal).to_csv(sortie / "02_journal_cod_ab.csv", sep=";", index=False, encoding="utf-8")
    for c in ctrl:
        print("%-34s %4d (attendu %d)%s" % (c["controle"], c["valeur"], c["attendu"], "" if c["valeur"] == c["attendu"] else "   <-- A VERIFIER"))
    print("Journal :")
    for j in journal:
        print("  %-9s %s" % (j["gravite"], j["message"][:220]))
    print("Sorties dans :", sortie.resolve())


if __name__ == "__main__":
    main()
