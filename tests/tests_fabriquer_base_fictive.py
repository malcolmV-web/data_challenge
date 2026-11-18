# -*- coding: utf-8 -*-
"""Fabrique de fausses donnees NETTOYEES (10 provinces fictives) aux emplacements attendus par les etapes 03 et 04, pour tester la chaine
sans donnees reelles. Usage : python tests/tests_fabriquer_base_fictive.py <racine_de_test>"""

import random, sys
from pathlib import Path
import pandas as pd
R = Path(sys.argv[1]); rnd = random.Random(3)
provs = [("P%02d" % i, "R%d" % (i // 4)) for i in range(10)]
L = []
def add(**k): L.append(k)
pop, pdi, esu, vois = [], [], [], []
for i, (p, r) in enumerate(provs):
    el = rnd.randint(8000, 90000); crise = i < 3
    for st, part in (("PUBLIC", 0.8), ("PRIVE", 0.2), ("PUBLIC_PRIVE", 1.0)):
        e = el * part
        for ind, val in (("ecoles", e / 250), ("salles", e / rnd.uniform(40, 70)), ("groupes", e / 50), ("maitres", e / rnd.uniform(38, 65)), ("eleves", e)):
            add(section="I.1", type_ligne="detail", region=r, province=p, indicateur=ind, statut=st, valeur=round(val))
    for ind in ("salles", "ecoles"):
        add(section="V.2", type_ligne="detail", region=r, province=p, indicateur=ind, statut="PUBLIC_PRIVE", milieu="TOTAL", valeur=1000)
        add(section="V.2", type_ligne="detail", region=r, province=p, indicateur=ind, statut="PUBLIC_PRIVE", milieu="RURAL", valeur=rnd.randint(300, 950))
    for ind, val in (("ecoles_fonctionnelles", 300), ("eau_potable", rnd.randint(80, 290)), ("latrines", rnd.randint(80, 290)), ("electricite", rnd.randint(10, 200))):
        add(section="V.4", type_ligne="detail", region=r, province=p, indicateur=ind, statut="PUBLIC_PRIVE", valeur=val)
    for ind, val in (("salles_total", 1000), ("murs_paille_banco_autre", rnd.randint(10, 300)), ("etat_mauvais", rnd.randint(10, 300))):
        add(section="VI.4", sous_section="VI.4.1", type_ligne="detail", region=r, province=p, indicateur=ind, statut="PUBLIC_PRIVE", valeur=val)
    for ind, val in (("salles_total", 1000), ("toit_banco", rnd.randint(0, 100)), ("toit_paille", rnd.randint(0, 100)), ("toit_sans_toit", rnd.randint(0, 30))):
        add(section="VI.4", sous_section="VI.4.2", type_ligne="detail", region=r, province=p, indicateur=ind, statut="PUBLIC_PRIVE", valeur=val)
    tbs = rnd.uniform(0.1, 0.4) if crise else rnd.uniform(0.7, 1.1)
    for N in range(2020, 2025):
        e = el * (1 + 0.03 * (N - 2024)) * (1.5 - 0.1 * (N - 2020) if crise else 1)
        for ind, val in (("eleves_total", e), ("eleves_filles", e * 0.49), ("eleves_garcons", e * 0.51)):
            add(section="VIII.1", type_ligne="detail", region=r, province=p, indicateur=ind, annee_scolaire="%d-%d" % (N, N + 1), valeur=round(val))
    for a in range(2020, 2036):
        pop.append(dict(province=p, annee=a, pop_6_11_total=round(el / tbs * (1 + 0.025 * (a - 2024))), alerte_controle=0))
    pdi.append(dict(province=p, pdi_total=rnd.randint(0, 50000), pdi_enfants=100, date="2023-03-31"))
    for o in ("prescolaire", "primaire", "cebnf"):
        esu.append(dict(rapport="x", mois="2026-02", numero=4, indicateur="edi", statut="", portee="mois", ordre=o, sexe="T", province_ancienne=p, valeur=rnd.randint(0, 6000), nb_allocations_prorata=0))
    esu.append(dict(rapport="x", mois="2026-02", numero=2, indicateur="structures", statut="delocalisee", portee="cumul", ordre="total", sexe="total", province_ancienne=p, valeur=rnd.randint(0, 40), nb_allocations_prorata=0))
    for j in (i - 1, i + 1):
        if 0 <= j < 10:
            vois.append(dict(province=p, voisine=provs[j][0], nb_segments=1))
def w(df, chemin):
    f = R / chemin; f.parent.mkdir(parents=True, exist_ok=True); pd.DataFrame(df).to_csv(f, sep=";", index=False)
w(L, "02_nettoyage/cns530_annuaire_2024-25/02_nettoye_cns530_long.csv")
w([dict(province=p, region=r) for p, r in provs], "02_nettoyage/cns530_annuaire_2024-25/02_nettoye_cns530_referentiel_provinces.csv")
w(pop, "02_nettoyage/projections_insd_provinces_2020-2035/02_nettoye_projections_population_cible_province.csv")
w(pdi, "02_nettoyage/pdi_idps4_serie/02_nettoye_pdi_idps4_province_derniere.csv")
w(esu, "02_nettoyage/esu_rapports_2026/02_nettoye_esu_2026_province_ancienne.csv")
w(vois, "02_nettoyage/carte_provinces_voisins/02_nettoye_carte_voisins_provinces_adminlines.csv")
import json
feats = []
for i, (p_, r_) in enumerate(provs):
    x, y = -5 + (i % 5) * 1.2, 10 + (i // 5) * 1.2
    feats.append({"type": "Feature", "properties": {"province": p_, "region": r_}, "geometry": {"type": "Polygon", "coordinates": [[[x, y], [x + 1.1, y], [x + 1.1, y + 1.1], [x, y + 1.1], [x, y]]]}})
(R / "02_nettoyage/carte_provinces_voisins/02_nettoye_carte_provinces_45.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": feats}), encoding="utf-8")
print("donnees fictives ecrites dans", R)
