# bibman — gestionnaire de bibliographie (Django)

Application locale pour parcourir, rechercher, corriger et exporter une bibliographie au format « fr.json remonté ».
Elle travaille sur **`biblio.db`** (SQLite), construite à partir de **`biblio.json`** : le modèle Django est *non géré*
(`managed = False`) et s'appuie sur `outils/lib/frlib.py` (conversion entrée JSON <-> ligne) et `outils/lib/json2db.py`
(schéma, index FTS5). Django n'y crée aucune table : **ne lancez pas `manage.py migrate`**.

## Organisation

```
manage.py
bibman/            projet Django (settings, urls, wsgi)
pieces/            application : modèle, vues, recherche, formulaires, gabarits, commandes loadjson / dumpjson
outils/lib/        frlib.py, json2db.py (partagés avec d'éventuels scripts hors Django)
synonyms.txt       synonymes de la recherche
```

## Démarrage

```sh
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt            # Django, markdown, nh3
python manage.py loadjson biblio.json      # construit biblio.db (--force pour remplacer une base existante)
python manage.py runserver                 # http://127.0.0.1:8000
python manage.py test                      # tests
```

Fichiers par défaut : `./biblio.db` (`FR_DB` pour changer) et `./biblio.json`. Les modifications faites dans le site vivent
dans la base : `python manage.py dumpjson biblio.json` (ou le lien « fr.json » du site) réécrit le JSON.

Raccourcis : `make install`, `make load` (`FORCE=1` pour remplacer), `make run`, `make test`, `make dump` ; `make help` liste tout.

## Déploiement

Application sans authentification, pensée pour un usage local ou un réseau de confiance (placez-la derrière un reverse proxy
avec authentification, ou utilisez `FR_READONLY=1` pour une consultation seule).

```sh
export DJANGO_DEBUG=0 DJANGO_SECRET_KEY='...' DJANGO_ALLOWED_HOSTS=bib.example.org FR_DB=/var/lib/bibman/biblio.db
python manage.py collectstatic --noinput   # copie les fichiers statiques dans staticfiles/ (BIBMAN_STATIC_ROOT)
pip install gunicorn && gunicorn bibman.wsgi
```

Le serveur web frontal sert `/static/` depuis `staticfiles/` et transmet le reste à gunicorn. SQLite : un seul processus
écrivain à la fois suffit pour cet usage ; le répertoire de la base doit être accessible en écriture.

## Recherche

Insensible aux accents et à la casse. Le site affiche sous la barre de recherche comment la requête a été lue.

| Besoin | Exemple |
|---|---|
| mots (ET) | `géothermie dogger corrosion` |
| expression, exclusion, préfixe | `"nappe du dogger"` · `-corrosion` · `géotherm*` |
| dates et périodes | `entre 1990 et 2000` · `avant 2010` · `depuis 2015` · `mai 1997` · `8 avril 2014` · `2014-04-08` · `1997` |
| champs | `theme:dogger` · `type:email` · `org:brgm` · `auteur:dupont` · `titre:"réseau de chaleur"` · `year:1990..2000` · `lang:fr` |
| présence | `has:url` · `no:note` · `has:override` (entrées avec surcharges du .bib) |
| clés, identifiants | `brgmfr-39522` · `39522` · `R39522` |
| FTS5 brut (case à cocher) | `dogger NEAR(corrosion tubage, 10)` · `title:dogger NOT corrosion` |

**Heuristiques** (mode normal) : chaque mot est résolu séparément et de plus en plus largement jusqu'à obtenir des
résultats — exact (+ synonymes de `synonyms.txt`), puis racine (`géothermiques` → `geothermi*`), puis orthographe
approchante (termes de l'index à 1 ou 2 fautes de frappe, d'après `fts5vocab`). Si le ET est vide, le site propose les
documents contenant au moins la moitié des mots (« résultats partiels ») ; un mot sans aucun résultat est ignoré et signalé.
Classement : bm25 pondéré par colonne, majoré pour les identifiants, les mots du titre et le nombre de mots trouvés.
La case « élargir » ajoute racines et orthographe approchante même quand des résultats exacts existent.

Autres outils : facettes cliquables (thème, nature, source, type, langue, décennie), tri, extraits surlignés, documents
proches (TF-IDF), **doublons probables** (texte très proche, même titre, même sha256, `xduplicate`) et **audit** de
cohérence entre la clé `AAAA-MM-JJ-acronyme-compteur` et `year`, `date`, `xacronym`, `xcounter`, `shorthand`.

## Édition

Formulaire pour les champs BibTeX (valeurs de base), les autres champs (JSON), les surcharges du .bib (JSON ; `null` supprime un
champ du .bib) et le markdown. Contrôles : accolades équilibrées (sinon l'export .bib échouerait), JSON valide, champs réservés,
clé unique. Les retours à la ligne des navigateurs (CRLF) sont normalisés : enregistrer sans rien changer ne modifie rien.
**Listes d'aide** : `ENTRYTYPE`, `xtheme` et `xacronym` sont des listes déroulantes alimentées par une table indépendante
`helper_values` de la même base. Elle est créée au premier usage et remplie par un `SELECT DISTINCT` sur les valeurs
existantes ; pour ajouter une valeur, remplissez le champ « nouvelle valeur » sous la liste (il l'emporte sur le choix), elle
est ajoutée à la liste à l'enregistrement. Supprimer la table `helper_values` la fait reconstruire depuis les données.
`FR_READONLY=1` désactive création, modification et suppression.

## Réglages (variables d'environnement)

`FR_DB` · `FR_TOOLS_LIB` (dossier de `frlib.py` et `json2db.py`, défaut `outils/lib`) · `FR_SYNONYMS` · `FR_READONLY` ·
`DJANGO_SECRET_KEY` · `DJANGO_DEBUG` · `DJANGO_ALLOWED_HOSTS`. Pour autre chose qu'un usage local, définissez une vraie
clé secrète, `DJANGO_DEBUG=0` et servez les fichiers statiques (`collectstatic`) ; il n'y a pas d'authentification.

## Tests

```sh
python manage.py test pieces        # 22 tests : analyse de requête, recherche, formulaires, vues, exports, audit
```

## Limites connues

- L'index FTS5 porte sur les valeurs de base ; le texte des surcharges du .bib n'est pas indexé (les filtres `champ:valeur`,
  eux, tiennent compte de la base **et** de la surcharge).
- Le premier affichage d'une fiche (index de similarité) ou la première recherche approchante (vocabulaire) prend environ une
  seconde ; ensuite tout est en mémoire. Les caches se recalculent quand la base change, y compris par les scripts.
- L'export `fr.bib` du site est le BibTeX « simple » (valeurs de base, surcharges appliquées).
- `synonyms.txt` n'est qu'un point de départ : adaptez-le à votre corpus.
