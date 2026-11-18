# -*- coding: utf-8 -*-
"""Extraction des rapports mensuels ESU 2026 (education en situation d'urgence), CSV issus de PDF NON OCR, NOUVEAU decoupage
(17 regions, 47 provinces). Tableaux regionaux (T1 a T13) et annexes provinciales (structures, eleves deplaces internes).

Usage : python 02_nettoyage_esu_2026.py <dossier_sortie> <rapport1.csv> [<rapport2.csv> ...] [--correspondance 02_nettoye_cod_ab_correspondance_provinces_ancien_nouveau.csv]
  Exemple : python 02_nettoyage_esu_2026.py 02_nettoyage/esu_rapports_2026 "Rapport_statistique_mensuel_ESU_Janvier_2026.csv" "Rapport_statistique_mensuel_ESU_Février_2026.csv" --correspondance 02_nettoyage/cod_ab_limites_administratives/02_nettoye_cod_ab_correspondance_provinces_ancien_nouveau.csv
Sorties : 02_nettoye_esu_2026_long.csv (une ligne par valeur), 02_nettoye_esu_2026_province_ancienne.csv (annexes ramenees aux 45 provinces anciennes),
          02_controles_esu_2026.csv (comptages et ecarts relatifs seulement), 02_journal_esu_2026.csv.
"""

import csv
import re
import sys
import difflib
from pathlib import Path
import pandas as pd
import sys as _sys
from pathlib import Path as _P
_sys.path.insert(0, str(_P(__file__).resolve().parents[2] / 'communs'))
import outils_communs as oc
from outils_communs import norm_label, norm_libre, to_number, nettoyer_cellule

csv.field_size_limit(10 ** 8)
NIV = {"PRESCOLAIRE": "prescolaire", "PRIMAIRE": "primaire", "CEBNF": "cebnf", "TOTAL": "total", "GENERAL": "total", "TOTAL GENERAL": "total"}
SEXE = {"G": "G", "GARCONS": "G", "H": "G", "HOMMES": "G", "M": "G", "MASCULIN": "G", "F": "F", "FILLES": "F", "FEMMES": "F", "FEMININ": "F", "T": "T"}
MOTS_ENTETE = set(NIV) | set(SEXE) | {"REGION", "PROVINCE", "ORDRE D ENSEIGNEMENT", "ORDRE ENSEIGNEMENT", "SEXE"}
TITRE = re.compile(r"^\s*(tableau|annexe)\s*(\d+)\s*[:\-–]?\s*(.*)$", re.I)
ROMAIN = re.compile(r"^[IVXL]+$")
MOIS = ["janvier", "fevrier", "mars", "avril", "mai", "juin", "juillet", "aout", "septembre", "octobre", "novembre", "decembre"]
ALIAS_USER = {}
ALIAS_PROV = {"KOMONDJARI": "KOMONDJARI", "KOMANDJARI": "KOMONDJARI"}

journal, ctrl_lignes, longues = [], [], []


def jr(gravite, message, rapport=""):
    journal.append(dict(gravite=gravite, rapport=rapport, message=message))


def ctrl(rapport, nom, ok, ecart=0.0):
    ctrl_lignes.append(dict(rapport=rapport, controle=nom, ok=int(bool(ok)), ecart_relatif=float(ecart)))


def lire_rapport(chemin):
    """-> liste de (page, [cellules non vides apres nettoyage]) dans l'ordre du fichier"""
    lignes = []
    with open(chemin, encoding="utf-8-sig", newline="") as fh:
        lect = csv.reader(fh, delimiter=";")
        en_tete = next(lect)
        i0 = en_tete.index("nb_cellules") + 1
        fin = en_tete.index("remarque_collecte") if "remarque_collecte" in en_tete else len(en_tete)
        i_page = en_tete.index("page")
        for n, r in enumerate(lect, 2):
            cells = []
            for v in r[i0:fin]:
                v2, note = nettoyer_cellule(v)
                if note:
                    oc.NOTES_IGNOREES.append((Path(chemin).name, n, 0))
                if v2 is not None and str(v2).strip():
                    cells.append(re.sub(r"\s+", " ", str(v2)).strip())
            try:
                page = int(float(r[i_page]))
            except Exception:
                page = -1
            if cells:
                lignes.append((page, cells))
    return lignes


