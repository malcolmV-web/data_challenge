# Salles et enseignants du primaire à l'horizon 2030 – Burkina Faso (Défi 3)

Où construire des salles de classe et où affecter des enseignants pour couvrir la demande de 2030 ?
Chaîne de traitement relançable (Python) et tableau de bord pensé pour une direction régionale de l'éducation.

**Tableau de bord en ligne :** voir la page GitHub Pages de ce dépôt (dossier `docs/`).

## Résultats principaux (scénario « maintien », rentrée 2029-2030)
- 7 454 salles manquantes et 5 741 salles dégradées à remplacer ;
- 8 714 maîtres publics manquants ; le redéploiement de l'excédent en couvre au plus 893.

## Relancer
```
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp parametres/chemins_sources_modele.json parametres/chemins_sources.json   # puis indiquer le dossier du Data Pack
python executer.py
```
Le tableau de bord est écrit dans `05_interpretation/tableau_de_bord/index.html` et copié dans `docs/index.html`.

## Organisation
| Dossier | Étape |
| --- | --- |
| `01_collecte/` | Inventaire, empreintes SHA-256, références des sources |
| `02_nettoyage/` | Nettoyage et contrôles de chaque source |
| `03_transformation/` | Base unique par province |
| `04_analyse/` | Besoins, indice de priorité, redéploiement optimisé, nouveau découpage |
| `05_interpretation/` | Tableau de bord (4 modules) |
| `parametres/` | Normes, horizon, poids, leviers |

## Licence
Le code est publié sous licence MIT (voir LICENSE).
Les données ne sont pas couvertes par cette licence : elles proviennent du Data Pack du Data Challenge Burkina (INSD, MENAPLN, CONASUR) et d'OCHA (plateforme HDX), et restent soumises aux conditions de leurs producteurs et au règlement du challenge.

Les données brutes du Data Pack ne sont pas incluses. Le tableau de bord ne contient que des données agrégées par province.
Détails : `LISEZ-MOI.txt` et la documentation déposée dans l'espace challenge.
