# -*- coding: utf-8 -*-
"""Agrege par province de l'ancien decoupage les structures educatives OpenStreetMap (ecoles_osm_burkina.csv).
Les P-codes du fichier OSM (adm2_pcode, adm3_pcode) sont ceux de l'ANCIEN decoupage : ils se joignent directement a la table des
communes du script 51 (prov_code_ancien, adm3_pcode_old). Les structures sans amenity scolaire (ex. 'drinking_water') sont exclues.

Usage : python 02_nettoyage_osm_ecoles.py ecoles_osm_burkina.csv 02_nettoyage/cod_ab_limites_administratives/02_nettoye_cod_ab_communes_ancien_decoupage.csv
        [--cns530 02_nettoyage/cns530_annuaire_2024-25/02_nettoye_cns530_long.csv] [dossier_sortie]
Sorties : 02_nettoye_osm_par_province.csv, 02_nettoye_osm_par_commune.csv, 02_journal_osm.csv ; affichage : couverture OSM / CNS 530 (comptages seulement)."""

import csv
import sys
from pathlib import Path
import pandas as pd
import sys as _sys
from pathlib import Path as _P
_sys.path.insert(0, str(_P(__file__).resolve().parents[2] / 'communs'))
import outils_communs as oc
from outils_communs import *

csv.field_size_limit(10 ** 8)
SCOLAIRES = ("school", "college", "kindergarten", "university", "sans_type")


