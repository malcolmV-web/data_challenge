# -*- coding: utf-8 -*-
"""Fichier des localites du 5e RGPH 2019 (CSV issu du PDF) -> population par commune, et poids de passage
de l'ancien decoupage (45 provinces, 13 regions) au nouveau (47 provinces, 17 regions).

Mise en page lue :
  - 'COMMUNE: <NOM> - Urbain' ou '- Rural' : en-tete d'une partie de commune ; la ligne porte les totaux de cette partie ;
  - lignes de localites : nom puis 19 nombres = Homme, Femme, Ensemble, puis 16 groupes d'age (dont 6-11) ;
    l'ordre des colonnes (sexes avant ou apres les ages) est verifie par Homme + Femme = Ensemble ;
  - pied des pages impaires : 'REGION DU .../PROVINCE DU ...' (sert a lever les homonymies de communes).
Chaque commune est rattachee au COD-AB (02_nettoye_cod_ab_communes_ancien_decoupage.csv), qui donne sa province et sa region
anciennes et nouvelles. Poids = part des enfants de 6-11 ans de la province ancienne qui vivent dans chaque province nouvelle.

Usage : python 02_nettoyage_rgph2019_localites.py FICHIER.csv --communes 02_nettoye_cod_ab_communes_ancien_decoupage.csv
                [--alias "NOM RGPH=NOM COD-AB" ...] [sortie]
Sorties : 02_nettoye_rgph2019_localites.csv, 02_nettoye_rgph2019_communes.csv, 02_nettoye_rgph2019_poids_ancien_nouveau.csv,
          02_controles_rgph2019.csv, 02_journal_rgph2019.csv"""

import csv
import difflib
import re
import sys
from pathlib import Path
import pandas as pd
import sys as _sys
from pathlib import Path as _P
_sys.path.insert(0, str(_P(__file__).resolve().parents[2] / 'communs'))
import outils_communs as oc

csv.field_size_limit(10 ** 8)
COMMUNE_RE = re.compile(r"^\s*COMMUNE\s*:\s*(.+?)(?:\s*[-–]\s*(URBAIN|RURAL)E?)?\s*$", re.I)  # milieu absent : commune d'un seul tenant
ALIAS_DEFAUT = {"ZEGUEDEGUIN": "ZEGUEDEGUEN", "SAMOROGOUAN": "SAMOGOGOUAN"}  # ecritures RGPH -> COD-AB verifiees a la main
PIED_RE = re.compile(r"REGION\s+(?:DU|DE LA|DES|DE L|D)?\s*(.+?)\s*/\s*PROVINCE\s+(?:DU|DE LA|DES|DE L|D)?\s*(.+?)\s*$", re.I)
NIVEAU_RE = re.compile(r"^\s*(REGION|PROVINCE|TOTAL|ENSEMBLE)\b", re.I)
SEXES = ["homme", "femme", "ensemble"]


def phon(s):
    """Cle phonetique simple pour les toponymes : KUY/KUI, GH/G, C dur/K, CE/SE, Y/I, H muet, lettres doublees."""
    s = re.sub(r"[^A-Z]", "", oc.norm_label(s).upper())
    for a, b in (("GH", "G"), ("GU", "G"), ("CE", "SE"), ("CI", "SI"), ("CY", "SI"), ("C", "K"), ("Y", "I"), ("H", ""), ("OU", "U"), ("W", "U")):
        s = s.replace(a, b)
    return re.sub(r"(.)\1+", r"\1", s)


def nombre(v):
    if v is None:
        return None
    s = str(v).strip()
    if s in ("-", "–", "—"):
        return 0.0
    return oc.to_number(s)


