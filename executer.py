# -*- coding: utf-8 -*-
"""Lance la chaine complete (etapes 01 collecte -> 05 interpretation) a partir de parametres/chemins_sources.json.
Cree les dossiers d'etape s'ils n'existent pas, ecrit les empreintes SHA-256 et les versions utilisees, puis execute chaque script
dans l'ordre. Une etape dont la source n'est pas renseignee est ignoree. A lancer depuis la racine du projet :
    python executer.py [--seulement 01|02|03|04|05] [--sans-transformation] [--arreter-si-erreur]
Tout s'execute en local sur la machine."""

import csv
import hashlib
import json
import platform
import subprocess
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parent
ETAPES = ["01_collecte", "02_nettoyage", "03_transformation", "04_analyse", "05_interpretation"]
S = lambda etape, nom: str(RACINE / etape / "scripts" / nom)
N2 = RACINE / "02_nettoyage"
D = {  # dossiers de sortie
    "classeur": N2 / "classeur_primaire_2016-2025", "cns": N2 / "cns530_annuaire_2024-25",
    "proj": N2 / "projections_insd_provinces_2020-2035", "projn": N2 / "projections_insd_nationales",
    "rec": N2 / "recoupements_classeur_cns530_projections", "cod": N2 / "cod_ab_limites_administratives",
    "carte": N2 / "carte_provinces_voisins", "esu": N2 / "esu_rapports_2026", "osm": N2 / "osm_ecoles",
    "pdi": N2 / "pdi_conasur_2022-12", "idps4": N2 / "pdi_idps4_serie", "rgph": N2 / "rgph2019_localites"}
F = {
    "ref": D["cns"] / "02_nettoye_cns530_referentiel_provinces.csv", "cns": D["cns"] / "02_nettoye_cns530_long.csv",
    "classeur": D["classeur"] / "02_nettoye_classeur_tableaux_long.csv", "proj": D["proj"] / "02_nettoye_projections_provinces_long.csv",
    "com": D["cod"] / "02_nettoye_cod_ab_communes_ancien_decoupage.csv", "cor": D["cod"] / "02_nettoye_cod_ab_correspondance_provinces_ancien_nouveau.csv",
    "poly": D["carte"] / "02_nettoye_carte_voisins_provinces.csv"}


MOTIFS = {  # source -> (motifs de nom, 'dossier' si dossier). Recherche insensible a la casse, dans tout le dossier du Data Pack.
    "classeur_primaire": (["*prescolaire*primaire*2016*2025*.xlsx"], False),
    "cns530_annuaire": (["cns530*.csv"], False),
    "projections_insd": (["insd_rgph2019_vol4_projections*.csv"], False),
    "cod_ab_dossier": (["cod-ab*", "cod_ab*"], True),
    "provinces_geojson": (["bfa_provinces_boundaries*.geojson"], False),
    "adminlines_csv": (["*bfa_adminlines*.csv"], False),
    "esu_janvier_2026": (["*esu*janvier*2026*.csv"], False),
    "esu_fevrier_2026": (["*esu*vrier*2026*.csv"], False),
    "osm_ecoles": (["ecoles_osm_burkina*.csv"], False),
    "pdi_conasur_2022_12": (["situation-des-pdi-par-communes-accueil-du-31-decembre-2022*31122022*.csv"], False),
    "pdi_conasur_2022_12_statistiques": (["situation-des-pdi-par-communes-accueil-du-31-decembre-2022*statistiques*.csv"], False),
    "idps4": (["idps4*tableau*.csv"], False),
    "rgph2019_localites": (["*rgph2019*localit*.csv"], False)}


def detecter(racine, cfg):
    """complete les chemins vides de cfg en cherchant dans racine ; ambigu ou absent -> laisse vide et le dit"""
    racine = Path(racine)
    tous = [p for p in racine.rglob("*")]
    print("DETECTION dans", racine)
    for cle, (motifs, dossier) in MOTIFS.items():
        if cfg.get(cle):
            continue
        trouves = sorted({p for p in tous if (p.is_dir() if dossier else p.is_file()) and any(p.match(m) or p.name.lower() == m for m in motifs)
                          or (((p.is_dir() if dossier else p.is_file())) and any(__import__("fnmatch").fnmatch(p.name.lower(), m) for m in motifs))})
        if len(trouves) == 1:
            cfg[cle] = str(trouves[0])
            print("   %-34s -> %s" % (cle, trouves[0].relative_to(racine)))
        elif not trouves:
            print("   %-34s : INTROUVABLE (etape ignoree)" % cle)
        else:
            print("   %-34s : %d correspondances, ambigu (etape ignoree) : %s" % (cle, len(trouves), [t.name for t in trouves][:4]))
    return cfg


