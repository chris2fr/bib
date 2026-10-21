"""Passage entre une entrée du fr.json « remonté » et une ligne de la table `pieces` (voir json2db.py).

Une entrée est un dict ordonné :
  key, ENTRYTYPE, champs BibTeX (BIB, valeurs de base), autres champs (extra), markdown,
  bibtex = {champ: valeur} (surcharges du .bib ; None supprime le champ du .bib).
L'ordre des champs est le même pour toutes les entrées (voir order_entry) : d'abord les champs BibTeX, puis les autres champs,
chaque groupe dans l'ordre donné par BIBMAN_ORDER_BIBTEX / BIBMAN_ORDER_OTHER (noms séparés par des virgules), les champs non
listés suivant par ordre alphabétique ; sans paramètre, tout est alphabétique. Aucun ordre n'est stocké."""
import json
import os

BIB = ['title', 'author', 'abstract', 'note', 'number', 'organization', 'type', 'xtype', 'keywords', 'xtheme',
       'date', 'year', 'language', 'xcounter', 'xacronym', 'shorthand', 'url', 'howpublished', 'xtime', 'xdatetime', 'xtimezone',
       'file', 'publisher', 'urldate', 'annote', 'volume', 'medium', 'issue', 'collection', 'archive', 'edition',
       'xduplicate', 'shorthand2']
BIBSET = frozenset(BIB)
SPECIAL = frozenset(['key', 'ENTRYTYPE', 'markdown', 'bibtex'])
_TAIL = ('markdown', 'bibtex')
_override = None        # (liste BibTeX, liste autres) posée par set_order(), sinon variables d'environnement


def set_order(bibtex=None, other=None):
    """Impose l'ordre des champs (listes de noms) ; set_order() sans argument revient aux variables d'environnement."""
    global _override
    _override = None if bibtex is None and other is None else (list(bibtex or []), list(other or []))


def field_order(group):
    """Noms listés par le paramètre du groupe ('bibtex' ou 'other'), dans l'ordre voulu ; [] si non défini."""
    if _override is not None:
        return _override[0 if group == 'bibtex' else 1]
    raw = os.environ.get('BIBMAN_ORDER_BIBTEX' if group == 'bibtex' else 'BIBMAN_ORDER_OTHER', '')
    return [n.strip() for n in raw.split(',') if n.strip()]


def sort_fields(names, group):
    """Noms triés : d'abord ceux du paramètre (dans son ordre), puis les autres par ordre alphabétique."""
    rank = {n: i for i, n in enumerate(field_order(group))}
    return sorted(names, key=lambda n: (rank.get(n, len(rank)), n.lower(), n))


def order_entry(entry):
    """Entrée avec l'ordre universel : key, ENTRYTYPE, champs BibTeX, autres champs, markdown, bibtex."""
    keys = [k for k in ('key', 'ENTRYTYPE') if k in entry]
    keys += sort_fields([k for k in entry if k in BIBSET], 'bibtex')
    keys += sort_fields([k for k in entry if k not in SPECIAL and k not in BIBSET], 'other')
    keys += [k for k in _TAIL if k in entry]
    return {k: entry[k] for k in keys}


def _dumps(v):
    return json.dumps(v, ensure_ascii=False)


def entry_to_row(entry):
    """Entrée -> dict de colonnes de `pieces` (id, entrytype, BIB..., extra, bibtex, markdown)."""
    entry = order_entry(entry)
    extra = {k: v for k, v in entry.items() if k not in SPECIAL and k not in BIBSET}
    row = {'id': entry['key'], 'entrytype': entry.get('ENTRYTYPE')}
    for f in BIB:
        row[f] = entry.get(f)
    row['extra'] = _dumps(extra)
    row['bibtex'] = _dumps(entry['bibtex']) if entry.get('bibtex') else None
    row['markdown'] = entry.get('markdown') or ''
    return row


def row_to_entry(row):
    """Ligne de `pieces` -> entrée, dans l'ordre universel des champs ; les champs vides sont absents."""
    extra = json.loads(row['extra'] or '{}')
    values = {'key': row['id'], 'ENTRYTYPE': row['entrytype'], 'markdown': row['markdown'],
              'bibtex': json.loads(row['bibtex']) if row['bibtex'] else None}
    values.update({f: row[f] for f in BIB})
    values.update(extra)
    entry = {k: v for k, v in values.items() if v not in (None, '') and k != 'bibtex'}
    if values['bibtex']:
        entry['bibtex'] = values['bibtex']
    return order_entry(entry)


def put_field(entry, name, value):
    """Affecte un champ; un nouveau champ s'insère avant markdown/bibtex, qui restent en fin d'entrée."""
    if name in entry:
        entry[name] = value
        return
    tail = [(k, entry.pop(k)) for k in [k for k in entry if k in _TAIL]]
    entry[name] = value
    entry.update(tail)


def set_bibtex(entry, overrides):
    """Définit (ou retire, si vide) les surcharges du .bib."""
    if overrides:
        entry['bibtex'] = dict(overrides)
    else:
        entry.pop('bibtex', None)


def check_braces(key, field, value):
    """Lève ValueError si les accolades de value sont déséquilibrées (db2bib échouerait)."""
    depth = 0
    for ch in value:
        if ch == '{':
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth < 0:
                break
    if depth != 0:
        raise ValueError(f'{key}: {field}: accolades déséquilibrées')
