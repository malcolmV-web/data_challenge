# -*- coding: utf-8 -*-
"""Fonctions communes aux scripts de nettoyage du classeur statistique prescolaire et primaire.
Ce script a prermis de tout executer en local."""

import re
import difflib
import hashlib
import unicodedata

REGIONS_13 = ["BOUCLE DU MOUHOUN", "CASCADES", "CENTRE", "CENTRE EST", "CENTRE NORD",
              "CENTRE OUEST", "CENTRE SUD", "EST", "HAUTS BASSINS", "NORD",
              "PLATEAU CENTRAL", "SAHEL", "SUD OUEST"]
NATIONAUX = {"NATIONAL", "BURKINA FASO", "BURKINA", "TOTAL GENERAL", "ENSEMBLE", "TOTAL NATIONAL", "ENSEMBLE DU PAYS"}
AGREGATS = NATIONAUX | {"TOTAL"}
NOTES_IGNOREES = []  # (feuille, ligne, colonne) des cellules contenant une note adressee a un assistant IA. Elles sont ignorees, mais signalees dans le journal.
MOTIF_NOTE_IA = re.compile(r"NOTE FOR ANY AUTOMATED|AUTOMATED ASSISTANT", re.I)
SEXES = {"total": "Total", "ensemble": "Total", "t": "Total",
         "filles": "Filles", "fille": "Filles", "f": "Filles", "feminin": "Filles",
         "garcons": "Garcons", "garcon": "Garcons", "g": "Garcons", "masculin": "Garcons"}
TITRE_RE = re.compile(r"^\s*tableau\s*(\d+)\s*[:\-\u2013]?\s*(.*)$", re.I)


def sha256(chemin):
    h = hashlib.sha256()
    with open(chemin, "rb") as f:
        for bloc in iter(lambda: f.read(1 << 20), b""):
            h.update(bloc)
    return h.hexdigest()


def sans_accents(s):
    s = unicodedata.normalize("NFKD", str(s))
    return "".join(c for c in s if not unicodedata.combining(c))


def norm_libre(s):
    """minuscules, sans accents, apostrophes remplacees par des espaces"""
    s = sans_accents(s).lower().replace("\u2019", " ").replace("'", " ")
    return re.sub(r"\s+", " ", s).strip()


def norm_label(s):
    """MAJUSCULES, sans accents, tirets et apostrophes remplaces par des espaces"""
    s = sans_accents(s).upper()
    s = re.sub(r"[-_'\u2019/]", " ", s)
    s = re.sub(r"[^A-Z0-9 ]", "", s)
    return re.sub(r"\s+", " ", s).strip()


def vide(v):
    return v is None or (isinstance(v, str) and v.strip() == "")


def to_number(v):
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).replace("\u00a0", "").replace("\u202f", "").replace(" ", "").replace(",", ".").replace("%", "")
    return float(s) if re.fullmatch(r"-?\d+(\.\d+)?", s) else None


def year_of(v):
    """(annee_debut, libelle, type) si v ressemble a une annee ou une annee scolaire, sinon None"""
    if v is None or isinstance(v, bool) or vide(v):
        return None
    if isinstance(v, (int, float)):
        if float(v).is_integer() and 1990 <= int(v) <= 2035:
            return int(v), str(int(v)), "annee_civile"
        return None
    s = str(v).strip()
    m = re.match(r"^(\d{4})\s*[/\-\u2013]\s*(\d{2,4})\D*$", s)
    if m:
        y = int(m.group(1))
        y2 = m.group(2)
        y2 = int(y2) if len(y2) == 4 else int(str(y)[:2] + y2)
        if 1990 <= y <= 2035 and y2 == y + 1:
            return y, "%d-%d" % (y, y2), "annee_scolaire"
        return None
    m = re.match(r"^(\d{4})\D*$", s)
    if m and 1990 <= int(m.group(1)) <= 2035:
        return int(m.group(1)), m.group(1), "annee_civile"
    return None


def sex_of(v):
    if vide(v) or isinstance(v, (int, float)):
        return None
    return SEXES.get(norm_libre(v).strip(" :."))


def valeur_numerique(v):
    """vrai si v est un nombre qui n'est pas une annee"""
    return to_number(v) is not None and year_of(v) is None


def nettoyer_cellule(v):
    """Ecarte, sans l'executer, tout texte adresse a un assistant IA insere dans une cellule."""
    if isinstance(v, str) and MOTIF_NOTE_IA.search(v):
        m = re.search(r"NOTE FOR ANY AUTOMATED", v, re.I)
        coupe = v[:m.start()] if m else v.split("\n")[0]
        return (coupe.strip() or None), True
    return v, False


def lire_feuille(ws):
    rows = []
    for i, r in enumerate(ws.iter_rows(values_only=True), 1):
        ligne = []
        for j, v in enumerate(r, 1):
            v2, note = nettoyer_cellule(v)
            if note:
                NOTES_IGNOREES.append((ws.title, i, j))
            ligne.append(v2)
        rows.append(ligne)
    return rows


