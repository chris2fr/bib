"""Mise à niveau légère d'une base existante (la table `pieces` appartient à json2db, pas à Django)."""
from django.db import connection

_ok = False


def ensure():
    """Ajoute les colonnes apparues depuis la construction de la base. Sans effet si la table pieces manque."""
    global _ok
    if _ok:
        return
    with connection.cursor() as c:
        c.execute("SELECT name FROM pragma_table_info('pieces')")
        cols = {r[0] for r in c.fetchall()}
        if not cols:
            return
        if 'xtimezone' not in cols:
            c.execute("ALTER TABLE pieces ADD COLUMN xtimezone TEXT DEFAULT 'Europe/Paris'")
            c.execute('UPDATE pieces SET xtimezone = NULL')      # les entrées existantes n'ont pas de fuseau (vide par défaut)
        if 'field_order' in cols:                                  # ordre par entrée abandonné : l'ordre des champs est universel
            c.execute('ALTER TABLE pieces DROP COLUMN field_order')    # SQLite >= 3.35
    _ok = True
