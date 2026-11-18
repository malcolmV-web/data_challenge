# -*- coding: utf-8 -*-
"""A partir d'un GeoJSON des 45 provinces (ancien decoupage), produit :
  - 02_nettoye_carte_provinces_45.geojson : geometries allegees (coordonnees arrondies), proprietes minimales {province, region}
  - 02_nettoye_carte_voisins_provinces.csv : une ligne par couple de provinces voisines (frontiere commune)
  - 02_nettoye_carte_voisins_regions.csv   : couples de regions voisines
  - 02_controles_carte_voisins.csv  : nombre de voisins par province (une province sans voisin signale un probleme)
Methode (sans bibliotheque de cartographie) : deux provinces sont voisines si elles partagent au moins 2 sommets de polygone
(coordonnees arrondies a 4 decimales, environ 10 m). Les limites issues d'une meme source sont topologiquement coherentes.

Usage : python 02_nettoyage_carte_provinces_voisins.py bfa_provinces_boundaries.geojson 02_nettoyage/cns530_annuaire_2024-25/02_nettoye_cns530_referentiel_provinces.csv [dossier_sortie]
        [--champ shapeName] [--decimales 4] [--seuil 2]"""

import csv
import json
import sys
from collections import defaultdict
from itertools import combinations
from pathlib import Path
import pandas as pd
import sys as _sys
from pathlib import Path as _P
_sys.path.insert(0, str(_P(__file__).resolve().parents[2] / 'communs'))
import outils_communs as oc
from outils_communs import *

ALIAS = {"BALES": "LES BALE", "BALE": "LES BALE"}


def anneaux(geom):
    t = geom.get("type")
    if t == "Polygon":
        return [geom["coordinates"]]
    if t == "MultiPolygon":
        return geom["coordinates"]
    return []


def arrondir(c, d):
    return [round(c[0], d), round(c[1], d)]


