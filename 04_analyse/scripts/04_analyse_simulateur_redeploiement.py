# -*- coding: utf-8 -*-
"""Etape 04_analyse (2/2) : simulateur d'allocation. A partir des besoins a l'horizon (script 1/2), calcule pour chaque scenario
  1) le redeploiement des maitres publics des provinces excedentaires vers les provinces VOISINES en deficit
     (seule une part de l'excedent est mobilisable). Methode par defaut : optimisation lineaire (probleme de transport, solveur HiGHS de scipy)
     qui MAXIMISE le nombre de maitres redeployes puis, a nombre egal, sert d'abord les provinces les plus prioritaires.
     L'ancienne methode gloutonne (provinces servies dans l'ordre de priorite) est conservee pour comparaison ;
  2) le recrutement restant apres redeploiement ;
  3) l'effet du double flux (une salle PUBLIQUE accueille deux groupes) sur le deficit en salles, puis les salles a construire ;
  4) une grille de leviers (part mobilisable x part de salles en double flux) pour comparer les options.
Les « excedents » sont theoriques : ecart a la norme, sans tenir compte des contraintes locales (ecoles a faible effectif, securite).

Usage : python 04_analyse_simulateur_redeploiement.py [--params parametres/parametres_modele.json] [--sortie 04_analyse/resultats]
Sorties : 04_flux_redeploiement_maitres.csv, 04_bilan_province.csv, 04_synthese_scenarios.csv, 04_grille_leviers.csv, 04_journal_simulateur.csv,
          04_flux_par_perimetre.csv et 04_synthese_perimetres.csv (redeploiement selon le perimetre de decision : dans la region, provinces voisines, national)"""

import json
import sys
from pathlib import Path
import numpy as np
import pandas as pd

DEFAUT = {"fichiers_simulateur": {
    "besoins": "04_analyse/resultats/04_besoins_horizon.csv",
    "indice": "04_analyse/resultats/04_indice_priorite.csv",
    "voisins": "02_nettoyage/carte_provinces_voisins/02_nettoye_carte_voisins_provinces_adminlines.csv",
    "carte": "02_nettoyage/carte_provinces_voisins/02_nettoye_carte_provinces_45.geojson"},
    "simulateur": {"methode_redeploiement": "optimal", "part_excedent_mobilisable": 0.5, "part_salles_double_flux": 0.0,
                   "grille_part_mobilisable": [0.0, 0.25, 0.5, 0.75, 1.0], "grille_double_flux": [0.0, 0.05, 0.10, 0.20]}}


def redeployer(b, voisins, rang, part):
    """b : besoins d'un scenario (index province). Renvoie (flux, deficit_restant, excedent_restant)."""
    dispo = np.floor(b.excedent_maitres_public * part).astype(int).to_dict()
    besoin = b.deficit_maitres_public.astype(int).to_dict()
    flux = []
    for p in sorted(besoin, key=lambda x: (rang.get(x, 999), x)):
        if besoin[p] <= 0:
            continue
        for q in sorted(voisins.get(p, []), key=lambda x: (-dispo.get(x, 0), x)):
            if besoin[p] <= 0:
                break
            n = min(besoin[p], dispo.get(q, 0))
            if n > 0:
                flux.append(dict(origine=q, destination=p, maitres=n))
                dispo[q] -= n
                besoin[p] -= n
    return flux, besoin, dispo


