"""Listes d'aide à la saisie (ENTRYTYPE, xtheme, xacronym) : table indépendante `helper_values` dans la même base.

La table n'appartient ni à json2db ni à Django (aucune migration) : elle est créée au premier usage et remplie
par un SELECT DISTINCT sur `pieces`. Ensuite elle ne change que lorsqu'on ajoute une valeur dans le formulaire."""
from django.db import connection

from .models import HelperValue
from .textutil import fold

HELPER_FIELDS = ('entrytype', 'xtheme', 'xacronym')
DDL = """CREATE TABLE helper_values (
  id INTEGER PRIMARY KEY,
  field TEXT NOT NULL,
  value TEXT NOT NULL,
  UNIQUE (field, value)
)"""


def ensure():
    """Crée helper_values si elle manque, et la remplit alors depuis les valeurs déjà présentes dans pieces."""
    with connection.cursor() as c:
        c.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'helper_values'")
        if c.fetchone():
            return
        c.execute(DDL)
        for f in HELPER_FIELDS:           # noms de colonnes issus de la constante ci-dessus
            c.execute(f"INSERT OR IGNORE INTO helper_values (field, value) "
                      f"SELECT DISTINCT '{f}', TRIM({f}) FROM pieces WHERE TRIM(COALESCE({f}, '')) != ''")


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
