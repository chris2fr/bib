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
pip install -r requirements.txt            # Django, markdown, nh3, tzdata, python-dotenv
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

La **recherche avancée** (`/recherche-avancee/`) est un formulaire (mots, expression, exclusions, champs, listes, années, dates,
présence) qui écrit la requête équivalente dans la barre de recherche. La page **Aide** du site (`/aide/`) détaille la syntaxe avec des exemples cliquables ; les champs « du / au » sous la barre de recherche filtrent par plage de dates avec un calendrier.

Insensible aux accents et à la casse. Le site affiche sous la barre de recherche comment la requête a été lue.

| Besoin | Exemple |
|---|---|
| mots (ET) | `géothermie dogger corrosion` |
| expression, exclusion, préfixe | `"nappe du dogger"` · `-corrosion` · `géotherm*` |
| dates et périodes | `entre 1990 et 2000` · `avant 2010` · `depuis 2015` · `mai 1997` · `8 avril 2014` · `2014-04-08` · `1997` |
| plages de dates précises | `entre 1997-05-12 et 1998-03-01` · `du 8 avril 2014 au 3 juin 2015` · `date:1997-05..1997-09` · `date:>=2014-04-08` · `avant 8 avril 2014` · `depuis mai 1997` |
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

Autres outils : facettes cliquables (thème, nature = champ `type`, source, langue, décennie), tri, extraits surlignés, documents
proches (TF-IDF), **doublons probables** (texte très proche, même titre, même sha256, `xduplicate`) et **audit** de
cohérence entre la clé `AAAA-MM-JJ-acronyme-compteur` et `year`, `date`, `xacronym`, `xcounter`, `shorthand`.

## Édition

Formulaire pour les champs BibTeX (valeurs de base), les autres champs (JSON), les surcharges du .bib (JSON ; `null` supprime un
champ du .bib) et le markdown. Contrôles : accolades équilibrées (sinon l'export .bib échouerait), JSON valide, champs réservés,
clé unique. Les retours à la ligne des navigateurs (CRLF) sont normalisés : enregistrer sans rien changer ne modifie rien.
**Ordre des champs** : universel, identique pour toutes les entrées (fiche, formulaire, `.bib`, `fr.json`). Les champs BibTeX viennent
d'abord, puis les « autres champs » ; dans chaque groupe, l'ordre est celui des paramètres `BIBMAN_ORDER_BIBTEX` et
`BIBMAN_ORDER_OTHER` (noms séparés par des virgules, ex. `BIBMAN_ORDER_BIBTEX=title,author,date,year`), les champs non listés suivant
par ordre alphabétique ; sans paramètre, tout est alphabétique. L'ordre n'est plus propre à chaque entrée et n'est plus stocké : la colonne `field_order` a disparu (une base existante la perd
automatiquement au premier accès, ce qui demande SQLite ≥ 3.35), un champ vide équivaut à un champ absent, et réécrire un
`fr.json` ne reproduit donc plus l'ordre d'origine des clés.