def main():
    args = sys.argv[1:]
    if len(args) < 2:
        print(__doc__)
        return
    chemin, ref_chemin = Path(args[0]), args[1]
    sortie = Path(args[2]) if len(args) > 2 and not args[2].startswith("--") else Path("02_nettoyage/carte_provinces_voisins")
    champ = args[args.index("--champ") + 1] if "--champ" in args else "shapeName"
    dec = int(args[args.index("--decimales") + 1]) if "--decimales" in args else 4
    seuil = int(args[args.index("--seuil") + 1]) if "--seuil" in args else 2
    sortie.mkdir(parents=True, exist_ok=True)
    ref = pd.read_csv(ref_chemin, sep=";")
    ref_prov = {norm_label(p): norm_label(r) for p, r in zip(ref.province, ref.region)}
    gj = json.load(open(chemin, encoding="utf-8"))
    sommets = defaultdict(set)
    feats, journal = [], []
    vus = {}
    for ft in gj["features"]:
        nom_brut = (ft.get("properties") or {}).get(champ)
        nom_brut, note = nettoyer_cellule(nom_brut) if isinstance(nom_brut, str) else (nom_brut, False)
        if note:
            oc.NOTES_IGNOREES.append(("geojson", champ, 0))
        n = ALIAS.get(norm_label(nom_brut or ""), norm_label(nom_brut or ""))
        if n not in ref_prov:
            p = difflib.get_close_matches(n, list(ref_prov), n=1, cutoff=0.85)
            if not p:
                journal.append(dict(gravite="ATTENTION", message="entite non appariee : '%s'" % nom_brut))
                continue
            n = p[0]
        if n in vus:
            journal.append(dict(gravite="ATTENTION", message="province en double : %s" % n))
        vus[n] = True
        nouveaux = []
        for poly in anneaux(ft["geometry"]):
            rings = []
            for ring in poly:
                r2 = []
                for c in ring:
                    a = arrondir(c, dec)
                    if not r2 or a != r2[-1]:
                        r2.append(a)
                    sommets[tuple(a)].add(n)
                if len(r2) >= 4:
                    rings.append(r2)
            if rings:
                nouveaux.append(rings)
        geom = {"type": "Polygon", "coordinates": nouveaux[0]} if len(nouveaux) == 1 else {"type": "MultiPolygon", "coordinates": nouveaux}
        feats.append({"type": "Feature", "properties": {"province": n, "region": ref_prov[n]}, "geometry": geom})
    manquantes = sorted(set(ref_prov) - set(vus))
    if manquantes:
        journal.append(dict(gravite="ATTENTION", message="provinces du CNS 530 absentes du GeoJSON : %s" % manquantes))
    json.dump({"type": "FeatureCollection", "features": feats}, open(sortie / "02_nettoye_carte_provinces_45.geojson", "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    paires = defaultdict(int)
    for v, ps in sommets.items():
        if len(ps) >= 2:
            for a, b in combinations(sorted(ps), 2):
                paires[(a, b)] += 1
    vois = [dict(province=a, voisine=b, sommets_communs=k) for (a, b), k in paires.items() if k >= seuil]
    lignes = []
    for r in vois:
        lignes.append(dict(province=r["province"], voisine=r["voisine"], sommets_communs=r["sommets_communs"]))
        lignes.append(dict(province=r["voisine"], voisine=r["province"], sommets_communs=r["sommets_communs"]))
    vp = pd.DataFrame(lignes).sort_values(["province", "voisine"]) if lignes else pd.DataFrame(columns=["province", "voisine", "sommets_communs"])
    vp.insert(1, "region", vp["province"].map(ref_prov))
    vp["region_voisine"] = vp["voisine"].map(ref_prov)
    vp.to_csv(sortie / "02_nettoye_carte_voisins_provinces.csv", sep=";", index=False, encoding="utf-8")
    vr = vp[vp.region != vp.region_voisine][["region", "region_voisine"]].drop_duplicates().sort_values(["region", "region_voisine"])
    vr.to_csv(sortie / "02_nettoye_carte_voisins_regions.csv", sep=";", index=False, encoding="utf-8")
    cnt = vp.groupby("province").size().reindex(sorted(vus), fill_value=0).rename("nb_voisins").reset_index()
    cnt.to_csv(sortie / "02_controles_carte_voisins.csv", sep=";", index=False, encoding="utf-8")
    seuls = cnt[cnt.nb_voisins == 0].province.tolist()
    if seuls:
        journal.append(dict(gravite="ATTENTION", message="provinces sans voisine detectee (seuil %d sommets communs) : %s" % (seuil, seuls)))
    faibles = vp[vp.sommets_communs <= 3]
    if len(faibles):
        journal.append(dict(gravite="INFO", message="%d couples a frontiere tres courte (<= 3 sommets communs) : a regarder si le resultat parait suspect" % (len(faibles) // 2)))
    if oc.NOTES_IGNOREES:
        journal.append(dict(gravite="ATTENTION", message="%d valeur(s) contenaient une note adressee a un assistant IA : texte ecarte, non execute" % len(oc.NOTES_IGNOREES)))
    pd.DataFrame(journal).to_csv(sortie / "02_journal_carte.csv", sep=";", index=False, encoding="utf-8")
    taille = (sortie / "02_nettoye_carte_provinces_45.geojson").stat().st_size / 1e6
    print("%d provinces ; %d couples de voisines ; %d couples de regions voisines ; GeoJSON allege : %.2f Mo (source %.2f Mo)" % (
        len(vus), len(vp) // 2, len(vr) // 2 if len(vr) else 0, taille, chemin.stat().st_size / 1e6))
    print("Nombre de voisines par province : min %d, moyenne %.1f, max %d" % (cnt.nb_voisins.min(), cnt.nb_voisins.mean(), cnt.nb_voisins.max()))
    for j in journal:
        print("  %-9s %s" % (j["gravite"], j["message"][:200]))
    print("Sorties dans :", sortie.resolve())


if __name__ == "__main__":
    main()
