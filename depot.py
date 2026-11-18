# -*- coding: utf-8 -*-
"""Prepare le depot de chaque etape : DEUX archives (donnees produites, code) + un fichier LISEZ-MOI du depot.

Nommage : EQUIPE_ETAPE_DEFI_ROLE_description_vN.extension (ROLE = engineer, architect, scientist ou analyst selon l'etape)
  ex. FasoEquiEduc_02_D3_engineer_donnees_nettoyees_controles_journaux_v1.zip
Par etape : description commencant par donnees (donnees produites), code (scripts et socle de relance) ou lisezmoi (contenu du depot).
Des controles d'anonymat du CONTENU pour les chaines de --interdits.

Usage : python depot.py --equipe NOM [--defi D3] [--version 1] [--interdits "nom1,nom2"] [--etapes 01,02,03,04] [--sortie depot]
Sortie : depot/<etape>/... et depot/MANIFESTE_depot.csv."""

import csv
import hashlib
import shutil
import sys
import zipfile
from pathlib import Path

R = Path(__file__).resolve().parent
MAX_OCTETS, MAX_TOTAL = 50 * 10**6, 500 * 10**6
ROLE_DONNEES, ROLE_CODE, ROLE_LISEZMOI = "donnees", "code", "lisezmoi"  # entrent dans la description
ROLES = {"01": "engineer", "02": "engineer", "03": "architect", "04": "scientist", "05": "analyst"}  # champ ROLE du nommage
SOCLE = ["executer.py", "depot.py", "requirements.txt", "LISEZ-MOI.txt", "README.md", "communs/outils_communs.py",
         "parametres/parametres_modele.json", "parametres/chemins_sources_modele.json"]
ETAPES = {
    "01": dict(dossier="01_collecte", desc_d="references_empreintes_inspections", desc_c="inspection_structure_sources",
               donnees=["01_collecte/references/*", "01_collecte/inspections/*"], code=["01_collecte/scripts/*.py"]),
    "02": dict(dossier="02_nettoyage", desc_d="nettoyees_controles_journaux", desc_c="scripts_nettoyage",
               donnees=["02_nettoyage/*/02_nettoye_*", "02_nettoyage/*/02_controles_*", "02_nettoyage/*/02_journal_*"],
               code=["02_nettoyage/scripts/*.py", "tests/*.py"]),
    "03": dict(dossier="03_transformation", desc_d="base_province_validation", desc_c="script_transformation",
               donnees=["03_transformation/donnees_transformees/*"], code=["03_transformation/scripts/*.py"]),
    "04": dict(dossier="04_analyse", desc_d="besoins_indice_simulateur", desc_c="scripts_analyse",
               donnees=["04_analyse/resultats/*"], code=["04_analyse/scripts/*.py"]),
    "05": dict(dossier="05_interpretation", desc_d="tableau_de_bord", desc_c="script_tableau_de_bord",
               donnees=["05_interpretation/tableau_de_bord/*"], code=["05_interpretation/scripts/*"])}
TEXTE = {".csv", ".txt", ".json", ".geojson", ".py", ".html", ".md"}


def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def trouver(motifs):
    out = []
    for m in motifs:
        out += sorted(p for p in R.glob(m) if p.is_file() and "__pycache__" not in p.parts)
    return list(dict.fromkeys(out))


def arg(a, nom, defaut=None):
    return a[a.index(nom) + 1] if nom in a else defaut