def redeployer_optimal(b, voisins, rang, part, prox=None, regle="priorite"):
    """Probleme de transport : max sum x[q->p] sous sum_p x <= disponible(q), sum_q x <= deficit(p), x >= 0, arcs = provinces voisines.
    Objectif lexicographique en un seul programme : coefficient 1 + eps * priorite(p), eps assez petit pour ne jamais sacrifier un maitre redeploye.
    La matrice est totalement unimodulaire : la solution de sommet est entiere (verifie)."""
    from scipy.optimize import linprog
    dispo = np.floor(b.excedent_maitres_public * part).astype(int).to_dict()
    besoin = b.deficit_maitres_public.astype(int).to_dict()
    arcs = sorted((q, p) for p in besoin if besoin[p] > 0 for q in voisins.get(p, []) if dispo.get(q, 0) > 0)
    if not arcs:
        return [], besoin, dispo
    orig, dest = sorted({q for q, _ in arcs}), sorted({p for _, p in arcs})
    rmax = max(rang.values()) if rang else 1
    prio = {p: (rmax + 1 - rang.get(p, rmax)) / float(rmax) for p in dest}  # 1 = la plus prioritaire
    eps = 1.0 / (sum(dispo[q] for q in orig) + 1)
    if prox is None:
        prox, regle = (lambda q, p: 0.0), "priorite"
    # second critere, a nombre de maitres egal : la priorite (puis la proximite) ou la proximite (puis la priorite)
    c = [-(1.0 + eps * ((0.9 * prio[p] + 0.1 * prox(q, p)) if regle == "priorite" else (0.9 * prox(q, p) + 0.1 * prio[p]))) for q, p in arcs]
    A = np.zeros((len(orig) + len(dest), len(arcs)))
    for j, (q, p) in enumerate(arcs):
        A[orig.index(q), j] = 1
        A[len(orig) + dest.index(p), j] = 1
    ub = [dispo[q] for q in orig] + [besoin[p] for p in dest]
    r = linprog(c, A_ub=A, b_ub=ub, bounds=(0, None), method="highs-ds")
    if r.status != 0:
        raise RuntimeError("optimisation non resolue : " + r.message)
    x = np.rint(r.x).astype(int)
    if np.abs(r.x - x).max() > 1e-6:
        raise RuntimeError("solution non entiere")
    flux = []
    for (q, p), n in zip(arcs, x):
        if n > 0:
            flux.append(dict(origine=q, destination=p, maitres=int(n)))
            dispo[q] -= int(n)
            besoin[p] -= int(n)
    return flux, besoin, dispo


METHODE = {"nom": "optimal"}
PERIMETRES = ["intra_region", "provinces_voisines", "national"]
REGLES = ["priorite", "proximite"]


def distances(chemin, provinces):
    """Distance a vol d'oiseau (km) entre les centres des provinces (moyenne des sommets du plus grand contour)."""
    gj = json.load(open(chemin, encoding="utf-8"))
    c = {}
    for f in gj["features"]:
        g = f["geometry"]
        pols = [g["coordinates"]] if g["type"] == "Polygon" else g["coordinates"]
        anneau = max((pol[0] for pol in pols), key=len)
        c[f["properties"]["province"]] = (np.mean([x for x, _ in anneau]), np.mean([y for _, y in anneau]))
    def km(a, b):
        (x1, y1), (x2, y2) = np.radians(c[a]), np.radians(c[b])
        h = np.sin((y2 - y1) / 2) ** 2 + np.cos(y1) * np.cos(y2) * np.sin((x2 - x1) / 2) ** 2
        return float(6371 * 2 * np.arcsin(np.sqrt(h)))
    ps = [p for p in provinces if p in c]
    return {(a, b): km(a, b) for a in ps for b in ps if a != b}, sorted(set(provinces) - set(c))


def candidats(perimetre, b, voisins):
    """Pour chaque province, les provinces d'ou des maitres peuvent venir selon le perimetre de decision."""
    reg = b.region.to_dict()
    if perimetre == "intra_region":
        return {p: [q for q in reg if q != p and reg[q] == reg[p]] for p in reg}
    if perimetre == "national":
        return {p: [q for q in reg if q != p] for p in reg}
    return voisins


def par_perimetre(b, voisins, rang, parts, dist):
    """Flux et bilan pour chaque perimetre, chaque regle et chaque part mobilisable (alimente le tableau de bord).
    Regle 'priorite' : a nombre egal, les maitres vont d'abord aux provinces les plus prioritaires, meme lointaines.
    Regle 'proximite' : a nombre egal, les maitres vont d'abord aux provinces en deficit les plus proches.
    Le nombre total de maitres deplaces est le meme pour les deux regles ; seules les destinations changent."""
    dmax = max(dist.values()) if dist else 1.0
    prox = lambda q, p: 1.0 - dist.get((q, p), dmax) / dmax
    lignes, synth = [], []
    for per in PERIMETRES:
        cand = candidats(per, b, voisins)
        for regle in REGLES:
            for part in parts:
                if METHODE["nom"] == "optimal":
                    flux, reste, dispo = redeployer_optimal(b, cand, rang, part, prox, regle)
                else:
                    flux, reste, dispo = redeployer(b, cand, rang, part)
                for f in flux:
                    f["distance_km"] = round(dist.get((f["origine"], f["destination"]), float("nan")), 1)
                n = int(sum(f["maitres"] for f in flux))
                km = sum(f["maitres"] * f["distance_km"] for f in flux)
                lignes += [dict(perimetre=per, regle=regle, part_excedent_mobilisable=part, **f) for f in flux]
                synth.append(dict(perimetre=per, regle=regle, part_excedent_mobilisable=part, maitres_redeployes=n,
                                  recrutements_necessaires=int(b.deficit_maitres_public.sum()) - n,
                                  excedent_mobilisable_non_affecte=int(sum(dispo.values())),
                                  distance_moyenne_km=round(km / n, 1) if n else 0.0,
                                  provinces_beneficiaires=len({f["destination"] for f in flux})))
    return lignes, synth


