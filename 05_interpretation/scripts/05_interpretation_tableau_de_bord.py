# -*- coding: utf-8 -*-
"""Etape 05_interpretation : fabrique le tableau de bord (une page HTML autonome, donnees agregees par province incluses, aucune ressource externe).
La page fonctionne hors ligne et peut etre publiee telle quelle (GitHub Pages).

Usage : python 05_interpretation_tableau_de_bord.py [--sortie 05_interpretation/tableau_de_bord]
Entrees : 03_base_province.csv, 04_indice_priorite.csv, 04_besoins_horizon.csv, 04_flux_par_perimetre.csv, 04_sensibilite_classement.csv, 02_nettoye_carte_provinces_45.geojson
Quatre modules : diagnostic et carte, indice et priorites, simulateur de postes, import et controle ; filtre par region.
Sortie : index.html"""

import json
import sys
from pathlib import Path
import pandas as pd

R3 = Path("03_transformation/donnees_transformees")
R4 = Path("04_analyse/resultats")
CARTE = Path("02_nettoyage/carte_provinces_voisins/02_nettoye_carte_provinces_45.geojson")


def arrondir(o, nd=3):
    if isinstance(o, list):
        return [arrondir(x, nd) for x in o]
    return round(o, nd) if isinstance(o, float) else o


def main():
    args = sys.argv[1:]
    sortie = Path(args[args.index("--sortie") + 1]) if "--sortie" in args else Path("05_interpretation/tableau_de_bord")
    sortie.mkdir(parents=True, exist_ok=True)
    lire = lambda f: pd.read_csv(f, sep=";")
    base, ind, bes = lire(R3 / "03_base_province.csv"), lire(R4 / "04_indice_priorite.csv"), lire(R4 / "04_besoins_horizon.csv")
    fper, sens = lire(R4 / "04_flux_par_perimetre.csv"), lire(R4 / "04_sensibilite_classement.csv")
    par = json.load(open(R3 / "03_parametres_utilises.json", encoding="utf-8"))
    num = lambda v: None if pd.isna(v) else (int(v) if float(v).is_integer() else round(float(v), 4))
    PIL = ("surcharge", "deficit_projete", "vetuste", "equite", "pression_pdi")
    provinces = {}
    bb = base.set_index("province")
    ss = sens.set_index("province")
    for r in ind.itertuples(index=False):
        b = bb.loc[r.province]
        provinces[r.province] = dict(
            region=r.region, piliers={k: num(getattr(r, k)) for k in PIL},  # piliers normalises (0 a 1) : l'indice est recalcule dans la page selon les poids
            eleves_par_salle=num(b.get("eleves_par_salle_total")), eleves_par_maitre=num(b.get("eleves_par_maitre_public")),
            edi_pour_100=num(b.get("edi_pour_100_eleves")), eleves=num(b.get("eleves_tot")), eleves_pub=num(b.get("eleves_pub")),
            salles=num(b.get("salles_tot")), salles_pub=num(b.get("salles_pub")), maitres_publics=num(b.get("maitres_pub")),
            freq_top10=num(ss.freq_top10.get(r.province)) if r.province in ss.index else None, sc={})
    for sc, g in bes.groupby("scenario", sort=False):
        for r in g.itertuples(index=False):
            provinces[r.province]["sc"][sc] = dict(
                tbs=num(r.tbs_horizon), pop=num(r.pop_6_11_horizon), eleves=num(r.eleves_horizon), hors_ecole=num(r.enfants_hors_ecole_horizon),
                deficit_salles=num(r.deficit_salles), deficit_maitres=num(r.deficit_maitres_public), excedent_maitres=num(r.excedent_maitres_public),
                a_remplacer=num(r.salles_a_remplacer))
    scen = list(bes.scenario.drop_duplicates())
    flux = {}
    for r in fper.itertuples(index=False):
        flux.setdefault(r.scenario, {}).setdefault(r.perimetre, {}).setdefault(r.regle, {}).setdefault("%g" % float(r.part_excedent_mobilisable), []).append(
            [r.origine, r.destination, int(r.maitres), num(r.distance_km)])
    passage = {}
    if (R4 / "04_passage_ancien_nouveau.csv").exists():
        for r in lire(R4 / "04_passage_ancien_nouveau.csv").itertuples(index=False):
            passage.setdefault(r.province_ancienne, []).append([r.region_nouvelle, r.province_nouvelle, round(float(r.part), 4)])
    sim = par.get("simulateur", {})
    parts = [float(x) for x in sim.get("grille_part_mobilisable", [0.0, 0.25, 0.5, 0.75, 1.0])]
    gj = json.load(open(CARTE, encoding="utf-8"))
    for ft in gj["features"]:
        ft["geometry"]["coordinates"] = arrondir(ft["geometry"]["coordinates"])
    donnees = dict(provinces=provinces, scenarios=scen, flux=flux, carte=gj, passage=passage,
                   params=dict(norme_classe=par.get("norme_eleves_par_classe_utilisee"), norme_maitre=par.get("norme_eleves_par_maitre_utilisee"),
                               annee_base=par.get("annee_base"), annee_horizon=par.get("annee_horizon"), poids=par.get("poids"),
                               parts=parts, part_defaut=float(sim.get("part_excedent_mobilisable", 0.5))))
    modele = (Path(__file__).resolve().parent / "05_interpretation_modele_tableau_de_bord.html").read_text(encoding="utf-8")
    html = modele.replace("/*__DONNEES__*/null", json.dumps(donnees, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/"))
    (sortie / "index.html").write_text(html, encoding="utf-8")
    # copie pour GitHub Pages (publication depuis le dossier docs/ de la branche principale)
    pages = Path(__file__).resolve().parents[2] / "docs"
    pages.mkdir(exist_ok=True)
    (pages / "index.html").write_text(html, encoding="utf-8")
    print("Tableau de bord ecrit : %s (%.2f Mo) ; %d provinces, scenarios %s" % (sortie / "index.html", len(html.encode("utf-8")) / 1e6, len(provinces), scen))


if __name__ == "__main__":
    main()