def classer(cells):
    """'titre' | 'entete' | 'donnee' | 'texte' | 'indice' ; pour 'donnee' renvoie aussi (etiquettes, nombres)"""
    texte = " ".join(cells)
    if TITRE.match(texte):
        if re.search(r"\.{4,}|\u2026", texte):
            return "texte", cells, None  # ligne de table des matieres (points de conduite)
        return "titre", cells, None
    nums = [to_number(c) for c in cells]
    k = 0
    while k < len(cells) and nums[k] is None:
        k += 1
    etiq, vals = cells[:k], nums[k:]
    if vals and all(v is not None for v in vals) and 1 <= len(etiq) <= 2 and all(len(e) <= 40 for e in etiq):
        return "donnee", etiq, vals
    if not vals and cells and TITRE.match(" ".join(cells)):
        return "titre", cells, None
    if not vals and all(norm_label(c) in MOTS_ENTETE for c in cells):
        return "entete", cells, None
    if not vals and len(cells) == 1 and ROMAIN.match(norm_label(cells[0])):
        return "indice", cells, None
    if not vals and len(cells) == 1 and len(cells[0]) <= 40:
        return "indice_label", cells, None  # nom de region seul (cellule fusionnee centree)
    return "texte", cells, None


def indic_du_titre(titre):
    t = norm_libre(titre)
    ind = "edi" if ("deplaces internes" in t or "edi" in t.split()) else "enseignants" if "enseignant" in t else "eleves" if "eleve" in t else "structures" if "structure" in t else "inconnu"
    statut = "rouverte" if re.search(r"r[e]?ouvert", t) else "delocalisee" if "delocalis" in t else ""
    portee = "cumul" if "ensemble des" in t else "mois"
    return ind, statut, portee


def niveau_du_titre(titre):
    t = norm_label(titre)
    trouves = [n for n, rx in (("prescolaire", r"\bPRESCOLAIRE"), ("primaire", r"\bPRIMAIRE"), ("cebnf", r"\bCEBNF|NON FORMEL")) if re.search(rx, t)]
    return trouves[0] if len(trouves) == 1 else None