def simuler(b, voisins, rang, part, part_df):
    flux, reste, dispo = (redeployer_optimal if METHODE["nom"] == "optimal" else redeployer)(b, voisins, rang, part)
    recu = pd.Series({p: 0 for p in b.index}, dtype=float)
    cede = recu.copy()
    for f in flux:
        recu[f["destination"]] += f["maitres"]
        cede[f["origine"]] += f["maitres"]
    salles_df = b.salles_publiques_actuelles if "salles_publiques_actuelles" in b.columns else b.salles_actuelles  # le double flux ne se decide que dans le public
    gain_df = np.where(b.deficit_salles > 0, np.floor(salles_df * part_df), 0)
    gain_df = np.minimum(gain_df, b.deficit_salles)
    bilan = pd.DataFrame({"region": b.region, "deficit_maitres_initial": b.deficit_maitres_public, "maitres_recus": recu, "maitres_cedes": cede,
                          "recrutements_necessaires": pd.Series(reste), "deficit_salles_initial": b.deficit_salles, "salles_gagnees_double_flux": gain_df,
                          "salles_a_construire": b.deficit_salles - gain_df, "salles_a_remplacer": b.salles_a_remplacer})
    return flux, bilan


def main():
    args = sys.argv[1:]
    params = json.loads(json.dumps(DEFAUT))
    if "--params" in args:
        u = json.load(open(args[args.index("--params") + 1], encoding="utf-8"))
        for k, v in u.items():
            if isinstance(v, dict) and isinstance(params.get(k), dict):
                params[k].update(v)
            else:
                params[k] = v
    sortie = Path(args[args.index("--sortie") + 1]) if "--sortie" in args else Path("04_analyse/resultats")
    sortie.mkdir(parents=True, exist_ok=True)
    F, S = params["fichiers_simulateur"], params["simulateur"]
    journal = []
    METHODE["nom"] = S.get("methode_redeploiement", "optimal")
    if METHODE["nom"] == "optimal":
        try:
            import scipy  # noqa
        except ImportError:
            METHODE["nom"] = "glouton"
            journal.append(dict(gravite="ATTENTION", message="scipy absent : redeploiement par la methode gloutonne (pip install scipy pour l'optimisation)"))
    bes = pd.read_csv(F["besoins"], sep=";")
    ind = pd.read_csv(F["indice"], sep=";")
    rang = dict(zip(ind.province, ind.rang))
    v = pd.read_csv(F["voisins"], sep=";")
    voisins = v.groupby("province").voisine.apply(list).to_dict()
    dist, sans_centre = distances(F["carte"], list(bes.province.unique()))
    if sans_centre:
        journal.append(dict(gravite="ATTENTION", message="provinces absentes de la carte (distance inconnue) : %s" % sans_centre))
    inconnues = sorted(set(bes.province) - set(voisins))
    if inconnues:
        journal.append(dict(gravite="ATTENTION", message="provinces sans voisine connue (noms a rapprocher) : %s" % inconnues))
    tous_flux, bilans, synth, grille, fper, sper = [], [], [], [], [], []
    for sc, g in bes.groupby("scenario", sort=False):
        b = g.set_index("province")
        flux, bilan = simuler(b, voisins, rang, S["part_excedent_mobilisable"], S["part_salles_double_flux"])
        for f in flux:
            f["scenario"] = sc
        tous_flux += flux
        bilan = bilan.reset_index().rename(columns={"index": "province"})
        bilan.insert(0, "scenario", sc)
        bilan["rang_priorite"] = bilan.province.map(rang)
        bilans.append(bilan)
        synth.append(dict(scenario=sc, deficit_maitres_initial=int(b.deficit_maitres_public.sum()), excedent_maitres_theorique=int(b.excedent_maitres_public.sum()),
                          methode_redeploiement=METHODE["nom"], maitres_redeployes=int(sum(f["maitres"] for f in flux)),
                          maitres_redeployes_methode_gloutonne=int(sum(f["maitres"] for f in redeployer(b, voisins, rang, S["part_excedent_mobilisable"])[0])),
                          maitres_redeployes_maximum_si_tout_mobilisable=int(sum(f["maitres"] for f in (redeployer_optimal if METHODE["nom"] == "optimal" else redeployer)(b, voisins, rang, 1.0)[0])),
                          recrutements_necessaires=int(bilan.recrutements_necessaires.sum()),
                          deficit_salles_initial=int(b.deficit_salles.sum()), salles_gagnees_double_flux=int(bilan.salles_gagnees_double_flux.sum()),
                          salles_a_construire=int(bilan.salles_a_construire.sum()), salles_a_remplacer=int(b.salles_a_remplacer.sum()),
                          provinces_beneficiaires=int((bilan.maitres_recus > 0).sum()), provinces_cedantes=int((bilan.maitres_cedes > 0).sum())))
        for pm in S["grille_part_mobilisable"]:
            for pdf in S["grille_double_flux"]:
                fl, bi = simuler(b, voisins, rang, pm, pdf)
                grille.append(dict(scenario=sc, part_excedent_mobilisable=pm, part_salles_double_flux=pdf, maitres_redeployes=int(sum(f["maitres"] for f in fl)),
                                   recrutements_necessaires=int(bi.recrutements_necessaires.sum()), salles_a_construire=int(bi.salles_a_construire.sum())))
        lg, sy_p = par_perimetre(b, voisins, rang, S["grille_part_mobilisable"], dist)
        fper += [dict(scenario=sc, **x) for x in lg]
        sper += [dict(scenario=sc, **x) for x in sy_p]
        # controle : conservation
        ok = int(bilan.maitres_recus.sum()) == int(bilan.maitres_cedes.sum()) and (bilan.recrutements_necessaires >= 0).all() and (bilan.salles_a_construire >= 0).all()
        journal.append(dict(gravite="INFO" if ok else "ERREUR", message="scenario %s : maitres recus = maitres cedes, aucun solde negatif : %s" % (sc, "oui" if ok else "NON")))
    pd.DataFrame(tous_flux, columns=["scenario", "origine", "destination", "maitres"]).to_csv(sortie / "04_flux_redeploiement_maitres.csv", sep=";", index=False, encoding="utf-8")
    pd.concat(bilans).to_csv(sortie / "04_bilan_province.csv", sep=";", index=False, encoding="utf-8")
    sy = pd.DataFrame(synth)
    sy.to_csv(sortie / "04_synthese_scenarios.csv", sep=";", index=False, encoding="utf-8")
    pd.DataFrame(fper, columns=["scenario", "perimetre", "regle", "part_excedent_mobilisable", "origine", "destination", "maitres", "distance_km"]).to_csv(sortie / "04_flux_par_perimetre.csv", sep=";", index=False, encoding="utf-8")
    pd.DataFrame(sper).to_csv(sortie / "04_synthese_perimetres.csv", sep=";", index=False, encoding="utf-8")
    pd.DataFrame(grille).to_csv(sortie / "04_grille_leviers.csv", sep=";", index=False, encoding="utf-8")
    journal.append(dict(gravite="INFO", message="methode de redeploiement : %s" % ("optimisation lineaire (transport, HiGHS) : maximum de maitres redeployes, puis priorite" if METHODE["nom"] == "optimal" else "gloutonne (ordre de priorite)")))
    journal.append(dict(gravite="INFO", message="leviers : %.0f %% de l'excedent mobilisable vers les provinces voisines ; double flux sur %.0f %% des salles publiques des provinces en deficit" % (
        100 * S["part_excedent_mobilisable"], 100 * S["part_salles_double_flux"])))
    pd.DataFrame(journal).to_csv(sortie / "04_journal_simulateur.csv", sep=";", index=False, encoding="utf-8")
    for j in journal:
        print("  %-9s %s" % (j["gravite"], j["message"]))
    print(sy.to_string(index=False))
    print("Sorties dans :", sortie.resolve())


if __name__ == "__main__":
    main()