def main():
    a = sys.argv[1:]
    if not a or "--communes" not in a:
        print(__doc__)
        return
    src = Path(a[0])
    communes = Path(a[a.index("--communes") + 1])
    alias = {oc.norm_label(k): oc.norm_label(v) for k, v in ALIAS_DEFAUT.items()}
    for i, x in enumerate(a):
        if x == "--alias" and i + 1 < len(a) and "=" in a[i + 1]:
            k, v = a[i + 1].split("=", 1)
            alias[oc.norm_label(k)] = oc.norm_label(v)
    libres = [x for i, x in enumerate(a[1:], 1) if not x.startswith("--") and a[i - 1] not in ("--communes", "--alias")]
    sortie = Path(libres[0]) if libres else Path("02_nettoyage/rgph2019_localites")
    sortie.mkdir(parents=True, exist_ok=True)
    journal, notes_ia = [], 0

    # ---------- 1. lecture brute
    lignes = []
    with open(src, encoding="utf-8-sig", newline="") as f:
        r = csv.reader(f, delimiter=";")
        en_tete = next(r)
        ic = [i for i, h in enumerate(en_tete) if re.fullmatch(r"c\d+", h.strip())]
        ip = en_tete.index("page")
        for row in r:
            cel = []
            for i in ic:
                v = row[i] if i < len(row) else ""
                v, note = oc.nettoyer_cellule(v)
                notes_ia += int(note)
                cel.append((v or "").strip().strip('"').strip())
            while cel and cel[-1] == "":
                cel.pop()
            try:
                page = int(float(row[ip]))
            except (ValueError, IndexError):
                continue
            lignes.append((page, cel))
    if notes_ia:
        journal.append(dict(gravite="INFO", message="%d cellule(s) contenant une note adressee a un assistant IA : texte ecarte, non execute" % notes_ia))

    ordre_prov = "tete"
    # ---------- 2. province de chaque page (pied de page) et libelles des groupes d'age
    pied, ages = {}, None
    for page, cel in lignes:
        for c in cel:
            m = PIED_RE.search(c)
            if m:
                pied[page] = (oc.norm_label(m.group(1)), oc.norm_label(m.group(2)))
        if ages is None and "6-11" in cel:
            ages = [c for c in cel if c]
    if ages is None or len(ages) != 16:
        journal.append(dict(gravite="ATTENTION", message="libelles des groupes d'age non trouves ou incomplets : %s" % ages))
        ages = (ages or []) + ["g%d" % i for i in range(16 - len(ages or []))]
    cols_age = ["age_" + oc.norm_label(x).replace(" ", "_") for x in ages[:16]]

    def province_page(p):
        for d in (0, 1, -1, 2, -2):
            if p + d in pied:
                return pied[p + d]
        return (None, None)

    # ---------- 3. machine a etats : communes et localites
    recs, entetes_communes, rejets, suspectes, total_national = [], [], [], [], None
    commune = milieu = None
    for page, cel in lignes:
        if not cel:
            continue
        lib = cel[0]
        m = COMMUNE_RE.match(lib)
        if not m and any(re.match(r"\s*COMMUNE\s*:", c, re.I) for c in cel):
            suspectes.append((page, " | ".join(cel[:3])))
        if total_national is None and oc.norm_label(lib) == "BURKINA FASO" and len(cel) >= 4:
            total_national = nombre(cel[3]) if ordre_prov == "tete" else None
        vals = [nombre(x) for x in cel[1:]]
        if m:
            commune, milieu = oc.norm_label(m.group(1)), (m.group(2) or "Ensemble").capitalize()
            if len(vals) == 19 and all(v is not None for v in vals):
                entetes_communes.append(dict(page=page, commune=commune, milieu=milieu, valeurs=vals))
            continue
        if len(cel) == 20 and nombre(lib) is None and all(v is not None for v in vals):
            if NIVEAU_RE.match(lib):
                continue
            if commune is None:
                rejets.append((page, lib, "localite avant toute commune"))
                continue
            recs.append(dict(page=page, commune=commune, milieu=milieu, localite=oc.norm_label(lib), valeurs=vals))
        elif len(cel) > 4 and nombre(lib) is None and sum(v is not None for v in vals) >= 10 and not NIVEAU_RE.match(lib):
            rejets.append((page, lib, "%d cellules (20 attendues)" % len(cel)))
    if not recs:
        print("Aucune localite lue : verifier le fichier.")
        return

    # ---------- 4. ordre des colonnes : sexes en tete ou en fin ?
    def ecart(ordre, v):
        s = v[:3] if ordre == "tete" else v[16:]
        return abs(s[0] + s[1] - s[2])
    ordre = min(("tete", "fin"), key=lambda o: sum(ecart(o, x["valeurs"]) for x in recs))
    def ventiler(v):
        s, g = (v[:3], v[3:]) if ordre == "tete" else (v[16:], v[:16])
        return dict(zip(SEXES, s), **dict(zip(cols_age, g)))
    loc = pd.DataFrame([dict(page=x["page"], commune_rgph=x["commune"], milieu=x["milieu"], localite=x["localite"], **ventiler(x["valeurs"])) for x in recs])
    loc["region_page"] = loc.page.map(lambda p: province_page(p)[0])
    loc["province_page"] = loc.page.map(lambda p: province_page(p)[1])
    col611 = next((c for c in cols_age if c.endswith("6_11")), None)
    if col611 is None:
        journal.append(dict(gravite="ERREUR", message="colonne des 6-11 ans introuvable parmi %s" % cols_age))
        col611 = "ensemble"

    # ---------- 5. totaux par commune : en-tetes de commune (officiels) recoupes avec la somme des localites
    som = loc.groupby(["commune_rgph", "milieu"], sort=False).agg(ensemble=("ensemble", "sum"), pop_6_11=(col611, "sum"), nb_localites=("localite", "size"),
                                                                  page=("page", "min"), province_page=("province_page", "first")).reset_index()
    ent = {(e["commune"], e["milieu"]): ventiler(e["valeurs"]) for e in entetes_communes}
    som["ensemble_entete"] = [ent.get((c, m), {}).get("ensemble") for c, m in zip(som.commune_rgph, som.milieu)]
    som["pop_6_11_entete"] = [ent.get((c, m), {}).get(col611) for c, m in zip(som.commune_rgph, som.milieu)]
    avec = som.ensemble_entete.notna()
    ecart_ent = (som.loc[avec, "ensemble"] - som.loc[avec, "ensemble_entete"]).abs()
    som["pop_6_11_retenue"] = som.pop_6_11_entete.where(som.pop_6_11_entete.notna(), som.pop_6_11)
    som["pop_totale_retenue"] = som.ensemble_entete.where(som.ensemble_entete.notna(), som.ensemble)
    com = som.groupby("commune_rgph", sort=False).agg(pop_totale=("pop_totale_retenue", "sum"), pop_6_11=("pop_6_11_retenue", "sum"), nb_localites=("nb_localites", "sum"),
                                                      milieux=("milieu", lambda s: "+".join(sorted(set(s)))), page=("page", "min"),
                                                      province_page=("province_page", "first")).reset_index()

    # ---------- 6. rattachement au COD-AB
    cod = pd.read_csv(communes, sep=";", dtype=str)
    p_anc = "province_cns530" if "province_cns530" in cod.columns else "province_ancienne"
    r_anc = "region_cns530" if "region_cns530" in cod.columns else "region_ancienne"
    cod["cle"] = cod.adm3_name.map(oc.norm_label)
    par_nom = cod.groupby("cle").apply(lambda g: list(g.index)).to_dict()
    noms = list(par_nom)
    cod["prov_cle"] = cod[p_anc].map(oc.norm_label)
    cod["phon"] = cod.cle.map(phon)
    res, pris = [], set()
    def meme_province(i, pp):
        return bool(pp) and difflib.SequenceMatcher(None, cod.at[i, "prov_cle"], pp).ratio() > 0.8
    for r in com.itertuples(index=False):
        n = alias.get(r.commune_rgph, r.commune_rgph)
        mode, cand = "exact", par_nom.get(n, [])
        if not cand:  # 1) meme ecriture phonetique ; 2) nom proche DANS LA MEME PROVINCE (evite Zimtenga -> Zitenga)
            ph = [i for i in cod.index[cod.phon == phon(n)]]
            if len(ph) == 1:
                mode, cand = "phonetique (%s)" % cod.at[ph[0], "adm3_name"], ph
            else:
                dans = [i for i in cod.index if meme_province(i, r.province_page)] or list(cod.index)
                sc = sorted(((difflib.SequenceMatcher(None, phon(n), cod.at[i, "phon"]).ratio(), i) for i in dans), reverse=True)
                if sc and sc[0][0] >= 0.75 and (len(sc) == 1 or sc[0][0] - sc[1][0] >= 0.05):
                    mode, cand = "approche (%s, %.2f)" % (cod.at[sc[0][1], "adm3_name"], sc[0][0]), [sc[0][1]]
        if len(cand) > 1:  # homonymes : la province du pied de page tranche
            pp = r.province_page
            filt = [i for i in cand if pp and difflib.SequenceMatcher(None, oc.norm_label(cod.at[i, p_anc]), pp).ratio() > 0.8]
            cand = filt if len(filt) == 1 else cand
            mode += " + province de la page" if len(filt) == 1 else ""
        if len(cand) == 1:
            i = cand[0]
            res.append(dict(adm3_pcode=cod.at[i, "adm3_pcode"], adm3_name=cod.at[i, "adm3_name"], province_ancienne=cod.at[i, p_anc], region_ancienne=cod.at[i, r_anc],
                            province_nouvelle=cod.at[i, "adm2_name"], region_nouvelle=cod.at[i, "adm1_name"], rattachement=mode))
        else:
            res.append(dict(adm3_pcode=None, adm3_name=None, province_ancienne=None, region_ancienne=None, province_nouvelle=None, region_nouvelle=None,
                            rattachement="NON RATTACHEE" if not cand else "AMBIGUE (%d)" % len(cand)))
    com = pd.concat([com, pd.DataFrame(res)], axis=1)
    non = com[com.adm3_pcode.isna()]
    if len(non):
        journal.append(dict(gravite="ATTENTION", message="%d commune(s) RGPH non rattachee(s) au COD-AB (ajouter --alias \"NOM RGPH=NOM COD-AB\") : %s" % (
            len(non), list(non.commune_rgph)[:15])))
    appr = com[com.rattachement.str.startswith(("approche", "phonetique"))]
    for r in appr.itertuples(index=False):
        journal.append(dict(gravite="INFO", message="rattachement approche : %s -> %s" % (r.commune_rgph, r.adm3_name)))
    doubl = com[com.adm3_pcode.notna() & com.adm3_pcode.duplicated(keep=False)]
    if len(doubl):
        journal.append(dict(gravite="ATTENTION", message="communes COD-AB recevant plusieurs communes RGPH : %s" % sorted(set(doubl.adm3_name))[:10]))
    manq = sorted(set(cod.adm3_name) - set(com.adm3_name.dropna()))
    if manq:
        journal.append(dict(gravite="ATTENTION", message="%d commune(s) COD-AB sans population RGPH : %s" % (len(manq), manq[:15])))

    # ---------- 7. poids de passage ancien -> nouveau
    ok = com[com.adm3_pcode.notna()]
    poids = ok.groupby(["region_ancienne", "province_ancienne", "region_nouvelle", "province_nouvelle"]).agg(
        nb_communes=("adm3_pcode", "nunique"), pop_totale=("pop_totale", "sum"), pop_6_11=("pop_6_11", "sum")).reset_index()
    poids["part_pop_6_11"] = poids.pop_6_11 / poids.groupby("province_ancienne").pop_6_11.transform("sum")
    poids["part_pop_totale"] = poids.pop_totale / poids.groupby("province_ancienne").pop_totale.transform("sum")
    poids["province_partagee"] = poids.groupby("province_ancienne").province_nouvelle.transform("nunique") > 1

    # ---------- 8. controles
    hfe = (loc.homme + loc.femme - loc.ensemble).abs()
    sage = (loc[cols_age].sum(axis=1) - loc.ensemble).abs()
    ctrl = [
        dict(controle="localites lues", valeur=len(loc), attendu="environ 9 000 a 10 000"),
        dict(controle="communes RGPH distinctes", valeur=len(com), attendu=351),
        dict(controle="communes rattachees au COD-AB", valeur=int(com.adm3_pcode.notna().sum()), attendu=len(com)),
        dict(controle="ordre des colonnes (sexes)", valeur=ordre, attendu="tete ou fin"),
        dict(controle="localites ou Homme + Femme <> Ensemble (ecart 1 ou 2 : arrondi de la source)", valeur=int(((hfe > 0) & (hfe <= 2)).sum()), attendu="information"),
        dict(controle="localites ou Homme + Femme <> Ensemble (ecart > 2)", valeur=int((hfe > 2).sum()), attendu=0),
        dict(controle="localites ou somme des ages <> Ensemble (ecart > 2)", valeur=int((sage > 2).sum()), attendu=0),
        dict(controle="parties de commune avec en-tete chiffre", valeur=int(avec.sum()), attendu=len(som)),
        dict(controle="parties ou en-tete <> somme des localites", valeur=int((ecart_ent > 1).sum()), attendu=0),
        dict(controle="population totale (millions)", valeur=round(com.pop_totale.sum() / 1e6, 3),
             attendu="%s (ligne 'Burkina Faso' du fichier)" % (round(total_national / 1e6, 3) if total_national else "environ 20,5")),
        dict(controle="population 6-11 ans (millions)", valeur=round(com.pop_6_11.sum() / 1e6, 3), attendu="a comparer aux projections INSD 2019-2020"),
        dict(controle="provinces anciennes couvertes", valeur=poids.province_ancienne.nunique(), attendu=45),
        dict(controle="provinces nouvelles couvertes", valeur=poids.province_nouvelle.nunique(), attendu=47),
        dict(controle="regions nouvelles couvertes", valeur=poids.region_nouvelle.nunique(), attendu=17),
        dict(controle="provinces anciennes partagees entre plusieurs nouvelles", valeur=int(poids.groupby("province_ancienne").province_partagee.first().sum()), attendu="information"),
        dict(controle="lignes ecartees (structure inattendue)", valeur=len(rejets), attendu=0)]
    pages_rej = sorted({p for p, _, _ in rejets})
    if rejets:
        journal.append(dict(gravite="INFO", message="%d ligne(s) ecartee(s), pages %s ; exemples : %s" % (len(rejets), pages_rej[:15], [l[:25] for _, l, _ in rejets[:8]])))
    for p, l in suspectes[:25]:
        journal.append(dict(gravite="ATTENTION", message="page %s : ligne contenant COMMUNE non reconnue : %s" % (p, l[:90])))
    ko = loc[(hfe > 2) | (sage > 2)]
    for r in ko.head(8).itertuples(index=False):
        journal.append(dict(gravite="ATTENTION", message="page %s, %s / %s : H %s + F %s ; ensemble %s ; somme des ages %s" % (
            r.page, r.commune_rgph, r.localite, r.homme, r.femme, r.ensemble, sum(getattr(r, c) for c in cols_age))))

    loc.drop(columns=["page"]).to_csv(sortie / "02_nettoye_rgph2019_localites.csv", sep=";", index=False, encoding="utf-8")
    com.to_csv(sortie / "02_nettoye_rgph2019_communes.csv", sep=";", index=False, encoding="utf-8")
    poids.to_csv(sortie / "02_nettoye_rgph2019_poids_ancien_nouveau.csv", sep=";", index=False, encoding="utf-8")
    pd.DataFrame(ctrl).to_csv(sortie / "02_controles_rgph2019.csv", sep=";", index=False, encoding="utf-8")
    pd.DataFrame(journal or [dict(gravite="INFO", message="aucune anomalie")]).to_csv(sortie / "02_journal_rgph2019.csv", sep=";", index=False, encoding="utf-8")
    for c in ctrl:
        print("%-58s %-12s (attendu %s)" % (c["controle"], c["valeur"], c["attendu"]))
    for j in journal:
        print("  %-9s %s" % (j["gravite"], j["message"][:220]))
    print("Sorties dans :", sortie)


if __name__ == "__main__":
    main()
