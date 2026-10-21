# Site de gestion de fr.json (Django)

Application locale pour parcourir, rechercher, corriger et exporter le `fr.json` « remonté » (voir `../outils/`).
Elle travaille sur **`fr.db`**, la base que produisent `json2db.sh` / `loadjson` : le modèle Django est *non géré*
(`managed = False`) et réutilise `frlib.py`, donc les scripts `db2json.sh`, `db2bib.sh`, `bib2db.sh` et Datasette
continuent de fonctionner sur la même base. Django n'y crée aucune table : **ne lancez pas `manage.py migrate`**.

## Démarrage

```sh
pip install -r requirements.txt            # Django, markdown, nh3
export FR_DB=/chemin/vers/fr.db            # défaut : ./fr.db
python manage.py loadjson ../fr.json       # construit fr.db (ou : ../outils/json2db.sh fr.json fr.db)
python manage.py runserver                 # http://127.0.0.1:8000
```

`loadjson` refuse d'écraser une base existante sans `--force`. Les modifications faites dans le site vivent dans la base :
`dumpjson [fr.json]` (ou le lien « fr.json » du site) réécrit le fichier, avec la même mise en forme que `db2json.sh`.

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
champ du .bib) et le markdown. Contrôles : accolades équilibrées (sinon `db2bib` échouerait), JSON valide, champs réservés,
clé unique. Les retours à la ligne des navigateurs (CRLF) sont normalisés : enregistrer sans rien changer ne modifie rien.
`FR_READONLY=1` désactive création, modification et suppression.

## Réglages (variables d'environnement)

`FR_DB` · `FR_TOOLS_LIB` (dossier de `frlib.py` et `json2db.py`, défaut `../outils/lib`) · `FR_SYNONYMS` · `FR_READONLY` ·
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
- L'export `fr.bib` du site est le BibTeX « simple » (comme `json2bib.sh`) ; pour un export sans perte, utilisez `db2bib.sh`.
- `synonyms.txt` n'est qu'un point de départ : adaptez-le à votre corpus.