def trouver_titres(rows):
    titres = []
    for i, r in enumerate(rows):
        for j in range(min(4, len(r))):
            v = r[j]
            if isinstance(v, str):
                m = TITRE_RE.match(v.strip())
                if m:
                    titres.append((i, int(m.group(1)), v.strip()))
                    break
    return titres


def analyser_bloc(rows, debut, fin):
    """Analyse un bloc (de la ligne de titre a la ligne avant le titre suivant)."""
    corps = rows[debut + 1:fin]
    entetes, donnees, notes, soustitres = [], [], [], []
    groupe, commence = None, False
    for k, r in enumerate(corps, start=debut + 1):
        cells = [(j, v) for j, v in enumerate(r) if not vide(v)]
        if not cells:
            continue
        nums = [j for j, v in cells if valeur_numerique(v)]
        if nums:
            commence = True
            donnees.append((k, r, groupe))
        elif not commence:
            if len(cells) == 1 and year_of(cells[0][1]) is None and sex_of(cells[0][1]) is None:
                soustitres.append(str(cells[0][1]).strip())
            else:
                entetes.append(r)
        else:
            txt = str(cells[0][1]).strip()
            if len(cells) == 1 and not re.match(r"^(source|note|\(|\*|nd\b|na\b)", norm_libre(txt)):
                groupe = txt
            else:
                notes.append(txt)
    if not donnees:
        return dict(vide=True, entetes=entetes, donnees=[], notes=notes, soustitres=soustitres)
    ncol = max(len(r) for _, r, _ in donnees)
    cols_label, cols_valeur, annee_en_ligne = [], [], []
    for j in range(ncol):
        vals = [r[j] if j < len(r) else None for _, r, _ in donnees]
        a_nombre = any(valeur_numerique(v) for v in vals)
        textes = [v for v in vals if not vide(v) and not valeur_numerique(v)]
        if a_nombre:
            cols_valeur.append(j)
        elif textes and not cols_valeur:
            cols_label.append(j)
            if all(year_of(v) is not None for v in textes):
                annee_en_ligne.append(j)
    premiere = cols_valeur[0] if cols_valeur else ncol
    entetes_remplis = []
    for h in entetes:
        rempli, cur = {}, None
        for j in range(ncol):
            v = h[j] if j < len(h) else None
            if j < premiere:
                continue
            if not vide(v):
                cur = str(v).strip() if not isinstance(v, (int, float)) else v
            if j in cols_valeur:
                rempli[j] = cur
        entetes_remplis.append(rempli)
    noms_label = {}
    for j in cols_label:
        for h in entetes:
            v = h[j] if j < len(h) else None
            if not vide(v) and year_of(v) is None and sex_of(v) is None:
                noms_label[j] = str(v).strip()
                break
    colonnes = {}
    for j in cols_valeur:
        labels = [h.get(j) for h in entetes_remplis if not vide(h.get(j))]
        an = next((year_of(x) for x in labels if year_of(x)), None)
        sx = next((sex_of(x) for x in labels if sex_of(x)), None)
        autres = [str(x) for x in labels if not year_of(x) and not sex_of(x)]
        colonnes[j] = dict(annee=an, sexe=sx, autre=" | ".join(autres))
    return dict(vide=False, entetes=entetes, donnees=donnees, notes=notes, soustitres=soustitres,
                cols_label=cols_label, cols_valeur=cols_valeur, annee_en_ligne=annee_en_ligne,
                colonnes=colonnes, ncol=ncol, noms_label=noms_label)


def dims_titre(titre):
    """Dimensions citees apres le premier 'par' du titre, dans l'ordre. 'sexe' est en colonnes."""
    n = norm_libre(titre)
    m = re.search(r"\bpar\b(.*)$", n)
    if not m:
        return []
    reste = m.group(1)
    pos = []
    for cle, nom in [("sexe", "sexe"), ("region", "region"), ("province", "province"), ("commune", "commune"),
                     ("statut", "statut"), ("milieu", "milieu"), ("niveau", "niveau_etudes")]:
        mm = re.search(cle, reste)
        if mm:
            pos.append((mm.start(), nom))
    return [nom for _, nom in sorted(pos)]


def indicateur_de(titre):
    n = norm_libre(titre)
    if re.search(r"\bips\b", n):
        m = re.search(r"\bips du (\w+)", n)
        return "IPS_" + (m.group(1).upper() if m else "INCONNU")
    regles = [("nouveaux inscrits", "NOUVEAUX_INSCRITS_CP1"), ("achevement", "TAUX_ACHEVEMENT"),
              ("taux de reussite", "TAUX_REUSSITE_CEP"), (" tba ", "TBA"), (" tbs ", "TBS"),
              ("salles de classe", "SALLES_CLASSE"), ("structures educatives", "NB_STRUCTURES"),
              ("ecoles", "NB_ECOLES"), ("effectifs", "EFFECTIFS")]
    n2 = " " + n + " "
    for cle, nom in regles:
        if cle in n2:
            return nom
    return "INCONNU"