def main():
    args = sys.argv[1:]
    if len(args) < 2:
        print(__doc__)
        return
    sortie = Path([a for a in args[2:] if not a.startswith("--") and not a.endswith(".csv")][-1]) if [a for a in args[2:] if not a.startswith("--") and not a.endswith(".csv")] else Path("02_nettoyage/osm_ecoles")
    sortie.mkdir(parents=True, exist_ok=True)
    journal = []
    osm = pd.read_csv(args[0], sep=";", dtype=str, keep_default_na=False)
    for c in osm.columns:
        osm[c] = osm[c].map(lambda v: (nettoyer_cellule(v)[0] or "") if isinstance(v, str) else v)
    com = pd.read_csv(args[1], sep=";", dtype=str)
    col_prov = "province_cns530" if "province_cns530" in com.columns else "province_ancienne"
    col_reg = "region_cns530" if "region_cns530" in com.columns else "region_ancienne"
    code2prov = dict(zip(com["prov_code_ancien"], com[col_prov]))
    code2reg = dict(zip(com["prov_code_ancien"], com[col_reg]))
    n0 = len(osm)
    osm["amenity"] = osm["amenity"].str.strip().str.lower().replace("", "sans_type")
    hors = osm[~osm.amenity.isin(SCOLAIRES)]
    journal.append(dict(gravite="INFO", message="%d lignes ; %d structures retenues (dont %d sans type) ; %d lignes exclues (amenity : %s)" % (
        n0, n0 - len(hors), int((osm.amenity == "sans_type").sum()), len(hors), {k: int(v) for k, v in hors.amenity.value_counts().items()})))
    osm = osm[osm.amenity.isin(SCOLAIRES)].copy()
    doublons = int(osm.id.duplicated().sum())
    if doublons:
        journal.append(dict(gravite="ATTENTION", message="%d identifiants OSM en double (conserves une fois)" % doublons))
        osm = osm.drop_duplicates("id")
    osm["province"] = osm["adm2_pcode"].map(code2prov)
    osm["region"] = osm["adm2_pcode"].map(code2reg)
    sans = int(osm.province.isna().sum())
    if sans:
        journal.append(dict(gravite="ATTENTION", message="%d structures dont adm2_pcode est absent de la table COD-AB : %s" % (sans, {k: int(v) for k, v in osm[osm.province.isna()].adm2_pcode.value_counts().head(5).items()})))
    osm["operateur"] = osm["operator_type"].str.strip().str.lower().replace("", "non_renseigne")
    g = osm.dropna(subset=["province"]).groupby(["region", "province"])
    out = g.agg(structures_osm=("id", "size"), communes_avec_structure=("adm3_pcode", "nunique")).reset_index()
    for a in SCOLAIRES:
        out["osm_" + a] = out.apply(lambda r: int(((osm.province == r.province) & (osm.amenity == a)).sum()), axis=1)
    for o in ("public", "private", "community", "religious", "ngo", "association", "non_renseigne"):
        out["operateur_" + o] = out.apply(lambda r: int(((osm.province == r.province) & (osm.operateur == o)).sum()), axis=1)
    nb_com = com.groupby(col_prov)["adm3_pcode"].nunique().rename("communes_cod_ab")
    out = out.merge(nb_com, left_on="province", right_index=True, how="left")
    out["part_communes_avec_structure"] = (out.communes_avec_structure / out.communes_cod_ab).round(3)
    ref = com[[col_reg, col_prov]].drop_duplicates().rename(columns={col_reg: "region", col_prov: "province"})
    out = ref.merge(out, on=["region", "province"], how="left").fillna(0)
    out.to_csv(sortie / "02_nettoye_osm_par_province.csv", sep=";", index=False, encoding="utf-8")
    cm = osm.groupby(["adm3_pcode", "adm3_name"]).size().rename("structures_osm").reset_index()
    cm.to_csv(sortie / "02_nettoye_osm_par_commune.csv", sep=";", index=False, encoding="utf-8")
    geo = {k: int(v) for k, v in osm["geometrie"].value_counts().items()} if "geometrie" in osm.columns else {}
    journal.append(dict(gravite="INFO", message="geometries : %s ; communes avec au moins une structure : %d sur %d" % (geo, osm.adm3_pcode.nunique(), com.adm3_pcode.nunique())))
    if "--cns530" in args:
        cns = pd.read_csv(args[args.index("--cns530") + 1], sep=";")
        e = cns[(cns.section == "I.1") & (cns.type_ligne == "detail") & (cns.indicateur == "ecoles") & (cns.statut == "PUBLIC_PRIVE")][["province", "valeur"]]
        e = e.groupby("province")["valeur"].sum().rename("ecoles_cns530")
        m = out.merge(e, left_on="province", right_index=True, how="left")
        m["couverture_osm_school"] = (m.osm_school / m.ecoles_cns530).round(3)
        m["couverture_osm_toutes_structures"] = (m.structures_osm / m.ecoles_cns530).round(3)
        m.to_csv(sortie / "02_nettoye_osm_couverture_vs_cns530.csv", sep=";", index=False, encoding="utf-8")
        c = m.couverture_osm_school
        journal.append(dict(gravite="INFO", message="couverture OSM 'school' / ecoles CNS 530 par province : min %.2f, mediane %.2f, max %.2f ; %d provinces sous 0,25" % (c.min(), c.median(), c.max(), int((c < 0.25).sum()))))
        c2 = m.couverture_osm_toutes_structures
        journal.append(dict(gravite="INFO", message="couverture OSM toutes structures (avec sans_type) / ecoles CNS 530 : min %.2f, mediane %.2f, max %.2f ; %d provinces sous 0,25" % (c2.min(), c2.median(), c2.max(), int((c2 < 0.25).sum()))))
    if oc.NOTES_IGNOREES:
        journal.append(dict(gravite="ATTENTION", message="%d cellule(s) contenaient une note adressee a un assistant IA : texte ecarte, non execute" % len(oc.NOTES_IGNOREES)))
    pd.DataFrame(journal).to_csv(sortie / "02_journal_osm.csv", sep=";", index=False, encoding="utf-8")
    for j in journal:
        print("  %-9s %s" % (j["gravite"], j["message"][:230]))
    print("Sorties dans :", sortie.resolve())


if __name__ == "__main__":
    main()