def sha256(chemin):
    h = hashlib.sha256()
    with open(chemin, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def lancer(nom, cmd, erreurs, arreter):
    print("\n>>>", nom)
    r = subprocess.run([sys.executable, "-X", "utf8"] + [str(c) for c in cmd], cwd=RACINE)
    if r.returncode != 0:
        erreurs.append(nom)
        print("   ECHEC :", nom)
        if arreter:
            sys.exit(1)


def main():
    args = sys.argv[1:]
    seul = args[args.index("--seulement") + 1] if "--seulement" in args else None
    arreter = "--arreter-si-erreur" in args
    for e in ETAPES:
        (RACINE / e).mkdir(exist_ok=True)
    for d in list(D.values()) + [RACINE / "01_collecte/references", RACINE / "01_collecte/inspections", RACINE / "03_transformation/donnees_transformees", RACINE / "04_analyse/resultats"]:
        d.mkdir(parents=True, exist_ok=True)
    f_cfg = RACINE / "parametres/chemins_sources.json"
    if not f_cfg.exists():  # premiere utilisation : copie du modele vide
        f_cfg.write_text((RACINE / "parametres/chemins_sources_modele.json").read_text(encoding="utf-8"), encoding="utf-8")
    cfg = json.loads(f_cfg.read_text(encoding="utf-8"))
    if cfg.get("dossier_datapack"):
        cfg = detecter(cfg["dossier_datapack"], cfg)
    P = {k: v for k, v in cfg.items() if not k.startswith("_") and k not in ("alias_provinces", "dossier_datapack") and v}
    if not P and seul not in ("03", "04", "05"):
        print("\nAUCUNE SOURCE : renseigner 'dossier_datapack' (ou les chemins) dans parametres/chemins_sources.json, puis relancer.")
        print("   fichier lu :", RACINE / "parametres/chemins_sources.json")
        return
    # --- 01 : empreintes et versions
    if seul in (None, "01"):
        import importlib
        vers = ["python %s" % platform.python_version()]
        for m in ("pandas", "numpy", "openpyxl", "scipy"):
            try:
                vers.append("%s %s" % (m, importlib.import_module(m).__version__))
            except Exception:
                vers.append("%s non installe" % m)
        (RACINE / "01_collecte/references/01_versions_utilisees.txt").write_text("\n".join(vers), encoding="utf-8")
        with open(RACINE / "01_collecte/references/01_empreintes_sources.csv", "w", encoding="utf-8", newline="") as fh:
            w = csv.writer(fh, delimiter=";")
            w.writerow(["source", "fichier", "octets", "sha256"])
            for k, v in P.items():
                p = Path(v)
                if p.is_file():
                    w.writerow([k, p.name, p.stat().st_size, sha256(p)])
                elif p.is_dir():
                    for f in sorted(p.rglob("*")):
                        if f.is_file():
                            w.writerow([k, f.relative_to(p).as_posix(), f.stat().st_size, sha256(f)])
                else:
                    print("   source introuvable :", k, v)
        print("empreintes et versions ecrites dans 01_collecte/references")
    erreurs = []
    if seul in (None, "02"):
        e = "02_nettoyage"
        if "cns530_annuaire" in P:
            lancer("cns530", [S(e, "02_nettoyage_cns530_annuaire.py"), P["cns530_annuaire"], D["cns"]], erreurs, arreter)
        if "classeur_primaire" in P:
            lancer("classeur", [S(e, "02_nettoyage_classeur_tableaux.py"), P["classeur_primaire"], D["classeur"]], erreurs, arreter)
        if "projections_insd" in P:
            lancer("projections provinces", [S(e, "02_nettoyage_projections_provinces.py"), P["projections_insd"], D["proj"], "--referentiel", F["ref"]], erreurs, arreter)
            lancer("projections nationales", [S(e, "02_nettoyage_projections_nationales.py"), P["projections_insd"], D["projn"], "--regional", F["proj"]], erreurs, arreter)
            if "classeur_primaire" in P and "cns530_annuaire" in P:
                lancer("recoupements", [S(e, "02_nettoyage_recoupements_convention.py"), F["classeur"], F["cns"], F["proj"], D["rec"]], erreurs, arreter)
        if "cod_ab_dossier" in P:
            lancer("cod-ab", [S(e, "02_nettoyage_cod_ab_decoupage.py"), P["cod_ab_dossier"], "--referentiel", F["ref"], D["cod"]], erreurs, arreter)
        if "rgph2019_localites" in P:
            lancer("rgph 2019 localites", [S(e, "02_nettoyage_rgph2019_localites.py"), P["rgph2019_localites"], "--communes", F["com"], D["rgph"]], erreurs, arreter)
        if "provinces_geojson" in P:
            lancer("carte", [S(e, "02_nettoyage_carte_provinces_voisins.py"), P["provinces_geojson"], F["ref"], D["carte"]], erreurs, arreter)
        if "adminlines_csv" in P:
            lancer("voisins adminlines", [S(e, "02_nettoyage_carte_voisins_adminlines.py"), P["adminlines_csv"], F["com"], "--polygones", F["poly"], D["carte"]], erreurs, arreter)
        esu = [P[k] for k in ("esu_janvier_2026", "esu_fevrier_2026") if k in P]
        if esu:
            cmd = [S(e, "02_nettoyage_esu_2026.py"), D["esu"]] + esu + ["--correspondance", F["cor"]]
            for a, b in cfg.get("alias_provinces", {}).items():
                cmd += ["--alias", "%s=%s" % (a, b)]
            lancer("esu 2026", cmd, erreurs, arreter)
        if "osm_ecoles" in P:
            lancer("osm", [S(e, "02_nettoyage_osm_ecoles.py"), P["osm_ecoles"], F["com"], "--cns530", F["cns"], D["osm"]], erreurs, arreter)
        if "pdi_conasur_2022_12" in P:
            cmd = [S(e, "02_nettoyage_pdi_conasur.py"), P["pdi_conasur_2022_12"], F["ref"]]
            if "pdi_conasur_2022_12_statistiques" in P:
                cmd += ["--stats", P["pdi_conasur_2022_12_statistiques"]]
            lancer("pdi conasur", cmd + [D["pdi"]], erreurs, arreter)
        if "idps4" in P:
            cmd = [S(e, "02_nettoyage_pdi_idps4.py"), P["idps4"], F["com"]]
            if "pdi_conasur_2022_12_statistiques" in P:
                cmd += ["--stats", P["pdi_conasur_2022_12_statistiques"]]
            lancer("pdi idps4", cmd + [D["idps4"]], erreurs, arreter)
    if seul in (None, "03") and "--sans-transformation" not in args:
        lancer("transformation", [S("03_transformation", "03_transformation_base_province.py"), "--params", RACINE / "parametres/parametres_modele.json",
                                  "--sortie", RACINE / "03_transformation/donnees_transformees"], erreurs, arreter)
    if seul in (None, "04") and "--sans-transformation" not in args:
        for nom, script in (("analyse : besoins et indice", "04_analyse_besoins_indice_priorite.py"), ("analyse : simulateur", "04_analyse_simulateur_redeploiement.py"),
                             ("analyse : nouveau decoupage", "04_analyse_nouveau_decoupage.py")):
            lancer(nom, [S("04_analyse", script), "--params", RACINE / "parametres/parametres_modele.json", "--sortie", RACINE / "04_analyse/resultats"], erreurs, arreter)
    if seul in (None, "05") and "--sans-transformation" not in args:
        lancer("interpretation : tableau de bord", [S("05_interpretation", "05_interpretation_tableau_de_bord.py"), "--sortie", RACINE / "05_interpretation/tableau_de_bord"], erreurs, arreter)
    print("\nTERMINE.", "Echecs : %s" % erreurs if erreurs else "Aucun echec.")


if __name__ == "__main__":
    main()