def cycle_de(titre, nom_feuille, precedent):
    n = norm_libre(titre + " " + nom_feuille)
    if "prescolaire" in n:
        return "prescolaire"
    if "primaire" in n or " cep" in " " + n or "cp1" in n or re.search(r"\btap\b", n):
        return "primaire"
    return precedent or "inconnu"


def normaliser_region(libelle, journal, contexte):
    """Retourne (region_normalisee, reconnue). Corrige les variantes proches, signale le reste."""
    lab = norm_label(libelle)
    if lab in REGIONS_13:
        return lab, True
    proche = difflib.get_close_matches(lab, REGIONS_13, n=1, cutoff=0.88)
    if proche:
        journal.append(dict(**contexte, gravite="INFO",
                            message="region corrigee : '%s' -> '%s'" % (libelle, proche[0])))
        return proche[0], True
    return lab, False


def dim_depuis_entete(texte):
    n = norm_libre(texte or "")
    for cle, nom in [("sexe", "sexe"), ("region", "region"), ("province", "province"), ("commune", "commune"),
                     ("statut", "statut"), ("milieu", "milieu"), ("niveau", "niveau_etudes"),
                     ("classe", "niveau_etudes")]:
        if cle in n:
            return nom
    return None


NIVEAUX = {"CP1", "CP2", "CE1", "CE2", "CM1", "CM2", "GRANDE SECTION", "MOYENNE SECTION", "PETITE SECTION"}


def dim_depuis_valeurs(valeurs):
    """Devine la dimension d'une colonne de libelles d'apres son contenu (prioritaire sur l'en-tete)."""
    v = set()
    for x in valeurs:
        if vide(x):
            continue
        n = norm_label(x)
        if n in NATIONAUX or n == "TOTAL":
            continue
        v.add(re.sub(r"^TOTAL ", "", n))
    if not v:
        return None
    reg = sum(1 for x in v if x in REGIONS_13 or difflib.get_close_matches(x, REGIONS_13, n=1, cutoff=0.88))
    if reg >= 0.7 * len(v):
        return "region"
    if v <= {"PUBLIC", "PRIVE", "COMMUNAUTAIRE"}:
        return "statut"
    if v <= {"URBAIN", "RURAL", "INDETERMINE", "INDETERMINEE"}:
        return "milieu"
    if v <= {"GARCONS", "FILLES", "G", "F"}:
        return "sexe"
    if v <= NIVEAUX:
        return "niveau_etudes"
    return None


def classer_label(dim, lib):
    """(valeur normalisee, type de ligne) : detail, sous_total ou national."""
    n = norm_label(lib)
    if dim == "sexe":
        return (sex_of(lib) or n), "detail"
    if n in NATIONAUX:
        return "NATIONAL", "national"
    if n == "TOTAL":
        return "TOTAL", "sous_total"
    if n.startswith("TOTAL "):
        return n[6:], "sous_total"
    return n, "detail"


def dimensions_bloc(b, titre):
    """Retourne (colonnes_de_libelles, noms_de_dimensions, messages). Priorite : valeurs > en-tete > titre."""
    msgs = []
    cols_label = [j for j in b["cols_label"] if j not in b["annee_en_ligne"]]
    sexe_en_colonnes = any(c["sexe"] for c in b["colonnes"].values())
    autres_vals = {norm_label(c["autre"]) for c in b["colonnes"].values() if c["autre"]}
    col_dim = None
    if autres_vals and autres_vals <= {"PUBLIC", "PRIVE", "COMMUNAUTAIRE", "TOTAL", "ENSEMBLE"}:
        col_dim = "statut"
    elif autres_vals and autres_vals <= {"URBAIN", "RURAL", "TOTAL", "ENSEMBLE"}:
        col_dim = "milieu"
    if col_dim:
        msgs.append(("INFO", "%s lu dans les en-tetes de colonnes" % col_dim))
    titre_d = [d for d in dims_titre(titre) if not (d == "sexe" and sexe_en_colonnes) and d != col_dim]
    dims = []
    for k, j in enumerate(cols_label):
        valeurs = [r[j] for _, r, _ in b["donnees"] if j < len(r)]
        dv = dim_depuis_valeurs(valeurs)
        de = dim_depuis_entete(b["noms_label"].get(j))
        dt = titre_d[k] if len(titre_d) == len(cols_label) else None
        if dv and de and dv != de:
            msgs.append(("INFO", "colonne %d : l'en-tete dit '%s' mais les valeurs sont de type '%s' : valeurs retenues" % (j + 1, de, dv)))
        choix = dv or de or dt
        if dv and dt and dv != dt and not de:
            msgs.append(("INFO", "colonne %d : titre '%s' contredit par les valeurs '%s' : valeurs retenues" % (j + 1, dt, dv)))
        dims.append(choix)
    if None in dims or len(set(dims)) != len(dims):
        msgs.append(("ATTENTION", "dimensions non determinees de facon unique %s (titre : %s) -> noms generiques dim1..dimN" % (dims, titre_d)))
        dims = ["dim%d" % (k + 1) for k in range(len(cols_label))]
    return cols_label, dims, col_dim, msgs