**Surcharges du .bib** : sur la fiche, de discrets boutons `bib2base` / `base2bib` apparaissent à côté de chaque champ surchargé (et, en
titre de section, pour toutes les surcharges). `bib2base` fait de la valeur du .bib la valeur de base puis supprime la surcharge
(une surcharge `null`, c'est-à-dire un champ retiré du .bib, retire aussi la valeur de base, après confirmation) ; la nouvelle
valeur de base passe par les contrôles du formulaire (date, heure, fichier, xdup…) et `year` / `xdatetime` sont recalculés.
`base2bib` garde la valeur de base et supprime seulement la surcharge. Un champ calculé (`year`, `xdatetime`) ou propre au .bib
n'a pas de valeur de base à remplacer : seul `base2bib` lui est proposé.

**Doublons** : un doublon est parfois nécessaire (d'anciens documents le citent). Le champ **`xdup`** d'une entrée donne la clé d'une
autre entrée dont elle est le doublon ; il se saisit dans le formulaire (clés proches proposées) ou en un clic depuis la page
Doublons (« gauche = doublon de droite »). Règles : la clé doit exister, ce n'est pas l'entrée elle-même, la cible n'est pas un
doublon (une seule couche) et une entrée citée comme cible ne peut pas devenir doublon. Une paire déclarée quitte la liste des
doublons probables et figure dans « Doublons déclarés » ; renommer la cible met `xdup` à jour, la supprimer est refusée tant que des
doublons la citent, et l'audit signale les `xdup` invalides. `xduplicate` reste un champ libre, comme avant.

**Fichiers sources** : le dossier `BIBMAN_FILES` (défaut `./files`) contient les documents d'origine. Le fichier d'une entrée est
celui que nomme son champ `file` (nom seul, **sans dossier** : refusé à l'enregistrement s'il contient `/` ou `\`), à défaut
`<clé>.pdf`. La fiche et la liste y renvoient (`/p/<clé>/fichier/` : PDF et images affichés, autres types téléchargés) ; le formulaire
propose les noms présents dans le dossier et prévient si le fichier est introuvable ; l'audit signale les champs `file` contenant un
dossier ou pointant vers un fichier absent.

**Heure et fuseau** : `xtime` est au format `HH:MM` (00:00–23:59). `xtimezone` se choisit dans la liste des fuseaux IANA
(vide par défaut ; la colonne a pour valeur par défaut SQL `Europe/Paris`, mais l'application écrit NULL quand rien n'est choisi,
et une base existante reçoit la colonne vide au premier accès). `xdatetime` est calculé, comme `year` : il combine la date
**complète** (sans `00`) et `xtime` — `2014-04-08T14:30` — et, si un fuseau est choisi, l'ISO dans ce fuseau, heure d'été
comprise — `2014-04-08T14:30+02:00`. Une heure sans date complète est refusée ; l'audit contrôle format, fuseau et cohérence.

**Clé (ID)** : la clé de citation (colonne `id`, utilisée dans le .bib) est affichée et modifiable à l'édition. Renommer
la clé met `shorthand` à jour (il vaut la clé par défaut), sauf s'il a été personnalisé ou modifié dans le même formulaire.
Les autres champs qui citent l'ancienne clé (`xduplicate`, `xacronym`, `xcounter`...) ne sont pas réécrits : l'audit les signale.

**Dates** : `date` doit être au format ISO `AAAA-MM-JJ`, `MM` et `JJ` pouvant valoir `00` (`1997-05-00`, `1997-00-00`) ; mois, jour et
longueur du mois sont contrôlés à l'enregistrement (et dans le navigateur, avant l'envoi). `year` n'est plus saisi : il est
calculé à partir de la date. Un petit calendrier facultatif remplit le champ (il ne sait pas écrire `00`, tapez-les à la main).
Une entrée sans date garde son `year` hérité ; l'audit signale les dates mal formées et les `year` incohérents.

**Listes d'aide** : `ENTRYTYPE`, `xtheme` et `xacronym` sont des listes déroulantes alimentées par une table indépendante
`helper_values` de la même base. Elle est créée au premier usage et remplie par un `SELECT DISTINCT` sur les valeurs
existantes ; pour ajouter une valeur, remplissez le champ « nouvelle valeur » sous la liste (il l'emporte sur le choix), elle
est ajoutée à la liste à l'enregistrement. Supprimer la table `helper_values` la fait reconstruire depuis les données.
`FR_READONLY=1` désactive création, modification et suppression.

## Réglages (variables d'environnement et `.env`)

Tous les réglages sont des variables d'environnement, lues dans `bibman/settings.py` (et, pour l'ordre des champs, dans
`outils/lib/frlib.py`). Elles peuvent aussi être écrites dans un fichier **`.env`** à la racine du projet (lignes `CLÉ=valeur`,
commentaires `#`, guillemets possibles) ou dans le fichier que désigne `BIBMAN_ENV_FILE`. Une variable déjà présente dans
l'environnement l'emporte sur le fichier. Partez de `.env.example`, qui liste tout ; `.env` n'est pas versionné.

| Variable | Rôle | Défaut |
|---|---|---|
| `FR_DB` | base SQLite | `./biblio.db` |
| `BIBMAN_FILES` | dossier des fichiers sources | `./files` |
| `FR_SYNONYMS` | fichier de synonymes | `./synonyms.txt` |
| `FR_TOOLS_LIB` | dossier de `frlib.py` et `json2db.py` | `./outils/lib` |
| `BIBMAN_ORDER_BIBTEX`, `BIBMAN_ORDER_OTHER` | ordre des champs (voir Édition) | alphabétique |
| `FR_READONLY` | `1` = consultation seule | désactivé |
| `DJANGO_DEBUG` | `0` en production | `1` |
| `DJANGO_SECRET_KEY` | clé secrète | clé de développement |
| `DJANGO_ALLOWED_HOSTS` | hôtes autorisés, séparés par des virgules | localhost |
| `BIBMAN_STATIC_ROOT` | destination de `collectstatic` | `./staticfiles` |

Pour autre chose qu'un usage local, définissez une vraie clé secrète, `DJANGO_DEBUG=0` et servez les fichiers statiques
(`collectstatic`) ; il n'y a pas d'authentification.

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