def colonnes(etat, n, rapport):
    """liste de (ordre, sexe) pour n valeurs, d'apres les lignes d'en-tete accumulees ; None si impossible"""
    flat = [c for row in etat["entete"] for c in row]
    nf = [norm_label(c) for c in flat]
    i_s = next((i for i, c in enumerate(nf) if c in ("G", "F", "GARCONS", "FILLES", "H", "HOMMES", "FEMMES")), None)
    if i_s is not None:
        j = i_s
        while j < len(nf) and nf[j] in ("G", "F", "T", "GARCONS", "FILLES", "TOTAL", "H", "HOMMES", "FEMMES"):
            j += 1
        sexes = [SEXE.get(c, "T") for c in nf[i_s:j]]
        for per in range(1, len(sexes) + 1):  # G F T repete pour chaque ordre d'enseignement : on garde un seul cycle
            if len(sexes) % per == 0 and sexes == sexes[:per] * (len(sexes) // per):
                sexes = sexes[:per]
                break
        niv = []
        for c in nf[:i_s]:
            if c in NIV and NIV[c] not in niv:
                niv.append(NIV[c])
        if not niv:
            h = niveau_du_titre(etat["titre"])
            if h is None and etat["kind"] == "annexe" and etat["num"] in (3, 4, 5):
                h = {3: "prescolaire", 4: "primaire", 5: "cebnf"}[etat["num"]]
                jr("ATTENTION", "annexe %d : ordre d'enseignement non lu dans le titre, deduit du numero (hypothese, verifie par le controle annexes vs Tableau 13)" % etat["num"], rapport)
            niv = [h or "inconnu"]
        if len(niv) * len(sexes) != n:
            jr("ERREUR", "%s %s : %d valeurs par ligne, %d niveaux x %d sexes attendus" % (etat["kind"], etat["num"], n, len(niv), len(sexes)), rapport)
            return None
        return [(o, s) for o in niv for s in sexes]
    niv = []
    for c in nf:
        if c in NIV and NIV[c] not in niv:
            niv.append(NIV[c])
    if "total" in niv and niv[-1] != "total":
        niv.remove("total")
        niv.append("total")
        jr("INFO", "%s %s : 'Total' deplace en derniere colonne (en-tete sur deux lignes) ; valide par le controle somme des ordres = total" % (etat["kind"], etat["num"]), rapport)
    sans = [x for x in niv if x != "total"]
    if n == len(niv):
        pass
    elif n == len(sans) + 1:
        niv = sans + ["total"]
    else:
        jr("ERREUR", "%s %s : %d valeurs par ligne mais colonnes lues = %s ; cellules d'en-tete vues : %s" % (etat["kind"], etat["num"], n, niv, [" | ".join(r) for r in etat["entete"]]), rapport)
        return None
    return [(o, "total") for o in niv]


def vider(etat, rapport, page_fin):
    """ecrit les lignes en attente d'une annexe sans 'Total region' final"""
    if etat and etat["tampon"]:
        jr("ATTENTION", "%s %s : %d province(s) sans ligne 'Total region' ensuite (region laissee vide)" % (etat["kind"], etat["num"], len(etat["tampon"])), rapport)
        for ligne in etat["tampon"]:
            longues.extend(ligne)
        etat["tampon"] = []


def traiter(chemin):
    rapport = Path(chemin).stem
    mois = None
    t = norm_libre(rapport)
    for i, m in enumerate(MOIS, 1):
        mm = re.search(m + r".{0,3}(20\d\d)", t)
        if mm:
            mois = "%s-%02d" % (mm.group(1), i)
    lignes = lire_rapport(chemin)
    etat = None
    dedans = 0

    def nouvelle(kind, num, titre, page):
        ind, statut, portee = indic_du_titre(titre)
        return dict(kind=kind, num=num, titre=titre, page=page, entete=[], cols=None, has_data=False, tampon=[], hints=set(),
                    ind=ind, statut=statut, portee=portee, geo=None, regions_lues=[], total_gen=None, ok=True)

    def sortie(etat, region, prov, typ, geo, valeurs, page):
        out = []
        for (o, s), v in zip(etat["cols"], valeurs):
            out.append(dict(rapport=rapport, mois=mois, page=page, source=etat["kind"], numero=etat["num"], indicateur=etat["ind"], statut=etat["statut"],
                            portee=etat["portee"], niveau_geo=geo, type_ligne=typ, region_nouvelle=region, province_nouvelle=prov,
                            ordre=o, sexe=s, valeur=v))
        return out

    def fermer(etat, page):
        if not etat:
            return
        vider(etat, rapport, page)
        if not etat["has_data"] and etat["entete"]:
            jr("ATTENTION", "%s %s : aucune ligne de donnees lue (titre : %s)" % (etat["kind"], etat["num"], etat["titre"][:60]), rapport)

    for page, cells in lignes:
        cl, a, b = classer(cells)
        if cl == "titre":
            fermer(etat, page)
            m = TITRE.match(" ".join(cells))
            etat = nouvelle(m.group(1).lower(), int(m.group(2)), " ".join(cells), page)
            continue
        if etat is None:
            continue
        if cl == "entete":
            if etat["cols"] is None:
                etat["entete"].append(cells)
            continue
        if cl == "texte":
            if etat["has_data"] and len(" ".join(cells)) > 50:
                fermer(etat, page)
                etat = None
            elif not etat["has_data"] and etat["entete"] and etat["cols"] is None:
                etat["entete"].append(cells)
                etat["entete_texte"] = etat.get("entete_texte", 0) + 1
            elif not etat["has_data"] and not etat["entete"]:
                etat["titre"] += " " + " ".join(cells)
                etat["ind"], etat["statut"], etat["portee"] = indic_du_titre(etat["titre"])
            continue
        if cl in ("indice", "indice_label"):
            if cl == "indice_label":
                etat["hints"].add(norm_label(cells[0]))
            elif not etat["has_data"] and not etat["entete"]:
                pass
            continue
        # donnee
        etiq, vals = a, b
        if etat["cols"] is None:
            etat["geo"] = "province" if any(norm_label(c) == "PROVINCE" for r in etat["entete"] for c in r) else "region"
            etat["cols"] = colonnes(etat, len(vals), rapport)
            if etat["cols"] is None:
                etat = None
                continue
        if len(vals) != len(etat["cols"]):
            jr("ATTENTION", "%s %s page %d : ligne ignoree (%d valeurs au lieu de %d)" % (etat["kind"], etat["num"], page, len(vals), len(etat["cols"])), rapport)
            continue
        if any(v is not None and v != int(v) for v in vals):
            jr("ATTENTION", "%s %s page %d : valeur non entiere" % (etat["kind"], etat["num"], page), rapport)
        etat["has_data"] = True
        lab = norm_label(etiq[-1])
        lab0 = norm_label(etiq[0])
        est_total = lab0.startswith("TOTAL")
        if est_total:
            reste = lab0[5:].strip()
            if reste in ("", "GENERAL"):
                etat["total_gen"] = vals
                if etat["geo"] == "province":
                    # somme des totaux regionaux = total general
                    sommes = etat["regions_lues"]
                    if sommes:
                        for k, (o, s) in enumerate(etat["cols"]):
                            tot = sum(x[k] for x in sommes)
                            ecart = abs(tot - vals[k]) / vals[k] if vals[k] else (0 if tot == 0 else 1)
                            ctrl(rapport, "annexe : somme des regions = total general", ecart < 1e-9, ecart)
                    vider(etat, rapport, page)
                longues.extend(sortie(etat, None, None, "national", "national", vals, page))
            else:
                reg = reste
                if etat["geo"] != "province":
                    jr("ATTENTION", "%s %s : ligne 'Total %s' dans un tableau regional" % (etat["kind"], etat["num"], reg), rapport)
                tampon = etat["tampon"]
                if not tampon:
                    jr("ATTENTION", "annexe %s : 'Total %s' sans province avant" % (etat["num"], reg), rapport)
                for k, (o, s) in enumerate(etat["cols"]):
                    tot = sum(l[k]["valeur"] for l in tampon)
                    ecart = abs(tot - vals[k]) / vals[k] if vals[k] else (0 if tot == 0 else 1)
                    ctrl(rapport, "annexe : somme des provinces = total region", ecart < 1e-9, ecart)
                for l in tampon:
                    for d in l:
                        d["region_nouvelle"] = reg
                    longues.extend(l)
                etat["tampon"] = []
                etat["regions_lues"].append(vals)
                longues.extend(sortie(etat, reg, None, "sous_total", "region", vals, page))
            continue
        if etat["geo"] == "province":
            region = norm_label(etiq[0]) if len(etiq) == 2 else None
            etat["tampon"].append(sortie(etat, region, lab, "detail", "province", vals, page))
        else:
            if lab == "":
                continue
            etat["regions_lues"].append(vals)
            longues.extend(sortie(etat, lab, None, "detail", "region", vals, page))
        if len(etiq) == 2:
            pass
    fermer(etat, 0)
    return rapport, mois


def controles_croises(df, rapport):
    d = df[df.rapport == rapport]
    # 1) tableaux regionaux : somme des regions = ligne 'Total'
    tr = d[(d.source == "tableau") & (d.niveau_geo == "region")]
    for (num, o, s), g in tr.groupby(["numero", "ordre", "sexe"]):
        nat = d[(d.source == "tableau") & (d.numero == num) & (d.niveau_geo == "national") & (d.ordre == o) & (d.sexe == s)]
        if len(nat):
            tot = g.valeur.sum()
            v = float(nat.valeur.iloc[0])
            ecart = abs(tot - v) / v if v else (0 if tot == 0 else 1)
            ctrl(rapport, "tableaux regionaux : somme des regions = Total", ecart < 1e-9, ecart)
    # 2) somme des ordres = total ; G + F = T (tous niveaux geographiques, lignes de detail et totaux)
    cles = ["source", "numero", "niveau_geo", "type_ligne", "region_nouvelle", "province_nouvelle", "indicateur", "statut", "portee"]
    p = d.pivot_table(index=cles + ["sexe"], columns="ordre", values="valeur", aggfunc="first", dropna=False).reset_index()
    if "total" in p.columns:
        autres = [c for c in ("prescolaire", "primaire", "cebnf") if c in p.columns]
        q = p.dropna(subset=["total"])
        q = q[q[autres].notna().sum(axis=1) >= 2]
        if autres and len(q) and q[autres].notna().all(axis=1).any():
            q = q.dropna(subset=autres)
            for _, r in q.iterrows():
                ecart = abs(r[autres].sum() - r["total"]) / r["total"] if r["total"] else 0
                ctrl(rapport, "somme des ordres = total", ecart < 1e-9, ecart)
    ps = d.pivot_table(index=cles + ["ordre"], columns="sexe", values="valeur", aggfunc="first").reset_index()
    if {"G", "F", "T"} <= set(ps.columns):
        q = ps.dropna(subset=["G", "F", "T"])
        for _, r in q.iterrows():
            ecart = abs(r["G"] + r["F"] - r["T"]) / r["T"] if r["T"] else 0
            ctrl(rapport, "garcons + filles = total", ecart < 1e-9, ecart)
    # 3) region (tableau) = sous-total region (annexe) : structures cumulees, EDI
    a = d[(d.source == "annexe") & (d.type_ligne == "sous_total")]
    t = d[(d.source == "tableau") & (d.niveau_geo == "region") & (d.portee == "cumul")]
    t2 = d[(d.source == "tableau") & (d.niveau_geo == "region") & (d.indicateur == "edi")]
    t = pd.concat([t, t2]).drop_duplicates()
    cle = ["indicateur", "statut", "region_nouvelle", "ordre", "sexe"]
    t_idx = t.set_index(cle).valeur.to_dict() if len(t) else {}
    for _, r in a.iterrows():
        k = (r.indicateur, r.statut, r.region_nouvelle, r.ordre, r.sexe)
        if k in t_idx:
            v = float(t_idx[k])
            ecart = abs(r.valeur - v) / v if v else (0 if r.valeur == 0 else 1)
            ctrl(rapport, "annexes vs tableaux regionaux (region x ordre x sexe)", ecart < 1e-9, ecart)
        elif r.indicateur != "inconnu":
            ctrl(rapport, "annexes : region absente du tableau regional", False, 1.0)
    # 4) nombre de regions
    nreg = d[(d.source == "tableau") & (d.niveau_geo == "region") & (d.numero == 2)].region_nouvelle.nunique()
    if nreg:
        ctrl(rapport, "nombre de regions du Tableau 2 (<= 17 : seules les regions concernees sont listees)", nreg <= 17, max(nreg - 17, 0) / 17)


def correspondance(df, chemin_cor):
    cor = pd.read_csv(chemin_cor, sep=";")
    col_old = "province_cns530" if "province_cns530" in cor.columns else cor.columns[0]
    cor["cle"] = cor["adm2_name"].map(norm_label)
    noms = sorted(set(cor.cle))
    par_nom = {}
    for cle, g in cor.groupby("cle"):
        poids = g.groupby(col_old)["nb_communes"].sum()
        par_nom[cle] = (poids / poids.sum()).to_dict()
    prov = df[(df.niveau_geo == "province") & (df.type_ligne == "detail")].copy()
    non = set()
    lignes = []
    for a_, b_ in ALIAS_USER.items():
        if b_ in par_nom:
            par_nom[a_] = par_nom[b_]
        else:
            jr("ATTENTION", "alias %s=%s : %s absent de la correspondance" % (a_, b_, b_))
    for r in prov.itertuples(index=False):
        n = ALIAS_PROV.get(r.province_nouvelle, r.province_nouvelle)
        if n not in par_nom:
            c = difflib.get_close_matches(n, noms, n=1, cutoff=0.85)
            if not c:
                non.add(r.province_nouvelle)
                continue
            n = c[0]
        for ancienne, part in par_nom[n].items():
            lignes.append(dict(rapport=r.rapport, mois=r.mois, numero=r.numero, indicateur=r.indicateur, statut=r.statut, portee=r.portee, ordre=r.ordre, sexe=r.sexe,
                               province_ancienne=ancienne, valeur=r.valeur * part, allocation="directe" if len(par_nom[n]) == 1 else "prorata_communes"))
    if non:
        jr("ATTENTION", "provinces ESU sans correspondance dans COD-AB : %s ; noms les plus proches : %s ; (corriger avec --alias NOM_ESU=NOM_COD-AB)" % (
            sorted(non), {n: difflib.get_close_matches(norm_label(n), noms, n=3, cutoff=0.4) for n in sorted(non)}))
    if not lignes:
        return pd.DataFrame()
    out = pd.DataFrame(lignes)
    agg = out.groupby(["rapport", "mois", "numero", "indicateur", "statut", "portee", "ordre", "sexe", "province_ancienne"]).agg(
        valeur=("valeur", "sum"), nb_allocations_prorata=("allocation", lambda s: int((s == "prorata_communes").sum()))).reset_index()
    toutes = set(cor[col_old].dropna())
    manquantes = sorted(toutes - set(agg.province_ancienne))
    if manquantes:
        jr("ATTENTION", "provinces anciennes sans aucune donnee ESU (hors annexes, ou nom non rapproche) : %s" % manquantes)
    nb = agg.province_ancienne.nunique()
    jr("INFO", "annexes ramenees a %d provinces anciennes (attendu <= 45)" % nb)
    # controle : total conserve
    for (rap, num), g in prov.groupby(["rapport", "numero"]):
        a = g.valeur.sum()
        b = agg[(agg.rapport == rap) & (agg.numero == num)].valeur.sum()
        ctrl(rap, "conservation du total apres passage aux provinces anciennes", abs(a - b) < 1e-6 * max(a, 1), abs(a - b) / max(a, 1))
    return agg


def evolution(df, rapports):
    ordre = sorted(set((r, m) for r, m in rapports if m), key=lambda x: x[1])
    for (r0, m0), (r1, m1) in zip(ordre, ordre[1:]):
        for ind, nom in (("structures", "structures rouvertes cumulees"),):
            def tot(r):
                x = df[(df.rapport == r) & (df.source == "tableau") & (df.numero == 2) & (df.niveau_geo == "national") & (df.ordre == "total")]
                return x.valeur.iloc[0] if len(x) else None
            a, b = tot(r0), tot(r1)
            if a and b:
                jr("INFO", "evolution %s -> %s du total national des structures rouvertes (T2) : %+.2f %%" % (m0, m1, 100.0 * (b - a) / a))
        reg0 = df[(df.rapport == r0) & (df.source == "tableau") & (df.numero == 2) & (df.niveau_geo == "region") & (df.ordre == "total")].set_index("region_nouvelle").valeur
        reg1 = df[(df.rapport == r1) & (df.source == "tableau") & (df.numero == 2) & (df.niveau_geo == "region") & (df.ordre == "total")].set_index("region_nouvelle").valeur
        com = reg0.index.intersection(reg1.index)
        if len(com):
            baisses = int((reg1[com] < reg0[com]).sum())
            jr("INFO", "%s -> %s : %d region(s) communes, %d en baisse pour le cumul des structures rouvertes" % (m0, m1, len(com), baisses))


def main():
    args = sys.argv[1:]
    if len(args) < 2:
        print(__doc__)
        return
    cor = None
    if "--correspondance" in args:
        i = args.index("--correspondance")
        cor = args[i + 1]
        del args[i:i + 2]
    while "--alias" in args:
        i = args.index("--alias")
        a_, b_ = args[i + 1].split("=")
        ALIAS_USER[norm_label(a_)] = norm_label(b_)
        del args[i:i + 2]
    sortie = Path(args[0])
    sortie.mkdir(parents=True, exist_ok=True)
    rapports = []
    for f in args[1:]:
        print("Lecture :", f)
        rapports.append(traiter(f))
    df = pd.DataFrame(longues)
    if df.empty:
        print("Aucune donnee extraite.")
        return
    for r, m in rapports:
        controles_croises(df, r)
    df.to_csv(sortie / "02_nettoye_esu_2026_long.csv", sep=";", index=False, encoding="utf-8")
    if cor:
        agg = correspondance(df, cor)
        if len(agg):
            agg.to_csv(sortie / "02_nettoye_esu_2026_province_ancienne.csv", sep=";", index=False, encoding="utf-8")
    else:
        jr("ATTENTION", "pas de --correspondance : annexes non ramenees aux provinces anciennes")
    evolution(df, rapports)
    if oc.NOTES_IGNOREES:
        jr("ATTENTION", "%d cellule(s) contenaient une note adressee a un assistant IA : texte ecarte, non execute" % len(oc.NOTES_IGNOREES))
    c = pd.DataFrame(ctrl_lignes)
    if len(c):
        res = c.groupby(["rapport", "controle"]).agg(n_testes=("ok", "size"), n_ok=("ok", "sum"), ecart_relatif_max=("ecart_relatif", "max")).reset_index()
        res["n_ecarts"] = res.n_testes - res.n_ok
        res.to_csv(sortie / "02_controles_esu_2026.csv", sep=";", index=False, encoding="utf-8")
        print("\nCONTROLES (comptages et ecart relatif max)")
        for r in res.itertuples():
            print("  %-12s %-62s %4d testes, %4d ecart(s), ecart max %.4f%s" % (r.rapport[-12:], r.controle, r.n_testes, r.n_ecarts, r.ecart_relatif_max, "" if r.n_ecarts == 0 else "   <-- A VERIFIER"))
    pd.DataFrame(journal).to_csv(sortie / "02_journal_esu_2026.csv", sep=";", index=False, encoding="utf-8")
    print("\nTABLEAUX LUS")
    rec = df.groupby(["rapport", "source", "numero", "indicateur", "statut", "portee"]).agg(lignes=("valeur", "size"), regions=("region_nouvelle", "nunique"),
                                                                                     provinces=("province_nouvelle", "nunique")).reset_index()
    for r in rec.itertuples():
        print("  %-12s %-8s %2d  %-11s %-11s %-6s %4d valeurs, %2d regions, %2d provinces" % (r.rapport[-12:], r.source, r.numero, r.indicateur, r.statut, r.portee, r.lignes, r.regions, r.provinces))
    print("\nJOURNAL (ATTENTION / ERREUR)")
    for j in journal:
        if j["gravite"] in ("ATTENTION", "ERREUR") or j["message"].startswith("evolution") or "provinces anciennes" in j["message"]:
            print("  [%s] %s" % (j["gravite"], j["message"]))
    print("\n-> Fichiers ecrits dans", sortie)


if __name__ == "__main__":
    main()