def main():
    a = sys.argv[1:]
    if "--equipe" not in a and "--prefixe" not in a:
        print(__doc__)
        return
    equipe = arg(a, "--equipe", arg(a, "--prefixe"))
    defi, ver = arg(a, "--defi", "D3"), "v" + arg(a, "--version", "1")
    interdits = [x.strip() for x in arg(a, "--interdits", "").split(",") if x.strip()]
    choix = arg(a, "--etapes", ",".join(ETAPES)).split(",")
    sortie = Path(arg(a, "--sortie", str(R / "depot")))
    if sortie.exists():
        shutil.rmtree(sortie)
    manifeste, alertes, notes, total = [], [], [], 0
    if "_" in equipe:
        notes.append("le nom d'equipe '%s' contient '_' : il se confond avec le separateur des champs ; ecrire par exemple %s" % (equipe, equipe.replace("_", "")))
    for num in [e for e in ETAPES if e in choix]:
        E = ETAPES[num]
        d = sortie / E["dossier"]
        d.mkdir(parents=True)
        base = "%s_%s_%s_%s" % (equipe, num, defi, ROLES[num])
        don = trouver(E["donnees"])
        don = [p for p in don if "scripts" not in p.relative_to(R).parts]
        cod = trouver(E["code"]) + [R / c for c in SOCLE if (R / c).exists()]
        for c in SOCLE:
            if not (R / c).exists() and c != "README.md":
                alertes.append("%s : fichier commun absent du code depose : %s (renomme ou supprime ?)" % (E["dossier"], c))
        if not don:
            alertes.append("%s : aucune donnee produite trouvee (etape non executee ?)" % E["dossier"])
        noms = {}
        for role, desc, fichiers in ((ROLE_DONNEES, E["desc_d"], don), (ROLE_CODE, E["desc_c"], cod)):
            if not fichiers:
                continue
            nom = "%s_%s_%s_%s.zip" % (base, role, desc, ver)
            with zipfile.ZipFile(d / nom, "w", zipfile.ZIP_DEFLATED) as z:
                for p in fichiers:
                    z.write(p, p.relative_to(R).as_posix())
            noms[role] = (nom, fichiers)
        # LISEZ-MOI du depot : texte de l'etape + contenu exact de chaque archive
        lm = R / E["dossier"] / "LISEZ-MOI.txt"
        L = ["DEPOT %s - %s - %s (%s)" % (num, E["dossier"], defi, ver), "",
             lm.read_text(encoding="utf-8").strip() if lm.exists() else "", "",
             "CONTENU DU DEPOT",
             "Le depot de cette etape se compose de trois fichiers : les donnees produites, le code, et ce LISEZ-MOI.", ""]
        for role in (ROLE_DONNEES, ROLE_CODE):
            if role in noms:
                nom, fichiers = noms[role]
                L.append("%s  (%d fichiers)" % (nom, len(fichiers)))
                L += ["   - %s  (%.1f Ko)" % (p.relative_to(R).as_posix(), p.stat().st_size / 1e3) for p in fichiers]
                L.append("")
        L += ["RELANCER", "Dans le projet : python python.py --seulement %s (voir LISEZ-MOI.txt du code pour l'installation et chemins_sources.json)." % num,
              "Les donnees brutes du Data Pack ne sont pas redeposees ; leurs empreintes SHA-256 figurent a l'etape 01."]
        (d / ("%s_%s_%s_%s.txt" % (base, ROLE_LISEZMOI, "contenu_du_depot", ver))).write_text("\n".join(L) + "\n", encoding="utf-8")
        for f in sorted(d.iterdir()):
            n = f.stat().st_size
            total += n
            if n > MAX_OCTETS:
                alertes.append("%s : %s fait %.1f Mo (maximum 50)" % (E["dossier"], f.name, n / 1e6))
            manifeste.append([E["dossier"], f.name, n, sha(f)])
            contenus = []
            if f.suffix.lower() in TEXTE:
                contenus.append((f.name, f.read_bytes()))
            elif f.suffix.lower() == ".zip":
                with zipfile.ZipFile(f) as z:
                    contenus += [(f.name + " > " + i, z.read(i)) for i in z.namelist()] + [(f.name + " (noms internes)", "\n".join(z.namelist()).encode())]
            for nom_c, octets in contenus:
                t = octets.decode("utf-8", "ignore").lower()
                for mot in interdits:
                    if mot.lower() in t:
                        alertes.append("ANONYMAT : '%s' trouve dans %s / %s" % (mot, E["dossier"], nom_c))
    if total > MAX_TOTAL:
        alertes.append("total %.1f Mo (maximum 500)" % (total / 1e6))
    with open(sortie / "MANIFESTE_depot.csv", "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh, delimiter=";")
        w.writerow(["etape", "fichier", "octets", "sha256"])
        w.writerows(manifeste)
    for m in manifeste:
        print("%-18s %-90s %8.2f Mo" % (m[0], m[1], m[2] / 1e6))
    print("total %.2f Mo ; chaines interdites controlees dans le contenu : %s" % (total / 1e6, interdits or "aucune (utiliser --interdits)"))
    for x in notes:
        print("NOTE :", x)
    print("\nCONTROLES :", "aucune alerte" if not alertes else "")
    for x in alertes:
        print("   !!", x)
    print("-> dossier pret :", sortie, "(MANIFESTE_depot.csv pour garder la trace)")


if __name__ == "__main__":
    main()
