# -*- coding: utf-8 -*-
"""Verifie la STRUCTURE d'un GeoJSON de limites administratives (sans bibliotheque de cartographie) et mesure son alignement
sur le referentiel des provinces / regions du CNS 530 (ancien decoupage : 45 provinces, 13 regions).

Usage : python 01_collecte_verifier_geojson.py fichier.geojson [--referentiel 02_nettoyage/cns530_annuaire_2024-25/02_nettoye_cns530_referentiel_provinces.csv]
Affiche : nombre d'entites, types de geometrie, etendue (longitude, latitude), champs et leurs modalites (colonnes texte a peu de
valeurs), puis pour chaque champ texte le taux de correspondance avec les provinces et avec les regions du referentiel, et les
noms non apparies.
Sortie : verification_geojson_<nom>.txt"""

import json
import re
import sys
from collections import Counter
from pathlib import Path
import sys as _sys
from pathlib import Path as _P
_sys.path.insert(0, str(_P(__file__).resolve().parents[2] / 'communs'))
import outils_communs as oc
from outils_communs import *

ALIAS = {"BALES": "LES BALE", "BALE": "LES BALE"}


def coords(g, acc):
    if isinstance(g, (list, tuple)):
        if len(g) >= 2 and all(isinstance(x, (int, float)) for x in g[:2]):
            acc.append((g[0], g[1]))
        else:
            for x in g:
                coords(x, acc)


def aligner(n, ref):
    n = ALIAS.get(n, n)
    if n in ref:
        return n
    p = difflib.get_close_matches(n, list(ref), n=1, cutoff=0.85)
    return p[0] if p else None


def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return
    chemin = Path(args[0])
    out = ["Fichier : %s (%.1f Mo)" % (chemin.name, chemin.stat().st_size / 1e6), "SHA-256 : %s" % sha256(chemin)]
    with open(chemin, encoding="utf-8") as f:
        gj = json.load(f)
    feats = gj.get("features", [])
    out.append("Type : %s ; entites : %d ; CRS declare : %s" % (gj.get("type"), len(feats), (gj.get("crs") or {}).get("properties", {}).get("name", "non declare (GeoJSON = WGS84 par defaut)")))
    out.append("Geometries : %s" % dict(Counter((x.get("geometry") or {}).get("type") for x in feats)))
    pts = []
    for x in feats[:400]:
        coords((x.get("geometry") or {}).get("coordinates"), pts)
    if pts:
        lon, lat = [p[0] for p in pts], [p[1] for p in pts]
        out.append("Etendue (echantillon de %d entites) : longitude %.1f a %.1f ; latitude %.1f a %.1f%s" % (
            min(400, len(feats)), min(lon), max(lon), min(lat), max(lat),
            "" if (-6 <= min(lon) and max(lon) <= 3 and 9 <= min(lat) and max(lat) <= 16) else "   <-- ne ressemble pas a des degres sur le Burkina Faso (projection ?)"))
    # proprietes
    cles = Counter()
    for x in feats:
        cles.update((x.get("properties") or {}).keys())
    ref = None
    if "--referentiel" in args:
        import pandas as pd
        r = pd.read_csv(args[args.index("--referentiel") + 1], sep=";")
        ref_prov = {norm_label(p): norm_label(g) for p, g in zip(r.province, r.region)}
        ref_reg = {norm_label(g): norm_label(g) for g in r.region}
        ref = (ref_prov, ref_reg)
    out.append("Champs (%d) : nom ; non vides ; distincts ; modalites si <= 40 ; correspondance avec le referentiel" % len(cles))
    for k in cles:
        vals = []
        for x in feats:
            v = (x.get("properties") or {}).get(k)
            v2, note = nettoyer_cellule(v) if isinstance(v, str) else (v, False)
            if note:
                oc.NOTES_IGNOREES.append(("geojson", k, 0))
            if v2 not in (None, ""):
                vals.append(v2)
        dist = Counter(str(v).strip() for v in vals)
        nb_num = sum(1 for v in vals if to_number(v) is not None)
        ligne = "  %-22s non vides=%d ; distincts=%d ; nombres=%d%%" % (k[:22], len(vals), len(dist), round(100 * nb_num / max(len(vals), 1)))
        if nb_num < 0.5 * max(len(vals), 1) and len(dist) <= 40:
            ligne += " ; " + " / ".join(sorted(d[:28] for d in dist))[:360]
        if ref and nb_num < 0.5 * max(len(vals), 1) and 5 <= len(dist) <= 80:
            for nom, table in (("provinces", ref[0]), ("regions", ref[1])):
                ok = [d for d in dist if aligner(norm_label(d), table)]
                if len(ok) >= 0.5 * len(dist):
                    non = [d for d in dist if d not in ok]
                    ligne += "\n      -> %s : %d/%d noms apparies ; non apparies : %s" % (nom, len(ok), len(dist), non[:10])
        out.append(ligne)
    if oc.NOTES_IGNOREES:
        out.append("")
        out.append("VALEURS CONTENANT UNE NOTE ADRESSEE A UN ASSISTANT IA : %d (texte ecarte, non execute)" % len(oc.NOTES_IGNOREES))
    nom = "verification_geojson_%s.txt" % re.sub(r"[^A-Za-z0-9_-]", "_", chemin.stem)[:60]
    Path(nom).write_text("\n".join(out), encoding="utf-8")
    print("\n".join(out))
    print("\n-> Fichier ecrit : %s" % nom)


if __name__ == "__main__":
    main()
