"""Listes d'aide à la saisie : table indépendante `helper_values` dans la même base.
  - ENTRYTYPE, xtheme, xacronym : une valeur par champ (liste déroulante) ;
  - keywords : plusieurs valeurs séparées par des virgules (complétion pendant la frappe, voir multi.js).

La table n'appartient ni à json2db ni à Django (aucune migration) : elle est créée au premier usage et remplie
par un SELECT DISTINCT sur `pieces`. Ensuite elle ne change que lorsqu'on ajoute une valeur dans le formulaire."""
import re

from django.db import connection

from .models import HelperValue
from .textutil import fold

HELPER_FIELDS = ('entrytype', 'xtheme', 'xacronym')
MULTI_FIELDS = ('keywords',)
_SEP = re.compile(r'[;,]')
DDL = """CREATE TABLE helper_values (
  id INTEGER PRIMARY KEY,
  field TEXT NOT NULL,
  value TEXT NOT NULL,
  UNIQUE (field, value)
)"""


def split_multi(text):
    """Valeurs d'un champ multiple (« a,b ; c » -> ['a', 'b', 'c']), sans vides ni doublons."""
    return list(dict.fromkeys(v for v in (x.strip() for x in _SEP.split(text or '')) if v))


def _seed_multi(c, field):
    c.execute(f'SELECT {field} FROM pieces WHERE TRIM(COALESCE({field}, \'\')) != \'\'')
    values = {v for (text,) in c.fetchall() for v in split_multi(text)}
    c.executemany('INSERT OR IGNORE INTO helper_values (field, value) VALUES (%s, %s)', [(field, v) for v in sorted(values)])


def ensure():
    """Crée helper_values si elle manque et la remplit depuis pieces (SELECT DISTINCT ; mots-clés découpés).
    Un champ multiple sans aucune valeur est (re)rempli, ce qui ajoute keywords aux bases créées avant lui."""
    with connection.cursor() as c:
        c.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'helper_values'")
        if not c.fetchone():
            c.execute(DDL)
            for f in HELPER_FIELDS:           # noms de colonnes issus de la constante ci-dessus
                c.execute(f"INSERT OR IGNORE INTO helper_values (field, value) "
                          f"SELECT DISTINCT '{f}', TRIM({f}) FROM pieces WHERE TRIM(COALESCE({f}, '')) != ''")
        for f in MULTI_FIELDS:
            c.execute('SELECT 1 FROM helper_values WHERE field = %s LIMIT 1', [f])
            if not c.fetchone():
                _seed_multi(c, f)


def choices(field):
    """Valeurs proposées pour field, triées sans tenir compte des accents ni de la casse."""
    ensure()
    values = HelperValue.objects.filter(field=field).values_list('value', flat=True)
    return sorted(values, key=lambda v: (fold(v), v))


def remember(piece):
    """Ajoute à la liste les valeurs (éventuellement nouvelles) de la pièce enregistrée."""
    ensure()
    for f in HELPER_FIELDS:
        value = (getattr(piece, f) or '').strip()
        if value:
            HelperValue.objects.get_or_create(field=f, value=value)
    for f in MULTI_FIELDS:
        for value in split_multi(getattr(piece, f)):
            HelperValue.objects.get_or_create(field=f, value=value)
